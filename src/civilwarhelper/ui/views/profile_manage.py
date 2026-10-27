import asyncio

import aiohttp
import discord

from civilwarhelper import db as database
from civilwarhelper.config.positions import LOL_STANDARD_POSITIONS, VAL_STANDARD_POSITIONS
from civilwarhelper.config.tiers import LOL_TIER_NAMES_ORDERED, VAL_TIER_NAMES_ORDERED
from civilwarhelper.riot import client as riot_api
from civilwarhelper.riot import valorant as riot_valorant
from civilwarhelper.ui.formatting.profile import format_user_profile_card


async def sync_valorant_profile(
    guild_id: int,
    discord_user_id: int,
    game_name: str,
    tagline: str,
) -> str:
    try:
        async with aiohttp.ClientSession(
            headers=riot_api.get_headers(riot_valorant.VAL_API_KEY_ENV),
            timeout=aiohttp.ClientTimeout(total=60),
        ) as session:
            api_data = await riot_valorant.fetch_val_profile_data(session, game_name, tagline)
    except riot_api.RiotAPIError as e:
        if e.status_code is None:
            return (
                "\n⚠️ 발로란트 API 키가 아직 설정되지 않아 티어를 불러오지 못했습니다. "
                "`/userprofile`에서 체감 티어와 포지션을 설정하면 내전 밸런스에 반영됩니다."
            )
        return f"\n⚠️ Riot API 조회 중 오류가 발생했습니다: {e}"
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        return f"\n⚠️ Riot API 조회 중 오류가 발생했습니다: {e}"

    database.update_profile_api_data(
        guild_id=guild_id,
        discord_user_id=discord_user_id,
        game="valorant",
        puuid=api_data["puuid"],
        competitive_tier=api_data["competitive_tier"],
        main_position=api_data["main_position"],
    )
    return (
        f"\n📊 **Riot API 연동 완료** — "
        f"경쟁전: `{api_data['competitive_tier']}` / "
        f"주 역할: `{api_data['main_position']}`"
    )


