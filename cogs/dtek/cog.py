from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import discord
from discord.ext import commands, tasks

from utils.database import Database

from .constants import DTEK_REGIONS
from .models import AddressConfig, PowerStatus, ValidationException
from .scraper_service import ScraperService
from .embed_builder import EmbedBuilder

logger = logging.getLogger("dtek_cog")


class DTEKMonitor(commands.Cog):
    dtek = discord.SlashCommandGroup(
        name="dtek",
        description="DTEK power shutdown monitoring",
    )

    def __init__(self, bot: commands.Bot):
        logger.info("DTEKMonitor cog initializing...")
        self.bot = bot
        self.db = Database()
        self.scraper_service = ScraperService()
        self.embed_builder = EmbedBuilder()
        self._addresses: List[AddressConfig] = []
        self._status_cache: Dict[int, PowerStatus] = {}
        self._last_successful_iteration: Optional[datetime] = None
        logger.info("Starting update_task loop...")
        self.update_task.start()
        self.health_check_task.start()
        logger.info(f"DTEKMonitor cog initialized. Commands in group: {[cmd.name for cmd in self.dtek.walk_commands()]}")

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"DTEKMonitor on_ready fired. Bot guilds: {len(self.bot.guilds)}")
        logger.info(f"Registered application commands: {[cmd.name for cmd in self.bot.pending_application_commands]}")

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx: discord.ApplicationContext, error: Exception):
        if ctx.command and ctx.command.cog != self:
            return
        
        logger.error(f"Slash command error in {ctx.command.name if ctx.command else 'unknown'}: {error}", exc_info=True)
        
        try:
            if ctx.response.is_done():
                await ctx.followup.send(f":x: Помилка: {error}", ephemeral=True)
            else:
                await ctx.respond(f":x: Помилка: {error}", ephemeral=True)
        except discord.HTTPException as e:
            logger.warning(f"Failed to send error response: {e}")

    def cog_unload(self):
        logger.info("DTEKMonitor cog unloading, cancelling tasks...")
        self.update_task.cancel()
        self.health_check_task.cancel()
        logger.info("DTEKMonitor cog unloaded.")

    @tasks.loop(minutes=5)
    async def health_check_task(self):
        is_running = self.update_task.is_running()
        next_iter = self.update_task.next_iteration
        failed = self.update_task.failed()

        logger.debug(
            f"Health check: update_task running={is_running}, "
            f"next_iteration={next_iter}, failed={failed}, "
            f"last_success={self._last_successful_iteration}"
        )

        if not is_running and not self.update_task.is_being_cancelled():
            logger.warning("Update task is not running! Attempting to restart...")
            try:
                self.scraper_service.clear_cache()
                self.scraper_service.clear_scrapers()
                self.update_task.start()
                logger.info("Update task restarted by health check.")
            except Exception as e:
                logger.exception(f"Failed to restart update task in health check: {e}")

    @health_check_task.before_loop
    async def before_health_check(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(60)

    @tasks.loop(minutes=15, reconnect=True)
    async def update_task(self):
        logger.info(f"DTEK update task iteration #{self.update_task.current_loop} starting... (next: {self.update_task.next_iteration})")
        try:
            await self._load_addresses()

            self.scraper_service.clear_cache()

            unique_regions = set(addr.region for addr in self._addresses)
            for region in unique_regions:
                try:
                    await self.scraper_service.fetch_schedule_data(region)
                except Exception as e:
                    logger.error(f"Failed to fetch schedule data for region {region}: {e}")

            by_channel: Dict[int, List[AddressConfig]] = {}
            for addr in self._addresses:
                if addr.channel_id not in by_channel:
                    by_channel[addr.channel_id] = []
                by_channel[addr.channel_id].append(addr)

            for channel_id, addresses in by_channel.items():
                await self._update_status_message(channel_id, addresses)
                await asyncio.sleep(2)

            self._last_successful_iteration = datetime.now(timezone.utc)
            logger.info(f"DTEK update task iteration #{self.update_task.current_loop} completed successfully. Next iteration: {self.update_task.next_iteration}")

        except asyncio.CancelledError:
            logger.warning(f"DTEK update task iteration #{self.update_task.current_loop} was cancelled")
            raise
        except Exception as e:
            logger.exception(f"Error in update task iteration #{self.update_task.current_loop}: {e}")

    @update_task.before_loop
    async def before_update_task(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)
        logger.info("DTEK update task starting...")

    @update_task.after_loop
    async def after_update_task(self):
        logger.warning(
            f"DTEK update task stopped. "
            f"Is being cancelled: {self.update_task.is_being_cancelled()}, "
            f"Failed: {self.update_task.failed()}, "
            f"Current loop count: {self.update_task.current_loop}"
        )
        if self.update_task.failed():
            task = self.update_task.get_task()
            exc_info = task.exception() if task and task.done() else 'N/A'
            logger.error(f"Task failure exception: {exc_info}")
            if not self.update_task.is_being_cancelled():
                logger.info("Attempting to restart DTEK update task in 60 seconds...")
                await asyncio.sleep(60)
                if not self.update_task.is_running():
                    try:
                        self.update_task.start()
                        logger.info("DTEK update task restarted successfully.")
                    except Exception as e:
                        logger.exception(f"Failed to restart DTEK update task: {e}")

    @update_task.error
    async def update_task_error(self, error: BaseException):
        logger.exception(f"DTEK update task encountered an error: {error}")

    async def _load_addresses(self):
        addresses = await self.db.get_dtek_addresses()
        self._addresses = [
            AddressConfig(
                id=addr["id"],
                region=addr["region"],
                city=addr["city"],
                street=addr["street"],
                house=addr["house"],
                label=addr["label"],
                guild_id=addr["guild_id"],
                channel_id=addr["channel_id"],
                message_id=addr.get("message_id"),
            )
            for addr in addresses
        ]

    async def _get_power_status(self, address: AddressConfig) -> PowerStatus:
        try:
            cache = self.scraper_service.get_cache(address.region)
            if not cache:
                await self.scraper_service.fetch_schedule_data(address.region)
                cache = self.scraper_service.get_cache(address.region)

            if not cache:
                raise ValueError(f"Failed to fetch schedule data for region {address.region}")

            queue = await self.scraper_service.lookup_queue(
                address.region,
                address.city,
                address.street,
                address.house,
            )
            logger.info(f"Resolved queue for {address.label}: {queue}")

            current_status, status_label, schedule_blocks, next_change, next_change_status, hourly_schedule = self.scraper_service.get_current_status(
                cache.fact,
                queue,
            )

            return PowerStatus(
                address=address,
                current_status=current_status,
                current_status_label=status_label,
                schedule_blocks=schedule_blocks,
                next_change=next_change,
                next_change_status=next_change_status,
                hourly_schedule=hourly_schedule,
                last_update=datetime.now(timezone.utc),
            )

        except Exception as e:
            logger.error(f"Error getting power status for {address.label}: {e}")
            return PowerStatus(
                address=address,
                current_status="error",
                current_status_label="Помилка",
                error=str(e),
                last_update=datetime.now(timezone.utc),
            )

    async def _update_status_message(self, channel_id: int, addresses: List[AddressConfig]):
        if not addresses:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            logger.warning(f"Channel {channel_id} not found or not a text channel")
            return

        statuses = []
        for addr in addresses:
            status = await self._get_power_status(addr)
            statuses.append(status)
            self._status_cache[addr.id] = status

        embed = self.embed_builder.build_status_embed(statuses)

        message_id = addresses[0].message_id

        try:
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(embed=embed)
                    return
                except discord.NotFound:
                    pass

            message = await channel.send(embed=embed)

            for addr in addresses:
                await self.db.update_dtek_message_id(addr.id, message.id)
                addr.message_id = message.id

        except discord.Forbidden:
            logger.error(f"No permission to send/edit in channel {channel_id}")
        except Exception as e:
            logger.error(f"Error updating status message: {e}")

    async def _label_autocomplete(self, ctx: discord.AutocompleteContext) -> List[str]:
        try:
            if not ctx.interaction.guild_id:
                return []
            addresses = await self.db.get_dtek_addresses_for_guild(ctx.interaction.guild_id)
            labels = [addr["label"] for addr in addresses]
            if ctx.value:
                labels = [l for l in labels if ctx.value.lower() in l.lower()]
            return labels[:25]
        except Exception as e:
            logger.error(f"Error in label autocomplete: {e}")
            return []

    @dtek.command(name="add_address", description="Add an address to monitor")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def add_address(
        self,
        ctx: discord.ApplicationContext,
        region: str = discord.Option(
            description="DTEK region",
            choices=[
                discord.OptionChoice(name="ДТЕК КРЕМ (Київська область)", value="krem"),
                discord.OptionChoice(name="ДТЕК КЕМ (м. Київ)", value="kem"),
            ],
        ),
        street: str = discord.Option(description="Street in Ukrainian (e.g. 'вул. Васильківська')"),
        house: str = discord.Option(description="House number (e.g. '9Г')"),
        label: str = discord.Option(description="Friendly name for display"),
        city: Optional[str] = discord.Option(description="КРЕМ: City (required) | КЕМ: Not needed", required=False, default=None),
        channel: Optional[discord.TextChannel] = discord.Option(description="Channel to post updates", required=False, default=None),
    ):
        logger.info(f"add_address command started by {ctx.author} (ID: {ctx.author.id}) in guild {ctx.guild_id}")
        try:
            await asyncio.wait_for(ctx.defer(ephemeral=True), timeout=5.0)
            logger.info(f"add_address deferred successfully for {ctx.author}")
        except asyncio.TimeoutError:
            logger.error(f"add_address defer() timed out for {ctx.author}")
            return
        except Exception as e:
            logger.exception(f"add_address defer() failed for {ctx.author}: {e}")
            return

        if not ctx.guild:
            await ctx.respond(":x: Ця команда доступна лише на сервері.", ephemeral=True)
            return

        region_config = DTEK_REGIONS.get(region, DTEK_REGIONS["krem"])
        if region_config.get("has_city", True) and not city:
            await ctx.respond(
                ":x: Для регіону **ДТЕК КРЕМ** потрібно вказати місто (параметр `city`).\n"
                "Приклад: `с. Велика Солтанівка`",
                ephemeral=True,
            )
            return

        actual_city = city if city else ""
        target_channel = channel or ctx.channel

        try:
            logger.debug(f"Fetching schedule data for region {region}...")
            await self.scraper_service.fetch_schedule_data(region)
            logger.debug(f"Looking up queue for {actual_city}, {street}, {house}...")
            queue = await self.scraper_service.lookup_queue(region, actual_city, street, house)
            logger.debug(f"Queue lookup result: {queue}")

            addr_id = await self.db.add_dtek_address(
                region=region,
                city=actual_city,
                street=street,
                house=house,
                label=label,
                guild_id=ctx.guild.id,
                channel_id=target_channel.id,
            )

            if region_config.get("has_city", True):
                location_str = f"{actual_city}, {street}, {house}"
            else:
                location_str = f"{actual_city}, {street}, {house}" if actual_city else f"{street}, {house}"

            await ctx.respond(
                f":white_check_mark: Адресу **{label}** додано!\n"
                f":round_pushpin: {location_str}\n"
                f":tv: Канал: {target_channel.mention}\n"
                f":electric_plug: Черга відключень: `{queue}`",
                ephemeral=True,
            )

            await self._load_addresses()
            addresses = [a for a in self._addresses if a.channel_id == target_channel.id]
            await self._update_status_message(target_channel.id, addresses)
            logger.info(f"add_address command completed successfully for {ctx.author}")

        except ValidationException as e:
            logger.warning(f"add_address validation error for {ctx.author}: {e}")
            await ctx.respond(f":x: Помилка валідації адреси: {e}", ephemeral=True)
        except Exception as e:
            logger.exception(f"Error adding address: {e}")
            await ctx.respond(f":x: Помилка: {e}", ephemeral=True)

    @dtek.command(name="remove_address", description="Remove a monitored address")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def remove_address(
        self,
        ctx: discord.ApplicationContext,
        label: str = discord.Option(description="Label of the address to remove", autocomplete=_label_autocomplete),
    ):
        await ctx.defer(ephemeral=True)

        if not ctx.guild:
            await ctx.respond(":x: Ця команда доступна лише на сервері.", ephemeral=True)
            return

        try:
            deleted = await self.db.remove_dtek_address(ctx.guild.id, label)

            if deleted:
                await ctx.respond(f":white_check_mark: Адресу **{label}** видалено!", ephemeral=True)
            else:
                await ctx.respond(f":x: Адресу **{label}** не знайдено.", ephemeral=True)

        except Exception as e:
            logger.exception(f"Error removing address: {e}")
            await ctx.respond(f":x: Помилка: {e}", ephemeral=True)

    @dtek.command(name="list_addresses", description="List monitored addresses")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def list_addresses(self, ctx: discord.ApplicationContext):
        logger.info(f"list_addresses command started by {ctx.author} (ID: {ctx.author.id}) in guild {ctx.guild_id}")
        try:
            await asyncio.wait_for(ctx.defer(ephemeral=True), timeout=5.0)
            logger.info(f"list_addresses deferred successfully for {ctx.author}")
        except asyncio.TimeoutError:
            logger.error(f"list_addresses defer() timed out for {ctx.author}")
            return
        except Exception as e:
            logger.exception(f"list_addresses defer() failed for {ctx.author}: {e}")
            return

        if not ctx.guild:
            await ctx.respond(":x: Ця команда доступна лише на сервері.", ephemeral=True)
            return

        try:
            addresses = await self.db.get_dtek_addresses_for_guild(ctx.guild.id)

            if not addresses:
                await ctx.respond(":mailbox_with_no_mail: Немає моніторингових адрес.", ephemeral=True)
                return

            embed = discord.Embed(
                title=":round_pushpin: Моніторингові адреси",
                color=discord.Color.blue(),
                description="Дані в базі (city | street | house):",
            )

            for addr in addresses:
                region_config = DTEK_REGIONS.get(addr["region"], DTEK_REGIONS["krem"])
                channel = self.bot.get_channel(addr["channel_id"])
                channel_mention = channel.mention if isinstance(channel, discord.TextChannel) else f"#{addr['channel_id']}"

                city_label = "Місто" if region_config.get("has_city", True) else "Район"

                embed.add_field(
                    name=f"{addr['label']} (ID: {addr['id']})",
                    value=(
                        f":office: {region_config['short_name']}\n"
                        f":cityscape: {city_label}: `{addr['city']}`\n"
                        f":motorway: Вулиця: `{addr['street']}`\n"
                        f":house: Будинок: `{addr['house']}`\n"
                        f":tv: {channel_mention}"
                    ),
                    inline=False,
                )

            await ctx.respond(embed=embed, ephemeral=True)
            logger.info(f"list_addresses command completed successfully for {ctx.author}")

        except Exception as e:
            logger.exception(f"Error listing addresses for {ctx.author}: {e}")
            await ctx.respond(f":x: Помилка: {e}", ephemeral=True)

    @dtek.command(name="refresh", description="Force refresh power status")
    @commands.has_permissions(administrator=True)
    async def refresh(self, ctx: discord.ApplicationContext):
        logger.info(f"refresh command started by {ctx.author} (ID: {ctx.author.id}) in guild {ctx.guild_id}")
        try:
            await asyncio.wait_for(ctx.defer(ephemeral=True), timeout=5.0)
            logger.info(f"refresh deferred successfully for {ctx.author}")
        except asyncio.TimeoutError:
            logger.error(f"refresh defer() timed out for {ctx.author}")
            return
        except Exception as e:
            logger.exception(f"refresh defer() failed for {ctx.author}: {e}")
            return

        try:
            self.scraper_service.clear_cache()
            await self._load_addresses()

            by_channel: Dict[int, List[AddressConfig]] = {}
            for addr in self._addresses:
                if addr.guild_id != ctx.guild.id:
                    continue
                if addr.channel_id not in by_channel:
                    by_channel[addr.channel_id] = []
                by_channel[addr.channel_id].append(addr)

            for channel_id, addresses in by_channel.items():
                await self._update_status_message(channel_id, addresses)

            await ctx.respond(":white_check_mark: Статус оновлено!", ephemeral=True)
            logger.info(f"refresh command completed successfully for {ctx.author}")

        except Exception as e:
            logger.exception(f"Error refreshing for {ctx.author}: {e}")
            await ctx.respond(f":x: Помилка: {e}", ephemeral=True)

    @dtek.command(name="status", description="Show current power status for all addresses")
    @commands.has_permissions(administrator=True)
    async def status(self, ctx: discord.ApplicationContext):
        logger.info(f"status command started by {ctx.author} (ID: {ctx.author.id}) in guild {ctx.guild_id}")
        try:
            await asyncio.wait_for(ctx.defer(), timeout=5.0)
            logger.info(f"status deferred successfully for {ctx.author}")
        except asyncio.TimeoutError:
            logger.error(f"status defer() timed out for {ctx.author}")
            return
        except Exception as e:
            logger.exception(f"status defer() failed for {ctx.author}: {e}")
            return

        try:
            await self._load_addresses()
            guild_addresses = [a for a in self._addresses if a.guild_id == ctx.guild.id]

            if not guild_addresses:
                await ctx.respond(":mailbox_with_no_mail: Немає моніторингових адрес. Додайте через `/dtek add_address`")
                return

            statuses = []
            for addr in guild_addresses:
                status = await self._get_power_status(addr)
                statuses.append(status)

            embed = self.embed_builder.build_status_embed(statuses)
            await ctx.respond(embed=embed)
            logger.info(f"status command completed successfully for {ctx.author}")

        except Exception as e:
            logger.exception(f"Error getting status for {ctx.author}: {e}")
            await ctx.respond(f":x: Помилка: {e}")

    @dtek.command(name="set_channel", description="Change the channel where status updates are displayed")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def set_channel(
        self,
        ctx: discord.ApplicationContext,
        label: str = discord.Option(description="Label of the address to update", autocomplete=_label_autocomplete),
        channel: discord.TextChannel = discord.Option(description="New channel for status updates"),
    ):
        await ctx.defer(ephemeral=True)

        if not ctx.guild:
            await ctx.respond(":x: Ця команда доступна лише на сервері.", ephemeral=True)
            return

        try:
            addresses = await self.db.get_dtek_addresses_for_guild(ctx.guild.id)
            old_address = next((a for a in addresses if a["label"] == label), None)

            if not old_address:
                await ctx.respond(f":x: Адресу **{label}** не знайдено.", ephemeral=True)
                return

            old_channel_id = old_address["channel_id"]
            old_message_id = old_address.get("message_id")

            if old_message_id:
                try:
                    old_channel = self.bot.get_channel(old_channel_id)
                    if old_channel and isinstance(old_channel, discord.TextChannel):
                        old_message = await old_channel.fetch_message(old_message_id)
                        await old_message.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            updated = await self.db.update_dtek_address_channel(ctx.guild.id, label, channel.id)

            if updated:
                await ctx.respond(
                    f":white_check_mark: Канал для **{label}** змінено на {channel.mention}!",
                    ephemeral=True,
                )

                await self._load_addresses()
                new_addresses = [a for a in self._addresses if a.channel_id == channel.id]
                await self._update_status_message(channel.id, new_addresses)
            else:
                await ctx.respond(f":x: Не вдалося оновити канал для **{label}**.", ephemeral=True)

        except Exception as e:
            logger.exception(f"Error changing channel: {e}")
            await ctx.respond(f":x: Помилка: {e}", ephemeral=True)

    @dtek.command(name="task_status", description="Check the status of the automatic update task")
    @commands.has_permissions(administrator=True)
    async def task_status(self, ctx: discord.ApplicationContext):
        logger.info(f"task_status command invoked by {ctx.author} in guild {ctx.guild_id}")
        await ctx.defer(ephemeral=True)

        is_running = self.update_task.is_running()
        is_being_cancelled = self.update_task.is_being_cancelled()
        current_loop = self.update_task.current_loop
        next_iteration = self.update_task.next_iteration
        failed = self.update_task.failed()
        last_success = self._last_successful_iteration

        status_emoji = ":white_check_mark:" if is_running else ":x:"

        status_lines = [
            f"{status_emoji} **Статус задачі оновлення:**",
            f":gear: Запущена: `{is_running}`",
            f":no_entry_sign: Відміняється: `{is_being_cancelled}`",
            f":repeat: Ітерацій виконано: `{current_loop}`",
            f":clock1: Наступна ітерація: `{next_iteration.strftime('%Y-%m-%d %H:%M:%S UTC') if next_iteration else 'N/A'}`",
            f":white_check_mark: Остання успішна: `{last_success.strftime('%Y-%m-%d %H:%M:%S UTC') if last_success else 'N/A'}`",
            f":warning: Помилка: `{failed}`",
        ]

        if not is_running and not is_being_cancelled:
            status_lines.append("\n:wrench: Задача зупинена! Використайте `/dtek restart_task` для перезапуску.")

        await ctx.respond("\n".join(status_lines), ephemeral=True)

    @dtek.command(name="restart_task", description="Restart the automatic update task if it stopped")
    @commands.has_permissions(administrator=True)
    async def restart_task(self, ctx: discord.ApplicationContext):
        logger.info(f"restart_task command invoked by {ctx.author} in guild {ctx.guild_id}")
        await ctx.defer(ephemeral=True)

        if self.update_task.is_running():
            await ctx.respond(":information_source: Задача вже запущена.", ephemeral=True)
            return

        try:
            self.update_task.cancel()
            await asyncio.sleep(1)

            self.scraper_service.clear_cache()
            self.scraper_service.clear_scrapers()

            self.update_task.start()

            await ctx.respond(":white_check_mark: Задачу оновлення перезапущено!", ephemeral=True)
            logger.info("Update task manually restarted via command.")

        except Exception as e:
            logger.exception(f"Error restarting task: {e}")
            await ctx.respond(f":x: Помилка перезапуску: {e}", ephemeral=True)


def setup(bot: commands.Bot):
    logger.info("Setting up DTEKMonitor cog...")
    cog = DTEKMonitor(bot)
    bot.add_cog(cog)
    logger.info(f"DTEKMonitor cog added. Slash command group 'dtek' registered with commands: {[cmd.name for cmd in cog.dtek.walk_commands()]}")
