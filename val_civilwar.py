import itertools
import discord
from discord import app_commands

import database
from match_common import (
    POSITION_SHORT_LABEL,
    SESSION_CUSTOM_TEAM_NAMES,
    VAL_COMBINED_POSITION_LABELS,
    VAL_STANDARD_POSITIONS,
    extract_player_tier_and_score,
    format_tier_with_custom_emoji,
    get_balance_badge,
    get_custom_emoji,
    record_participants_match_stats,
)

VAL_POSITION_CHOICES = [
    app_commands.Choice(name="타격대 (Duelist)", value="Duelist"),
    app_commands.Choice(name="척후대 (Initiator)", value="Initiator"),
    app_commands.Choice(name="전략가 (Controller)", value="Controller"),
    app_commands.Choice(name="감시자 (Sentinel)", value="Sentinel"),
    app_commands.Choice(name="올라운더 (Flex)", value="Flex"),
]


def _get_val_position_fit_cost(player: dict, target_pos: str) -> float:
    pref = str(player.get("preferred_position") or player.get("main_position") or "")
    sub = str(player.get("sub_position") or player.get("profile_sub_position") or "")
    if pref in ("Flex", "Fill") or target_pos == "Flex":
        return 0.0
    if pref == target_pos:
        return 0.0
    if pref == "Duel_Init" and target_pos in ("Duelist", "Initiator"):
        return 0.3
    if pref == "Ctrl_Sent" and target_pos in ("Controller", "Sentinel"):
        return 0.3
    if sub == target_pos or sub in ("Flex", "Fill"):
        return 1.2
    if sub == "Duel_Init" and target_pos in ("Duelist", "Initiator"):
        return 1.5
    if sub == "Ctrl_Sent" and target_pos in ("Controller", "Sentinel"):
        return 1.5
    return 4.5


def _best_val_role_assignment_for_five(team_players: list[dict]) -> tuple[float, dict[str, dict]]:
    best_cost = float("inf")
    best_map: dict[str, dict] = {}
    for perm in itertools.permutations(team_players, 5):
        cost = 0.0
        cur_map: dict[str, dict] = {}
        for pos, p in zip(VAL_STANDARD_POSITIONS, perm):
            cost += _get_val_position_fit_cost(p, pos)
            cur_map[pos] = p
        if cost < best_cost:
            best_cost = cost
            best_map = cur_map
    return best_cost, best_map


def assign_val_teams_with_balance(
    participants: list[dict],
    balance_settings: dict[str, str] | None = None,
    team_groups: list[list[int]] | None = None,
) -> list[dict]:
    if len(participants) < 10:
        return []

    players = participants[:10]
    balance_settings = balance_settings or {pos: "황밸" for pos in VAL_STANDARD_POSITIONS}
    team_groups = team_groups or []

    score_cache: dict[int, float] = {}
    for idx, p in enumerate(players):
        _, sc = extract_player_tier_and_score(p, "valorant")
        score_cache[idx] = sc

    best_total_penalty = float("inf")
    best_assignments: list[dict] = []

    indices = list(range(10))
    for red_indices in itertools.combinations(indices, 5):
        red_set = set(red_indices)
        blue_indices = [i for i in indices if i not in red_set]

        red_uids = {
            int(players[i].get("discord_user_id", players[i].get("user_id")))
            for i in red_indices
        }
        blue_uids = {
            int(players[i].get("discord_user_id", players[i].get("user_id")))
            for i in blue_indices
        }

        group_violated = False
        for grp in team_groups:
            grp_set = {int(u) for u in grp}
            active_grp = grp_set.intersection(red_uids.union(blue_uids))
            if len(active_grp) >= 2:
                if not (active_grp.issubset(red_uids) or active_grp.issubset(blue_uids)):
                    group_violated = True
                    break
        if group_violated:
            continue

        red_team = [players[i] for i in red_indices]
        blue_team = [players[i] for i in blue_indices]

        red_role_cost, red_pos_map = _best_val_role_assignment_for_five(red_team)
        blue_role_cost, blue_pos_map = _best_val_role_assignment_for_five(blue_team)

        red_sum = sum(score_cache[i] for i in red_indices)
        blue_sum = sum(score_cache[i] for i in blue_indices)
        team_diff_penalty = abs(red_sum - blue_sum) * 1.6

        lane_penalty = 0.0
        for pos in VAL_STANDARD_POSITIONS:
            rp = red_pos_map[pos]
            bp = blue_pos_map[pos]
            _, r_sc = extract_player_tier_and_score(rp, "valorant")
            _, b_sc = extract_player_tier_and_score(bp, "valorant")
            diff = r_sc - b_sc
            mode = balance_settings.get(pos, "황밸")

            if mode == "윗밸":
                if diff < 1.5:
                    lane_penalty += (1.5 - diff) * 3.0
            elif mode == "아랫밸":
                if diff > -1.5:
                    lane_penalty += (diff + 1.5) * 3.0
            else:
                lane_penalty += abs(diff) * 1.1

        total_penalty = (red_role_cost + blue_role_cost) * 3.5 + team_diff_penalty + lane_penalty
        if total_penalty < best_total_penalty:
            best_total_penalty = total_penalty
            cur_result: list[dict] = []
            for pos in VAL_STANDARD_POSITIONS:
                rp = red_pos_map[pos]
                bp = blue_pos_map[pos]
                r_uid = int(rp.get("discord_user_id", rp.get("user_id")))
                b_uid = int(bp.get("discord_user_id", bp.get("user_id")))
                cur_result.append(
                    {
                        "discord_user_id": r_uid,
                        "user_id": r_uid,
                        "assigned_team": "RED",
                        "assigned_position": pos,
                    }
                )
                cur_result.append(
                    {
                        "discord_user_id": b_uid,
                        "user_id": b_uid,
                        "assigned_team": "BLUE",
                        "assigned_position": pos,
                    }
                )
            best_assignments = cur_result

    if not best_assignments and team_groups:
        return assign_val_teams_with_balance(participants, balance_settings, [])

    return best_assignments


