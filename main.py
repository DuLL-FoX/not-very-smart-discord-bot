import os
import logging
import shutil
import subprocess
from datetime import timedelta
from dotenv import load_dotenv

from discord.ext import commands
import discord
from utils.database import Database

intents = discord.Intents.all()
bot = commands.Bot(intents=intents)

load_dotenv()

def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)

logger = logging.getLogger("startup")
setup_logging()

async def startup_health_checks() -> None:
    for path in ("data", "downloads"):
        try:
            os.makedirs(path, exist_ok=True)
            logger.info("Directory ready: %s", os.path.abspath(path))
        except Exception as e:
            logger.error("Failed to prepare directory %s: %s", path, e)

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        try:
            proc = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5)
            first_line = proc.stdout.splitlines()[0] if proc.stdout else "ffmpeg detected"
            logger.info("FFmpeg: %s (%s)", first_line, ffmpeg_path)
        except Exception as e:
            logger.warning("FFmpeg found at %s but failed to get version: %s", ffmpeg_path, e)
    else:
        logger.warning("FFmpeg not found in PATH. Audio playback may fail.")

    try:
        import yt_dlp
        logger.info("yt-dlp version: %s", getattr(yt_dlp, "version", getattr(yt_dlp, "__version__", "unknown")))
    except Exception as e:
        logger.warning("yt-dlp import failed: %s", e)

    try:
        import spotipy
        logger.info("spotipy version: %s", getattr(spotipy, "__version__", "unknown"))
        if not os.getenv("SPOTIFY_CLIENT_ID") or not os.getenv("SPOTIFY_CLIENT_SECRET"):
            logger.warning("Spotify credentials not set. Spotify URLs won't resolve.")
    except Exception as e:
        logger.warning("spotipy import failed: %s", e)

    try:
        db = Database()
        ok, details = await db.ping()
        if ok:
            logger.info("Database connected: %s", details)
        else:
            logger.error("Database ping failed: %s", details)
    except Exception as e:
        logger.error("Database check failed: %s", e)

@bot.event
async def on_ready():
    logger.info("Logged in as %s (id=%s)", bot.user, getattr(bot.user, "id", "unknown"))
    logger.info("Guilds: %d | Latency: %d ms", len(bot.guilds), int(bot.latency * 1000))
    logger.info("Cogs loaded: %s", ", ".join(sorted(bot.cogs.keys())) or "none")
    try:
        db = Database()
        await db.run_migrations()
        logger.info("Database migrations applied (if any).")
    except Exception as e:
        logger.exception("Failed to run migrations: %s", e)

    await startup_health_checks()

    try:
        app_cmds = getattr(bot, "application_commands", [])
        logger.info("Application commands registered: %d", len(app_cmds))
        
        logger.info("Syncing slash commands to Discord...")
        await bot.sync_commands()
        logger.info("Slash commands synced successfully")
    except Exception as e:
        logger.warning(f"Failed to sync commands: {e}")
@bot.event
async def on_application_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        try:
            await ctx.respond(
                f"Можешь так не спешить, у тебя ещё {str(timedelta(seconds=int(error.retry_after)))} кулдауна.")
        except discord.HTTPException:
            pass
    elif isinstance(error, discord.errors.NotFound):
        try:
            await ctx.respond("Честно говоря, я не ебу что это за ошибка, но я добавил её обработку.")
        except discord.HTTPException:
            pass
    else:
        logging.getLogger("commands").exception("Unhandled application command error: %s", error)
        try:
            if ctx.response.is_done():
                await ctx.followup.send(f":x: Невідома помилка: {type(error).__name__}", ephemeral=True)
            else:
                await ctx.respond(f":x: Невідома помилка: {type(error).__name__}", ephemeral=True)
        except discord.HTTPException:
            pass

bot.load_extension("cogs.tyd")
bot.load_extension("cogs.music")
bot.load_extension("cogs.dtek")
logger.info("Extensions loaded: %s", ", ".join(sorted(bot.cogs.keys())) or "none")

token = os.getenv('DISCORD_TOKEN')
if not token:
    logger.error("DISCORD_TOKEN is not set. Bot cannot start.")
else:
    logger.info("Starting bot...")
    bot.run(token)
