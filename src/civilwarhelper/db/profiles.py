from contextlib import closing
from datetime import datetime, timezone

from civilwarhelper.db.connection import get_connection


def save_profile(
    guild_id: int,
    discord_user_id: int,
    game: str,
    discord_nickname: str,
    riot_game_name: str,
    riot_tagline: str,
    server_location: str,
):
    with closing(get_connection()) as conn:
        try:
            now = datetime.now(timezone.utc).isoformat()
            existing = conn.execute(
                """
                SELECT riot_game_name, riot_tagline, server_location
                FROM profiles
                WHERE guild_id = ? AND discord_user_id = ? AND game = ?
                """,
                (guild_id, discord_user_id, game),
            ).fetchone()

            same_account = (
                existing is not None
                and existing["riot_game_name"] == riot_game_name
                and existing["riot_tagline"] == riot_tagline
                and existing["server_location"] == server_location
            )

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO profiles (
                        guild_id, discord_user_id, game,
                        discord_nickname, riot_game_name, riot_tagline, server_location,
                        puuid, solo_tier, flex_tier, competitive_tier, main_position,
                        created_at, updated_at, last_api_sync
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, NULL)
                    """,
                    (
                        guild_id, discord_user_id, game,
                        discord_nickname, riot_game_name, riot_tagline, server_location,
                        now, now,
                    ),
                )
                was_updated = False
            elif same_account:
                conn.execute(
                    """
                    UPDATE profiles
                    SET discord_nickname = ?, updated_at = ?
                    WHERE guild_id = ? AND discord_user_id = ? AND game = ?
                    """,
                    (discord_nickname, now, guild_id, discord_user_id, game),
                )
                was_updated = True
            else:
                conn.execute(
                    """
                    UPDATE profiles
                    SET discord_nickname = ?,
                        riot_game_name = ?,
                        riot_tagline = ?,
                        server_location = ?,
                        puuid = NULL,
                        solo_tier = NULL,
                        flex_tier = NULL,
                        competitive_tier = NULL,
                        main_position = NULL,
                        updated_at = ?,
                        last_api_sync = NULL
                    WHERE guild_id = ? AND discord_user_id = ? AND game = ?
                    """,
                    (
                        discord_nickname, riot_game_name, riot_tagline, server_location,
                        now, guild_id, discord_user_id, game,
                    ),
                )
                was_updated = True

            conn.commit()
            return was_updated
        except Exception:
            conn.rollback()
            raise


def get_profiles(guild_id: int, game: str):
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT
                guild_id, discord_user_id, game,
                discord_nickname, riot_game_name, riot_tagline, server_location,
                puuid, solo_tier, flex_tier, competitive_tier, custom_tier,
                main_position, sub_position, created_at, updated_at, last_api_sync
            FROM profiles
            WHERE guild_id = ? AND game = ?
            ORDER BY discord_nickname COLLATE NOCASE ASC,
                     riot_game_name COLLATE NOCASE ASC,
                     discord_user_id ASC
            """,
            (guild_id, game),
        ).fetchall()
        return [dict(r) for r in rows]


