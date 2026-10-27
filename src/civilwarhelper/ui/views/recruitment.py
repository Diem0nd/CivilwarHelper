import discord

from civilwarhelper import db as database
from civilwarhelper.config.positions import LOL_COMBINED_POSITION_LABELS, LOL_STANDARD_POSITIONS, VAL_COMBINED_POSITION_LABELS, VAL_STANDARD_POSITIONS
from civilwarhelper.services.balance import assign_teams_with_balance
from civilwarhelper.ui.formatting.board import format_matchmaking_board
from civilwarhelper.ui.formatting.inhouse import format_inhouse_session_detail
from civilwarhelper.ui.formatting.profile import _format_short_position


class OrganizerAddRegisteredSelect(discord.ui.Select):
    def __init__(self, unjoined_profiles: list[dict], remaining_slots: int, custom_id: str | None = None):
        options: list[discord.SelectOption] = []
        for prof in unjoined_profiles[:25]:
            uid = prof["discord_user_id"]
            name = prof.get("discord_nickname") or prof.get("riot_game_name") or str(uid)
            riot_label = f"{prof.get('riot_game_name', '')}#{prof.get('riot_tagline', '')}"
            pos = _format_short_position(prof.get("main_position"), "lol")
            tier = prof.get("custom_tier") or prof.get("solo_tier") or prof.get("competitive_tier") or "UNRANKED"
            options.append(
                discord.SelectOption(
                    label=f"{name} ({riot_label})"[:100],
                    description=f"티어: {tier} | 주포지션: {pos}"[:100],
                    value=str(uid),
                )
            )

        if not options or remaining_slots <= 0:
            options = [discord.SelectOption(label="추가 가능한 미참가 등록 서버원이 없습니다", value="none")]
            super().__init__(
                placeholder="➕ [주최자 전용] 추가 가능한 미참가 서버원이 없습니다",
                min_values=1,
                max_values=1,
                options=options,
                disabled=True,
                row=2,
                custom_id=custom_id,
            )
        else:
            super().__init__(
                placeholder=f"➕ [주최자 전용] 등록된 서버원 직접 참가시키기 ({len(options)}명 대기 중)",
                min_values=1,
                max_values=min(len(options), max(1, remaining_slots)),
                options=options,
                disabled=False,
                row=2,
                custom_id=custom_id,
            )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseRecruitmentView = self.view  # type: ignore
        await interaction.response.defer()

        session = database.get_inhouse_session_by_id(view.guild_id, view.session_id)
        if not session:
            await interaction.followup.send("이미 종료된 내전입니다.", ephemeral=True)
            return

        if interaction.user.id != session["organizer_user_id"]:
            await interaction.followup.send("주최자만 다른 서버원을 직접 추가할 수 있습니다.", ephemeral=True)
            return

        added_count = 0
        for val in self.values:
            if val == "none":
                continue
            ok, _ = database.add_inhouse_participant(view.guild_id, view.session_id, int(val))
            if ok:
                added_count += 1

        await view.refresh_lobby_message(interaction)
        await interaction.followup.send(f"✅ 선택한 서버원 {added_count}명을 내전 명단에 추가했습니다.", ephemeral=True)


