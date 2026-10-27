import asyncio
import os
from urllib.parse import quote

import aiohttp

ACCOUNT_ROUTING_URL = "https://asia.api.riotgames.com"
LEAGUE_ROUTING_URL = "https://kr.api.riotgames.com"
MATCH_ROUTING_URL = "https://asia.api.riotgames.com"

POSITION_NAMES = {
    "TOP": "Top",
    "JUNGLE": "Jungle",
    "MIDDLE": "Mid",
    "BOTTOM": "Bot",
    "UTILITY": "Support",
}


class RiotAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def get_api_key(env_name: str = "RIOT_API_KEY") -> str:
    api_key = os.getenv(env_name)
    if not api_key:
        raise RiotAPIError(f"{env_name} 환경변수가 설정되지 않았습니다.")
    return api_key


def get_headers(env_name: str = "RIOT_API_KEY") -> dict[str, str]:
    return {"X-Riot-Token": get_api_key(env_name)}


async def _get_json(
    session: aiohttp.ClientSession,
    base_url: str,
    path: str,
    params: dict | None = None,
):
    url = f"{base_url}{path}"

    for attempt in range(3):
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)

            # 429 뜨면 Retry-After 만큼 대기 후 재시도
            if resp.status == 429 and attempt < 2:
                try:
                    wait = float(resp.headers.get("Retry-After", "1"))
                except (TypeError, ValueError):
                    wait = 1.0
                await asyncio.sleep(min(max(wait, 0.0), 10.0))
                continue

            if resp.status == 401:
                raise RiotAPIError("Riot API 키가 유효하지 않거나 만료되었습니다.", 401)
            if resp.status == 403:
                raise RiotAPIError("Riot API 키 권한이 없거나 만료되었습니다.", 403)
            if resp.status == 404:
                raise RiotAPIError("Riot 계정 또는 리그 데이터를 찾을 수 없습니다.", 404)
            if resp.status == 429:
                raise RiotAPIError("Riot API 요청 한도 초과. 잠시 후 다시 시도하세요.", 429)

            raise RiotAPIError(f"Riot API 오류 (HTTP {resp.status})", resp.status)


async def get_account_by_riot_id(session: aiohttp.ClientSession, game_name: str, tagline: str):
    return await _get_json(
        session,
        ACCOUNT_ROUTING_URL,
        f"/riot/account/v1/accounts/by-riot-id/{quote(game_name, safe='')}/{quote(tagline, safe='')}",
    )


async def get_summoner_by_puuid(session: aiohttp.ClientSession, puuid: str):
    return await _get_json(
        session,
        LEAGUE_ROUTING_URL,
        f"/lol/summoner/v4/summoners/by-puuid/{quote(puuid, safe='')}",
    )


async def get_ranked_entries(session: aiohttp.ClientSession, summoner_id: str):
    return await _get_json(
        session,
        LEAGUE_ROUTING_URL,
        f"/lol/league/v4/entries/by-summoner/{quote(summoner_id, safe='')}",
    )


async def get_ranked_entries_by_puuid(session: aiohttp.ClientSession, puuid: str):
    return await _get_json(
        session,
        LEAGUE_ROUTING_URL,
        f"/lol/league/v4/entries/by-puuid/{quote(puuid, safe='')}",
    )


async def get_ranked_entries_for_account(session: aiohttp.ClientSession, puuid: str):
    # puuid 기반 엔드포인트 먼저 찌르고 404면 구버전(summoner_id)으로 폴백
    try:
        return await get_ranked_entries_by_puuid(session, puuid)
    except RiotAPIError as e:
        if e.status_code != 404:
            raise
        summoner = await get_summoner_by_puuid(session, puuid)
        summoner_id = summoner.get("id")
        if not summoner_id:
            raise RiotAPIError(f"summoner ID를 찾을 수 없음 (fields: {', '.join(summoner.keys())})")
        return await get_ranked_entries(session, summoner_id)


async def get_match_ids(
    session: aiohttp.ClientSession,
    puuid: str,
    queue_id: int,
    count: int = 5,
):
    return await _get_json(
        session,
        MATCH_ROUTING_URL,
        f"/lol/match/v5/matches/by-puuid/{quote(puuid, safe='')}/ids",
        params={"queue": queue_id, "start": 0, "count": count},
    )


async def get_match(session: aiohttp.ClientSession, match_id: str):
    return await _get_json(
        session,
        MATCH_ROUTING_URL,
        f"/lol/match/v5/matches/{quote(match_id, safe='')}",
    )


def format_rank(entry: dict | None) -> str:
    if entry is None:
        return "Unranked"
    tier = entry.get("tier", "Unknown").title()
    div = entry.get("rank", "")
    return f"{tier} {div}" if div else tier


async def get_primary_position(session: aiohttp.ClientSession, puuid: str) -> str:
    counts: dict[str, int] = {}

    # 420: 솔랭, 440: 자랭 최근 5판씩만 확인
    for qid in (420, 440):
        match_ids = await get_match_ids(session, puuid, queue_id=qid, count=5)
        for mid in match_ids:
            match = await get_match(session, mid)
            participants = match.get("info", {}).get("participants", [])
            me = next((p for p in participants if p.get("puuid") == puuid), None)
            if not me:
                continue
            pos = me.get("teamPosition")
            if pos in POSITION_NAMES:
                counts[pos] = counts.get(pos, 0) + 1

    if not counts:
        return "Unknown"
    return POSITION_NAMES[max(counts, key=counts.get)]


async def fetch_lol_profile_data(session: aiohttp.ClientSession, game_name: str, tagline: str):
    account = await get_account_by_riot_id(session, game_name, tagline)
    puuid = account["puuid"]
    entries = await get_ranked_entries_for_account(session, puuid)

    solo = next((e for e in entries if e.get("queueType") == "RANKED_SOLO_5x5"), None)
    flex = next((e for e in entries if e.get("queueType") == "RANKED_FLEX_SR"), None)
    main_pos = await get_primary_position(session, puuid)

    return {
        "puuid": puuid,
        "solo_tier": format_rank(solo),
        "flex_tier": format_rank(flex),
        "main_position": main_pos,
    }
