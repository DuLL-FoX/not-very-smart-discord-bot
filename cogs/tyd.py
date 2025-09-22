import random
from datetime import datetime, timedelta
from types import SimpleNamespace
import discord
from discord.ext import commands, tasks
from utils.database import Database


class TYD(commands.Cog):
    tyd_owner = discord.SlashCommandGroup(
        name="tyd_owner",
        description="Owner-only TYD controls",
        default_member_permissions=discord.Permissions(administrator=True),
        dm_permission=False,
    )
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.check_expired_roles_task.start()

    def cog_unload(self):
        self.check_expired_roles_task.cancel()

    @commands.slash_command(name="tyd", description="Test your destiny")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    async def tyd(self, ctx):
        await self.remove_expired_roles_for_user(ctx.author)

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
        elif 30 <= random_number < 50:
            range_key, role_to_assign, days = "30-49", None, None
        elif 51 <= random_number < 66:
            range_key, role_to_assign, days = "51-65", None, None
        elif 67 <= random_number < 77:
            range_key, role_to_assign, days = "67-76", None, None
        elif 78 <= random_number < 100:
            range_key, role_to_assign, days = "78-99", None, None

        if role_to_assign:
            await self.remove_tyd_roles(ctx.author, ctx.guild, role_to_assign)
            expiration = datetime.now() + timedelta(days=days)
            await self.assign_role_and_update_db(ctx, role_to_assign, expiration)

        messages = await self.db.get_messages_for_range(range_key)
        if not messages:
            messages = [
                "{user_mention}, тебе выпало {random_number}. {bot_mention} записал это в книгу судьбы!"
            ]
        text = random.choice(messages).format(
            user_mention=user_mention,
            bot_mention=bot_member.mention,
            random_number=random_number,
        )

        color = discord.Color.random()
        embed = discord.Embed(title="Твоя судьба!", description=text, color=color)
        embed.add_field(name="Число", value=str(random_number), inline=True)
        if role_to_assign:
            embed.add_field(name="Роль", value=role_to_assign, inline=True)
        await ctx.respond(embed=embed)

    async def assign_role_and_update_db(self, ctx, role_name, expiration):
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not role:
            role = await ctx.guild.create_role(name=role_name)
        await ctx.author.add_roles(role)
        await self.db.assign_role(ctx.author.id, role_name, expiration)

    async def remove_tyd_roles(self, member, guild, new_role_name=None):
        tyd_role_names = [
            "Имеет немного власти", "Одинокая половинка", "Грешник",
            "Неудачник", "Участник под номером 100", "Эскапист",
            "Любимец фортуны", "Средний класс"
        ]
        roles_to_remove = []
        for role in member.roles:
            if role.name in tyd_role_names and role.name != new_role_name:
                roles_to_remove.append(role)
                await self.db.delete_role(member.id, role.name)
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)

    async def remove_expired_roles_for_user(self, member):
        expired_roles = await self.db.fetch_expired_roles_for_user(member.id)
        roles_to_remove = []
        for record in expired_roles:
            role_name = record['role']
            role = discord.utils.get(member.guild.roles, name=role_name)
            if role and role in member.roles:
                roles_to_remove.append(role)
            await self.db.delete_expired_role(member.id, role_name)
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)

    # ===== Owner-only utilities =====
    def _dummy_ctx_for_member(self, base_ctx: discord.ApplicationContext, member: discord.Member):
        return SimpleNamespace(author=member, guild=base_ctx.guild, channel=base_ctx.channel)

    @tyd_owner.command(name="reset_cooldown", description="Reset /tyd cooldown for a user")
    @commands.is_owner()
    async def reset_cooldown(self, ctx: discord.ApplicationContext, user: discord.Member = None):
        target = user or ctx.author
        dummy_ctx = self._dummy_ctx_for_member(ctx, target)
        try:
            self.tyd.reset_cooldown(dummy_ctx)  # type: ignore[attr-defined]
            await ctx.respond(f"Сброшен кулдаун /tyd для {target.mention}.", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"Не удалось сбросить кулдаун: {e}", ephemeral=True)

    @tyd_owner.command(name="cooldown_status", description="Show /tyd cooldown status for a user")
    @commands.is_owner()
    async def cooldown_status(self, ctx: discord.ApplicationContext, user: discord.Member = None):
        target = user or ctx.author
        dummy_ctx = self._dummy_ctx_for_member(ctx, target)
        try:
            seconds = float(self.tyd.get_cooldown_retry_after(dummy_ctx))  # type: ignore[attr-defined]
            if seconds <= 0:
                await ctx.respond(f"У {target.mention} нет кулдауна на /tyd.", ephemeral=True)
            else:
                await ctx.respond(
                    f"Осталось {int(seconds)} сек. кулдауна /tyd для {target.mention}.",
                    ephemeral=True,
                )
        except Exception as e:
            await ctx.respond(f"Ошибка получения статуса кулдауна: {e}", ephemeral=True)

    @tyd_owner.command(name="purge_expired", description="Remove expired TYD roles for a user (or all expired in guild)")
    @commands.is_owner()
    async def purge_expired(self, ctx: discord.ApplicationContext, user: discord.Member = None):
        try:
            if user:
                await self.remove_expired_roles_for_user(user)
                await ctx.respond(f"Проверены и сняты просроченные роли у {user.mention}.", ephemeral=True)
            else:
                count = 0
                for member in ctx.guild.members:
                    await self.remove_expired_roles_for_user(member)
                    count += 1
                await ctx.respond(f"Проверены и сняты просроченные роли (по возможности) у {count} участников.", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"Ошибка при очистке ролей: {e}", ephemeral=True)

    @tasks.loop(hours=1)
    async def check_expired_roles_task(self):
        try:
            expired_roles = await self.db.fetch_expired_roles()
            for guild in self.bot.guilds:
                for record in expired_roles:
                    user_id = record['user_id']
                    role_name = record['role']
                    member = guild.get_member(user_id)
                    role = discord.utils.get(guild.roles, name=role_name)
                    if member and role and role in member.roles:
                        try:
                            await member.remove_roles(role)
                        except discord.HTTPException as e:
                            print(f"Error removing role {role_name} from user {user_id}: {e}")
                    await self.db.delete_expired_role(user_id, role_name)
        except Exception as e:
            print(f"Error in check_expired_roles_task: {e}")

    @check_expired_roles_task.before_loop
    async def before_check_expired_roles(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(TYD(bot))