class RecruitmentKickParticipantSelect(discord.ui.Select):
    def __init__(self, participants: list[dict], custom_id: str | None = None):
        options: list[discord.SelectOption] = []
        for idx, p in enumerate(participants[:25], start=1):
            uid = p["discord_user_id"]
            name = p.get("discord_nickname") or p.get("riot_game_name") or str(uid)
            riot_tag = p.get("riot_tagline") or ""
            riot_str = f"{p.get('riot_game_name', '')}#{riot_tag}" if riot_tag else "미등록"
            primary_pos = _format_short_position(p.get("preferred_position") or p.get("main_position"), "lol")

            options.append(
                discord.SelectOption(
                    label=f"{idx}. {name} ({primary_pos})"[:100],
                    description=f"Riot: {riot_str}"[:100],
                    value=str(uid),
                )
            )

        disabled = len(options) == 0
        if disabled:
            options.append(discord.SelectOption(label="현재 참가자가 없습니다", value="none"))

        super().__init__(
            placeholder="🚫 [주최자 전용] 내전에서 제외할 참가자 선택...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=disabled,
            row=3,
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseRecruitmentView = self.view  # type: ignore
        await interaction.response.defer()

        session = database.get_inhouse_session_by_id(view.guild_id, view.session_id)
        if session is None:
            await interaction.followup.send("이미 종료된 내전입니다.", ephemeral=True)
            return

        is_organizer = interaction.user.id == session["organizer_user_id"]
        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild
        if not (is_organizer or is_admin):
            await interaction.followup.send("내전 주최자 또는 서버 관리자만 인원을 제외할 수 있습니다.", ephemeral=True)
            return

        if self.values[0] == "none":
            return

        target_user_id = int(self.values[0])
        success, message = database.remove_inhouse_participant(view.guild_id, view.session_id, target_user_id)
        if not success:
            await interaction.followup.send(message, ephemeral=True)
            return

        await view.refresh_lobby_message(interaction)
        await interaction.followup.send(f"✅ <@{target_user_id}> 님을 내전 참가자 목록에서 제외했습니다.", ephemeral=True)


class RecruitmentTeamGroupSelect(discord.ui.Select):
    def __init__(self, participants: list[dict], team_groups: list[list[int]], custom_id: str | None = None):
        options: list[discord.SelectOption] = []

        if team_groups:
            options.append(
                discord.SelectOption(
                    label="🔄 모든 같은 팀 묶기 예약 초기화",
                    description="현재 설정된 같은 팀 묶기 예약을 모두 해제합니다.",
                    value="CLEAR_GROUPS",
                )
            )

        user_group_label: dict[int, str] = {}
        for g_idx, g in enumerate(team_groups):
            g_letter = chr(ord("A") + g_idx)
            for uid in g:
                user_group_label[int(uid)] = f"[그룹 {g_letter}] "

        for idx, p in enumerate(participants[:24], start=1):
            uid = int(p["discord_user_id"])
            name = p.get("discord_nickname") or p.get("riot_game_name") or str(uid)
            primary_pos = _format_short_position(p.get("preferred_position") or p.get("main_position"), "lol")
            g_prefix = user_group_label.get(uid, "")

            options.append(
                discord.SelectOption(
                    label=f"{idx}. {g_prefix}{name} ({primary_pos})"[:100],
                    description="2명 이상 함께 선택하면 같은 팀으로 묶입니다.",
                    value=str(uid),
                )
            )

        disabled = len(participants) < 2 and not team_groups
        if not options:
            options.append(discord.SelectOption(label="참가자가 2명 이상일 때 묶기가 가능합니다", value="none"))

        super().__init__(
            placeholder="🤝 [주최자 전용] 같은 팀으로 묶을 참가자 2~5명 선택 (또는 초기화)...",
            min_values=1,
            max_values=min(5, len(options)) if not disabled else 1,
            options=options,
            disabled=disabled,
            row=4,
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseRecruitmentView = self.view  # type: ignore
        await interaction.response.defer()

        session = database.get_inhouse_session_by_id(view.guild_id, view.session_id)
        if session is None:
            await interaction.followup.send("이미 종료된 내전입니다.", ephemeral=True)
            return

        if interaction.user.id != session["organizer_user_id"]:
            await interaction.followup.send("같은 팀 묶기 예약은 **내전 주최자**만 설정할 수 있습니다.", ephemeral=True)
            return

        if "CLEAR_GROUPS" in self.values:
            database.clear_session_team_groups(view.guild_id, view.session_id)
            await view.refresh_lobby_message(interaction)
            await interaction.followup.send("🔄 모든 같은 팀 묶기 예약을 초기화했습니다.", ephemeral=True)
            return

        selected_uids = [int(v) for v in self.values if v != "none"]
        if len(selected_uids) < 2:
            await interaction.followup.send(
                "⚠️ 같은 팀으로 묶으려면 드롭다운에서 **한 번에 2명 이상(최대 5명)**을 함께 체크해 주세요!",
                ephemeral=True,
            )
            return

        ok, msg, _ = database.add_or_update_session_team_group(view.guild_id, view.session_id, selected_uids)
        if not ok:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            return

        await view.refresh_lobby_message(interaction)
        mentions = ", ".join(f"<@{u}>" for u in selected_uids)
        await interaction.followup.send(f"🤝 {mentions} 님을 같은 팀으로 예약했습니다!", ephemeral=True)


class SelfPositionCombinedSelect(discord.ui.Select):
    def __init__(self, game: str, custom_id: str | None = None):
        pos_list = LOL_COMBINED_POSITION_LABELS if game == "lol" else VAL_COMBINED_POSITION_LABELS

        options = [discord.SelectOption(label=f"주 포지션: {lbl}", value=f"MAIN:{val}") for val, lbl in pos_list]
        options += [discord.SelectOption(label=f"부 포지션: {lbl}", value=f"SUB:{val}") for val, lbl in pos_list]
        options.append(discord.SelectOption(label="부 포지션: 선택안함 (초기화)", value="SUB:NONE"))

        super().__init__(
            placeholder="🎯 내 주 포지션 / 부 포지션 설정 (주+부 동시 선택 가능)...",
            min_values=1,
            max_values=2,
            options=options,
            row=1,
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view: InhouseRecruitmentView = self.view  # type: ignore

        chosen_mains = [v.split(":", 1)[1] for v in self.values if v.startswith("MAIN:")]
        chosen_subs = [v.split(":", 1)[1] for v in self.values if v.startswith("SUB:")]

        if len(chosen_mains) > 1 or len(chosen_subs) > 1:
            await interaction.followup.send("⚠️ 주 포지션 1개와 부 포지션 1개씩만 선택해 주세요.", ephemeral=True)
            return

        if chosen_mains:
            success, msg = database.update_inhouse_participant_position(
                view.guild_id, view.session_id, interaction.user.id, chosen_mains[0]
            )
            if not success:
                await interaction.followup.send(msg, ephemeral=True)
                return

        if chosen_subs:
            sub_val = None if chosen_subs[0] == "NONE" else chosen_subs[0]
            success, msg = database.update_inhouse_participant_sub_position(
                view.guild_id, view.session_id, interaction.user.id, sub_val
            )
            if not success:
                await interaction.followup.send(msg, ephemeral=True)
                return

        await view.refresh_lobby_message(interaction)


class InhouseRecruitmentView(discord.ui.View):
    def __init__(self, guild_id: int, session: dict, participant_count: int = 0):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.session = session
        self.session_id = session["session_id"]
        self.game = session["game"]
        self.participant_count = participant_count
        self.rebuild_components()

    def rebuild_components(self):
        self.clear_items()
        is_full = self.participant_count >= 10
        sid = self.session_id

        join_btn = discord.ui.Button(
            label="🎮 내전 참가" if not is_full else "🔒 모집 마감 (10/10)",
            style=discord.ButtonStyle.success if not is_full else discord.ButtonStyle.secondary,
            disabled=is_full,
            row=0,
            custom_id=f"inhouse:{sid}:join",
        )
        join_btn.callback = self.join_callback
        self.add_item(join_btn)

        leave_btn = discord.ui.Button(
            label="🚪 참가 취소",
            style=discord.ButtonStyle.danger,
            row=0,
            custom_id=f"inhouse:{sid}:leave",
        )
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

        start_btn = discord.ui.Button(
            label=f"🚀 내전 시작 ({self.participant_count}/10)",
            style=discord.ButtonStyle.primary if is_full else discord.ButtonStyle.secondary,
            disabled=(self.participant_count != 10),
            row=0,
            custom_id=f"inhouse:{sid}:start",
        )
        start_btn.callback = self.start_callback
        self.add_item(start_btn)

        cancel_btn = discord.ui.Button(
            label="🛑 내전 모집 취소",
            style=discord.ButtonStyle.danger,
            row=0,
            custom_id=f"inhouse:{sid}:cancel",
        )
        cancel_btn.callback = self.cancel_recruitment_callback
        self.add_item(cancel_btn)

        fill_btn = discord.ui.Button(
            label="🧪 10명 자동 채우기",
            style=discord.ButtonStyle.secondary,
            disabled=is_full,
            row=0,
            custom_id=f"inhouse:{sid}:autofill",
        )
        fill_btn.callback = self.auto_fill_callback
        self.add_item(fill_btn)

        self.add_item(SelfPositionCombinedSelect(self.game, custom_id=f"inhouse:{sid}:position"))

        unjoined = (
            database.get_unjoined_registered_profiles(self.guild_id, sid, self.game)
            if not is_full
            else []
        )
        self.add_item(
            OrganizerAddRegisteredSelect(
                unjoined_profiles=unjoined,
                remaining_slots=max(0, 10 - self.participant_count),
                custom_id=f"inhouse:{sid}:add",
            )
        )

        current_participants = database.get_inhouse_participants_with_profiles(self.guild_id, sid)
        self.add_item(RecruitmentKickParticipantSelect(participants=current_participants, custom_id=f"inhouse:{sid}:kick"))

        team_groups = database.get_session_team_groups(self.guild_id, sid)
        self.add_item(
            RecruitmentTeamGroupSelect(
                participants=current_participants,
                team_groups=team_groups,
                custom_id=f"inhouse:{sid}:groups",
            )
        )

    async def refresh_lobby_message(self, interaction: discord.Interaction):
        session = database.get_inhouse_session_by_id(self.guild_id, self.session_id)
        if session is None:
            closed_text = format_inhouse_session_detail(self.session, [], is_closed=True, closed_reason="모집 종료")
            if interaction.message is not None:
                await interaction.message.edit(content=closed_text, view=None)
            else:
                await interaction.edit_original_response(content=closed_text, view=None)
            return

        self.session = session
        participants = database.get_inhouse_participants_with_profiles(self.guild_id, self.session_id)
        self.participant_count = len(participants)
        self.rebuild_components()

        text = format_inhouse_session_detail(session, participants)
        mentions = discord.AllowedMentions(users=True)
        if interaction.message is not None:
            await interaction.message.edit(content=text, view=self, allowed_mentions=mentions)
        else:
            await interaction.edit_original_response(content=text, view=self, allowed_mentions=mentions)

    async def join_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        success, message = database.add_inhouse_participant(self.guild_id, self.session_id, interaction.user.id)
        if not success:
            await interaction.followup.send(message, ephemeral=True)
            return
        await self.refresh_lobby_message(interaction)

    async def leave_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        success, message = database.remove_inhouse_participant(self.guild_id, self.session_id, interaction.user.id)
        if not success:
            await interaction.followup.send(message, ephemeral=True)
            return
        await self.refresh_lobby_message(interaction)

    async def cancel_recruitment_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        session = database.get_inhouse_session_by_id(self.guild_id, self.session_id)
        if session is None:
            await interaction.edit_original_response(content="🛑 **[모집 종료]** 이미 종료된 내전입니다.", view=None)
            return

        is_organizer = interaction.user.id == session["organizer_user_id"]
        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild
        if not (is_organizer or is_admin):
            await interaction.followup.send(
                "내전 모집 취소는 **주최자**(또는 서버 관리자)만 할 수 있습니다.",
                ephemeral=True,
            )
            return

        participants = database.get_inhouse_participants_with_profiles(self.guild_id, self.session_id)
        database.delete_inhouse_session(self.guild_id, self.session_id)

        closed_text = format_inhouse_session_detail(
            session=session,
            participants=participants,
            is_closed=True,
            closed_reason="모집 취소 및 종료",
        )
        await interaction.edit_original_response(
            content=closed_text,
            view=None,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def start_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        session = database.get_inhouse_session_by_id(self.guild_id, self.session_id)
        if session is None:
            await interaction.followup.send("이미 종료된 내전입니다.", ephemeral=True)
            return

        if interaction.user.id != session["organizer_user_id"]:
            await interaction.followup.send("내전 시작은 **주최자**만 누를 수 있습니다.", ephemeral=True)
            return

        participants = database.get_inhouse_participants_with_profiles(self.guild_id, self.session_id)
        if len(participants) != 10:
            await interaction.followup.send(
                f"참가자가 10명이어야 시작할 수 있습니다. (현재 {len(participants)}/10)",
                ephemeral=True,
            )
            return

        positions = LOL_STANDARD_POSITIONS if session["game"] == "lol" else VAL_STANDARD_POSITIONS
        balance_settings = database.get_session_balance_settings(self.guild_id, self.session_id, positions)

        occupied_slots: set[tuple[str, str]] = set()
        assigned_members = []
        unassigned_members = []

        for p in participants:
            team = p.get("assigned_team")
            pos = p.get("assigned_position")
            if team in ("RED", "BLUE") and pos in positions and (team, pos) not in occupied_slots:
                occupied_slots.add((team, pos))
                assigned_members.append(p)
            else:
                unassigned_members.append(p)

        # 기존 배정 인원이 7명 이상 남아있으면 빈 슬롯만 채움
        if len(assigned_members) >= 7:
            all_slots = [(team, pos) for team in ("RED", "BLUE") for pos in positions]
            empty_slots = [slot for slot in all_slots if slot not in occupied_slots]

            if unassigned_members and empty_slots:
                assignments = [
                    {
                        "discord_user_id": p.get("discord_user_id", p.get("user_id")),
                        "user_id": p.get("discord_user_id", p.get("user_id")),
                        "assigned_team": p["assigned_team"],
                        "assigned_position": p["assigned_position"],
                    }
                    for p in assigned_members
                ]

                remaining_slots = list(empty_slots)
                remaining_members = list(unassigned_members)

                for p in list(remaining_members):
                    desired_raw = p.get("desired_position") or p.get("main_position") or ""
                    desired_list = [x.strip() for x in str(desired_raw).split(",") if x.strip()]
                    matched_slot = None
                    for want_pos in desired_list:
                        matched_slot = next((s for s in remaining_slots if s[1].lower() == want_pos.lower()), None)
                        if matched_slot:
                            break

                    if matched_slot:
                        uid = p.get("discord_user_id", p.get("user_id"))
                        assignments.append(
                            {
                                "discord_user_id": uid,
                                "user_id": uid,
                                "assigned_team": matched_slot[0],
                                "assigned_position": matched_slot[1],
                            }
                        )
                        remaining_slots.remove(matched_slot)
                        remaining_members.remove(p)

                for p, slot in zip(remaining_members, remaining_slots):
                    uid = p.get("discord_user_id", p.get("user_id"))
                    assignments.append(
                        {
                            "discord_user_id": uid,
                            "user_id": uid,
                            "assigned_team": slot[0],
                            "assigned_position": slot[1],
                        }
                    )

                database.save_team_assignments(self.guild_id, self.session_id, assignments)
        else:
            team_groups = database.get_session_team_groups(self.guild_id, self.session_id)
            assignments = assign_teams_with_balance(
                participants=participants,
                game=session["game"],
                balance_settings=balance_settings,
                team_groups=team_groups,
            )
            database.save_team_assignments(self.guild_id, self.session_id, assignments)

        database.set_inhouse_match_started(self.guild_id, self.session_id, True)
        updated_participants = database.get_inhouse_participants_with_profiles(self.guild_id, self.session_id)

        await interaction.edit_original_response(
            content=format_matchmaking_board(session, updated_participants, balance_settings),
            view=InhouseTeamManageView(self.guild_id, session, updated_participants, balance_settings),
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def auto_fill_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        session = database.get_inhouse_session_by_id(self.guild_id, self.session_id)
        if session is None:
            await interaction.followup.send("이미 종료된 내전입니다.", ephemeral=True)
            return

        if interaction.user.id != session["organizer_user_id"]:
            await interaction.followup.send("10명 자동 채우기는 **주최자**만 사용할 수 있습니다.", ephemeral=True)
            return

        success, msg = database.auto_fill_inhouse_to_ten(self.guild_id, self.session_id)
        if not success:
            await interaction.followup.send(msg, ephemeral=True)
            return

        await self.refresh_lobby_message(interaction)
        await interaction.followup.send(f"✅ {msg}", ephemeral=True)


# 순환참조 방지용 하단 import
from civilwarhelper.ui.views.team_manage import InhouseTeamManageView  # noqa: E402
