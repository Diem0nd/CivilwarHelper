import asyncio
import re
from collections import Counter
from urllib.parse import quote

import aiohttp

from civilwarhelper.config.positions import VAL_AGENT_ROLES
from civilwarhelper.config.tiers import VAL_DIVIDED_TIERS
from civilwarhelper.riot.client import (
    ACCOUNT_ROUTING_URL,
    RiotAPIError,
    _get_json,
    get_account_by_riot_id,
    get_api_key,
)

VAL_API_KEY_ENV = "RIOT_VAL_API_KEY"
HENRIK_BASE_URL = "https://api.henrikdev.xyz"
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


async def _get_henrik_json(
    session: aiohttp.ClientSession,
    path: str,
    params: dict | None = None,
) -> dict:
    api_key = get_api_key(VAL_API_KEY_ENV).strip()
    url = f"{HENRIK_BASE_URL}{path}"
    headers = {"Authorization": api_key, "Accept": "application/json"}

    for attempt in range(3):
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)

            if resp.status == 429 and attempt < 2:
                await asyncio.sleep(2.0)
                continue

            if resp.status in (401, 403):
                raise RiotAPIError("HenrikDev 발로란트 API 키가 유효하지 않거나 만료되었습니다.", resp.status)
            if resp.status == 404:
                raise RiotAPIError("발로란트 계정 또는 전적 데이터를 찾을 수 없습니다.", 404)
            if resp.status == 429:
                raise RiotAPIError("발로란트 API 요청 한도 초과. 잠시 후 다시 시도하세요.", 429)

            raise RiotAPIError(f"발로란트 API 오류 (HTTP {resp.status})", resp.status)

    raise RiotAPIError("발로란트 API 요청 실패")


async def _fetch_val_profile_data_henrik(
    session: aiohttp.ClientSession,
    game_name: str,
    tagline: str,
) -> dict:
    enc_name = quote(game_name, safe="")
    enc_tag = quote(tagline, safe="")

    # 1. 계정 조회 (puuid 및 지역 확인)
    acc_resp = await _get_henrik_json(session, f"/valorant/v1/account/{enc_name}/{enc_tag}")
    acc_data = acc_resp.get("data") or {}
    puuid = acc_data.get("puuid")
    region = acc_data.get("region") or DEFAULT_SHARD
    if not puuid:
        raise RiotAPIError("발로란트 계정의 PUUID를 찾을 수 없습니다.", 404)

    # 2. 경쟁전 티어(MMR) 조회
    comp_tier = "Unranked"
    try:
        mmr_resp = await _get_henrik_json(session, f"/valorant/v2/mmr/{region}/{enc_name}/{enc_tag}")
        mmr_data = mmr_resp.get("data") or {}
        current_data = mmr_data.get("current_data") or {}
        tier_num = current_data.get("currenttier")
        if tier_num:
            comp_tier = competitive_tier_name(int(tier_num))
    except RiotAPIError as e:
        if e.status_code != 404:
            raise

    # 3. 최근 매치 기준 주 포지션(역할군) 추출
    roles: list[str] = []
    try:
        matches_resp = await _get_henrik_json(
            session,
            f"/valorant/v3/matches/{region}/{enc_name}/{enc_tag}",
            params={"size": RECENT_MATCH_COUNT},
        )
        for m in matches_resp.get("data") or []:
            all_players = (m.get("players") or {}).get("all_players") or []
            me = next((p for p in all_players if p.get("puuid") == puuid), None)
            if not me:
                continue

            if comp_tier == "Unranked":
                meta = m.get("metadata") or {}
                if str(meta.get("mode_id", "")).lower() == "competitive":
                    comp_tier = competitive_tier_name(me.get("currenttier"))

            role = agent_role(me.get("character"))
            if role:
                roles.append(role)
    except RiotAPIError as e:
        if e.status_code != 404:
            raise

    return {
        "puuid": puuid,
        "competitive_tier": comp_tier,
        "main_position": pick_main_role(roles),
    }


async def fetch_val_profile_data(
    session: aiohttp.ClientSession,
    game_name: str,
    tagline: str,
) -> dict:
    api_key = get_api_key(VAL_API_KEY_ENV).strip()
    # HenrikDev API 키(HDEV-...)를 사용하거나 RGAPI-로 시작하지 않는 경우 HenrikDev API 사용
    if api_key.upper().startswith("HDEV-") or not api_key.upper().startswith("RGAPI-"):
        return await _fetch_val_profile_data_henrik(session, game_name, tagline)

    # 기존 라이엇 공식 API 로직 (추후 라이엇 Production 키 발급 시 자동 호환)
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
