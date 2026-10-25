import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "civilwarhelper.db"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    cursor = connection.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing_columns = {row["name"] for row in cursor.fetchall()}

    if column_name not in existing_columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def initialize_database() -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()

        # 1. 프로필 테이블
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                guild_id INTEGER NOT NULL,
                discord_user_id INTEGER NOT NULL,
                discord_nickname TEXT NOT NULL,
                game TEXT NOT NULL,
                riot_game_name TEXT NOT NULL,
                riot_tagline TEXT NOT NULL,
                server_location TEXT NOT NULL,
                solo_tier TEXT NOT NULL DEFAULT 'Not retrieved yet',
                flex_tier TEXT NOT NULL DEFAULT 'Not retrieved yet',
                competitive_tier TEXT NOT NULL DEFAULT 'Not retrieved yet',
                main_position TEXT NOT NULL DEFAULT 'Unknown',
                sub_position TEXT DEFAULT NULL,
                custom_tier TEXT DEFAULT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, discord_user_id, game)
            )
            """
        )

        # 2. 내전 세션 테이블
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS inhouse_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                civilwar_number INTEGER NOT NULL,
                game TEXT NOT NULL,
                organizer_user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                channel_id INTEGER,
                message_id INTEGER,
                balance_settings TEXT,
                team_groups_json TEXT DEFAULT '[]',
                fearless_data TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (guild_id, civilwar_number)
            )
            """
        )

        # 3. 내전 참가자 테이블
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS inhouse_participants (
                session_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                discord_user_id INTEGER NOT NULL,
                preferred_position TEXT,
                sub_position TEXT DEFAULT NULL,
                custom_tier TEXT DEFAULT NULL,
                assigned_team TEXT,
                assigned_position TEXT,
                joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, discord_user_id)
            )
            """
        )

        # 4. 글로벌 개인 내전 전적 테이블 (서버 무관 누적)
        cursor.execute(
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
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (discord_user_id, game)
            )
            """
        )

        # 기존 DB 호환을 위한 컬럼 자동 보강
        _ensure_column(connection, "profiles", "custom_tier", "TEXT DEFAULT NULL")
        _ensure_column(connection, "profiles", "sub_position", "TEXT DEFAULT NULL")

        _ensure_column(connection, "inhouse_sessions", "channel_id", "INTEGER")
        _ensure_column(connection, "inhouse_sessions", "message_id", "INTEGER")
        _ensure_column(connection, "inhouse_sessions", "balance_settings", "TEXT")
        _ensure_column(connection, "inhouse_sessions", "team_groups_json", "TEXT DEFAULT '[]'")
        _ensure_column(connection, "inhouse_sessions", "fearless_data", "TEXT DEFAULT NULL")

        _ensure_column(connection, "inhouse_participants", "preferred_position", "TEXT")
        _ensure_column(connection, "inhouse_participants", "sub_position", "TEXT DEFAULT NULL")
        _ensure_column(connection, "inhouse_participants", "custom_tier", "TEXT DEFAULT NULL")
        _ensure_column(connection, "inhouse_participants", "assigned_team", "TEXT")
        _ensure_column(connection, "inhouse_participants", "assigned_position", "TEXT")

        connection.commit()
    finally:
        connection.close()


# =====================================================================
# 프로필 등록 / 조회 / 수정 / 삭제
# =====================================================================

def upsert_profile(
    guild_id: int,
    discord_user_id: int,
    discord_nickname: str,
    game: str,
    riot_game_name: str,
    riot_tagline: str,
    server_location: str,
    solo_tier: str = "Not retrieved yet",
    flex_tier: str = "Not retrieved yet",
    competitive_tier: str = "Not retrieved yet",
    main_position: str = "Unknown",
) -> str:
    connection = get_connection()
    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT 1
            FROM profiles
            WHERE guild_id = ? AND discord_user_id = ? AND game = ?
            """,
            (guild_id, discord_user_id, game),
        )
        exists = cursor.fetchone() is not None

        if exists:
            cursor.execute(
                """
                UPDATE profiles
                SET discord_nickname = ?,
                    riot_game_name = ?,
                    riot_tagline = ?,
                    server_location = ?,
                    solo_tier = ?,
                    flex_tier = ?,
                    competitive_tier = ?,
                    main_position = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ? AND discord_user_id = ? AND game = ?
                """,
                (
                    discord_nickname,
                    riot_game_name,
                    riot_tagline,
                    server_location,
                    solo_tier,
                    flex_tier,
                    competitive_tier,
                    main_position,
                    guild_id,
                    discord_user_id,
                    game,
                ),
            )
            action = "updated"
        else:
            cursor.execute(
                """
                INSERT INTO profiles (
                    guild_id,
                    discord_user_id,
                    discord_nickname,
                    game,
                    riot_game_name,
                    riot_tagline,
                    server_location,
                    solo_tier,
                    flex_tier,
                    competitive_tier,
                    main_position
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    discord_user_id,
                    discord_nickname,
                    game,
                    riot_game_name,
                    riot_tagline,
                    server_location,
                    solo_tier,
                    flex_tier,
                    competitive_tier,
                    main_position,
                ),
            )
            action = "created"

        connection.commit()
        return action
    finally:
        connection.close()


