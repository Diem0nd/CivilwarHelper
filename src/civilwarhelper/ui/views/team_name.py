import discord

from civilwarhelper.services.team_names import SESSION_CUSTOM_TEAM_NAMES, recommend_team_names_by_balance
from civilwarhelper.ui.formatting.board import format_matchmaking_board


class TeamNameConfigModal(discord.ui.Modal, title="🏷️ 팀 이름 설정 (자동 추천 포함)"):
    def __init__(
        self,
        parent_view: "InhouseTeamManageView",
        rec_red: str,
        rec_blue: str,
        cur_red: str,
        cur_blue: str,
    ):
        super().__init__()
        self.parent_view = parent_view
        self.rec_red = rec_red
        self.rec_blue = rec_blue

        self.red_name_input = discord.ui.TextInput(
            label=f"🟥 RED 팀 이름 (추천: {rec_red})",
            placeholder=f"비워두면 추천 이름 '{rec_red}'(으)로 설정됩니다.",
            default=cur_red or rec_red,
            required=False,
            max_length=25,
        )
        self.blue_name_input = discord.ui.TextInput(
            label=f"🟦 BLUE 팀 이름 (추천: {rec_blue})",
            placeholder=f"비워두면 추천 이름 '{rec_blue}'(으)로 설정됩니다.",
            default=cur_blue or rec_blue,
            required=False,
            max_length=25,
        )
        self.add_item(self.red_name_input)
        self.add_item(self.blue_name_input)

    async def on_submit(self, interaction: discord.Interaction):
        red_val = self.red_name_input.value.strip() or self.rec_red
        blue_val = self.blue_name_input.value.strip() or self.rec_blue

        SESSION_CUSTOM_TEAM_NAMES[(self.parent_view.guild_id, self.parent_view.session_id)] = {
            "RED": red_val,
            "BLUE": blue_val,
        }

        board_text = format_matchmaking_board(
            session=self.parent_view.session,
            participants=self.parent_view.participants,
            balance_settings=self.parent_view.balance_settings,
        )
        await interaction.response.edit_message(
            content=board_text,
            view=self.parent_view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class SetTeamNameButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="🏷️ 팀 이름 설정/추천",
            style=discord.ButtonStyle.secondary,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view: InhouseTeamManageView = self.view  # type: ignore
        if interaction.user.id != view.organizer_user_id:
            await interaction.response.send_message(
                "❌ 팀 이름 설정은 **내전 주최자**만 할 수 있습니다.",
                ephemeral=True,
            )
            return

        rec_red, rec_blue = recommend_team_names_by_balance(view.session, view.participants)
        existing = SESSION_CUSTOM_TEAM_NAMES.get((view.guild_id, view.session_id), {})

        await interaction.response.send_modal(
            TeamNameConfigModal(
                parent_view=view,
                rec_red=rec_red,
                rec_blue=rec_blue,
                cur_red=existing.get("RED", ""),
                cur_blue=existing.get("BLUE", ""),
            )
        )


# 순환참조 방지용 하단 import
from civilwarhelper.ui.views.team_manage import InhouseTeamManageView  # noqa: E402
