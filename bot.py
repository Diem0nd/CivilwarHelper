import os
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv

import database
import riot_api


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
riot_key = os.getenv("RIOT_API_KEY")

print(
    "Riot 키 로드됨:",
    bool(riot_key),
    "올바르게 시작함:",
    bool(riot_key and riot_key.startswith("RGAPI-")),
    "길이:",
    len(riot_key) if riot_key else 0,
)


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Supports multiple test servers.
# Example:
# TEST_GUILD_IDS=123456789012345678,987654321098765432
raw_test_guild_ids = os.getenv("TEST_GUILD_IDS", "")

TEST_GUILD_IDS = [
    int(guild_id.strip())
    for guild_id in raw_test_guild_ids.split(",")
    if guild_id.strip()
]

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from the environment.")


database.initialize_database()


class CivilwarHelper(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()

        super().__init__(intents=intents)

        self.command_tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if TEST_GUILD_IDS:
            for guild_id in TEST_GUILD_IDS:
                test_guild = discord.Object(id=guild_id)

                self.command_tree.copy_global_to(guild=test_guild)
                await self.command_tree.sync(guild=test_guild)

                print(
                    f"Commands synchronized to test server {guild_id}."
                )
        else:
            await self.command_tree.sync()
            print("Global commands synchronized.")


bot = CivilwarHelper()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}.")
    print("CivilwarHelper is ready.")


@bot.command_tree.command(
    name="ping",
    description="Checks whether the bot is working.",
)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

async def send_profile_lines(
    interaction: discord.Interaction,
    lines: list[str],
):
    """
    Sends the profile list without allowing Discord mentions.

    If the list becomes too long for one Discord message, it is split
    into multiple messages.
    """
    chunks = []
    current_chunk = ""

    for line in lines:
        proposed_chunk = (
            f"{current_chunk}\n{line}"
            if current_chunk
            else line
        )

        if len(proposed_chunk) > 1900:
            if current_chunk:
                chunks.append(current_chunk)

            current_chunk = line
        else:
            current_chunk = proposed_chunk

    if current_chunk:
        chunks.append(current_chunk)

    if not chunks:
        chunks = ["No registered members."]

    no_mentions = discord.AllowedMentions.none()

    await interaction.response.send_message(
        chunks[0],
        allowed_mentions=no_mentions,
    )

    for chunk in chunks[1:]:
        await interaction.followup.send(
            chunk,
            allowed_mentions=no_mentions,
        )

async def get_display_nickname(
    guild: discord.Guild,
    profile: dict,
):
    """
    Uses the member's current server nickname.
    Falls back to the nickname saved during registration.
    """
    member = guild.get_member(profile["discord_user_id"])

    if member is not None:
        return member.display_name

    return profile.get("discord_nickname", "Unknown member")


