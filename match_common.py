import discord
import database

# 봇(Application) 및 서버에 등록된 커스텀 이모티콘 캐시
CUSTOM_EMOJI_CACHE: dict[str, discord.Emoji | discord.PartialEmoji | str] = {}
_BOT_CLIENT: discord.Client | None = None

# 내전 세션별 커스텀 팀 이름 저장소: {(guild_id, session_id): {"RED": "...", "BLUE": "..."}}
SESSION_CUSTOM_TEAM_NAMES: dict[tuple[int, int], dict[str, str]] = {}

LOL_STANDARD_POSITIONS = ["Top", "Jungle", "Mid", "AD carry", "Support"]
VAL_STANDARD_POSITIONS = ["Duelist", "Initiator", "Controller", "Sentinel", "Flex"]

LOL_POS_SHORT_MAP = {
    "TOP": "TOP",
    "JUNGLE": "JGL",
    "JGL": "JGL",
    "MID": "MID",
    "MIDDLE": "MID",
    "ADC": "ADC",
    "AD CARRY": "ADC",
    "BOT": "ADC",
    "BOTTOM": "ADC",
    "SUPPORT": "SUP",
    "SUP": "SUP",
    "UTILITY": "SUP",
    "DUELIST": "DUEL",
    "INITIATOR": "INIT",
    "CONTROLLER": "CTRL",
    "SENTINEL": "SENT",
    "FLEX": "FLEX",
}

POSITION_SHORT_LABEL = {
    "Top": "TOP",
    "Jungle": "JGL",
    "Mid": "MID",
    "Bot": "ADC",
    "ADC": "ADC",
    "AD carry": "ADC",
    "Support": "SUP",
    "Duelist": "DUEL",
    "Initiator": "INIT",
    "Controller": "CTRL",
    "Sentinel": "SENT",
    "Flex": "FLEX",
}

LOL_COMBINED_POSITION_LABELS = {
    "Top_Jungle": "탑 / 정글 (Top & Jungle)",
    "Top_Mid": "탑 / 미드 (Top & Mid)",
    "Mid_Jungle": "미드 / 정글 (Mid & Jungle)",
    "Bot_Duo": "바텀 듀오 (AD carry & Support)",
    "Fill": "전라인 가능 (All / Fill)",
}

VAL_COMBINED_POSITION_LABELS = {
    "Duel_Init": "타격대 / 척후대 (Duelist & Initiator)",
    "Ctrl_Sent": "전략가 / 감시자 (Controller & Sentinel)",
    "Fill": "올라운더 (All / Flex)",
}

TIER_BASE_SCORE = {
    "UNRANKED": 10.0,
    "IRON": 4.0,
    "BRONZE": 8.0,
    "SILVER": 12.0,
    "GOLD": 16.0,
    "PLATINUM": 20.0,
    "EMERALD": 24.0,
    "DIAMOND": 28.0,
    "MASTER": 34.0,
    "GRANDMASTER": 38.0,
    "CHALLENGER": 42.0,
    "ASCENDANT": 24.0,
    "IMMORTAL": 34.0,
    "RADIANT": 42.0,
}

DIVISION_BONUS = {
    "IV": 1.0,
    "III": 2.0,
    "II": 3.0,
    "I": 4.0,
    "1": 1.0,
    "2": 2.0,
    "3": 3.0,
}


async def load_custom_emojis(bot_client: discord.Client) -> None:
    """봇에 추가된 Application 이모티콘과 서버 이모티콘을 모두 불러와 캐시에 저장합니다."""
    global _BOT_CLIENT
    _BOT_CLIENT = bot_client

    for em in bot_client.emojis:
        CUSTOM_EMOJI_CACHE[em.name] = em

    if hasattr(bot_client, "fetch_application_emojis"):
        try:
            app_emojis = await bot_client.fetch_application_emojis()
            for em in app_emojis:
                CUSTOM_EMOJI_CACHE[em.name] = em
        except Exception:
            pass


def get_custom_emoji(name: str, fallback: str = "") -> str:
    """메시지 본문에서 사용할 커스텀 이모티콘 문자열(<:이름:ID>)을 반환합니다."""
    if name in CUSTOM_EMOJI_CACHE:
        return str(CUSTOM_EMOJI_CACHE[name])

    if _BOT_CLIENT is not None:
        for em in _BOT_CLIENT.emojis:
            if em.name == name:
                CUSTOM_EMOJI_CACHE[name] = em
                return str(em)

    return fallback if fallback else f":{name}:"


def format_tier_with_custom_emoji(tier_text: str | None, game: str) -> str:
    """티어 문자열 앞에 등록된 커스텀 티어 이모티콘(lol_TIER / val_TIER)을 붙여 반환합니다."""
    prefix = "lol" if game == "lol" else "val"
    if not tier_text or tier_text.strip().upper() in (
        "UNRANKED",
        "NONE",
        "UNKNOWN",
        "NOT RETRIEVED YET",
    ):
        emoji = get_custom_emoji(f"{prefix}_UNRANKED", "⬜")
        return f"{emoji} Unranked".strip()

    cleaned = tier_text.strip()
    tier_key = cleaned.split()[0].upper()
    emoji = get_custom_emoji(f"{prefix}_{tier_key}", "⬜")
    return f"{emoji} {cleaned}".strip()


