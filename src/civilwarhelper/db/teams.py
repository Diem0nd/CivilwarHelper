from contextlib import closing
from datetime import datetime, timezone
import json
import logging

from civilwarhelper.db.connection import get_connection


def get_session_balance_settings(
    guild_id: int,
    session_id: int,
    positions: list[str],
) -> dict[str, str]:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT balance_settings FROM inhouse_sessions WHERE guild_id = ? AND session_id = ?",
            (guild_id, session_id),
        ).fetchone()

        defaults = {pos: "황밸" for pos in positions}
        if row is None or not row["balance_settings"]:
            return defaults

        try:
            saved = json.loads(row["balance_settings"])
            for pos in positions:
                if saved.get(pos) not in ("아랫밸", "황밸", "윗밸"):
                    saved[pos] = "황밸"
            return saved
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logging.warning("밸런스 설정 파싱 실패 (session=%s): %s", session_id, e)
            return defaults


def save_session_balance_settings(
    guild_id: int,
    session_id: int,
    settings: dict[str, str],
) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE inhouse_sessions SET balance_settings = ?, updated_at = ? WHERE guild_id = ? AND session_id = ?",
            (json.dumps(settings, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), guild_id, session_id),
        )
        conn.commit()


def save_team_assignments(
    guild_id: int,
    session_id: int,
    assignments: list[dict],
) -> None:
    with closing(get_connection()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            session = conn.execute(
                "SELECT 1 FROM inhouse_sessions WHERE guild_id = ? AND session_id = ?",
                (guild_id, session_id),
            ).fetchone()
            if session is None:
                return

            conn.executemany(
                """
                UPDATE inhouse_participants
                SET assigned_team = ?, assigned_position = ?
                WHERE session_id = ? AND discord_user_id = ?
                """,
                [
                    (a["assigned_team"], a["assigned_position"], session_id, a["discord_user_id"])
                    for a in assignments
                ],
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def swap_two_participants_team(
    session_id: int,
    user_a_id: int,
    user_b_id: int,
) -> tuple[bool, str]:
    with closing(get_connection()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row_a = conn.execute(
                "SELECT assigned_team, assigned_position FROM inhouse_participants WHERE session_id = ? AND discord_user_id = ?",
                (session_id, user_a_id),
            ).fetchone()
            row_b = conn.execute(
                "SELECT assigned_team, assigned_position FROM inhouse_participants WHERE session_id = ? AND discord_user_id = ?",
                (session_id, user_b_id),
            ).fetchone()

            if row_a is None or row_b is None:
                conn.rollback()
                return False, "교환할 참가자 정보를 찾을 수 없습니다."

            conn.execute(
                "UPDATE inhouse_participants SET assigned_team = ?, assigned_position = ? WHERE session_id = ? AND discord_user_id = ?",
                (row_b["assigned_team"], row_b["assigned_position"], session_id, user_a_id),
            )
            conn.execute(
                "UPDATE inhouse_participants SET assigned_team = ?, assigned_position = ? WHERE session_id = ? AND discord_user_id = ?",
                (row_a["assigned_team"], row_a["assigned_position"], session_id, user_b_id),
            )
            conn.commit()
            return True, "두 참가자의 자리(팀/포지션)가 교체되었습니다."
        except Exception:
            conn.rollback()
            raise


def swap_entire_red_blue_teams(guild_id: int, session_id: int) -> tuple[bool, str]:
    # 5인 구성 유지한 채 레드/블루 진영 + 밸런스 기준 + 세트 승패 기록 전부 반전
    with closing(get_connection()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            session = conn.execute(
                "SELECT 1 FROM inhouse_sessions WHERE guild_id = ? AND session_id = ?",
                (guild_id, session_id),
            ).fetchone()
            if session is None:
                return False, "해당 내전을 찾을 수 없습니다."

            conn.execute(
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

            row = conn.execute(
                "SELECT balance_settings, fearless_enabled, fearless_data FROM inhouse_sessions WHERE guild_id = ? AND session_id = ?",
                (guild_id, session_id),
            ).fetchone()

            now = datetime.now(timezone.utc).isoformat()
            if row and row["balance_settings"]:
                try:
                    settings = json.loads(row["balance_settings"])
                    for pos, val in list(settings.items()):
                        if val == "윗밸":
                            settings[pos] = "아랫밸"
                        elif val == "아랫밸":
                            settings[pos] = "윗밸"

                    conn.execute(
                        "UPDATE inhouse_sessions SET balance_settings = ?, updated_at = ? WHERE guild_id = ? AND session_id = ?",
                        (json.dumps(settings, ensure_ascii=False), now, guild_id, session_id),
                    )
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    logging.warning("진영 스왑 중 밸런스 설정 반전 실패 (%s): %s", session_id, e)
                    conn.rollback()
                    return False, "밸런스 설정을 변경하지 못했습니다. 다시 시도해 주세요."

            try:
                payload = json.loads(row["fearless_data"] or "{}")
                if not isinstance(payload, dict):
                    raise ValueError
                if "sets" in payload or "results" in payload:
                    sets_data = payload.get("sets", {})
                    results_data = payload.get("results", {})
                else:
                    sets_data = payload
                    results_data = {}
                if not isinstance(sets_data, dict) or not isinstance(results_data, dict):
                    raise ValueError

                swapped_results = {
                    k: ("BLUE" if v == "RED" else "RED" if v == "BLUE" else v)
                    for k, v in results_data.items()
                }
                conn.execute(
                    "UPDATE inhouse_sessions SET fearless_data = ?, updated_at = ? WHERE guild_id = ? AND session_id = ?",
                    (json.dumps({"sets": sets_data, "results": swapped_results}, ensure_ascii=False), now, guild_id, session_id),
                )
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as e:
                logging.warning("진영 스왑 중 피어리스 결과 반전 실패 (%s): %s", session_id, e)
                conn.rollback()
                return False, "진영 기록을 변경하지 못했습니다. 다시 시도해 주세요."

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return True, "레드팀과 블루팀의 진영 및 승패 기록이 함께 변경되었습니다."


def flip_all_teams_red_blue(session_id: int) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
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
        conn.commit()


def get_session_team_groups(guild_id: int, session_id: int) -> list[list[int]]:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT team_groups_json FROM inhouse_sessions WHERE guild_id = ? AND session_id = ?",
            (guild_id, session_id),
        ).fetchone()
        if row is None or not row["team_groups_json"]:
            return []

        try:
            data = json.loads(row["team_groups_json"])
            if not isinstance(data, list):
                return []
            res: list[list[int]] = []
            for g in data:
                if isinstance(g, list):
                    ids = [int(x) for x in g]
                    if len(ids) >= 2:
                        res.append(ids)
            return res
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logging.warning("팀 그룹 파싱 실패 (session=%s): %s", session_id, e)
            return []


def add_or_update_session_team_group(
    guild_id: int,
    session_id: int,
    selected_user_ids: list[int],
) -> tuple[bool, str, list[list[int]]]:
    unique_ids = list(dict.fromkeys(int(u) for u in selected_user_ids))

    if len(unique_ids) < 2:
        return False, "같은 팀으로 묶으려면 최소 2명 이상을 선택해야 합니다.", []
    if len(unique_ids) > 5:
        return False, "한 팀의 최대 인원은 5명이므로 최대 5명까지만 묶을 수 있습니다.", []

    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT team_groups_json FROM inhouse_sessions WHERE guild_id = ? AND session_id = ? AND status = 'open'",
            (guild_id, session_id),
        ).fetchone()
        if row is None:
            return False, "진행 중인 모집 세션을 찾을 수 없습니다.", []

        try:
            existing_groups = json.loads(row["team_groups_json"] or "[]")
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logging.warning("기존 팀 그룹 로드 실패 (session=%s): %s", session_id, e)
            existing_groups = []

        # 기존 그룹에서 새로 묶인 인원 빼고 2명 이상 남은 그룹만 유지
        new_groups = [
            rem for g in existing_groups
            if len(rem := [int(u) for u in g if int(u) not in unique_ids]) >= 2
        ]
        new_groups.append(unique_ids)

        conn.execute(
            "UPDATE inhouse_sessions SET team_groups_json = ? WHERE guild_id = ? AND session_id = ?",
            (json.dumps(new_groups), guild_id, session_id),
        )
        conn.commit()
        return True, f"{len(unique_ids)}명을 같은 팀으로 예약했습니다.", new_groups


def clear_session_team_groups(guild_id: int, session_id: int) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE inhouse_sessions SET team_groups_json = '[]' WHERE guild_id = ? AND session_id = ?",
            (guild_id, session_id),
        )
        conn.commit()
