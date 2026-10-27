import asyncio
import logging

import discord

RPS_CHOICES = {
    "scissors": {"label": "가위", "emoji": "✌️", "beats": "paper"},
    "rock": {"label": "바위", "emoji": "✊", "beats": "scissors"},
    "paper": {"label": "보", "emoji": "🖐️", "beats": "rock"},
}


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
        red_text = f"<@{self.red_user.id}>" if self.red_user else "*대기 중...*"
        blue_text = f"<@{self.blue_user.id}>" if self.blue_user else "*대기 중...*"

        lines = [
            "✊✌️🖐️ **진영 / 선공 결정 가위바위보**",
            f"🟥 **RED 진영**: {red_text}",
            f"🟦 **BLUE 진영**: {blue_text}",
            "",
        ]

        if self.phase == "SIDE_SELECT":
            lines.append("👉 각 진영 대표 1명씩 아래 버튼을 눌러 참가해 주세요! (두 명이 모이면 바로 시작됩니다)")
        elif self.phase == "PICK":
            red_ready = "✅ 선택 완료" if "RED" in self.picks else "⏳ 고민 중..."
            blue_ready = "✅ 선택 완료" if "BLUE" in self.picks else "⏳ 고민 중..."
            lines.append("🔥 **두 진영 참가 완료! 아래에서 가위, 바위, 보 중 하나를 선택해 주세요!**")
            lines.append(f"상태: 🟥 RED ({red_ready}) vs 🟦 BLUE ({blue_ready})")
        elif self.phase == "REVEALING":
            lines.append("🥁 **두 선수 모두 패를 골랐습니다! 곧 결과를 공개합니다...**")

        return "\n".join(lines)

    def rebuild_items(self):
        self.clear_items()

        if self.phase == "SIDE_SELECT":
            red_label = f"🟥 RED 참가 ({self.red_user.display_name})" if self.red_user else "🟥 RED 진영 선택"
            blue_label = f"🟦 BLUE 참가 ({self.blue_user.display_name})" if self.blue_user else "🟦 BLUE 진영 선택"

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

            cancel_btn = discord.ui.Button(label="✖️ 취소", style=discord.ButtonStyle.secondary, row=0)
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
        user = interaction.user
        if self.red_user and self.red_user.id == user.id:
            self.red_user = None
        elif self.blue_user and self.blue_user.id == user.id:
            await interaction.response.send_message(
                "이미 🟦 **BLUE 진영**을 선택하셨습니다! 한 사람이 두 진영을 동시에 선택할 수 없습니다.",
                ephemeral=True,
            )
            return
        elif self.red_user is not None:
            await interaction.response.send_message(
                f"이미 <@{self.red_user.id}> 님이 🟥 **RED 진영**을 선택했습니다.",
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
        user = interaction.user
        if self.blue_user and self.blue_user.id == user.id:
            self.blue_user = None
        elif self.red_user and self.red_user.id == user.id:
            await interaction.response.send_message(
                "이미 🟥 **RED 진영**을 선택하셨습니다! 한 사람이 두 진영을 동시에 선택할 수 없습니다.",
                ephemeral=True,
            )
            return
        elif self.blue_user is not None:
            await interaction.response.send_message(
                f"이미 <@{self.blue_user.id}> 님이 🟦 **BLUE 진영**을 선택했습니다.",
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
        allowed = {self.host_user.id, getattr(self.red_user, "id", 0), getattr(self.blue_user, "id", 0)}
        if interaction.user.id not in allowed:
            await interaction.response.send_message("가위바위보 생성자 또는 참가자만 취소할 수 있습니다.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="🛑 가위바위보가 취소되었습니다.", view=None)

    def _make_pick_callback(self, choice_key: str):
        async def _callback(interaction: discord.Interaction):
            if self.phase != "PICK":
                await interaction.response.defer()
                return

            uid = interaction.user.id
            if self.red_user and uid == self.red_user.id:
                side = "RED"
            elif self.blue_user and uid == self.blue_user.id:
                side = "BLUE"
            else:
                await interaction.response.send_message(
                    "참가 중인 두 선수(RED / BLUE)만 패를 선택할 수 있습니다!",
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
                    f"패 선택 완료: **{choice_info['emoji']} {choice_info['label']}** (상대방의 선택을 기다리는 중입니다)",
                    ephemeral=True,
                )
                return

            # 둘 다 골랐으면 기존 메시지 지우고 카운트다운 후 결과 출력
            self.phase = "REVEALING"
            self.clear_items()
            await interaction.response.defer()

            if interaction.message is not None:
                try:
                    await interaction.message.delete()
                except discord.HTTPException as e:
                    logging.debug("가위바위보 메시지 삭제 실패: %s", e)

            channel = interaction.channel
            if channel is not None:
                for n in (3, 2, 1):
                    try:
                        tmp = await channel.send(f"⏳ **가위바위보 공개 {n}...**")
                        await asyncio.sleep(0.5)
                        await tmp.delete()
                    except discord.HTTPException as e:
                        logging.debug("카운트다운 메시지 처리 실패: %s", e)
                        await asyncio.sleep(0.4)

            red_key, blue_key = self.picks["RED"], self.picks["BLUE"]
            red_pick, blue_pick = RPS_CHOICES[red_key], RPS_CHOICES[blue_key]

            if red_key == blue_key:
                self.picks.clear()
                self.phase = "PICK"
                self.rebuild_items()
                result_line = (
                    "🤝 **무승부입니다! 바로 다시 승부를 가립니다!**\n"
                    "🔥 **아래에서 가위, 바위, 보 중 하나를 다시 선택해 주세요!**\n"
                    "상태: 🟥 RED (⏳ 고민 중...) vs 🟦 BLUE (⏳ 고민 중...)"
                )
                next_view = self
            elif red_pick["beats"] == blue_key:
                result_line = f"승리! **🟥 RED 진영 (<@{self.red_user.id}>)**"
                self.phase = "DONE"
                self.stop()
                next_view = None
            else:
                result_line = f"승리! **🟦 BLUE 진영 (<@{self.blue_user.id}>)**"
                self.phase = "DONE"
                self.stop()
                next_view = None

            final_text = "\n".join([
                "✊✌️🖐️ **가위바위보 결과 공개!**",
                "",
                f"🟥 **RED (<@{self.red_user.id}>)**: {red_pick['emoji']} **{red_pick['label']}**",
                "⚡ **VS** ⚡",
                f"🟦 **BLUE (<@{self.blue_user.id}>)**: {blue_pick['emoji']} **{blue_pick['label']}**",
                "",
                result_line,
            ])

            if channel is not None:
                kwargs: dict = {
                    "content": final_text,
                    "allowed_mentions": discord.AllowedMentions(users=True),
                }
                if next_view is not None:
                    kwargs["view"] = next_view
                await channel.send(**kwargs)
            else:
                await interaction.followup.send(
                    content=final_text,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )

        return _callback

    async def rematch_callback(self, interaction: discord.Interaction):
        allowed = {getattr(self.red_user, "id", 0), getattr(self.blue_user, "id", 0), self.host_user.id}
        if interaction.user.id not in allowed:
            await interaction.response.send_message(
                "참가 중인 선수 또는 주최자만 재대결을 시작할 수 있습니다.",
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