def parse_single_tier_score(tier_str: str | None, game: str) -> float:
    """단일 티어 문자열을 밸런스 점수로 변환합니다."""
    if not tier_str:
        return 10.0

    cleaned = tier_str.strip()
    if not cleaned or cleaned.upper() in ("UNRANKED", "UNKNOWN", "NOT RETRIEVED YET"):
        return 10.0

    parts = cleaned.upper().split()
    tier_name = parts[0]
    div_name = parts[1] if len(parts) > 1 else ""

    if tier_name not in TIER_BASE_SCORE or tier_name == "UNRANKED":
        return 10.0

    base = TIER_BASE_SCORE[tier_name]
    if game == "lol" and tier_name in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return base
    if game == "valorant" and tier_name == "RADIANT":
        return base

    return base + DIVISION_BONUS.get(div_name, 0.0)


def get_participant_highest_tier_info(participant: dict, game: str) -> tuple[str, float]:
    """참가자의 체감 티어(최우선) 또는 실제 최고 티어 이름과 밸런스 점수를 반환합니다."""
    custom_tier = (participant.get("custom_tier") or "").strip()
    if custom_tier and custom_tier.lower() != "none":
        custom_score = parse_single_tier_score(custom_tier, game)
        return f"{custom_tier} (체감)", custom_score

    if game == "lol":
        solo_tier = participant.get("solo_tier") or "Unranked"
        flex_tier = participant.get("flex_tier") or "Unranked"

        solo_score = parse_single_tier_score(solo_tier, "lol")
        flex_score = parse_single_tier_score(flex_tier, "lol")

        if solo_tier != "Unranked" and (solo_score >= flex_score or flex_tier == "Unranked"):
            return solo_tier, solo_score
        elif flex_tier != "Unranked":
            return flex_tier, flex_score
        return "Unranked", 10.0

    comp_tier = participant.get("competitive_tier") or "Unranked"
    comp_score = parse_single_tier_score(comp_tier, "valorant")
    return comp_tier, comp_score


def extract_player_tier_and_score(
    p: dict | None,
    game: str = "lol",
) -> tuple[str, float]:
    """참가자 dict에서 ':game_TIER: TIER' 형식 문자열과 밸런스 점수를 계산합니다."""
    prefix = "lol" if game == "lol" else "val"

    if not p:
        unranked_emoji = get_custom_emoji(f"{prefix}_UNRANKED", "⬜")
        return f"{unranked_emoji} Unranked", 10.0

    pre_score = p.get("mmr_score") or p.get("balance_score") or p.get("tier_score")

    def _parse(raw: str | None) -> tuple[str, float]:
        if not raw or not str(raw).strip():
            return "Unranked", 10.0
        text = str(raw).strip()
        parts = text.upper().split()
        base_name = parts[0]
        if base_name not in TIER_BASE_SCORE or base_name == "UNRANKED":
            return "Unranked", 10.0
        score = TIER_BASE_SCORE[base_name]
        if len(parts) >= 2:
            score += DIVISION_BONUS.get(parts[1], 0.0)
        return text, score

    custom_raw = (p.get("custom_tier") or "").strip()
    is_custom = False

    if custom_raw:
        tier_text, calc_score = _parse(custom_raw)
        is_custom = True
    elif game == "valorant":
        val_raw = (
            p.get("competitive_tier")
            or p.get("valorant_tier")
            or p.get("val_tier")
            or p.get("solo_tier")
            or "Unranked"
        )
        tier_text, calc_score = _parse(val_raw)
    else:
        solo_text, solo_score = _parse(p.get("solo_tier"))
        flex_text, flex_score = _parse(p.get("flex_tier"))

        if solo_text != "Unranked" and (solo_score >= flex_score or flex_text == "Unranked"):
            tier_text, calc_score = solo_text, solo_score
        elif flex_text != "Unranked":
            tier_text, calc_score = flex_text, flex_score
        else:
            tier_text, calc_score = "Unranked", 10.0

    base_tier_upper = tier_text.upper().split()[0] if tier_text else "UNRANKED"
    tier_emoji = get_custom_emoji(f"{prefix}_{base_tier_upper}", "⬜")
    final_score = float(pre_score) if pre_score is not None else calc_score

    suffix = " (체감)" if is_custom else ""
    return f"{tier_emoji} {tier_text}{suffix}", final_score