def update_profile_api_data(
    guild_id: int,
    discord_user_id: int,
    game: str,
    puuid: str | None = None,
    solo_tier: str | None = None,
    flex_tier: str | None = None,
    competitive_tier: str | None = None,
    main_position: str | None = None,
):
    with closing(get_connection()) as conn:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE profiles
            SET puuid = ?, solo_tier = ?, flex_tier = ?,
                competitive_tier = ?, main_position = ?,
                last_api_sync = ?, updated_at = ?
            WHERE guild_id = ? AND discord_user_id = ? AND game = ?
            """,
            (
                puuid, solo_tier, flex_tier, competitive_tier, main_position,
                now, now, guild_id, discord_user_id, game,
            ),
        )
        conn.commit()


def delete_user_profile(
    guild_id: int,
    discord_user_id: int,
    game: str | None = None,
) -> int:
    with closing(get_connection()) as conn:
        if game is None or game == "all":
            cur = conn.execute(
                "DELETE FROM profiles WHERE guild_id = ? AND discord_user_id = ?",
                (guild_id, discord_user_id),
            )
        else:
            cur = conn.execute(
                "DELETE FROM profiles WHERE guild_id = ? AND discord_user_id = ? AND game = ?",
                (guild_id, discord_user_id, game),
            )
        conn.commit()
        return cur.rowcount


def get_user_profile(guild_id: int, discord_user_id: int, game: str) -> dict | None:
    with closing(get_connection()) as conn:
        row = conn.execute(
            """
            SELECT
                guild_id, discord_user_id, game,
                discord_nickname, riot_game_name, riot_tagline, server_location,
                puuid, solo_tier, flex_tier, competitive_tier, custom_tier,
                main_position, sub_position, created_at, updated_at, last_api_sync
            FROM profiles
            WHERE guild_id = ? AND discord_user_id = ? AND game = ?
            """,
            (guild_id, discord_user_id, game),
        ).fetchone()
        return dict(row) if row is not None else None


def can_user_edit_profile(
    guild_id: int,
    actor_user_id: int,
    target_user_id: int,
    game: str,
) -> tuple[bool, str]:
    # 본인이거나 같은 내전에 참가 중(또는 주최자)이면 수정 허용
    if actor_user_id == target_user_id:
        return True, "본인 프로필"

    with closing(get_connection()) as conn:
        row = conn.execute(
            """
            SELECT s.session_id, s.civilwar_number
            FROM inhouse_sessions s
            INNER JOIN inhouse_participants p_target
                ON s.session_id = p_target.session_id
            LEFT JOIN inhouse_participants p_actor
                ON s.session_id = p_actor.session_id
               AND p_actor.discord_user_id = ?
            WHERE s.guild_id = ?
              AND s.game = ?
              AND s.status NOT IN ('closed', 'ended', 'cancelled')
              AND p_target.discord_user_id = ?
              AND (p_actor.discord_user_id IS NOT NULL OR s.organizer_user_id = ?)
            ORDER BY s.session_id DESC
            LIMIT 1
            """,
            (actor_user_id, guild_id, game, target_user_id, actor_user_id),
        ).fetchone()

        if row is not None:
            return True, f"civilwar #{row['civilwar_number']} 내전 참가자 권한"

        return (
            False,
            "타인의 프로필은 조회만 가능합니다. (단, 같은 내전에 참가 중인 인원끼리는 서로의 체감 티어/프로필을 수정할 수 있습니다.)",
        )


def update_user_profile_custom_settings(
    guild_id: int,
    discord_user_id: int,
    game: str,
    *,
    custom_tier: str | None = ...,
    main_position: str | None = ...,
    sub_position: str | None = ...,
) -> dict | None:
    with closing(get_connection()) as conn:
        try:
            now = datetime.now(timezone.utc).isoformat()
            updates = ["updated_at = ?"]
            params: list = [now]

            if custom_tier is not ...:
                updates.append("custom_tier = ?")
                params.append(custom_tier)
            if main_position is not ...:
                updates.append("main_position = ?")
                params.append(main_position)
            if sub_position is not ...:
                updates.append("sub_position = ?")
                params.append(sub_position)

            params.extend([guild_id, discord_user_id, game])
            conn.execute(
                f"UPDATE profiles SET {', '.join(updates)} WHERE guild_id = ? AND discord_user_id = ? AND game = ?",
                tuple(params),
            )

            # 참가자 테이블에도 반영
            part_updates = []
            part_params: list = []

            if custom_tier is not ...:
                part_updates.append("custom_tier = ?")
                part_params.append(custom_tier)
            if main_position is not ...:
                part_updates.extend(["main_position = ?", "preferred_position = ?"])
                part_params.extend([main_position, main_position])
            if sub_position is not ...:
                part_updates.append("sub_position = ?")
                part_params.append(sub_position)

            if part_updates:
                conn.execute(
                    f"""
                    UPDATE inhouse_participants
                    SET {', '.join(part_updates)}
                    WHERE guild_id = ?
                      AND discord_user_id = ?
                      AND session_id IN (
                          SELECT session_id FROM inhouse_sessions
                          WHERE guild_id = ? AND game = ?
                            AND status IN ('closed', 'ended', 'cancelled')
                      )
                    """,
                    (*part_params, guild_id, discord_user_id, guild_id, game),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return get_user_profile(guild_id, discord_user_id, game)
