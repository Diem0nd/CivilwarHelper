from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import json


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "civilwarhelper.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
):
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()
    existing_columns = {row["name"] for row in rows}

    if column_name not in existing_columns:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )


def initialize_database():
    connection = get_connection()

    try:
        # 예전 단일 내전 제한 인덱스가 남아 있다면 제거
        connection.execute(
            "DROP INDEX IF EXISTS one_open_inhouse_per_guild"
        )

        # 1. 프로필 테이블
        connection.execute(
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

        # 2. 내전(civilwar) 세션 테이블
        connection.execute(
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

        # 이전 버전 테이블과의 호환성을 위해 누락된 컬럼 자동 보정
        _ensure_column(connection, "inhouse_sessions", "updated_at", "TEXT")

        # 3. 내전 참가자 테이블
        connection.execute(
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

                FOREIGN KEY (session_id)
                    REFERENCES inhouse_sessions(session_id)
                    ON DELETE CASCADE
            )
            """
        )

        _ensure_column(connection, "inhouse_participants", "guild_id", "INTEGER")
        _ensure_column(connection, "inhouse_participants", "discord_nickname", "TEXT")
        _ensure_column(connection, "inhouse_participants", "riot_game_name", "TEXT")
        _ensure_column(connection, "inhouse_participants", "riot_tagline", "TEXT")
        _ensure_column(connection, "inhouse_participants", "server_location", "TEXT")
        _ensure_column(connection, "inhouse_participants", "solo_tier", "TEXT")
        _ensure_column(connection, "inhouse_participants", "flex_tier", "TEXT")
        _ensure_column(connection, "inhouse_participants", "custom_tier", "TEXT")       
        _ensure_column(connection, "inhouse_participants", "competitive_tier", "TEXT")
        _ensure_column(connection, "inhouse_participants", "main_position", "TEXT")
        _ensure_column(connection, "inhouse_participants", "preferred_position", "TEXT")
        _ensure_column(connection, "inhouse_participants", "assigned_team", "TEXT")
        _ensure_column(connection, "inhouse_participants", "assigned_position", "TEXT")
        _ensure_column(connection, "inhouse_participants", "sub_position", "TEXT")
        _ensure_column(connection, "inhouse_sessions", "lobby_channel_id", "INTEGER")
        _ensure_column(connection, "inhouse_sessions", "lobby_message_id", "INTEGER")
        _ensure_column(connection, "inhouse_sessions", "balance_settings", "TEXT")
        _ensure_column(connection, "inhouse_sessions", "fearless_enabled", "INTEGER DEFAULT 0")
        _ensure_column(connection, "inhouse_sessions", "current_set", "INTEGER DEFAULT 1")
        _ensure_column(connection, "inhouse_sessions", "fearless_bans_json", "TEXT DEFAULT '{}'")
        _ensure_column(connection, "inhouse_sessions", "set_results_json", "TEXT DEFAULT '{}'")
        _ensure_column(connection, "inhouse_sessions", "balance_settings", "TEXT")
        _ensure_column(connection, "profiles", "custom_tier", "TEXT")
        _ensure_column(connection, "profiles", "sub_position", "TEXT")
        # 👇 [여기에 아래 CREATE TABLE 블록을 추가하세요!]
        # 4. 글로벌 개인 내전 전적 테이블 (서버 무관, discord_user_id + game 기준 영구 보존)
        connection.execute(
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

        connection.commit()

    finally:
        connection.close()


# =========================================================
# 프로필 관련 함수 (2~3단계)
# =========================================================

def save_profile(
    guild_id: int,
    discord_user_id: int,
    game: str,
    discord_nickname: str,
    riot_game_name: str,
    riot_tagline: str,
    server_location: str,
):
    connection = get_connection()

    try:
        current_time = datetime.now(timezone.utc).isoformat()

        existing_profile = connection.execute(
            """
            SELECT
                riot_game_name,
                riot_tagline,
                server_location
            FROM profiles
            WHERE guild_id = ?
              AND discord_user_id = ?
              AND game = ?
            """,
            (guild_id, discord_user_id, game),
        ).fetchone()

        account_is_unchanged = (
            existing_profile is not None
            and existing_profile["riot_game_name"] == riot_game_name
            and existing_profile["riot_tagline"] == riot_tagline
            and existing_profile["server_location"] == server_location
        )

        if existing_profile is None:
            connection.execute(
                """
                INSERT INTO profiles (
                    guild_id,
                    discord_user_id,
                    game,
                    discord_nickname,
                    riot_game_name,
                    riot_tagline,
                    server_location,
                    puuid,
                    solo_tier,
                    flex_tier,
                    competitive_tier,
                    main_position,
                    created_at,
                    updated_at,
                    last_api_sync
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, NULL)
                """,
                (
                    guild_id,
                    discord_user_id,
                    game,
                    discord_nickname,
                    riot_game_name,
                    riot_tagline,
                    server_location,
                    current_time,
                    current_time,
                ),
            )
            was_updated = False

        elif account_is_unchanged:
            connection.execute(
                """
                UPDATE profiles
                SET discord_nickname = ?,
                    updated_at = ?
                WHERE guild_id = ?
                  AND discord_user_id = ?
                  AND game = ?
                """,
                (
                    discord_nickname,
                    current_time,
                    guild_id,
                    discord_user_id,
                    game,
                ),
            )
            was_updated = True

        else:
            connection.execute(
                """
                UPDATE profiles
                SET discord_nickname = ?,
                    riot_game_name = ?,
                    riot_tagline = ?,
                    server_location = ?,
                    puuid = NULL,
                    solo_tier = NULL,
                    flex_tier = NULL,
                    competitive_tier = NULL,
                    main_position = NULL,
                    updated_at = ?,
                    last_api_sync = NULL
                WHERE guild_id = ?
                  AND discord_user_id = ?
                  AND game = ?
                """,
                (
                    discord_nickname,
                    riot_game_name,
                    riot_tagline,
                    server_location,
                    current_time,
                    guild_id,
                    discord_user_id,
                    game,
                ),
            )
            was_updated = True

        connection.commit()
        return was_updated

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def ensure_profile_custom_columns(connection: sqlite3.Connection) -> None:
    _ensure_column(connection, "profiles", "custom_tier", "TEXT")
    _ensure_column(connection, "profiles", "sub_position", "TEXT")
    _ensure_column(connection, "inhouse_participants", "custom_tier", "TEXT")


def get_profiles(guild_id: int, game: str):
    connection = get_connection()

    try:
        ensure_profile_custom_columns(connection)
        profiles = connection.execute(
            """
            SELECT
                guild_id,
                discord_user_id,
                game,
                discord_nickname,
                riot_game_name,
                riot_tagline,
                server_location,
                puuid,
                solo_tier,
                flex_tier,
                competitive_tier,
                custom_tier,
                main_position,
                sub_position,
                created_at,
                updated_at,
                last_api_sync
            FROM profiles
            WHERE guild_id = ?
              AND game = ?
            ORDER BY discord_nickname COLLATE NOCASE ASC,
                     riot_game_name COLLATE NOCASE ASC,
                     discord_user_id ASC
            """,
            (guild_id, game),
        ).fetchall()

        return [dict(profile) for profile in profiles]

    finally:
        connection.close()


def update_profile_api_data(
    guild_id: int,
    discord_user_id: int,
    game: str,
    puuid: str | None = None,
    solo_tier: str | None = None,
    flex_tier: str | None = None,
    competitive_tier: str | None = None,
    main_position: str | None = None,
):
    connection = get_connection()

    try:
        current_time = datetime.now(timezone.utc).isoformat()

        connection.execute(
            """
            UPDATE profiles
            SET puuid = ?,
                solo_tier = ?,
                flex_tier = ?,
                competitive_tier = ?,
                main_position = ?,
                last_api_sync = ?,
                updated_at = ?
            WHERE guild_id = ?
              AND discord_user_id = ?
              AND game = ?
            """,
            (
                puuid,
                solo_tier,
                flex_tier,
                competitive_tier,
                main_position,
                current_time,
                current_time,
                guild_id,
                discord_user_id,
                game,
            ),
        )

        connection.commit()

    finally:
        connection.close()


# =========================================================
# 내전(Civilwar) 관련 함수 (4단계)
# =========================================================

def create_inhouse_session(
    guild_id: int,
    game: str,
    organizer_user_id: int,
) -> dict:
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        current_time = datetime.now(timezone.utc).isoformat()

        row = connection.execute(
            """
            SELECT COALESCE(MAX(civilwar_number), 0) AS max_num
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND status = 'open'
            """,
            (guild_id,),
        ).fetchone()

        next_number = (row["max_num"] if row else 0) + 1

        cursor = connection.execute(
            """
            INSERT INTO inhouse_sessions (
                guild_id,
                civilwar_number,
                game,
                organizer_user_id,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                guild_id,
                next_number,
                game,
                organizer_user_id,
                current_time,
                current_time,
            ),
        )

        session_id = cursor.lastrowid
        connection.commit()

        return {
            "session_id": session_id,
            "guild_id": guild_id,
            "civilwar_number": next_number,
            "game": game,
            "organizer_user_id": organizer_user_id,
            "status": "open",
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_active_inhouse_sessions(
    guild_id: int,
    game: str | None = None,
) -> list[dict]:
    connection = get_connection()

    try:
        if game:
            rows = connection.execute(
                """
                SELECT
                    s.*,
                    COUNT(p.discord_user_id) AS participant_count
                FROM inhouse_sessions s
                LEFT JOIN inhouse_participants p
                    ON s.session_id = p.session_id
                WHERE s.guild_id = ?
                  AND s.status = 'open'
                  AND s.game = ?
                GROUP BY s.session_id
                ORDER BY s.civilwar_number ASC
                """,
                (guild_id, game),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT
                    s.*,
                    COUNT(p.discord_user_id) AS participant_count
                FROM inhouse_sessions s
                LEFT JOIN inhouse_participants p
                    ON s.session_id = p.session_id
                WHERE s.guild_id = ?
                  AND s.status = 'open'
                GROUP BY s.session_id
                ORDER BY s.civilwar_number ASC
                """,
                (guild_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()


# 별칭(Alias) 지원: get_open_inhouse_sessions로 호출해도 동일하게 작동
get_open_inhouse_sessions = get_active_inhouse_sessions


def get_inhouse_session_by_id(
    guild_id: int,
    session_id: int,
) -> dict | None:
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT *
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
              AND status = 'open'
            """,
            (guild_id, session_id),
        ).fetchone()

        return dict(row) if row else None

    finally:
        connection.close()


get_open_inhouse_session_by_id = get_inhouse_session_by_id


def get_inhouse_session_by_number(
    guild_id: int,
    civilwar_number: int,
) -> dict | None:
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT *
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND civilwar_number = ?
              AND status = 'open'
            """,
            (guild_id, civilwar_number),
        ).fetchone()

        return dict(row) if row else None

    finally:
        connection.close()


get_open_inhouse_session_by_number = get_inhouse_session_by_number


def transfer_inhouse_organizer(
    guild_id: int,
    session_id: int,
    new_organizer_user_id: int,
) -> bool:
    connection = get_connection()

    try:
        current_time = datetime.now(timezone.utc).isoformat()

        cursor = connection.execute(
            """
            UPDATE inhouse_sessions
            SET organizer_user_id = ?,
                updated_at = ?
            WHERE guild_id = ?
              AND session_id = ?
              AND status = 'open'
            """,
            (
                new_organizer_user_id,
                current_time,
                guild_id,
                session_id,
            ),
        )

        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()


def add_inhouse_participant(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
) -> tuple[bool, str]:
    connection = get_connection()

    try:
        ensure_profile_custom_columns(connection)

        session = connection.execute(
            """
            SELECT *
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
              AND status = 'open'
            """,
            (guild_id, session_id),
        ).fetchone()

        if session is None:
            return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

        game = session["game"]

        profile = connection.execute(
            """
            SELECT *
            FROM profiles
            WHERE guild_id = ?
              AND discord_user_id = ?
              AND game = ?
            """,
            (guild_id, discord_user_id, game),
        ).fetchone()

        if profile is None:
            game_label = "League of Legends" if game == "lol" else "VALORANT"
            return (
                False,
                f"이 유저는 아직 {game_label} 프로필이 등록되지 않았습니다. 먼저 `/register`로 등록해 주세요.",
            )

        existing = connection.execute(
            """
            SELECT 1
            FROM inhouse_participants
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (session_id, discord_user_id),
        ).fetchone()

        if existing is not None:
            return False, "이미 해당 내전에 참가 중인 유저입니다."

        count_row = connection.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM inhouse_participants
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

        if count_row["cnt"] >= 10:
            return False, "이미 참가자가 10명 모두 모집되었습니다."

        current_time = datetime.now(timezone.utc).isoformat()
        recommended_pos = profile["main_position"]
        recommended_sub_pos = profile["sub_position"] if "sub_position" in profile.keys() else None
        custom_tier_val = profile["custom_tier"] if "custom_tier" in profile.keys() else None

        connection.execute(
            """
            INSERT INTO inhouse_participants (
                session_id,
                guild_id,
                discord_user_id,
                discord_nickname,
                riot_game_name,
                riot_tagline,
                server_location,
                solo_tier,
                flex_tier,
                competitive_tier,
                custom_tier,
                main_position,
                preferred_position,
                sub_position,
                joined_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                guild_id,
                discord_user_id,
                profile["discord_nickname"],
                profile["riot_game_name"],
                profile["riot_tagline"],
                profile["server_location"],
                profile["solo_tier"],
                profile["flex_tier"],
                profile["competitive_tier"],
                custom_tier_val,
                profile["main_position"],
                recommended_pos,
                recommended_sub_pos,
                current_time,
            ),
        )

        connection.commit()
        return True, "참가자가 추가되었습니다."

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def remove_inhouse_participant(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
) -> tuple[bool, str]:
    connection = get_connection()

    try:
        session = connection.execute(
            """
            SELECT 1
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
              AND status = 'open'
            """,
            (guild_id, session_id),
        ).fetchone()

        if session is None:
            return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

        cursor = connection.execute(
            """
            DELETE FROM inhouse_participants
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (session_id, discord_user_id),
        )

        connection.commit()

        if cursor.rowcount == 0:
            return False, "해당 유저는 이 내전의 참가자 목록에 없습니다."

        return True, "참가자가 목록에서 제외되었습니다."

    finally:
        connection.close()

def get_inhouse_participants_with_profiles(
    guild_id: int,
    session_id: int,
) -> list[dict]:
    connection = get_connection()

    try:
        ensure_profile_custom_columns(connection)

        session = connection.execute(
            """
            SELECT *
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
            """,
            (guild_id, session_id),
        ).fetchone()

        if session is None:
            return []

        rows = connection.execute(
            """
            SELECT
                p.session_id,
                p.discord_user_id,
                COALESCE(p.preferred_position, pr.main_position) AS preferred_position,
                COALESCE(p.sub_position, pr.sub_position) AS sub_position,
                p.assigned_team,
                p.assigned_position,
                p.joined_at,
                COALESCE(pr.discord_nickname, p.discord_nickname) AS discord_nickname,
                COALESCE(pr.riot_game_name, p.riot_game_name) AS riot_game_name,
                COALESCE(pr.riot_tagline, p.riot_tagline) AS riot_tagline,
                COALESCE(pr.server_location, p.server_location) AS server_location,
                COALESCE(pr.solo_tier, p.solo_tier) AS solo_tier,
                COALESCE(pr.flex_tier, p.flex_tier) AS flex_tier,
                COALESCE(pr.competitive_tier, p.competitive_tier) AS competitive_tier,
                COALESCE(pr.custom_tier, p.custom_tier) AS custom_tier,
                COALESCE(pr.main_position, p.main_position) AS main_position
            FROM inhouse_participants p
            LEFT JOIN profiles pr
                ON pr.guild_id = ?
               AND pr.discord_user_id = p.discord_user_id
               AND pr.game = ?
            WHERE p.session_id = ?
            ORDER BY p.joined_at ASC
            """,
            (
                guild_id,
                session["game"],
                session_id,
            ),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()


get_inhouse_participants = get_inhouse_participants_with_profiles

def delete_inhouse_session(
    guild_id: int,
    session_id: int,
) -> bool:
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            DELETE FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
            """,
            (guild_id, session_id),
        )

        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()

def update_inhouse_participant_position(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    preferred_position: str,
) -> tuple[bool, str]:
    connection = get_connection()

    try:
        session = connection.execute(
            """
            SELECT 1
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
              AND status = 'open'
            """,
            (guild_id, session_id),
        ).fetchone()

        if session is None:
            return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

        cursor = connection.execute(
            """
            UPDATE inhouse_participants
            SET preferred_position = ?
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (preferred_position, session_id, discord_user_id),
        )

        connection.commit()

        if cursor.rowcount == 0:
            return False, "해당 유저는 이 내전의 참가자 목록에 없습니다."

        return True, f"선호 포지션이 **{preferred_position}**(으)로 설정되었습니다."

    finally:
        connection.close()


def replace_inhouse_participant(
    guild_id: int,
    session_id: int,
    old_user_id: int,
    new_user_id: int,
) -> tuple[bool, str]:
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        session = connection.execute(
            """
            SELECT *
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
              AND status = 'open'
            """,
            (guild_id, session_id),
        ).fetchone()

        if session is None:
            connection.rollback()
            return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

        old_existing = connection.execute(
            """
            SELECT 1
            FROM inhouse_participants
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (session_id, old_user_id),
        ).fetchone()

        if old_existing is None:
            connection.rollback()
            return False, "교체 대상(기존 유저)이 이 내전의 참가자 목록에 없습니다."

        new_existing = connection.execute(
            """
            SELECT 1
            FROM inhouse_participants
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (session_id, new_user_id),
        ).fetchone()

        if new_existing is not None:
            connection.rollback()
            return False, "새로 추가하려는 유저가 이미 이 내전에 참가 중입니다."

        game = session["game"]
        profile = connection.execute(
            """
            SELECT *
            FROM profiles
            WHERE guild_id = ?
              AND discord_user_id = ?
              AND game = ?
            """,
            (guild_id, new_user_id, game),
        ).fetchone()

        if profile is None:
            connection.rollback()
            game_label = "League of Legends" if game == "lol" else "VALORANT"
            return (
                False,
                f"새 참가자는 아직 {game_label} 프로필이 등록되지 않았습니다. 먼저 `/register`로 등록해 주세요.",
            )

        connection.execute(
            """
            DELETE FROM inhouse_participants
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (session_id, old_user_id),
        )

        current_time = datetime.now(timezone.utc).isoformat()
        recommended_pos = profile["main_position"]

        connection.execute(
            """
            INSERT INTO inhouse_participants (
                session_id,
                guild_id,
                discord_user_id,
                discord_nickname,
                riot_game_name,
                riot_tagline,
                server_location,
                solo_tier,
                flex_tier,
                competitive_tier,
                main_position,
                preferred_position,
                joined_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                guild_id,
                new_user_id,
                profile["discord_nickname"],
                profile["riot_game_name"],
                profile["riot_tagline"],
                profile["server_location"],
                profile["solo_tier"],
                profile["flex_tier"],
                profile["competitive_tier"],
                profile["main_position"],
                recommended_pos,
                current_time,
            ),
        )

        connection.commit()
        return True, "참가자가 성공적으로 교체되었습니다."

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def get_session_balance_settings(
    guild_id: int,
    session_id: int,
    positions: list[str],
) -> dict[str, str]:
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT balance_settings
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
            """,
            (guild_id, session_id),
        ).fetchone()

        default_settings = {pos: "황밸" for pos in positions}
        if row is None or not row["balance_settings"]:
            return default_settings

        try:
            saved = json.loads(row["balance_settings"])
            for pos in positions:
                if saved.get(pos) not in ("아랫밸", "황밸", "윗밸"):
                    saved[pos] = "황밸"
            return saved
        except Exception:
            return default_settings

    finally:
        connection.close()


def save_session_balance_settings(
    guild_id: int,
    session_id: int,
    settings: dict[str, str],
) -> None:
    connection = get_connection()

    try:
        current_time = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            UPDATE inhouse_sessions
            SET balance_settings = ?,
                updated_at = ?
            WHERE guild_id = ?
              AND session_id = ?
            """,
            (
                json.dumps(settings, ensure_ascii=False),
                current_time,
                guild_id,
                session_id,
            ),
        )
        connection.commit()

    finally:
        connection.close()