def get_profiles_by_game(guild_id: int, game: str) -> list[dict]:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                guild_id,
                discord_user_id,
                discord_nickname,
                game,
                riot_game_name,
                riot_tagline,
                server_location,
                solo_tier,
                flex_tier,
                competitive_tier,
                main_position,
                sub_position,
                custom_tier,
                updated_at
            FROM profiles
            WHERE guild_id = ? AND game = ?
            ORDER BY LOWER(discord_nickname) ASC, discord_user_id ASC
            """,
            (guild_id, game),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_single_profile(
    guild_id: int,
    discord_user_id: int,
    game: str,
) -> dict | None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                guild_id,
                discord_user_id,
                discord_nickname,
                game,
                riot_game_name,
                riot_tagline,
                server_location,
                solo_tier,
                flex_tier,
                competitive_tier,
                main_position,
                sub_position,
                custom_tier,
                updated_at
            FROM profiles
            WHERE guild_id = ? AND discord_user_id = ? AND game = ?
            """,
            (guild_id, discord_user_id, game),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def get_user_profile(
    guild_id: int,
    discord_user_id: int,
    game: str,
) -> dict | None:
    return get_single_profile(guild_id, discord_user_id, game)


def update_lol_profile_stats(
    guild_id: int,
    discord_user_id: int,
    riot_game_name: str,
    riot_tagline: str,
    solo_tier: str,
    flex_tier: str,
    main_position: str,
) -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE profiles
            SET riot_game_name = ?,
                riot_tagline = ?,
                solo_tier = ?,
                flex_tier = ?,
                main_position = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE guild_id = ? AND discord_user_id = ? AND game = 'lol'
            """,
            (
                riot_game_name,
                riot_tagline,
                solo_tier,
                flex_tier,
                main_position,
                guild_id,
                discord_user_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def delete_user_profile(
    guild_id: int,
    discord_user_id: int,
    game: str | None = None,
) -> int:
    """특정 유저의 등록된 프로필(register 정보)을 DB에서 삭제하고 삭제된 행 수를 반환합니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        if game and game in ("lol", "valorant"):
            cursor.execute(
                """
                DELETE FROM profiles
                WHERE guild_id = ? AND discord_user_id = ? AND game = ?
                """,
                (guild_id, discord_user_id, game),
            )
        else:
            cursor.execute(
                """
                DELETE FROM profiles
                WHERE guild_id = ? AND discord_user_id = ?
                """,
                (guild_id, discord_user_id),
            )
        deleted_count = cursor.rowcount
        connection.commit()
        return deleted_count
    finally:
        connection.close()


def can_user_edit_profile(
    guild_id: int,
    actor_user_id: int,
    target_user_id: int,
    game: str,
) -> tuple[bool, str]:
    """
    프로필 수정 권한 확인:
    1) 본인인 경우 허용
    2) 현재 같은 게임의 활성 내전에 두 사람이 함께 속해 있는 경우(주최자 또는 같은 내전 참가자) 허용
    """
    if actor_user_id == target_user_id:
        return True, "본인 프로필"

    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT s.session_id, s.civilwar_number, s.organizer_user_id
            FROM inhouse_sessions s
            JOIN inhouse_participants p_target
              ON s.session_id = p_target.session_id
             AND p_target.discord_user_id = ?
            LEFT JOIN inhouse_participants p_actor
              ON s.session_id = p_actor.session_id
             AND p_actor.discord_user_id = ?
            WHERE s.guild_id = ?
              AND s.game = ?
              AND s.status NOT IN ('closed', 'ended', 'cancelled')
              AND (s.organizer_user_id = ? OR p_actor.discord_user_id IS NOT NULL)
            LIMIT 1
            """,
            (target_user_id, actor_user_id, guild_id, game, actor_user_id),
        )
        row = cursor.fetchone()
        if row is not None:
            return True, f"civilwar #{row['civilwar_number']} 함께 참여 중"

        return (
            False,
            "본인이거나 현재 같은 내전에 참여 중인 멤버(또는 주최자)만 프로필 설정을 변경할 수 있습니다.",
        )
    finally:
        connection.close()


_UNSET = object()


def update_user_profile_custom_settings(
    guild_id: int,
    discord_user_id: int,
    game: str,
    custom_tier: str | None | object = _UNSET,
    main_position: str | object = _UNSET,
    sub_position: str | None | object = _UNSET,
) -> dict | None:
    """프로필의 체감 티어 / 주 포지션 / 부 포지션을 업데이트하고 진행 중인 내전 참가자 정보에도 동기화합니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()

        updates: list[str] = []
        params: list[object] = []

        if custom_tier is not _UNSET:
            updates.append("custom_tier = ?")
            params.append(custom_tier)
        if main_position is not _UNSET:
            updates.append("main_position = ?")
            params.append(main_position)
        if sub_position is not _UNSET:
            updates.append("sub_position = ?")
            params.append(sub_position)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.extend([guild_id, discord_user_id, game])
            cursor.execute(
                f"""
                UPDATE profiles
                SET {', '.join(updates)}
                WHERE guild_id = ? AND discord_user_id = ? AND game = ?
                """,
                tuple(params),
            )

            # 현재 진행 중인 동일 게임 내전 참가자 테이블에도 즉시 반영
            part_updates: list[str] = []
            part_params: list[object] = []
            if custom_tier is not _UNSET:
                part_updates.append("custom_tier = ?")
                part_params.append(custom_tier)
            if main_position is not _UNSET:
                part_updates.append("preferred_position = ?")
                part_params.append(main_position)
            if sub_position is not _UNSET:
                part_updates.append("sub_position = ?")
                part_params.append(sub_position)

            if part_updates:
                part_params.extend([guild_id, discord_user_id, guild_id, game])
                cursor.execute(
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
                            AND status NOT IN ('closed', 'ended', 'cancelled')
                      )
                    """,
                    tuple(part_params),
                )

            connection.commit()

        cursor.execute(
            """
            SELECT *
            FROM profiles
            WHERE guild_id = ? AND discord_user_id = ? AND game = ?
            """,
            (guild_id, discord_user_id, game),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


# =====================================================================
# 내전 세션 생성 / 조회 / 관리
# =====================================================================

def create_inhouse_session(
    guild_id: int,
    game: str,
    organizer_user_id: int,
) -> dict:
    connection = get_connection()
    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT COALESCE(MAX(civilwar_number), 0) + 1 AS next_num
            FROM inhouse_sessions
            WHERE guild_id = ?
            """,
            (guild_id,),
        )
        next_num = cursor.fetchone()["next_num"]

        cursor.execute(
            """
            INSERT INTO inhouse_sessions (
                guild_id,
                civilwar_number,
                game,
                organizer_user_id,
                status
            )
            VALUES (?, ?, ?, ?, 'active')
            """,
            (guild_id, next_num, game, organizer_user_id),
        )
        session_id = cursor.lastrowid
        connection.commit()

        return {
            "session_id": session_id,
            "guild_id": guild_id,
            "civilwar_number": next_num,
            "game": game,
            "organizer_user_id": organizer_user_id,
            "status": "active",
            "channel_id": None,
            "message_id": None,
            "balance_settings": None,
        }
    finally:
        connection.close()


