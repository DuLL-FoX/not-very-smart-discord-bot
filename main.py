import os
from datetime import timedelta
from dotenv import load_dotenv

from discord.ext import commands
import discord

intents = discord.Intents.all()
bot = commands.Bot(intents=intents)

# Load environment variables from .env file
load_dotenv()

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")

@bot.event
async def on_application_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.respond(
            f"Можешь так не спешить, у тебя ещё {str(timedelta(seconds=int(error.retry_after)))} кулдауна.")
    elif isinstance(error, discord.errors.NotFound):
        await ctx.respond("Честно говоря, я не ебу что это за ошибка, но я добавил её обработку.")
    else:
        raise error

# Load extensions
bot.load_extension("cogs.tyd")
bot.load_extension("cogs.music")

bot.run(os.getenv('DISCORD_TOKEN'))