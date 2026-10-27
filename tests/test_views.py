import discord
import pytest

from civilwarhelper import db
from civilwarhelper.app import bot, restore_lobby_view
from civilwarhelper.config.positions import LOL_STANDARD_POSITIONS
from civilwarhelper.services.balance import assign_teams_with_balance
from civilwarhelper.ui.formatting.board import format_matchmaking_board
from civilwarhelper.ui.views.recruitment import InhouseRecruitmentView
from civilwarhelper.ui.views.team_manage import InhouseTeamManageView

from conftest import G


@pytest.fixture
def started_session(full_session):
    sid = full_session
    participants = db.get_inhouse_participants_with_profiles(guild_id=G, session_id=sid)
    settings = db.get_session_balance_settings(G, sid, LOL_STANDARD_POSITIONS)
    db.save_team_assignments(G, sid, assign_teams_with_balance(participants, "lol", settings))
    db.set_session_lobby_message(G, sid, channel_id=555, message_id=777)
    db.set_inhouse_match_started(G, sid, True)
    session = db.get_inhouse_session_by_id(guild_id=G, session_id=sid)
    participants = db.get_inhouse_participants_with_profiles(guild_id=G, session_id=sid)
    return session, participants, db.get_session_balance_settings(G, sid, LOL_STANDARD_POSITIONS)


async def test_session_records_match_started(started_session):
    session, _, _ = started_session
    assert session.get("match_started") == 1


async def test_recruitment_view_is_persistent(started_session):
    session, _, _ = started_session
    assert InhouseRecruitmentView(guild_id=G, session=session, participant_count=10).is_persistent()


async def test_team_view_is_persistent_with_unique_ids(started_session):
    session, participants, settings = started_session
    view = InhouseTeamManageView(guild_id=G, session=session, participants=participants, balance_settings=settings)
    assert view.is_persistent()
    ids = [child.custom_id for child in view.children]
    assert len(ids) == len(set(ids))
    assert len(view.children) <= 25


async def test_matchmaking_board_fits_discord_limit(started_session):
    session, participants, settings = started_session
    board = format_matchmaking_board(session=session, participants=participants, balance_settings=settings)
    assert len(board) <= 2000


async def test_restore_registers_persistent_view(started_session):
    session, _, _ = started_session

    class FakeGuild:
        id = G

        def get_channel(self, _):
            return None

        async def fetch_channel(self, _):
            raise discord.NotFound(type("R", (), {"status": 404, "reason": "nf"})(), "gone")

    await restore_lobby_view(FakeGuild(), session)
    assert len(bot.persistent_views) >= 1