class RiotIdRegisterModal(discord.ui.Modal):
    def __init__(self, guild_id: int, member: discord.Member, game_value: str, game_label: str):
        super().__init__(title=f"{game_label} 프로필 등록")
        self.guild_id = guild_id
        self.member = member
        self.game_value = game_value
        self.game_label = game_label

        self.riot_id_tag_input = discord.ui.TextInput(
            label="라이엇 ID#태그",
            placeholder="예: Hide on bush#KR1",
            required=True,
            max_length=60,
        )
        self.add_item(self.riot_id_tag_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.riot_id_tag_input.value.strip()
        if "#" not in raw:
            await interaction.response.send_message(
                "❌ 반드시 `#`을 포함하여 **`라이엇ID#태그`** 형식으로 입력해 주세요. (예: `Hide on bush#KR1`)",
                ephemeral=True,
            )
            return

        riot_part, tag_part = raw.rsplit("#", 1)
        riot_id = riot_part.strip()
        tag = tag_part.strip().lstrip("#").upper()

        if not riot_id or not tag:
            await interaction.response.send_message(
                "❌ 라이엇 ID와 태그가 모두 비어있지 않아야 합니다. (예: `Hide on bush#KR1`)",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        loc = "Korea"
        was_updated = database.save_profile(
            guild_id=self.guild_id,
            discord_user_id=self.member.id,
            game=self.game_value,
            discord_nickname=self.member.display_name,
            riot_game_name=riot_id,
            riot_tagline=tag,
            server_location=loc,
        )

        api_note = ""
        if self.game_value == "lol":
            try:
                async with aiohttp.ClientSession(
                    headers=riot_api.get_headers(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as session:
                    api_data = await riot_api.fetch_lol_profile_data(session, riot_id, tag)

                database.update_profile_api_data(
                    guild_id=self.guild_id,
                    discord_user_id=self.member.id,
                    game="lol",
                    puuid=api_data["puuid"],
                    solo_tier=api_data["solo_tier"],
                    flex_tier=api_data["flex_tier"],
                    main_position=api_data["main_position"],
                )
                api_note = (
                    f"\n📊 **Riot API 연동 완료** — "
                    f"Solo: `{api_data['solo_tier']}` / "
                    f"Flex: `{api_data['flex_tier']}` / "
                    f"주 포지션: `{api_data['main_position']}`"
                )
            except (riot_api.RiotAPIError, aiohttp.ClientError, asyncio.TimeoutError) as e:
                api_note = f"\n⚠️ Riot API 조회 중 오류가 발생했습니다: {e}"
        elif self.game_value == "valorant":
            api_note = await sync_valorant_profile(self.guild_id, self.member.id, riot_id, tag)

        action_word = "Updated" if was_updated else "Registered"
        await interaction.followup.send(
            f"✅ **{action_word} {self.game_label} profile**\n"
            f"`{self.member.display_name} - {riot_id} #{tag} / {loc}`"
            f"{api_note}",
            allowed_mentions=discord.AllowedMentions.none(),
        )


def _needs_division(game: str, base_tier: str) -> bool:
    up = base_tier.upper()
    if up == "UNRANKED":
        return False
    if game == "lol" and up in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return False
    if game == "valorant" and up == "RADIANT":
        return False
    return True


class CustomTierBaseSelect(discord.ui.Select):
    def __init__(self, parent_view: "UserProfileManageView"):
        self.parent_view = parent_view
        tier_names = LOL_TIER_NAMES_ORDERED if parent_view.game == "lol" else VAL_TIER_NAMES_ORDERED

        options = [
            discord.SelectOption(
                label="체감 티어 해제 (실제 티어 사용)",
                value="RESET_CUSTOM_TIER",
                description="체감 티어 보정을 끄고 원래 랭크 티어를 사용합니다.",
            )
        ]

        selected_base = (parent_view.selected_tier_base or "").upper()
        for t_name in tier_names:
            options.append(
                discord.SelectOption(
                    label=f"체감 티어: {t_name}",
                    value=t_name,
                    default=(t_name.upper() == selected_base),
                )
            )

        super().__init__(
            placeholder="1️⃣ 체감 티어 등급 선택 (또는 해제)",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        allowed, reason = database.can_user_edit_profile(
            pv.guild_id, interaction.user.id, pv.target_user_id, pv.game
        )
        if not allowed:
            await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
            return

        choice = self.values[0]
        if choice == "RESET_CUSTOM_TIER":
            pv.selected_tier_base = None
            new_tier = None
        elif not _needs_division(pv.game, choice):
            pv.selected_tier_base = choice
            new_tier = choice
        else:
            pv.selected_tier_base = choice
            new_tier = f"{choice} {'IV' if pv.game == 'lol' else '1'}"

        updated = database.update_user_profile_custom_settings(
            pv.guild_id, pv.target_user_id, pv.game, custom_tier=new_tier
        )
        pv.profile = updated
        pv.rebuild_components()
        await interaction.response.edit_message(
            content=format_user_profile_card(updated, True, reason),
            view=pv,
        )


class CustomTierDivisionSelect(discord.ui.Select):
    def __init__(self, parent_view: "UserProfileManageView"):
        self.parent_view = parent_view
        base_name = parent_view.selected_tier_base or "Gold"
        current_custom = (parent_view.profile.get("custom_tier") or "").strip()
        divisions = ["IV", "III", "II", "I"] if parent_view.game == "lol" else ["1", "2", "3"]

        options = [
            discord.SelectOption(
                label=f"세부 단계: {base_name} {div}",
                value=f"{base_name} {div}",
                default=(current_custom.upper() == f"{base_name} {div}".upper()),
            )
            for div in divisions
        ]

        super().__init__(
            placeholder=f"2️⃣ {base_name} 세부 단계 선택",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        allowed, reason = database.can_user_edit_profile(
            pv.guild_id, interaction.user.id, pv.target_user_id, pv.game
        )
        if not allowed:
            await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
            return

        updated = database.update_user_profile_custom_settings(
            pv.guild_id, pv.target_user_id, pv.game, custom_tier=self.values[0]
        )
        pv.profile = updated
        pv.rebuild_components()
        await interaction.response.edit_message(
            content=format_user_profile_card(updated, True, reason),
            view=pv,
        )


class ProfileMainPositionSelect(discord.ui.Select):
    def __init__(self, parent_view: "UserProfileManageView"):
        self.parent_view = parent_view
        positions = LOL_STANDARD_POSITIONS if parent_view.game == "lol" else VAL_STANDARD_POSITIONS
        current_main = parent_view.profile.get("main_position") or ""

        options = [
            discord.SelectOption(
                label=f"주 포지션: {pos}",
                value=pos,
                default=(pos.lower() == current_main.lower()),
            )
            for pos in positions
        ]

        super().__init__(
            placeholder="🎯 주 포지션 변경",
            min_values=1,
            max_values=1,
            options=options,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        allowed, reason = database.can_user_edit_profile(
            pv.guild_id, interaction.user.id, pv.target_user_id, pv.game
        )
        if not allowed:
            await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
            return

        updated = database.update_user_profile_custom_settings(
            pv.guild_id, pv.target_user_id, pv.game, main_position=self.values[0]
        )
        pv.profile = updated
        pv.rebuild_components()
        await interaction.response.edit_message(
            content=format_user_profile_card(updated, True, reason),
            view=pv,
        )


class ProfileSubPositionSelect(discord.ui.Select):
    def __init__(self, parent_view: "UserProfileManageView"):
        self.parent_view = parent_view
        positions = LOL_STANDARD_POSITIONS if parent_view.game == "lol" else VAL_STANDARD_POSITIONS
        current_sub = parent_view.profile.get("sub_position") or ""

        options = [
            discord.SelectOption(
                label="부 포지션: 선택안함",
                value="NONE",
                default=(not current_sub or current_sub == "선택안함"),
            )
        ] + [
            discord.SelectOption(
                label=f"부 포지션: {pos}",
                value=pos,
                default=(pos.lower() == current_sub.lower()),
            )
            for pos in positions
        ]

        super().__init__(
            placeholder="🛡️ 부 포지션 변경 (선택안함 가능)",
            min_values=1,
            max_values=1,
            options=options,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        allowed, reason = database.can_user_edit_profile(
            pv.guild_id, interaction.user.id, pv.target_user_id, pv.game
        )
        if not allowed:
            await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
            return

        choice = None if self.values[0] == "NONE" else self.values[0]
        updated = database.update_user_profile_custom_settings(
            pv.guild_id, pv.target_user_id, pv.game, sub_position=choice
        )
        pv.profile = updated
        pv.rebuild_components()
        await interaction.response.edit_message(
            content=format_user_profile_card(updated, True, reason),
            view=pv,
        )


class UserProfileManageView(discord.ui.View):
    def __init__(self, guild_id: int, target_user_id: int, game: str, profile: dict):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.target_user_id = target_user_id
        self.game = game
        self.profile = profile

        custom_tier = (profile.get("custom_tier") or "").strip()
        self.selected_tier_base = custom_tier.split()[0] if custom_tier else None
        self.rebuild_components()

    def rebuild_components(self) -> None:
        self.clear_items()
        self.add_item(CustomTierBaseSelect(self))

        if self.selected_tier_base and _needs_division(self.game, self.selected_tier_base):
            self.add_item(CustomTierDivisionSelect(self))

        self.add_item(ProfileMainPositionSelect(self))
        self.add_item(ProfileSubPositionSelect(self))
