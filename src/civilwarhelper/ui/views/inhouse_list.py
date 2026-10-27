import discord

from civilwarhelper import db as database
from civilwarhelper.ui.formatting.inhouse import format_inhouse_session_detail


class InhouseListSelect(discord.ui.Select):
    def __init__(self, guild_id: int, sessions: list[dict]):
        self.guild_id = guild_id
        options = [
            discord.SelectOption(
                label=f"civilwar #{s['civilwar_number']}",
                description=f"{'LoL' if s['game'] == 'lol' else 'VAL'} | 참가자: {s.get('participant_count', 0)}/10",
                value=str(s["session_id"]),
            )
            for s in sessions[:25]
        ]

        super().__init__(
            placeholder="확인할 내전(civilwar)을 선택하세요...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        session_id = int(self.values[0])
        session = database.get_inhouse_session_by_id(self.guild_id, session_id)

        if session is None:
            await interaction.response.edit_message(
                content="해당 내전을 찾을 수 없거나 이미 종료되었습니다.",
                view=None,
            )
            return

        participants = database.get_inhouse_participants_with_profiles(self.guild_id, session_id)
        await interaction.response.edit_message(
            content=format_inhouse_session_detail(session, participants),
            view=self.view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class InhouseListView(discord.ui.View):
    def __init__(self, guild_id: int, sessions: list[dict]):
        super().__init__(timeout=180)
        self.add_item(InhouseListSelect(guild_id, sessions))
