LOL_COMBINED_POSITION_LABELS = [
    ("Top", "TOP 탑 Top"),
    ("Jungle", "JGL 정글 Jungle"),
    ("Mid", "MID 미드 Mid"),
    ("Adc", "ADC 원딜 AD Carry"),
    ("Support", "SUP 서포터 Supporter"),
]

VAL_COMBINED_POSITION_LABELS = [
    ("Duelist", "DUEL 타격대 Duelist"),
    ("Initiator", "INIT 척후대 Initiator"),
    ("Controller", "CTRL 전략가 Controller"),
    ("Sentinel", "SENT 감시자 Sentinel"),
    ("Flex", "FLEX 올라운더"),
]

LOL_POSITIONS = ["Top", "Jungle", "Mid", "Bot", "Support", "Fill"]
VAL_POSITIONS = ["Duelist", "Initiator", "Controller", "Sentinel", "Flex"]

LOL_STANDARD_POSITIONS = ["Top", "Jungle", "Mid", "AD carry", "Support"]
VAL_STANDARD_POSITIONS = ["Duelist", "Initiator", "Controller", "Sentinel", "Flex"]

LOL_POS_SHORT_MAP = {
    "TOP": "TOP",
    "JUNGLE": "JGL",
    "JGL": "JGL",
    "MID": "MID",
    "BOT": "ADC",
    "BOTTOM": "ADC",
    "ADC": "ADC",
    "AD CARRY": "ADC",
    "SUPPORT": "SUP",
    "SUPPORTER": "SUP",
    "SUP": "SUP",
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

# 신캐 나오면 여기 추가 (영문 대문자, 특수문자 제외)
VAL_AGENT_ROLES = {
    **dict.fromkeys(["JETT", "PHOENIX", "REYNA", "RAZE", "YORU", "NEON", "ISO", "WAYLAY"], "Duelist"),
    **dict.fromkeys(["SOVA", "BREACH", "SKYE", "KAYO", "FADE", "GEKKO", "TEJO"], "Initiator"),
    **dict.fromkeys(["BRIMSTONE", "VIPER", "OMEN", "ASTRA", "HARBOR", "CLOVE"], "Controller"),
    **dict.fromkeys(["KILLJOY", "CYPHER", "SAGE", "CHAMBER", "DEADLOCK", "VYSE", "VETO"], "Sentinel"),
}
