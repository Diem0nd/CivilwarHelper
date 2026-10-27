import pytest

from civilwarhelper import db
from civilwarhelper.config.positions import VAL_STANDARD_POSITIONS
from civilwarhelper.riot import valorant
from civilwarhelper.services.balance import assign_teams_with_balance
from civilwarhelper.services.team_names import recommend_team_names_by_balance
from civilwarhelper.ui import emojis
from civilwarhelper.ui.formatting.board import format_fearless_section, format_matchmaking_board
from civilwarhelper.ui.views.profile_manage import sync_valorant_profile
from civilwarhelper.ui.views.team_manage import InhouseTeamManageView

from conftest import G


@pytest.fixture
def val_session():
    session = db.create_inhouse_session(G, "valorant", organizer_user_id=1)
    sid = int(session["session_id"])
    ok, _ = db.auto_fill_inhouse_to_ten(G, sid)
    assert ok
    return sid


def _started(sid):
    participants = db.get_inhouse_participants_with_profiles(guild_id=G, session_id=sid)
    settings = db.get_session_balance_settings(G, sid, VAL_STANDARD_POSITIONS)
    db.save_team_assignments(G, sid, assign_teams_with_balance(participants, "valorant", settings))
    session = db.get_inhouse_session_by_id(guild_id=G, session_id=sid)
    participants = db.get_inhouse_participants_with_profiles(guild_id=G, session_id=sid)
    return session, participants, settings


@pytest.mark.parametrize(
    ("number", "expected"),
    [(None, "Unranked"), (0, "Unranked"), (3, "Iron 1"), (14, "Gold 3"), (21, "Ascendant 1"), (26, "Immortal 3"), (27, "Radiant")],
)
def test_competitive_tier_name(number, expected):
    assert valorant.competitive_tier_name(number) == expected


def test_agent_role_normalizes_names():
    assert valorant.agent_role("KAY/O") == "Initiator"
    assert valorant.agent_role("Jett") == "Duelist"
    assert valorant.agent_role("Someone New") is None


def test_pick_main_role():
    assert valorant.pick_main_role([]) == "Unknown"
    assert valorant.pick_main_role(["Duelist"] * 6 + ["Sentinel"] * 4) == "Duelist"
    spread = ["Duelist", "Initiator", "Controller", "Sentinel"] * 3
    assert valorant.pick_main_role(spread) == "Flex"


def _match(queue, tier, agent_id, puuid="me"):
    return {
        "matchInfo": {"queueId": queue},
        "players": [
            {"puuid": "other", "competitiveTier": 27, "characterId": "x"},
            {"puuid": puuid, "competitiveTier": tier, "characterId": agent_id},
        ],
    }


def test_summarize_matches_uses_latest_competitive_tier():
    agents = {"jett-id": "Jett", "omen-id": "Omen"}
    matches = [
        _match("unrated", 0, "OMEN-ID"),
        _match("competitive", 15, "JETT-ID"),
        _match("competitive", 9, "JETT-ID"),
    ]
    assert valorant.summarize_matches(matches, "me", agents) == ("Platinum 1", "Duelist")


async def test_fetch_adds_latest_competitive_match_when_recent_ones_are_unrated(monkeypatch):
    history = [{"matchId": f"u{i}", "queueId": "unrated", "gameStartTimeMillis": 100 - i} for i in range(12)]
    history.append({"matchId": "c1", "queueId": "competitive", "gameStartTimeMillis": 1})
    fetched = []

    async def fake_account(session, game_name, tagline):
        return {"puuid": "me"}

    async def fake_shard(session, puuid):
        return "kr"

    async def fake_matchlist(session, shard, puuid):
        return history

    async def fake_agents(session, shard):
        return {"jett-id": "Jett"}

    async def fake_match(session, shard, match_id):
        fetched.append(match_id)
        return _match("competitive" if match_id == "c1" else "unrated", 18, "jett-id")

    monkeypatch.setattr(valorant, "get_account_by_riot_id", fake_account)
    monkeypatch.setattr(valorant, "get_active_shard", fake_shard)
    monkeypatch.setattr(valorant, "get_matchlist", fake_matchlist)
    monkeypatch.setattr(valorant, "load_agent_names", fake_agents)
    monkeypatch.setattr(valorant, "get_match", fake_match)

    data = await valorant.fetch_val_profile_data(None, "name", "KR1")
    assert len(fetched) == valorant.RECENT_MATCH_COUNT + 1 and fetched[-1] == "c1"
    assert data == {"puuid": "me", "competitive_tier": "Diamond 1", "main_position": "Duelist"}


async def test_registration_without_val_key_explains_manual_tier(monkeypatch):
    monkeypatch.delenv(valorant.VAL_API_KEY_ENV, raising=False)
    note = await sync_valorant_profile(G, 1, "name", "KR1")
    assert "API 키" in note and "/userprofile" in note


def test_tier_emoji_accepts_both_name_styles(monkeypatch):
    monkeypatch.setattr(emojis, "CUSTOM_EMOJI_CACHE", {"valGOLD": "<:valGOLD:1>", "lol_SILVER": "<:lol_SILVER:2>"})
    assert emojis.get_tier_emoji("valorant", "gold") == "<:valGOLD:1>"
    assert emojis.get_tier_emoji("lol", "SILVER") == "<:lol_SILVER:2>"
    assert emojis.get_tier_emoji("lol", "GOLD") == "⬜"


def test_auto_fill_gives_bots_valorant_tiers_and_roles(val_session):
    participants = db.get_inhouse_participants_with_profiles(guild_id=G, session_id=val_session)
    assert len(participants) == 10
    assert {p["main_position"] for p in participants} == set(VAL_STANDARD_POSITIONS)
    assert all("EMERALD" not in (p["competitive_tier"] or "") for p in participants)


def test_map_ban_is_recorded_and_shown(val_session):
    db.toggle_fearless_mode(G, val_session)
    db.record_set_winner(G, val_session, "RED")
    db.save_fearless_set_record(G, val_session, 2, [], [], extra_bans=["바인드"], played_maps=["어센트"])

    section = format_fearless_section(G, val_session, game="valorant")
    assert "맵 밴 : ON" in section
    assert "2세트 맵 밴 : 🗺️ - (어센트) / 🚫 - (바인드)" in section
    assert "피어리스" not in section


def test_lol_fearless_section_is_unchanged(full_session):
    db.toggle_fearless_mode(G, full_session)
    assert "피어리스 : ON" in format_fearless_section(G, full_session, game="lol")


async def test_valorant_team_view_has_map_ban_controls(val_session):
    session, participants, settings = _started(val_session)
    db.toggle_fearless_mode(G, val_session)
    view = InhouseTeamManageView(guild_id=G, session=session, participants=participants, balance_settings=settings)
    labels = [getattr(child, "label", "") or "" for child in view.children]
    assert any("맵 밴: ON" in label for label in labels)
    assert any("맵 밴 입력" in label for label in labels)
    assert not any("피어리스" in label for label in labels)
    assert len(view.children) <= 25


async def test_valorant_board_and_team_names(val_session):
    session, participants, settings = _started(val_session)
    board = format_matchmaking_board(session=session, participants=participants, balance_settings=settings)
    assert len(board) <= 2000
    assert "[DUEL]" in board and "[SENT]" in board
    red, blue = recommend_team_names_by_balance(session, participants, settings)
    assert red and blue
