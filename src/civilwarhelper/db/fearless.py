from contextlib import closing
import json
import logging

from civilwarhelper.db.connection import get_connection


def get_fearless_state(guild_id: int, session_id: int) -> dict:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT fearless_enabled, fearless_data FROM inhouse_sessions WHERE guild_id = ? AND session_id = ?",
            (guild_id, session_id),
        ).fetchone()

    if not row:
        return {"enabled": False, "current_set": 1, "sets": {}, "results": {}}

    enabled = bool(row["fearless_enabled"])
    try:
        parsed = json.loads(row["fearless_data"] or "{}")
        if not isinstance(parsed, dict):
            parsed = {}
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logging.warning("피어리스 데이터 파싱 실패 (session=%s): %s", session_id, e)
        parsed = {}

    if "sets" in parsed or "results" in parsed:
        sets_data = parsed.get("sets", {})
        results_data = parsed.get("results", {})
    else:
        sets_data = parsed
        results_data = {}

    # 승패 기록된 마지막 세트 + 1이 현재 세트
    done = [int(k) for k in results_data if str(k).isdigit()]
    current_set = (max(done) + 1) if done else 1

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
    payload = {"sets": sets_data, "results": results_data}
    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE inhouse_sessions SET fearless_enabled = ?, fearless_data = ? WHERE guild_id = ? AND session_id = ?",
            (1 if enabled else 0, json.dumps(payload, ensure_ascii=False), guild_id, session_id),
        )
        conn.commit()


def toggle_fearless_mode(guild_id: int, session_id: int) -> dict:
    state = get_fearless_state(guild_id, session_id)
    _save_fearless_payload(
        guild_id,
        session_id,
        not state["enabled"],
        state["sets"],
        state["results"],
    )
    return get_fearless_state(guild_id, session_id)


def record_set_winner(guild_id: int, session_id: int, winner_side: str) -> dict:
    state = get_fearless_state(guild_id, session_id)
    results = state["results"]
    results[str(state["current_set"])] = winner_side.upper()

    _save_fearless_payload(guild_id, session_id, state["enabled"], state["sets"], results)
    return get_fearless_state(guild_id, session_id)


def save_fearless_set_record(
    guild_id: int,
    session_id: int,
    set_number: int,
    red_champions: list[str],
    blue_champions: list[str],
    extra_bans: list[str] | None = None,
    played_maps: list[str] | None = None,
) -> dict:
    state = get_fearless_state(guild_id, session_id)
    sets_data = state["sets"]

    entry: dict = {
        "red": [c.strip() for c in red_champions if c.strip()],
        "blue": [c.strip() for c in blue_champions if c.strip()],
        "extra": [c.strip() for c in (extra_bans or []) if c.strip()],
    }
    if played_maps is not None:
        entry["maps"] = [m.strip() for m in played_maps if m.strip()]
    sets_data[str(set_number)] = entry

    _save_fearless_payload(guild_id, session_id, True, sets_data, state["results"])
    return get_fearless_state(guild_id, session_id)


def clear_fearless_records(guild_id: int, session_id: int) -> dict:
    state = get_fearless_state(guild_id, session_id)
    _save_fearless_payload(guild_id, session_id, state["enabled"], {}, state["results"])
    return get_fearless_state(guild_id, session_id)
