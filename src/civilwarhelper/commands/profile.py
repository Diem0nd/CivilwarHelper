import asyncio
import logging

import aiohttp
import discord
from discord import app_commands

from civilwarhelper import db as database
from civilwarhelper.riot import client as riot_api
from civilwarhelper.riot import valorant as riot_valorant
from civilwarhelper.ui.formatting.profile import format_user_profile_card, get_display_nickname
from civilwarhelper.ui.views.profile_directory import ProfileDirectoryView
from civilwarhelper.ui.views.profile_manage import RiotIdRegisterModal, UserProfileManageView


@app_commands.command(
    name="register",
    description="서버 멤버의 League of Legends 또는 VALORANT 프로필을 등록하거나 수정합니다.",
)
@app_commands.guild_only()
@app_commands.describe(
    member="등록할 디스코드 서버 멤버를 선택하세요.",
    profile_type="등록할 게임(League of Legends 또는 VALORANT)을 선택하세요.",
)
@app_commands.choices(
    profile_type=[
        app_commands.Choice(name="League of Legends", value="lol"),
        app_commands.Choice(name="VALORANT", value="valorant"),
    ],
)
async def register(
    interaction: discord.Interaction,
    member: discord.Member,
    profile_type: app_commands.Choice[str],
):
    if interaction.guild_id is None:
        await interaction.response.send_message("이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    modal = RiotIdRegisterModal(
        guild_id=interaction.guild_id,
        member=member,
        game_value=profile_type.value,
        game_label=profile_type.name,
    )
    await interaction.response.send_modal(modal)


