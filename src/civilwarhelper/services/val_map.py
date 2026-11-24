import random

# 세션별 커스텀 팀 이름 메모리 캐시: {(guild_id, session_id): {"RED": "...", "BLUE": "..."}}
SESSION_CUSTOM_TEAM_NAMES: dict[tuple[int, int], dict[str, str]] = {}

# 발로란트 내전 세션별 현재 배정된 맵 캐시: {(guild_id, session_id): "어센트 (Ascent)"}
SESSION_VALORANT_MAP: dict[tuple[int, int], str] = {}

VALORANT_MAPS: list[str] = [
    "어센트 (Ascent)",
    "바인드 (Bind)",
    "헤이븐 (Haven)",
    "스플릿 (Split)",
    "아이스박스 (Icebox)",
    "브리즈 (Breeze)",
    "프랙처 (Fracture)",
    "펄 (Pearl)",
    "로터스 (Lotus)",
    "선셋 (Sunset)",
    "어비스 (Abyss)",
    "코로드 (Corrode)",
    "서밋 (Summit)",
]

def get_or_assign_valorant_map(guild_id: int, session_id: int, reroll: bool = False) -> str:
    key = (guild_id, session_id)
    current = SESSION_VALORANT_MAP.get(key)
    if current and not reroll:
        return current

    candidates = [m for m in VALORANT_MAPS if m != current] or VALORANT_MAPS
    chosen = random.choice(candidates)
    SESSION_VALORANT_MAP[key] = chosen
    return chosen