@bot.command_tree.command(
    name="register",
    description="Registers one League of Legends or VALORANT profile.",
)
@app_commands.guild_only()
@app_commands.describe(
    profile_type="Choose League of Legends or VALORANT.",
    member="Select the Discord server member being registered.",
    riot_id="Enter the Riot ID game name, without the # symbol.",
    tag="Enter the Riot ID tag, without the # symbol.",
    server_location="Select the account's server location.",
)
@app_commands.choices(
    profile_type=[
        app_commands.Choice(
            name="League of Legends",
            value="lol",
        ),
        app_commands.Choice(
            name="VALORANT",
            value="valorant",
        ),
    ],
    server_location=[
        app_commands.Choice(
            name="Korea",
            value="Korea",
        ),
    ],

)
async def register(
    interaction: discord.Interaction,
    profile_type: app_commands.Choice[str],
    member: discord.Member,
    riot_id: str,
    tag: str,
    server_location: app_commands.Choice[str],
):
    if interaction.guild is None or interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used inside a Discord server.",
            ephemeral=True,
        )
        return

    riot_id = riot_id.strip()
    tag = tag.strip().lstrip("#")

    if not riot_id:
        await interaction.response.send_message(
            "The Riot ID is required.",
            ephemeral=True,
        )
        return

    if not tag:
        await interaction.response.send_message(
            "The tag is required.",
            ephemeral=True,
        )
        return

    nickname = member.display_name

    was_updated = database.save_profile(
        guild_id=interaction.guild_id,
        discord_user_id=member.id,
        game=profile_type.value,
        discord_nickname=nickname,
        riot_game_name=riot_id,
        riot_tagline=tag,
        server_location=server_location.value,
    )

    if profile_type.value == "lol":
        game_name = "League of Legends"
    else:
        game_name = "VALORANT"

    if was_updated:
        result_message = "The profile has been updated."
    else:
        result_message = "The profile has been registered."

    safe_nickname = discord.utils.escape_markdown(nickname)

    await interaction.response.send_message(
        (
            f"{result_message}\n\n"
            f"Game: {game_name}\n"
            f"Discord nickname: {safe_nickname}\n"
            f"Riot ID: {riot_id}#{tag}\n"
            f"Server location: {server_location.name}"
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )

@bot.command_tree.command(
    name="lolprofile",
    description="Displays registered League of Legends members.",
)
@app_commands.guild_only()
async def lolprofile(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used inside a Discord server.",
            ephemeral=True,
        )
        return

    profiles = database.get_profiles(
        guild_id=interaction.guild_id,
        game="lol",
    )

    if not profiles:
        await interaction.response.send_message(
            "No League of Legends profiles are registered.",
            ephemeral=True,
        )
        return

    lines = ["Registered members"]

    for profile in profiles:
        nickname = await get_display_nickname(
            interaction.guild,
            profile,
        )

        nickname = discord.utils.escape_markdown(nickname)

        solo_tier = profile["solo_tier"] or "Not retrieved yet"
        flex_tier = profile["flex_tier"] or "Not retrieved yet"
        position = profile["main_position"] or "Not retrieved yet"

        lines.append(
            (
                f"{nickname} - "
                f"{profile['riot_game_name']} #{profile['riot_tagline']} / "
                f"{profile['server_location']} "
                f"(Tier Solo: {solo_tier} / "
                f"Flex: {flex_tier} / "
                f"Position: {position})"
            )
        )

    await send_profile_lines(
        interaction=interaction,
        lines=lines,
    )

@bot.command_tree.command(
    name="refreshlol",
    description="Retrieves current League of Legends data from Riot.",
)
@app_commands.guild_only()
async def refreshlol(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used inside a Discord server.",
            ephemeral=True,
        )
        return

    profiles = database.get_profiles(
        guild_id=interaction.guild_id,
        game="lol",
    )

    if not profiles:
        await interaction.response.send_message(
            "No League of Legends profiles are registered.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    updated_profiles = []
    failed_profiles = []

    try:
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(
            headers=riot_api.get_headers(),
            timeout=timeout,
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

                    updated_profiles.append(
                        profile["discord_nickname"]
                    )

                except Exception as error:
                    print(
                        "Error retrieving Riot data for "
                        f"{profile['riot_game_name']}#"
                        f"{profile['riot_tagline']}: "
                        f"{type(error).__name__}: {error}"
                    )

                    failed_profiles.append(
                        profile["discord_nickname"]
                    )


    except riot_api.RiotAPIError as error:
        await interaction.followup.send(
            str(error),
            ephemeral=True,
        )
        return

    lines = [
        f"Updated League profiles: {len(updated_profiles)}",
        f"Failed profiles: {len(failed_profiles)}",
    ]

    if failed_profiles:
        lines.append("")
        lines.append("Failed profiles:")

        for failed_profile in failed_profiles:
            lines.append(f"- {failed_profile}")

    await interaction.followup.send(
        "\n".join(lines),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )

@bot.command_tree.command(
    name="valprofile",
    description="Displays registered VALORANT members.",
)
@app_commands.guild_only()
async def valprofile(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used inside a Discord server.",
            ephemeral=True,
        )
        return

    profiles = database.get_profiles(
        guild_id=interaction.guild_id,
        game="valorant",
    )

    if not profiles:
        await interaction.response.send_message(
            "No VALORANT profiles are registered.",
            ephemeral=True,
        )
        return

    lines = ["Registered members"]

    for profile in profiles:
        nickname = await get_display_nickname(
            interaction.guild,
            profile,
        )

        nickname = discord.utils.escape_markdown(nickname)

        tier = profile["competitive_tier"] or "Not retrieved yet"
        position = profile["main_position"] or "Not retrieved yet"

        lines.append(
            (
                f"{nickname} - "
                f"{profile['riot_game_name']} #{profile['riot_tagline']} / "
                f"{profile['server_location']} "
                f"(Tier: {tier} / Position: {position})"
            )
        )

    await send_profile_lines(
        interaction=interaction,
        lines=lines,
    )


bot.run(DISCORD_TOKEN)

@bot.command_tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    original_error = getattr(error, "original", error)

    print("Application command error:")
    print(repr(original_error))

    error_message = (
        "An internal error occurred while processing this command. "
        "Please check the bot console."
    )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                error_message,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                error_message,
                ephemeral=True,
            )
    except discord.HTTPException as response_error:
        print("Could not send the error message:")
        print(repr(response_error))