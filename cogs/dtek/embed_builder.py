from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from zoneinfo import ZoneInfo

import discord

from .constants import DTEK_REGIONS, STATUS_MARKERS, STATUS_CHARS
from .models import PowerStatus


class EmbedBuilder:
    DIVIDER = "─" * 32
    DIVIDER_THIN = "┄" * 28
    KYIV_TZ = ZoneInfo("Europe/Kyiv")

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
            marker = "  <<" if is_current else ""

            time_range = f"{start} - {end}"
            lines.append(f"{prefix} {time_range:<13} {status_label}{marker}")

        return "```diff\n" + "\n".join(lines) + "\n```"

    @staticmethod
    def get_status_marker(status: str) -> str:
        return STATUS_MARKERS.get(status, "[?]")

    @staticmethod
    def get_next_change_info(status: PowerStatus) -> str:
        if not status.next_change or not status.next_change_status:
            return ""

        action = "Вимкнення" if status.next_change_status in ("no", "maybe") else "Увімкнення"
        return f"Очікується: **{action}** о `{status.next_change}`"

    @classmethod
    def build_status_embed(cls, statuses: List[PowerStatus], target_date: Optional[datetime] = None) -> discord.Embed:
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
            "yes": discord.Color.from_rgb(67, 181, 129),
            "no": discord.Color.from_rgb(240, 71, 71),
            "maybe": discord.Color.from_rgb(250, 166, 26),
            "error": discord.Color.from_rgb(116, 127, 141),
        }

        if target_date:
            weekday_names = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
            weekday = weekday_names[target_date.weekday()]
            date_str = target_date.strftime("%d.%m")
            title = f"Прогноз на завтра ({weekday}, {date_str})"
        else:
            title = "Моніторинг електропостачання"

        embed = discord.Embed(
            title=title,
            color=color_map.get(overall_status, discord.Color.blue()),
            timestamp=datetime.now(timezone.utc),
        )

        if target_date:
            now = target_date.replace(hour=0, minute=0)
            is_tomorrow = True
        else:
            now = datetime.now(cls.KYIV_TZ)
            is_tomorrow = False

        for idx, status in enumerate(statuses):
            region_config = DTEK_REGIONS.get(status.address.region, DTEK_REGIONS["krem"])

            status_marker = cls.get_status_marker(status.current_status)

            header = f"{status_marker}  {status.address.label}"

            field_parts = []

            address_parts = []
            if region_config.get("has_city", True):
                address_parts.append(status.address.city)
            address_parts.append(f"{status.address.street}, {status.address.house}")
            field_parts.append(f"`{' / '.join(address_parts)}`")

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
                field_parts.append(f"\n**Графік на сьогодні**")
                graph = cls.build_schedule_graph(status.schedule_blocks, now)
                field_parts.append(graph)

            if status.error:
                field_parts.append(f"**Помилка:** `{status.error}`")

            if idx < len(statuses) - 1:
                field_parts.append(f"\n{cls.DIVIDER_THIN}")

            embed.add_field(
                name=header,
                value="\n".join(field_parts),
                inline=False,
            )

        legend = (
            f"```\n"
            f"[+] Є світло    [-] Немає світла\n"
            f"[~] Можливе     <<  Поточний час\n"
            f"```"
        )

        embed.add_field(
            name=cls.DIVIDER,
            value=legend,
            inline=False,
        )

        if is_tomorrow:
            embed.set_footer(
                text="Прогноз може змінитися • Повернення до сьогодні через 15 хв",
                icon_url="https://www.dtek-krem.com.ua/favicon.ico"
            )
        else:
            embed.set_footer(
                text="Автооновлення кожні 15 хв",
                icon_url="https://www.dtek-krem.com.ua/favicon.ico"
            )

        return embed
