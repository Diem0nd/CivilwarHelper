import discord

from civilwarhelper import db as database
from civilwarhelper.config.games import draft_rule_name
from civilwarhelper.ui.formatting.board import format_matchmaking_board


class FearlessInputModal(discord.ui.Modal):
    def __init__(self, team_view: "InhouseTeamManageView", target_set: int):
        self.is_lol = team_view.session["game"] == "lol"
        title = f"🔥 {target_set}세트 피어리스 챔피언 입력" if self.is_lol else f"🗺️ {target_set}세트 맵 밴 입력"
        super().__init__(title=title)
        self.team_view = team_view
        self.target_set = target_set

        if not self.is_lol:
            self.played_map_input = discord.ui.TextInput(
                label="🗺️ 이전 세트에 플레이한 맵",
                placeholder="예: 어센트",
                style=discord.TextStyle.short,
                required=False,
                max_length=100,
            )
            self.extra_bans_input = discord.ui.TextInput(
                label="🚫 추가 밴 맵 (선택사항, 쉼표 구분)",
                placeholder="예: 바인드, 헤이븐 (없으면 비워두세요)",
                style=discord.TextStyle.short,
                required=False,
                max_length=200,
            )
            self.add_item(self.played_map_input)
            self.add_item(self.extra_bans_input)
            return

        self.red_champs_input = discord.ui.TextInput(
            label="🟥 RED 팀 이전 세트 사용 챔피언 (쉼표/공백 구분)",
            placeholder="예: 아트록스, 리신, 아리, 이즈리얼, 노틸러스",
            style=discord.TextStyle.short,
            required=False,
            max_length=200,
        )
        self.blue_champs_input = discord.ui.TextInput(
            label="🟦 BLUE 팀 이전 세트 사용 챔피언 (쉼표/공백 구분)",
            placeholder="예: 크산테, 비에고, 오리아나, 카이사, 레오나",
            style=discord.TextStyle.short,
            required=False,
            max_length=200,
        )
        self.extra_bans_input = discord.ui.TextInput(
            label="🚫 추가 글로벌 밴 (선택사항, 쉼표 구분)",
            placeholder="예: 오로라, 스몰더 (없으면 비워두세요)",
            style=discord.TextStyle.short,
            required=False,
            max_length=200,
        )

        self.add_item(self.red_champs_input)
        self.add_item(self.blue_champs_input)
        self.add_item(self.extra_bans_input)

    @staticmethod
    def _parse_names(raw_text: str) -> list[str]:
        if not raw_text.strip():
            return []
        items = raw_text.split(",") if "," in raw_text else raw_text.split()
        return [x.strip() for x in items if x.strip()]

    async def on_submit(self, interaction: discord.Interaction):
        view = self.team_view
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        if self.is_lol:
            red_list = self._parse_names(self.red_champs_input.value)
            blue_list = self._parse_names(self.blue_champs_input.value)
            map_list = None
        else:
            red_list, blue_list = [], []
            map_list = self._parse_names(self.played_map_input.value)
        extra_list = self._parse_names(self.extra_bans_input.value)

        if not (red_list or blue_list or map_list or extra_list):
            await interaction.response.send_message(
                "최소 1개 이상의 챔피언을 입력해 주세요." if self.is_lol else "최소 1개 이상의 맵을 입력해 주세요.",
                ephemeral=True,
            )
            return

        database.save_fearless_set_record(
            guild_id=view.guild_id,
            session_id=view.session_id,
            set_number=self.target_set,
            red_champions=red_list,
            blue_champions=blue_list,
            extra_bans=extra_list,
            played_maps=map_list,
        )

        view.refresh_items()
        await interaction.response.edit_message(
            content=format_matchmaking_board(view.session, view.participants, view.balance_settings),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class ToggleFearlessButton(discord.ui.Button):
    def __init__(self, is_enabled: bool, game: str = "lol"):
        icon = "🔥" if game == "lol" else "🗺️"
        super().__init__(
            label=f"{icon} {draft_rule_name(game)}: {'ON' if is_enabled else 'OFF'}",
            style=discord.ButtonStyle.success if is_enabled else discord.ButtonStyle.secondary,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        database.toggle_fearless_mode(view.guild_id, view.session_id)
        view.refresh_items()
        await interaction.response.edit_message(
            content=format_matchmaking_board(view.session, view.participants, view.balance_settings),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class OpenFearlessModalButton(discord.ui.Button):
    def __init__(self, current_set: int, can_input: bool, already_recorded: bool, game: str = "lol"):
        rule = draft_rule_name(game)
        if current_set < 2:
            label = f"🔒 {rule} 입력 (1세트 승패 결정 후 2세트부터 가능)"
            disabled = True
        elif already_recorded:
            label = f"📝 {current_set}세트 {rule} 수정 (입력 완료됨)"
            disabled = not can_input
        else:
            label = f"📝 {current_set}세트 {'피어리스 챔피언' if game == 'lol' else '맵 밴'} 입력"
            disabled = not can_input

        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary if not disabled else discord.ButtonStyle.secondary,
            disabled=disabled,
            row=4,
        )
        self.current_set = current_set

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        state = database.get_fearless_state(view.guild_id, view.session_id)
        if state["current_set"] < 2:
            await interaction.response.send_message(
                f"{draft_rule_name(view.session['game'])}은(는) 1세트 승패 결정 후 **2세트부터** 입력할 수 있습니다.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(FearlessInputModal(team_view=view, target_set=state["current_set"]))


class ClearFearlessButton(discord.ui.Button):
    def __init__(self, game: str = "lol"):
        super().__init__(
            label=f"🗑️ {draft_rule_name(game)} 기록 초기화",
            style=discord.ButtonStyle.danger,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message("이 내전의 주최자만 조작할 수 있습니다.", ephemeral=True)
            return

        database.clear_fearless_records(view.guild_id, view.session_id)
        view.refresh_items()
        await interaction.response.edit_message(
            content=format_matchmaking_board(view.session, view.participants, view.balance_settings),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


# 순환참조 방지용 하단 import
from civilwarhelper.ui.views.team_manage import InhouseTeamManageView  # noqa: E402
