import itertools
import discord

import database
from match_common import (
    LOL_COMBINED_POSITION_LABELS,
    LOL_POS_SHORT_MAP,
    LOL_STANDARD_POSITIONS,
    POSITION_SHORT_LABEL,
    SESSION_CUSTOM_TEAM_NAMES,
    extract_player_tier_and_score,
    format_position_display,
    format_tier_with_custom_emoji,
    get_balance_badge,
    get_custom_emoji,
    get_participant_highest_tier_info,
    record_participants_match_stats,
)


# =====================================================================
# 1. LoL 내전 모집 로비 포맷팅 및 동기화 헬퍼
# =====================================================================

def format_lol_lobby_message(
    session: dict,
    participants: list[dict] | None = None,
    balance_settings: dict[str, str] | None = None,
) -> str:
    """리그 오브 레전드 내전 모집 로비 메시지 본문을 생성합니다."""
    guild_id = session["guild_id"]
    session_id = session["session_id"]

    if participants is None:
        participants = database.get_inhouse_participants_with_profiles(
            guild_id=guild_id,
            session_id=session_id,
        )

    if balance_settings is None:
        balance_settings = database.get_session_balance_settings(
            guild_id=guild_id,
            session_id=session_id,
            positions=LOL_STANDARD_POSITIONS,
        )

    civilwar_emoji = get_custom_emoji("ACivilwar", "⚔️")
    chart_emoji = get_custom_emoji("ACharting", "📊")
    thinking_emoji = get_custom_emoji("AThinking", "⏳")

    status = str(session.get("status") or "open").lower()
    status_label = "🟢 모집 중" if status == "open" else "🔴 종료됨"

    lines = [
        f"{civilwar_emoji} **League of Legends 내전 모집 (`match #{session['civilwar_number']}`)** [{status_label}]",
        f"• **주최자**: <@{session['organizer_user_id']}>",
        f"• **참가 인원**: **{len(participants)} / 10명**",
        "",
        f"{chart_emoji} **참가자 목록**",
    ]

    if not participants:
        lines.append(f"• *{thinking_emoji} 아직 참가자가 없습니다. 아래 **[참가하기]** 버튼을 눌러 참가해 보세요!*")
    else:
        for idx, p in enumerate(participants, start=1):
            uid = p.get("discord_user_id", p.get("user_id"))
            riot_name = p.get("riot_game_name") or "미등록"
            riot_tag = p.get("riot_tagline") or ""
            riot_str = f"{riot_name}#{riot_tag}" if riot_tag else riot_name

            tier_display, _ = extract_player_tier_and_score(p, "lol")

            pref_raw = p.get("preferred_position") or p.get("main_position")
            sub_raw = p.get("sub_position")
            main_pos_str = format_position_display("lol", pref_raw)
            sub_pos_str = format_position_display("lol", sub_raw) if sub_raw else "선택안함"

            lines.append(
                f"`{idx:02d}.` <@{uid}> ({riot_str}) — {tier_display} | **주**: {main_pos_str} / **부**: {sub_pos_str}"
            )

    # 같은 팀 묶기 그룹 표시
    team_groups = database.get_session_team_groups(guild_id, session_id)
    if team_groups:
        lines.append("")
        lines.append("🤝 **같은 팀 예약 그룹**")
        for g_idx, grp in enumerate(team_groups, start=1):
            mentions = ", ".join(f"<@{u}>" for u in grp)
            lines.append(f"• **그룹 {g_idx}** ({len(grp)}명): {mentions}")

    # 라인별 밸런스 방향 설정 표시
    bal_parts = []
    for pos in LOL_STANDARD_POSITIONS:
        short_pos = POSITION_SHORT_LABEL.get(pos, pos)
        mode = balance_settings.get(pos, "황밸")
        bal_parts.append(f"{short_pos}: **{mode}**")
    lines.append("")
    lines.append(f"⚖️ **라인별 밸런스 설정 (RED 기준)**: {' | '.join(bal_parts)}")

    return "\n".join(lines)


