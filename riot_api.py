import os
from collections import Counter
from urllib.parse import quote
import aiohttp

ACCOUNT_REGION = "asia"
PLATFORM_REGION = "kr"


class RiotAPIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def get_headers() -> dict:
    api_key = os.getenv("RIOT_API_KEY", "").strip()
    return {"X-Riot-Token": api_key}


async def riot_get(session: aiohttp.ClientSession, url: str):
    async with session.get(url, headers=get_headers()) as resp:
        if resp.status == 200:
            return await resp.json()
        if resp.status == 404:
            raise RiotAPIError(404, "라이엇 계정을 찾을 수 없습니다.")
        if resp.status in (401, 403):
            raise RiotAPIError(resp.status, "RIOT_API_KEY가 만료되었거나 유효하지 않습니다.")
        if resp.status == 429:
            raise RiotAPIError(429, "라이엇 API 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.")
        text = await resp.text()
        raise RiotAPIError(resp.status, f"라이엇 API 오류 ({resp.status}): {text[:120]}")


async def get_account_by_riot_id(session: aiohttp.ClientSession, game_name: str, tagline: str) -> dict:
    encoded_name = quote(game_name.strip())
    encoded_tag = quote(tagline.strip())
    url = f"https://{ACCOUNT_REGION}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{encoded_name}/{encoded_tag}"
    return await riot_get(session, url)


async def get_summoner_by_puuid(session: aiohttp.ClientSession, puuid: str) -> dict:
    url = f"https://{PLATFORM_REGION}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{quote(puuid)}"
    return await riot_get(session, url)


async def get_ranked_entries(session: aiohttp.ClientSession, summoner_id: str) -> list[dict]:
    url = f"https://{PLATFORM_REGION}.api.riotgames.com/lol/league/v4/entries/by-summoner/{quote(summoner_id)}"
    return await riot_get(session, url)


async def get_ranked_entries_by_puuid(session: aiohttp.ClientSession, puuid: str) -> list[dict]:
    url = f"https://{PLATFORM_REGION}.api.riotgames.com/lol/league/v4/entries/by-puuid/{quote(puuid)}"
    return await riot_get(session, url)


async def get_ranked_entries_for_account(session: aiohttp.ClientSession, puuid: str, summoner_id: str | None = None) -> list[dict]:
    try:
        return await get_ranked_entries_by_puuid(session, puuid)
    except RiotAPIError:
        if summoner_id:
            return await get_ranked_entries(session, summoner_id)
        return []


async def get_match_ids(
    session: aiohttp.ClientSession,
    puuid: str,
    queue_id: int | None = None,
    count: int = 5,
) -> list[str]:
    url = f"https://{ACCOUNT_REGION}.api.riotgames.com/lol/match/v5/matches/by-puuid/{quote(puuid)}/ids?start=0&count={count}"
    if queue_id is not None:
        url += f"&queue={queue_id}"
    return await riot_get(session, url)


async def get_match(session: aiohttp.ClientSession, match_id: str) -> dict:
    url = f"https://{ACCOUNT_REGION}.api.riotgames.com/lol/match/v5/matches/{quote(match_id)}"
    return await riot_get(session, url)


def format_rank(entry: dict | None) -> str:
    if not entry:
        return "Unranked"
    tier = str(entry.get("tier", "")).strip().title()
    rank = str(entry.get("rank", "")).strip().upper()
    lp = entry.get("leaguePoints", 0)
    if not tier:
        return "Unranked"
    if tier.upper() in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return f"{tier} ({lp} LP)"
    return f"{tier} {rank} ({lp} LP)"


async def get_primary_position(session: aiohttp.ClientSession, puuid: str) -> str:
    role_map = {
        "TOP": "TOP",
        "JUNGLE": "JUNGLE",
        "MIDDLE": "MID",
        "BOTTOM": "ADC",
        "UTILITY": "SUPPORT",
    }
    try:
        match_ids = await get_match_ids(session, puuid, count=10)
    except Exception:
        return "ALL"

    positions: list[str] = []
    for mid in match_ids[:5]:
        try:
            m_data = await get_match(session, mid)
            participants = m_data.get("info", {}).get("participants", [])
            for p in participants:
                if p.get("puuid") == puuid:
                    raw_pos = str(p.get("teamPosition") or p.get("individualPosition") or "").upper()
                    if raw_pos in role_map:
                        positions.append(role_map[raw_pos])
                    break
        except Exception:
            continue

    if not positions:
        return "ALL"
    return Counter(positions).most_common(1)[0][0]


async def fetch_lol_profile_data(session: aiohttp.ClientSession, game_name: str, tagline: str) -> dict:
    account = await get_account_by_riot_id(session, game_name, tagline)
    puuid = account["puuid"]
    canonical_name = account.get("gameName", game_name)
    canonical_tag = account.get("tagLine", tagline)

    summoner_id = None
    try:
        summoner = await get_summoner_by_puuid(session, puuid)
        summoner_id = summoner.get("id")
    except Exception:
        pass

    entries = await get_ranked_entries_for_account(session, puuid, summoner_id)
    solo_entry = next((e for e in entries if e.get("queueType") == "RANKED_SOLO_5x5"), None)
    flex_entry = next((e for e in entries if e.get("queueType") == "RANKED_FLEX_SR"), None)

    solo_tier = format_rank(solo_entry)
    flex_tier = format_rank(flex_entry)
    main_pos = await get_primary_position(session, puuid)

    return {
        "puuid": puuid,
        "game_name": canonical_name,
        "tagline": canonical_tag,
        "solo_tier": solo_tier,
        "flex_tier": flex_tier,
        "main_position": main_pos,
    }
