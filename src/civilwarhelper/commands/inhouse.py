import discord
from discord import app_commands

from civilwarhelper import db as database
from civilwarhelper.ui.formatting.inhouse import format_inhouse_session_detail
from civilwarhelper.ui.lobby import mark_lobby_message_closed, resolve_organizer_target_session, sync_lobby_message_if_exists
from civilwarhelper.ui.views.inhouse_list import InhouseListView
from civilwarhelper.ui.views.recruitment import InhouseRecruitmentView


@app_commands.command(
    name="create-inhouse",
    description="League of Legends 또는 VALORANT 내전 모집 로비를 생성합니다.",
)
@app_commands.guild_only()
@app_commands.describe(game="게임을 선택하세요 (League of Legends 또는 VALORANT)")
@app_commands.choices(
    game=[
        app_commands.Choice(name="League of Legends", value="lol"),
        app_commands.Choice(name="VALORANT", value="valorant"),
    ]
)
async def create_inhouse(interaction: discord.Interaction, game: app_commands.Choice[str]):
    if interaction.guild_id is None:
        await interaction.response.send_message("이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    session = database.create_inhouse_session(
        guild_id=interaction.guild_id,
        game=game.value,
        organizer_user_id=interaction.user.id,
    )

    await interaction.response.send_message(
        format_inhouse_session_detail(session, []),
        view=InhouseRecruitmentView(interaction.guild_id, session, participant_count=0),
        allowed_mentions=discord.AllowedMentions(users=True),
    )

    sent_message = await interaction.original_response()
    database.set_session_lobby_message(
        guild_id=interaction.guild_id,
        session_id=session["session_id"],
        channel_id=sent_message.channel.id,
        message_id=sent_message.id,
    )


