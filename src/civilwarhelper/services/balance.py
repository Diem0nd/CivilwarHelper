from civilwarhelper.config.positions import LOL_STANDARD_POSITIONS, VAL_STANDARD_POSITIONS
from civilwarhelper.config.tiers import DIVISION_BONUS, TIER_BASE_SCORE
from civilwarhelper.ui.emojis import get_tier_emoji


def get_participant_highest_tier_info(participant: dict, game: str) -> tuple[float, str]:
    tier_label, score = _extract_player_tier_and_score(participant, game)
    return score, tier_label


def assign_teams_with_balance(
    participants: list[dict],
    game: str,
    balance_settings: dict[str, str],
    team_groups: list[list[int]] | None = None,
) -> list[dict]:
    positions = LOL_STANDARD_POSITIONS if game == "lol" else VAL_STANDARD_POSITIONS

    # 10명 안 될 때 예외처리
    if len(participants) != 10:
        scored = sorted(
            participants,
            key=lambda p: get_participant_highest_tier_info(p, game)[0],
            reverse=True,
        )
        return [
            {
                "discord_user_id": p["discord_user_id"],
                "assigned_team": "RED" if idx % 2 == 0 else "BLUE",
                "assigned_position": positions[idx % len(positions)],
            }
            for idx, p in enumerate(scored)
        ]

    active_groups: list[list[int]] = []
    participant_uids = {int(p["discord_user_id"]) for p in participants}

    if team_groups:
        for g in team_groups:
            valid_g = [int(uid) for uid in g if int(uid) in participant_uids]
            if 2 <= len(valid_g) <= 5:
                active_groups.append(valid_g)

    user_to_group = {
        uid: g_idx
        for g_idx, g in enumerate(active_groups)
        for uid in g
    }

    aliases = {"ADC": "AD carry", "Bot": "AD carry", "Bottom": "AD carry"} if game == "lol" else {}
    enriched = []
    for p in participants:
        uid = int(p["discord_user_id"])
        score, best_label = get_participant_highest_tier_info(p, game)
        prim = p.get("preferred_position") or p.get("main_position") or "Fill"
        sub = p.get("sub_position") or None
        if aliases:
            prim = aliases.get(prim, prim)
            sub = aliases.get(sub, sub)

        enriched.append(
            {
                **p,
                "_uid": uid,
                "_group_id": user_to_group.get(uid),
                "_score": score,
                "_best_tier_label": best_label,
                "_primary": prim,
                "_sub": sub,
            }
        )

    pos_buckets: dict[str, list[dict]] = {pos: [] for pos in positions}

    def can_join_bucket(bucket: list[dict], cand: dict, ignore_group: bool = False) -> bool:
        if len(bucket) >= 2:
            return False
        if not ignore_group and cand["_group_id"] is not None:
            return all(ep["_group_id"] != cand["_group_id"] for ep in bucket)
        return True

    # 같은 팀 예약된 인원 먼저 넣어야 맞라인 충돌 안 남
    sorted_players = sorted(
        enriched,
        key=lambda x: (x["_group_id"] is not None, x["_score"]),
        reverse=True,
    )

    overflow: list[dict] = []
    for p in sorted_players:
        prim = p["_primary"]
        if prim in pos_buckets and can_join_bucket(pos_buckets[prim], p):
            pos_buckets[prim].append(p)
        else:
            overflow.append(p)

    remaining: list[dict] = []
    for p in overflow:
        sub = p["_sub"]
        if sub and sub in pos_buckets and can_join_bucket(pos_buckets[sub], p):
            pos_buckets[sub].append(p)
        else:
            remaining.append(p)

    # 남은 인원 빈 슬롯에 배정 (한 명 있는 라인이면 점수 비슷한 사람 우선)
    for pos in positions:
        while len(pos_buckets[pos]) < 2 and remaining:
            cands = [c for c in remaining if can_join_bucket(pos_buckets[pos], c)]
            if not cands:
                break
            if len(pos_buckets[pos]) == 1:
                anchor = pos_buckets[pos][0]["_score"]
                cands.sort(key=lambda x: abs(x["_score"] - anchor))
            chosen = cands[0]
            pos_buckets[pos].append(chosen)
            remaining.remove(chosen)

    for pos in positions:
        while len(pos_buckets[pos]) < 2 and remaining:
            pos_buckets[pos].append(remaining.pop(0))

    # 2^5 = 32가지 조합 완전탐색 (그룹 유지 > 밸런스 모드 > 점수차 최소)
    best_assignment: dict[str, tuple[dict, dict]] = {}
    best_key: tuple[int, int, float] = (999, 999, float("inf"))

    for mask in range(1 << len(positions)):
        cur_map: dict[str, tuple[dict, dict]] = {}
        red_uids: set[int] = set()
        blue_uids: set[int] = set()
        mode_v = 0

        for i, pos in enumerate(positions):
            high_p, low_p = sorted(pos_buckets[pos], key=lambda x: x["_score"], reverse=True)
            mode = balance_settings.get(pos, "황밸")

            if (mask >> i) & 1:
                red_p, blue_p = high_p, low_p
                if mode == "아랫밸":
                    mode_v += 1
            else:
                red_p, blue_p = low_p, high_p
                if mode == "윗밸":
                    mode_v += 1

            cur_map[pos] = (red_p, blue_p)
            red_uids.add(red_p["_uid"])
            blue_uids.add(blue_p["_uid"])

        group_v = sum(
            1 for g in active_groups
            if any(u in red_uids for u in g) and any(u in blue_uids for u in g)
        )

        diff = abs(
            sum(cur_map[pos][0]["_score"] for pos in positions)
            - sum(cur_map[pos][1]["_score"] for pos in positions)
        )

        key = (group_v, mode_v, diff)
        if key < best_key:
            best_key = key
            best_assignment = cur_map

    res: list[dict] = []
    for pos in positions:
        red_p, blue_p = best_assignment[pos]
        res.append(
            {
                "discord_user_id": red_p["discord_user_id"],
                "assigned_team": "RED",
                "assigned_position": pos,
            }
        )
        res.append(
            {
                "discord_user_id": blue_p["discord_user_id"],
                "assigned_team": "BLUE",
                "assigned_position": pos,
            }
        )
    return res