def save_inhouse_lobby_message(
    guild_id: int,
    session_id: int,
    channel_id: int,
    message_id: int,
) -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE inhouse_sessions
            SET channel_id = ?, message_id = ?
            WHERE guild_id = ? AND session_id = ?
            """,
            (channel_id, message_id, guild_id, session_id),
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
    save_inhouse_lobby_message(guild_id, session_id, channel_id, message_id)


def get_active_inhouse_sessions(guild_id: int) -> list[dict]:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                session_id,
                guild_id,
                civilwar_number,
                game,
                organizer_user_id,
                status,
                channel_id,
                message_id,
                balance_settings,
                created_at
            FROM inhouse_sessions
            WHERE guild_id = ? AND status = 'active'
            ORDER BY civilwar_number ASC
            """,
            (guild_id,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_open_inhouse_sessions(guild_id: int) -> list[dict]:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT *
            FROM inhouse_sessions
            WHERE guild_id = ?
              AND (status IS NULL OR status NOT IN ('closed', 'ended', 'cancelled'))
            ORDER BY session_id DESC
            """,
            (guild_id,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_inhouse_session_by_number(
    guild_id: int,
    civilwar_number: int,
) -> dict | None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                session_id,
                guild_id,
                civilwar_number,
                game,
                organizer_user_id,
                status,
                channel_id,
                message_id,
                balance_settings,
                created_at
            FROM inhouse_sessions
            WHERE guild_id = ? AND civilwar_number = ? AND status = 'active'
            """,
            (guild_id, civilwar_number),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def get_inhouse_session_by_id(
    guild_id: int,
    session_id: int,
) -> dict | None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                session_id,
                guild_id,
                civilwar_number,
                game,
                organizer_user_id,
                status,
                channel_id,
                message_id,
                balance_settings,
                created_at
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ? AND status = 'active'
            """,
            (guild_id, session_id),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def get_inhouse_session(guild_id: int, session_id: int) -> dict | None:
    return get_inhouse_session_by_id(guild_id, session_id)


def delete_inhouse_session(guild_id: int, session_id: int) -> bool:
    connection = get_connection()
    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM inhouse_participants
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )

        cursor.execute(
            """
            DELETE FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )

        deleted = cursor.rowcount > 0
        connection.commit()
        return deleted
    finally:
        connection.close()