async def _open_profile_directory(interaction: discord.Interaction, game: str, empty_msg: str):
    if interaction.guild is None or interaction.guild_id is None:
        await interaction.response.send_message("이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    profiles = database.get_profiles(guild_id=interaction.guild_id, game=game)
    if not profiles:
        await interaction.response.send_message(empty_msg, ephemeral=True)
        return

    items_with_names = [(p, await get_display_nickname(interaction.guild, p)) for p in profiles]
    view = ProfileDirectoryView(game=game, items_with_names=items_with_names)
    await interaction.response.send_message(content=view.render_content(), view=view, ephemeral=True)


@app_commands.command(name="lolprofile", description="등록된 League of Legends 멤버의 프로필을 드롭다운으로 조회합니다.")
@app_commands.guild_only()
async def lolprofile(interaction: discord.Interaction):
    await _open_profile_directory(
        interaction, "lol", "등록된 League of Legends 프로필이 없습니다. `/register`로 먼저 등록해 주세요."
    )


@app_commands.command(name="valprofile", description="등록된 VALORANT 멤버의 프로필을 드롭다운으로 조회합니다.")
@app_commands.guild_only()
async def valprofile(interaction: discord.Interaction):
    await _open_profile_directory(
        interaction, "valorant", "등록된 VALORANT 프로필이 없습니다. `/register`로 먼저 등록해 주세요."
    )


@app_commands.command(
    name="refreshlol",
    description="등록된 League of Legends 프로필의 랭크와 주 포지션을 Riot에서 다시 불러옵니다.",
)
@app_commands.guild_only()
async def refreshlol(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild_id is None:
        await interaction.response.send_message("이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    profiles = database.get_profiles(guild_id=interaction.guild_id, game="lol")
    if not profiles:
        await interaction.response.send_message("등록된 League of Legends 프로필이 없습니다.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    updated_profiles = []
    failed_profiles = []

    try:
        async with aiohttp.ClientSession(
            headers=riot_api.get_headers(),
            timeout=aiohttp.ClientTimeout(total=30),
        ) as session:
            for profile in profiles:
                try:
                    api_data = await riot_api.fetch_lol_profile_data(
                        session=session,
                        game_name=profile["riot_game_name"],
                        tagline=profile["riot_tagline"],
                    )
                    database.update_profile_api_data(
                        guild_id=interaction.guild_id,
                        discord_user_id=profile["discord_user_id"],
                        game="lol",
                        puuid=api_data["puuid"],
                        solo_tier=api_data["solo_tier"],
                        flex_tier=api_data["flex_tier"],
                        main_position=api_data["main_position"],
                    )
                    updated_profiles.append(profile["discord_nickname"])
                except (riot_api.RiotAPIError, aiohttp.ClientError, asyncio.TimeoutError) as error:
                    logging.warning(
                        "LoL 데이터 조회 실패 (%s#%s): %s: %s",
                        profile["riot_game_name"],
                        profile["riot_tagline"],
                        type(error).__name__,
                        error,
                    )
                    failed_profiles.append(profile["discord_nickname"])
    except riot_api.RiotAPIError as error:
        await interaction.followup.send(str(error), ephemeral=True)
        return

    lines = [
        f"갱신한 LoL 프로필: {len(updated_profiles)}개",
        f"실패한 프로필: {len(failed_profiles)}개",
    ]
    if failed_profiles:
        lines.append("")
        lines.extend(f"- {name}" for name in failed_profiles)

    await interaction.followup.send(
        "\n".join(lines),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@app_commands.command(
    name="refreshval",
    description="등록된 VALORANT 프로필의 경쟁전 티어와 주 역할을 Riot에서 다시 불러옵니다.",
)
@app_commands.guild_only()
async def refreshval(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild_id is None:
        await interaction.response.send_message("이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    profiles = database.get_profiles(guild_id=interaction.guild_id, game="valorant")
    if not profiles:
        await interaction.response.send_message("등록된 VALORANT 프로필이 없습니다.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    updated_profiles = []
    failed_profiles = []

    try:
        async with aiohttp.ClientSession(
            headers=riot_api.get_headers(riot_valorant.VAL_API_KEY_ENV),
            timeout=aiohttp.ClientTimeout(total=60),
        ) as session:
            for profile in profiles:
                try:
                    api_data = await riot_valorant.fetch_val_profile_data(
                        session=session,
                        game_name=profile["riot_game_name"],
                        tagline=profile["riot_tagline"],
                    )
                    database.update_profile_api_data(
                        guild_id=interaction.guild_id,
                        discord_user_id=profile["discord_user_id"],
                        game="valorant",
                        puuid=api_data["puuid"],
                        competitive_tier=api_data["competitive_tier"],
                        main_position=api_data["main_position"],
                    )
                    updated_profiles.append(profile["discord_nickname"])
                except (riot_api.RiotAPIError, aiohttp.ClientError, asyncio.TimeoutError) as error:
                    logging.warning(
                        "VALORANT 데이터 조회 실패 (%s#%s): %s: %s",
                        profile["riot_game_name"],
                        profile["riot_tagline"],
                        type(error).__name__,
                        error,
                    )
                    failed_profiles.append(profile["discord_nickname"])
    except riot_api.RiotAPIError:
        await interaction.followup.send(
            "발로란트 API 키(`RIOT_VAL_API_KEY`)가 설정되지 않았습니다. 봇 관리자에게 문의해 주세요.",
            ephemeral=True,
        )
        return

    lines = [
        f"갱신한 VALORANT 프로필: {len(updated_profiles)}개",
        f"실패한 프로필: {len(failed_profiles)}개",
    ]
    if failed_profiles:
        lines.append("")
        lines.extend(f"- {name}" for name in failed_profiles)

    await interaction.followup.send(
        "\n".join(lines),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@app_commands.command(
    name="unregister",
    description="등록된 게임 프로필(register 정보)을 삭제합니다. 다른 유저가 잘못 등록된 경우 대상을 지정해 삭제할 수 있습니다.",
)
@app_commands.guild_only()
@app_commands.describe(
    member="등록 해제할 디스코드 유저 (비워두면 본인의 등록 정보를 삭제합니다)",
    game="삭제할 게임 프로필 (비워두면 LoL과 발로란트 모두 삭제합니다)",
)
@app_commands.choices(
    game=[
        app_commands.Choice(name="전체 (LoL + VALORANT)", value="all"),
        app_commands.Choice(name="League of Legends", value="lol"),
        app_commands.Choice(name="VALORANT", value="valorant"),
    ]
)
async def unregister_command(
    interaction: discord.Interaction,
    member: discord.Member | None = None,
    game: app_commands.Choice[str] | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message("이 명령어는 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return

    target_user = member or interaction.user
    selected_game = game.value if game else "all"

    if target_user.id != interaction.user.id:
        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild
        if not is_admin:
            await interaction.response.send_message(
                "다른 유저의 등록 정보를 해제하려면 서버 관리(`서버 관리하기`) 권한이 필요합니다.",
                ephemeral=True,
            )
            return

    deleted_count = database.delete_user_profile(
        guild_id=interaction.guild.id,
        discord_user_id=target_user.id,
        game=selected_game,
    )

    game_label = (
        "전체(LoL + VALORANT)"
        if selected_game == "all"
        else ("League of Legends" if selected_game == "lol" else "VALORANT")
    )

    if deleted_count > 0:
        await interaction.response.send_message(
            f"✅ {target_user.mention} 님의 **{game_label}** 등록 프로필({deleted_count}건)이 삭제되었습니다.\n"
            "이제 `/register` 명령어로 올바른 계정을 다시 등록할 수 있습니다.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ {target_user.mention} 님은 현재 **{game_label}**에 등록된 프로필이 없습니다.",
            ephemeral=True,
        )


@app_commands.command(
    name="userprofile",
    description="유저의 게임 프로필(실제/체감 티어 및 선호 포지션)을 확인하고 권한이 있으면 수정합니다.",
)
@discord.app_commands.describe(
    game="조회할 게임을 선택하세요 (League of Legends 또는 VALORANT)",
    member="조회할 서버원을 선택하세요 (비워두면 본인의 프로필을 조회합니다)",
)
@discord.app_commands.choices(
    game=[
        discord.app_commands.Choice(name="League of Legends", value="lol"),
        discord.app_commands.Choice(name="VALORANT", value="valorant"),
    ]
)
async def userprofile_command(
    interaction: discord.Interaction,
    game: discord.app_commands.Choice[str],
    member: discord.Member | None = None,
):
    if interaction.guild_id is None:
        await interaction.response.send_message("이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    target_member = member or interaction.user
    selected_game = game.value
    game_label = "League of Legends" if selected_game == "lol" else "VALORANT"

    profile = database.get_user_profile(interaction.guild_id, target_member.id, selected_game)
    if profile is None:
        await interaction.response.send_message(
            f"❌ **{target_member.display_name}**님은 아직 **{game_label}** 프로필이 등록되어 있지 않습니다.\n"
            "먼저 `/register` 명령어로 프로필을 등록해 주세요.",
            ephemeral=True,
        )
        return

    can_edit, edit_reason = database.can_user_edit_profile(
        interaction.guild_id,
        interaction.user.id,
        target_member.id,
        selected_game,
    )
    card_text = format_user_profile_card(profile, can_edit, edit_reason)

    if can_edit:
        view = UserProfileManageView(
            guild_id=interaction.guild_id,
            target_user_id=target_member.id,
            game=selected_game,
            profile=profile,
        )
        await interaction.response.send_message(content=card_text, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(content=card_text, ephemeral=True)


def setup(tree: app_commands.CommandTree) -> None:
    tree.add_command(register)
    tree.add_command(lolprofile)
    tree.add_command(valprofile)
    tree.add_command(refreshlol)
    tree.add_command(refreshval)
    tree.add_command(unregister_command)
    tree.add_command(userprofile_command)
