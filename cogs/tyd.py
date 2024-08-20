import random
from datetime import datetime, timedelta
import discord
from discord.ext import commands
from utils.database import Database

class TYD(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    @commands.slash_command(name="tyd", description="Test your destiny")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    async def tyd(self, ctx):
        bot_member = ctx.guild.get_member(self.bot.user.id)
        user_mention = ctx.author.mention

        random_number = random.randint(0, 101)
        role_mapping = {
            0: ("0", None, None),
            1: ("1", "Имеет немного власти", 7),
            50: ("50", "Одинокая половинка", 2),
            66: ("66", "Грешник", 1),
            77: ("77", "Неудачник", 1),
            100: ("100", "Участник под номером 100", 1),
            101: ("101", "Эскапист", 2)
        }

        range_key, role_to_assign, days = role_mapping.get(random_number, ("default", None, None))
        if 2 <= random_number < 11:
            range_key, role_to_assign, days = "2-10", "Любимец фортуны", 4
        elif 11 <= random_number < 30:
            range_key, role_to_assign, days = "11-29", "Средний класс", 2

        if role_to_assign:
            expiration = datetime.now() + timedelta(days=days)
            await self.assign_role_and_update_db(ctx, role_to_assign, expiration)

        messages = await self.db.get_messages_for_range(range_key)
        message = random.choice(messages).format(user_mention=user_mention, bot_mention=bot_member.mention,
                                                 random_number=random_number)
        await ctx.respond(message)

    async def assign_role_and_update_db(self, ctx, role_name, expiration):
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        await ctx.author.add_roles(role)
        await self.db.assign_role(ctx.author.id, role_name, expiration)

def setup(bot):
    bot.add_cog(TYD(bot))