def transfer_inhouse_organizer(
    guild_id: int,
    session_id: int,
    new_organizer_user_id: int,
) -> bool:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE inhouse_sessions
            SET organizer_user_id = ?
            WHERE guild_id = ? AND session_id = ? AND status = 'active'
            """,
            (new_organizer_user_id, guild_id, session_id),
        )
        updated = cursor.rowcount > 0
        connection.commit()
        return updated
    finally:
        connection.close()


# =====================================================================
# 내전 참가자 추가 / 제외 / 교체 / 포지션 설정
# =====================================================================

def add_inhouse_participant(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
) -> tuple[bool, str]:
    connection = get_connection()
    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT game, civilwar_number
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ? AND status = 'active'
            """,
            (guild_id, session_id),
        )
        session_row = cursor.fetchone()
        if session_row is None:
            return False, "해당 내전 세션을 찾을 수 없거나 이미 종료되었습니다."

        game = session_row["game"]
        game_label = "League of Legends" if game == "lol" else "VALORANT"

        cursor.execute(
            """
            SELECT main_position, sub_position, custom_tier
            FROM profiles
            WHERE guild_id = ? AND discord_user_id = ? AND game = ?
            """,
            (guild_id, discord_user_id, game),
        )
        profile_row = cursor.fetchone()
        if profile_row is None:
            return (
                False,
                f"이 유저는 **{game_label}** 프로필이 등록되어 있지 않습니다. 먼저 `/register`로 등록해 주세요.",
            )

        cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM inhouse_participants
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )
        current_count = cursor.fetchone()["cnt"]
        if current_count >= 10:
            return False, "이미 참가자가 10명으로 가득 찼습니다."

        cursor.execute(
            """
            SELECT 1
            FROM inhouse_participants
            WHERE session_id = ? AND discord_user_id = ?
            """,
            (session_id, discord_user_id),
        )
        if cursor.fetchone() is not None:
            return False, "이미 이 내전에 참가 중인 유저입니다."

        default_pos = profile_row["main_position"] or "Unknown"
        if default_pos == "Unknown":
            default_pos = "Top" if game == "lol" else "Flex"

        default_sub_pos = profile_row["sub_position"]
        default_custom_tier = profile_row["custom_tier"]

        cursor.execute(
            """
            INSERT INTO inhouse_participants (
                session_id,
                guild_id,
                discord_user_id,
                preferred_position,
                sub_position,
                custom_tier
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                guild_id,
                discord_user_id,
                default_pos,
                default_sub_pos,
                default_custom_tier,
            ),
        )
        connection.commit()
        return True, "참가자가 추가되었습니다."
    finally:
        connection.close()


def remove_inhouse_participant(
    session_id: int,
    discord_user_id: int,
    guild_id: int | None = None,
) -> tuple[bool, str]:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        if guild_id is not None:
            cursor.execute(
                """
                DELETE FROM inhouse_participants
                WHERE guild_id = ? AND session_id = ? AND discord_user_id = ?
                """,
                (guild_id, session_id, discord_user_id),
            )
        else:
            cursor.execute(
                """
                DELETE FROM inhouse_participants
                WHERE session_id = ? AND discord_user_id = ?
                """,
                (session_id, discord_user_id),
            )

        removed = cursor.rowcount > 0
        connection.commit()
        if not removed:
            return False, "현재 이 내전에 참가 중이지 않은 유저입니다."
        return True, "내전 참가가 취소(제외)되었습니다."
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
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT game
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ? AND status = 'active'
            """,
            (guild_id, session_id),
        )
        session_row = cursor.fetchone()
        if session_row is None:
            return False, "해당 내전 세션을 찾을 수 없습니다."

        game = session_row["game"]
        game_label = "League of Legends" if game == "lol" else "VALORANT"

        cursor.execute(
            """
            SELECT 1
            FROM inhouse_participants
            WHERE session_id = ? AND discord_user_id = ?
            """,
            (session_id, old_user_id),
        )
        if cursor.fetchone() is None:
            return False, "교체 대상(기존 유저)이 현재 내전 참가자가 아닙니다."

        cursor.execute(
            """
            SELECT 1
            FROM inhouse_participants
            WHERE session_id = ? AND discord_user_id = ?
            """,
            (session_id, new_user_id),
        )
        if cursor.fetchone() is not None:
            return False, "새로 투입할 유저가 이미 이 내전에 참가 중입니다."

        cursor.execute(
            """
            SELECT main_position, sub_position, custom_tier
            FROM profiles
            WHERE guild_id = ? AND discord_user_id = ? AND game = ?
            """,
            (guild_id, new_user_id, game),
        )
        profile_row = cursor.fetchone()
        if profile_row is None:
            return (
                False,
                f"새로 투입할 유저는 **{game_label}** 프로필이 등록되어 있지 않습니다. 먼저 `/register`로 등록해 주세요.",
            )

        default_pos = profile_row["main_position"] or "Unknown"
        if default_pos == "Unknown":
            default_pos = "Top" if game == "lol" else "Flex"

        cursor.execute(
            """
            DELETE FROM inhouse_participants
            WHERE session_id = ? AND discord_user_id = ?
            """,
            (session_id, old_user_id),
        )

        cursor.execute(
            """
            INSERT INTO inhouse_participants (
                session_id,
                guild_id,
                discord_user_id,
                preferred_position,
                sub_position,
                custom_tier
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                guild_id,
                new_user_id,
                default_pos,
                profile_row["sub_position"],
                profile_row["custom_tier"],
            ),
        )
        connection.commit()
        return True, "참가자 교체가 완료되었습니다."
    finally:
        connection.close()


def update_inhouse_participant_position(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    preferred_position: str,
) -> tuple[bool, str]:
    """참가자의 주 포지션을 변경하고 프로필(profiles) 테이블에도 함께 저장합니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT sub_position
            FROM inhouse_participants
            WHERE guild_id = ? AND session_id = ? AND discord_user_id = ?
            """,
            (guild_id, session_id, discord_user_id),
        )
        row = cursor.fetchone()
        if row is None:
            return False, "먼저 **내전 참가** 버튼을 눌러 참가한 뒤에 포지션을 변경할 수 있습니다."

        current_sub = row["sub_position"]
        new_sub = None if current_sub == preferred_position else current_sub

        cursor.execute(
            """
            UPDATE inhouse_participants
            SET preferred_position = ?, sub_position = ?
            WHERE guild_id = ? AND session_id = ? AND discord_user_id = ?
            """,
            (preferred_position, new_sub, guild_id, session_id, discord_user_id),
        )

        cursor.execute(
            """
            SELECT game FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )
        s_row = cursor.fetchone()
        if s_row is not None:
            cursor.execute(
                """
                UPDATE profiles
                SET main_position = ?, sub_position = ?
                WHERE guild_id = ? AND discord_user_id = ? AND game = ?
                """,
                (preferred_position, new_sub, guild_id, discord_user_id, s_row["game"]),
            )

        connection.commit()
        return True, f"주 포지션이 **{preferred_position}**(으)로 설정되었습니다."
    finally:
        connection.close()


