import logging

import discord

# 커스텀 이모지 캐시
CUSTOM_EMOJI_CACHE: dict[str, discord.Emoji | discord.PartialEmoji | str] = {}
_emoji_client: discord.Client | None = None


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
