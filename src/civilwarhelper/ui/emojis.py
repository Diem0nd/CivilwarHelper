import logging

import discord

# 커스텀 이모지 캐시
CUSTOM_EMOJI_CACHE: dict[str, discord.Emoji | discord.PartialEmoji | str] = {}
_emoji_client: discord.Client | None = None

# 포지션/역할군 입력값을 실제 등록된 커스텀 이모지 이름으로 변환하는 매핑
_POSITION_EMOJI_NAME_MAP: dict[str, dict[str, str]] = {
    "lol": {
        "TOP": "lol_TOP",
        "JUNGLE": "lol_JGL",
        "JGL": "lol_JGL",
        "MID": "lol_MID",
        "BOT": "lol_BOT",
        "BOTTOM": "lol_BOT",
        "ADC": "lol_BOT",
        "AD CARRY": "lol_BOT",
        "SUPPORT": "lol_SUP",
        "SUPPORTER": "lol_SUP",
        "SUP": "lol_SUP",
    },
    "valorant": {
        "DUELIST": "val_DUEL",
        "DUEL": "val_DUEL",
        "INITIATOR": "val_INIT",
        "INIT": "val_INIT",
        "CONTROLLER": "val_CTRL",
        "CTRL": "val_CTRL",
        "SENTINEL": "val_SENT",
        "SENT": "val_SENT",
        "FLEX": "val_FLEX",
    },
}


async def load_custom_emojis(bot_client: discord.Client) -> None:
    global _emoji_client
    _emoji_client = bot_client
    for em in bot_client.emojis:
        CUSTOM_EMOJI_CACHE[em.name] = em

    if hasattr(bot_client, "fetch_application_emojis"):
        try:
            for em in await bot_client.fetch_application_emojis():
                CUSTOM_EMOJI_CACHE[em.name] = em
        except discord.HTTPException as e:
            logging.debug("앱 이모지 로드 실패: %s", e)


def get_custom_emoji(name: str, fallback: str = "") -> str:
    if name in CUSTOM_EMOJI_CACHE:
        return str(CUSTOM_EMOJI_CACHE[name])

    for em in (_emoji_client.emojis if _emoji_client else ()):
        if em.name == name:
            CUSTOM_EMOJI_CACHE[name] = em
            return str(em)

    return fallback if fallback else f":{name}:"


def get_button_emoji(name: str, fallback: str | None = None):
    if name in CUSTOM_EMOJI_CACHE:
        return CUSTOM_EMOJI_CACHE[name]

    for em in (_emoji_client.emojis if _emoji_client else ()):
        if em.name == name:
            CUSTOM_EMOJI_CACHE[name] = em
            return em

    return fallback


def get_tier_emoji(game: str, tier: str, fallback: str = "⬜") -> str:
    prefix = "lol" if game == "lol" else "val"
    key = tier.strip().upper()
    # lolGOLD, lol_GOLD 둘 다 지원
    for name in (f"{prefix}{key}", f"{prefix}_{key}"):
        emoji = get_custom_emoji(name)
        if emoji != f":{name}:":
            return emoji
    return fallback


def _resolve_position_emoji_name(game: str, pos_text: str | None) -> str | None:
    if not pos_text:
        return None
    game_key = "lol" if str(game).lower() == "lol" else "valorant"
    cleaned = pos_text.strip().upper()
    return _POSITION_EMOJI_NAME_MAP.get(game_key, {}).get(cleaned)


def get_position_emoji(game: str, pos_text: str | None, fallback: str = "") -> str:
    emoji_name = _resolve_position_emoji_name(game, pos_text)
    if not emoji_name:
        return fallback
    emoji = get_custom_emoji(emoji_name)
    if emoji != f":{emoji_name}:":
        return emoji
    return fallback


def get_position_button_emoji(game: str, pos_text: str | None, fallback: str | None = None):
    emoji_name = _resolve_position_emoji_name(game, pos_text)
    if not emoji_name:
        return fallback
    return get_button_emoji(emoji_name, fallback=fallback)