def update_inhouse_participant_sub_position(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    sub_position: str | None,
) -> tuple[bool, str]:
    """참가자의 부 포지션을 변경하고 프로필(profiles) 테이블에도 함께 저장합니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT preferred_position
            FROM inhouse_participants
            WHERE guild_id = ? AND session_id = ? AND discord_user_id = ?
            """,
            (guild_id, session_id, discord_user_id),
        )
        row = cursor.fetchone()
        if row is None:
            return False, "먼저 **내전 참가** 버튼을 눌러 참가한 뒤에 부 포지션을 설정할 수 있습니다."

        if sub_position and row["preferred_position"] == sub_position:
            return False, "주 포지션과 동일한 포지션은 부 포지션으로 선택할 수 없습니다."

        cursor.execute(
            """
            UPDATE inhouse_participants
            SET sub_position = ?
            WHERE guild_id = ? AND session_id = ? AND discord_user_id = ?
            """,
            (sub_position, guild_id, session_id, discord_user_id),
        )

        cursor.execute(
            """
            SELECT game FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )
        s_row = cursor.fetchone()
        if s_row is not None:
            cursor.execute(
                """
                UPDATE profiles
                SET sub_position = ?
                WHERE guild_id = ? AND discord_user_id = ? AND game = ?
                """,
                (sub_position, guild_id, discord_user_id, s_row["game"]),
            )

        connection.commit()
        label = sub_position if sub_position else "선택안함"
        return True, f"부 포지션이 **{label}**(으)로 설정되었습니다."
    finally:
        connection.close()


def get_inhouse_participants_with_profiles(
    guild_id: int,
    session_id: int,
) -> list[dict]:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                p.session_id,
                p.guild_id,
                p.discord_user_id,
                p.preferred_position,
                COALESCE(p.sub_position, pr.sub_position) AS sub_position,
                COALESCE(p.custom_tier, pr.custom_tier) AS custom_tier,
                p.assigned_team,
                p.assigned_position,
                p.joined_at,
                pr.discord_nickname,
                pr.riot_game_name,
                pr.riot_tagline,
                pr.server_location,
                pr.solo_tier,
                pr.flex_tier,
                pr.competitive_tier,
                pr.main_position
            FROM inhouse_participants p
            JOIN inhouse_sessions s
                ON p.session_id = s.session_id AND p.guild_id = s.guild_id
            LEFT JOIN profiles pr
                ON p.guild_id = pr.guild_id
               AND p.discord_user_id = pr.discord_user_id
               AND s.game = pr.game
            WHERE p.guild_id = ? AND p.session_id = ?
            ORDER BY p.joined_at ASC, p.discord_user_id ASC
            """,
            (guild_id, session_id),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


# =====================================================================
# 팀 배정 / 밸런스 설정 / 진영 및 선수 스왑
# =====================================================================

def save_team_assignments(
    guild_id: int,
    session_id: int,
    assignments: list[dict],
) -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        for item in assignments:
            uid = item.get("discord_user_id", item.get("user_id"))
            cursor.execute(
                """
                UPDATE inhouse_participants
                SET assigned_team = ?,
                    assigned_position = ?
                WHERE guild_id = ? AND session_id = ? AND discord_user_id = ?
                """,
                (
                    item["assigned_team"],
                    item["assigned_position"],
                    guild_id,
                    session_id,
                    uid,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def get_session_balance_settings(
    guild_id: int,
    session_id: int,
    positions: list[str],
) -> dict[str, str]:
    default_map = {pos: "황밸" for pos in positions}
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT balance_settings
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )
        row = cursor.fetchone()
        if row and row["balance_settings"]:
            try:
                loaded = json.loads(row["balance_settings"])
                if isinstance(loaded, dict):
                    for pos in positions:
                        if loaded.get(pos) in ("황밸", "윗밸", "아랫밸"):
                            default_map[pos] = loaded[pos]
            except Exception:
                pass
        return default_map
    finally:
        connection.close()


def save_session_balance_settings(
    guild_id: int,
    session_id: int,
    settings: dict[str, str],
) -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE inhouse_sessions
            SET balance_settings = ?
            WHERE guild_id = ? AND session_id = ?
            """,
            (json.dumps(settings, ensure_ascii=False), guild_id, session_id),
        )
        connection.commit()
    finally:
        connection.close()


def swap_two_participants_team(
    session_id: int,
    user_a_id: int,
    user_b_id: int,
    guild_id: int | None = None,
) -> bool:
    """임의의 두 참가자의 배정된 팀(RED/BLUE)과 배정된 포지션을 서로 맞바꿉니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT discord_user_id, assigned_team, assigned_position
            FROM inhouse_participants
            WHERE session_id = ? AND discord_user_id IN (?, ?)
            """,
            (session_id, user_a_id, user_b_id),
        )
        rows = cursor.fetchall()
        if len(rows) != 2:
            return False

        info = {row["discord_user_id"]: dict(row) for row in rows}
        a_info = info.get(user_a_id)
        b_info = info.get(user_b_id)
        if not a_info or not b_info:
            return False

        cursor.execute(
            """
            UPDATE inhouse_participants
            SET assigned_team = ?, assigned_position = ?
            WHERE session_id = ? AND discord_user_id = ?
            """,
            (
                b_info["assigned_team"],
                b_info["assigned_position"],
                session_id,
                user_a_id,
            ),
        )
        cursor.execute(
            """
            UPDATE inhouse_participants
            SET assigned_team = ?, assigned_position = ?
            WHERE session_id = ? AND discord_user_id = ?
            """,
            (
                a_info["assigned_team"],
                a_info["assigned_position"],
                session_id,
                user_b_id,
            ),
        )
        connection.commit()
        return True
    finally:
        connection.close()


def swap_entire_red_blue_teams(
    guild_id: int,
    session_id: int,
) -> None:
    """레드 팀과 블루 팀 전체의 진영(RED <-> BLUE)을 서로 맞바꾸고 밸런스 방향 설정도 반전합니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE inhouse_participants
            SET assigned_team = CASE
                WHEN assigned_team = 'RED' THEN 'BLUE'
                WHEN assigned_team = 'BLUE' THEN 'RED'
                ELSE assigned_team
            END
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )

        cursor.execute(
            """
            SELECT balance_settings
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )
        row = cursor.fetchone()
        if row and row["balance_settings"]:
            try:
                loaded = json.loads(row["balance_settings"])
                if isinstance(loaded, dict):
                    flipped = {}
                    for pos, mode in loaded.items():
                        if mode == "윗밸":
                            flipped[pos] = "아랫밸"
                        elif mode == "아랫밸":
                            flipped[pos] = "윗밸"
                        else:
                            flipped[pos] = mode
                    cursor.execute(
                        """
                        UPDATE inhouse_sessions
                        SET balance_settings = ?
                        WHERE guild_id = ? AND session_id = ?
                        """,
                        (
                            json.dumps(flipped, ensure_ascii=False),
                            guild_id,
                            session_id,
                        ),
                    )
            except Exception:
                pass

        connection.commit()
    finally:
        connection.close()


def flip_all_teams_red_blue(guild_id: int, session_id: int) -> None:
    swap_entire_red_blue_teams(guild_id, session_id)


# =====================================================================
# 피어리스(Fearless) 및 세트 승패 기록 관리
# =====================================================================

def get_fearless_state(guild_id: int, session_id: int) -> dict:
    """세션의 세트 진행도, 승패 결과, 피어리스 활성화 여부 및 세트별 사용 챔피언 목록을 반환합니다."""
    default_state = {
        "enabled": False,
        "current_set": 1,
        "sets": {},     # {"2": {"red": [...], "blue": [...], "extra": [...]}, ...}
        "results": {},  # {"1": "RED", "2": "BLUE", ...}
    }
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT fearless_data
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )
        row = cursor.fetchone()
        if not row or not row["fearless_data"]:
            return default_state

        try:
            data = json.loads(row["fearless_data"])
            return {
                "enabled": bool(data.get("enabled", False)),
                "current_set": int(data.get("current_set", 1)),
                "sets": dict(data.get("sets", {})),
                "results": dict(data.get("results", {})),
            }
        except Exception:
            return default_state
    finally:
        connection.close()


def _save_fearless_payload(guild_id: int, session_id: int, payload: dict) -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE inhouse_sessions
            SET fearless_data = ?
            WHERE guild_id = ? AND session_id = ?
            """,
            (json.dumps(payload, ensure_ascii=False), guild_id, session_id),
        )
        connection.commit()
    finally:
        connection.close()


def toggle_fearless_mode(guild_id: int, session_id: int) -> dict:
    state = get_fearless_state(guild_id, session_id)
    state["enabled"] = not state["enabled"]
    _save_fearless_payload(guild_id, session_id, state)
    return state


def record_set_winner(
    guild_id: int,
    session_id: int,
    winner_side: str,
) -> dict:
    """현재 세트의 승리 팀('RED' 또는 'BLUE')을 기록하고 다음 세트로 진행도를 넘깁니다."""
    state = get_fearless_state(guild_id, session_id)
    cur_set = state["current_set"]
    state["results"][str(cur_set)] = winner_side
    state["current_set"] = cur_set + 1
    _save_fearless_payload(guild_id, session_id, state)
    return state


def save_fearless_set_record(
    guild_id: int,
    session_id: int,
    set_number: int,
    red_champions: list[str],
    blue_champions: list[str],
    extra_bans: list[str],
) -> dict:
    state = get_fearless_state(guild_id, session_id)
    state["enabled"] = True
    state["sets"][str(set_number)] = {
        "red": red_champions,
        "blue": blue_champions,
        "extra": extra_bans,
    }
    _save_fearless_payload(guild_id, session_id, state)
    return state


def clear_fearless_records(guild_id: int, session_id: int) -> dict:
    state = get_fearless_state(guild_id, session_id)
    state["sets"] = {}
    _save_fearless_payload(guild_id, session_id, state)
    return state


# =====================================================================
# 모집 보조 기능 (미참가 유저 조회 / 10명 자동 채우기 / 같은 팀 그룹 예약)
# =====================================================================

def get_unjoined_registered_profiles(
    guild_id: int,
    session_id: int,
    game: str,
) -> list[dict]:
    """해당 게임에 등록되어 있으나 현재 내전 세션에 참가하지 않은 유저 프로필 목록을 반환합니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT pr.*
            FROM profiles pr
            WHERE pr.guild_id = ?
              AND pr.game = ?
              AND pr.discord_user_id NOT IN (
                  SELECT p.discord_user_id
                  FROM inhouse_participants p
                  WHERE p.guild_id = ? AND p.session_id = ?
              )
            ORDER BY pr.discord_nickname COLLATE NOCASE ASC
            """,
            (guild_id, game, guild_id, session_id),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        connection.close()


def auto_fill_inhouse_to_ten(
    guild_id: int,
    session_id: int,
    game: str,
) -> tuple[bool, str, list[dict]]:
    """현재 내전 참가자가 10명이 될 때까지 미참가 등록 유저(부족 시 테스트 봇)를 자동으로 채웁니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM inhouse_participants
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )
        current_count = int(cursor.fetchone()["cnt"])
    finally:
        connection.close()

    if current_count >= 10:
        return False, "이미 참가자가 10명으로 가득 차 있습니다.", []

    needed = 10 - current_count
    candidates = get_unjoined_registered_profiles(guild_id, session_id, game)

    added_users: list[dict] = []
    for prof in candidates:
        if len(added_users) >= needed:
            break
        ok, _ = add_inhouse_participant(
            guild_id=guild_id,
            session_id=session_id,
            discord_user_id=int(prof["discord_user_id"]),
        )
        if ok:
            added_users.append(prof)

    still_needed = needed - len(added_users)
    if still_needed > 0:
        lol_positions = ["Top", "Jungle", "Mid", "AD carry", "Support"]
        val_positions = ["Duelist", "Initiator", "Controller", "Sentinel", "Flex"]
        lol_tiers = [
            ("Silver II", "Silver III"),
            ("Gold IV", "Silver I"),
            ("Gold II", "Gold III"),
            ("Platinum IV", "Gold I"),
            ("Platinum II", "Platinum III"),
            ("Emerald IV", "Platinum I"),
            ("Emerald II", "Emerald III"),
            ("Diamond IV", "Emerald I"),
        ]
        val_tiers = [
            "Silver 2",
            "Gold 1",
            "Gold 3",
            "Platinum 2",
            "Diamond 1",
            "Ascendant 1",
        ]

        connection = get_connection()
        try:
            cursor = connection.cursor()
            for idx in range(1, 25):
                if still_needed <= 0:
                    break
                dummy_uid = 900000000000000000 + idx
                cursor.execute(
                    """
                    SELECT 1 FROM inhouse_participants
                    WHERE guild_id = ? AND session_id = ? AND discord_user_id = ?
                    """,
                    (guild_id, session_id, dummy_uid),
                )
                if cursor.fetchone() is not None:
                    continue

                if game == "lol":
                    main_pos = lol_positions[(idx - 1) % len(lol_positions)]
                    sub_pos = lol_positions[idx % len(lol_positions)]
                    solo_t, flex_t = lol_tiers[(idx - 1) % len(lol_tiers)]
                    comp_t = "Unranked"
                else:
                    main_pos = val_positions[(idx - 1) % len(val_positions)]
                    sub_pos = val_positions[idx % len(val_positions)]
                    solo_t, flex_t = "Unranked", "Unranked"
                    comp_t = val_tiers[(idx - 1) % len(val_tiers)]

                bot_nick = f"테스트봇{idx}호"
                riot_name = f"TestBot{idx}"
                riot_tag = "KR1"

                cursor.execute(
                    """
                    INSERT INTO profiles (
                        guild_id, discord_user_id, discord_nickname, game,
                        riot_game_name, riot_tagline, server_location,
                        solo_tier, flex_tier, competitive_tier, main_position, sub_position
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'KR', ?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, discord_user_id, game) DO UPDATE SET
                        discord_nickname = excluded.discord_nickname,
                        solo_tier = excluded.solo_tier,
                        flex_tier = excluded.flex_tier,
                        competitive_tier = excluded.competitive_tier,
                        main_position = excluded.main_position,
                        sub_position = excluded.sub_position
                    """,
                    (
                        guild_id,
                        dummy_uid,
                        bot_nick,
                        game,
                        riot_name,
                        riot_tag,
                        solo_t,
                        flex_t,
                        comp_t,
                        main_pos,
                        sub_pos,
                    ),
                )

                cursor.execute(
                    """
                    INSERT INTO inhouse_participants (
                        session_id, guild_id, discord_user_id, preferred_position, sub_position
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, guild_id, dummy_uid, main_pos, sub_pos),
                )

                added_users.append(
                    {
                        "discord_user_id": dummy_uid,
                        "discord_nickname": bot_nick,
                        "riot_game_name": riot_name,
                        "riot_tagline": riot_tag,
                    }
                )
                still_needed -= 1

            connection.commit()
        finally:
            connection.close()

    if not added_users:
        return False, "추가할 수 있는 인원이 없습니다.", []

    return True, f"총 **{len(added_users)}명**이 자동으로 채워져 10명이 완성되었습니다!", added_users