def save_team_assignments(
    guild_id: int,
    session_id: int,
    assignments: list[dict],
) -> None:
    """
    assignments 예시:
    [
        {"discord_user_id": 123, "assigned_team": "RED", "assigned_position": "Top"},
        ...
    ]
    """
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        for item in assignments:
            connection.execute(
                """
                UPDATE inhouse_participants
                SET assigned_team = ?,
                    assigned_position = ?
                WHERE session_id = ?
                  AND discord_user_id = ?
                """,
                (
                    item["assigned_team"],
                    item["assigned_position"],
                    session_id,
                    item["discord_user_id"],
                ),
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def swap_two_participants_team(
    session_id: int,
    user_a_id: int,
    user_b_id: int,
) -> tuple[bool, str]:
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        row_a = connection.execute(
            """
            SELECT assigned_team, assigned_position
            FROM inhouse_participants
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (session_id, user_a_id),
        ).fetchone()

        row_b = connection.execute(
            """
            SELECT assigned_team, assigned_position
            FROM inhouse_participants
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (session_id, user_b_id),
        ).fetchone()

        if row_a is None or row_b is None:
            connection.rollback()
            return False, "교환할 참가자 정보를 찾을 수 없습니다."

        connection.execute(
            """
            UPDATE inhouse_participants
            SET assigned_team = ?,
                assigned_position = ?
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (row_b["assigned_team"], row_b["assigned_position"], session_id, user_a_id),
        )

        connection.execute(
            """
            UPDATE inhouse_participants
            SET assigned_team = ?,
                assigned_position = ?
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (row_a["assigned_team"], row_a["assigned_position"], session_id, user_b_id),
        )

        connection.commit()
        return True, "두 참가자의 자리(팀/포지션)가 교체되었습니다."

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

def update_inhouse_participant_position(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    preferred_position: str,
) -> tuple[bool, str]:
    connection = get_connection()

    try:
        session = connection.execute(
            """
            SELECT 1
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
              AND status = 'open'
            """,
            (guild_id, session_id),
        ).fetchone()

        if session is None:
            return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

        cursor = connection.execute(
            """
            UPDATE inhouse_participants
            SET preferred_position = ?
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (preferred_position, session_id, discord_user_id),
        )

        connection.commit()

        if cursor.rowcount == 0:
            return False, "먼저 [내전 참가] 버튼을 눌러 내전에 참가해 주세요."

        return True, f"주 포지션이 **{preferred_position}**(으)로 변경되었습니다."

    finally:
        connection.close()

def update_inhouse_participant_sub_position(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    sub_position: str | None,
) -> tuple[bool, str]:
    connection = get_connection()

    try:
        session = connection.execute(
            """
            SELECT 1
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
              AND status = 'open'
            """,
            (guild_id, session_id),
        ).fetchone()

        if session is None:
            return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

        cursor = connection.execute(
            """
            UPDATE inhouse_participants
            SET sub_position = ?
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (sub_position, session_id, discord_user_id),
        )

        connection.commit()

        if cursor.rowcount == 0:
            return False, "먼저 [내전 참가] 버튼을 눌러 내전에 참가해 주세요."

        display_sub = sub_position if sub_position else "선택안함"
        return True, f"부 포지션이 **{display_sub}**(으)로 설정되었습니다."

    finally:
        connection.close()

def save_inhouse_lobby_message(
    guild_id: int,
    session_id: int,
    channel_id: int,
    message_id: int,
) -> None:
    """
    모집 로비 메시지의 채널 ID와 메시지 ID를 저장하여 언제든 실시간 업데이트할 수 있게 합니다.
    """
    connection = get_connection()

    try:
        connection.execute(
            """
            UPDATE inhouse_sessions
            SET lobby_channel_id = ?,
                lobby_message_id = ?
            WHERE guild_id = ?
              AND session_id = ?
            """,
            (channel_id, message_id, guild_id, session_id),
        )
        connection.commit()

    finally:
        connection.close()

def swap_entire_red_blue_teams(
    guild_id: int,
    session_id: int,
) -> tuple[bool, str]:
    """
    현재 편성된 5인 구성을 그대로 유지한 채 RED 팀과 BLUE 팀의 진영만 서로 맞바꿉니다.
    또한 포지션별 밸런스 설정(윗밸 <-> 아랫밸) 및 기존 세트 승패 기록(RED <-> BLUE)도
    선수들의 진영 이동에 맞춰 함께 반전합니다.
    """
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        # 1. 참가자들의 RED <-> BLUE 팀 소속 일괄 반전
        connection.execute(
            """
            UPDATE inhouse_participants
            SET assigned_team = CASE
                WHEN assigned_team = 'RED' THEN 'BLUE'
                WHEN assigned_team = 'BLUE' THEN 'RED'
                ELSE assigned_team
            END
            WHERE session_id = ?
            """,
            (session_id,),
        )

        # 2. 레드 기준 밸런스 표시도 윗밸 <-> 아랫밸 반전하여 일관성 유지
        row = connection.execute(
            """
            SELECT balance_settings
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND session_id = ?
            """,
            (guild_id, session_id),
        ).fetchone()

        if row and row["balance_settings"]:
            try:
                settings = json.loads(row["balance_settings"])
                for pos, val in list(settings.items()):
                    if val == "윗밸":
                        settings[pos] = "아랫밸"
                    elif val == "아랫밸":
                        settings[pos] = "윗밸"

                connection.execute(
                    """
                    UPDATE inhouse_sessions
                    SET balance_settings = ?,
                        updated_at = ?
                    WHERE guild_id = ?
                      AND session_id = ?
                    """,
                    (
                        json.dumps(settings, ensure_ascii=False),
                        datetime.now(timezone.utc).isoformat(),
                        guild_id,
                        session_id,
                    ),
                )
            except Exception:
                pass

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    # 3. 기록된 세트별 승패(RED <-> BLUE)도 진영 이동에 맞춰 함께 반전
    try:
        state = get_fearless_state(guild_id, session_id)
        results_data = state.get("results", {})
        if results_data:
            swapped_results = {}
            for set_num, winner in results_data.items():
                if winner == "RED":
                    swapped_results[set_num] = "BLUE"
                elif winner == "BLUE":
                    swapped_results[set_num] = "RED"
                else:
                    swapped_results[set_num] = winner

            _save_fearless_payload(
                guild_id=guild_id,
                session_id=session_id,
                enabled=state["enabled"],
                sets_data=state["sets"],
                results_data=swapped_results,
            )
    except Exception:
        pass

    return True, "레드팀과 블루팀의 진영 및 승패 기록이 함께 변경되었습니다."


def update_inhouse_participant_position(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    preferred_position: str,
) -> tuple[bool, str]:
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE inhouse_participants
            SET preferred_position = ?
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (preferred_position, session_id, discord_user_id),
        )
        connection.commit()

        if cursor.rowcount == 0:
            return False, "먼저 [🎮 내전 참가] 버튼을 눌러 내전에 참가해 주세요."

        return True, f"주 포지션이 **{preferred_position}**(으)로 변경되었습니다."

    finally:
        connection.close()


