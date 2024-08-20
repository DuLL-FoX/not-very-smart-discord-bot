import asyncio
from typing import Union, List

import discord
from discord import Option
from discord.ext import commands, tasks

from utils.music_utils import ytdl, sp
from utils.queue_manager import QueueManager


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.loop = bot.loop
        self.last_played = None
        self.ctx = None
        self.queue_manager = QueueManager()
        self.current_playing = None
        self.disconnect_timer.start()
        self.first_time = True

    @tasks.loop(minutes=5)
    async def disconnect_timer(self):
        if self.ctx and self.ctx.voice_client and not self.ctx.voice_client.is_playing() and self.last_played and (
                discord.utils.utcnow() - self.last_played).total_seconds() >= 300:
            await self.leave_voice_channel()

    async def leave_voice_channel(self):
        if self.ctx and self.ctx.voice_client:
            embed = await self.create_embed("👋 Отключение",
                                            "5 минут бездействия прошло. Я выхожу из голосового канала. Ня.пока!")
            await self.ctx.respond(embed=embed)
            await self.ctx.voice_client.disconnect()
            self.last_played = None

    async def create_embed(self, title, description, color=discord.Color.blue()):
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="🎵 Музыкальный бот | Наслаждайтесь музыкой!")
        return embed

    async def extract_info(self, url, download=False):
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=download))
        except Exception as e:
            await self.send_error_message(f"Ошибка при извлечении информации: {str(e)}")
            return None

    async def send_error_message(self, content):
        embed = await self.create_embed("❌ Ошибка", content, discord.Color.red())
        await self.ctx.respond(embed=embed)

    async def add_to_queue(self, url):
        if "open.spotify.com" in url:
            added_tracks = await self.add_spotify_to_queue(url)
            if added_tracks:
                tracks_info = "\n".join([f"🎵 {track}" for track in added_tracks[:5]])
                if len(added_tracks) > 5:
                    tracks_info += f"\n... и ещё {len(added_tracks) - 5} треков"
                embed = await self.create_embed("🎶 Добавлено в очередь",
                    f"**Добавлено {len(added_tracks)} треков из Spotify:**\n\n{tracks_info}")
                embed.add_field(name="🔗 Источник", value="Spotify", inline=True)
                embed.add_field(name="👤 Добавил", value=self.ctx.author.mention, inline=True)
                await self.ctx.respond(embed=embed)
            else:
                await self.send_error_message("Не удалось добавить треки из Spotify в очередь")
        else:
            info = await self.extract_info(url, download=False)
            if info is None:
                await self.send_error_message(f"Не удалось добавить трек в очередь: {url}")
                return

            if 'entries' in info:
                tracks_info = "\n".join([f"🎵 {entry['title']}" for entry in info['entries'][:5]])
                if len(info['entries']) > 5:
                    tracks_info += f"\n... и ещё {len(info['entries']) - 5} треков"
                embed = await self.create_embed("🎶 Добавлено в очередь",
                    f"**Добавлено {len(info['entries'])} треков в очередь:**\n\n{tracks_info}")
                embed.add_field(name="🔗 Источник", value="YouTube", inline=True)
                embed.add_field(name="👤 Добавил", value=self.ctx.author.mention, inline=True)
                await self.ctx.respond(embed=embed)
                for entry in info['entries']:
                    self.queue_manager.add_to_queue(entry)
            else:
                self.queue_manager.add_to_queue(info)
                embed = await self.create_embed("🎶 Добавлено в очередь", f"**Трек добавлен в очередь:**\n\n🎵 {info['title']}")
                embed.add_field(name="🔗 Источник", value="YouTube", inline=True)
                embed.add_field(name="👤 Добавил", value=self.ctx.author.mention, inline=True)
                embed.add_field(name="⏱️ Длительность", value=self.format_duration(info.get('duration', 0)), inline=True)
                await self.ctx.respond(embed=embed)

    def format_duration(self, duration):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
        else:
            return f"{int(minutes):02d}:{int(seconds):02d}"

    async def add_youtube_to_queue(self, url: str) -> Union[str, List[str]]:
        info = await self.extract_info(url, download=False)
        if info is None:
            return f"Не удалось добавить трек в очередь: {url}"

        if info.get("_type") == "playlist":
            added_tracks = []
            for entry in info["entries"]:
                self.queue_manager.add_to_queue(entry)
                added_tracks.append(entry['title'])
            return added_tracks
        else:
            self.queue_manager.add_to_queue(info)
            return info['title']

    async def add_spotify_to_queue(self, url: str) -> Union[str, List[str]]:
        added_tracks = []
        if "track" in url:
            track = sp.track(url)
            search_query = f"{track['name']} {track['artists'][0]['name']}"
            youtube_url = await self.search_youtube(search_query)
            if youtube_url:
                result = await self.add_youtube_to_queue(youtube_url)
                if isinstance(result, str):
                    added_tracks.append(result)
        elif "album" in url:
            album = sp.album(url)
            for track in album['tracks']['items']:
                search_query = f"{track['name']} {track['artists'][0]['name']}"
                youtube_url = await self.search_youtube(search_query)
                if youtube_url:
                    result = await self.add_youtube_to_queue(youtube_url)
                    if isinstance(result, str):
                        added_tracks.append(result)
        elif "playlist" in url:
            playlist = sp.playlist(url)
            for item in playlist['tracks']['items']:
                track = item['track']
                search_query = f"{track['name']} {track['artists'][0]['name']}"
                youtube_url = await self.search_youtube(search_query)
                if youtube_url:
                    result = await self.add_youtube_to_queue(youtube_url)
                    if isinstance(result, str):
                        added_tracks.append(result)
        return added_tracks

    async def search_youtube(self, query):
        search_url = f"ytsearch1:{query}"
        info = await self.extract_info(search_url, download=False)
        if info and 'entries' in info and info['entries']:
            return info['entries'][0]['webpage_url']
        return None

    async def download_and_play(self, track):
        if not isinstance(track, dict) or 'info' not in track:
            await self.send_error_message(f"Некорректная информация о треке: {track}")
            await self.play_next_track()
            return

        info = track['info']
        url = info.get('url')
        webpage_url = info.get('webpage_url')

        if not url and webpage_url:
            try:
                extracted_info = await self.extract_info(webpage_url, download=False)
                if extracted_info and 'url' in extracted_info:
                    url = extracted_info['url']
                else:
                    await self.send_error_message(f"Не удалось получить URL для трека: {info.get('title', 'Unknown')}")
                    await self.play_next_track()
                    return
            except Exception as e:
                await self.send_error_message(f"Ошибка при извлечении информации: {str(e)}")
                await self.play_next_track()
                return

        if not url:
            await self.send_error_message(f"Отсутствует URL для трека: {info.get('title', 'Unknown')}")
            await self.play_next_track()
            return

        try:
            self.ctx.voice_client.play(discord.FFmpegPCMAudio(source=url,
                                                              before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"),
                                       after=lambda x: self.loop.create_task(self.after_playing(x)))
            self.current_playing = f"{info.get('title', 'Неизвестно')} - {webpage_url or 'Нет URL'}"
            self.last_played = discord.utils.utcnow()

            embed = await self.create_embed("🎵 Сейчас играет", f"🎶 {self.current_playing}")
            await self.ctx.respond(embed=embed)
        except Exception as e:
            await self.send_error_message(f"Ошибка при воспроизведении трека: {str(e)}")
            await self.play_next_track()

    async def after_playing(self, error=None):
        if error:
            await self.send_error_message(f"Произошла ошибка при воспроизведении: {str(error)}")

        if self.ctx.voice_client:
            if not self.queue_manager.is_empty():
                await self.play_next_track()
            else:
                self.current_playing = None
                self.first_time = True
                embed = await self.create_embed("📢 Информация", "Очередь закончилась. Добавьте больше треков!")
                await self.ctx.respond(embed=embed)
        else:
            self.current_playing = None
            self.first_time = True
        self.last_played = discord.utils.utcnow()

    async def play_next_track(self):
        if not self.ctx.voice_client or not self.ctx.voice_client.is_connected():
            embed = await self.create_embed("❗ Внимание",
                                            "Бот не подключен к голосовому каналу. Пытаюсь переподключиться...")
            await self.ctx.respond(embed=embed)
            try:
                await self.ctx.author.voice.channel.connect()
            except AttributeError:
                await self.send_error_message("Вы должны быть в голосовом канале, чтобы воспроизводить музыку.")
                return
            except discord.errors.ClientException:
                await self.send_error_message(
                    "Не удалось подключиться к голосовому каналу. Пожалуйста, попробуйте снова.")
                return

        next_track = self.queue_manager.get_next()
        if next_track:
            try:
                await self.download_and_play(next_track)
            except Exception as e:
                await self.send_error_message(
                    f"Произошла ошибка при воспроизведении трека: {str(e)}. Перехожу к следующему треку.")
                await self.play_next_track()
        else:
            embed = await self.create_embed("📢 Информация", "Очередь пуста!")
            await self.ctx.respond(embed=embed)
            self.current_playing = None
            self.first_time = True

    @commands.slash_command(name="play", description="Воспроизвести музыку с Spotify или YouTube")
    async def play(self, ctx, *, url: Option(str, "URL или название трека", required=True)):
        await ctx.defer()
        self.ctx = ctx

        if not ctx.author.voice:
            embed = await self.create_embed("❌ Ошибка",
                                            "Вы должны быть в голосовом канале, чтобы использовать эту команду!",
                                            discord.Color.red())
            await ctx.respond(embed=embed)
            return

        channel = ctx.author.voice.channel

        if ctx.voice_client and ctx.voice_client.channel != channel:
            old_channel = ctx.voice_client.channel.name
            await ctx.voice_client.disconnect()
            self.queue_manager.clear_queue()
            await channel.connect()
            embed = await self.create_embed("🔄 Смена канала",
                                            f"Я покинул канал **{old_channel}** и подключился к **{channel.name}**!")
            await ctx.respond(embed=embed)
        elif not ctx.voice_client:
            await channel.connect()

        if not ctx.voice_client or not ctx.voice_client.is_connected():
            embed = await self.create_embed("❌ Ошибка",
                                            "Не удалось подключиться к голосовому каналу. Попробуйте позже.",
                                            discord.Color.red())
            await ctx.respond(embed=embed)
            return

        await self.add_to_queue(url)

        if not ctx.voice_client.is_playing():
            await self.play_next_track()

    @commands.slash_command(name="queue", description="Показать текущую очередь")
    async def show_queue(self, ctx):
        if not self.queue_manager.is_empty() or self.current_playing:
            queue_pages = []
            items_per_page = 10

            for i in range(0, len(self.queue_manager.queue), items_per_page):
                page_items = self.queue_manager.queue[i:i + items_per_page]
                embed = discord.Embed(title="🎶 Текущая очередь", color=discord.Color.blue())
                embed.set_thumbnail(url="https://i.imgur.com/nVFj1iD.png")  # Replace with your bot's logo URL

                if self.current_playing and i == 0:
                    embed.add_field(name="▶️ Сейчас играет", value=f"**{self.current_playing}**", inline=False)

                for idx, track in enumerate(page_items, i + 1):
                    embed.add_field(name=f"{idx}. {track['info']['title']}",
                                    value=f"[🔗]({track['info']['original_url']}) | ⏱️ {self.format_duration(track['info'].get('duration', 0))}",
                                    inline=False)

                embed.set_footer(
                    text=f"Страница {i // items_per_page + 1} из {-(-len(self.queue_manager.queue) // items_per_page)} | 🎵 Музыкальный бот")
                queue_pages.append(embed)

            if queue_pages:
                paginator = discord.ui.View()
                paginator.add_item(
                    discord.ui.Button(label="⬅️ Предыдущая", style=discord.ButtonStyle.primary, custom_id="previous"))
                paginator.add_item(
                    discord.ui.Button(label="Следующая ➡️", style=discord.ButtonStyle.primary, custom_id="next"))

                message = await ctx.respond(embed=queue_pages[0], view=paginator)

                current_page = 0

                async def button_callback(interaction):
                    nonlocal current_page
                    if interaction.custom_id == "previous":
                        current_page = (current_page - 1) % len(queue_pages)
                    elif interaction.custom_id == "next":
                        current_page = (current_page + 1) % len(queue_pages)

                    await interaction.response.edit_message(embed=queue_pages[current_page])

                paginator.children[0].callback = button_callback
                paginator.children[1].callback = button_callback
            else:
                embed = await self.create_embed("Текущая очередь", "В очереди нет треков, но сейчас что-то играет.")
                await ctx.respond(embed=embed)
        else:
            embed = await self.create_embed("Очередь пуста", "Добавьте треки с помощью команды **/play**!")
            await ctx.respond(embed=embed)

    @commands.slash_command(name="skip_tracks", description="Скипнуть n треков")
    async def skip_tracks(self, ctx, num_tracks: int):
        if num_tracks <= 0:
            await ctx.respond("Количество треков должно быть больше нуля")
            return

        if ctx.voice_client and ctx.voice_client.is_playing():
            skipped = 0
            for _ in range(num_tracks):
                if not self.queue_manager.is_empty():
                    self.queue_manager.get_next()
                    skipped += 1
                else:
                    break

            ctx.voice_client.stop()
            embed = await self.create_embed("⏭️ Треки пропущены", f"Пропущено {skipped} треков!")
            await ctx.respond(embed=embed)
        else:
            embed = await self.create_embed("❌ Ошибка", "В данный момент ничего не играет", color=discord.Color.red())
            await ctx.respond(embed=embed)

    @commands.slash_command(name="skip", description="Пропустить текущий трек")
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            embed = await self.create_embed("⏭️ Трек пропущен", "Переходим к следующему треку в очереди!")
            await ctx.respond(embed=embed)
        else:
            embed = await self.create_embed("❌ Ошибка", "Сейчас ничего не играет", color=discord.Color.red())
            await ctx.respond(embed=embed)

    @commands.slash_command(name="pause", description="Приостановить воспроизведение")
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            embed = await self.create_embed("⏸️ Пауза", "Музыка приостановлена. Используйте /resume, чтобы продолжить.")
            await ctx.respond(embed=embed)
        else:
            embed = await self.create_embed("❌ Ошибка", "Нечего ставить на паузу!", color=discord.Color.red())
            await ctx.respond(embed=embed)

    @commands.slash_command(name="resume", description="Возобновить воспроизведение")
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            embed = await self.create_embed("▶️ Возобновление", "Музыка снова играет!")
            await ctx.respond(embed=embed)
        else:
            embed = await self.create_embed("❌ Ошибка", "Нечего возобновлять!", color=discord.Color.red())
            await ctx.respond(embed=embed)

    @commands.slash_command(name="stop", description="Остановить воспроизведение и очистить очередь")
    async def stop(self, ctx):
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
            self.queue_manager.clear_queue()
            self.last_played = None
            embed = await self.create_embed("🛑 Остановлено",
                                            "Воспроизведение остановлено, очередь очищена. До новых встреч!")
            await ctx.respond(embed=embed)
        else:
            embed = await self.create_embed("❌ Ошибка", "Я не нахожусь в голосовом канале!",
                                            color=discord.Color.red())
            await ctx.respond(embed=embed)

    @commands.slash_command(name="now_playing", description="Показать информацию о текущем треке")
    async def now_playing(self, ctx):
        if self.current_playing:
            embed = await self.create_embed("🎵 Сейчас играет", f"🎶 {self.current_playing}")
            await ctx.respond(embed=embed)
        else:
            embed = await self.create_embed("❌ Ошибка", "Сейчас ничего не играет", color=discord.Color.red())
            await ctx.respond(embed=embed)


def setup(bot):
    bot.add_cog(Music(bot))