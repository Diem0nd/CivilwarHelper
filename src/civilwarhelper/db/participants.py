from contextlib import closing
from datetime import datetime, timezone

from civilwarhelper.db.connection import get_connection
from civilwarhelper.db.sessions import get_inhouse_session_by_id


def add_inhouse_participant(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
) -> tuple[bool, str]:
    with closing(get_connection()) as conn:
        try:
            # 동시에 마지막 자리 누르는 경우 막으려고 트랜잭션 잠금
            conn.execute("BEGIN IMMEDIATE")
            session = conn.execute(
                "SELECT * FROM inhouse_sessions WHERE guild_id = ? AND session_id = ? AND status = 'open'",
                (guild_id, session_id),
            ).fetchone()

            if session is None:
                return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

            game = session["game"]
            profile = conn.execute(
                "SELECT * FROM profiles WHERE guild_id = ? AND discord_user_id = ? AND game = ?",
                (guild_id, discord_user_id, game),
            ).fetchone()

            if profile is None:
                game_label = "League of Legends" if game == "lol" else "VALORANT"
                return (
                    False,
                    f"이 유저는 아직 {game_label} 프로필이 등록되지 않았습니다. 먼저 `/register`로 등록해 주세요.",
                )

            existing = conn.execute(
                "SELECT 1 FROM inhouse_participants WHERE session_id = ? AND discord_user_id = ?",
                (session_id, discord_user_id),
            ).fetchone()
            if existing is not None:
                return False, "이미 해당 내전에 참가 중인 유저입니다."

            cnt = conn.execute(
                "SELECT COUNT(*) AS cnt FROM inhouse_participants WHERE session_id = ?",
                (session_id,),
            ).fetchone()["cnt"]
            if cnt >= 10:
                return False, "이미 참가자가 10명 모두 모집되었습니다."

            now = datetime.now(timezone.utc).isoformat()
            keys = profile.keys()
            sub_pos = profile["sub_position"] if "sub_position" in keys else None
            custom_tier = profile["custom_tier"] if "custom_tier" in keys else None

            conn.execute(
                """
                INSERT INTO inhouse_participants (
                    session_id, guild_id, discord_user_id,
                    discord_nickname, riot_game_name, riot_tagline, server_location,
                    solo_tier, flex_tier, competitive_tier, custom_tier,
                    main_position, preferred_position, sub_position, joined_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, guild_id, discord_user_id,
                    profile["discord_nickname"], profile["riot_game_name"],
                    profile["riot_tagline"], profile["server_location"],
                    profile["solo_tier"], profile["flex_tier"],
                    profile["competitive_tier"], custom_tier,
                    profile["main_position"], profile["main_position"],
                    sub_pos, now,
                ),
            )
            conn.commit()
            return True, "참가자가 추가되었습니다."
        except Exception:
            conn.rollback()
            raise


def remove_inhouse_participant(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
) -> tuple[bool, str]:
    with closing(get_connection()) as conn:
        session = conn.execute(
            "SELECT 1 FROM inhouse_sessions WHERE guild_id = ? AND session_id = ? AND status = 'open'",
            (guild_id, session_id),
        ).fetchone()
        if session is None:
            return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

        cur = conn.execute(
            "DELETE FROM inhouse_participants WHERE session_id = ? AND discord_user_id = ?",
            (session_id, discord_user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return False, "해당 유저는 이 내전의 참가자 목록에 없습니다."
        return True, "참가자가 목록에서 제외되었습니다."


def get_inhouse_participants_with_profiles(guild_id: int, session_id: int) -> list[dict]:
    with closing(get_connection()) as conn:
        session = conn.execute(
            "SELECT * FROM inhouse_sessions WHERE guild_id = ? AND session_id = ?",
            (guild_id, session_id),
        ).fetchone()
        if session is None:
            return []

        rows = conn.execute(
            """
            SELECT
                p.session_id,
                p.discord_user_id,
                COALESCE(p.preferred_position, pr.main_position) AS preferred_position,
                COALESCE(p.sub_position, pr.sub_position) AS sub_position,
                p.assigned_team,
                p.assigned_position,
                p.joined_at,
                COALESCE(pr.discord_nickname, p.discord_nickname) AS discord_nickname,
                COALESCE(pr.riot_game_name, p.riot_game_name) AS riot_game_name,
                COALESCE(pr.riot_tagline, p.riot_tagline) AS riot_tagline,
                COALESCE(pr.server_location, p.server_location) AS server_location,
                COALESCE(pr.solo_tier, p.solo_tier) AS solo_tier,
                COALESCE(pr.flex_tier, p.flex_tier) AS flex_tier,
                COALESCE(pr.competitive_tier, p.competitive_tier) AS competitive_tier,
                COALESCE(pr.custom_tier, p.custom_tier) AS custom_tier,
                COALESCE(pr.main_position, p.main_position) AS main_position
            FROM inhouse_participants p
            LEFT JOIN profiles pr
                ON pr.guild_id = ?
               AND pr.discord_user_id = p.discord_user_id
               AND pr.game = ?
            WHERE p.session_id = ?
            ORDER BY p.joined_at ASC
            """,
            (guild_id, session["game"], session_id),
        ).fetchall()
        return [dict(r) for r in rows]


get_inhouse_participants = get_inhouse_participants_with_profiles


def update_inhouse_participant_position(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    preferred_position: str,
) -> tuple[bool, str]:
    with closing(get_connection()) as conn:
        session = conn.execute(
            "SELECT 1 FROM inhouse_sessions WHERE guild_id = ? AND session_id = ? AND status = 'open'",
            (guild_id, session_id),
        ).fetchone()
        if session is None:
            return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

        cur = conn.execute(
            "UPDATE inhouse_participants SET preferred_position = ? WHERE session_id = ? AND discord_user_id = ?",
            (preferred_position, session_id, discord_user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return False, "해당 유저는 이 내전의 참가자 목록에 없습니다."
        return True, f"선호 포지션이 **{preferred_position}**(으)로 설정되었습니다."


def update_inhouse_participant_sub_position(
    guild_id: int,
    session_id: int,
    discord_user_id: int,
    sub_position: str | None,
) -> tuple[bool, str]:
    with closing(get_connection()) as conn:
        session = conn.execute(
            "SELECT 1 FROM inhouse_sessions WHERE guild_id = ? AND session_id = ? AND status = 'open'",
            (guild_id, session_id),
        ).fetchone()
        if session is None:
            return False, "해당 내전을 찾을 수 없거나 이미 종료되었습니다."

        cur = conn.execute(
            "UPDATE inhouse_participants SET sub_position = ? WHERE session_id = ? AND discord_user_id = ?",
            (sub_position, session_id, discord_user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return False, "먼저 [내전 참가] 버튼을 눌러 내전에 참가해 주세요."

        display_sub = sub_position if sub_position else "선택안함"
        return True, f"부 포지션이 **{display_sub}**(으)로 설정되었습니다."


def get_unjoined_registered_profiles(guild_id: int, session_id: int, game: str) -> list[dict]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT p.discord_user_id, p.discord_nickname,
                   p.riot_game_name, p.riot_tagline,
                   p.solo_tier, p.flex_tier, p.competitive_tier, p.main_position
            FROM profiles p
            WHERE p.guild_id = ?
              AND p.game = ?
              AND p.discord_user_id NOT IN (
                  SELECT discord_user_id FROM inhouse_participants WHERE session_id = ?
              )
            ORDER BY p.discord_nickname ASC
            """,
            (guild_id, game, session_id),
        ).fetchall()
        return [dict(r) for r in rows]