def update_inhouse_participant_sub_position(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    sub_position: str | None,
) -> tuple[bool, str]:
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE inhouse_participants
            SET sub_position = ?
            WHERE session_id = ?
              AND discord_user_id = ?
            """,
            (sub_position, session_id, discord_user_id),
        )
        connection.commit()

        if cursor.rowcount == 0:
            return False, "먼저 [🎮 내전 참가] 버튼을 눌러 내전에 참가해 주세요."

        label = sub_position if sub_position else "선택안함"
        return True, f"부 포지션이 **{label}**(으)로 변경되었습니다."

    finally:
        connection.close()


def flip_all_teams_red_blue(session_id: int) -> None:
    """
    편성된 팀원 구성을 그대로 유지한 채 RED 팀과 BLUE 팀만 통째로 맞바꿉니다.
    """
    connection = get_connection()

    try:
        connection.execute(
            """
            UPDATE inhouse_participants
            SET assigned_team = CASE
                WHEN assigned_team = 'RED' THEN 'BLUE'
                WHEN assigned_team = 'BLUE' THEN 'RED'
                ELSE assigned_team
            END
            WHERE session_id = ?
            """,
            (session_id,),
        )
        connection.commit()

    finally:
        connection.close()
# ---------------------------------------------------------
# 7단계: 피어리스(Fearless) 규칙 및 챔피언/요원 기록 관리
# (※ 주의: def 앞에 공백이 하나도 없어야 합니다!)
# ---------------------------------------------------------
# ---------------------------------------------------------
# 7단계 개편: 세트별 승패 기록 + LoL 피어리스 순서 제어
# ---------------------------------------------------------
def _ensure_fearless_columns(conn) -> None:
    """inhouse_sessions 테이블에 fearless_enabled, fearless_data 컬럼이 없으면 자동 추가합니다."""
    rows = conn.execute("PRAGMA table_info(inhouse_sessions)").fetchall()
    existing_cols = {row[1] for row in rows}
    if "fearless_enabled" not in existing_cols:
        conn.execute(
            "ALTER TABLE inhouse_sessions ADD COLUMN fearless_enabled INTEGER NOT NULL DEFAULT 0"
        )
    if "fearless_data" not in existing_cols:
        conn.execute(
            "ALTER TABLE inhouse_sessions ADD COLUMN fearless_data TEXT NOT NULL DEFAULT '{}'"
        )
    conn.commit()


def get_fearless_state(guild_id: int, session_id: int) -> dict:
    """해당 내전 세션의 피어리스 상태와 세트 승패 기록을 반환합니다."""
    with get_connection() as conn:
        _ensure_fearless_columns(conn)
        row = conn.execute(
            """
            SELECT fearless_enabled, fearless_data
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        ).fetchone()

    if not row:
        return {"enabled": False, "current_set": 1, "sets": {}, "results": {}}

    enabled = bool(row["fearless_enabled"])
    raw_json = row["fearless_data"] or "{}"
    try:
        parsed = json.loads(raw_json)
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception:
        parsed = {}

    if "sets" in parsed or "results" in parsed:
        sets_data = parsed.get("sets", {})
        results_data = parsed.get("results", {})
    else:
        sets_data = parsed
        results_data = {}

    # 현재 진행 세트는 오직 '승패가 결정된 세트(results_data)' 기준으로만 계산
    completed_sets = [int(k) for k in results_data.keys() if str(k).isdigit()]
    current_set = (max(completed_sets) + 1) if completed_sets else 1

    return {
        "enabled": enabled,
        "current_set": current_set,
        "sets": sets_data,
        "results": results_data,
    }


