import re
from collections import Counter
from urllib.parse import quote

import aiohttp

from civilwarhelper.config.positions import VAL_AGENT_ROLES
from civilwarhelper.config.tiers import VAL_DIVIDED_TIERS
from civilwarhelper.riot.client import ACCOUNT_ROUTING_URL, RiotAPIError, _get_json, get_account_by_riot_id

VAL_API_KEY_ENV = "RIOT_VAL_API_KEY"
DEFAULT_SHARD = "kr"
RECENT_MATCH_COUNT = 10

# 요원 uuid -> 영문명 캐시
_agent_names: dict[str, str] = {}


def shard_url(shard: str) -> str:
    return f"https://{shard}.api.riotgames.com"


def competitive_tier_name(tier_number: int | None) -> str:
    if not tier_number or tier_number < 3:
        return "Unranked"
    if tier_number >= 27:
        return "Radiant"
    idx, div = divmod(tier_number - 3, 3)
    if idx >= len(VAL_DIVIDED_TIERS):
        return "Unranked"
    return f"{VAL_DIVIDED_TIERS[idx].title()} {div + 1}"


def agent_role(agent_name: str | None) -> str | None:
    key = re.sub(r"[^A-Z0-9]", "", (agent_name or "").upper())
    return VAL_AGENT_ROLES.get(key)


def pick_main_role(roles: list[str]) -> str:
    if not roles:
        return "Unknown"
    role, cnt = Counter(roles).most_common(1)[0]
    # 5판 이상 했는데 한 포지션 비중이 40% 안 되면 올라운더(Flex) 처리
    if len(roles) >= 5 and cnt / len(roles) < 0.4:
        return "Flex"
    return role


async def get_active_shard(session: aiohttp.ClientSession, puuid: str) -> str:
    data = await _get_json(
        session,
        ACCOUNT_ROUTING_URL,
        f"/riot/account/v1/active-shards/by-game/val/by-puuid/{quote(puuid, safe='')}",
    )
    return data.get("activeShard") or DEFAULT_SHARD


async def get_matchlist(session: aiohttp.ClientSession, shard: str, puuid: str) -> list[dict]:
    data = await _get_json(
        session,
        shard_url(shard),
        f"/val/match/v1/matchlists/by-puuid/{quote(puuid, safe='')}",
    )
    return sorted(data.get("history", []), key=lambda x: x.get("gameStartTimeMillis", 0), reverse=True)


async def get_match(session: aiohttp.ClientSession, shard: str, match_id: str) -> dict:
    return await _get_json(
        session,
        shard_url(shard),
        f"/val/match/v1/matches/{quote(match_id, safe='')}",
    )


async def load_agent_names(session: aiohttp.ClientSession, shard: str) -> dict[str, str]:
    if not _agent_names:
        content = await _get_json(session, shard_url(shard), "/val/content/v1/contents", params={"locale": "en-US"})
        for ch in content.get("characters", []):
            if ch.get("id") and ch.get("name"):
                _agent_names[ch["id"].lower()] = ch["name"]
    return _agent_names


def summarize_matches(matches: list[dict], puuid: str, agent_names: dict[str, str]) -> tuple[str, str]:
    comp_tier = "Unranked"
    roles: list[str] = []

    for m in matches:
        player = next((p for p in m.get("players", []) if p.get("puuid") == puuid), None)
        if not player:
            continue

        if comp_tier == "Unranked" and m.get("matchInfo", {}).get("queueId") == "competitive":
            comp_tier = competitive_tier_name(player.get("competitiveTier"))

        role = agent_role(agent_names.get(str(player.get("characterId", "")).lower()))
        if role:
            roles.append(role)

    return comp_tier, pick_main_role(roles)


async def fetch_val_profile_data(
    session: aiohttp.ClientSession,
    game_name: str,
    tagline: str,
) -> dict:
    account = await get_account_by_riot_id(session=session, game_name=game_name, tagline=tagline)
    puuid = account["puuid"]

    try:
        shard = await get_active_shard(session, puuid)
    except RiotAPIError:
        shard = DEFAULT_SHARD

    history = [m for m in await get_matchlist(session, shard, puuid) if m.get("matchId")]
    picked = history[:RECENT_MATCH_COUNT]

    # 최근 10판에 경쟁전이 하나도 없으면 티어 확인용으로 가장 최근 경쟁전 1판 추가
    if not any(m.get("queueId") == "competitive" for m in picked):
        last_comp = next((m for m in history if m.get("queueId") == "competitive"), None)
        if last_comp is not None:
            picked.append(last_comp)

    agent_names = await load_agent_names(session, shard)
    matches = [await get_match(session, shard, m["matchId"]) for m in picked]

    comp_tier, main_role = summarize_matches(matches, puuid, agent_names)
    return {
        "puuid": puuid,
        "competitive_tier": comp_tier,
        "main_position": main_role,
    }