def get_balance_badge(
    red_score: float,
    blue_score: float,
    threshold: float = 2.0,
) -> str:
    """점수 차이에 따라 (황밸) ⚖️ / (윗밸) ⬆️ / (아랫밸) ⬇️ 반환"""
    diff = red_score - blue_score
    if abs(diff) <= threshold:
        return "(황밸) ⚖️"
    elif diff > threshold:
        return "(윗밸) ⬆️"
    else:
        return "(아랫밸) ⬇️"


def format_position_display(game: str, raw_position: str | None) -> str:
    if not raw_position:
        return "미정"
    if game == "lol":
        return LOL_COMBINED_POSITION_LABELS.get(raw_position, raw_position)
    return VAL_COMBINED_POSITION_LABELS.get(raw_position, raw_position)


def record_participants_match_stats(
    session: dict,
    participants: list[dict],
    winner_side: str,
) -> None:
    """승리 팀이 결정되었을 때 맞라인 점수 차이(1순위)와 팀 전체 점수 차이(2순위)로 글로벌 개인 전적을 기록합니다."""
    game = str(session.get("game") or "lol").lower()
    win_side_upper = str(winner_side).upper()

    def _norm_pos(raw_pos: str) -> str:
        up = str(raw_pos or "").strip().upper()
        return LOL_POS_SHORT_MAP.get(up, up)

    red_players: list[dict] = []
    blue_players: list[dict] = []
    red_by_pos: dict[str, dict] = {}
    blue_by_pos: dict[str, dict] = {}

    red_total_score = 0.0
    blue_total_score = 0.0

    for p in participants:
        side = str(p.get("team_side") or p.get("assigned_team") or "").upper()
        pos_raw = str(p.get("assigned_position") or p.get("primary_position") or "")
        pos_key = _norm_pos(pos_raw)
        _, score = extract_player_tier_and_score(p, game)

        p_info = {
            "uid": p.get("discord_user_id", p.get("user_id")),
            "side": side,
            "pos_key": pos_key,
            "score": score,
        }

        if side == "RED":
            red_players.append(p_info)
            red_total_score += score
            if pos_key and pos_key not in red_by_pos:
                red_by_pos[pos_key] = p_info
        elif side == "BLUE":
            blue_players.append(p_info)
            blue_total_score += score
            if pos_key and pos_key not in blue_by_pos:
                blue_by_pos[pos_key] = p_info

    LANE_DIFF_THRESHOLD = 2.0
    TEAM_DIFF_THRESHOLD = 5.0

    player_records: list[dict] = []

    for p_info in red_players + blue_players:
        uid = p_info["uid"]
        if uid is None:
            continue

        my_side = p_info["side"]
        my_pos = p_info["pos_key"]
        my_score = p_info["score"]

        opp_map = blue_by_pos if my_side == "RED" else red_by_pos
        opp_info = opp_map.get(my_pos)

        my_team_total = red_total_score if my_side == "RED" else blue_total_score
        opp_team_total = blue_total_score if my_side == "RED" else red_total_score
        team_diff = opp_team_total - my_team_total

        matchup_type = "황밸"

        if opp_info is not None:
            lane_diff = opp_info["score"] - my_score
            if lane_diff >= LANE_DIFF_THRESHOLD:
                matchup_type = "윗밸"
            elif lane_diff <= -LANE_DIFF_THRESHOLD:
                matchup_type = "아랫밸"
            else:
                if team_diff >= TEAM_DIFF_THRESHOLD:
                    matchup_type = "윗밸"
                elif team_diff <= -TEAM_DIFF_THRESHOLD:
                    matchup_type = "아랫밸"
                else:
                    matchup_type = "황밸"
        else:
            if team_diff >= TEAM_DIFF_THRESHOLD:
                matchup_type = "윗밸"
            elif team_diff <= -TEAM_DIFF_THRESHOLD:
                matchup_type = "아랫밸"
            else:
                matchup_type = "황밸"

        player_records.append(
            {
                "discord_user_id": uid,
                "user_id": uid,
                "is_win": (my_side == win_side_upper),
                "matchup_type": matchup_type,
            }
        )

    if player_records:
        database.record_global_user_inhouse_result(
            game=game,
            player_records=player_records,
        )

# =====================================================================
# [호환성 보강] val_civilwar.py / lol_civilwar.py 별칭(Alias) 지원
# =====================================================================

def format_tier_with_emoji(tier_text: str | None, game: str = "lol") -> str:
    return format_tier_with_custom_emoji(tier_text or "Unranked", game=game)


if "POSITION_SHORT_LABEL" not in globals():
    POSITION_SHORT_LABEL = {
        "TOP": "탑",
        "JUNGLE": "정글",
        "MID": "미드",
        "ADC": "원딜",
        "SUPPORT": "서폿",
        "ALL": "올라운더",
        "Duelist": "타격대",
        "Initiator": "척후대",
        "Controller": "전략가",
        "Sentinel": "감시자",
        "Flex": "올라운더",
    }

if "SESSION_CUSTOM_TEAM_NAMES" not in globals():
    SESSION_CUSTOM_TEAM_NAMES: dict = {}
