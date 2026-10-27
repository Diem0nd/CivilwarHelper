import logging

import discord
from discord import app_commands

from civilwarhelper import db as database
from civilwarhelper.commands import admin, general, inhouse, profile
from civilwarhelper.config.positions import LOL_STANDARD_POSITIONS, VAL_STANDARD_POSITIONS
from civilwarhelper.config.settings import DISCORD_TOKEN, TEST_GUILD_IDS
from civilwarhelper.ui.emojis import load_custom_emojis
from civilwarhelper.ui.views.recruitment import InhouseRecruitmentView
from civilwarhelper.ui.views.team_manage import InhouseTeamManageView


class CivilwarHelper(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.command_tree = self.tree

    async def setup_hook(self):
        if TEST_GUILD_IDS:
            for gid in TEST_GUILD_IDS:
                guild = discord.Object(id=gid)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"테스트 서버({gid}) 커맨드 동기화 완료")
        else:
            await self.tree.sync()
            print("글로벌 커맨드 동기화 완료")


bot = CivilwarHelper()


async def restore_lobby_view(guild: discord.Guild, session: dict) -> None:
    # 봇 재시작 시 열려있는 내전 메시지에 버튼/셀렉트 다시 연결
    message_id = session.get("lobby_message_id")
    channel_id = session.get("lobby_channel_id")
    if not message_id or not channel_id:
        return

    session_id = int(session["session_id"])
    participants = database.get_inhouse_participants_with_profiles(guild.id, session_id)

    if session.get("match_started"):
        positions = LOL_STANDARD_POSITIONS if session["game"] == "lol" else VAL_STANDARD_POSITIONS
        view = InhouseTeamManageView(
            guild_id=guild.id,
            session=session,
            participants=participants,
            balance_settings=database.get_session_balance_settings(guild.id, session_id, positions),
        )
    else:
        view = InhouseRecruitmentView(
            guild_id=guild.id,
            session=session,
            participant_count=len(participants),
        )

    bot.add_view(view, message_id=int(message_id))

    try:
        channel = guild.get_channel(int(channel_id)) or await guild.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            return
        msg = await channel.fetch_message(int(message_id))
        await msg.edit(view=view)
    except discord.HTTPException as e:
        logging.debug("로비 뷰 갱신 실패 (session=%s): %s", session_id, e)


async def on_ready():
    await load_custom_emojis(bot)
    if not getattr(bot, "_recruitment_views_registered", False):
        for guild in bot.guilds:
            for session in database.get_active_inhouse_sessions(guild.id):
                try:
                    await restore_lobby_view(guild, session)
                except Exception:
                    logging.exception("로비 뷰 복원 실패 (session=%s)", session.get("session_id"))
        bot._recruitment_views_registered = True
    print(f"로그인 완료: {bot.user}")


async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    orig = getattr(error, "original", error)
    print(f"[명령어 오류] {orig!r}")

    msg = "명령어 처리 중 오류가 발생했습니다. 콘솔 로그를 확인해 주세요."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException as e:
        print(f"오류 응답 전송 실패: {e!r}")


bot.event(on_ready)
bot.tree.error(on_app_command_error)
for _mod in (general, profile, inhouse, admin):
    _mod.setup(bot.tree)


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN 환경변수가 없습니다.")

    database.initialize_database()
    bot.run(DISCORD_TOKEN)
