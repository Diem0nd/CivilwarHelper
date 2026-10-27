from contextlib import closing
import sqlite3

from civilwarhelper.db.connection import get_connection


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, col_type: str):
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")


def initialize_database():
    with closing(get_connection()) as conn:
        # 구버전 단일 내전 인덱스 삭제
        conn.execute("DROP INDEX IF EXISTS one_open_inhouse_per_guild")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                guild_id INTEGER NOT NULL,
                discord_user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                discord_nickname TEXT NOT NULL,
                riot_game_name TEXT NOT NULL,
                riot_tagline TEXT NOT NULL,
                server_location TEXT NOT NULL,
                puuid TEXT,
                solo_tier TEXT,
                flex_tier TEXT,
                competitive_tier TEXT,
                main_position TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_api_sync TEXT,
                PRIMARY KEY (guild_id, discord_user_id, game)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inhouse_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                civilwar_number INTEGER NOT NULL,
                game TEXT NOT NULL,
                organizer_user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inhouse_participants (
                session_id INTEGER NOT NULL,
                guild_id INTEGER,
                discord_user_id INTEGER NOT NULL,
                discord_nickname TEXT,
                riot_game_name TEXT,
                riot_tagline TEXT,
                server_location TEXT,
                solo_tier TEXT,
                flex_tier TEXT,
                competitive_tier TEXT,
                main_position TEXT,
                preferred_position TEXT,
                assigned_team TEXT,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (session_id, discord_user_id),
                FOREIGN KEY (session_id) REFERENCES inhouse_sessions(session_id) ON DELETE CASCADE
            )
            """
        )

        # 스키마 마이그레이션용 컬럼 보정
        for col, ctype in (
            ("guild_id", "INTEGER"),
            ("discord_nickname", "TEXT"),
            ("riot_game_name", "TEXT"),
            ("riot_tagline", "TEXT"),
            ("server_location", "TEXT"),
            ("solo_tier", "TEXT"),
            ("flex_tier", "TEXT"),
            ("custom_tier", "TEXT"),
            ("competitive_tier", "TEXT"),
            ("main_position", "TEXT"),
            ("preferred_position", "TEXT"),
            ("assigned_team", "TEXT"),
            ("assigned_position", "TEXT"),
            ("sub_position", "TEXT"),
        ):
            _ensure_column(conn, "inhouse_participants", col, ctype)

        session_cols = {r["name"] for r in conn.execute("PRAGMA table_info(inhouse_sessions)").fetchall()}
        if "match_started" not in session_cols:
            _ensure_column(conn, "inhouse_sessions", "match_started", "INTEGER NOT NULL DEFAULT 0")
            # 이미 10명 팀배정 끝난 세션이면 시작된 상태로 간주
            conn.execute(
                """
                UPDATE inhouse_sessions
                SET match_started = 1
                WHERE status = 'open'
                  AND (SELECT COUNT(*) FROM inhouse_participants p WHERE p.session_id = inhouse_sessions.session_id) = 10
                  AND (
                      SELECT COUNT(*) FROM inhouse_participants p
                      WHERE p.session_id = inhouse_sessions.session_id
                        AND p.assigned_team IN ('RED', 'BLUE')
                        AND p.assigned_position IS NOT NULL
                  ) = 10
                """
            )

        for col, ctype in (
            ("updated_at", "TEXT"),
            ("lobby_channel_id", "INTEGER"),
            ("lobby_message_id", "INTEGER"),
            ("team_groups_json", "TEXT DEFAULT '[]'"),
            ("balance_settings", "TEXT"),
            ("fearless_enabled", "INTEGER DEFAULT 0"),
            ("current_set", "INTEGER DEFAULT 1"),
            ("fearless_bans_json", "TEXT DEFAULT '{}'"),
            ("set_results_json", "TEXT DEFAULT '{}'"),
            ("fearless_data", "TEXT NOT NULL DEFAULT '{}'"),
        ):
            _ensure_column(conn, "inhouse_sessions", col, ctype)

        _ensure_column(conn, "profiles", "custom_tier", "TEXT")
        _ensure_column(conn, "profiles", "sub_position", "TEXT")

        # 서버 무관 개인 누적 전적
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS global_user_inhouse_stats (
                discord_user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                total_wins INTEGER NOT NULL DEFAULT 0,
                total_losses INTEGER NOT NULL DEFAULT 0,
                upper_wins INTEGER NOT NULL DEFAULT 0,
                upper_losses INTEGER NOT NULL DEFAULT 0,
                even_wins INTEGER NOT NULL DEFAULT 0,
                even_losses INTEGER NOT NULL DEFAULT 0,
                lower_wins INTEGER NOT NULL DEFAULT 0,
                lower_losses INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (discord_user_id, game)
            )
            """
        )

        conn.commit()
