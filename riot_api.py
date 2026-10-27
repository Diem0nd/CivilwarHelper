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


def get_api_key() -> str:
    api_key = os.getenv("RIOT_API_KEY")

    if not api_key:
        raise RiotAPIError(
            "RIOT_API_KEY is missing from the environment."
        )

    return api_key


def get_headers() -> dict[str, str]:
    return {
        "X-Riot-Token": get_api_key(),
    }


async def _get_json(
    session: aiohttp.ClientSession,
    base_url: str,
    path: str,
    params: dict | None = None,
):
    url = f"{base_url}{path}"

    async with session.get(url, params=params) as response:
        if response.status == 200:
            return await response.json(content_type=None)

        if response.status == 401:
            raise RiotAPIError(
                "Riot API 키가 유효하지 않거나 만료되었거나 올바르게 로드되지 않았습니다.",
                response.status,
            )

        if response.status == 403:
            raise RiotAPIError(
                "Riot API key 가 만료되었거나 올바르게 로드되지 않았습니다.",
                response.status,
            )

        if response.status == 404:
            raise RiotAPIError(
                "Riot 계정 또는 요청한 리그 데이터를 찾을 수 없습니다.",
                response.status,
            )

        if response.status == 429:
            raise RiotAPIError(
                "Riot API rate limit을 초과했습니다. 나중에 다시 시도하세요.",
                response.status,
            )

        raise RiotAPIError(
            f"The Riot API returned HTTP status {response.status}.",
            response.status,
        )


async def get_account_by_riot_id(
    session: aiohttp.ClientSession,
    game_name: str,
    tagline: str,
):
    encoded_game_name = quote(game_name, safe="")
    encoded_tagline = quote(tagline, safe="")

    return await _get_json(
        session=session,
        base_url=ACCOUNT_ROUTING_URL,
        path=(
            "/riot/account/v1/accounts/by-riot-id/"
            f"{encoded_game_name}/{encoded_tagline}"
        ),
    )


async def get_summoner_by_puuid(
    session: aiohttp.ClientSession,
    puuid: str,
):
    encoded_puuid = quote(puuid, safe="")

    return await _get_json(
        session=session,
        base_url=LEAGUE_ROUTING_URL,
        path=f"/lol/summoner/v4/summoners/by-puuid/{encoded_puuid}",
    )


async def get_ranked_entries(
    session: aiohttp.ClientSession,
    summoner_id: str,
):
    encoded_summoner_id = quote(summoner_id, safe="")

    return await _get_json(
        session=session,
        base_url=LEAGUE_ROUTING_URL,
        path=(
            "/lol/league/v4/entries/by-summoner/"
            f"{encoded_summoner_id}"
        ),
    )

async def get_ranked_entries_by_puuid(
    session: aiohttp.ClientSession,
    puuid: str,
):
    encoded_puuid = quote(puuid, safe="")

    return await _get_json(
        session=session,
        base_url=LEAGUE_ROUTING_URL,
        path=f"/lol/league/v4/entries/by-puuid/{encoded_puuid}",
    )

async def get_ranked_entries_for_account(
    session: aiohttp.ClientSession,
    puuid: str,
):
    """
    Tries the PUUID-based ranked endpoint first.

    If that endpoint is unavailable, falls back to the older
    summoner-ID-based method.
    """
    try:
        return await get_ranked_entries_by_puuid(
            session=session,
            puuid=puuid,
        )

    except RiotAPIError as error:
        if error.status_code != 404:
            raise

        # Fallback for APIs or accounts where the PUUID endpoint
        # is unavailable.
        summoner = await get_summoner_by_puuid(
            session=session,
            puuid=puuid,
        )

        summoner_id = summoner.get("id")

        if not summoner_id:
            returned_keys = ", ".join(summoner.keys())

            raise RiotAPIError(
                (
                    "The Riot summoner response did not contain a "
                    f"summoner ID. Returned fields: {returned_keys}"
                )
            )

        return await get_ranked_entries(
            session=session,
            summoner_id=summoner_id,
        )

async def get_match_ids(
    session: aiohttp.ClientSession,
    puuid: str,
    queue_id: int,
    count: int = 5,
):
    encoded_puuid = quote(puuid, safe="")

    return await _get_json(
        session=session,
        base_url=MATCH_ROUTING_URL,
        path=f"/lol/match/v5/matches/by-puuid/{encoded_puuid}/ids",
        params={
            "queue": queue_id,
            "start": 0,
            "count": count,
        },
    )


async def get_match(
    session: aiohttp.ClientSession,
    match_id: str,
):
    encoded_match_id = quote(match_id, safe="")

    return await _get_json(
        session=session,
        base_url=MATCH_ROUTING_URL,
        path=f"/lol/match/v5/matches/{encoded_match_id}",
    )


def format_rank(entry: dict | None) -> str:
    if entry is None:
        return "Unranked"

    tier = entry.get("tier", "Unknown").title()
    division = entry.get("rank", "")

    if division:
        return f"{tier} {division}"

    return tier


async def get_primary_position(
    session: aiohttp.ClientSession,
    puuid: str,
) -> str:
    position_counts: dict[str, int] = {}

    # 420 = Ranked Solo/Duo
    # 440 = Ranked Flex
    for queue_id in (420, 440):
        match_ids = await get_match_ids(
            session=session,
            puuid=puuid,
            queue_id=queue_id,
            count=5,
        )

        for match_id in match_ids:
            match = await get_match(
                session=session,
                match_id=match_id,
            )

            participants = match.get("info", {}).get(
                "participants",
                [],
            )

            participant = next(
                (
                    item
                    for item in participants
                    if item.get("puuid") == puuid
                ),
                None,
            )

            if participant is None:
                continue

            raw_position = participant.get("teamPosition")

            if raw_position not in POSITION_NAMES:
                continue

            position_counts[raw_position] = (
                position_counts.get(raw_position, 0) + 1
            )

    if not position_counts:
        return "Unknown"

    primary_position = max(
        position_counts,
        key=position_counts.get,
    )

    return POSITION_NAMES[primary_position]


async def fetch_lol_profile_data(
    session: aiohttp.ClientSession,
    game_name: str,
    tagline: str,
):
    account = await get_account_by_riot_id(
        session=session,
        game_name=game_name,
        tagline=tagline,
    )

    puuid = account["puuid"]

    ranked_entries = await get_ranked_entries_for_account(
        session=session,
        puuid=puuid,
    )

    solo_entry = next(
        (
            entry
            for entry in ranked_entries
            if entry.get("queueType") == "RANKED_SOLO_5x5"
        ),
        None,
    )

    flex_entry = next(
        (
            entry
            for entry in ranked_entries
            if entry.get("queueType") == "RANKED_FLEX_SR"
        ),
        None,
    )

    primary_position = await get_primary_position(
        session=session,
        puuid=puuid,
    )

    return {
        "puuid": puuid,
        "solo_tier": format_rank(solo_entry),
        "flex_tier": format_rank(flex_entry),
        "main_position": primary_position,
    }
