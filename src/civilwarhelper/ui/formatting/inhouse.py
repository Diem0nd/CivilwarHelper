from civilwarhelper import db as database
from civilwarhelper.ui.formatting.profile import _format_short_position, _format_tier_with_custom_emoji


def format_inhouse_session_detail(
    session: dict,
    participants: list[dict],
    is_closed: bool = False,
    closed_reason: str = "모집 종료",
) -> str:
    civilwar_num = session["civilwar_number"]
    game = session["game"]
    game_label = "League of Legends" if game == "lol" else "VALORANT"
    organizer_mention = f"<@{session['organizer_user_id']}>"
    count = len(participants)

    if is_closed or session.get("status") != "open":
        status_header = f"🛑 **[{closed_reason}] civilwar #{civilwar_num} ({game_label})**"
        status_line = f"상태 : **{closed_reason}**"
    else:
        status_badge = "🟢 모집 중" if count < 10 else "🌕 모집 완료 (시작 대기 중)"
        status_header = f"📢 **현재 civilwar #{civilwar_num} ({game_label}) 참가자**"
        status_line = f"상태 : {status_badge}"

    lines = [
        status_header,
        f"{status_line} | 주최자 : {organizer_mention} | 참가자 : **{count}/10**",
    ]

    team_groups = database.get_session_team_groups(session["guild_id"], session["session_id"])
    if team_groups:
        group_strs = [
            f"`그룹{i}`(" + ", ".join(f"<@{u}>" for u in g) + ")"
            for i, g in enumerate(team_groups, 1)
        ]
        lines.append("🤝 **같은 팀 예약** : " + " / ".join(group_strs))

    if participants:
        lines.append("")
        for idx, p in enumerate(participants, start=1):
            user_mention = f"<@{p['discord_user_id']}>"
            riot_name = p.get("riot_game_name") or "Unknown"
            riot_tag = p.get("riot_tagline") or "Unknown"

            main_pos = _format_short_position(p.get("preferred_position") or p.get("main_position"), game)
            sub_raw = (p.get("sub_position") or "").strip()
            pos_display = (
                f"{main_pos}/{_format_short_position(sub_raw, game)}"
                if sub_raw and sub_raw != "선택안함"
                else main_pos
            )

            custom_raw = (p.get("custom_tier") or "").strip()
            custom_prefix = (
                f"체감:{_format_tier_with_custom_emoji(custom_raw, game)} | "
                if custom_raw
                else ""
            )

            if game == "lol":
                solo_tier = _format_tier_with_custom_emoji(p.get("solo_tier"), "lol")
                flex_tier = _format_tier_with_custom_emoji(p.get("flex_tier"), "lol")
                lines.append(
                    f"{idx}. {user_mention} `{riot_name}#{riot_tag}` "
                    f"({custom_prefix}솔로:{solo_tier} / 자유:{flex_tier} | **{pos_display}**)"
                )
            else:
                comp_tier = _format_tier_with_custom_emoji(p.get("competitive_tier"), "valorant")
                lines.append(
                    f"{idx}. {user_mention} `{riot_name}#{riot_tag}` "
                    f"({custom_prefix}티어:{comp_tier} | **{pos_display}**)"
                )
    elif not is_closed:
        lines.append("\n*아직 참가자가 없습니다. 아래 [🎮 내전 참가] 버튼을 눌러 참여하세요!*")

    result = "\n".join(lines)
    # 디스코드 메시지 2000자 제한 방어
    if len(result) > 1990:
        result = result[:1985] + "\n..."
    return result
