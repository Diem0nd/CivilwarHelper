from contextlib import closing
from datetime import datetime, timezone

from civilwarhelper.db.connection import get_connection


def get_global_user_inhouse_stats(discord_user_id: int, game: str) -> dict:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM global_user_inhouse_stats WHERE discord_user_id = ? AND game = ?",
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

def record_global_user_inhouse_result(
    game: str,
    player_records: list[dict],
    undo: bool = False,
) -> None:
    """
    세트 승패가 결정될 때 참가자 개개인의 승패 및 밸런스(윗밸/황밸/아랫밸 상대) 전적을 누적 기록합니다.
    undo=True일 경우 직전 기록을 1씩 차감(롤백)합니다.
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
        sign = -1 if undo else 1

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

            t_win = (1 if is_win else 0) * sign
            t_loss = (0 if is_win else 1) * sign

            u_win = (1 if (is_win and matchup_type == "윗밸") else 0) * sign
            u_loss = (1 if (not is_win and matchup_type == "윗밸") else 0) * sign

            e_win = (1 if (is_win and matchup_type == "황밸") else 0) * sign
            e_loss = (1 if (not is_win and matchup_type == "황밸") else 0) * sign

            l_win = (1 if (is_win and matchup_type == "아랫밸") else 0) * sign
            l_loss = (1 if (not is_win and matchup_type == "아랫밸") else 0) * sign

            if undo:
                connection.execute(
                    """
                    UPDATE global_user_inhouse_stats
                    SET total_wins = MAX(0, total_wins + ?),
                        total_losses = MAX(0, total_losses + ?),
                        upper_wins = MAX(0, upper_wins + ?),
                        upper_losses = MAX(0, upper_losses + ?),
                        even_wins = MAX(0, even_wins + ?),
                        even_losses = MAX(0, even_losses + ?),
                        lower_wins = MAX(0, lower_wins + ?),
                        lower_losses = MAX(0, lower_losses + ?),
                        updated_at = ?
                    WHERE discord_user_id = ? AND game = ?
                    """,
                    (
                        t_win, t_loss,
                        u_win, u_loss,
                        e_win, e_loss,
                        l_win, l_loss,
                        current_time,
                        uid, game,
                    ),
                )
            else:
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
    with closing(get_connection()) as conn:
        target_game = None if (game is None or game == "all") else game.lower()

        if discord_user_id is not None and target_game is not None:
            cur = conn.execute(
                "DELETE FROM global_user_inhouse_stats WHERE discord_user_id = ? AND game = ?",
                (int(discord_user_id), target_game),
            )
        elif discord_user_id is not None:
            cur = conn.execute(
                "DELETE FROM global_user_inhouse_stats WHERE discord_user_id = ?",
                (int(discord_user_id),),
            )
        elif target_game is not None:
            cur = conn.execute(
                "DELETE FROM global_user_inhouse_stats WHERE game = ?",
                (target_game,),
            )
        else:
            cur = conn.execute("DELETE FROM global_user_inhouse_stats")

        conn.commit()
        return cur.rowcount
