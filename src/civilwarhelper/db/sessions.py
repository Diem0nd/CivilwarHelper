from contextlib import closing
from datetime import datetime, timezone

from civilwarhelper.db.connection import get_connection


def create_inhouse_session(guild_id: int, game: str, organizer_user_id: int) -> dict:
    with closing(get_connection()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc).isoformat()

            row = conn.execute(
                """
                SELECT COALESCE(MAX(civilwar_number), 0) AS max_num
                FROM inhouse_sessions
                WHERE guild_id = ? AND status = 'open'
                """,
                (guild_id,),
            ).fetchone()
            next_num = (row["max_num"] if row else 0) + 1

            cur = conn.execute(
                """
                INSERT INTO inhouse_sessions (
                    guild_id, civilwar_number, game, organizer_user_id,
                    status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'open', ?, ?)
                """,
                (guild_id, next_num, game, organizer_user_id, now, now),
            )
            conn.commit()
            return {
                "session_id": cur.lastrowid,
                "guild_id": guild_id,
                "civilwar_number": next_num,
                "game": game,
                "organizer_user_id": organizer_user_id,
                "status": "open",
            }
        except Exception:
            conn.rollback()
            raise


def get_active_inhouse_sessions(guild_id: int, game: str | None = None) -> list[dict]:
    with closing(get_connection()) as conn:
        if game:
            rows = conn.execute(
                """
                SELECT s.*, COUNT(p.discord_user_id) AS participant_count
                FROM inhouse_sessions s
                LEFT JOIN inhouse_participants p ON s.session_id = p.session_id
                WHERE s.guild_id = ? AND s.status = 'open' AND s.game = ?
                GROUP BY s.session_id
                ORDER BY s.civilwar_number ASC
                """,
                (guild_id, game),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT s.*, COUNT(p.discord_user_id) AS participant_count
                FROM inhouse_sessions s
                LEFT JOIN inhouse_participants p ON s.session_id = p.session_id
                WHERE s.guild_id = ? AND s.status = 'open'
                GROUP BY s.session_id
                ORDER BY s.civilwar_number ASC
                """,
                (guild_id,),
            ).fetchall()
        return [dict(r) for r in rows]


get_open_inhouse_sessions = get_active_inhouse_sessions


def get_inhouse_session_by_id(guild_id: int, session_id: int) -> dict | None:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM inhouse_sessions WHERE guild_id = ? AND session_id = ? AND status = 'open'",
            (guild_id, session_id),
        ).fetchone()
        return dict(row) if row else None


get_open_inhouse_session_by_id = get_inhouse_session_by_id


def get_inhouse_session_by_number(guild_id: int, civilwar_number: int) -> dict | None:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM inhouse_sessions WHERE guild_id = ? AND civilwar_number = ? AND status = 'open'",
            (guild_id, civilwar_number),
        ).fetchone()
        return dict(row) if row else None


get_open_inhouse_session_by_number = get_inhouse_session_by_number


def transfer_inhouse_organizer(
    guild_id: int,
    session_id: int,
    new_organizer_user_id: int,
) -> bool:
    with closing(get_connection()) as conn:
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            UPDATE inhouse_sessions
            SET organizer_user_id = ?, updated_at = ?
            WHERE guild_id = ? AND session_id = ? AND status = 'open'
            """,
            (new_organizer_user_id, now, guild_id, session_id),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_inhouse_session(guild_id: int, session_id: int) -> bool:
    with closing(get_connection()) as conn:
        cur = conn.execute(
            "DELETE FROM inhouse_sessions WHERE guild_id = ? AND session_id = ?",
            (guild_id, session_id),
        )
        conn.commit()
        return cur.rowcount > 0


def save_inhouse_lobby_message(
    guild_id: int,
    session_id: int,
    channel_id: int,
    message_id: int,
) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """
            UPDATE inhouse_sessions
            SET lobby_channel_id = ?, lobby_message_id = ?
            WHERE guild_id = ? AND session_id = ?
            """,
            (channel_id, message_id, guild_id, session_id),
        )
        conn.commit()


def set_inhouse_match_started(guild_id: int, session_id: int, started: bool) -> bool:
    with closing(get_connection()) as conn:
        try:
            cur = conn.execute(
                "UPDATE inhouse_sessions SET match_started = ?, updated_at = ? "
                "WHERE guild_id = ? AND session_id = ? AND status = 'open'",
                (1 if started else 0, datetime.now(timezone.utc).isoformat(), guild_id, session_id),
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception:
            conn.rollback()
            raise


def list_open_inhouse_sessions(guild_id: int) -> list[dict]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM inhouse_sessions WHERE guild_id = ? ORDER BY session_id DESC",
            (guild_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_session_lobby_message(
    guild_id: int,
    session_id: int,
    channel_id: int,
    message_id: int,
) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """
            UPDATE inhouse_sessions
            SET lobby_channel_id = ?, lobby_message_id = ?, updated_at = ?
            WHERE guild_id = ? AND session_id = ?
            """,
            (channel_id, message_id, datetime.now(timezone.utc).isoformat(), guild_id, session_id),
        )
        conn.commit()
