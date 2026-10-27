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


def record_global_user_inhouse_result(game: str, player_records: list[dict]) -> None:
    with closing(get_connection()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc).isoformat()

            for rec in player_records:
                uid = rec.get("discord_user_id", rec.get("user_id"))
                if uid is None:
                    continue
                uid = int(uid)
                # 더미 테스트봇 제외
                if 900000000000000000 <= uid <= 900000000000000999:
                    continue

                win = bool(rec.get("is_win"))
                mtype = str(rec.get("matchup_type") or "황밸")

                t_w, t_l = (1, 0) if win else (0, 1)
                u_w = 1 if (win and mtype == "윗밸") else 0
                u_l = 1 if (not win and mtype == "윗밸") else 0
                e_w = 1 if (win and mtype == "황밸") else 0
                e_l = 1 if (not win and mtype == "황밸") else 0
                l_w = 1 if (win and mtype == "아랫밸") else 0
                l_l = 1 if (not win and mtype == "아랫밸") else 0

                conn.execute(
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
                    (uid, game, t_w, t_l, u_w, u_l, e_w, e_l, l_w, l_l, now),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise


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