def get_session_team_groups(guild_id: int, session_id: int) -> list[list[int]]:
    """해당 내전 세션에 설정된 '같은 팀 묶기 그룹' 목록([[uid1, uid2], ...])을 반환합니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT team_groups_json
            FROM inhouse_sessions
            WHERE guild_id = ? AND session_id = ?
            """,
            (guild_id, session_id),
        )
        row = cursor.fetchone()
        if not row or not row["team_groups_json"]:
            return []
        try:
            data = json.loads(row["team_groups_json"])
            if isinstance(data, list):
                return [
                    [int(u) for u in grp if isinstance(u, (int, str))]
                    for grp in data
                    if isinstance(grp, list) and len(grp) >= 2
                ]
        except Exception:
            pass
        return []
    finally:
        connection.close()


def save_session_team_groups(
    guild_id: int,
    session_id: int,
    groups: list[list[int]],
) -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE inhouse_sessions
            SET team_groups_json = ?
            WHERE guild_id = ? AND session_id = ?
            """,
            (json.dumps(groups), guild_id, session_id),
        )
        connection.commit()
    finally:
        connection.close()


def add_session_team_group(
    guild_id: int,
    session_id: int,
    user_ids: list[int],
) -> tuple[bool, str, list[list[int]]]:
    """선택한 2~5명을 하나의 같은 팀 그룹으로 묶습니다. 기존 다른 그룹에 속해 있던 인원은 새 그룹으로 이동합니다."""
    clean_ids = []
    for uid in user_ids:
        uid_int = int(uid)
        if uid_int not in clean_ids:
            clean_ids.append(uid_int)

    if len(clean_ids) < 2 or len(clean_ids) > 5:
        return (
            False,
            "같은 팀으로 묶을 인원은 **최소 2명 ~ 최대 5명**이어야 합니다.",
            get_session_team_groups(guild_id, session_id),
        )

    existing = get_session_team_groups(guild_id, session_id)
    new_groups: list[list[int]] = []

    for grp in existing:
        rem = [u for u in grp if u not in clean_ids]
        if len(rem) >= 2:
            new_groups.append(rem)

    new_groups.append(clean_ids)
    save_session_team_groups(guild_id, session_id, new_groups)
    return (
        True,
        f"선택한 **{len(clean_ids)}명**이 같은 팀 그룹으로 설정되었습니다.",
        new_groups,
    )


def clear_session_team_groups(guild_id: int, session_id: int) -> None:
    save_session_team_groups(guild_id, session_id, [])


# =====================================================================
# 글로벌 개인 내전 전적 (서버 무관 누적) 조회 / 기록 / 초기화
# =====================================================================

def get_global_user_inhouse_stats(discord_user_id: int, game: str) -> dict:
    """특정 유저의 게임별 글로벌 내전 통산 전적(전체 / 윗밸 / 황밸 / 아랫밸)을 반환합니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                total_wins,
                total_losses,
                upper_wins,
                upper_losses,
                even_wins,
                even_losses,
                lower_wins,
                lower_losses
            FROM global_user_inhouse_stats
            WHERE discord_user_id = ? AND game = ?
            """,
            (int(discord_user_id), str(game).lower()),
        )
        row = cursor.fetchone()
        if row is None:
            return {
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
    """세트 종료 시 참가자별 승/패 및 밸런스 구도('윗밸', '황밸', '아랫밸')를 글로벌 전적에 누적합니다."""
    game_key = str(game).lower()
    connection = get_connection()
    try:
        cursor = connection.cursor()
        for rec in player_records:
            uid = rec.get("discord_user_id", rec.get("user_id"))
            if uid is None:
                continue
            uid = int(uid)
            # 자동 채우기 테스트 봇(900000000000000000 이상)은 통산 전적 기록 제외
            if uid >= 900000000000000000:
                continue

            is_win = bool(rec.get("is_win"))
            matchup = str(rec.get("matchup_type") or "황밸")

            t_win = 1 if is_win else 0
            t_loss = 0 if is_win else 1

            u_win = 1 if (matchup == "윗밸" and is_win) else 0
            u_loss = 1 if (matchup == "윗밸" and not is_win) else 0

            e_win = 1 if (matchup == "황밸" and is_win) else 0
            e_loss = 1 if (matchup == "황밸" and not is_win) else 0

            l_win = 1 if (matchup == "아랫밸" and is_win) else 0
            l_loss = 1 if (matchup == "아랫밸" and not is_win) else 0

            cursor.execute(
                """
                INSERT INTO global_user_inhouse_stats (
                    discord_user_id,
                    game,
                    total_wins,
                    total_losses,
                    upper_wins,
                    upper_losses,
                    even_wins,
                    even_losses,
                    lower_wins,
                    lower_losses,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(discord_user_id, game) DO UPDATE SET
                    total_wins = total_wins + excluded.total_wins,
                    total_losses = total_losses + excluded.total_losses,
                    upper_wins = upper_wins + excluded.upper_wins,
                    upper_losses = upper_losses + excluded.upper_losses,
                    even_wins = even_wins + excluded.even_wins,
                    even_losses = even_losses + excluded.even_losses,
                    lower_wins = lower_wins + excluded.lower_wins,
                    lower_losses = lower_losses + excluded.lower_losses,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    uid,
                    game_key,
                    t_win,
                    t_loss,
                    u_win,
                    u_loss,
                    e_win,
                    e_loss,
                    l_win,
                    l_loss,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def reset_global_user_inhouse_stats(
    discord_user_id: int | None = None,
    game: str | None = None,
) -> int:
    """글로벌 개인 내전 전적을 초기화(삭제)하고 초기화된 행 수를 반환합니다."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        game_key = str(game).lower() if game else "all"

        if discord_user_id is not None and game_key in ("lol", "valorant"):
            cursor.execute(
                """
                DELETE FROM global_user_inhouse_stats
                WHERE discord_user_id = ? AND game = ?
                """,
                (int(discord_user_id), game_key),
            )
        elif discord_user_id is not None:
            cursor.execute(
                """
                DELETE FROM global_user_inhouse_stats
                WHERE discord_user_id = ?
                """,
                (int(discord_user_id),),
            )
        elif game_key in ("lol", "valorant"):
            cursor.execute(
                """
                DELETE FROM global_user_inhouse_stats
                WHERE game = ?
                """,
                (game_key,),
            )
        else:
            cursor.execute("DELETE FROM global_user_inhouse_stats")

        deleted_count = cursor.rowcount
        connection.commit()
        return deleted_count
    finally:
        connection.close()

# =====================================================================
# [호환성 보강] lol_civilwar.py / val_civilwar.py 연동용 래퍼 함수
# =====================================================================

def update_participant_positions(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    preferred_position: str | None = None,
    sub_position: str | None = None,
) -> tuple[bool, str]:
    """참가자의 주 포지션 또는 부 포지션을 변경합니다."""
    if preferred_position is not None:
        return update_inhouse_participant_position(
            guild_id=guild_id,
            session_id=session_id,
            discord_user_id=discord_user_id,
            new_position=preferred_position,
        )
    if sub_position is not None:
        return update_inhouse_participant_sub_position(
            guild_id=guild_id,
            session_id=session_id,
            discord_user_id=discord_user_id,
            new_sub_position=sub_position,
        )
    return False, "변경할 포지션 정보가 없습니다."


def close_inhouse_session(
    guild_id: int,
    civilwar_number: int | None = None,
    game: str | None = None,
    requester_user_id: int | None = None,
    allow_adminoverride: bool = True,
    session_id: int | None = None,
) -> tuple[bool, str, dict | None]:
    """내전 세션을 종료(삭제)하고 종료된 세션 정보를 반환합니다."""
    session = None
    if session_id is not None:
        session = get_inhouse_session_by_id(guild_id, session_id)
    elif civilwar_number is not None:
        session = get_inhouse_session_by_number(guild_id, civilwar_number, game)

    if not session:
        return False, "해당 내전 세션을 찾을 수 없거나 이미 종료되었습니다.", None

    if requester_user_id is not None and not allow_adminoverride:
        if int(session.get("organizer_user_id", 0)) != int(requester_user_id):
            return False, "내전 주최자 또는 관리자만 내전을 종료할 수 있습니다.", None

    closed_copy = dict(session)
    closed_copy["status"] = "closed"

    delete_inhouse_session(
        guild_id=guild_id,
        civilwar_number=int(session["civilwar_number"]),
        game=str(session["game"]),
    )
    return True, f"내전(match #{session['civilwar_number']})이 종료되었습니다.", closed_copy
