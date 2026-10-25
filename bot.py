import os
import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv

import database
import riot_api
from match_common import (
    POSITION_SHORT_LABEL,
    format_tier_with_custom_emoji,
    get_custom_emoji,
    load_custom_emojis,
)
from lol_civilwar import (
    LOL_POSITION_CHOICES,
    LolRecruitmentView,
    format_lol_lobby_message,
    mark_lol_lobby_closed,
    sync_lol_lobby_message,
)
from val_civilwar import (
    VAL_POSITION_CHOICES,
    ValRecruitmentView,
    format_val_lobby_message,
    sync_val_lobby_message_if_exists,
)
from minigames import register_minigame_commands

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()


# =====================================================================
# 봇 클래스 정의
# =====================================================================

class CivilwarBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents. guilds = True
        intents.members = True
        super().__init__(intents=intents)
        self.command_tree = app_commands.CommandTree(self)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        database.initialize_database()
        self.http_session = aiohttp.ClientSession()
        await self.command_tree.sync()

    async def on_ready(self):
        load_custom_emojis(self)
        print(f"✅ 로그인 완료: {self.user} (ID: {self.user.id})")
        print("✅ 슬래시 명령어 동기화 및 이모지 로드가 완료되었습니다.")

    async def close(self):
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await super().close()


bot = CivilwarBot()


# =====================================================================
# 공통 선택지 상수
# =====================================================================

GAME_CHOICES = [
    app_commands.Choice(name="리그 오브 레전드 (LoL)", value="lol"),
    app_commands.Choice(name="발로란트 (VALORANT)", value="valorant"),
]

LOL_TIER_CHOICES = [
    app_commands.Choice(name=t, value=t)
    for t in [
        "Unranked",
        "Iron IV", "Iron III", "Iron II", "Iron I",
        "Bronze IV", "Bronze III", "Bronze II", "Bronze I",
        "Silver IV", "Silver III", "Silver II", "Silver I",
        "Gold IV", "Gold III", "Gold II", "Gold I",
        "Platinum IV", "Platinum III", "Platinum II", "Platinum I",
        "Emerald IV", "Emerald III", "Emerald II", "Emerald I",
        "Diamond IV", "Diamond III", "Diamond II", "Diamond I",
        "Master", "Grandmaster", "Challenger",
    ][:25]
]

VAL_TIER_CHOICES = [
    app_commands.Choice(name=t, value=t)
    for t in [
        "Unranked",
        "Iron 1", "Iron 2", "Iron 3",
        "Bronze 1", "Bronze 2", "Bronze 3",
        "Silver 1", "Silver 2", "Silver 3",
        "Gold 1", "Gold 2", "Gold 3",
        "Platinum 1", "Platinum 2", "Platinum 3",
        "Diamond 1", "Diamond 2", "Diamond 3",
        "Ascendant 1", "Ascendant 2", "Ascendant 3",
        "Immortal 1", "Immortal 2", "Immortal 3",
        "Radiant",
    ][:25]
]


def _is_admin(interaction: discord.Interaction) -> bool:
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


# =====================================================================
# 1. 프로필 등록 및 관리 명령어
# =====================================================================

