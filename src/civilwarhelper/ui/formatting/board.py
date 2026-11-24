from civilwarhelper import db as database
from civilwarhelper.config.games import draft_rule_name
from civilwarhelper.config.positions import LOL_STANDARD_POSITIONS, POSITION_SHORT_LABEL, VAL_STANDARD_POSITIONS
from civilwarhelper.services.balance import _extract_player_tier_and_score, _get_comparison_symbol
from civilwarhelper.services.team_names import SESSION_CUSTOM_TEAM_NAMES
from civilwarhelper.ui.emojis import get_custom_emoji, get_position_emoji, get_tier_emoji
from civilwarhelper.services.val_map import get_or_assign_valorant_map


def format_fearless_section(
    guild_id: int,
    session_id: int,
    game: str = "lol",
    is_finished: bool = False,
) -> str:
    state = database.get_fearless_state(guild_id, session_id)
    current_set = state["current_set"]
    results_data: dict = state.get("results", {})

    red_wins = sum(1 for v in results_data.values() if v == "RED")
    blue_wins = sum(1 for v in results_data.values() if v == "BLUE")

    playing_emoji = get_custom_emoji("APlaying", "🔥")
    win_emoji = get_custom_emoji("AWin", "WIN")
    fearless_emoji = get_custom_emoji("AFearless", "⛔")

    if is_finished:
        done = [int(k) for k in results_data if str(k).isdigit()]
        final_cnt = max(done) if done else 0
        status_line = f"{playing_emoji} **진행 결과 : {final_cnt}세트 (SCORE {red_wins} : {blue_wins})**"
    else:
        status_line = f"{playing_emoji} **현재 진행도 : {current_set}세트 (SCORE {red_wins} : {blue_wins})**"

    lines = ["", status_line]

    for s_num in sorted(results_data.keys(), key=int):
        sq = "🟥" if results_data[s_num] == "RED" else "🟦"
        lines.append(f"└ {s_num}세트 : {sq} {win_emoji}")

    rule = draft_rule_name(game)
    lines.append("")
    if not state["enabled"]:
        lines.append(f"{fearless_emoji} **{rule} : OFF**")
        return "\n".join(lines)

    lines.append(f"{fearless_emoji} **{rule} : ON**")
    sets_data: dict = state["sets"]

    for set_num in sorted(sets_data.keys(), key=int):
        rec = sets_data[set_num]
        if game != "lol":
            maps_str = ", ".join(rec.get("maps", [])) or "없음"
            line = f"{set_num}세트 맵 밴 : 🗺️ - ({maps_str})"
            if rec.get("extra"):
                line += f" / 🚫 - ({', '.join(rec['extra'])})"
            lines.append(line)
            continue

        red_str = ", ".join(rec.get("red", [])) or "없음"
        blue_str = ", ".join(rec.get("blue", [])) or "없음"
        line = f"{set_num}세트 피어리스 : 🟥 - ({red_str}) / 🟦 - ({blue_str})"
        if rec.get("extra"):
            line += f" / 🚫 - ({', '.join(rec['extra'])})"
        lines.append(line)

    return "\n".join(lines)


def format_matchmaking_board(
    session: dict,
    participants: list[dict],
    balance_settings: dict[str, str] | None = None,
    is_finished: bool = False,
) -> str:
    game = session.get("game", "lol")

    guild_id = session.get("guild_id", 0)
    session_id = session["session_id"]
    custom_names = SESSION_CUSTOM_TEAM_NAMES.get((guild_id, session_id), {})
    red_name = custom_names.get("RED") or "RED 팀"
    blue_name = custom_names.get("BLUE") or "BLUE 팀"

    playing_emoji = get_custom_emoji("APlaying", "⚔️")
    lines = [
        f"{playing_emoji} **civilwar #{session_id} 팀 편성 결과** (기준: 왼쪽 = 🟥 **{red_name}** / 오른쪽 = 🟦 **{blue_name}**)",
        f"주최자 : <@{session['organizer_user_id']}>",
    ]
    
    if game != "lol":
        current_map = get_or_assign_valorant_map(guild_id, session_id, reroll=False)
        lines.append(f"🗺️ **이번 세트 배정 맵** : 🎯 **{current_map}**")
    lines.append("")


    total_red = 0.0
    total_blue = 0.0

    if game == "lol":
        positions = LOL_STANDARD_POSITIONS
        red_by_pos: dict[str, dict] = {}
        blue_by_pos: dict[str, dict] = {}

        for p in participants:
            side = str(p.get("team_side") or p.get("assigned_team") or "").upper()
            pos = str(p.get("assigned_position") or p.get("primary_position") or "")
            if side == "RED":
                red_by_pos[pos] = p
            elif side == "BLUE":
                blue_by_pos[pos] = p

        matchup_rows = [
            (POSITION_SHORT_LABEL.get(pos, pos.upper()), red_by_pos.get(pos), blue_by_pos.get(pos))
            for pos in positions
        ]
    else:
        # 발로란트 내전: 각 팀 인원을 티어 점수 내림차순으로 정렬하여 [1] ~ [5]로 표시
        red_list = [
            p for p in participants
            if str(p.get("team_side") or p.get("assigned_team") or "").upper() == "RED"
        ]
        blue_list = [
            p for p in participants
            if str(p.get("team_side") or p.get("assigned_team") or "").upper() == "BLUE"
        ]
        red_list.sort(key=lambda p: _extract_player_tier_and_score(p, game)[1], reverse=True)
        blue_list.sort(key=lambda p: _extract_player_tier_and_score(p, game)[1], reverse=True)

        matchup_rows = []
        for idx in range(5):
            r_p = red_list[idx] if idx < len(red_list) else None
            b_p = blue_list[idx] if idx < len(blue_list) else None
            matchup_rows.append((str(idx + 1), r_p, b_p))

    for idx, (short_pos, red_p, blue_p) in enumerate(matchup_rows):
        red_tier_str, red_score = _extract_player_tier_and_score(red_p, game)
        blue_tier_str, blue_score = _extract_player_tier_and_score(blue_p, game)

        total_red += red_score
        total_blue += blue_score

        lane_sym = _get_comparison_symbol(red_score, blue_score, strong_threshold=2.0)
        red_mention = f"<@{red_p['discord_user_id']}>" if red_p else "미배정"
        blue_mention = f"<@{blue_p['discord_user_id']}>" if blue_p else "미배정"

        pos_emoji = get_position_emoji(game, short_pos) if game == "lol" else ""
        pos_header = f"{pos_emoji} **[{short_pos}]**" if pos_emoji else f"**[{short_pos}]**"
        lines.append(f"{pos_header} {red_tier_str} **{lane_sym}** {blue_tier_str}")
        lines.append(f"{red_mention} vs {blue_mention}")

        if idx < len(matchup_rows) - 1:
            lines.append("")

    team_sym = _get_comparison_symbol(total_red, total_blue, strong_threshold=4.0)
    lines.extend([
        "",
        get_custom_emoji("ACharting", "📊")
        + f" **팀 밸런스 점수 합계** - 🟥 {red_name} ({total_red:.1f}) **{team_sym}** 🟦 {blue_name} ({total_blue:.1f})",
        format_fearless_section(guild_id, session_id, game=game, is_finished=is_finished),
    ])

    return "\n".join(lines)