def _extract_player_tier_and_score(p: dict | None, game: str = "lol") -> tuple[str, float]:
    if not p:
        return f"{get_tier_emoji(game, 'UNRANKED')} Unranked", 10.0

    pre_score = p.get("mmr_score") or p.get("balance_score") or p.get("tier_score")

    def parse_tier(raw: str | None) -> tuple[str, float]:
        if not raw or not str(raw).strip():
            return "Unranked", 10.0
        text = str(raw).strip()
        parts = text.upper().split()
        base = parts[0]
        if base not in TIER_BASE_SCORE or base == "UNRANKED":
            return "Unranked", 10.0
        score = TIER_BASE_SCORE[base] + (DIVISION_BONUS.get(parts[1], 0.0) if len(parts) >= 2 else 0.0)
        return text, score

    custom_raw = (p.get("custom_tier") or "").strip()
    is_custom = bool(custom_raw)

    if is_custom:
        tier_text, calc_score = parse_tier(custom_raw)
    elif game == "valorant":
        val_raw = (
            p.get("competitive_tier")
            or p.get("valorant_tier")
            or p.get("val_tier")
            or p.get("solo_tier")
            or "Unranked"
        )
        tier_text, calc_score = parse_tier(val_raw)
    else:
        solo_text, solo_score = parse_tier(p.get("solo_tier"))
        flex_text, flex_score = parse_tier(p.get("flex_tier"))

        if solo_text != "Unranked" and (solo_score >= flex_score or flex_text == "Unranked"):
            tier_text, calc_score = solo_text, solo_score
        elif flex_text != "Unranked":
            tier_text, calc_score = flex_text, flex_score
        else:
            tier_text, calc_score = "Unranked", 10.0

    base_upper = tier_text.upper().split()[0] if tier_text else "UNRANKED"
    emoji = get_tier_emoji(game, base_upper)
    final_score = float(pre_score) if pre_score is not None else calc_score

    suffix = " (체감)" if is_custom else ""
    return f"{emoji} {tier_text}{suffix}", final_score


def _get_balance_badge(red_score: float, blue_score: float, threshold: float = 2.0) -> str:
    diff = red_score - blue_score
    if abs(diff) <= threshold:
        return "(황밸) ⚖️"
    return "(윗밸) ⬆️" if diff > threshold else "(아랫밸) ⬇️"


def _get_comparison_symbol(
    left_score: float,
    right_score: float,
    strong_threshold: float = 2.0,
) -> str:
    diff = round(left_score - right_score, 2)
    if abs(diff) < 0.01:
        return "＝"
    if diff > strong_threshold:
        return "＞"
    if diff > 0:
        return "≥"
    if diff < -strong_threshold:
        return "＜"
    return "≤"
