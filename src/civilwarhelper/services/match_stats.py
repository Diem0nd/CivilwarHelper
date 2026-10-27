from civilwarhelper import db as database
from civilwarhelper.config.positions import LOL_POS_SHORT_MAP
from civilwarhelper.services.balance import _extract_player_tier_and_score

LANE_DIFF_THRESHOLD = 2.0
TEAM_DIFF_THRESHOLD = 5.0


def _record_participants_match_stats(
    session: dict,
    participants: list[dict],
    winner_side: str,
) -> None:
    game = str(session.get("game") or "lol").lower()
    win_side = str(winner_side).upper()

    red_players: list[dict] = []
    blue_players: list[dict] = []
    red_by_pos: dict[str, dict] = {}
    blue_by_pos: dict[str, dict] = {}

    red_total = 0.0
    blue_total = 0.0

    for p in participants:
        side = str(p.get("team_side") or p.get("assigned_team") or "").upper()
        pos_raw = str(p.get("assigned_position") or p.get("primary_position") or "").strip().upper()
        pos_key = LOL_POS_SHORT_MAP.get(pos_raw, pos_raw)
        _, score = _extract_player_tier_and_score(p, game)

        info = {
            "uid": p.get("discord_user_id", p.get("user_id")),
            "side": side,
            "pos_key": pos_key,
            "score": score,
        }

        if side == "RED":
            red_players.append(info)
            red_total += score
            if pos_key and pos_key not in red_by_pos:
                red_by_pos[pos_key] = info
        elif side == "BLUE":
            blue_players.append(info)
            blue_total += score
            if pos_key and pos_key not in blue_by_pos:
                blue_by_pos[pos_key] = info

    records: list[dict] = []
    for p_info in red_players + blue_players:
        uid = p_info["uid"]
        if uid is None:
            continue

        is_red = p_info["side"] == "RED"
        opp = (blue_by_pos if is_red else red_by_pos).get(p_info["pos_key"])
        team_diff = (blue_total - red_total) if is_red else (red_total - blue_total)

        # 맞라인 차이(>=2.0) 우선, 맞라인이 황밸이면 팀 총점 차이(>=5.0)로 판정
        lane_diff = (opp["score"] - p_info["score"]) if opp is not None else 0.0
        if opp is not None and lane_diff >= LANE_DIFF_THRESHOLD:
            matchup_type = "윗밸"
        elif opp is not None and lane_diff <= -LANE_DIFF_THRESHOLD:
            matchup_type = "아랫밸"
        elif team_diff >= TEAM_DIFF_THRESHOLD:
            matchup_type = "윗밸"
        elif team_diff <= -TEAM_DIFF_THRESHOLD:
            matchup_type = "아랫밸"
        else:
            matchup_type = "황밸"

        records.append(
            {
                "discord_user_id": uid,
                "user_id": uid,
                "is_win": (p_info["side"] == win_side),
                "matchup_type": matchup_type,
            }
        )

    if records:
        database.record_global_user_inhouse_result(game=game, player_records=records)
