from civilwarhelper import db
from civilwarhelper.config.positions import LOL_STANDARD_POSITIONS
from civilwarhelper.config.settings import TEST_GUILD_IDS
from civilwarhelper.services.balance import assign_teams_with_balance

from conftest import G, OTHER_G


def test_test_guild_ids_skip_invalid_entries():
    assert TEST_GUILD_IDS == [123]


def test_eleventh_join_is_rejected(full_session):
    ok, _ = db.add_inhouse_participant(G, full_session, 11)
    assert not ok


def test_position_update_is_scoped_to_guild(full_session):
    ok, _ = db.update_inhouse_participant_position(G, full_session, 2, "Mid")
    assert ok
    ok, _ = db.update_inhouse_participant_position(OTHER_G, full_session, 2, "Top")
    assert not ok


def test_position_update_on_deleted_session_is_rejected(full_session):
    db.delete_inhouse_session(G, full_session)
    ok, _ = db.update_inhouse_participant_position(G, full_session, 2, "Top")
    assert not ok


def test_balance_assigns_five_per_side(full_session):
    participants = db.get_inhouse_participants_with_profiles(guild_id=G, session_id=full_session)
    settings = db.get_session_balance_settings(G, full_session, LOL_STANDARD_POSITIONS)
    assignments = assign_teams_with_balance(participants, "lol", settings)
    assert len(assignments) == 10
    assert sum(a["assigned_team"] == "RED" for a in assignments) == 5


def test_balance_with_seven_participants_does_not_crash(full_session):
    participants = db.get_inhouse_participants_with_profiles(guild_id=G, session_id=full_session)
    settings = db.get_session_balance_settings(G, full_session, LOL_STANDARD_POSITIONS)
    assert len(assign_teams_with_balance(participants[:7], "lol", settings)) == 7


def test_side_swap_is_scoped_to_guild(full_session):
    participants = db.get_inhouse_participants_with_profiles(guild_id=G, session_id=full_session)
    settings = db.get_session_balance_settings(G, full_session, LOL_STANDARD_POSITIONS)
    db.save_team_assignments(G, full_session, assign_teams_with_balance(participants, "lol", settings))

    ok, _ = db.swap_entire_red_blue_teams(guild_id=OTHER_G, session_id=full_session)
    assert not ok
    ok, _ = db.swap_entire_red_blue_teams(guild_id=G, session_id=full_session)
    assert ok


def test_initialize_database_is_idempotent():
    db.initialize_database()
    db.initialize_database()
