import discord

from civilwarhelper import db as database
from civilwarhelper.config.positions import LOL_POS_SHORT_MAP, POSITION_SHORT_LABEL
from civilwarhelper.services.balance import _extract_player_tier_and_score
from civilwarhelper.ui.emojis import get_tier_emoji


async def send_profile_lines(interaction: discord.Interaction, lines: list[str]):
    # 2000자 제한 안 넘게 쪼개서 전송
    chunks: list[str] = []
    cur = ""

    for line in lines:
        cand = f"{cur}\n{line}" if cur else line
        if len(cand) > 1900:
            if cur:
                chunks.append(cur)
            cur = line
        else:
            cur = cand

    if cur:
        chunks.append(cur)
    if not chunks:
        chunks = ["등록된 멤버가 없습니다."]

    no_mentions = discord.AllowedMentions.none()
    await interaction.response.send_message(chunks[0], allowed_mentions=no_mentions)
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk, allowed_mentions=no_mentions)


async def get_display_nickname(guild: discord.Guild, profile: dict):
    member = guild.get_member(profile["discord_user_id"])
    return member.display_name if member is not None else profile.get("discord_nickname", "Unknown member")


def _format_short_position(pos_text: str | None, game: str) -> str:
    if not pos_text or pos_text.strip().upper() in ("NOT RETRIEVED YET", "NONE", "UNKNOWN", ""):
        return "미정"
    cleaned = pos_text.strip()
    if game == "lol":
        return LOL_POS_SHORT_MAP.get(cleaned.upper(), cleaned.upper())
    return POSITION_SHORT_LABEL.get(cleaned, cleaned.upper())


def format_single_member_profile_detail(profile: dict, display_name: str, game: str) -> str:
    safe_name = discord.utils.escape_markdown(display_name)
    riot_name = profile.get("riot_game_name") or "Unknown"
    riot_tag = profile.get("riot_tagline") or "Unknown"
    location = profile.get("server_location") or "Korea"

    custom_raw = (profile.get("custom_tier") or "").strip()
    custom_str = (
        _format_tier_with_custom_emoji(custom_raw, game)
        if custom_raw
        else "미설정 *(실제 티어 적용)*"
    )

    main_short = _format_short_position(profile.get("main_position"), game)
    sub_raw = (profile.get("sub_position") or "").strip()
    sub_short = _format_short_position(sub_raw, game) if sub_raw and sub_raw != "선택안함" else "선택안함"

    if game == "lol":
        solo_str = _format_tier_with_custom_emoji(profile.get("solo_tier"), "lol")
        flex_str = _format_tier_with_custom_emoji(profile.get("flex_tier"), "lol")
        tier_line = f"• **실제 티어**: Solo {solo_str} / Flex {flex_str}"
    else:
        comp_str = _format_tier_with_custom_emoji(profile.get("competitive_tier"), "valorant")
        tier_line = f"• **실제 티어**: {comp_str}"

    return (
        f"👤 **{safe_name}** — `{riot_name} #{riot_tag}` ({location})\n"
        f"• **체감 티어**: {custom_str}\n"
        f"{tier_line}\n"
        f"• **포지션**: 주 **{main_short}** / 부 **{sub_short}**"
    )


def format_compact_member_profile_line(profile: dict, display_name: str, game: str) -> str:
    safe_name = discord.utils.escape_markdown(display_name)
    riot_name = profile.get("riot_game_name") or "Unknown"
    riot_tag = profile.get("riot_tagline") or "Unknown"
    location = profile.get("server_location") or "Korea"

    custom_raw = (profile.get("custom_tier") or "").strip()
    custom_str = _format_tier_with_custom_emoji(custom_raw, game) if custom_raw else "미설정"

    main_short = _format_short_position(profile.get("main_position"), game)
    sub_raw = (profile.get("sub_position") or "").strip()
    pos_part = (
        f"{main_short}/{_format_short_position(sub_raw, game)}"
        if sub_raw and sub_raw != "선택안함"
        else main_short
    )

    if game == "lol":
        solo_str = _format_tier_with_custom_emoji(profile.get("solo_tier"), "lol")
        flex_str = _format_tier_with_custom_emoji(profile.get("flex_tier"), "lol")
        return (
            f"• **{safe_name}** - {riot_name} #{riot_tag} / {location} "
            f"(체감: {custom_str} / Solo: {solo_str} / Flex: {flex_str} / 라인: **{pos_part}**)"
        )

    comp_str = _format_tier_with_custom_emoji(profile.get("competitive_tier"), "valorant")
    return (
        f"• **{safe_name}** - {riot_name} #{riot_tag} / {location} "
        f"(체감: {custom_str} / Tier: {comp_str} / 포지션: **{pos_part}**)"
    )


