# 롤은 피어리스, 발로는 맵 밴
DRAFT_RULE_NAME = {
    "lol": "피어리스",
    "valorant": "맵 밴",
}


def draft_rule_name(game: str) -> str:
    return DRAFT_RULE_NAME.get(game, DRAFT_RULE_NAME["lol"])
