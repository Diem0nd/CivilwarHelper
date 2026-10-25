import asyncio
import random
import discord

from match_common import get_custom_emoji

RPS_CHOICES = {
    "scissors": {"label": "가위", "emoji": "✌️", "beats": "paper"},
    "rock": {"label": "바위", "emoji": "✊", "beats": "scissors"},
    "paper": {"label": "보", "emoji": "🖐️", "beats": "rock"},
}

DICE_ROLLING_TEXTS = [
    ("데구르르... 주사위가 백플립을 하는 것 같습니다...", 24),
    ("당신은 사기 주사위가 아니길 바라며, 손에 땀을 쥐고 있습니다...", 24),
    ("주사위가 테이블 끝에서 아슬아슬하게 회전합니다...!", 24),
    ("기도하는 마음으로 주사위를 던졌습니다... 제발 높은 숫자!!", 24),
    ("✨🌈 **[초희귀] 빛을 내는 말랑한 두부 위로 주사위가 슬로우 모션으로 굴러갑니다...!!** 🌈✨", 4),
]


class RPSGameView(discord.ui.View):
    def __init__(self, host_user: discord.abc.User):
        super().__init__(timeout=300)
        self.host_user = host_user
        self.red_user: discord.abc.User | None = None
        self.blue_user: discord.abc.User | None = None
        self.picks: dict[str, str] = {}
        self.phase: str = "SIDE_SELECT"
        self.rebuild_items()

    def format_status_message(self) -> str:
        thinking_emoji = get_custom_emoji("AThinking", "⏳")
        playing_emoji = get_custom_emoji("APlaying", "🔥")

        red_text = f"<@{self.red_user.id}>" if self.red_user else f"*{thinking_emoji} 대기 중...*"
        blue_text = f"<@{self.blue_user.id}>" if self.blue_user else f"*{thinking_emoji} 대기 중...*"

        lines = [
            f"{playing_emoji} **진영 / 선공 결정 가위바위보**",
            f"🟥 **RED 진영**: {red_text}",
            f"🟦 **BLUE 진영**: {blue_text}",
            "",
        ]

        if self.phase == "SIDE_SELECT":
            lines.append(
                f"{thinking_emoji} 각 진영 대표 1명씩 아래 버튼을 눌러 참가해 주세요! (두 명이 모이면 바로 시작됩니다)"
            )
        elif self.phase == "PICK":
            red_ready = "✅ 선택 완료" if "RED" in self.picks else f"{thinking_emoji} 고민 중..."
            blue_ready = "✅ 선택 완료" if "BLUE" in self.picks else f"{thinking_emoji} 고민 중..."
            lines.append(f"{playing_emoji} **두 진영 참가 완료! 아래에서 가위, 바위, 보 중 하나를 선택해 주세요!**")
            lines.append(f"상태: 🟥 RED ({red_ready}) vs 🟦 BLUE ({blue_ready})")
        elif self.phase == "REVEALING":
            lines.append(f"{thinking_emoji} **두 선수 모두 패를 골랐습니다! 곧 결과를 공개합니다...**")

        return "\n".join(lines)

    def rebuild_items(self):
        self.clear_items()

        if self.phase == "SIDE_SELECT":
            red_label = (
                f"🟥 RED 참가 ({self.red_user.display_name})"
                if self.red_user
                else "🟥 RED 진영 선택"
            )
            blue_label = (
                f"🟦 BLUE 참가 ({self.blue_user.display_name})"
                if self.blue_user
                else "🟦 BLUE 진영 선택"
            )

            red_btn = discord.ui.Button(
                label=red_label,
                style=discord.ButtonStyle.danger if not self.red_user else discord.ButtonStyle.secondary,
                row=0,
            )
            red_btn.callback = self.select_red_callback
            self.add_item(red_btn)

            blue_btn = discord.ui.Button(
                label=blue_label,
                style=discord.ButtonStyle.primary if not self.blue_user else discord.ButtonStyle.secondary,
                row=0,
            )
            blue_btn.callback = self.select_blue_callback
            self.add_item(blue_btn)

            cancel_btn = discord.ui.Button(
                label="✖️ 취소",
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            cancel_btn.callback = self.cancel_callback
            self.add_item(cancel_btn)

        elif self.phase == "PICK":
            for key, info in RPS_CHOICES.items():
                btn = discord.ui.Button(
                    label=f"{info['emoji']} {info['label']}",
                    style=discord.ButtonStyle.primary,
                    row=0,
                )
                btn.callback = self._make_pick_callback(key)
                self.add_item(btn)

        elif self.phase == "DONE":
            rematch_btn = discord.ui.Button(
                label="🔄 같은 진영으로 재대결",
                style=discord.ButtonStyle.success,
                row=0,
            )
            rematch_btn.callback = self.rematch_callback
            self.add_item(rematch_btn)

    async def select_red_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        user = interaction.user

        if self.red_user and self.red_user.id == user.id:
            self.red_user = None
        elif self.blue_user and self.blue_user.id == user.id:
            await interaction.response.send_message(
                f"{lose_emoji} 이미 🟦 **BLUE 진영**을 선택하셨습니다! 한 사람이 두 진영을 동시에 선택할 수 없습니다.",
                ephemeral=True,
            )
            return
        elif self.red_user is not None:
            await interaction.response.send_message(
                f"{lose_emoji} 이미 <@{self.red_user.id}> 님이 🟥 **RED 진영**을 선택했습니다.",
                ephemeral=True,
            )
            return
        else:
            self.red_user = user

        if self.red_user and self.blue_user:
            self.phase = "PICK"

        self.rebuild_items()
        await interaction.response.edit_message(
            content=self.format_status_message(),
            view=self,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def select_blue_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        user = interaction.user

        if self.blue_user and self.blue_user.id == user.id:
            self.blue_user = None
        elif self.red_user and self.red_user.id == user.id:
            await interaction.response.send_message(
                f"{lose_emoji} 이미 🟥 **RED 진영**을 선택하셨습니다! 한 사람이 두 진영을 동시에 선택할 수 없습니다.",
                ephemeral=True,
            )
            return
        elif self.blue_user is not None:
            await interaction.response.send_message(
                f"{lose_emoji} 이미 <@{self.blue_user.id}> 님이 🟦 **BLUE 진영**을 선택했습니다.",
                ephemeral=True,
            )
            return
        else:
            self.blue_user = user

        if self.red_user and self.blue_user:
            self.phase = "PICK"

        self.rebuild_items()
        await interaction.response.edit_message(
            content=self.format_status_message(),
            view=self,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def cancel_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "🛑")
        if interaction.user.id not in {
            self.host_user.id,
            getattr(self.red_user, "id", 0),
            getattr(self.blue_user, "id", 0),
        }:
            await interaction.response.send_message(
                f"{lose_emoji} 가위바위보 생성자 또는 참가자만 취소할 수 있습니다.",
                ephemeral=True,
            )
            return
        self.stop()
        await interaction.response.edit_message(
            content=f"{lose_emoji} 가위바위보가 취소되었습니다.",
            view=None,
        )

    def _make_pick_callback(self, choice_key: str):
        async def _callback(interaction: discord.Interaction):
            if self.phase != "PICK":
                await interaction.response.defer()
                return

            lose_emoji = get_custom_emoji("ALose", "❌")
            thinking_emoji = get_custom_emoji("AThinking", "⏳")
            win_emoji = get_custom_emoji("AWin", "🏆")
            playing_emoji = get_custom_emoji("APlaying", "⚡")

            uid = interaction.user.id
            if self.red_user and uid == self.red_user.id:
                side = "RED"
            elif self.blue_user and uid == self.blue_user.id:
                side = "BLUE"
            else:
                await interaction.response.send_message(
                    f"{lose_emoji} 참가 중인 두 선수(RED / BLUE)만 패를 선택할 수 있습니다!",
                    ephemeral=True,
                )
                return

            self.picks[side] = choice_key
            choice_info = RPS_CHOICES[choice_key]

            if len(self.picks) < 2:
                await interaction.response.edit_message(
                    content=self.format_status_message(),
                    view=self,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
                await interaction.followup.send(
                    f"{thinking_emoji} 패 선택 완료: **{choice_info['emoji']} {choice_info['label']}** (상대방의 선택을 기다리는 중입니다)",
                    ephemeral=True,
                )
                return

            self.phase = "REVEALING"
            self.clear_items()
            await interaction.response.defer()

            if interaction.message is not None:
                try:
                    await interaction.message.delete()
                except Exception:
                    pass

            channel = interaction.channel
            if channel is not None:
                for count_num in (3, 2, 1):
                    try:
                        temp_msg = await channel.send(
                            f"{thinking_emoji} **가위바위보 공개 {count_num}...**"
                        )
                        await asyncio.sleep(0.5)
                        await temp_msg.delete()
                    except Exception:
                        await asyncio.sleep(0.4)

            red_pick_key = self.picks["RED"]
            blue_pick_key = self.picks["BLUE"]
            red_pick = RPS_CHOICES[red_pick_key]
            blue_pick = RPS_CHOICES[blue_pick_key]

            if red_pick_key == blue_pick_key:
                result_line = f"{thinking_emoji} **무승부입니다!** 아래 버튼을 눌러 바로 재대결할 수 있습니다."
                self.phase = "DONE"
                self.rebuild_items()
                next_view = self
            elif red_pick["beats"] == blue_pick_key:
                result_line = f"{win_emoji} **승리! 🟥 RED 진영 (<@{self.red_user.id}>)**"
                self.phase = "DONE"
                self.stop()
                next_view = None
            else:
                result_line = f"{win_emoji} **승리! 🟦 BLUE 진영 (<@{self.blue_user.id}>)**"
                self.phase = "DONE"
                self.stop()
                next_view = None

            final_lines = [
                f"{playing_emoji} **가위바위보 결과 공개!**",
                "",
                f"🟥 **RED (<@{self.red_user.id}>)**: {red_pick['emoji']} **{red_pick['label']}**",
                "⚡ **VS** ⚡",
                f"🟦 **BLUE (<@{self.blue_user.id}>)**: {blue_pick['emoji']} **{blue_pick['label']}**",
                "",
                result_line,
            ]
            final_text = "\n".join(final_lines)

            if channel is not None:
                send_kwargs = {
                    "content": final_text,
                    "allowed_mentions": discord.AllowedMentions(users=True),
                }
                if next_view is not None:
                    send_kwargs["view"] = next_view
                await channel.send(**send_kwargs)
            else:
                await interaction.followup.send(
                    content=final_text,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )

        return _callback

    async def rematch_callback(self, interaction: discord.Interaction):
        lose_emoji = get_custom_emoji("ALose", "❌")
        if interaction.user.id not in {
            getattr(self.red_user, "id", 0),
            getattr(self.blue_user, "id", 0),
            self.host_user.id,
        }:
            await interaction.response.send_message(
                f"{lose_emoji} 참가 중인 선수 또는 주최자만 재대결을 시작할 수 있습니다.",
                ephemeral=True,
            )
            return

        self.picks.clear()
        self.phase = "PICK"
        self.rebuild_items()
        await interaction.response.edit_message(
            content=self.format_status_message(),
            view=self,
            allowed_mentions=discord.AllowedMentions(users=True),
        )


def register_minigame_commands(bot) -> None:
    """bot.py에서 호출하여 /rps 와 /dice 슬래시 명령어를 등록합니다."""

    @bot.command_tree.command(
        name="rps",
        description="RED / BLUE 두 진영 대표가 가위바위보로 진영이나 선공을 결정합니다.",
    )
    async def rps_command(interaction: discord.Interaction):
        view = RPSGameView(host_user=interaction.user)
        await interaction.response.send_message(
            content=view.format_status_message(),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @bot.command_tree.command(
        name="dice",
        description="1에서 6 사이의 주사위를 굴립니다. (누구나 사용 가능)",
    )
    async def dice_command(interaction: discord.Interaction):
        await interaction.response.defer()

        thinking_emoji = get_custom_emoji("AThinking", "🎲")
        texts = [item[0] for item in DICE_ROLLING_TEXTS]
        weights = [item[1] for item in DICE_ROLLING_TEXTS]
        selected_rolling_text = random.choices(texts, weights=weights, k=1)[0]

        if not selected_rolling_text.startswith("✨"):
            rolling_line = f"{thinking_emoji} **{selected_rolling_text}**"
        else:
            rolling_line = selected_rolling_text

        channel = interaction.channel
        if channel is not None:
            try:
                temp_msg = await channel.send(rolling_line)
                await asyncio.sleep(1.6)
                await temp_msg.delete()
            except Exception:
                await asyncio.sleep(1.3)

        rolled = random.randint(1, 6)
        dice_emoji = get_custom_emoji(f"Dice{rolled}", f"🎲({rolled})")

        result_text = (
            f"<@{interaction.user.id}> 님이 주사위를 굴렸습니다!\n"
            f"결과: {dice_emoji} **{rolled}**"
        )
        await interaction.followup.send(
            content=result_text,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
