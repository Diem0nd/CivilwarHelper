import logging

import discord

from civilwarhelper import db as database
from civilwarhelper.ui.formatting.inhouse import format_inhouse_session_detail
from civilwarhelper.ui.views.recruitment import InhouseRecruitmentView


def resolve_organizer_target_session(
    guild_id: int,
    user_id: int,
    civilwar_number: int | None,
) -> tuple[dict | None, str | None]:
    sessions = database.get_active_inhouse_sessions(guild_id)
    if not sessions:
        return None, "현재 진행 중인 내전이 없습니다."

    if civilwar_number is not None:
        target = next((s for s in sessions if s["civilwar_number"] == civilwar_number), None)
        if target is None:
            return None, f"`civilwar #{civilwar_number}` 내전을 찾을 수 없습니다."
        if target["organizer_user_id"] != user_id:
            return None, f"`civilwar #{civilwar_number}`의 주최자만 이 명령어를 사용할 수 있습니다."
        return target, None

    owned = [s for s in sessions if s["organizer_user_id"] == user_id]
    if not owned:
        return None, "본인이 주최 중인 내전이 없습니다. (주최자만 실행 가능)"

    if len(owned) > 1:
        nums = ", ".join(f"#{s['civilwar_number']}" for s in owned)
        return None, f"현재 여러 개의 내전({nums})을 주최 중입니다. `civilwar_number` 옵션에 번호를 지정해 주세요."

    return owned[0], None


async def _fetch_lobby_msg(guild: discord.Guild, session: dict) -> discord.Message | None:
    channel_id = session.get("lobby_channel_id") or session.get("channel_id")
    message_id = session.get("lobby_message_id") or session.get("message_id")
    if not channel_id or not message_id:
        return None

    channel = guild.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await guild.fetch_channel(int(channel_id))
        except discord.HTTPException as e:
            logging.debug("로비 채널 조회 실패 (%s): %s", channel_id, e)
            return None

    if not isinstance(channel, discord.abc.Messageable):
        return None

    try:
        return await channel.fetch_message(int(message_id))
    except discord.HTTPException as e:
        logging.debug("로비 메시지 조회 실패 (%s): %s", message_id, e)
        return None


async def mark_lobby_message_closed(
    guild: discord.Guild | None,
    session: dict,
    participants: list[dict],
    reason: str = "내전 종료",
) -> None:
    if guild is None:
        return
    msg = await _fetch_lobby_msg(guild, session)
    if msg is None:
        return

    try:
        await msg.edit(
            content=format_inhouse_session_detail(session, participants, is_closed=True, closed_reason=reason),
            view=None,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    except discord.HTTPException as e:
        logging.debug("종료 로비 메시지 수정 실패: %s", e)


async def sync_lobby_message_if_exists(
    guild: discord.Guild | None,
    session_or_id: dict | int,
    participants: list[dict] | None = None,
) -> None:
    if guild is None:
        return

    session = (
        database.get_inhouse_session_by_id(guild.id, session_or_id)
        if isinstance(session_or_id, int)
        else session_or_id
    )
    if not session:
        return

    session_id = int(session["session_id"])
    if participants is None:
        participants = database.get_inhouse_participants_with_profiles(guild.id, session_id)

    msg = await _fetch_lobby_msg(guild, session)
    if msg is None:
        return

    try:
        is_closed = session.get("status") not in (None, "open", "recruiting")
        updated_text = format_inhouse_session_detail(session, participants, is_closed=is_closed)
        new_view = (
            None
            if is_closed
            else InhouseRecruitmentView(guild_id=guild.id, session=session, participant_count=len(participants))
        )
        await msg.edit(
            content=updated_text,
            view=new_view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    except discord.HTTPException as e:
        logging.debug("로비 메시지 동기화 실패: %s", e)
