import os

import discord
from discord import app_commands
from dotenv import load_dotenv


load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID")


if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from the environment.")


class InhouseBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)

        self.command_tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if TEST_GUILD_ID:
            test_guild = discord.Object(id=int(TEST_GUILD_ID))

            # Copy commands to the test server.
            # Guild commands normally appear almost immediately.
            self.command_tree.copy_global_to(guild=test_guild)
            await self.command_tree.sync(guild=test_guild)

            print(f"Commands synchronized to test server {TEST_GUILD_ID}.")
        else:
            # Global commands can take longer to appear.
            await self.command_tree.sync()
            print("Global commands synchronized.")


bot = InhouseBot()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}.")


@bot.command_tree.command(
    name="ping",
    description="정상적으로 작동 중인지 확인합니다."
)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("퐁! 정상적으로 작동 중입니다.")


bot.run(DISCORD_TOKEN)