async def sync_lol_lobby_message(bot: discord.Client, session: dict) -> None:
    """저장된 모집 로비 메시지가 있으면 최신 참가자/설정 상태로 업데이트합니다."""
    channel_id = session.get("lobby_channel_id")
    message_id = session.get("lobby_message_id")
    if not channel_id or not message_id:
        return

    channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except Exception:
            return

    if not isinstance(channel, discord.abc.Messageable):
        return

    try:
        message = await channel.fetch_message(int(message_id))
    except Exception:
        return

    guild_id = session["guild_id"]
    session_id = session["session_id"]
    latest_session = database.get_inhouse_session_by_id(guild_id, session_id) or session
    participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
    balance_settings = database.get_session_balance_settings(
        guild_id, session_id, LOL_STANDARD_POSITIONS
    )

    content = format_lol_lobby_message(
        session=latest_session,
        participants=participants,
        balance_settings=balance_settings,
    )

    if str(latest_session.get("status") or "").lower() != "open":
        try:
            await message.edit(content=content, view=None)
        except Exception:
            pass
        return

    view = LolRecruitmentView(
        session=latest_session,
        participant_count=len(participants),
    )
    try:
        await message.edit(
            content=content,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    except Exception:
        pass


async def mark_lol_lobby_closed(bot: discord.Client, session: dict) -> None:
    """내전이 종료되었을 때 로비 메시지의 버튼을 제거하고 종료 상태로 표시합니다."""
    updated_session = dict(session)
    updated_session["status"] = "closed"
    await sync_lol_lobby_message(bot, updated_session)


# =====================================================================
# 2. LoL 팀 자동 밸런스 배정 알고리즘
# =====================================================================

def _get_allowed_lol_positions(raw_pos: str | None) -> list[str]:
    if not raw_pos:
        return LOL_STANDARD_POSITIONS
    if raw_pos in LOL_STANDARD_POSITIONS:
        return [raw_pos]
    mapping = {
        "Top_Jungle": ["Top", "Jungle"],
        "Top_Mid": ["Top", "Mid"],
        "Mid_Jungle": ["Mid", "Jungle"],
        "Bot_Duo": ["AD carry", "Support"],
        "Fill": LOL_STANDARD_POSITIONS,
    }
    return mapping.get(raw_pos, LOL_STANDARD_POSITIONS)


def assign_lol_teams_with_balance(
    participants: list[dict],
    balance_settings: dict[str, str],
    team_groups: list[list[int]] | None = None,
) -> list[dict]:
    """10명의 참가자를 선호 포지션, 같은 팀 그룹, 라인별 밸런스 설정에 맞춰 RED/BLUE 팀으로 최적 배정합니다."""
    players = []
    for p in participants[:10]:
        uid = int(p.get("discord_user_id", p.get("user_id")))
        _, score = get_participant_highest_tier_info(p, "lol")
        main_raw = p.get("preferred_position") or p.get("main_position")
        sub_raw = p.get("sub_position")
        players.append(
            {
                "uid": uid,
                "score": score,
                "main_allowed": _get_allowed_lol_positions(main_raw),
                "sub_allowed": _get_allowed_lol_positions(sub_raw) if sub_raw else [],
                "raw": p,
            }
        )

    valid_groups: list[set[int]] = []
    player_uids = {pl["uid"] for pl in players}
    if team_groups:
        for grp in team_groups:
            filtered = {int(u) for u in grp if int(u) in player_uids}
            if 2 <= len(filtered) <= 5:
                valid_groups.append(filtered)

    def _assign_five_to_positions(team_five: list[dict]) -> tuple[dict[str, dict], float]:
        best_map: dict[str, dict] = {}
        best_Ordered_cost = float("inf")

        for perm in itertools.permutations(team_five):
            cost = 0.0
            pos_map = {}
            for pos, pl in zip(LOL_STANDARD_POSITIONS, perm):
                pos_map[pos] = pl
                if pos in pl["main_allowed"]:
                    if len(pl["main_allowed"]) == 5:
                        cost += 2.0  # Fill
                    else:
                        cost += 0.0
                elif pos in pl["sub_allowed"]:
                    cost += 6.0
                else:
                    cost += 25.0
            if cost < best_Ordered_cost:
                best_Ordered_cost = cost
                best_map = pos_map
        return best_map, best_Ordered_cost

    indices = list(range(len(players)))
    best_total_cost = float("inf")
    best_red_map: dict[str, dict] = {}
    best_blue_map: dict[str, dict] = {}

    for red_idx_tuple in itertools.combinations(indices, 5):
        red_set = set(red_idx_tuple)
        red_team = [players[i] for i in red_idx_tuple]
        blue_team = [players[i] for i in indices if i not in red_set]

        red_uids = {pl["uid"] for pl in red_team}
        blue_uids = {pl["uid"] for pl in blue_team}

        # 같은 팀 묶기 그룹 위반 여부 확인
        group_violated = False
        for grp_set in valid_groups:
            if not (grp_set.issubset(red_uids) or grp_set.issubset(blue_uids)):
                group_violated = True
                break
        if group_violated:
            continue

        red_map, red_pos_cost = _assign_five_to_positions(red_team)
        blue_map, blue_pos_cost = _assign_five_to_positions(blue_team)

        # Red <-> Blue 전체 스왑 케이스도 함께 평가
        for r_map, b_map in ((red_map, blue_map), (blue_map, red_map)):
            balance_cost = 0.0
            red_sum = 0.0
            blue_sum = 0.0

            for pos in LOL_STANDARD_POSITIONS:
                r_score = r_map[pos]["score"]
                b_score = b_map[pos]["score"]
                red_sum += r_score
                blue_sum += b_score

                diff = r_score - b_score
                target_mode = balance_settings.get(pos, "황밸")

                if target_mode == "황밸":
                    balance_cost += abs(diff) * 2.5
                elif target_mode == "윗밸":
                    if diff < 2.0:
                        balance_cost += (2.0 - diff) * 6.0
                    else:
                        balance_cost += (diff - 2.0) * 1.0
                elif target_mode == "아랫밸":
                    if diff > -2.0:
                        balance_cost += (diff + 2.0) * 6.0
                    else:
                        balance_cost += (-2.0 - diff) * 1.0

            total_diff_cost = abs(red_sum - blue_sum) * 1.8
            total_cost = red_pos_cost + blue_pos_cost + balance_cost + total_diff_cost

            if total_cost < best_total_cost:
                best_total_cost = total_cost
                best_red_map = r_map
                best_blue_map = b_map

    # 그룹 제약 때문에 조합이 하나도 없으면 그룹 제약을 완화하여 재시도
    if not best_red_map and valid_groups:
        return assign_lol_teams_with_balance(participants, balance_settings, team_groups=None)

    final_assignments: list[dict] = []
    for pos in LOL_STANDARD_POSITIONS:
        r_pl = best_red_map[pos]
        b_pl = best_blue_map[pos]
        final_assignments.append(
            {
                "discord_user_id": r_pl["uid"],
                "user_id": r_pl["uid"],
                "assigned_team": "RED",
                "assigned_position": pos,
            }
        )
        final_assignments.append(
            {
                "discord_user_id": b_pl["uid"],
                "user_id": b_pl["uid"],
                "assigned_team": "BLUE",
                "assigned_position": pos,
            }
        )

    return final_assignments


# =====================================================================
# 3. LoL 내전 모집 보조 뷰 (포지션 변경, 참가자 관리, 밸런스 설정 등)
# =====================================================================

LOL_POSITION_OPTIONS = [
    ("Top", "탑 (Top)"),
    ("Jungle", "정글 (Jungle)"),
    ("Mid", "미드 (Mid)"),
    ("AD carry", "원딜 (AD carry)"),
    ("Support", "서포터 (Support)"),
    ("Top_Jungle", "탑 / 정글 (Top & Jungle)"),
    ("Top_Mid", "탑 / 미드 (Top & Mid)"),
    ("Mid_Jungle", "미드 / 정글 (Mid & Jungle)"),
    ("Bot_Duo", "바텀 듀오 (AD carry & Support)"),
    ("Fill", "전라인 가능 (All / Fill)"),
]


class LolParticipantPositionSelect(discord.ui.Select):
    def __init__(self, session: dict, is_sub: bool = False):
        self.session = session
        self.is_sub = is_sub

        options = []
        if is_sub:
            options.append(
                discord.SelectOption(
                    label="선택안함 (부 포지션 해제)",
                    value="NONE",
                    description="부 포지션을 설정하지 않습니다.",
                )
            )

        for val, label in LOL_POSITION_OPTIONS:
            options.append(
                discord.SelectOption(
                    label=f"{'부' if is_sub else '주'} 포지션: {label}",
                    value=val,
                )
            )

        super().__init__(
            placeholder="🛡️ 내전 부 포지션 변경" if is_sub else "🎯 내전 주 포지션 변경",
            min_values=1,
            max_values=1,
            options=options,
            row=1 if not is_sub else 2,
        )

    async def callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        choice = self.values[0]

        if self.is_sub:
            sub_val = None if choice == "NONE" else choice
            ok, msg = database.update_inhouse_participant_sub_position(
                guild_id=guild_id,
                session_id=session_id,
                discord_user_id=interaction.user.id,
                sub_position=sub_val,
            )
        else:
            ok, msg = database.update_inhouse_participant_position(
                guild_id=guild_id,
                session_id=session_id,
                discord_user_id=interaction.user.id,
                preferred_position=choice,
            )

        if not ok:
            await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
            return

        participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
        content = format_lol_lobby_message(self.session, participants)
        view = LolRecruitmentView(self.session, len(participants))
        await interaction.response.edit_message(
            content=content,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class LolAddParticipantView(discord.ui.View):
    def __init__(self, session: dict, candidates: list[dict], lobby_message: discord.Message | None):
        super().__init__(timeout=180)
        self.session = session
        self.lobby_message = lobby_message

        options = []
        for prof in candidates[:25]:
            uid = prof["discord_user_id"]
            nick = prof.get("discord_nickname") or str(uid)
            r_name = prof.get("riot_game_name") or ""
            r_tag = prof.get("riot_tagline") or ""
            options.append(
                discord.SelectOption(
                    label=f"{nick}"[:100],
                    value=str(uid),
                    description=f"{r_name}#{r_tag} | 주: {prof.get('main_position', '미정')}"[:100],
                )
            )

        select = discord.ui.Select(
            placeholder="➕ 내전에 추가할 등록 유저 선택 (여러 명 선택 가능)",
            min_values=1,
            max_values=min(len(options), 10),
            options=options,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]

        added_mentions = []
        errors = []
        for val in interaction.data.get("values", []):
            uid = int(val)
            ok, msg = database.add_inhouse_participant(guild_id, session_id, uid)
            if ok:
                added_mentions.append(f"<@{uid}>")
            else:
                errors.append(msg)

        await sync_lol_lobby_message(interaction.client, self.session)

        result_lines = []
        if added_mentions:
            result_lines.append(f"✅ 참가자 추가 완료: {', '.join(added_mentions)}")
        if errors:
            result_lines.append(f"{lose_emoji} 일부 추가 실패: {errors[0]}")

        await interaction.response.edit_message(
            content="\n".join(result_lines) or "처리가 완료되었습니다.",
            view=None,
        )


class LolRemoveParticipantView(discord.ui.View):
    def __init__(self, session: dict, participants: list[dict]):
        super().__init__(timeout=180)
        self.session = session

        options = []
        for p in participants[:25]:
            uid = p.get("discord_user_id", p.get("user_id"))
            nick = p.get("discord_nickname") or str(uid)
            r_name = p.get("riot_game_name") or ""
            options.append(
                discord.SelectOption(
                    label=f"{nick}"[:100],
                    value=str(uid),
                    description=f"Riot: {r_name} | 포지션: {p.get('preferred_position') or '미정'}"[:100],
                )
            )

        select = discord.ui.Select(
            placeholder="➖ 내전에서 제외할 참가자 선택",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        uid = int(interaction.data["values"][0])
        ok, msg = database.remove_inhouse_participant(
            self.session["guild_id"], self.session["session_id"], uid
        )
        if not ok:
            await interaction.response.edit_message(content=f"{lose_emoji} {msg}", view=None)
            return

        await sync_lol_lobby_message(interaction.client, self.session)
        await interaction.response.edit_message(
            content=f"✅ <@{uid}> 님을 내전 참가자 목록에서 제외했습니다.",
            view=None,
        )


class LolReplaceParticipantView(discord.ui.View):
    def __init__(self, session: dict, participants: list[dict], candidates: list[dict]):
        super().__init__(timeout=180)
        self.session = session
        self.old_uid: int | None = None
        self.new_uid: int | None = None

        old_opts = [
            discord.SelectOption(
                label=(p.get("discord_nickname") or str(p.get("discord_user_id")))[:100],
                value=str(p.get("discord_user_id", p.get("user_id"))),
                description=f"현재 참가 중 ({p.get('riot_game_name', '')})"[:100],
            )
            for p in participants[:25]
        ]
        new_opts = [
            discord.SelectOption(
                label=(c.get("discord_nickname") or str(c.get("discord_user_id")))[:100],
                value=str(c.get("discord_user_id")),
                description=f"대기 유저 ({c.get('riot_game_name', '')})"[:100],
            )
            for c in candidates[:25]
        ]

        sel_old = discord.ui.Select(placeholder="1️⃣ 내전에서 뺄 기존 참가자 선택", options=old_opts, row=0)
        sel_new = discord.ui.Select(placeholder="2️⃣ 새로 투입할 등록 유저 선택", options=new_opts, row=1)
        btn_confirm = discord.ui.Button(label="🔄 교체 실행", style=discord.ButtonStyle.primary, row=2)

        sel_old.callback = self._on_old
        sel_new.callback = self._on_new
        btn_confirm.callback = self._on_confirm

        self.add_item(sel_old)
        self.add_item(sel_new)
        self.add_item(btn_confirm)

    async def _on_old(self, interaction: discord.Interaction):
        self.old_uid = int(interaction.data["values"][0])
        await interaction.response.defer()

    async def _on_new(self, interaction: discord.Interaction):
        self.new_uid = int(interaction.data["values"][0])
        await interaction.response.defer()

    async def _on_confirm(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        flip_emoji = get_custom_emoji("AFlip", "🔄")
        if not self.old_uid or not self.new_uid:
            await interaction.response.send_message(
                f"{lose_emoji} 뺄 참가자와 새로 투입할 유저를 모두 선택해 주세요.",
                ephemeral=True,
            )
            return

        ok, msg = database.replace_inhouse_participant(
            self.session["guild_id"],
            self.session["session_id"],
            self.old_uid,
            self.new_uid,
        )
        if not ok:
            await interaction.response.edit_message(content=f"{lose_emoji} {msg}", view=None)
            return

        await sync_lol_lobby_message(interaction.client, self.session)
        await interaction.response.edit_message(
            content=f"{flip_emoji} <@{self.old_uid}> 님을 <@{self.new_uid}> 님으로 교체했습니다!",
            view=None,
        )


class LolTeamGroupConfigView(discord.ui.View):
    def __init__(self, session: dict, participants: list[dict]):
        super().__init__(timeout=180)
        self.session = session

        options = [
            discord.SelectOption(
                label=(p.get("discord_nickname") or str(p.get("discord_user_id")))[:100],
                value=str(p.get("discord_user_id", p.get("user_id"))),
                description=f"{p.get('riot_game_name', '')}#{p.get('riot_tagline', '')}"[:100],
            )
            for p in participants[:25]
        ]

        select = discord.ui.Select(
            placeholder="🤝 같은 팀으로 묶을 참가자 2~5명 선택",
            min_values=2,
            max_values=min(5, len(options)),
            options=options,
            row=0,
        )
        select.callback = self.select_callback
        self.add_item(select)

        clear_btn = discord.ui.Button(
            label="🗑️ 모든 그룹 초기화",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        clear_btn.callback = self.clear_callback
        self.add_item(clear_btn)

    async def select_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        uids = [int(v) for v in interaction.data.get("values", [])]
        ok, msg, _ = database.add_session_team_group(
            self.session["guild_id"], self.session["session_id"], uids
        )
        if not ok:
            await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
            return

        await sync_lol_lobby_message(interaction.client, self.session)
        mentions = ", ".join(f"<@{u}>" for u in uids)
        await interaction.response.edit_message(
            content=f"✅ {msg}\n묶인 인원: {mentions}",
            view=None,
        )

    async def clear_callback(self, interaction: discord.Interaction):
        database.clear_session_team_groups(
            self.session["guild_id"], self.session["session_id"]
        )
        await sync_lol_lobby_message(interaction.client, self.session)
        await interaction.response.edit_message(
            content="✅ 설정된 모든 같은 팀 예약 그룹을 초기화했습니다.",
            view=None,
        )


class LolBalanceConfigView(discord.ui.View):
    def __init__(self, session: dict):
        super().__init__(timeout=180)
        self.session = session
        self.selected_pos = LOL_STANDARD_POSITIONS[0]
        self.settings = database.get_session_balance_settings(
            session["guild_id"], session["session_id"], LOL_STANDARD_POSITIONS
        )
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        options = [
            discord.SelectOption(
                label=f"{pos} (현재: {self.settings.get(pos, '황밸')})",
                value=pos,
                default=(pos == self.selected_pos),
            )
            for pos in LOL_STANDARD_POSITIONS
        ]
        sel = discord.ui.Select(placeholder="라인 선택", options=options, row=0)
        sel.callback = self.on_pos_select
        self.add_item(sel)

        for mode, style in (
            ("황밸", discord.ButtonStyle.primary),
            ("윗밸", discord.ButtonStyle.success),
            ("아랫밸", discord.ButtonStyle.secondary),
        ):
            btn = discord.ui.Button(label=f"{self.selected_pos}: {mode}", style=style, row=1)
            btn.callback = self._make_mode_cb(mode)
            self.add_item(btn)

    async def on_pos_select(self, interaction: discord.Interaction):
        self.selected_pos = interaction.data["values"][0]
        self.rebuild()
        await interaction.response.edit_message(view=self)

    def _make_mode_cb(self, mode: str):
        async def _cb(interaction: discord.Interaction):
            self.settings[self.selected_pos] = mode
            database.save_session_balance_settings(
                self.session["guild_id"], self.session["session_id"], self.settings
            )
            await sync_lol_lobby_message(interaction.client, self.session)
            self.rebuild()
            await interaction.response.edit_message(
                content=f"✅ **{self.selected_pos}** 라인 밸런스가 **{mode}**(으)로 설정되었습니다.",
                view=self,
            )

        return _cb

# =====================================================================
# 4. LoL 내전 모집 메인 뷰 (LolRecruitmentView)
# =====================================================================

class LolRecruitmentView(discord.ui.View):
    def __init__(self, session: dict, participant_count: int = 0):
        super().__init__(timeout=None)
        self.session = session
        self.participant_count = participant_count

        # Row 0: 참가 / 퇴장 / 내전 종료
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

        # Row 1 & 2: 주 포지션 / 부 포지션 변경 드롭다운
        self.add_item(LolParticipantPositionSelect(session, is_sub=False))
        self.add_item(LolParticipantPositionSelect(session, is_sub=True))

        # Row 3: 주최자 관리 버튼 (참가자 추가 / 제외 / 교체 / 같은 팀 묶기 / 라인 밸런스)
        add_btn = discord.ui.Button(label="참가자 추가", style=discord.ButtonStyle.secondary, row=3)
        rem_btn = discord.ui.Button(label="참가자 제외", style=discord.ButtonStyle.secondary, row=3)
        rep_btn = discord.ui.Button(label="참가자 교체", style=discord.ButtonStyle.secondary, row=3)
        grp_btn = discord.ui.Button(label="같은 팀 묶기", style=discord.ButtonStyle.secondary, row=3)
        bal_btn = discord.ui.Button(label="라인 밸런스", style=discord.ButtonStyle.secondary, row=3)

        add_btn.callback = self.add_user_callback
        rem_btn.callback = self.remove_user_callback
        rep_btn.callback = self.replace_user_callback
        grp_btn.callback = self.group_user_callback
        bal_btn.callback = self.balance_config_callback

        self.add_item(add_btn)
        self.add_item(rem_btn)
        self.add_item(rep_btn)
        self.add_item(grp_btn)
        self.add_item(bal_btn)

        # Row 4: 10명 자동 채우기 / 팀 편성 및 경기 시작
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
        content = format_lol_lobby_message(latest_session, participants)
        new_view = LolRecruitmentView(latest_session, len(participants))
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
            game="lol",
            requester_user_id=interaction.user.id,
            allow_adminoverride=True,
        )
        if not ok or not closed_session:
            await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
            return

        participants = database.get_inhouse_participants_with_profiles(
            closed_session["guild_id"], closed_session["session_id"]
        )
        content = format_lol_lobby_message(closed_session, participants)
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
            self.session["guild_id"], self.session["session_id"], "lol"
        )
        if not candidates:
            await interaction.response.send_message(
                f"{lose_emoji} 추가할 수 있는 미참가 등록 유저가 없습니다.",
                ephemeral=True,
            )
            return

        view = LolAddParticipantView(self.session, candidates, interaction.message)
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

        view = LolRemoveParticipantView(self.session, participants)
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
            self.session["guild_id"], self.session["session_id"], "lol"
        )
        if not participants or not candidates:
            await interaction.response.send_message(
                f"{lose_emoji} 교체할 참가자 또는 대기 중인 등록 유저가 부족합니다.",
                ephemeral=True,
            )
            return

        view = LolReplaceParticipantView(self.session, participants, candidates)
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

        view = LolTeamGroupConfigView(self.session, participants)
        await interaction.response.send_message(
            "🤝 같은 팀으로 배정할 참가자(2~5명)를 선택해 주세요.",
            view=view,
            ephemeral=True,
        )

    async def balance_config_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 라인 밸런스를 설정할 수 있습니다.",
                ephemeral=True,
            )
            return

        view = LolBalanceConfigView(self.session)
        await interaction.response.send_message(
            "⚖️ **라인별 밸런스 방향(RED 팀 기준)**을 선택해 주세요.",
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
            self.session["guild_id"], self.session["session_id"], "lol"
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
            guild_id, session_id, LOL_STANDARD_POSITIONS
        )
        team_groups = database.get_session_team_groups(guild_id, session_id)
        assignments = assign_lol_teams_with_balance(
            participants, balance_settings, team_groups
        )
        database.save_team_assignments(guild_id, session_id, assignments)

        updated_participants = database.get_inhouse_participants_with_profiles(
            guild_id, session_id
        )
        board_text = format_lol_matchmaking_board(
            self.session, updated_participants, is_finished=False
        )
        manage_view = LolTeamManageView(self.session, updated_participants)

        await interaction.response.edit_message(
            content=board_text,
            view=manage_view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


# =====================================================================
# 5. LoL 경기 보드 포맷팅 (피어리스 & 라인 매치업 & 팀 이름 추천)
# =====================================================================

def recommend_lol_team_names_by_balance(participants: list[dict]) -> tuple[str, str]:
    red_players = [
        p for p in participants
        if str(p.get("team_side") or p.get("assigned_team") or "").upper() == "RED"
    ]
    blue_players = [
        p for p in participants
        if str(p.get("team_side") or p.get("assigned_team") or "").upper() == "BLUE"
    ]

    red_by_pos = {
        str(p.get("assigned_position") or p.get("primary_position") or ""): p
        for p in red_players
    }
    blue_by_pos = {
        str(p.get("assigned_position") or p.get("primary_position") or ""): p
        for p in blue_players
    }

    red_adv = []
    blue_adv = []
    for pos in LOL_STANDARD_POSITIONS:
        rp = red_by_pos.get(pos)
        bp = blue_by_pos.get(pos)
        if not rp or not bp:
            continue
        _, r_score = extract_player_tier_and_score(rp, "lol")
        _, b_score = extract_player_tier_and_score(bp, "lol")
        diff = r_score - b_score
        short_label = POSITION_SHORT_LABEL.get(pos, pos)
        if diff >= 2.0:
            red_adv.append(short_label)
        elif diff <= -2.0:
            blue_adv.append(short_label)

    red_name = f"RED ({'/'.join(red_adv)} 강세)" if red_adv else "RED (밸런스)"
    blue_name = f"BLUE ({'/'.join(blue_adv)} 강세)" if blue_adv else "BLUE (밸런스)"
    return red_name, blue_name


def format_lol_fearless_section(
    guild_id: int,
    session_id: int,
    red_team_name: str,
    blue_team_name: str,
    is_finished: bool = False,
) -> str:
    state = database.get_fearless_state(guild_id, session_id)
    playing_emoji = get_custom_emoji("APlaying", "🔥")
    win_emoji = get_custom_emoji("AWin", "🏆")
    fearless_emoji = get_custom_emoji("AFearless", "⛔")
    chart_emoji = get_custom_emoji("ACharting", "📊")

    results: dict[str, str] = state.get("results", {})
    red_wins = sum(1 for w in results.values() if w == "RED")
    blue_wins = sum(1 for w in results.values() if w == "BLUE")
    completed_sets = len(results)
    current_set = int(state.get("current_set", 1))

    lines = []
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
        set_badges = []
        for s_num in sorted(results.keys(), key=lambda x: int(x)):
            winner = results[s_num]
            badge = f"🟥 RED 승" if winner == "RED" else f"🟦 BLUE 승"
            set_badges.append(f"`{s_num}세트`: {badge}")
        lines.append(f"{chart_emoji} **세트별 기록**: " + " | ".join(set_badges))

    if state.get("enabled"):
        lines.append("")
        lines.append(f"{fearless_emoji} **피어리스(Fearless) 글로벌 밴 목록**")
        sets_data: dict[str, dict] = state.get("sets", {})
        if not sets_data:
            lines.append("• *아직 기록된 세트별 사용 챔피언이 없습니다.*")
        else:
            for s_num in sorted(sets_data.keys(), key=lambda x: int(x)):
                info = sets_data[s_num]
                r_champs = ", ".join(info.get("red", [])) or "없음"
                b_champs = ", ".join(info.get("blue", [])) or "없음"
                e_champs = ", ".join(info.get("extra", []))
                line = f"• **`{s_num}세트 사용`**: 🟥 {r_champs} / 🟦 {b_champs}"
                if e_champs:
                    line += f" / 🚫 추가 밴: {e_champs}"
                lines.append(line)

    return "\n".join(lines)


def format_lol_matchmaking_board(
    session: dict,
    participants: list[dict],
    is_finished: bool = False,
) -> str:
    guild_id = session["guild_id"]
    session_id = session["session_id"]

    custom_names = SESSION_CUSTOM_TEAM_NAMES.get(session_id)
    if custom_names:
        red_team_name, blue_team_name = custom_names
    else:
        red_team_name, blue_team_name = recommend_lol_team_names_by_balance(participants)

    red_by_pos: dict[str, dict] = {}
    blue_by_pos: dict[str, dict] = {}
    for p in participants:
        side = str(p.get("team_side") or p.get("assigned_team") or "").upper()
        pos = str(p.get("assigned_position") or p.get("primary_position") or "")
        if side == "RED":
            red_by_pos[pos] = p
        elif side == "BLUE":
            blue_by_pos[pos] = p

    civilwar_emoji = get_custom_emoji("ACivilwar", "⚔️")
    header_status = "🏁 경기 종료" if is_finished else "⚔️ 대진표 및 세트 진행"

    lines = [
        f"{civilwar_emoji} **League of Legends 내전 (`match #{session['civilwar_number']}`) — {header_status}**",
        "",
        format_lol_fearless_section(
            guild_id=guild_id,
            session_id=session_id,
            red_team_name=red_team_name,
            blue_team_name=blue_team_name,
            is_finished=is_finished,
        ),
        "",
        f"🟥 **{red_team_name}**  vs  🟦 **{blue_team_name}**",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    red_total = 0.0
    blue_total = 0.0

    for pos in LOL_STANDARD_POSITIONS:
        rp = red_by_pos.get(pos)
        bp = blue_by_pos.get(pos)
        short_pos = POSITION_SHORT_LABEL.get(pos, pos)

        if rp:
            r_uid = rp.get("discord_user_id", rp.get("user_id"))
            r_tier, r_score = extract_player_tier_and_score(rp, "lol")
            red_total += r_score
            r_text = f"<@{r_uid}> ({r_tier})"
        else:
            r_score = 0.0
            r_text = "*미배정*"

        if bp:
            b_uid = bp.get("discord_user_id", bp.get("user_id"))
            b_tier, b_score = extract_player_tier_and_score(bp, "lol")
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
        f"📊 **팀 티어 점수 합계**: 🟥 `{red_total:.1f}점` vs 🟦 `{blue_total:.1f}점` "
        f"(차이: `{abs(red_total - blue_total):.1f}점`)"
    )

    return "\n".join(lines)


# =====================================================================
# 6. LoL 경기 관리 뷰 (LolTeamManageView) 및 모달
# =====================================================================

class LolFearlessModal(discord.ui.Modal, title="⛔ 피어리스 세트 챔피언 입력"):
    set_num_input = discord.ui.TextInput(
        label="세트 번호 (숫자만 입력)",
        placeholder="예: 1",
        default="1",
        max_length=2,
        required=True,
    )
    red_champs_input = discord.ui.TextInput(
        label="🟥 RED 팀 사용 챔피언 (쉼표 또는 공백 구분)",
        placeholder="예: 크산테, 리신, 아리, 이즈리얼, 노틸러스",
        required=True,
        max_length=200,
    )
    blue_champs_input = discord.ui.TextInput(
        label="🟦 BLUE 팀 사용 챔피언 (쉼표 또는 공백 구분)",
        placeholder="예: 잭스, 바위게, 오리아나, 카이사, 레오나",
        required=True,
        max_length=200,
    )
    extra_bans_input = discord.ui.TextInput(
        label="🚫 추가 글로벌 밴 챔피언 (선택)",
        placeholder="없으면 비워두세요.",
        required=False,
        max_length=200,
    )

    def __init__(self, session: dict, default_set: int = 1):
        super().__init__()
        self.session = session
        self.set_num_input.default = str(default_set)

    @staticmethod
    def _parse_names(raw: str) -> list[str]:
        if not raw:
            return []
        replaced = raw.replace(",", " ").replace("/", " ")
        return [tok.strip() for tok in replaced.split() if tok.strip()]

    async def on_submit(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        try:
            set_no = int(self.set_num_input.value.strip())
            if set_no < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                f"{lose_emoji} 세트 번호는 1 이상의 숫자로 입력해 주세요.",
                ephemeral=True,
            )
            return

        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]

        database.save_fearless_set_record(
            guild_id=guild_id,
            session_id=session_id,
            set_number=set_no,
            red_champions=self._parse_names(self.red_champs_input.value),
            blue_champions=self._parse_names(self.blue_champs_input.value),
            extra_bans=self._parse_names(self.extra_bans_input.value),
        )

        participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
        board = format_lol_matchmaking_board(self.session, participants, is_finished=False)
        view = LolTeamManageView(self.session, participants)
        await interaction.response.edit_message(
            content=board,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class LolTeamNameModal(discord.ui.Modal, title="🏷️ RED / BLUE 팀 이름 설정"):
    red_name_input = discord.ui.TextInput(
        label="🟥 RED 팀 이름",
        placeholder="비워두면 밸런스 추천 이름으로 자동 설정됩니다.",
        required=False,
        max_length=40,
    )
    blue_name_input = discord.ui.TextInput(
        label="🟦 BLUE 팀 이름",
        placeholder="비워두면 밸런스 추천 이름으로 자동 설정됩니다.",
        required=False,
        max_length=40,
    )

    def __init__(self, session: dict):
        super().__init__()
        self.session = session

    async def on_submit(self, interaction: discord.Interaction):
        session_id = self.session["session_id"]
        guild_id = self.session["guild_id"]
        participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)

        r_val = self.red_name_input.value.strip()
        b_val = self.blue_name_input.value.strip()

        if not r_val and not b_val:
            SESSION_CUSTOM_TEAM_NAMES.pop(session_id, None)
        else:
            rec_r, rec_b = recommend_lol_team_names_by_balance(participants)
            SESSION_CUSTOM_TEAM_NAMES[session_id] = (r_val or rec_r, b_val or rec_b)

        board = format_lol_matchmaking_board(self.session, participants, is_finished=False)
        view = LolTeamManageView(self.session, participants)
        await interaction.response.edit_message(
            content=board,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class LolTeamManageView(discord.ui.View):
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

        # Row 0: 자유 선수 2명 스왑 드롭다운
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
                placeholder="🔄 위치를 맞바꿀 선수 2명 선택 (팀/포지션 무관)",
                min_values=2,
                max_values=2,
                options=options,
                row=0,
            )
            swap_sel.callback = self.free_swap_callback
            self.add_item(swap_sel)

        # Row 1: 라인별 RED <-> BLUE 1:1 빠른 스왑 버튼 5개
        for pos in LOL_STANDARD_POSITIONS:
            short_pos = POSITION_SHORT_LABEL.get(pos, pos)
            btn = discord.ui.Button(
                label=f"{short_pos} 스왑",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            btn.callback = self._make_lane_swap_cb(pos)
            self.add_item(btn)

        # Row 2: 세트 승패 기록 & 진영 전체 스왑 & 팀 이름 설정 & 재편성
        red_win_btn = discord.ui.Button(label="RED 세트 승", style=discord.ButtonStyle.danger, row=2)
        blue_win_btn = discord.ui.Button(label="BLUE 세트 승", style=discord.ButtonStyle.primary, row=2)
        flip_btn = discord.ui.Button(label="진영 전체 스왑", style=discord.ButtonStyle.secondary, row=2)
        name_btn = discord.ui.Button(label="팀 이름 설정", style=discord.ButtonStyle.secondary, row=2)
        reroll_btn = discord.ui.Button(label="밸런스 재편성", style=discord.ButtonStyle.secondary, row=2)

        red_win_btn.callback = self._make_win_cb("RED")
        blue_win_btn.callback = self._make_win_cb("BLUE")
        flip_btn.callback = self.flip_side_callback
        name_btn.callback = self.team_name_callback
        reroll_btn.callback = self.reroll_callback

        self.add_item(red_win_btn)
        self.add_item(blue_win_btn)
        self.add_item(flip_btn)
        self.add_item(name_btn)
        self.add_item(reroll_btn)

        # Row 3: 피어리스 제어 및 모집 화면 복귀 / 내전 완전 종료
        f_toggle_btn = discord.ui.Button(label="피어리스 ON/OFF", style=discord.ButtonStyle.secondary, row=3)
        f_input_btn = discord.ui.Button(label="피어리스 챔프 입력", style=discord.ButtonStyle.secondary, row=3)
        f_clear_btn = discord.ui.Button(label="피어리스 초기화", style=discord.ButtonStyle.secondary, row=3)
        back_btn = discord.ui.Button(label="모집 화면으로", style=discord.ButtonStyle.primary, row=3)
        finish_btn = discord.ui.Button(label="내전 종료", style=discord.ButtonStyle.danger, row=3)

        f_toggle_btn.callback = self.fearless_toggle_callback
        f_input_btn.callback = self.fearless_input_callback
        f_clear_btn.callback = self.fearless_clear_callback
        back_btn.callback = self.back_to_lobby_callback
        finish_btn.callback = self.finish_match_callback

        self.add_item(f_toggle_btn)
        self.add_item(f_input_btn)
        self.add_item(f_clear_btn)
        self.add_item(back_btn)
        self.add_item(finish_btn)

    async def _reload_board(self, interaction: discord.Interaction, is_finished: bool = False):
        guild_id = self.session["guild_id"]
        session_id = self.session["session_id"]
        self.participants = database.get_inhouse_participants_with_profiles(guild_id, session_id)
        board = format_lol_matchmaking_board(self.session, self.participants, is_finished=is_finished)
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

    def _make_lane_swap_cb(self, pos: str):
        async def _cb(interaction: discord.Interaction):
            lose_emoji = get_custom_emoji("ALose", "❌")
            if not self._is_organizer_or_admin(interaction):
                await interaction.response.send_message(
                    f"{lose_emoji} 주최자 또는 관리자만 라인 스왑을 사용할 수 있습니다.",
                    ephemeral=True,
                )
                return

            red_uid = None
            blue_uid = None
            for p in self.participants:
                p_pos = str(p.get("assigned_position") or p.get("primary_position") or "")
                side = str(p.get("team_side") or p.get("assigned_team") or "").upper()
                if p_pos == pos:
                    if side == "RED":
                        red_uid = int(p.get("discord_user_id", p.get("user_id")))
                    elif side == "BLUE":
                        blue_uid = int(p.get("discord_user_id", p.get("user_id")))

            if not red_uid or not blue_uid:
                await interaction.response.send_message(
                    f"{lose_emoji} 해당 라인({pos})에 배정된 두 선수를 찾을 수 없습니다.",
                    ephemeral=True,
                )
                return

            database.swap_two_participants_team(
                session_id=self.session["session_id"],
                user_a_id=red_uid,
                user_b_id=blue_uid,
                guild_id=self.session["guild_id"],
            )
            await self._reload_board(interaction)

        return _cb

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

            # 글로벌 통산 내전 전적 누적 기록
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
                f"{win_emoji} **`{recorded_set}세트` {side_label} 승리**가 기록되었으며, 참가자 전원에게 내전 통산 전적이 반영되었습니다!",
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

        session_id = self.session["session_id"]
        if session_id in SESSION_CUSTOM_TEAM_NAMES:
            r_name, b_name = SESSION_CUSTOM_TEAM_NAMES[session_id]
            SESSION_CUSTOM_TEAM_NAMES[session_id] = (b_name, r_name)

        database.swap_entire_red_blue_teams(
            self.session["guild_id"], session_id
        )
        await self._reload_board(interaction)

    async def team_name_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 팀 이름을 변경할 수 있습니다.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(LolTeamNameModal(self.session))

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
            guild_id, session_id, LOL_STANDARD_POSITIONS
        )
        team_groups = database.get_session_team_groups(guild_id, session_id)
        assignments = assign_lol_teams_with_balance(
            participants, balance_settings, team_groups
        )
        database.save_team_assignments(guild_id, session_id, assignments)
        await self._reload_board(interaction)

    async def fearless_toggle_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 피어리스 모드를 전환할 수 있습니다.",
                ephemeral=True,
            )
            return

        database.toggle_fearless_mode(self.session["guild_id"], self.session["session_id"])
        await self._reload_board(interaction)

    async def fearless_input_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 피어리스 챔피언을 입력할 수 있습니다.",
                ephemeral=True,
            )
            return

        state = database.get_fearless_state(self.session["guild_id"], self.session["session_id"])
        default_set = max(1, int(state.get("current_set", 1)) - 1)
        await interaction.response.send_modal(
            LolFearlessModal(self.session, default_set=default_set)
        )

    async def fearless_clear_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if not self._is_organizer_or_admin(interaction):
            await interaction.response.send_message(
                f"{lose_emoji} 주최자 또는 관리자만 피어리스 기록을 초기화할 수 있습니다.",
                ephemeral=True,
            )
            return

        database.clear_fearless_records(self.session["guild_id"], self.session["session_id"])
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
        content = format_lol_lobby_message(self.session, participants)
        view = LolRecruitmentView(self.session, len(participants))
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
            game="lol",
            requester_user_id=interaction.user.id,
            allow_adminoverride=True,
        )
        await self._reload_board(interaction, is_finished=True)
