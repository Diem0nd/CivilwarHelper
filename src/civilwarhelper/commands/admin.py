import discord
from discord import app_commands

from civilwarhelper import db as database


@app_commands.command(
    name="resetstats",
    description="[관리자 전용] 내전 통산 승률 및 밸런스별 전적 기록을 초기화합니다.",
)
@discord.app_commands.default_permissions(administrator=True)
@discord.app_commands.describe(
    member="전적을 초기화할 멤버 (선택하지 않으면 모든 유저의 전적을 초기화합니다)",
    game="초기화할 게임 종목 (기본값: 전체 게임)",
)
@discord.app_commands.choices(
    game=[
        discord.app_commands.Choice(name="전체 게임 (LoL + VALORANT)", value="all"),
        discord.app_commands.Choice(name="League of Legends (롤)", value="lol"),
        discord.app_commands.Choice(name="VALORANT (발로란트)", value="valorant"),
    ]
)
async def resetstats_command(
    interaction: discord.Interaction,
    member: discord.Member | None = None,
    game: discord.app_commands.Choice[str] | None = None,
):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("이 명령어는 서버 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "🚫 이 명령어는 **서버 관리자(Administrator)** 이상의 권한을 가진 사람만 사용할 수 있습니다.",
            ephemeral=True,
        )
        return

    selected_game = game.value if game is not None else "all"
    game_label_map = {
        "all": "전체 게임(LoL + VALORANT)",
        "lol": "League of Legends",
        "valorant": "VALORANT",
    }
    game_label = game_label_map.get(selected_game, "전체 게임")

    target_uid = member.id if member is not None else None
    deleted_count = database.reset_global_user_inhouse_stats(discord_user_id=target_uid, game=selected_game)
    target_desc = f"**{member.display_name}**님의" if member is not None else "**모든 유저**의"

    await interaction.response.send_message(
        f"✅ {target_desc} **{game_label}** 내전 전적 기록이 초기화되었습니다. (삭제된 기록: {deleted_count}건)",
        ephemeral=True,
    )


def setup(tree: app_commands.CommandTree) -> None:
    tree.add_command(resetstats_command)
