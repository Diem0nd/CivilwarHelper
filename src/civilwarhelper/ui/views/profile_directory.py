import discord

from civilwarhelper.ui.formatting.profile import _format_short_position, format_compact_member_profile_line, format_single_member_profile_detail


class ProfileDirectorySelect(discord.ui.Select):
    def __init__(self, parent_view: "ProfileDirectoryView"):
        self.parent_view = parent_view
        game = parent_view.game
        start = parent_view.page * 24
        page_items = parent_view.items_with_names[start : start + 24]

        # 맨 위 전체보기 1칸 + 유저 최대 24명 (디스코드 25개 제한)
        options = [
            discord.SelectOption(
                label="📋 전체 등록 멤버 한눈에 보기",
                value="SHOW_ALL",
                description="현재 페이지의 모든 등록 멤버 프로필을 한 번에 출력합니다.",
                default=(parent_view.selected_user_id == "SHOW_ALL"),
            )
        ]

        for profile, disp_name in page_items:
            uid_str = str(profile["discord_user_id"])
            riot_id = f"{profile.get('riot_game_name', '')} #{profile.get('riot_tagline', '')}"
            custom_raw = (profile.get("custom_tier") or "").strip()
            actual_raw = (
                (profile.get("solo_tier") or profile.get("flex_tier") or "Unranked")
                if game == "lol"
                else (profile.get("competitive_tier") or "Unranked")
            )

            tier_preview = f"체감: {custom_raw}" if custom_raw else f"티어: {actual_raw}"
            pos_short = _format_short_position(profile.get("main_position"), game)

            options.append(
                discord.SelectOption(
                    label=f"{disp_name[:40]} ({pos_short})",
                    value=uid_str,
                    description=f"{tier_preview} | {riot_id}"[:100],
                    default=(parent_view.selected_user_id == uid_str),
                )
            )

        super().__init__(
            placeholder="🔍 조회할 서버원을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.selected_user_id = self.values[0]
        self.parent_view.rebuild_components()
        await interaction.response.edit_message(
            content=self.parent_view.render_content(),
            view=self.parent_view,
        )


class ProfileDirectoryPageButton(discord.ui.Button):
    def __init__(self, parent_view: "ProfileDirectoryView", direction: int):
        self.parent_view = parent_view
        self.direction = direction
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="◀ 이전 목록" if direction < 0 else "다음 목록 ▶",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.page += self.direction
        self.parent_view.rebuild_components()
        await interaction.response.edit_message(
            content=self.parent_view.render_content(),
            view=self.parent_view,
        )


class ProfileDirectoryView(discord.ui.View):
    def __init__(self, game: str, items_with_names: list[tuple[dict, str]]):
        super().__init__(timeout=300)
        self.game = game
        self.items_with_names = items_with_names
        self.page = 0
        self.selected_user_id: str | None = None
        self.rebuild_components()

    @property
    def max_page(self) -> int:
        return (len(self.items_with_names) - 1) // 24 if self.items_with_names else 0

    def rebuild_components(self) -> None:
        self.clear_items()
        self.add_item(ProfileDirectorySelect(self))

        if self.max_page > 0:
            prev_btn = ProfileDirectoryPageButton(self, -1)
            prev_btn.disabled = self.page <= 0
            next_btn = ProfileDirectoryPageButton(self, 1)
            next_btn.disabled = self.page >= self.max_page
            self.add_item(prev_btn)
            self.add_item(next_btn)

    def render_content(self) -> str:
        game_label = "League of Legends" if self.game == "lol" else "VALORANT"
        header = f"📋 **{game_label} 등록 프로필 조회** (총 {len(self.items_with_names)}명)"

        if self.selected_user_id is None:
            return f"{header}\n아래 드롭다운 메뉴에서 프로필을 확인할 서버원을 선택해 주세요."

        if self.selected_user_id == "SHOW_ALL":
            start = self.page * 24
            page_items = self.items_with_names[start : start + 24]
            lines = [header, ""] + [
                format_compact_member_profile_line(p, name, self.game)
                for p, name in page_items
            ]
            return "\n".join(lines)

        for profile, disp_name in self.items_with_names:
            if str(profile["discord_user_id"]) == self.selected_user_id:
                return f"{header}\n\n{format_single_member_profile_detail(profile, disp_name, self.game)}"

        return f"{header}\n❌ 선택한 유저의 프로필을 찾을 수 없습니다."