def auto_fill_inhouse_to_ten(guild_id: int, session_id: int) -> tuple[bool, str]:
    session = get_inhouse_session_by_id(guild_id, session_id)
    if not session:
        return False, "존재하지 않는 내전입니다."

    game = session["game"]
    participants = get_inhouse_participants_with_profiles(guild_id, session_id)
    current_count = len(participants)
    if current_count >= 10:
        return False, "이미 10명이 모두 모집되었습니다."

    added_real = 0
    added_bots = 0

    # 미참가 서버원 먼저 넣고 부족하면 더미 봇으로 채움
    for prof in get_unjoined_registered_profiles(guild_id, session_id, game):
        if current_count >= 10:
            break
        ok, _ = add_inhouse_participant(guild_id, session_id, prof["discord_user_id"])
        if ok:
            current_count += 1
            added_real += 1

    pos_list = (
        ["Top", "Jungle", "Mid", "AD carry", "Support"]
        if game == "lol"
        else ["Duelist", "Initiator", "Controller", "Sentinel", "Flex"]
    )
    sample_tiers = (
        [
            "IRON I", "BRONZE II", "SILVER I", "GOLD III", "PLATINUM II",
            "EMERALD IV", "EMERALD I", "DIAMOND III", "MASTER", "GRANDMASTER",
        ]
        if game == "lol"
        else [
            "IRON 1", "BRONZE 2", "SILVER 1", "GOLD 3", "PLATINUM 2",
            "DIAMOND 1", "DIAMOND 3", "ASCENDANT 2", "IMMORTAL 1", "RADIANT",
        ]
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    with closing(get_connection()) as conn:
        bot_idx = 1
        while current_count < 10 and bot_idx <= 20:
            fake_uid = 900000000000000000 + bot_idx
            pos = pos_list[(bot_idx - 1) % 5]
            tier = sample_tiers[(bot_idx - 1) % len(sample_tiers)]

            conn.execute(
                """
                INSERT OR IGNORE INTO profiles (
                    guild_id, discord_user_id, game,
                    discord_nickname, riot_game_name, riot_tagline, server_location,
                    solo_tier, flex_tier, competitive_tier, main_position,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'Korea', ?, 'UNRANKED', ?, ?, ?, ?)
                """,
                (
                    guild_id, fake_uid, game,
                    f"테스트봇{bot_idx}", f"TestBot{bot_idx}", f"KR{bot_idx}",
                    tier, tier, pos, now_iso, now_iso,
                ),
            )
            conn.commit()

            ok, _ = add_inhouse_participant(guild_id, session_id, fake_uid)
            if ok:
                current_count += 1
                added_bots += 1
            bot_idx += 1

    return True, f"자동 충원 완료! (등록 서버원 {added_real}명 + 가상 테스트봇 {added_bots}명 추가됨)"