def _save_fearless_payload(
    guild_id: int,
    session_id: int,
    enabled: bool,
    sets_data: dict,
    results_data: dict,
) -> None:
    payload = {
        "sets": sets_data,
        "results": results_data,
    }
    with get_connection() as conn:
        _ensure_fearless_columns(conn)
        conn.execute(
            """
            UPDATE inhouse_sessions
            SET fearless_enabled = ?,
                fearless_data = ?
            WHERE guild_id = ? AND session_id = ?
            """,
            (
                1 if enabled else 0,
                json.dumps(payload, ensure_ascii=False),
                guild_id,
                session_id,
            ),
        )
        conn.commit()


def toggle_fearless_mode(guild_id: int, session_id: int) -> dict:
    """피어리스 ON/OFF를 전환합니다."""
    state = get_fearless_state(guild_id, session_id)
    new_enabled = not state["enabled"]
    _save_fearless_payload(
        guild_id=guild_id,
        session_id=session_id,
        enabled=new_enabled,
        sets_data=state["sets"],
        results_data=state["results"],
    )
    return get_fearless_state(guild_id, session_id)


def record_set_winner(guild_id: int, session_id: int, winner_side: str) -> dict:
    """현재 세트의 승리 팀('RED' 또는 'BLUE')을 기록하고 다음 세트로 넘깁니다."""
    state = get_fearless_state(guild_id, session_id)
    current_set = state["current_set"]
    results_data = state["results"]
    results_data[str(current_set)] = winner_side.upper()

    _save_fearless_payload(
        guild_id=guild_id,
        session_id=session_id,
        enabled=state["enabled"],
        sets_data=state["sets"],
        results_data=results_data,
    )
    return get_fearless_state(guild_id, session_id)


