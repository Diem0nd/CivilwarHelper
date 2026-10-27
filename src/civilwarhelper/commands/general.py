import asyncio
import logging
import random

import discord
from discord import app_commands

from civilwarhelper.ui.emojis import get_custom_emoji
from civilwarhelper.ui.views.rps import RPSGameView


@app_commands.command(name="ping", description="봇이 정상 작동하는지 확인합니다.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("# 퐁! " + get_custom_emoji("APing", "🏓"))


@app_commands.command(name="rps", description="RED / BLUE 두 진영 대표가 가위바위보로 진영이나 선공을 결정합니다.")
async def rps_command(interaction: discord.Interaction):
    view = RPSGameView(host_user=interaction.user)
    await interaction.response.send_message(
        content=view.format_status_message(),
        view=view,
        allowed_mentions=discord.AllowedMentions(users=True),
    )


DICE_ROLLING_TEXTS = [
    ("🎲 **데구르르... 주사위가 백플립을 하는 것 같습니다...**", 24),
    ("🎲 **당신은 사기 주사위가 아니길 바라며, 손에 땀을 쥐고있습니다...**", 24),
    ("🎲 **주사위가 테이블 끝에서 아슬아슬하게 회전합니다...!**", 24),
    ("🎲 **기도하는 마음으로 주사위를 던졌습니다... 제발 높은 숫자!!**", 24),
    ("✨🌈 **[초희귀] 빛을 내는 말랑한 두부 위로 주사위가 슬로우 모션으로 굴러갑니다...!!** 🌈✨", 4),
]


@app_commands.command(name="dice", description="1에서 6 사이의 주사위를 굴립니다. (누구나 사용 가능)")
async def dice_command(interaction: discord.Interaction):
    await interaction.response.defer()

    texts = [item[0] for item in DICE_ROLLING_TEXTS]
    weights = [item[1] for item in DICE_ROLLING_TEXTS]
    selected_rolling_text = random.choices(texts, weights=weights, k=1)[0]

    channel = interaction.channel
    if channel is not None:
        try:
            temp_msg = await channel.send(selected_rolling_text)
            await asyncio.sleep(1.6)
            await temp_msg.delete()
        except discord.HTTPException as error:
            logging.debug("주사위 연출 메시지 전송/삭제 실패: %s", error)
            await asyncio.sleep(1.3)

    rolled = random.randint(1, 6)
    dice_emoji = get_custom_emoji(f"Dice{rolled}", f"🎲({rolled})")

    await interaction.followup.send(
        content=f"<@{interaction.user.id}> 님이 주사위를 굴렸습니다!\n결과: {dice_emoji} **{rolled}**",
        allowed_mentions=discord.AllowedMentions(users=True),
    )


def setup(tree: app_commands.CommandTree) -> None:
    tree.add_command(ping)
    tree.add_command(rps_command)
    tree.add_command(dice_command)