def _format_tier_with_custom_emoji(tier_text: str | None, game: str) -> str:
    if not tier_text or tier_text.strip().upper() in ("UNRANKED", "NONE", "UNKNOWN", "NOT RETRIEVED YET"):
        return f"{get_tier_emoji(game, 'UNRANKED')} Unranked".strip()

    cleaned = tier_text.strip()
    emoji = get_tier_emoji(game, cleaned.split()[0].upper())
    return f"{emoji} {cleaned}".strip()


def format_user_profile_card(profile: dict, can_edit: bool, edit_reason: str) -> str:
    game = profile["game"]
    game_label = "League of Legends" if game == "lol" else "VALORANT"
    nickname = profile.get("discord_nickname") or "Unknown"
    riot_name = profile.get("riot_game_name") or "Unknown"
    riot_tag = profile.get("riot_tagline") or "Unknown"
    location = profile.get("server_location") or "Korea"

    custom_tier = (profile.get("custom_tier") or "").strip()
    main_pos = profile.get("main_position") or "미정"
    sub_pos = profile.get("sub_position") or "선택안함"

    effective_tier_display, effective_score = _extract_player_tier_and_score(profile, game)

    lines = [
        f"👤 **{nickname}님의 {game_label} 프로필**",
        f"• **Riot ID**: {riot_name} #{riot_tag} ({location})",
    ]

    if game == "lol":
        solo_str = _format_tier_with_custom_emoji(profile.get("solo_tier"), "lol")
        flex_str = _format_tier_with_custom_emoji(profile.get("flex_tier"), "lol")
        lines.append(f"• **실제 랭크 티어**: 솔로 {solo_str} / 자유 {flex_str}")
    else:
        comp_str = _format_tier_with_custom_emoji(profile.get("competitive_tier"), "valorant")
        lines.append(f"• **실제 경쟁전 티어**: {comp_str}")

    if custom_tier:
        custom_str = _format_tier_with_custom_emoji(custom_tier, game)
        lines.append(f"• **체감 티어 (위장/보정)**: {custom_str} *(내전 밸런스 최우선 적용 중)*")
    else:
        lines.append("• **체감 티어 (위장/보정)**: 설정 안 됨 *(실제 최고 티어 적용 중)*")

    lines.append(f"• **내전 적용 기준**: {effective_tier_display} (밸런스 점수: {effective_score:.1f}점)")
    lines.append(f"• **선호 포지션**: 주 포지션 **{main_pos}** / 부 포지션 **{sub_pos}**")

    uid = profile.get("discord_user_id", profile.get("user_id"))
    stats = (
        database.get_global_user_inhouse_stats(int(uid), game)
        if uid is not None
        else {
            "total_wins": 0, "total_losses": 0,
            "upper_wins": 0, "upper_losses": 0,
            "even_wins": 0, "even_losses": 0,
            "lower_wins": 0, "lower_losses": 0,
        }
    )

    def _fmt_wl(w: int, l: int) -> str:
        total = w + l
        if total == 0:
            return "0전 0승 0패 (0.0%)"
        return f"{total}전 {w}승 {l}패 ({(w / total) * 100.0:.1f}%)"

    lines.extend([
        "",
        "📊 **내전 통산 전적 (모든 서버 누적)**",
        f"• **전체 승률**: {_fmt_wl(stats['total_wins'], stats['total_losses'])}",
        f"  ├ 🔼 **윗밸 상대**: {_fmt_wl(stats['upper_wins'], stats['upper_losses'])}",
        f"  ├ ⚖️ **황밸 상대**: {_fmt_wl(stats['even_wins'], stats['even_losses'])}",
        f"  └ 🔽 **아랫밸 상대**: {_fmt_wl(stats['lower_wins'], stats['lower_losses'])}",
        "",
    ])

    if can_edit:
        lines.append(f"🛠️ **수정 권한 활성화됨** ({edit_reason}) — 아래 드롭다운에서 체감 티어 및 선호 포지션을 변경할 수 있습니다.")
    else:
        lines.append("🔒 *조회 전용 화면입니다. (본인 또는 같은 내전 참가자/주최자만 수정할 수 있습니다.)*")

    return "\n".join(lines)
