import asyncio
import logging
import random

import discord
from discord import app_commands

from civilwarhelper.ui.emojis import get_custom_emoji
from civilwarhelper.ui.views.rps import RPSGameView


@app_commands.command(name="핑", description="봇이 정상 작동하는지 확인합니다.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("# 퐁! " + get_custom_emoji("APing", "🏓"))


@app_commands.command(name="가위바위보", description="RED / BLUE 두 진영 대표가 가위바위보로 진영이나 선공을 결정합니다.")
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


@app_commands.command(name="주사위", description="1에서 6 사이의 주사위를 굴립니다. (누구나 사용 가능)")
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

@app_commands.command(name="도움", description="내전 도우미 봇의 전체 명령어 목록과 사용 방법을 안내합니다.")
async def help_command(interaction: discord.Interaction):
    help_text = "\n".join(
        [
            f"# {get_custom_emoji('ACharting', '📘')} 내전 도우미 (CivilwarHelper) 사용 가이드",
            "",
            "### 1️⃣ 기본 사용 순서 (처음이신 분 필독!)",
            "1. **`/등록`** 명령어로 본인의 **롤(LoL)** 또는 **발로란트** 계정(`닉네임#태그`)을 먼저 등록합니다.",
            "2. **`/프로필`** 명령어에서 본인의 **선호 포지션**이나 **체감 티어**(권한 보유 시)를 설정할 수 있습니다.",
            "3. 주최자가 **`/내전생성`**으로 모집 로비를 열면 **[참가]** 버튼을 눌러 내전에 합류합니다!",
            "",
            "---",
            "### 👤 프로필 및 계정 관리",
            "- **`/등록`** : 서버 멤버의 LoL 또는 VALORANT 계정을 등록하거나 수정합니다.",
            "- **`/프로필`** : 유저의 게임 프로필(실제/체감 티어, 선호 포지션, 내전 전적)을 확인하고 수정합니다.",
            "- **`/롤프로필`** : 서버에 등록된 모든 LoL 멤버 프로필을 드롭다운으로 조회합니다.",
            "- **`/발로프로필`** : 서버에 등록된 모든 VALORANT 멤버 프로필을 드롭다운으로 조회합니다.",
            "- **`/롤갱신`** : 등록된 LoL 프로필들의 최신 랭크와 주 포지션을 Riot API에서 다시 불러옵니다.",
            "- **`/발로갱신`** : 등록된 VALORANT 프로필들의 최신 티어와 주 역할을 다시 불러옵니다.",
            "- **`/등록해제`** : 등록된 게임 프로필 정보를 삭제합니다.",
            "",
            "### ⚔️ 내전 진행 및 관리",
            "- **`/내전생성`** : LoL 또는 VALORANT 내전 모집 로비를 생성합니다.",
            "- **`/내전목록`** : 현재 진행 중인 내전 목록과 참가자 현황을 확인합니다.",
            "- **`/주최자양도`** : 현재 내전의 주최자 권한을 다른 멤버에게 넘깁니다.",
            "- **`/내전종료`** : 진행 중인 내전 세션을 종료합니다. (주최자 또는 서버 관리자)",
            "",
            "### 🎲 미니게임 및 유틸리티",
            "- **`/가위바위보`** : RED / BLUE 두 진영 대표가 가위바위보로 진영이나 선공을 결정합니다.",
            "- **`/주사위`** : 1에서 6 사이의 주사위를 굴립니다.",
            "- **`/핑`** : 봇이 정상 작동하는지 응답 속도를 확인합니다.",
            "- **`/도움`** : 지금 보고 계신 명령어 안내창을 표시합니다.",
            "",
            "### 🛠️ 관리자 전용",
            "- **`/전적초기화`** : `[서버 관리자 전용]` 내전 통산 승률 및 밸런스별 전적 기록을 초기화합니다.",
        ]
    )

    await interaction.response.send_message(content=help_text, ephemeral=True)

def setup(tree: app_commands.CommandTree) -> None:
    tree.add_command(ping)
    tree.add_command(rps_command)
    tree.add_command(dice_command)
    tree.add_command(help_command)