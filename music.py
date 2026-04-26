import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
import asyncio
import random
from collections import deque

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET")
))

YDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'noplaylist': False,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
    }],
}

FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

def format_duration(seconds):
    if not seconds:
        return "Unknown"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{secs:02}"
    return f"{minutes:02}:{secs:02}"

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = deque()
        self.current = None
        self.loop = False
        self.shuffle = False
        self.volume = 0.5
        self._timeout_task = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel.name != "music":
            await interaction.response.send_message(
                "❌ DJ Doof only works in the **#music** channel!", ephemeral=True
            )
            return False
        return True

    async def start_timeout(self, interaction):
        await asyncio.sleep(600)
        vc = interaction.guild.voice_client
        if vc and not vc.is_playing() and not self.queue:
            self.queue.clear()
            self.current = None
            await vc.disconnect()
            await interaction.channel.send("👋 No songs in the queue for 10 minutes, disconnecting!")

    def get_spotify_tracks(self, url):
        if "track" in url:
            track = sp.track(url)
            return [f"{track['name']} {track['artists'][0]['name']}"]
        elif "playlist" in url:
            results = sp.playlist_tracks(url)
            return [
                f"{item['track']['name']} {item['track']['artists'][0]['name']}"
                for item in results['items'] if item['track']
            ]
        elif "album" in url:
            results = sp.album_tracks(url)
            return [
                f"{item['name']} {item['artists'][0]['name']}"
                for item in results['items']
            ]
        return []

    async def get_soundcloud_playlist(self, url):
        loop = asyncio.get_event_loop()
        ydl_opts = {'quiet': True, 'extract_flat': True, 'noplaylist': False}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            if info and 'entries' in info:
                return [
                    {'title': e.get('title', 'Unknown'), 'url': e.get('url', url)}
                    for e in info['entries'] if e
                ], info.get('title', 'SoundCloud Playlist')
        return [], 'SoundCloud Playlist'

    async def get_youtube_playlist(self, url):
        loop = asyncio.get_event_loop()
        ydl_opts = {'quiet': True, 'extract_flat': True, 'noplaylist': False}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            if info and 'entries' in info:
                return [
                    {'title': e.get('title', 'Unknown'), 'url': e.get('url', '')}
                    for e in info['entries'] if e
                ], info.get('title', 'YouTube Playlist')
        return [], 'YouTube Playlist'

    async def suggest_query(self, query):
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            results = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch5:{query}", download=False))
            if results and 'entries' in results:
                return [entry.get('title', 'Unknown') for entry in results['entries'][:5]]
        return []

    async def get_audio(self, query):
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))
            if 'entries' in info:
                info = info['entries'][0]
            return {
                'url': info['url'],
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'webpage_url': info.get('webpage_url', ''),
                'thumbnail': info.get('thumbnail', None),
            }

    async def play_next(self, interaction):
        if self.loop and self.current:
            self.queue.appendleft(self.current)

        if not self.queue:
            self.current = None
            if self._timeout_task:
                self._timeout_task.cancel()
            self._timeout_task = asyncio.ensure_future(self.start_timeout(interaction))
            return

        if self.shuffle:
            idx = random.randint(0, len(self.queue) - 1)
            queue_list = list(self.queue)
            song = queue_list.pop(idx)
            self.queue = deque(queue_list)
        else:
            song = self.queue.popleft()

        self.current = song
        query = song['query']
        requested_by = song['requested_by']

        track = await self.get_audio(query)

        vc = interaction.guild.voice_client
        if vc:
            if self._timeout_task:
                self._timeout_task.cancel()
                self._timeout_task = None

            source = discord.FFmpegPCMAudio(track['url'], **FFMPEG_OPTS)
            source = discord.PCMVolumeTransformer(source, volume=self.volume)
            vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(
                self.play_next(interaction), self.bot.loop))

            embed = discord.Embed(
                title="Now Playing 🎵",
                description=f"**[{track['title']}]({track['webpage_url']})**",
                color=discord.Color.blurple()
            )
            if track['thumbnail']:
                embed.set_thumbnail(url=track['thumbnail'])
            embed.add_field(name="Duration", value=format_duration(track['duration']), inline=True)
            embed.add_field(name="Requested by", value=requested_by, inline=True)
            embed.add_field(name="Songs in queue", value=str(len(self.queue)), inline=True)
            await interaction.channel.send(embed=embed)

    @app_commands.command(name="play", description="Play a song or playlist from YouTube, Spotify, or SoundCloud")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        if not interaction.user.voice:
            await interaction.followup.send("You need to be in a voice channel!")
            return

        vc = interaction.guild.voice_client
        if not vc:
            vc = await interaction.user.voice.channel.connect()

        requester = interaction.user.display_name

        # --- Spotify (track, playlist, album) ---
        if "spotify.com" in query:
            tracks = self.get_spotify_tracks(query)
            if not tracks:
                await interaction.followup.send("Couldn't find anything on Spotify!")
                return
            for t in tracks:
                self.queue.append({'query': t, 'requested_by': requester})
            label = "track" if len(tracks) == 1 else f"**{len(tracks)}** songs"
            embed = discord.Embed(
                title="Spotify Added 🎵",
                description=f"Queued {label} from Spotify!",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Requested by {requester}")
            await interaction.followup.send(embed=embed)
            if not vc.is_playing():
                await self.play_next(interaction)
            return

        # --- SoundCloud playlist/set ---
        if "soundcloud.com" in query and ("/sets/" in query or "/likes" in query or "/tracks" in query):
            tracks, playlist_title = await self.get_soundcloud_playlist(query)
            if tracks:
                for t in tracks:
                    self.queue.append({'query': t['url'], 'requested_by': requester})
                embed = discord.Embed(
                    title="SoundCloud Playlist Added 🎵",
                    description=f"**{playlist_title}**\nQueued **{len(tracks)}** songs!",
                    color=discord.Color.orange()
                )
                embed.set_footer(text=f"Requested by {requester}")
                await interaction.followup.send(embed=embed)
                if not vc.is_playing():
                    await self.play_next(interaction)
                return

        # --- YouTube playlist ---
        if query.startswith("http") and ("youtube.com/playlist" in query or "list=" in query):
            tracks, playlist_title = await self.get_youtube_playlist(query)
            if tracks:
                for t in tracks:
                    self.queue.append({'query': t['url'] or t['title'], 'requested_by': requester})
                embed = discord.Embed(
                    title="YouTube Playlist Added 📋",
                    description=f"**{playlist_title}**\nQueued **{len(tracks)}** songs!",
                    color=discord.Color.red()
                )
                embed.set_footer(text=f"Requested by {requester}")
                await interaction.followup.send(embed=embed)
                if not vc.is_playing():
                    await self.play_next(interaction)
                return

        # --- Single song (search or direct URL) ---
        if not query.startswith("http"):
            suggestions = await self.suggest_query(query)
            if suggestions:
                suggestion_text = "\n".join([f"`{i+1}.` {s}" for i, s in enumerate(suggestions)])
                embed = discord.Embed(
                    title="Did you mean...? 🔍",
                    description=f"Closest matches for **{query}**:\n\n{suggestion_text}\n\nPlaying the top result!",
                    color=discord.Color.blurple()
                )
                await interaction.followup.send(embed=embed)

        song = {'query': query, 'requested_by': requester}
        self.queue.append(song)

        if not vc.is_playing():
            await self.play_next(interaction)
        else:
            try:
                track = await self.get_audio(query)
                embed = discord.Embed(title="Added Track ✅", color=discord.Color.green())
                embed.add_field(name="Track", value=f"**[{track['title']}]({track['webpage_url']})**", inline=False)
                embed.add_field(name="Duration", value=format_duration(track['duration']), inline=True)
                embed.add_field(name="Position in queue", value=str(len(self.queue)), inline=True)
                if track['thumbnail']:
                    embed.set_thumbnail(url=track['thumbnail'])
                embed.set_footer(text=f"Requested by {requester}")
                await interaction.followup.send(embed=embed)
            except Exception:
                await interaction.followup.send(f"Added to queue: **{query}**")

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("Skipped! ⏭️")
        else:
            await interaction.response.send_message("Nothing is playing!")

    @app_commands.command(name="pause", description="Pause the current song")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("Paused ⏸️")
        else:
            await interaction.response.send_message("Nothing is playing!")

    @app_commands.command(name="resume", description="Resume the current song")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Resumed ▶️")
        else:
            await interaction.response.send_message("Nothing is paused!")

    @app_commands.command(name="stop", description="Stop music and clear the queue")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            self.queue.clear()
            self.current = None
            if self._timeout_task:
                self._timeout_task.cancel()
                self._timeout_task = None
            vc.stop()
            await vc.disconnect()
            await interaction.response.send_message("Stopped and disconnected 👋")
        else:
            await interaction.response.send_message("I'm not in a voice channel!")

    @app_commands.command(name="queue", description="Show the current queue")
    async def show_queue(self, interaction: discord.Interaction):
        if not self.queue and not self.current:
            await interaction.response.send_message("The queue is empty!")
            return

        embed = discord.Embed(title="DJ Doof's Queue 🎶", color=discord.Color.blurple())
        if self.current:
            embed.add_field(name="Now Playing", value=f"{self.current['query']} — *{self.current['requested_by']}*", inline=False)
        queue_list = list(self.queue)[:10]
        if queue_list:
            lines = [f"`{i+1}.` {s['query']} — *{s['requested_by']}*" for i, s in enumerate(queue_list)]
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        if len(self.queue) > 10:
            embed.set_footer(text=f"...and {len(self.queue) - 10} more songs")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shuffle", description="Toggle shuffle mode")
    async def toggle_shuffle(self, interaction: discord.Interaction):
        self.shuffle = not self.shuffle
        state = "on 🔀" if self.shuffle else "off"
        await interaction.response.send_message(f"Shuffle is now **{state}**")

    @app_commands.command(name="loop", description="Toggle loop mode")
    async def toggle_loop(self, interaction: discord.Interaction):
        self.loop = not self.loop
        state = "on 🔁" if self.loop else "off"
        await interaction.response.send_message(f"Loop is now **{state}**")

    @app_commands.command(name="volume", description="Set the volume (0-100)")
    async def set_volume(self, interaction: discord.Interaction, level: int):
        if not 0 <= level <= 100:
            await interaction.response.send_message("Volume must be between 0 and 100!")
            return
        self.volume = level / 100
        vc = interaction.guild.voice_client
        if vc and vc.source:
            vc.source.volume = self.volume
        await interaction.response.send_message(f"Volume set to **{level}%** 🔊")

    @app_commands.command(name="nowplaying", description="Show the currently playing song")
    async def nowplaying(self, interaction: discord.Interaction):
        if not self.current:
            await interaction.response.send_message("Nothing is playing right now!")
            return
        embed = discord.Embed(
            title="Now Playing 🎵",
            description=f"**{self.current['query']}**",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Requested by", value=self.current['requested_by'], inline=True)
        embed.add_field(name="Loop", value="🔁 On" if self.loop else "Off", inline=True)
        embed.add_field(name="Shuffle", value="🔀 On" if self.shuffle else "Off", inline=True)
        embed.add_field(name="Volume", value=f"🔊 {int(self.volume * 100)}%", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Show all DJ Doof commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="DJ Doof Commands 🎧",
            description="*Behold! The Music-inator! Here's everything I can do:*",
            color=discord.Color.blurple()
        )
        embed.add_field(name="🎵 Playback", value="""
`/play <song or URL>` — Play from YouTube, Spotify, or SoundCloud
`/pause` — Pause the current song
`/resume` — Resume playback
`/skip` — Skip to the next song
`/stop` — Stop music and disconnect
`/nowplaying` — Show the current song
""", inline=False)
        embed.add_field(name="📋 Queue", value="""
`/queue` — Show the current queue
`/shuffle` — Toggle shuffle mode
`/loop` — Toggle loop mode
`/volume <0-100>` — Set the volume
""", inline=False)
        embed.add_field(name="💡 Tips", value="""
• Paste a YouTube, Spotify, or SoundCloud playlist URL to queue everything
• Spotify tracks, playlists, and albums are all supported
• SoundCloud sets and likes pages are supported
• You must be in a voice channel to use playback commands
• Bot disconnects after 10 minutes of inactivity
""", inline=False)
        embed.set_footer(text="Curse you, Perry the Platypus, for interrupting my playlist. 🦆")
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(MusicCog(bot))