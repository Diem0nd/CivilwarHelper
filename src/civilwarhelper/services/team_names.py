from civilwarhelper.config.positions import LOL_POS_SHORT_MAP, LOL_STANDARD_POSITIONS, POSITION_SHORT_LABEL, VAL_STANDARD_POSITIONS
from civilwarhelper.services.balance import _extract_player_tier_and_score

# (guild_id, session_id) -> {"RED": "...", "BLUE": "..."}
SESSION_CUSTOM_TEAM_NAMES: dict[tuple[int, int], dict[str, str]] = {}


def recommend_team_names_by_balance(
    session: dict,
    participants: list[dict],
    balance_settings: dict[str, str] | None = None,
) -> tuple[str, str]:
    game = session.get("game", "lol")
    positions = LOL_STANDARD_POSITIONS if game == "lol" else VAL_STANDARD_POSITIONS

    red_by_pos: dict[str, dict] = {}
    blue_by_pos: dict[str, dict] = {}

    for p in participants:
        side = str(p.get("team_side") or p.get("assigned_team") or "").upper()
        raw_pos = str(p.get("assigned_position") or p.get("primary_position") or "")
        short_key = POSITION_SHORT_LABEL.get(raw_pos, LOL_POS_SHORT_MAP.get(raw_pos.upper(), raw_pos.upper()))
        if side == "RED":
            red_by_pos[short_key] = p
        elif side == "BLUE":
            blue_by_pos[short_key] = p

    red_high: set[str] = set()
    red_low: set[str] = set()
    blue_high: set[str] = set()
    blue_low: set[str] = set()

    for pos in positions:
        short_pos = POSITION_SHORT_LABEL.get(pos, LOL_POS_SHORT_MAP.get(pos.upper(), pos.upper()))
        _, red_score = _extract_player_tier_and_score(red_by_pos.get(short_pos), game)
        _, blue_score = _extract_player_tier_and_score(blue_by_pos.get(short_pos), game)

        diff = red_score - blue_score
        # 2점 이하는 황밸이니까 2점 초과일 때만 우세/열세로 봄
        if diff > 2.0:
            red_high.add(short_pos)
            blue_low.add(short_pos)
        elif diff < -2.0:
            blue_high.add(short_pos)
            red_low.add(short_pos)

    def _pick_val(high_set: set[str], low_set: set[str], default_name: str) -> str:
        if {"DUEL", "INIT"}.issubset(high_set):
            return "진입 맛집"
        if {"CTRL", "SENT"}.issubset(high_set):
            return "철벽 수비대"
        if {"DUEL", "INIT"}.issubset(low_set):
            return "들어가 말아"
        if {"CTRL", "SENT"}.issubset(low_set):
            return "연막은 어디에"
        if len(high_set) == 1:
            return {
                "DUEL": "원맨쇼",
                "INIT": "정보통",
                "CTRL": "연막 장인",
                "SENT": "문지기",
                "FLEX": "만능 해결사",
            }.get(next(iter(high_set)), default_name)
        return default_name

    def _pick(high_set: set[str], low_set: set[str], default_name: str) -> str:
        if len(high_set) >= 4:
            return "라고 적혀있는데요?"
        if len(low_set) >= 4:
            return "살려주세요"
        if game != "lol":
            return _pick_val(high_set, low_set, default_name)

        if {"TOP", "MID"}.issubset(high_set):
            return "어깨깡패"
        if {"ADC", "SUP"}.issubset(high_set):
            return "하체 단련의 날"
        if {"MID", "ADC"}.issubset(low_set):
            return "응애 해줘"
        if {"SUP", "JGL"}.issubset(low_set):
            return "노력하는데 잘 안돼"
        if len(high_set) == 1:
            return {
                "TOP": "특대머리",
                "JGL": "배달의 달인",
                "MID": "터질 듯한 미드",
                "ADC": "금수저",
                "SUP": "금쪽 같은 우리팀",
            }.get(next(iter(high_set)), default_name)
        return default_name

    return _pick(red_high, red_low, "RED 팀"), _pick(blue_high, blue_low, "BLUE 팀")
