import discord

from civilwarhelper import db as database
from civilwarhelper.config.positions import LOL_STANDARD_POSITIONS, POSITION_SHORT_LABEL, VAL_STANDARD_POSITIONS
from civilwarhelper.services.balance import assign_teams_with_balance
from civilwarhelper.services.match_stats import _record_participants_match_stats
from civilwarhelper.ui.formatting.board import format_matchmaking_board
from civilwarhelper.ui.formatting.inhouse import format_inhouse_session_detail
from civilwarhelper.ui.formatting.profile import _format_short_position


class BalancePositionSelect(discord.ui.Select):
    def __init__(self, positions: list[str], selected_pos: str):
        options = [
            discord.SelectOption(
                label=f"포지션 선택: {pos}",
                value=pos,
                default=(pos == selected_pos),
            )
            for pos in positions
        ]
        super().__init__(
            placeholder="밸런스를 조절할 포지션을 선택하세요...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        view.selected_position = self.values[0]
        view.refresh_items()
        await interaction.response.edit_message(view=view)


class SetBalanceModeButton(discord.ui.Button):
    def __init__(self, mode_label: str, is_active: bool):
        super().__init__(
            label=f"레드 기준: {mode_label}",
            style=discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary,
            row=1,
        )
        self.mode_label = mode_label

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        view.balance_settings[view.selected_position] = self.mode_label
        database.save_session_balance_settings(view.guild_id, view.session_id, view.balance_settings)

        participants = database.get_inhouse_participants_with_profiles(view.guild_id, view.session_id)
        new_assignments = assign_teams_with_balance(
            participants=participants,
            game=view.session["game"],
            balance_settings=view.balance_settings,
        )
        database.save_team_assignments(view.guild_id, view.session_id, new_assignments)

        view.participants = database.get_inhouse_participants_with_profiles(view.guild_id, view.session_id)
        view.refresh_items()

        await interaction.response.edit_message(
            content=format_matchmaking_board(view.session, view.participants, view.balance_settings),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class FreeParticipantSwapSelect(discord.ui.Select):
    def __init__(self, participants: list[dict]):
        team_order = {"RED": 0, "BLUE": 1}
        pos_order = {
            "Top": 0, "Jungle": 1, "Mid": 2, "Bot": 3, "Bottom": 3, "ADC": 3, "AD carry": 3, "Support": 4,
            "Duelist": 0, "Initiator": 1, "Controller": 2, "Sentinel": 3, "Flex": 4,
        }

        def sort_key(p: dict) -> tuple[int, int, str]:
            team = str(p.get("team_side") or p.get("assigned_team") or "").upper()
            pos = str(p.get("assigned_position") or p.get("primary_position") or "")
            name = str(p.get("discord_nickname") or p.get("riot_game_name") or "")
            return team_order.get(team, 99), pos_order.get(pos, 99), name

        options: list[discord.SelectOption] = []
        for p in sorted(participants, key=sort_key)[:25]:
            uid = p["discord_user_id"]
            team_side = str(p.get("team_side") or p.get("assigned_team") or "미배정").upper()
            team_icon = "🟥 RED" if team_side == "RED" else ("🟦 BLUE" if team_side == "BLUE" else "⬜ 미배정")
            pos = p.get("assigned_position") or p.get("primary_position") or "미정"
            name = p.get("discord_nickname") or p.get("riot_game_name") or str(uid)
            riot_tag = f"{p.get('riot_game_name', '')}#{p.get('riot_tagline', '')}"

            options.append(
                discord.SelectOption(
                    label=f"{team_icon} | [{pos}] {name}"[:100],
                    description=f"Riot: {riot_tag}"[:100],
                    value=str(uid),
                )
            )

        super().__init__(
            placeholder="🔀 자유 스왑: 맞바꿀 두 선수를 선택하세요 (2명 선택)",
            min_values=2,
            max_values=2,
            options=options,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        database.swap_two_participants_team(view.session_id, int(self.values[0]), int(self.values[1]))
        view.participants = database.get_inhouse_participants_with_profiles(view.guild_id, view.session_id)
        view.refresh_items()

        await interaction.response.edit_message(
            content=format_matchmaking_board(view.session, view.participants, view.balance_settings),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class QuickLaneSwapButton(discord.ui.Button):
    def __init__(self, position_name: str):
        self.position_name = position_name
        short_label = POSITION_SHORT_LABEL.get(position_name, _format_short_position(position_name, "lol"))
        super().__init__(
            label=f"🔄 {short_label} 스왑",
            style=discord.ButtonStyle.secondary,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        lane_players = [p for p in view.participants if p.get("assigned_position") == self.position_name]
        if len(lane_players) != 2:
            await interaction.response.send_message(
                f"{self.position_name} 포지션에 배정된 두 선수를 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        database.swap_two_participants_team(
            view.session_id,
            lane_players[0]["discord_user_id"],
            lane_players[1]["discord_user_id"],
        )
        view.participants = database.get_inhouse_participants_with_profiles(view.guild_id, view.session_id)
        view.refresh_items()

        await interaction.response.edit_message(
            content=format_matchmaking_board(view.session, view.participants, view.balance_settings),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class RecordMatchResultButton(discord.ui.Button):
    def __init__(self, is_red_win: bool, current_set: int, disabled: bool = False):
        super().__init__(
            label=f"🏆 {current_set}세트 {'레드' if is_red_win else '블루'} 승",
            style=discord.ButtonStyle.danger if is_red_win else discord.ButtonStyle.primary,
            disabled=disabled,
            row=0,
        )
        self.winner_side = "RED" if is_red_win else "BLUE"

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        database.record_set_winner(view.guild_id, view.session_id, self.winner_side)
        _record_participants_match_stats(view.session, view.participants, self.winner_side)

        view.refresh_items()
        await interaction.response.edit_message(
            content=format_matchmaking_board(view.session, view.participants, view.balance_settings),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class FinishInhouseMatchButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🛑 내전 종료", style=discord.ButtonStyle.danger, row=0)

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        is_organizer = interaction.user.id == view.organizer_user_id
        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild
        if not (is_organizer or is_admin):
            await interaction.response.send_message(
                "내전 종료는 주최자(또는 서버 관리자)만 할 수 있습니다.",
                ephemeral=True,
            )
            return

        state = database.get_fearless_state(view.guild_id, view.session_id)
        current_set = state["current_set"]
        done = [int(k) for k in state.get("results", {}) if str(k).isdigit()]
        final_set_count = max(done) if done else 0

        final_board = format_matchmaking_board(view.session, view.participants, view.balance_settings)
        final_board = final_board.replace(
            f"현재 진행도 : {current_set}세트",
            f"진행 결과 : {final_set_count}세트",
        )
        final_board = f"🏁 **[내전 종료]**\n{final_board}"

        database.delete_inhouse_session(view.guild_id, view.session_id)
        await interaction.response.edit_message(
            content=final_board,
            view=None,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class ReturnToRecruitmentButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="↩️ 모집창으로 돌아가기", style=discord.ButtonStyle.secondary, row=0)

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        is_organizer = interaction.user.id == view.organizer_user_id
        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild
        if not (is_organizer or is_admin):
            await interaction.response.send_message(
                "모집창으로 돌아가기는 주최자(또는 서버 관리자)만 할 수 있습니다.",
                ephemeral=True,
            )
            return

        session = database.get_inhouse_session_by_id(view.guild_id, view.session_id)
        if session is None:
            await interaction.response.send_message("이미 종료된 내전입니다.", ephemeral=True)
            return

        participants = database.get_inhouse_participants_with_profiles(view.guild_id, view.session_id)
        database.set_inhouse_match_started(view.guild_id, view.session_id, False)

        await interaction.response.edit_message(
            content=format_inhouse_session_detail(session, participants),
            view=InhouseRecruitmentView(view.guild_id, session, len(participants)),
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class SwapWholeTeamSideButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="🔄 레드 ↔ 블루 팀 전체 진영 변경",
            style=discord.ButtonStyle.success,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        database.swap_entire_red_blue_teams(view.guild_id, view.session_id)
        view.balance_settings = database.get_session_balance_settings(view.guild_id, view.session_id, view.positions)
        view.participants = database.get_inhouse_participants_with_profiles(view.guild_id, view.session_id)
        view.refresh_items()

        await interaction.response.edit_message(
            content=format_matchmaking_board(view.session, view.participants, view.balance_settings),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class InhouseTeamManageView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        session: dict,
        participants: list[dict],
        balance_settings: dict[str, str],
    ):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.session = session
        self.session_id = session["session_id"]
        self.organizer_user_id = session["organizer_user_id"]
        self.participants = participants
        self.balance_settings = balance_settings
        self.positions = LOL_STANDARD_POSITIONS if session["game"] == "lol" else VAL_STANDARD_POSITIONS
        self.refresh_items()

    def refresh_items(self):
        self.clear_items()

        state = database.get_fearless_state(self.guild_id, self.session_id)
        current_set = state["current_set"]
        game = self.session["game"]
        already_recorded = str(current_set) in state["sets"]
        need_fearless_first = state["enabled"] and (current_set >= 2) and (not already_recorded)

        def _add(item: discord.ui.Item, row_idx: int):
            item.row = row_idx
            item.custom_id = f"inhouse-match:{self.session_id}:{len(self.children)}"
            self.add_item(item)

        # row 0: 팀명 / 모집창 복귀 / 종료
        _add(SetTeamNameButton(), 0)
        _add(ReturnToRecruitmentButton(), 0)
        _add(FinishInhouseMatchButton(), 0)

        # row 1: 세트 승패 기록 / 진영 전체 스왑
        _add(RecordMatchResultButton(True, current_set, disabled=need_fearless_first), 1)
        _add(RecordMatchResultButton(False, current_set, disabled=need_fearless_first), 1)
        _add(SwapWholeTeamSideButton(), 1)

        # row 2: 라인별 1:1 스왑
        for pos in self.positions:
            _add(QuickLaneSwapButton(pos), 2)

        # row 3: 2명 자유 스왑
        if len(self.participants) >= 2:
            _add(FreeParticipantSwapSelect(self.participants), 3)

        # row 4: 피어리스 / 맵 밴
        _add(ToggleFearlessButton(state["enabled"], game=game), 4)
        if state["enabled"]:
            _add(
                OpenFearlessModalButton(
                    current_set=current_set,
                    can_input=(current_set >= 2),
                    already_recorded=already_recorded,
                    game=game,
                ),
                4,
            )
        if state["sets"]:
            _add(ClearFearlessButton(game=game), 4)


# 순환참조 방지용 하단 import
from civilwarhelper.ui.views.fearless import ClearFearlessButton, OpenFearlessModalButton, ToggleFearlessButton  # noqa: E402
from civilwarhelper.ui.views.recruitment import InhouseRecruitmentView  # noqa: E402
from civilwarhelper.ui.views.team_name import SetTeamNameButton  # noqa: E402