async def inhouse_add(
    interaction: discord.Interaction,
    member: discord.Member,
    civilwar_number: int | None = None,
):
    if interaction.guild_id is None:
        return

    session, error_msg = resolve_organizer_target_session(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        civilwar_number=civilwar_number,
    )
    if session is None:
        await interaction.response.send_message(error_msg, ephemeral=True)
        return

    success, message = database.add_inhouse_participant(
        guild_id=interaction.guild_id,
        session_id=session["session_id"],
        discord_user_id=member.id,
    )
    if not success:
        await interaction.response.send_message(message, ephemeral=True)
        return

    participants = database.get_inhouse_participants_with_profiles(interaction.guild_id, session["session_id"])
    cw_num = session["civilwar_number"]
    await interaction.response.send_message(
        f"**civilwar #{cw_num}**에 {member.mention} 님이 추가되었습니다. (현재 참가자: {len(participants)}/10)",
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    await sync_lobby_message_if_exists(interaction.guild, session["session_id"])


@app_commands.command(
    name="inhouse-transfer",
    description="내전 주최자 권한을 다른 멤버에게 양도합니다.",
)
@app_commands.guild_only()
@app_commands.describe(
    new_organizer="새 주최자가 될 멤버를 선택하세요.",
    civilwar_number="내전 번호 (예: civilwar #1이면 1 입력)",
)
async def inhouse_transfer(
    interaction: discord.Interaction,
    new_organizer: discord.Member,
    civilwar_number: int | None = None,
):
    if interaction.guild_id is None:
        return

    session, error_msg = resolve_organizer_target_session(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        civilwar_number=civilwar_number,
    )
    if session is None:
        await interaction.response.send_message(error_msg, ephemeral=True)
        return

    database.transfer_inhouse_organizer(
        guild_id=interaction.guild_id,
        session_id=session["session_id"],
        new_organizer_user_id=new_organizer.id,
    )

    cw_num = session["civilwar_number"]
    await interaction.response.send_message(
        f"**civilwar #{cw_num}**의 주최자가 {interaction.user.mention} 님에서 {new_organizer.mention} 님으로 변경되었습니다.",
        allowed_mentions=discord.AllowedMentions(users=True),
    )


@app_commands.command(
    name="inhouse-list",
    description="현재 진행 중인 내전 목록과 참가자를 확인합니다.",
)
@app_commands.guild_only()
async def inhouse_list(interaction: discord.Interaction):
    if interaction.guild_id is None:
        return

    sessions = database.get_active_inhouse_sessions(interaction.guild_id)
    if not sessions:
        await interaction.response.send_message("현재 진행 중인 내전이 없습니다.", ephemeral=True)
        return

    if len(sessions) == 1:
        session = sessions[0]
        participants = database.get_inhouse_participants_with_profiles(interaction.guild_id, session["session_id"])
        await interaction.response.send_message(
            format_inhouse_session_detail(session, participants),
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        return

    lines = [f"진행 중인 내전이 {len(sessions)}개 있습니다. 어떤 내전을 보시겠습니까?"]
    lines.extend(f"civilwar #{s['civilwar_number']}" for s in sessions)

    await interaction.response.send_message(
        "\n".join(lines),
        view=InhouseListView(interaction.guild_id, sessions),
        allowed_mentions=discord.AllowedMentions(users=True),
    )


@app_commands.command(
    name="end-inhouse",
    description="진행 중인 내전 세션을 종료합니다.",
)
@app_commands.guild_only()
@app_commands.describe(civilwar_number="종료할 내전 번호 (주최 중인 내전이 1개면 생략 가능)")
async def end_inhouse(interaction: discord.Interaction, civilwar_number: int | None = None):
    if interaction.guild is None or interaction.guild_id is None:
        await interaction.response.send_message("이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    sessions = database.get_active_inhouse_sessions(interaction.guild_id)
    if not sessions:
        await interaction.response.send_message("현재 진행 중인 내전이 없습니다.", ephemeral=True)
        return

    target_session = None
    if civilwar_number is not None:
        target_session = database.get_inhouse_session_by_number(interaction.guild_id, civilwar_number)
        if target_session is None:
            await interaction.response.send_message(f"`civilwar #{civilwar_number}` 내전은 진행 중이 아닙니다.", ephemeral=True)
            return
    else:
        my_sessions = [s for s in sessions if s["organizer_user_id"] == interaction.user.id]
        if len(my_sessions) == 1:
            target_session = my_sessions[0]
        elif len(sessions) == 1:
            target_session = sessions[0]
        else:
            active_numbers = ", ".join(f"#{s['civilwar_number']}" for s in sessions)
            await interaction.response.send_message(
                f"진행 중인 내전이 여러 개입니다 ({active_numbers}). `civilwar_number`를 지정해 주세요.",
                ephemeral=True,
            )
            return

    is_organizer = target_session["organizer_user_id"] == interaction.user.id
    is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild
    if not (is_organizer or is_admin):
        await interaction.response.send_message(
            f"`civilwar #{target_session['civilwar_number']}` 주최자(또는 서버 관리자)만 내전을 종료할 수 있습니다.",
            ephemeral=True,
        )
        return

    participants = database.get_inhouse_participants_with_profiles(interaction.guild_id, target_session["session_id"])
    deleted = database.delete_inhouse_session(interaction.guild_id, target_session["session_id"])
    if not deleted:
        await interaction.response.send_message("내전 종료 처리에 실패했습니다.", ephemeral=True)
        return

    await mark_lobby_message_closed(
        guild=interaction.guild,
        session=target_session,
        participants=participants,
        reason="모집 종료",
    )
    await interaction.response.send_message(
        f"🛑 **civilwar #{target_session['civilwar_number']}** 내전이 종료되었습니다. (모집 종료 처리 완료)",
    )


def setup(tree: app_commands.CommandTree) -> None:
    tree.add_command(create_inhouse)
    tree.add_command(inhouse_transfer)
    tree.add_command(inhouse_list)
    tree.add_command(end_inhouse)