def format_val_lobby_message(session: dict, participants: list[dict]) -> str:
    guild_id = session["guild_id"]
    session_id = session["session_id"]
    civilwar_no = session["civilwar_number"]
    organizer_id = session["organizer_user_id"]
    status = session.get("status", "open")

    civilwar_emoji = get_custom_emoji("ACivilwar", "🔫")
    playing_emoji = get_custom_emoji("APlaying", "🔥")
    thinking_emoji = get_custom_emoji("AThinking", "⏳")

    status_badge = (
        f"{playing_emoji} **모집 중**"
        if status == "open"
        else "🔒 **종료됨**"
    )

    lines = [
        f"{civilwar_emoji} **VALORANT 내전 모집 (`match #{civilwar_no}`)**",
        f"• **상태**: {status_badge}  |  **주최자**: <@{organizer_id}>",
        f"• **현재 인원**: `{len(participants)} / 10명`",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if not participants:
        lines.append(f"{thinking_emoji} *아직 참가자가 없습니다. 아래 **[참가하기]** 버튼을 눌러 참가해 보세요!*")
    else:
        for idx, p in enumerate(participants, start=1):
            uid = p.get("discord_user_id", p.get("user_id"))
            riot_id = (
                f"{p.get('riot_game_name')}#{p.get('riot_tagline')}"
                if p.get("riot_game_name")
                else "미등록"
            )
            comp_t = format_tier_with_custom_emoji(p.get("competitive_tier") or "Unranked", "valorant")
            pref_pos = p.get("preferred_position") or p.get("main_position") or "Flex"
            sub_pos = p.get("sub_position") or p.get("profile_sub_position") or "Flex"
            pref_short = POSITION_SHORT_LABEL.get(pref_pos, VAL_COMBINED_POSITION_LABELS.get(pref_pos, pref_pos))
            sub_short = POSITION_SHORT_LABEL.get(sub_pos, VAL_COMBINED_POSITION_LABELS.get(sub_pos, sub_pos))

            lines.append(
                f"`{idx:02d}.` <@{uid}> (`{riot_id}`) — "
                f"경쟁전: {comp_t} | 희망 역할군: **{pref_short}** (부: {sub_short})"
            )

    team_groups = database.get_session_team_groups(guild_id, session_id)
    if team_groups:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        grp_texts = []
        for g_idx, grp in enumerate(team_groups, start=1):
            mentions = ", ".join(f"<@{u}>" for u in grp)
            grp_texts.append(f"**그룹 {g_idx}**: {mentions}")
        lines.append("🤝 **같은 팀 묶기 설정**: " + " / ".join(grp_texts))

    balance_map = database.get_session_balance_settings(
        guild_id, session_id, VAL_STANDARD_POSITIONS
    )
    non_default = [
        f"{POSITION_SHORT_LABEL.get(pos, pos)}:{mode}"
        for pos, mode in balance_map.items()
        if mode != "황밸"
    ]
    if non_default:
        lines.append("⚖️ **역할군 밸런스 설정(RED 기준)**: " + ", ".join(non_default))

    return "\n".join(lines)


async def sync_val_lobby_message_if_exists(
    bot: discord.Client,
    session: dict,
    fallback_channel: discord.abc.Messageable | None = None,
) -> None:
    channel_id = session.get("channel_id")
    message_id = session.get("message_id")
    if not message_id:
        return

    channel = bot.get_channel(channel_id) if channel_id else fallback_channel
    if channel is None and channel_id:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            channel = fallback_channel
    if channel is None:
        return

    try:
        msg = await channel.fetch_message(int(message_id))
        participants = database.get_inhouse_participants_with_profiles(
            session["guild_id"], session["session_id"]
        )
        new_content = format_val_lobby_message(session, participants)
        new_view = (
            ValRecruitmentView(session=session, participant_count=len(participants))
            if session.get("status") == "open"
            else None
        )
        await msg.edit(
            content=new_content,
            view=new_view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    except Exception:
        pass


class ValParticipantPositionSelect(discord.ui.Select):
    def __init__(self, session: dict, is_sub: bool = False):
        self.session = session
        self.is_sub = is_sub
        kind_label = "부 역할군" if is_sub else "주 역할군"
        pos_labels = {
            "Duelist": "타격대 (Duelist)",
            "Initiator": "척후대 (Initiator)",
            "Controller": "전략가 (Controller)",
            "Sentinel": "감시자 (Sentinel)",
            "Flex": "올라운더 (Flex)",
        }
        options = [
            discord.SelectOption(
                label=pos_labels[pos],
                value=pos,
                description=f"내 {kind_label}을 {pos_labels[pos]}으로 변경합니다.",
            )
            for pos in VAL_STANDARD_POSITIONS
        ]
        super().__init__(
            placeholder=f"🎯 내 {kind_label} 변경하기 (참가자 전용)",
            min_values=1,
            max_values=1,
            options=options,
            row=1 if not is_sub else 2,
        )

    async def callback(self, interaction: discord.Interaction):
        chosen = self.values[0]
        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        lose_emoji = get_custom_emoji("ALose", "❌")

        if self.is_sub:
            ok, msg = database.update_participant_positions(
                guild_id=guild_id,
                session_id=session_id,
                discord_user_id=interaction.user.id,
                sub_position=chosen,
            )
        else:
            ok, msg = database.update_participant_positions(
                guild_id=guild_id,
                session_id=session_id,
                discord_user_id=interaction.user.id,
                preferred_position=chosen,
            )

        if not ok:
            await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
            return

        participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
        new_content = format_val_lobby_message(self.session, participants)
        new_view = ValRecruitmentView(session=self.session, participant_count=len(participants))
        await interaction.response.edit_message(
            content=new_content,
            view=new_view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class ValAddParticipantView(discord.ui.View):
    def __init__(self, session: dict, candidates: list[dict], lobby_message: discord.Message | None):
        super().__init__(timeout=120)
        self.session = session
        self.lobby_message = lobby_message

        options = []
        for c in candidates[:25]:
            uid = c["discord_user_id"]
            nick = c.get("discord_nickname") or str(uid)
            riot_str = f"{c.get('riot_game_name', '')}#{c.get('riot_tagline', '')}"
            tier_str = c.get("competitive_tier") or "Unranked"
            options.append(
                discord.SelectOption(
                    label=f"{nick} ({riot_str})"[:100],
                    value=str(uid),
                    description=f"경쟁전: {tier_str} | 주 역할군: {c.get('main_position', 'Flex')}"[:100],
                )
            )

        select = discord.ui.Select(
            placeholder="내전에 추가할 등록 유저를 선택하세요 (최대 10명)",
            min_values=1,
            max_values=min(len(options), 10),
            options=options,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        selected_ids = [int(v) for v in interaction.data["values"]]

        added = []
        failed = []
        for uid in selected_ids:
            ok, msg = database.add_inhouse_participant(guild_id, session_id, uid)
            if ok:
                added.append(f"<@{uid}>")
            else:
                failed.append(f"<@{uid}> ({msg})")

        await sync_val_lobby_message_if_exists(interaction.client, self.session, interaction.channel)

        res_lines = []
        if added:
            res_lines.append(f"✅ **추가 완료**: {', '.join(added)}")
        if failed:
            res_lines.append(f"⚠️ **추가 실패**: {', '.join(failed)}")

        await interaction.response.edit_message(content="\n".join(res_lines), view=None)


class ValRemoveParticipantView(discord.ui.View):
    def __init__(self, session: dict, participants: list[dict]):
        super().__init__(timeout=120)
        self.session = session

        options = []
        for p in participants[:25]:
            uid = p.get("discord_user_id", p.get("user_id"))
            nick = p.get("discord_nickname") or str(uid)
            riot_str = f"{p.get('riot_game_name', '')}#{p.get('riot_tagline', '')}"
            options.append(
                discord.SelectOption(
                    label=f"{nick} ({riot_str})"[:100],
                    value=str(uid),
                    description=f"희망 역할군: {p.get('preferred_position', 'Flex')}"[:100],
                )
            )

        select = discord.ui.Select(
            placeholder="내전에서 제외할 참가자를 선택하세요",
            min_values=1,
            max_values=len(options),
            options=options,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        selected_ids = [int(v) for v in interaction.data["values"]]

        removed = []
        for uid in selected_ids:
            ok, _ = database.remove_inhouse_participant(guild_id, session_id, uid)
            if ok:
                removed.append(f"<@{uid}>")

        await sync_val_lobby_message_if_exists(interaction.client, self.session, interaction.channel)
        await interaction.response.edit_message(
            content=f"✅ **참가자 제외 완료**: {', '.join(removed) if removed else '없음'}",
            view=None,
        )


class ValReplaceParticipantView(discord.ui.View):
    def __init__(self, session: dict, participants: list[dict], candidates: list[dict]):
        super().__init__(timeout=120)
        self.session = session
        self.old_user_id: int | None = None
        self.new_user_id: int | None = None

        old_opts = [
            discord.SelectOption(
                label=f"{p.get('discord_nickname') or p.get('discord_user_id')}"[:100],
                value=str(p.get("discord_user_id", p.get("user_id"))),
                description=f"현재 참가자 ({p.get('riot_game_name', '')}#{p.get('riot_tagline', '')})"[:100],
            )
            for p in participants[:25]
        ]
        new_opts = [
            discord.SelectOption(
                label=f"{c.get('discord_nickname') or c.get('discord_user_id')}"[:100],
                value=str(c["discord_user_id"]),
                description=f"대기 유저 ({c.get('riot_game_name', '')}#{c.get('riot_tagline', '')})"[:100],
            )
            for c in candidates[:25]
        ]

        self.old_select = discord.ui.Select(placeholder="1️⃣ 내전에서 뺄 참가자 선택", options=old_opts, row=0)
        self.new_select = discord.ui.Select(placeholder="2️⃣ 새로 투입할 유저 선택", options=new_opts, row=1)
        self.confirm_btn = discord.ui.Button(label="교체 실행", style=discord.ButtonStyle.primary, row=2)

        self.old_select.callback = self._on_old
        self.new_select.callback = self._on_new
        self.confirm_btn.callback = self._on_confirm

        self.add_item(self.old_select)
        self.add_item(self.new_select)
        self.add_item(self.confirm_btn)

    async def _on_old(self, interaction: discord.Interaction):
        self.old_user_id = int(self.old_select.values[0])
        await interaction.response.defer()

    async def _on_new(self, interaction: discord.Interaction):
        self.new_user_id = int(self.new_select.values[0])
        await interaction.response.defer()

    async def _on_confirm(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self.old_user_id or not self.new_user_id:
            await interaction.response.send_message(
                f"{lose_emoji} 뺄 참가자와 새로 투입할 유저를 모두 선택해 주세요.",
                ephemeral=True,
            )
            return

        ok, msg = database.replace_inhouse_participant(
            guild_id=self.session["guild_id"],
            session_id=self.session["session_id"],
            old_user_id=self.old_user_id,
            new_user_id=self.new_user_id,
        )
        if not ok:
            await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
            return

        await sync_val_lobby_message_if_exists(interaction.client, self.session, interaction.channel)
        await interaction.response.edit_message(
            content=f"🔄 <@{self.old_user_id}> ➔ <@{self.new_user_id}> 교체가 완료되었습니다!",
            view=None,
        )


class ValTeamGroupConfigView(discord.ui.View):
    def __init__(self, session: dict, participants: list[dict]):
        super().__init__(timeout=120)
        self.session = session

        options = [
            discord.SelectOption(
                label=f"{p.get('discord_nickname') or p.get('discord_user_id')}"[:100],
                value=str(p.get("discord_user_id", p.get("user_id"))),
                description=f"{p.get('riot_game_name', '')}#{p.get('riot_tagline', '')}"[:100],
            )
            for p in participants[:25]
        ]

        select = discord.ui.Select(
            placeholder="🤝 같은 팀으로 묶을 참가자 선택 (2~5명)",
            min_values=2,
            max_values=min(5, len(options)),
            options=options,
            row=0,
        )
        select.callback = self.select_callback
        self.add_item(select)

        clear_btn = discord.ui.Button(
            label="모든 그룹 해제",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        clear_btn.callback = self.clear_callback
        self.add_item(clear_btn)

    async def select_callback(self, interaction: discord.Interaction):
        user_ids = [int(v) for v in interaction.data["values"]]
        ok, msg, _ = database.add_session_team_group(
            self.session["guild_id"], self.session["session_id"], user_ids
        )
        await sync_val_lobby_message_if_exists(interaction.client, self.session, interaction.channel)
        await interaction.response.edit_message(content=f"🤝 {msg}", view=None)

    async def clear_callback(self, interaction: discord.Interaction):
        database.clear_session_team_groups(self.session["guild_id"], self.session["session_id"])
        await sync_val_lobby_message_if_exists(interaction.client, self.session, interaction.channel)
        await interaction.response.edit_message(
            content="🗑️ 설정된 모든 같은 팀 묶기 그룹을 해제했습니다.",
            view=None,
        )


class ValRecruitmentView(discord.ui.View):
    def __init__(self, session: dict, participant_count: int = 0):
        super().__init__(timeout=None)
        self.session = session
        self.participant_count = participant_count

        join_btn = discord.ui.Button(
            label="참가하기",
            style=discord.ButtonStyle.success,
            disabled=(participant_count >= 10),
            row=0,
        )
        leave_btn = discord.ui.Button(
            label="나가기",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        end_btn = discord.ui.Button(
            label="내전 종료",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        join_btn.callback = self.join_callback
        leave_btn.callback = self.leave_callback
        end_btn.callback = self.end_callback
        self.add_item(join_btn)
        self.add_item(leave_btn)
        self.add_item(end_btn)

        self.add_item(ValParticipantPositionSelect(session, is_sub=False))
        self.add_item(ValParticipantPositionSelect(session, is_sub=True))

        add_btn = discord.ui.Button(label="참가자 추가", style=discord.ButtonStyle.secondary, row=3)
        rem_btn = discord.ui.Button(label="참가자 제외", style=discord.ButtonStyle.secondary, row=3)
        rep_btn = discord.ui.Button(label="참가자 교체", style=discord.ButtonStyle.secondary, row=3)
        grp_btn = discord.ui.Button(label="같은 팀 묶기", style=discord.ButtonStyle.secondary, row=3)

        add_btn.callback = self.add_user_callback
        rem_btn.callback = self.remove_user_callback
        rep_btn.callback = self.replace_user_callback
        grp_btn.callback = self.group_user_callback

        self.add_item(add_btn)
        self.add_item(rem_btn)
        self.add_item(rep_btn)
        self.add_item(grp_btn)

        autofill_btn = discord.ui.Button(
            label="10명 자동 채우기",
            style=discord.ButtonStyle.primary,
            disabled=(participant_count >= 10),
            row=4,
        )
        start_btn = discord.ui.Button(
            label="팀 편성 시작 (10명)",
            style=discord.ButtonStyle.success,
            disabled=(participant_count < 10),
            row=4,
        )
        autofill_btn.callback = self.autofill_callback
        start_btn.callback = self.start_matchmaking_callback
        self.add_item(autofill_btn)
        self.add_item(start_btn)

    def _is_organizer_or_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.session["organizer_user_id"]:
            return True
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(perms and (perms.administrator or perms.manage_guild))

    async def _refresh_this_message(self, interaction: discord.Interaction):
        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        latest_session = database.get_inhouse_session_by_id(guild_id, session_id) or self.session
        self.session = latest_session
        participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
        content = format_val_lobby_message(latest_session, participants)
        new_view = ValRecruitmentView(latest_session, len(participants))
        await interaction.response.edit_message(
            content=content,
            view=new_view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def join_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        ok, msg = database.add_inhouse_participant(
            guild_id=self.session["guild_id"],
            session_id=self.session["session_id"],
            discord_user_id=interaction.user.id,
        )
        if not ok:
            await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
            return
        await self._refresh_this_message(interaction)

    async def leave_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        ok, msg = database.remove_inhouse_participant(
            guild_id=self.session["guild_id"],
            session_id=self.session["session_id"],
            discord_user_id=interaction.user.id,
        )
        if not ok:
            await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
            return
        await self._refresh_this_message(interaction)

    async def end_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 내전 주최자 또는 서버 관리자만 내전을 종료할 수 있습니다.",
                ephemeral=True,
            )
            return

        ok, msg, closed_session = database.close_inhouse_session(
            guild_id=self.session["guild_id"],
            civilwar_number=self.session["civilwar_number"],
            game="valorant",
            requester_user_id=interaction.user.id,
            allow_adminoverride=True,
        )
        if not ok or not closed_session:
            await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
            return

        participants = database.get_inhouse_participants_with_profiles(
            closed_session["guild_id"], closed_session["session_id"]
        )
        content = format_val_lobby_message(closed_session, participants)
        await interaction.response.edit_message(content=content, view=None)

    async def add_user_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 참가자를 직접 추가할 수 있습니다.",
                ephemeral=True,
            )
            return

        candidates = database.get_unjoined_registered_profiles(
            self.session["guild_id"], self.session["session_id"], "valorant"
        )
        if not candidates:
            await interaction.response.send_message(
                f"{lose_emoji} 추가할 수 있는 미참가 등록 유저가 없습니다.",
                ephemeral=True,
            )
            return

        view = ValAddParticipantView(self.session, candidates, interaction.message)
        await interaction.response.send_message(
            "➕ 내전에 추가할 유저를 아래에서 선택해 주세요.",
            view=view,
            ephemeral=True,
        )

    async def remove_user_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 참가자를 제외할 수 있습니다.",
                ephemeral=True,
            )
            return

        participants = database.get_inhouse_participants_with_profiles(
            self.session["guild_id"], self.session["session_id"]
        )
        if not participants:
            await interaction.response.send_message(
                f"{lose_emoji} 현재 참가 중인 유저가 없습니다.",
                ephemeral=True,
            )
            return

        view = ValRemoveParticipantView(self.session, participants)
        await interaction.response.send_message(
            "➖ 내전에서 제외할 참가자를 선택해 주세요.",
            view=view,
            ephemeral=True,
        )

    async def replace_user_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 참가자를 교체할 수 있습니다.",
                ephemeral=True,
            )
            return

        participants = database.get_inhouse_participants_with_profiles(
            self.session["guild_id"], self.session["session_id"]
        )
        candidates = database.get_unjoined_registered_profiles(
            self.session["guild_id"], self.session["session_id"], "valorant"
        )
        if not participants or not candidates:
            await interaction.response.send_message(
                f"{lose_emoji} 교체할 참가자 또는 대기 중인 등록 유저가 부족합니다.",
                ephemeral=True,
            )
            return

        view = ValReplaceParticipantView(self.session, participants, candidates)
        await interaction.response.send_message(
            "🔄 뺄 참가자와 새로 투입할 유저를 차례대로 선택한 뒤 **[교체 실행]**을 눌러 주세요.",
            view=view,
            ephemeral=True,
        )

    async def group_user_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 같은 팀 묶기를 설정할 수 있습니다.",
                ephemeral=True,
            )
            return

        participants = database.get_inhouse_participants_with_profiles(
            self.session["guild_id"], self.session["session_id"]
        )
        if len(participants) < 2:
            await interaction.response.send_message(
                f"{lose_emoji} 최소 2명 이상의 참가자가 있어야 같은 팀으로 묶을 수 있습니다.",
                ephemeral=True,
            )
            return

        view = ValTeamGroupConfigView(self.session, participants)
        await interaction.response.send_message(
            "🤝 같은 팀으로 배정할 참가자(2~5명)를 선택해 주세요.",
            view=view,
            ephemeral=True,
        )

    async def autofill_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 자동 채우기를 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        ok, msg, _ = database.auto_fill_inhouse_to_ten(
            self.session["guild_id"], self.session["session_id"], "valorant"
        )
        if not ok:
            await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
            return

        await self._refresh_this_message(interaction)

    async def start_matchmaking_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 팀 편성을 시작할 수 있습니다.",
                ephemeral=True,
            )
            return

        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
        if len(participants) != 10:
            await interaction.response.send_message(
                f"{lose_emoji} 팀 편성을 시작하려면 정확히 **10명**의 참가자가 필요합니다. (현재 {len(participants)}명)",
                ephemeral=True,
            )
            return

        balance_settings = database.get_session_balance_settings(
            guild_id, session_id, VAL_STANDARD_POSITIONS
        )
        team_groups = database.get_session_team_groups(guild_id, session_id)
        assignments = assign_val_teams_with_balance(
            participants, balance_settings, team_groups
        )
        database.save_team_assignments(guild_id, session_id, assignments)

        updated_participants = database.get_inhouse_participants_with_profiles(
            guild_id, session_id
        )
        board_text = format_val_matchmaking_board(
            self.session, updated_participants, is_finished=False
        )
        manage_view = ValTeamManageView(self.session, updated_participants)

        await interaction.response.edit_message(
            content=board_text,
            view=manage_view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


def format_val_matchmaking_board(
    session: dict,
    participants: list[dict],
    is_finished: bool = False,
) -> str:
    guild_id = session["guild_id"]
    session_id = session["session_id"]

    custom_names = SESSION_CUSTOM_TEAM_NAMES.get((guild_id, session_id))
    if isinstance(custom_names, dict):
        red_team_name = custom_names.get("RED", "RED (공격 진영)")
        blue_team_name = custom_names.get("BLUE", "BLUE (수비 진영)")
    elif isinstance(custom_names, tuple) and len(custom_names) == 2:
        red_team_name, blue_team_name = custom_names
    else:
        red_team_name, blue_team_name = ("RED (공격 진영)", "BLUE (수비 진영)")

    state = database.get_fearless_state(guild_id, session_id)
    results: dict[str, str] = state.get("results", {})
    red_wins = sum(1 for w in results.values() if w == "RED")
    blue_wins = sum(1 for w in results.values() if w == "BLUE")
    completed_sets = len(results)
    current_set = int(state.get("current_set", 1))

    civilwar_emoji = get_custom_emoji("ACivilwar", "🔫")
    playing_emoji = get_custom_emoji("APlaying", "🔥")
    win_emoji = get_custom_emoji("AWin", "🏆")
    chart_emoji = get_custom_emoji("ACharting", "📊")

    header_status = "🏁 경기 종료" if is_finished else "🔫 대진표 및 세트 진행"

    lines = [
        f"{civilwar_emoji} **VALORANT 내전 (`match #{session['civilwar_number']}`) — {header_status}**",
        "",
    ]

    if is_finished:
        lines.append(
            f"{win_emoji} **진행 결과 : {completed_sets}세트 종료** "
            f"(🟥 **{red_team_name}** `{red_wins}` : `{blue_wins}` 🟦 **{blue_team_name}**)"
        )
    else:
        lines.append(
            f"{playing_emoji} **현재 진행도 : {current_set}세트 진행 중** "
            f"(🟥 **{red_team_name}** `{red_wins}` : `{blue_wins}` 🟦 **{blue_team_name}**)"
        )

    if results:
        set_badges = [
            f"`{s_num}세트`: {'🟥 RED 승' if w == 'RED' else '🟦 BLUE 승'}"
            for s_num, w in sorted(results.items(), key=lambda x: int(x[0]))
        ]
        lines.append(f"{chart_emoji} **세트별 기록**: " + " | ".join(set_badges))

    lines.extend([
        "",
        f"🟥 **{red_team_name}**  vs  🟦 **{blue_team_name}**",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ])

    red_by_pos: dict[str, dict] = {}
    blue_by_pos: dict[str, dict] = {}
    for p in participants:
        side = str(p.get("team_side") or p.get("assigned_team") or "").upper()
        pos = str(p.get("assigned_position") or p.get("primary_position") or "")
        if side == "RED":
            red_by_pos[pos] = p
        elif side == "BLUE":
            blue_by_pos[pos] = p

    red_total = 0.0
    blue_total = 0.0

    for pos in VAL_STANDARD_POSITIONS:
        rp = red_by_pos.get(pos)
        bp = blue_by_pos.get(pos)
        short_pos = POSITION_SHORT_LABEL.get(pos, pos)

        if rp:
            r_uid = rp.get("discord_user_id", rp.get("user_id"))
            r_tier, r_score = extract_player_tier_and_score(rp, "valorant")
            red_total += r_score
            r_text = f"<@{r_uid}> ({r_tier})"
        else:
            r_score = 0.0
            r_text = "*미배정*"

        if bp:
            b_uid = bp.get("discord_user_id", bp.get("user_id"))
            b_tier, b_score = extract_player_tier_and_score(bp, "valorant")
            blue_total += b_score
            b_text = f"<@{b_uid}> ({b_tier})"
        else:
            b_score = 0.0
            b_text = "*미배정*"

        badge = get_balance_badge(r_score, b_score)
        lines.append(f"**[{short_pos}]** {badge}")
        lines.append(f"🟥 {r_text}  ⚡  🟦 {b_text}")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"{chart_emoji} **팀 티어 점수 합계**: 🟥 `{red_total:.1f}점` vs 🟦 `{blue_total:.1f}점` "
        f"(차이: `{abs(red_total - blue_total):.1f}점`)"
    )

    return "\n".join(lines)


class ValTeamManageView(discord.ui.View):
    def __init__(self, session: dict, participants: list[dict]):
        super().__init__(timeout=None)
        self.session = session
        self.participants = participants
        self.refresh_items()

    def _is_organizer_or_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.session["organizer_user_id"]:
            return True
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(perms and (perms.administrator or perms.manage_guild))

    def refresh_items(self):
        self.clear_items()

        options = []
        for p in self.participants[:25]:
            uid = p.get("discord_user_id", p.get("user_id"))
            side = str(p.get("team_side") or p.get("assigned_team") or "").upper()
            pos = str(p.get("assigned_position") or p.get("primary_position") or "")
            short_pos = POSITION_SHORT_LABEL.get(pos, pos)
            nick = p.get("discord_nickname") or str(uid)
            options.append(
                discord.SelectOption(
                    label=f"[{side}/{short_pos}] {nick}"[:100],
                    value=str(uid),
                    description=f"{p.get('riot_game_name', '')}#{p.get('riot_tagline', '')}"[:100],
                )
            )

        if len(options) >= 2:
            swap_sel = discord.ui.Select(
                placeholder="🔄 위치를 맞바꿀 선수 2명 선택 (팀/역할군 무관)",
                min_values=2,
                max_values=2,
                options=options,
                row=0,
            )
            swap_sel.callback = self.free_swap_callback
            self.add_item(swap_sel)

        red_win_btn = discord.ui.Button(label="RED 세트 승", style=discord.ButtonStyle.danger, row=1)
        blue_win_btn = discord.ui.Button(label="BLUE 세트 승", style=discord.ButtonStyle.primary, row=1)
        flip_btn = discord.ui.Button(label="진영 전체 스왑", style=discord.ButtonStyle.secondary, row=1)
        reroll_btn = discord.ui.Button(label="밸런스 재편성", style=discord.ButtonStyle.secondary, row=1)

        red_win_btn.callback = self._make_win_cb("RED")
        blue_win_btn.callback = self._make_win_cb("BLUE")
        flip_btn.callback = self.flip_side_callback
        reroll_btn.callback = self.reroll_callback

        self.add_item(red_win_btn)
        self.add_item(blue_win_btn)
        self.add_item(flip_btn)
        self.add_item(reroll_btn)

        back_btn = discord.ui.Button(label="모집 화면으로", style=discord.ButtonStyle.primary, row=2)
        finish_btn = discord.ui.Button(label="내전 종료", style=discord.ButtonStyle.danger, row=2)

        back_btn.callback = self.back_to_lobby_callback
        finish_btn.callback = self.finish_match_callback

        self.add_item(back_btn)
        self.add_item(finish_btn)

    async def _reload_board(self, interaction: discord.Interaction, is_finished: bool = False):
        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        self.participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
        board = format_val_matchmaking_board(self.session, self.participants, is_finished=is_finished)
        if is_finished:
            await interaction.response.edit_message(
                content=board,
                view=None,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        else:
            self.refresh_items()
            await interaction.response.edit_message(
                content=board,
                view=self,
                allowed_mentions=discord.AllowedMentions(users=True),
            )

    async def free_swap_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 선수를 스왑할 수 있습니다.",
                ephemeral=True,
            )
            return

        vals = interaction.data.get("values", [])
        if len(vals) != 2:
            await interaction.response.defer()
            return

        database.swap_two_participants_team(
            session_id=self.session["session_id"],
            user_a_id=int(vals[0]),
            user_b_id=int(vals[1]),
            guild_id=self.session["guild_id"],
        )
        await self._reload_board(interaction)

    def _make_win_cb(self, winner_side: str):
        async def _cb(interaction: discord.Interaction):
            lose_emoji = get_custom_emoji("ALose", "❌")
            win_emoji = get_custom_emoji("AWin", "🏆")
            if not self._is_organizer_or_admin(interaction):
                await interaction.response.send_message(
                    f"{lose_emoji} 주최자 또는 관리자만 세트 승패를 기록할 수 있습니다.",
                    ephemeral=True,
                )
                return

            guild_id = self.session["guild_id"]
            session_id = self.session["session_id"]

            state_before = database.get_fearless_state(guild_id, session_id)
            recorded_set = state_before.get("current_set", 1)

            current_participants = database.get_inhouse_participants_with_profiles(
                guild_id, session_id
            )
            record_participants_match_stats(
                self.session,
                current_participants,
                winner_side,
            )

            database.record_set_winner(guild_id, session_id, winner_side)
            await self._reload_board(interaction)

            side_label = "🟥 RED 팀" if winner_side == "RED" else "🟦 BLUE 팀"
            await interaction.followup.send(
                f"{win_emoji} **`{recorded_set}세트` {side_label} 승리**가 기록되었으며, 참가자 전원에게 발로란트 내전 전적이 반영되었습니다!",
                ephemeral=True,
            )

        return _cb

    async def flip_side_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 진영을 교체할 수 있습니다.",
                ephemeral=True,
            )
            return

        database.swap_entire_red_blue_teams(self.session["guild_id"], self.session["session_id"])
        await self._reload_board(interaction)

    async def reroll_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 밸런스 재편성을 실행할 수 있습니다.",
                ephemeral=True,
            )
            return

        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
        balance_settings = database.get_session_balance_settings(
            guild_id, session_id, VAL_STANDARD_POSITIONS
        )
        team_groups = database.get_session_team_groups(guild_id, session_id)
        assignments = assign_val_teams_with_balance(
            participants, balance_settings, team_groups
        )
        database.save_team_assignments(guild_id, session_id, assignments)
        await self._reload_board(interaction)

    async def back_to_lobby_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 모집 화면으로 돌아갈 수 있습니다.",
                ephemeral=True,
            )
            return

        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
        content = format_val_lobby_message(self.session, participants)
        view = ValRecruitmentView(self.session, len(participants))
        await interaction.response.edit_message(
            content=content,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def finish_match_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 내전을 종료할 수 있습니다.",
                ephemeral=True,
            )
            return

        database.close_inhouse_session(
            guild_id=self.session["guild_id"],
            civilwar_number=self.session["civilwar_number"],
            game="valorant",
            requester_user_id=interaction.user.id,
            allow_adminoverride=True,
        )
        await self._reload_board(interaction, is_finished=True)