@bot.command_tree.command(name="register-lol", description="롤(LoL) 라이엇 계정을 봇에 등록합니다.")
@app_commands.describe(
    game_name="라이엇 게임 닉네임 (태그 제외)",
    tagline="태그라인 (# 제외, 예: KR1)",
    main_position="주 포지션 선택 (미선택 시 최근 전적 기반 자동 분석)",
    sub_position="부 포지션 선택 (기본: 올라운더)",
    target_user="(관리자 전용) 다른 유저 대신 등록할 경우 선택",
)
@app_commands.choices(main_position=LOL_POSITION_CHOICES, sub_position=LOL_POSITION_CHOICES)
async def register_lol(
    interaction: discord.Interaction,
    game_name: str,
    tagline: str,
    main_position: app_commands.Choice[str] | None = None,
    sub_position: app_commands.Choice[str] | None = None,
    target_user: discord.Member | None = None,
):
    lose_emoji = get_custom_emoji("ALose", "❌")
    thinking_emoji = get_custom_emoji("AThinking", "⏳")

    if target_user and target_user.id != interaction.user.id and not _is_admin(interaction):
        await interaction.response.send_message(
            f"{lose_emoji} 다른 유저의 프로필 등록은 서버 관리자만 가능합니다.",
            ephemeral=True,
        )
        return

    user = target_user or interaction.user
    await interaction.response.defer(thinking=True)

    try:
        assert bot.http_session is not None
        profile_data = await riot_api.fetch_lol_profile_data(
            session=bot.http_session,
            game_name=game_name,
            tagline=tagline,
        )
    except riot_api.RiotAPIError as e:
        await interaction.followup.send(f"{lose_emoji} {e.message}", ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(
            f"{lose_emoji} 라이엇 API 조회 중 오류가 발생했습니다: `{e}`",
            ephemeral=True,
        )
        return

    chosen_main = main_position.value if main_position else profile_data["main_position"]
    chosen_sub = sub_position.value if sub_position else "ALL"

    database.upsert_profile(
        guild_id=interaction.guild_id,
        discord_user_id=user.id,
        discord_nickname=user.display_name,
        game="lol",
        riot_game_name=profile_data["game_name"],
        riot_tagline=profile_data["tagline"],
        puuid=profile_data["puuid"],
        solo_tier=profile_data["solo_tier"],
        flex_tier=profile_data["flex_tier"],
        main_position=chosen_main,
        sub_position=chosen_sub,
    )

    solo_str = format_tier_with_custom_emoji(profile_data["solo_tier"], "lol")
    flex_str = format_tier_with_custom_emoji(profile_data["flex_tier"], "lol")
    main_label = POSITION_SHORT_LABEL.get(chosen_main, chosen_main)
    sub_label = POSITION_SHORT_LABEL.get(chosen_sub, chosen_sub)

    await interaction.followup.send(
        f"✅ **LoL 프로필 등록 완료!** (<@{user.id}>)\n"
        f"• **계정**: `{profile_data['game_name']}#{profile_data['tagline']}`\n"
        f"• **솔로랭크**: {solo_str} | **자유랭크**: {flex_str}\n"
        f"• **주 포지션**: **{main_label}** | **부 포지션**: **{sub_label}**"
    )


@bot.command_tree.command(name="register-val", description="발로란트(VALORANT) 계정을 봇에 등록합니다.")
@app_commands.describe(
    game_name="라이엇 게임 닉네임 (태그 제외)",
    tagline="태그라인 (# 제외, 예: KR1)",
    competitive_tier="현재 경쟁전 티어 (예: Gold 2, Platinum 1, Radiant 등)",
    main_position="주 역할군 선택",
    sub_position="부 역할군 선택 (기본: 올라운더)",
    target_user="(관리자 전용) 다른 유저 대신 등록할 경우 선택",
)
@app_commands.choices(main_position=VAL_POSITION_CHOICES, sub_position=VAL_POSITION_CHOICES)
async def register_val(
    interaction: discord.Interaction,
    game_name: str,
    tagline: str,
    competitive_tier: str = "Unranked",
    main_position: app_commands.Choice[str] | None = None,
    sub_position: app_commands.Choice[str] | None = None,
    target_user: discord.Member | None = None,
):
    lose_emoji = get_custom_emoji("ALose", "❌")
    if target_user and target_user.id != interaction.user.id and not _is_admin(interaction):
        await interaction.response.send_message(
            f"{lose_emoji} 다른 유저의 프로필 등록은 서버 관리자만 가능합니다.",
            ephemeral=True,
        )
        return

    user = target_user or interaction.user
    await interaction.response.defer(thinking=True)

    puuid = ""
    canonical_name = game_name.strip()
    canonical_tag = tagline.strip()
    try:
        if bot.http_session:
            acc = await riot_api.get_account_by_riot_id(bot.http_session, canonical_name, canonical_tag)
            puuid = acc.get("puuid", "")
            canonical_name = acc.get("gameName", canonical_name)
            canonical_tag = acc.get("tagLine", canonical_tag)
    except Exception:
        pass

    chosen_main = main_position.value if main_position else "Flex"
    chosen_sub = sub_position.value if sub_position else "Flex"

    database.upsert_profile(
        guild_id=interaction.guild_id,
        discord_user_id=user.id,
        discord_nickname=user.display_name,
        game="valorant",
        riot_game_name=canonical_name,
        riot_tagline=canonical_tag,
        puuid=puuid,
        competitive_tier=competitive_tier.strip(),
        main_position=chosen_main,
        sub_position=chosen_sub,
    )

    tier_str = format_tier_with_custom_emoji(competitive_tier, "valorant")
    main_label = POSITION_SHORT_LABEL.get(chosen_main, chosen_main)
    sub_label = POSITION_SHORT_LABEL.get(chosen_sub, chosen_sub)

    await interaction.followup.send(
        f"✅ **VALORANT 프로필 등록 완료!** (<@{user.id}>)\n"
        f"• **계정**: `{canonical_name}#{canonical_tag}`\n"
        f"• **경쟁전 티어**: {tier_str}\n"
        f"• **주 역할군**: **{main_label}** | **부 역할군**: **{sub_label}**"
    )


@bot.command_tree.command(name="profile-list", description="서버에 등록된 내전 프로필 목록을 확인합니다.")
@app_commands.describe(game="조회할 게임 선택")
@app_commands.choices(game=GAME_CHOICES)
async def profile_list(interaction: discord.Interaction, game: app_commands.Choice[str]):
    profiles = database.get_profiles_by_game(interaction.guild_id, game.value)
    if not profiles:
        await interaction.response.send_message(
            f"📋 현재 **{game.name}**에 등록된 프로필이 없습니다.",
            ephemeral=True,
        )
        return

    lines = [f"📋 **{game.name} 등록 유저 목록 ({len(profiles)}명)**", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for idx, p in enumerate(profiles[:30], start=1):
        uid = p["discord_user_id"]
        riot_id = f"{p.get('riot_game_name', '')}#{p.get('riot_tagline', '')}"
        main_pos = POSITION_SHORT_LABEL.get(p.get("main_position", ""), p.get("main_position", "-"))
        sub_pos = POSITION_SHORT_LABEL.get(p.get("sub_position", ""), p.get("sub_position", "-"))
        if game.value == "lol":
            t_str = format_tier_with_custom_emoji(p.get("solo_tier") or "Unranked", "lol")
        else:
            t_str = format_tier_with_custom_emoji(p.get("competitive_tier") or "Unranked", "valorant")
        lines.append(f"`{idx:02d}.` <@{uid}> (`{riot_id}`) — {t_str} | 주:{main_pos} / 부:{sub_pos}")

    await interaction.response.send_message(
        "\n".join(lines),
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.command_tree.command(name="delete-profile", description="등록된 게임 프로필을 삭제합니다.")
@app_commands.describe(
    game="삭제할 게임 선택",
    target_user="(관리자 전용) 삭제할 대상 유저",
)
@app_commands.choices(game=GAME_CHOICES)
async def delete_profile(
    interaction: discord.Interaction,
    game: app_commands.Choice[str],
    target_user: discord.Member | None = None,
):
    lose_emoji = get_custom_emoji("ALose", "❌")
    user = target_user or interaction.user
    if user.id != interaction.user.id and not _is_admin(interaction):
        await interaction.response.send_message(
            f"{lose_emoji} 본인의 프로필만 삭제할 수 있습니다. (타 유저 삭제는 관리자 전용)",
            ephemeral=True,
        )
        return

    deleted = database.delete_user_profile(interaction.guild_id, user.id, game.value)
    if not deleted:
        await interaction.response.send_message(
            f"{lose_emoji} <@{user.id}>님의 **{game.name}** 프로필을 찾을 수 없습니다.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"🗑️ <@{user.id}>님의 **{game.name}** 프로필이 삭제되었습니다.",
        allowed_mentions=discord.AllowedMentions.none(),
    )


# =====================================================================
# 2. 내전(Match) 핵심 명령어 (match 이름으로 표준화)
# =====================================================================

@bot.command_tree.command(name="create-match", description="새로운 롤 또는 발로란트 내전 모집을 생성합니다.")
@app_commands.describe(game="내전을 진행할 종목을 선택하세요.")
@app_commands.choices(game=GAME_CHOICES)
async def create_match(interaction: discord.Interaction, game: app_commands.Choice[str]):
    lose_emoji = get_custom_emoji("ALose", "❌")
    if not interaction.guild_id or not interaction.channel:
        await interaction.response.send_message(
            f"{lose_emoji} 서버 채널에서만 사용할 수 있는 명령어입니다.",
            ephemeral=True,
        )
        return

    session = database.create_inhouse_session(
        guild_id=interaction.guild_id,
        game=game.value,
        organizer_user_id=interaction.user.id,
        channel_id=interaction.channel_id,
    )

    # 주최자가 이미 해당 게임에 프로필이 등록되어 있으면 자동 참가 처리
    database.add_inhouse_participant(
        guild_id=interaction.guild_id,
        session_id=session["session_id"],
        discord_user_id=interaction.user.id,
    )

    participants = database.get_inhouse_participants_with_profiles(
        interaction.guild_id, session["session_id"]
    )

    if game.value == "lol":
        content = format_lol_lobby_message(session, participants)
        view = LolRecruitmentView(session=session, participant_count=len(participants))
    else:
        content = format_val_lobby_message(session, participants)
        view = ValRecruitmentView(session=session, participant_count=len(participants))

    await interaction.response.send_message(
        content=content,
        view=view,
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    sent_msg = await interaction.original_response()

    database.save_inhouse_lobby_message(
        guild_id=interaction.guild_id,
        session_id=session["session_id"],
        channel_id=sent_msg.channel.id,
        message_id=sent_msg.id,
    )
    session["channel_id"] = sent_msg.channel.id
    session["message_id"] = sent_msg.id
    session["lobby_channel_id"] = sent_msg.channel.id
    session["lobby_message_id"] = sent_msg.id


@bot.command_tree.command(name="match-list", description="현재 서버에서 진행(모집) 중인 내전 목록을 확인합니다.")
@app_commands.describe(game="특정 게임만 조회하려면 선택하세요 (미선택 시 전체)")
@app_commands.choices(game=GAME_CHOICES)
async def match_list(
    interaction: discord.Interaction,
    game: app_commands.Choice[str] | None = None,
):
    sessions = database.get_active_inhouse_sessions(
        interaction.guild_id, game.value if game else None
    )
    if not sessions:
        await interaction.response.send_message(
            "📭 현재 열려 있는 내전 세션이 없습니다. `/create-match` 명령어로 내전을 열어보세요!",
            ephemeral=True,
        )
        return

    civilwar_emoji = get_custom_emoji("ACivilwar", "⚔️")
    lines = [f"{civilwar_emoji} **현재 진행 중인 내전 목록 ({len(sessions)}개)**", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for s in sessions:
        parts = database.get_inhouse_participants_with_profiles(s["guild_id"], s["session_id"])
        g_label = "LoL" if s["game"] == "lol" else "VALORANT"
        lines.append(
            f"• **[`{g_label}`] `match #{s['civilwar_number']}`** — "
            f"인원: `{len(parts)}/10명` | 주최자: <@{s['organizer_user_id']}>"
        )

    await interaction.response.send_message(
        "\n".join(lines),
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.command_tree.command(name="match-transfer", description="내전 주최자 권한을 다른 유저에게 양도합니다.")
@app_commands.describe(
    game="게임 종목 선택",
    match_number="내전 번호 (match #번호)",
    new_organizer="새 주최자로 지정할 유저",
)
@app_commands.choices(game=GAME_CHOICES)
async def match_transfer(
    interaction: discord.Interaction,
    game: app_commands.Choice[str],
    match_number: int,
    new_organizer: discord.Member,
):
    lose_emoji = get_custom_emoji("ALose", "❌")
    session = database.get_inhouse_session_by_number(interaction.guild_id, match_number, game.value)
    if not session:
        await interaction.response.send_message(
            f"{lose_emoji} 해당 번호(`match #{match_number}`)의 진행 중인 내전을 찾을 수 없습니다.",
            ephemeral=True,
        )
        return

    if session["organizer_user_id"] != interaction.user.id and not _is_admin(interaction):
        await interaction.response.send_message(
            f"{lose_emoji} 현재 주최자 또는 서버 관리자만 주최자 권한을 양도할 수 있습니다.",
            ephemeral=True,
        )
        return

    ok, msg, updated_session = database.transfer_inhouse_organizer(
        guild_id=interaction.guild_id,
        civilwar_number=match_number,
        game=game.value,
        new_organizer_user_id=new_organizer.id,
    )
    if not ok or not updated_session:
        await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
        return

    if game.value == "lol":
        await sync_lol_lobby_message(bot, updated_session, interaction.channel)
    else:
        await sync_val_lobby_message_if_exists(bot, updated_session, interaction.channel)

    await interaction.response.send_message(
        f"👑 **`match #{match_number}`**의 주최자가 <@{new_organizer.id}>님으로 변경되었습니다!"
    )


@bot.command_tree.command(name="end-match", description="진행 중인 내전을 종료합니다.")
@app_commands.describe(
    game="종료할 내전의 게임 종목",
    match_number="종료할 내전 번호 (match #번호)",
)
@app_commands.choices(game=GAME_CHOICES)
async def end_match(
    interaction: discord.Interaction,
    game: app_commands.Choice[str],
    match_number: int,
):
    lose_emoji = get_custom_emoji("ALose", "❌")
    session = database.get_inhouse_session_by_number(interaction.guild_id, match_number, game.value)
    if not session:
        await interaction.response.send_message(
            f"{lose_emoji} 해당 번호(`match #{match_number}`)의 내전을 찾을 수 없습니다.",
            ephemeral=True,
        )
        return

    is_admin = _is_admin(interaction)
    ok, msg, closed_session = database.close_inhouse_session(
        guild_id=interaction.guild_id,
        civilwar_number=match_number,
        game=game.value,
        requester_user_id=interaction.user.id,
        allow_adminoverride=is_admin,
    )
    if not ok or not closed_session:
        await interaction.response.send_message(f"{lose_emoji} {msg}", ephemeral=True)
        return

    if game.value == "lol":
        await mark_lol_lobby_closed(bot, closed_session, interaction.channel)
    else:
        await sync_val_lobby_message_if_exists(bot, closed_session, interaction.channel)

    await interaction.response.send_message(f"🛑 {msg}")


# =====================================================================
# 3. 내전 전적 확인 및 초기화 명령어
# =====================================================================

@bot.command_tree.command(name="match-stats", description="유저의 내전 누적 승패 및 승률 전적을 확인합니다.")
@app_commands.describe(target_user="조회할 유저 (미선택 시 본인 조회)")
async def match_stats(
    interaction: discord.Interaction,
    target_user: discord.Member | None = None,
):
    user = target_user or interaction.user
    stats = database.get_global_user_inhouse_stats(user.id)

    chart_emoji = get_custom_emoji("ACharting", "📊")
    win_emoji = get_custom_emoji("AWin", "🏆")

    lol_s = stats.get("lol", {"wins": 0, "losses": 0, "total": 0, "win_rate": 0.0})
    val_s = stats.get("valorant", {"wins": 0, "losses": 0, "total": 0, "win_rate": 0.0})
    tot_s = stats.get("overall", {"wins": 0, "losses": 0, "total": 0, "win_rate": 0.0})

    lines = [
        f"{chart_emoji} **<@{user.id}>님의 내전 전적 요약**",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{win_emoji} **통합 전적**: `{tot_s['total']}전 {tot_s['wins']}승 {tot_s['losses']}패` (승률 **{tot_s['win_rate']:.1f}%**)",
        f"• **LoL 내전**: `{lol_s['total']}전 {lol_s['wins']}승 {lol_s['losses']}패` (승률 **{lol_s['win_rate']:.1f}%**)",
        f"• **VALORANT 내전**: `{val_s['total']}전 {val_s['wins']}승 {val_s['losses']}패` (승률 **{val_s['win_rate']:.1f}%**)",
    ]
    await interaction.response.send_message(
        "\n".join(lines),
        allowed_mentions=discord.AllowedMentions.none(),
    )


# =====================================================================
# 4. 미니게임 명령어 등록 (/dice, /rps)
# =====================================================================

register_minigame_commands(bot)


# =====================================================================
# 봇 실행
# =====================================================================

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("❌ .env 파일에 DISCORD_TOKEN이 설정되어 있지 않습니다.")
    bot.run(DISCORD_TOKEN)