def save_fearless_set_record(
    guild_id: int,
    session_id: int,
    set_number: int,
    red_champions: list[str],
    blue_champions: list[str],
    extra_bans: list[str] | None = None,
) -> dict:
    """특정 세트의 피어리스 챔피언을 저장합니다. (세트 번호는 넘어가지 않고 유지됩니다)"""
    state = get_fearless_state(guild_id, session_id)
    sets_data = state["sets"]

    sets_data[str(set_number)] = {
        "red": [c.strip() for c in red_champions if c.strip()],
        "blue": [c.strip() for c in blue_champions if c.strip()],
        "extra": [c.strip() for c in (extra_bans or []) if c.strip()],
    }

    _save_fearless_payload(
        guild_id=guild_id,
        session_id=session_id,
        enabled=True,
        sets_data=sets_data,
        results_data=state["results"],
    )
    return get_fearless_state(guild_id, session_id)


def clear_fearless_records(guild_id: int, session_id: int) -> dict:
    """입력된 피어리스 챔피언 기록만 초기화합니다. (세트 승패 스코어는 유지)"""
    state = get_fearless_state(guild_id, session_id)
    _save_fearless_payload(
        guild_id=guild_id,
        session_id=session_id,
        enabled=state["enabled"],
        sets_data={},
        results_data=state["results"],
    )
    return get_fearless_state(guild_id, session_id)


