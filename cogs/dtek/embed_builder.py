from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

import discord

from .constants import DTEK_REGIONS, STATUS_MARKERS, STATUS_CHARS
from .models import PowerStatus


class EmbedBuilder:
    @staticmethod
    def build_schedule_graph(schedule_blocks: List[Tuple[str, str, str]], current_time: datetime) -> str:
        if not schedule_blocks:
            return ""

        lines = []
        current_time_str = f"{current_time.hour:02d}:{current_time.minute:02d}"

        for start, end, status in schedule_blocks:
            status_label = {"yes": "Є", "no": "Немає", "maybe": "Можливо"}.get(status, status)
            prefix = STATUS_CHARS.get(status, " ")

            is_current = start <= current_time_str < end
            marker = " <" if is_current else ""

            lines.append(f"{prefix} {start}-{end} {status_label}{marker}")

        return "```diff\n" + "\n".join(lines) + "\n```"

    @staticmethod
    def get_status_marker(status: str) -> str:
        return STATUS_MARKERS.get(status, "[?]")

    @staticmethod
    def get_next_change_info(status: PowerStatus) -> str:
        if not status.next_change or not status.next_change_status:
            return ""

        action = "Вимкнення" if status.next_change_status in ("no", "maybe") else "Увімкнення"
        return f"\n{action} о **{status.next_change}**"

    @classmethod
    def build_status_embed(cls, statuses: List[PowerStatus]) -> discord.Embed:
        overall_status = "yes"
        for status in statuses:
            if status.current_status == "error":
                overall_status = "error"
                break
            elif status.current_status == "no":
                overall_status = "no"
            elif status.current_status in ("maybe", "first", "second", "mfirst", "msecond") and overall_status == "yes":
                overall_status = "maybe"

        color_map = {
            "yes": discord.Color.from_rgb(87, 242, 135),
            "no": discord.Color.from_rgb(237, 66, 69),
            "maybe": discord.Color.from_rgb(254, 231, 92),
            "error": discord.Color.from_rgb(149, 165, 166),
        }

        embed = discord.Embed(
            title="Моніторинг електропостачання",
            color=color_map.get(overall_status, discord.Color.blue()),
            timestamp=datetime.now(timezone.utc),
        )

        now = datetime.now()

        for status in statuses:
            region_config = DTEK_REGIONS.get(status.address.region, DTEK_REGIONS["krem"])

            status_marker = cls.get_status_marker(status.current_status)

            header = f"{status_marker} {status.address.label}"

            field_parts = []

            if region_config.get("has_city", True):
                field_parts.append(f"{status.address.city}")
            field_parts.append(f"{status.address.street}, {status.address.house}")
            field_parts.append("")

            status_text = status.current_status_label
            if status.current_status == "yes":
                field_parts.append(f"```diff\n+ {status_text}\n```")
            elif status.current_status in ("no", "first", "second"):
                field_parts.append(f"```diff\n- {status_text}\n```")
            elif status.current_status in ("maybe", "mfirst", "msecond"):
                field_parts.append(f"```fix\n{status_text}\n```")
            else:
                field_parts.append(f"```\n{status_text}\n```")

            next_change_info = cls.get_next_change_info(status)
            if next_change_info:
                field_parts.append(next_change_info)

            if status.schedule_blocks:
                field_parts.append("")
                field_parts.append("**Графік на сьогодні:**")
                graph = cls.build_schedule_graph(status.schedule_blocks, now)
                field_parts.append(graph)

            if status.error:
                field_parts.append(f"\n**Помилка:** {status.error}")

            field_parts.append(f"\n`{region_config['short_name']}`")

            embed.add_field(
                name=header,
                value="\n".join(field_parts),
                inline=False,
            )

        embed.add_field(
            name="",
            value="━━━━━━━━━━━━━━━━━━━━━━━━━\n[+] Є світло | [-] Немає | [~] Можливе | < Зараз",
            inline=False,
        )

        embed.set_footer(
            text="Оновлено | Автооновлення кожні 15 хв",
            icon_url="https://www.dtek-krem.com.ua/favicon.ico"
        )

        return embed
