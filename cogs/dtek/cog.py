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
        logger.info(f"DTEKMonitor cog initialized")

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"[DTEK_COG] on_ready event fired")
        logger.info(f"[DTEK_COG] Bot user: {self.bot.user} (ID: {self.bot.user.id if self.bot.user else 'N/A'})")
        logger.info(f"[DTEK_COG] Bot guilds: {len(self.bot.guilds)}")
        logger.info(f"[DTEK_COG] Bot latency: {self.bot.latency * 1000:.2f}ms")
        logger.info(f"[DTEK_COG] Pending application commands: {[cmd.name for cmd in self.bot.pending_application_commands]}")

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx: discord.ApplicationContext, error: Exception):
        if ctx.command and ctx.command.cog != self:
            return

        logger.error(f"[DTEK_COG] Application command error in {ctx.command.name if ctx.command else 'unknown'}: {type(error).__name__}: {error}", exc_info=True)
        logger.error(f"[DTEK_COG] Error context - User: {ctx.author} (ID: {ctx.author.id}), Guild: {ctx.guild_id}, Channel: {ctx.channel_id}")
        logger.error(f"[DTEK_COG] Response state: is_done={ctx.response.is_done()}")

        try:
            if ctx.response.is_done():
                logger.debug(f"[DTEK_COG] Sending error via followup...")
                await ctx.followup.send(f":x: Помилка: {error}", ephemeral=True)
                logger.debug(f"[DTEK_COG] Error sent via followup")
            else:
                logger.debug(f"[DTEK_COG] Sending error via respond...")
                await ctx.respond(f":x: Помилка: {error}", ephemeral=True)
                logger.debug(f"[DTEK_COG] Error sent via respond")
        except discord.HTTPException as e:
            logger.exception(f"[DTEK_COG] CRITICAL: Failed to send error response: {e}, status={getattr(e, 'status', 'N/A')}")
        except Exception as e:
            logger.exception(f"[DTEK_COG] CRITICAL: Unexpected error sending error response: {type(e).__name__}: {e}")

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
        logger.debug(f"[GET_STATUS] Getting power status for address: {address.label} (ID: {address.id})")

        try:
            logger.debug(f"[GET_STATUS] Checking cache for region {address.region}...")
            cache = self.scraper_service.get_cache(address.region)

            if not cache:
                logger.info(f"[GET_STATUS] No cache for region {address.region}, fetching...")
                await self.scraper_service.fetch_schedule_data(address.region)
                cache = self.scraper_service.get_cache(address.region)

            if not cache:
                logger.error(f"[GET_STATUS] Failed to fetch schedule data for region {address.region}")
                raise ValueError(f"Failed to fetch schedule data for region {address.region}")

            logger.debug(f"[GET_STATUS] Looking up queue for {address.label}...")
            queue = await self.scraper_service.lookup_queue(
                address.region,
                address.city,
                address.street,
                address.house,
            )
            logger.info(f"[GET_STATUS] Resolved queue for {address.label}: {queue}")

            logger.debug(f"[GET_STATUS] Getting current status from scraper service...")
            current_status, status_label, schedule_blocks, next_change, next_change_status, hourly_schedule = self.scraper_service.get_current_status(
                cache.fact,
                queue,
            )
            logger.info(f"[GET_STATUS] Status for {address.label}: {current_status} ({status_label})")

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
            logger.exception(f"[GET_STATUS] Error getting power status for {address.label}: {type(e).__name__}: {e}")
            return PowerStatus(
                address=address,
                current_status="error",
                current_status_label="Помилка",
                error=str(e),
                last_update=datetime.now(timezone.utc),
            )

    async def _update_status_message(self, channel_id: int, addresses: List[AddressConfig]):
        logger.info(f"[UPDATE_MSG] Updating status message for channel {channel_id} with {len(addresses)} addresses")

        if not addresses:
            logger.debug(f"[UPDATE_MSG] No addresses provided, skipping")
            return

        logger.debug(f"[UPDATE_MSG] Checking bot connection state...")
        logger.debug(f"[UPDATE_MSG] Bot is_ready: {self.bot.is_ready()}, is_closed: {self.bot.is_closed()}, latency: {self.bot.latency * 1000:.2f}ms")

        logger.debug(f"[UPDATE_MSG] Getting channel {channel_id}...")
        channel = self.bot.get_channel(channel_id)

        if not channel:
            logger.warning(f"[UPDATE_MSG] Channel {channel_id} not found in bot cache")
            return

        if not isinstance(channel, discord.TextChannel):
            logger.warning(f"[UPDATE_MSG] Channel {channel_id} is not a TextChannel (type: {type(channel).__name__})")
            return

        logger.info(f"[UPDATE_MSG] Channel found: {channel.name} (ID: {channel.id}) in guild {channel.guild.name}")

        logger.debug(f"[UPDATE_MSG] Fetching power statuses for {len(addresses)} addresses...")
        statuses = []
        for i, addr in enumerate(addresses):
            logger.debug(f"[UPDATE_MSG] Fetching status {i+1}/{len(addresses)} for {addr.label}...")
            status = await self._get_power_status(addr)
            statuses.append(status)
            self._status_cache[addr.id] = status
            logger.debug(f"[UPDATE_MSG] Status cached for {addr.label}")

        logger.debug(f"[UPDATE_MSG] Building embed...")
        embed = self.embed_builder.build_status_embed(statuses)
        logger.debug(f"[UPDATE_MSG] Embed built")

        message_id = addresses[0].message_id
        logger.debug(f"[UPDATE_MSG] Existing message_id: {message_id}")

        try:
            if message_id:
                logger.debug(f"[UPDATE_MSG] Attempting to fetch and edit existing message {message_id}...")
                try:
                    message = await channel.fetch_message(message_id)
                    logger.debug(f"[UPDATE_MSG] Message {message_id} fetched, editing...")
                    await message.edit(embed=embed)
                    logger.info(f"[UPDATE_MSG] Successfully edited message {message_id}")
                    return
                except discord.NotFound:
                    logger.warning(f"[UPDATE_MSG] Message {message_id} not found, will create new message")
                except discord.HTTPException as e:
                    logger.error(f"[UPDATE_MSG] HTTP error fetching/editing message {message_id}: {e}, status={getattr(e, 'status', 'N/A')}")
                except Exception as e:
                    logger.exception(f"[UPDATE_MSG] Unexpected error fetching/editing message {message_id}: {e}")

            logger.debug(f"[UPDATE_MSG] Sending new message to channel {channel_id}...")
            message = await channel.send(embed=embed)
            logger.info(f"[UPDATE_MSG] New message created: {message.id}")

            logger.debug(f"[UPDATE_MSG] Updating database with new message_id...")
            for i, addr in enumerate(addresses):
                logger.debug(f"[UPDATE_MSG] Updating message_id for address {i+1}/{len(addresses)}: {addr.label}")
                await self.db.update_dtek_message_id(addr.id, message.id)
                addr.message_id = message.id
            logger.info(f"[UPDATE_MSG] Database updated with message_id {message.id}")

        except discord.Forbidden as e:
            logger.error(f"[UPDATE_MSG] CRITICAL: No permission to send/edit in channel {channel_id}: {e}")
        except discord.HTTPException as e:
            logger.exception(f"[UPDATE_MSG] CRITICAL: Discord HTTP error updating status message: {e}, status={getattr(e, 'status', 'N/A')}")
        except Exception as e:
            logger.exception(f"[UPDATE_MSG] CRITICAL: Unexpected error updating status message: {type(e).__name__}: {e}")
        finally:
            logger.debug(f"[UPDATE_MSG] _update_status_message exiting for channel {channel_id}")

    async def label_autocomplete(self, ctx: discord.AutocompleteContext) -> List[str]:
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

    @commands.slash_command(name="dtek_add_address", description="Add an address to monitor for DTEK power shutdowns")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def dtek_add_address(
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
        logger.info(f"[ADD_ADDRESS] Command invoked by {ctx.author} (ID: {ctx.author.id}) in guild {ctx.guild_id}, channel {ctx.channel_id}")
        logger.info(f"[ADD_ADDRESS] Parameters: region={region}, street={street}, house={house}, label={label}, city={city}, channel={channel}")

        try:
            logger.debug(f"[ADD_ADDRESS] Attempting to defer response...")
            await asyncio.wait_for(ctx.defer(ephemeral=True), timeout=5.0)
            logger.info(f"[ADD_ADDRESS] Response deferred successfully")
        except asyncio.TimeoutError:
            logger.error(f"[ADD_ADDRESS] CRITICAL: defer() timed out after 5 seconds")
            return
        except discord.HTTPException as e:
            logger.exception(f"[ADD_ADDRESS] CRITICAL: Discord HTTP error during defer(): {e}, status={getattr(e, 'status', 'N/A')}, code={getattr(e, 'code', 'N/A')}")
            return
        except Exception as e:
            logger.exception(f"[ADD_ADDRESS] CRITICAL: Unexpected error during defer(): {type(e).__name__}: {e}")
            return

        if not ctx.guild:
            logger.warning(f"[ADD_ADDRESS] Command used outside guild context")
            try:
                await ctx.respond(":x: Ця команда доступна лише на сервері.", ephemeral=True)
            except Exception as e:
                logger.exception(f"[ADD_ADDRESS] Failed to send guild-only error: {e}")
            return

        logger.debug(f"[ADD_ADDRESS] Validating region configuration...")
        region_config = DTEK_REGIONS.get(region, DTEK_REGIONS["krem"])
        if region_config.get("has_city", True) and not city:
            logger.warning(f"[ADD_ADDRESS] Missing city parameter for region {region}")
            try:
                await ctx.respond(
                    ":x: Для регіону **ДТЕК КРЕМ** потрібно вказати місто (параметр `city`).\n"
                    "Приклад: `с. Велика Солтанівка`",
                    ephemeral=True,
                )
            except Exception as e:
                logger.exception(f"[ADD_ADDRESS] Failed to send city validation error: {e}")
            return

        actual_city = city if city else ""
        target_channel = channel or ctx.channel
        logger.info(f"[ADD_ADDRESS] Target channel: {target_channel.id} ({target_channel.name})")

        try:
            logger.info(f"[ADD_ADDRESS] Starting scraper service fetch for region {region}...")
            await self.scraper_service.fetch_schedule_data(region)
            logger.info(f"[ADD_ADDRESS] Schedule data fetched successfully for region {region}")

            logger.info(f"[ADD_ADDRESS] Looking up queue for address: city='{actual_city}', street='{street}', house='{house}'")
            queue = await self.scraper_service.lookup_queue(region, actual_city, street, house)
            logger.info(f"[ADD_ADDRESS] Queue resolved successfully: {queue}")

            logger.debug(f"[ADD_ADDRESS] Adding address to database...")
            addr_id = await self.db.add_dtek_address(
                region=region,
                city=actual_city,
                street=street,
                house=house,
                label=label,
                guild_id=ctx.guild.id,
                channel_id=target_channel.id,
            )
            logger.info(f"[ADD_ADDRESS] Address added to database with ID: {addr_id}")

            if region_config.get("has_city", True):
                location_str = f"{actual_city}, {street}, {house}"
            else:
                location_str = f"{actual_city}, {street}, {house}" if actual_city else f"{street}, {house}"

            logger.debug(f"[ADD_ADDRESS] Sending success response...")
            try:
                await ctx.respond(
                    f":white_check_mark: Адресу **{label}** додано!\n"
                    f":round_pushpin: {location_str}\n"
                    f":tv: Канал: {target_channel.mention}\n"
                    f":electric_plug: Черга відключень: `{queue}`",
                    ephemeral=True,
                )
                logger.info(f"[ADD_ADDRESS] Success response sent to user")
            except discord.HTTPException as e:
                logger.exception(f"[ADD_ADDRESS] Failed to send success response: {e}, status={getattr(e, 'status', 'N/A')}")
            except Exception as e:
                logger.exception(f"[ADD_ADDRESS] Unexpected error sending success response: {e}")

            logger.debug(f"[ADD_ADDRESS] Reloading addresses from database...")
            await self._load_addresses()
            addresses = [a for a in self._addresses if a.channel_id == target_channel.id]
            logger.info(f"[ADD_ADDRESS] Found {len(addresses)} addresses for channel {target_channel.id}")

            logger.debug(f"[ADD_ADDRESS] Updating status message...")
            await self._update_status_message(target_channel.id, addresses)
            logger.info(f"[ADD_ADDRESS] Command completed successfully for {ctx.author}")

        except ValidationException as e:
            logger.warning(f"[ADD_ADDRESS] Validation error: {e}")
            try:
                await ctx.respond(f":x: Помилка валідації адреси: {e}", ephemeral=True)
            except Exception as resp_err:
                logger.exception(f"[ADD_ADDRESS] Failed to send validation error response: {resp_err}")
        except discord.HTTPException as e:
            logger.exception(f"[ADD_ADDRESS] Discord HTTP error: {e}, status={getattr(e, 'status', 'N/A')}, code={getattr(e, 'code', 'N/A')}")
            try:
                await ctx.respond(f":x: Помилка Discord API: {e}", ephemeral=True)
            except Exception as resp_err:
                logger.exception(f"[ADD_ADDRESS] Failed to send HTTP error response: {resp_err}")
        except Exception as e:
            logger.exception(f"[ADD_ADDRESS] CRITICAL: Unexpected error: {type(e).__name__}: {e}")
            try:
                await ctx.respond(f":x: Помилка: {e}", ephemeral=True)
            except Exception as resp_err:
                logger.exception(f"[ADD_ADDRESS] Failed to send general error response: {resp_err}")
        finally:
            logger.info(f"[ADD_ADDRESS] Command handler exiting for {ctx.author}")

    @commands.slash_command(name="dtek_remove_address", description="Remove a monitored DTEK address")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def dtek_remove_address(
        self,
        ctx: discord.ApplicationContext,
        label: str = discord.Option(str, description="Label of the address to remove"),
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

    @commands.slash_command(name="dtek_list_addresses", description="List monitored DTEK addresses")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def dtek_list_addresses(self, ctx: discord.ApplicationContext):
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

    @commands.slash_command(name="dtek_refresh", description="Force refresh DTEK power status")
    @commands.has_permissions(administrator=True)
    async def dtek_refresh(self, ctx: discord.ApplicationContext):
        logger.info(f"[REFRESH] Command invoked by {ctx.author} (ID: {ctx.author.id}) in guild {ctx.guild_id}")

        try:
            logger.debug(f"[REFRESH] Attempting to defer response...")
            await asyncio.wait_for(ctx.defer(ephemeral=True), timeout=5.0)
            logger.info(f"[REFRESH] Response deferred successfully")
        except asyncio.TimeoutError:
            logger.error(f"[REFRESH] CRITICAL: defer() timed out")
            return
        except discord.HTTPException as e:
            logger.exception(f"[REFRESH] CRITICAL: Discord HTTP error during defer(): {e}")
            return
        except Exception as e:
            logger.exception(f"[REFRESH] CRITICAL: Unexpected error during defer(): {e}")
            return

        try:
            logger.debug(f"[REFRESH] Clearing scraper cache...")
            self.scraper_service.clear_cache()
            logger.debug(f"[REFRESH] Cache cleared")

            logger.debug(f"[REFRESH] Loading addresses...")
            await self._load_addresses()
            logger.info(f"[REFRESH] Loaded {len(self._addresses)} total addresses")

            by_channel: Dict[int, List[AddressConfig]] = {}
            for addr in self._addresses:
                if addr.guild_id != ctx.guild.id:
                    continue
                if addr.channel_id not in by_channel:
                    by_channel[addr.channel_id] = []
                by_channel[addr.channel_id].append(addr)

            logger.info(f"[REFRESH] Found {len(by_channel)} channels with addresses for guild {ctx.guild_id}")

            for i, (channel_id, addresses) in enumerate(by_channel.items()):
                logger.debug(f"[REFRESH] Updating channel {i+1}/{len(by_channel)}: {channel_id} ({len(addresses)} addresses)")
                await self._update_status_message(channel_id, addresses)
                logger.debug(f"[REFRESH] Channel {channel_id} updated")

            logger.debug(f"[REFRESH] Sending success response...")
            await ctx.respond(":white_check_mark: Статус оновлено!", ephemeral=True)
            logger.info(f"[REFRESH] Command completed successfully")

        except discord.HTTPException as e:
            logger.exception(f"[REFRESH] Discord HTTP error: {e}")
            try:
                await ctx.respond(f":x: Помилка Discord API: {e}", ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            logger.exception(f"[REFRESH] CRITICAL: Unexpected error: {e}")
            try:
                await ctx.respond(f":x: Помилка: {e}", ephemeral=True)
            except Exception:
                pass
        finally:
            logger.info(f"[REFRESH] Command handler exiting")

    @commands.slash_command(name="dtek_status", description="Show current DTEK power status for all addresses")
    @commands.has_permissions(administrator=True)
    async def dtek_status(self, ctx: discord.ApplicationContext):
        logger.info(f"[STATUS] Command invoked by {ctx.author} (ID: {ctx.author.id}) in guild {ctx.guild_id}")

        try:
            logger.debug(f"[STATUS] Attempting to defer response...")
            await asyncio.wait_for(ctx.defer(), timeout=5.0)
            logger.info(f"[STATUS] Response deferred successfully")
        except asyncio.TimeoutError:
            logger.error(f"[STATUS] CRITICAL: defer() timed out")
            return
        except discord.HTTPException as e:
            logger.exception(f"[STATUS] CRITICAL: Discord HTTP error during defer(): {e}")
            return
        except Exception as e:
            logger.exception(f"[STATUS] CRITICAL: Unexpected error during defer(): {e}")
            return

        try:
            logger.debug(f"[STATUS] Loading addresses from database...")
            await self._load_addresses()
            guild_addresses = [a for a in self._addresses if a.guild_id == ctx.guild.id]
            logger.info(f"[STATUS] Found {len(guild_addresses)} addresses for guild {ctx.guild_id}")

            if not guild_addresses:
                logger.info(f"[STATUS] No addresses found, sending empty response")
                await ctx.respond(":mailbox_with_no_mail: Немає моніторингових адрес. Додайте через `/dtek_add_address`")
                return

            logger.debug(f"[STATUS] Getting power status for {len(guild_addresses)} addresses...")
            statuses = []
            for i, addr in enumerate(guild_addresses):
                logger.debug(f"[STATUS] Getting status for address {i+1}/{len(guild_addresses)}: {addr.label}")
                status = await self._get_power_status(addr)
                statuses.append(status)
                logger.debug(f"[STATUS] Status retrieved for {addr.label}: {status.current_status}")

            logger.debug(f"[STATUS] Building embed...")
            embed = self.embed_builder.build_status_embed(statuses)

            logger.debug(f"[STATUS] Sending response...")
            await ctx.respond(embed=embed)
            logger.info(f"[STATUS] Command completed successfully")

        except discord.HTTPException as e:
            logger.exception(f"[STATUS] Discord HTTP error: {e}")
            try:
                await ctx.respond(f":x: Помилка Discord API: {e}")
            except Exception:
                pass
        except Exception as e:
            logger.exception(f"[STATUS] CRITICAL: Unexpected error: {e}")
            try:
                await ctx.respond(f":x: Помилка: {e}")
            except Exception:
                pass
        finally:
            logger.info(f"[STATUS] Command handler exiting")

    @commands.slash_command(name="dtek_set_channel", description="Change the channel where DTEK status updates are displayed")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def dtek_set_channel(
        self,
        ctx: discord.ApplicationContext,
        label: str = discord.Option(str, description="Label of the address to update"),
        channel: discord.TextChannel = discord.Option(discord.TextChannel, description="New channel for status updates"),
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

    @commands.slash_command(name="dtek_task_status", description="Check the status of the DTEK automatic update task")
    @commands.has_permissions(administrator=True)
    async def dtek_task_status(self, ctx: discord.ApplicationContext):
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

    @commands.slash_command(name="dtek_restart_task", description="Restart the DTEK automatic update task if it stopped")
    @commands.has_permissions(administrator=True)
    async def dtek_restart_task(self, ctx: discord.ApplicationContext):
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
    logger.info(f"DTEKMonitor cog added with DTEK commands")