# ---------------------------------------------------------
# 주최자 수동 인원 추가 및 10명 자동 채우기 (profiles 실제 컬럼명 반영)
# ---------------------------------------------------------
def get_unjoined_registered_profiles(guild_id: int, session_id: int, game: str) -> list[dict]:
    """해당 게임 프로필이 등록되어 있으나 현재 내전 세션에 아직 참가하지 않은 유저 목록을 반환합니다."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.discord_user_id,
                   p.discord_nickname,
                   p.riot_game_name,
                   p.riot_tagline,
                   p.solo_tier,
                   p.flex_tier,
                   p.competitive_tier,
                   p.main_position
            FROM profiles p
            WHERE p.guild_id = ?
              AND p.game = ?
              AND p.discord_user_id NOT IN (
                  SELECT discord_user_id
                  FROM inhouse_participants
                  WHERE session_id = ?
              )
            ORDER BY p.discord_nickname ASC
            """,
            (guild_id, game, session_id),
        ).fetchall()
        return [dict(r) for r in rows]


def auto_fill_inhouse_to_ten(guild_id: int, session_id: int) -> tuple[bool, str]:
    """
    1순위: 서버에 등록된 미참가 유저를 자동으로 참가시킴
    2순위: 그래도 10명이 안 되면 부족한 인원만큼 가상 테스트 프로필을 생성해 10명을 채움
    """
    from datetime import datetime, timezone

    session = get_inhouse_session_by_id(guild_id, session_id)
    if not session:
        return False, "존재하지 않는 내전입니다."

    game = session["game"]
    participants = get_inhouse_participants_with_profiles(guild_id, session_id)
    current_count = len(participants)

    if current_count >= 10:
        return False, "이미 10명이 모두 모집되었습니다."

    added_real = 0
    added_bots = 0

    # 1순위: 실제 등록된 미참가 서버원 먼저 추가
    unjoined = get_unjoined_registered_profiles(guild_id, session_id, game)
    for prof in unjoined:
        if current_count >= 10:
            break
        ok, _ = add_inhouse_participant(guild_id, session_id, prof["discord_user_id"])
        if ok:
            current_count += 1
            added_real += 1

    # 2순위: 여전히 10명 미만이면 가상 테스트 유저 생성 및 참가
    lol_positions = ["Top", "Jungle", "Mid", "AD carry", "Support"]
    val_positions = ["Duelist", "Initiator", "Controller", "Sentinel", "Flex"]
    sample_tiers = [
        "IRON I", "BRONZE II", "SILVER I", "GOLD III", "PLATINUM II",
        "EMERALD IV", "EMERALD I", "DIAMOND III", "MASTER", "GRANDMASTER",
    ]
    pos_list = lol_positions if game == "lol" else val_positions
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        bot_idx = 1
        while current_count < 10 and bot_idx <= 20:
            fake_user_id = 900000000000000000 + bot_idx
            pos = pos_list[(bot_idx - 1) % 5]
            tier = sample_tiers[(bot_idx - 1) % len(sample_tiers)]

            # 가상 유저 프로필을 profiles 스키마에 맞춰 등록
            conn.execute(
                """
                INSERT OR IGNORE INTO profiles (
                    guild_id, discord_user_id, game,
                    discord_nickname, riot_game_name, riot_tagline, server_location,
                    solo_tier, flex_tier, competitive_tier, main_position,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'Korea', ?, 'UNRANKED', ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    fake_user_id,
                    game,
                    f"테스트봇{bot_idx}",
                    f"TestBot{bot_idx}",
                    f"KR{bot_idx}",
                    tier,
                    tier,
                    pos,
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()

            ok, _ = add_inhouse_participant(guild_id, session_id, fake_user_id)
            if ok:
                current_count += 1
                added_bots += 1
            bot_idx += 1

    return True, f"자동 충원 완료! (등록 서버원 {added_real}명 + 가상 테스트봇 {added_bots}명 추가됨)"

def delete_user_profile(
    guild_id: int,
    discord_user_id: int,
    game: str | None = None,
) -> int:
    """특정 유저의 등록된 프로필(game이 None이거나 'all'이면 전체 게임, 아니면 해당 게임만)을 삭제하고 삭제된 행 수를 반환합니다."""
    with get_connection() as conn:
        if game is None or game == "all":
            cursor = conn.execute(
                """
                DELETE FROM profiles
                WHERE guild_id = ? AND discord_user_id = ?
                """,
                (guild_id, discord_user_id),
            )
        else:
            cursor = conn.execute(
                """
                DELETE FROM profiles
                WHERE guild_id = ? AND discord_user_id = ? AND game = ?
                """,
                (guild_id, discord_user_id, game),
            )
        conn.commit()
        return cursor.rowcount

def list_open_inhouse_sessions(guild_id: int) -> list[dict]:
    """해당 서버에서 현재 열려 있는(모집/진행 중인) 내전 세션 목록을 최신순으로 반환합니다."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM inhouse_sessions
            WHERE guild_id = ?
            ORDER BY session_id DESC
            """,
            (guild_id,),
        ).fetchall()
    return [dict(row) for row in rows]

def get_user_profile(
    guild_id: int,
    discord_user_id: int,
    game: str,
) -> dict | None:
    """특정 유저의 게임 프로필 1건을 조회합니다."""
    connection = get_connection()

    try:
        ensure_profile_custom_columns(connection)
        row = connection.execute(
            """
            SELECT
                guild_id,
                discord_user_id,
                game,
                discord_nickname,
                riot_game_name,
                riot_tagline,
                server_location,
                puuid,
                solo_tier,
                flex_tier,
                competitive_tier,
                custom_tier,
                main_position,
                sub_position,
                created_at,
                updated_at,
                last_api_sync
            FROM profiles
            WHERE guild_id = ?
              AND discord_user_id = ?
              AND game = ?
            """,
            (guild_id, discord_user_id, game),
        ).fetchone()

        return dict(row) if row is not None else None

    finally:
        connection.close()


def can_user_edit_profile(
    guild_id: int,
    actor_user_id: int,
    target_user_id: int,
    game: str,
) -> tuple[bool, str]:
    """
    프로필(체감 티어 등) 수정 권한을 확인합니다.
    1) 본인이면 항상 가능
    2) 본인이 아니더라도, target_user_id가 현재 해당 게임의 활성 내전에 참가 중이고,
       actor_user_id 역시 그 내전에 함께 참가 중(또는 주최자)이라면 수정 가능
    """
    if actor_user_id == target_user_id:
        return True, "본인 프로필"

    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT s.session_id, s.civilwar_number
            FROM inhouse_sessions s
            INNER JOIN inhouse_participants p_target
                ON s.session_id = p_target.session_id
            LEFT JOIN inhouse_participants p_actor
                ON s.session_id = p_actor.session_id
               AND p_actor.discord_user_id = ?
            WHERE s.guild_id = ?
              AND s.game = ?
              AND s.status NOT IN ('closed', 'ended', 'cancelled')
              AND p_target.discord_user_id = ?
              AND (p_actor.discord_user_id IS NOT NULL OR s.organizer_user_id = ?)
            ORDER BY s.session_id DESC
            LIMIT 1
            """,
            (actor_user_id, guild_id, game, target_user_id, actor_user_id),
        ).fetchone()

        if row is not None:
            return True, f"civilwar #{row['civilwar_number']} 내전 참가자 권한"

        return (
            False,
            "타인의 프로필은 조회만 가능합니다. (단, 같은 내전에 참가 중인 인원끼리는 서로의 체감 티어/프로필을 수정할 수 있습니다.)",
        )

    finally:
        connection.close()


