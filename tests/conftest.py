import os

import pytest

# settings.py가 import 시점에 환경변수를 읽으므로 먼저 세팅
os.environ["DISCORD_TOKEN"] = "fake-token-for-tests"
os.environ["TEST_GUILD_IDS"] = "123,not-a-number"

G, OTHER_G = 1000, 2000


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    from civilwarhelper import db
    from civilwarhelper.db import connection

    monkeypatch.setattr(connection, "DATA_DIR", tmp_path)
    monkeypatch.setattr(connection, "DATABASE_PATH", tmp_path / "test.db")
    db.initialize_database()
    return db


@pytest.fixture
def full_session(isolated_database):
    db = isolated_database
    for uid in range(1, 12):
        db.save_profile(G, uid, "lol", f"user{uid}", f"name{uid}", "KR1", "KR")
    session = db.create_inhouse_session(G, "lol", organizer_user_id=1)
    sid = int(session["session_id"])
    for uid in range(1, 11):
        ok, _ = db.add_inhouse_participant(G, sid, uid)
        assert ok, f"join {uid}"
    return sid
