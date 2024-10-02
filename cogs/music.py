import asyncio
from typing import Union, List

import discord
from discord import Option
from discord.ext import commands, tasks

from utils.music_utils import ytdl, sp


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.loop = bot.loop
        self.guild_states = {}
        self.disconnect_timer.start()

    def cog_unload(self):
        self.disconnect_timer.cancel()

    @tasks.loop(minutes=5)
    async def disconnect_timer(self):
        for guild_id, state in list(self.guild_states.items()):
            voice_client = state.get('voice_client')
            last_played = state.get('last_played')
            if voice_client and not voice_client.is_playing() and last_played and (
                    discord.utils.utcnow() - last_played).total_seconds() >= 300:
                await self.leave_voice_channel(voice_client, guild_id)

    async def leave_voice_channel(self, voice_client, guild_id):
        if voice_client:
            embed = self.create_embed("👋 Отключение",
                                      "5 минут бездействия прошло. Я выхожу из голосового канала. Ня.пока!")
            await voice_client.disconnect()
            state = self.guild_states.get(guild_id)
            if state:
                channel = state.get('text_channel')
                if channel:
                    await channel.send(embed=embed)
            del self.guild_states[guild_id]

    def create_embed(self, title, description, color=discord.Color.blue()):
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="🎵 Музыкальный бот | Наслаждайтесь музыкой!")
        return embed

    async def extract_info(self, url, download=False):
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=download))
        except Exception as e:
            return None

    async def send_error_message(self, channel, content):
        embed = self.create_embed("❌ Ошибка", content, discord.Color.red())
        await channel.send(embed=embed)

    async def add_to_queue(self, ctx, url):
        guild_id = ctx.guild.id
        state = self.guild_states.setdefault(guild_id, {'queue': [], 'last_played': None, 'voice_client': ctx.voice_client, 'text_channel': ctx.channel})
        if "open.spotify.com" in url:
            added_tracks = await self.add_spotify_to_queue(ctx, url)
            if added_tracks:
                tracks_info = "\n".join([f"🎵 {track}" for track in added_tracks[:5]])
                if len(added_tracks) > 5:
                    tracks_info += f"\n... и ещё {len(added_tracks) - 5} треков"
                embed = self.create_embed("🎶 Добавлено в очередь",
                    f"**Добавлено {len(added_tracks)} треков из Spotify:**\n\n{tracks_info}")
                embed.add_field(name="🔗 Источник", value="Spotify", inline=True)
                embed.add_field(name="👤 Добавил", value=ctx.author.mention, inline=True)
                await ctx.respond(embed=embed)
            else:
                await self.send_error_message(ctx.channel, "Не удалось добавить треки из Spotify в очередь")
        else:
            info = await self.extract_info(url, download=False)
            if info is None:
                await self.send_error_message(ctx.channel, f"Не удалось добавить трек в очередь: {url}")
                return

            if 'entries' in info:
                tracks_info = "\n".join([f"🎵 {entry['title']}" for entry in info['entries'][:5]])
                if len(info['entries']) > 5:
                    tracks_info += f"\n... и ещё {len(info['entries']) - 5} треков"
                embed = self.create_embed("🎶 Добавлено в очередь",
                    f"**Добавлено {len(info['entries'])} треков в очередь:**\n\n{tracks_info}")
                embed.add_field(name="🔗 Источник", value="YouTube", inline=True)
                embed.add_field(name="👤 Добавил", value=ctx.author.mention, inline=True)
                await ctx.respond(embed=embed)
                for entry in info['entries']:
                    state['queue'].append(entry)
            else:
                state['queue'].append(info)
                embed = self.create_embed("🎶 Добавлено в очередь", f"**Трек добавлен в очередь:**\n\n🎵 {info['title']}")
                embed.add_field(name="🔗 Источник", value="YouTube", inline=True)
                embed.add_field(name="👤 Добавил", value=ctx.author.mention, inline=True)
                embed.add_field(name="⏱️ Длительность", value=self.format_duration(info.get('duration', 0)), inline=True)
                await ctx.respond(embed=embed)

    def format_duration(self, duration):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
        else:
            return f"{int(minutes):02d}:{int(seconds):02d}"

    async def add_spotify_to_queue(self, ctx, url: str) -> List[str]:
        added_tracks = []
        if "track" in url:
            track = sp.track(url)
            search_query = f"{track['name']} {track['artists'][0]['name']}"
            youtube_url = await self.search_youtube(search_query)
            if youtube_url:
                result = await self.add_youtube_to_queue(ctx, youtube_url)
                if isinstance(result, str):
                    added_tracks.append(result)
        elif "album" in url:
            album = sp.album(url)
            for track in album['tracks']['items']:
                search_query = f"{track['name']} {track['artists'][0]['name']}"
                youtube_url = await self.search_youtube(search_query)
                if youtube_url:
                    result = await self.add_youtube_to_queue(ctx, youtube_url)
                    if isinstance(result, str):
                        added_tracks.append(result)
        elif "playlist" in url:
            playlist = sp.playlist(url)
            for item in playlist['tracks']['items']:
                track = item['track']
                search_query = f"{track['name']} {track['artists'][0]['name']}"
                youtube_url = await self.search_youtube(search_query)
                if youtube_url:
                    result = await self.add_youtube_to_queue(ctx, youtube_url)
                    if isinstance(result, str):
                        added_tracks.append(result)
        return added_tracks

    async def add_youtube_to_queue(self, ctx, url: str) -> Union[str, List[str]]:
        info = await self.extract_info(url, download=False)
        if info is None:
            return f"Не удалось добавить трек в очередь: {url}"

        guild_id = ctx.guild.id
        state = self.guild_states.setdefault(guild_id, {'queue': [], 'last_played': None, 'voice_client': ctx.voice_client, 'text_channel': ctx.channel})

        if info.get("_type") == "playlist":
            added_tracks = []
            for entry in info["entries"]:
                state['queue'].append(entry)
                added_tracks.append(entry['title'])
            return added_tracks
        else:
            state['queue'].append(info)
            return info['title']

    async def search_youtube(self, query):
        search_url = f"ytsearch1:{query}"
        info = await self.extract_info(search_url, download=False)
        if info and 'entries' in info and info['entries']:
            return info['entries'][0]['webpage_url']
        return None

    async def download_and_play(self, ctx, track):
        if not isinstance(track, dict):
            await self.send_error_message(ctx.channel, f"Некорректная информация о треке: {track}")
            await self.play_next_track(ctx)
            return

        info = track
        url = info.get('url')
        webpage_url = info.get('webpage_url')

        if not url and webpage_url:
            extracted_info = await self.extract_info(webpage_url, download=False)
            if extracted_info and 'url' in extracted_info:
                url = extracted_info['url']
                info = extracted_info
            else:
                await self.send_error_message(ctx.channel, f"Не удалось получить URL для трека: {info.get('title', 'Unknown')}")
                await self.play_next_track(ctx)
                return

        if not url:
            await self.send_error_message(ctx.channel, f"Отсутствует URL для трека: {info.get('title', 'Unknown')}")
            await self.play_next_track(ctx)
            return

        source = discord.FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")
        ctx.voice_client.play(source, after=lambda e: self.bot.loop.create_task(self.after_playing(ctx, e)))

        guild_id = ctx.guild.id
        state = self.guild_states.get(guild_id)
        if state:
            state['current_playing'] = f"{info.get('title', 'Неизвестно')} - {webpage_url or 'Нет URL'}"
            state['last_played'] = discord.utils.utcnow()

        embed = self.create_embed("🎵 Сейчас играет", f"🎶 {state['current_playing']}")
        await ctx.respond(embed=embed)

    async def after_playing(self, ctx, error=None):
        if error:
            await self.send_error_message(ctx.channel, f"Произошла ошибка при воспроизведении: {str(error)}")

        guild_id = ctx.guild.id
        state = self.guild_states.get(guild_id)

        if state:
            if not state['queue']:
                state['current_playing'] = None
                embed = self.create_embed("📢 Информация", "Очередь закончилась. Добавьте больше треков!")
                await ctx.respond(embed=embed)
            else:
                await self.play_next_track(ctx)

    async def play_next_track(self, ctx):
        guild_id = ctx.guild.id
        state = self.guild_states.get(guild_id)
        if state:
            if not ctx.voice_client or not ctx.voice_client.is_connected():
                try:
                    await ctx.author.voice.channel.connect()
                except Exception as e:
                    await self.send_error_message(ctx.channel, "Не удалось подключиться к голосовому каналу. Пожалуйста, попробуйте снова.")
                    return

            if state['queue']:
                next_track = state['queue'].pop(0)
                await self.download_and_play(ctx, next_track)
            else:
                embed = self.create_embed("📢 Информация", "Очередь пуста!")
                await ctx.respond(embed=embed)
                state['current_playing'] = None

    @commands.slash_command(name="play", description="Воспроизвести музыку с Spotify или YouTube")
    async def play(self, ctx, *, url: Option(str, "URL или название трека", required=True)):
        await ctx.defer()
        if not ctx.author.voice:
            embed = self.create_embed("❌ Ошибка",
                                        "Вы должны быть в голосовом канале, чтобы использовать эту команду!",
                                        discord.Color.red())
            await ctx.respond(embed=embed)
            return

        if ctx.voice_client and ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.disconnect()
            await ctx.author.voice.channel.connect()
        elif not ctx.voice_client:
            await ctx.author.voice.channel.connect()

        await self.add_to_queue(ctx, url)

        if not ctx.voice_client.is_playing():
            await self.play_next_track(ctx)

    @commands.slash_command(name="queue", description="Показать текущую очередь")
    async def show_queue(self, ctx):
        guild_id = ctx.guild.id
        state = self.guild_states.get(guild_id)
        if state:
            queue = state.get('queue', [])
            current_playing = state.get('current_playing')

            if queue or current_playing:
                queue_pages = []
                items_per_page = 10

                for i in range(0, len(queue), items_per_page):
                    page_items = queue[i:i + items_per_page]
                    embed = discord.Embed(title="🎶 Текущая очередь", color=discord.Color.blue())

                    if current_playing and i == 0:
                        embed.add_field(name="▶️ Сейчас играет", value=f"**{current_playing}**", inline=False)

                    for idx, track in enumerate(page_items, i + 1):
                        embed.add_field(name=f"{idx}. {track['title']}",
                                        value=f"[🔗]({track['webpage_url']}) | ⏱️ {self.format_duration(track.get('duration', 0))}",
                                        inline=False)

                    embed.set_footer(
                        text=f"Страница {i // items_per_page + 1} из {-(-len(queue) // items_per_page)} | 🎵 Музыкальный бот")
                    queue_pages.append(embed)

                if queue_pages:
                    message = await ctx.respond(embed=queue_pages[0])

                    if len(queue_pages) > 1:
                        await self.paginate(ctx, message, queue_pages)
                else:
                    embed = self.create_embed("Текущая очередь", "В очереди нет треков, но сейчас что-то играет.")
                    await ctx.respond(embed=embed)
            else:
                embed = self.create_embed("Очередь пуста", "Добавьте треки с помощью команды **/play**!")
                await ctx.respond(embed=embed)
        else:
            embed = self.create_embed("Очередь пуста", "Добавьте треки с помощью команды **/play**!")
            await ctx.respond(embed=embed)

    async def paginate(self, ctx, message, embeds):
        current_page = 0

        buttons = [
            discord.ui.Button(emoji="⬅️", style=discord.ButtonStyle.primary),
            discord.ui.Button(emoji="➡️", style=discord.ButtonStyle.primary)
        ]

        async def button_callback(interaction):
            nonlocal current_page
            if interaction.user != ctx.author:
                await interaction.response.send_message("Вы не можете управлять этой страницей.", ephemeral=True)
                return
            if interaction.component.emoji.name == "⬅️":
                current_page = (current_page - 1) % len(embeds)
            elif interaction.component.emoji.name == "➡️":
                current_page = (current_page + 1) % len(embeds)
            await interaction.response.edit_message(embed=embeds[current_page])

        for button in buttons:
            button.callback = button_callback

        view = discord.ui.View()
        for button in buttons:
            view.add_item(button)

        await message.edit(view=view)

    @commands.slash_command(name="skip", description="Пропустить текущий трек")
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            embed = self.create_embed("⏭️ Трек пропущен", "Переходим к следующему треку в очереди!")
            await ctx.respond(embed=embed)
        else:
            embed = self.create_embed("❌ Ошибка", "Сейчас ничего не играет", color=discord.Color.red())
            await ctx.respond(embed=embed)

    @commands.slash_command(name="pause", description="Приостановить воспроизведение")
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            embed = self.create_embed("⏸️ Пауза", "Музыка приостановлена. Используйте /resume, чтобы продолжить.")
            await ctx.respond(embed=embed)
        else:
            embed = self.create_embed("❌ Ошибка", "Нечего ставить на паузу!", color=discord.Color.red())
            await ctx.respond(embed=embed)

    @commands.slash_command(name="resume", description="Возобновить воспроизведение")
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            embed = self.create_embed("▶️ Возобновление", "Музыка снова играет!")
            await ctx.respond(embed=embed)
        else:
            embed = self.create_embed("❌ Ошибка", "Нечего возобновлять!", color=discord.Color.red())
            await ctx.respond(embed=embed)

    @commands.slash_command(name="stop", description="Остановить воспроизведение и очистить очередь")
    async def stop(self, ctx):
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
            guild_id = ctx.guild.id
            if guild_id in self.guild_states:
                del self.guild_states[guild_id]
            embed = self.create_embed("🛑 Остановлено",
                                      "Воспроизведение остановлено, очередь очищена. До новых встреч!")
            await ctx.respond(embed=embed)
        else:
            embed = self.create_embed("❌ Ошибка", "Я не нахожусь в голосовом канале!",
                                      color=discord.Color.red())
            await ctx.respond(embed=embed)

    @commands.slash_command(name="now_playing", description="Показать информацию о текущем треке")
    async def now_playing(self, ctx):
        guild_id = ctx.guild.id
        state = self.guild_states.get(guild_id)
        if state and state.get('current_playing'):
            embed = self.create_embed("🎵 Сейчас играет", f"🎶 {state['current_playing']}")
            await ctx.respond(embed=embed)
        else:
            embed = self.create_embed("❌ Ошибка", "Сейчас ничего не играет", color=discord.Color.red())
            await ctx.respond(embed=embed)

def setup(bot):
    bot.add_cog(Music(bot))