def update_user_profile_custom_settings(
    guild_id: int,
    discord_user_id: int,
    game: str,
    *,
    custom_tier: str | None = ...,
    main_position: str | None = ...,
    sub_position: str | None = ...,
) -> dict | None:
    """
    유저 프로필의 체감 티어(custom_tier), 주 포지션(main_position), 부 포지션(sub_position)을 수정하고,
    현재 모집 중인 내전(open)에 참가 중이라면 해당 참가자 정보도 함께 갱신합니다.
    """
    connection = get_connection()

    try:
        ensure_profile_custom_columns(connection)
        current_time = datetime.now(timezone.utc).isoformat()

        updates = ["updated_at = ?"]
        params: list = [current_time]

        if custom_tier is not ...:
            updates.append("custom_tier = ?")
            params.append(custom_tier)

        if main_position is not ...:
            updates.append("main_position = ?")
            params.append(main_position)

        if sub_position is not ...:
            updates.append("sub_position = ?")
            params.append(sub_position)

        params.extend([guild_id, discord_user_id, game])

        connection.execute(
            f"""
            UPDATE profiles
            SET {', '.join(updates)}
            WHERE guild_id = ?
              AND discord_user_id = ?
              AND game = ?
            """,
            tuple(params),
        )

        # 현재 진행 중인 내전 참가자 테이블에도 동기화
        part_updates = []
        part_params: list = []

        if custom_tier is not ...:
            part_updates.append("custom_tier = ?")
            part_params.append(custom_tier)

        if main_position is not ...:
            part_updates.append("main_position = ?")
            part_updates.append("preferred_position = ?")
            part_params.extend([main_position, main_position])

        if sub_position is not ...:
            part_updates.append("sub_position = ?")
            part_params.append(sub_position)

        if part_updates:
            part_params.extend([guild_id, discord_user_id, game])
            connection.execute(
                f"""
                UPDATE inhouse_participants
                SET {', '.join(part_updates)}
                WHERE guild_id = ?
                  AND discord_user_id = ?
                  AND session_id IN (
                      SELECT session_id
                      FROM inhouse_sessions
                      WHERE guild_id = ?
                        AND game = ?
                        AND status IN ('closed', 'ended', 'cancelled')
                  )
                """,
                (
                    *part_params[:-3],
                    guild_id,
                    discord_user_id,
                    guild_id,
                    game,
                ),
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return get_user_profile(guild_id, discord_user_id, game)

def get_session_team_groups(guild_id: int, session_id: int) -> list[list[int]]:
    """해당 내전에 예약된 같은 팀 그룹 목록([[uid1, uid2], ...])을 반환합니다."""
    connection = get_connection()
    try:
        _ensure_column(connection, "inhouse_sessions", "team_groups_json", "TEXT DEFAULT '[]'")
        row = connection.execute(
            """
            SELECT team_groups_json
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        ).fetchone()

        if row is None or not row["team_groups_json"]:
            return []

        data = json.loads(row["team_groups_json"])
        if not isinstance(data, list):
            return []

        result: list[list[int]] = []
        for group in data:
            if isinstance(group, list):
                valid_ids = [int(x) for x in group]
                if len(valid_ids) >= 2:
                    result.append(valid_ids)
        return result
    except Exception:
        return []
    finally:
        connection.close()


def add_or_update_session_team_group(
    guild_id: int,
    session_id: int,
    selected_user_ids: list[int],
) -> tuple[bool, str, list[list[int]]]:
    """
    선택된 2~5명의 참가자를 같은 팀 그룹으로 묶습니다.
    기존에 다른 그룹에 속해 있던 인원이 포함되면 새 그룹으로 갱신합니다.
    """
    unique_ids = []
    for uid in selected_user_ids:
        if int(uid) not in unique_ids:
            unique_ids.append(int(uid))

    if len(unique_ids) < 2:
        return False, "같은 팀으로 묶으려면 최소 2명 이상을 선택해야 합니다.", []
    if len(unique_ids) > 5:
        return False, "한 팀의 최대 인원은 5명이므로 최대 5명까지만 묶을 수 있습니다.", []

    connection = get_connection()
    try:
        _ensure_column(connection, "inhouse_sessions", "team_groups_json", "TEXT DEFAULT '[]'")
        row = connection.execute(
            """
            SELECT team_groups_json
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ? AND status = 'open'
            """,
            (guild_id, session_id),
        ).fetchone()

        if row is None:
            return False, "진행 중인 모집 세션을 찾을 수 없습니다.", []

        try:
            existing_groups = json.loads(row["team_groups_json"] or "[]")
        except Exception:
            existing_groups = []

        # 새로 선택된 유저들을 기존 그룹에서 먼저 제외
        new_groups: list[list[int]] = []
        for g in existing_groups:
            rem = [int(u) for u in g if int(u) not in unique_ids]
            if len(rem) >= 2:
                new_groups.append(rem)

        new_groups.append(unique_ids)

        connection.execute(
            """
            UPDATE inhouse_sessions
            SET team_groups_json = ?
            WHERE guild_id = ? AND session_id = ?
            """,
            (json.dumps(new_groups), guild_id, session_id),
        )
        connection.commit()
        return True, f"{len(unique_ids)}명을 같은 팀으로 예약했습니다.", new_groups
    finally:
        connection.close()


def clear_session_team_groups(guild_id: int, session_id: int) -> None:
    """해당 내전의 모든 같은 팀 묶기 예약을 초기화합니다."""
    connection = get_connection()
    try:
        _ensure_column(connection, "inhouse_sessions", "team_groups_json", "TEXT DEFAULT '[]'")
        connection.execute(
            """
            UPDATE inhouse_sessions
            SET team_groups_json = '[]'
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )
        connection.commit()
    finally:
        connection.close()

def set_session_lobby_message(
    guild_id: int,
    session_id: int,
    channel_id: int,
    message_id: int,
) -> None:
    """내전 모집창(로비) 메시지의 채널 ID와 메시지 ID를 세션에 기록합니다."""
    connection = get_connection()
    try:
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(inhouse_sessions)").fetchall()
        }
        if "lobby_channel_id" not in existing_columns:
            connection.execute(
                "ALTER TABLE inhouse_sessions ADD COLUMN lobby_channel_id INTEGER"
            )
        if "lobby_message_id" not in existing_columns:
            connection.execute(
                "ALTER TABLE inhouse_sessions ADD COLUMN lobby_message_id INTEGER"
            )

        connection.execute(
            """
            UPDATE inhouse_sessions
            SET lobby_channel_id = ?,
                lobby_message_id = ?,
                updated_at = ?
            WHERE guild_id = ?
              AND session_id = ?
            """,
            (
                channel_id,
                message_id,
                datetime.now(timezone.utc).isoformat(),
                guild_id,
                session_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

# =========================================================
# 글로벌 개인 내전 전적 (서버 이동/신규 등록 시에도 영구 유지)
# =========================================================

def get_global_user_inhouse_stats(
    discord_user_id: int,
    game: str,
) -> dict:
    """특정 유저의 글로벌 내전 전적(전체 및 윗밸/황밸/아랫밸 상대 승패)을 조회합니다."""
    connection = get_connection()
    try:
        connection.execute(
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
        row = connection.execute(
            """
            SELECT *
            FROM global_user_inhouse_stats
            WHERE discord_user_id = ?
              AND game = ?
            """,
            (int(discord_user_id), game),
        ).fetchone()

        if row is None:
            return {
                "discord_user_id": int(discord_user_id),
                "game": game,
                "total_wins": 0,
                "total_losses": 0,
                "upper_wins": 0,
                "upper_losses": 0,
                "even_wins": 0,
                "even_losses": 0,
                "lower_wins": 0,
                "lower_losses": 0,
            }

        return dict(row)
    finally:
        connection.close()


def record_global_user_inhouse_result(
    game: str,
    player_records: list[dict],
) -> None:
    """
    세트 승패가 결정될 때 참가자 개개인의 승패 및 밸런스(윗밸/황밸/아랫밸 상대) 전적을 누적 기록합니다.
    player_records 항목 예시:
    {"discord_user_id": 123, "is_win": True, "matchup_type": "윗밸"}
    """
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
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

        current_time = datetime.now(timezone.utc).isoformat()

        for rec in player_records:
            uid = rec.get("discord_user_id", rec.get("user_id"))
            if uid is None:
                continue
            uid = int(uid)
            # 가상 테스트봇(900000000000000000번대)은 전적 기록에서 제외하려면 아래 조건 유지 (원치 않으면 주석 처리 가능)
            if 900000000000000000 <= uid <= 900000000000000999:
                continue

            is_win = bool(rec.get("is_win"))
            matchup_type = str(rec.get("matchup_type") or "황밸")

            t_win = 1 if is_win else 0
            t_loss = 0 if is_win else 1

            u_win = 1 if (is_win and matchup_type == "윗밸") else 0
            u_loss = 1 if (not is_win and matchup_type == "윗밸") else 0

            e_win = 1 if (is_win and matchup_type == "황밸") else 0
            e_loss = 1 if (not is_win and matchup_type == "황밸") else 0

            l_win = 1 if (is_win and matchup_type == "아랫밸") else 0
            l_loss = 1 if (not is_win and matchup_type == "아랫밸") else 0

            connection.execute(
                """
                INSERT INTO global_user_inhouse_stats (
                    discord_user_id, game,
                    total_wins, total_losses,
                    upper_wins, upper_losses,
                    even_wins, even_losses,
                    lower_wins, lower_losses,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(discord_user_id, game) DO UPDATE SET
                    total_wins = total_wins + excluded.total_wins,
                    total_losses = total_losses + excluded.total_losses,
                    upper_wins = upper_wins + excluded.upper_wins,
                    upper_losses = upper_losses + excluded.upper_losses,
                    even_wins = even_wins + excluded.even_wins,
                    even_losses = even_losses + excluded.even_losses,
                    lower_wins = lower_wins + excluded.lower_wins,
                    lower_losses = lower_losses + excluded.lower_losses,
                    updated_at = excluded.updated_at
                """,
                (
                    uid, game,
                    t_win, t_loss,
                    u_win, u_loss,
                    e_win, e_loss,
                    l_win, l_loss,
                    current_time,
                ),
            )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def reset_global_user_inhouse_stats(
    discord_user_id: int | None = None,
    game: str | None = None,
) -> int:
    """
    글로벌 내전 전적을 초기화(삭제)하고 삭제된 행 수를 반환합니다.
    - discord_user_id가 지정되면 해당 유저만, None이면 전체 유저 초기화
    - game이 'lol' 또는 'valorant'면 해당 게임만, None이거나 'all'이면 전체 게임 초기화
    """
    connection = get_connection()
    try:
        connection.execute(
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

        target_game = None if (game is None or game == "all") else game.lower()

        if discord_user_id is not None and target_game is not None:
            cursor = connection.execute(
                """
                DELETE FROM global_user_inhouse_stats
                WHERE discord_user_id = ? AND game = ?
                """,
                (int(discord_user_id), target_game),
            )
        elif discord_user_id is not None:
            cursor = connection.execute(
                """
                DELETE FROM global_user_inhouse_stats
                WHERE discord_user_id = ?
                """,
                (int(discord_user_id),),
            )
        elif target_game is not None:
            cursor = connection.execute(
                """
                DELETE FROM global_user_inhouse_stats
                WHERE game = ?
                """,
                (target_game,),
            )
        else:
            cursor = connection.execute(
                """
                DELETE FROM global_user_inhouse_stats
                """
            )

        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()
