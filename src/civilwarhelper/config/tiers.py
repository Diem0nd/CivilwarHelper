# 밸런싱용 티어 기본 점수
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

LOL_TIER_NAMES_ORDERED = [
    "Unranked", "Iron", "Bronze", "Silver", "Gold",
    "Platinum", "Emerald", "Diamond", "Master", "Grandmaster", "Challenger",
]

VAL_TIER_NAMES_ORDERED = [
    "Unranked", "Iron", "Bronze", "Silver", "Gold",
    "Platinum", "Diamond", "Ascendant", "Immortal", "Radiant",
]

# 발로 경쟁전 티어 번호 매핑용 (3~26이 아이언1~불멸3, 27이 레디언트)
VAL_DIVIDED_TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "DIAMOND", "ASCENDANT", "IMMORTAL"]
