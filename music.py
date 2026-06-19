import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import random
import urllib.request
import urllib.parse
import json
from collections import deque

YDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'noplaylist': False,
    'extractor_args': {'youtube': {'player_client': ['android_vr']}},
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
        self.current_track = None
        self.loop = False
        self.shuffle = False
        self.volume = 0.05
        self._timeout_task = None
        self.text_channel = None
        self.history = deque(maxlen=10)
        self.skip_votes = set()
        self.autoplay = False
        self.dj_role_name = "DJ"
        self._seek_offset = None

    def has_dj_permission(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        if discord.utils.get(interaction.user.roles, name=self.dj_role_name):
            return True
        vc = interaction.guild.voice_client
        if vc:
            human_members = [m for m in vc.channel.members if not m.bot]
            if len(human_members) <= 1:
                return True
        return False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel.name != "music":
            await interaction.response.send_message(
                "❌ DJ Doof only works in the **#music** channel!", ephemeral=True
            )
            return False
        return True

    async def start_timeout(self, guild):
        await asyncio.sleep(600)
        vc = guild.voice_client
        if vc and not vc.is_playing() and not self.queue:
            self.queue.clear()
            self.current = None
            self.current_track = None
            self.history.clear()
            await vc.disconnect()
            if self.text_channel:
                await self.text_channel.send("✅ Queue is empty! Add more songs with `/play`")

    def get_spotify_tracks(self, url):
        import re
        if "track" in url:
            try:
                oembed_url = f"https://open.spotify.com/oembed?url={url}"
                req = urllib.request.urlopen(oembed_url)
                data = json.loads(req.read().decode())
                title = data.get('title', '')
                return [title] if title else []
            except:
                return []
        elif "playlist" in url or "album" in url:
            try:
                match = re.search(r'spotify\.com/(playlist|album)/([a-zA-Z0-9]+)', url)
                if not match:
                    return []
                content_type = match.group(1)
                content_id = match.group(2)
                embed_url = f"https://open.spotify.com/embed/{content_type}/{content_id}"
                req = urllib.request.Request(embed_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                response = urllib.request.urlopen(req)
                html = response.read().decode('utf-8')
                match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
                if match:
                    data = json.loads(match.group(1))
                    entities = data.get('props', {}).get('pageProps', {}).get('state', {}).get('data', {}).get('entity', {})
                    tracks = []
                    items = entities.get('trackList', []) or entities.get('items', [])
                    for item in items:
                        title = item.get('title', '') or item.get('track', {}).get('name', '')
                        artist = item.get('subtitle', '') or item.get('track', {}).get('artists', [{}])[0].get('name', '')
                        if title:
                            tracks.append(f"{title} {artist}".strip())
                    if tracks:
                        return tracks
            except Exception as e:
                print(f"Spotify scrape error: {e}")
            return []
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
        with yt_dlp.YoutubeDL({
            'quiet': True,
            'extract_flat': True,
            'default_search': 'ytsearch5',
        }) as ydl:
            results = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch5:{query}", download=False))
            if results and 'entries' in results:
                return [entry.get('title', 'Unknown') for entry in results['entries'][:5]]
        return []

    def clean_youtube_url(self, url):
        parsed = urllib.parse.urlparse(url)
        if 'youtube.com' in parsed.netloc and 'watch' in parsed.path:
            params = urllib.parse.parse_qs(parsed.query)
            params.pop('list', None)
            params.pop('index', None)
            clean_query = urllib.parse.urlencode({k: v[0] for k, v in params.items()})
            return urllib.parse.urlunparse(parsed._replace(query=clean_query))
        return url

    async def get_audio(self, query):
        if query.startswith("http"):
            query = self.clean_youtube_url(query)
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

    async def get_autoplay_track(self, last_title):
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'default_search': 'ytsearch3'}) as ydl:
            results = await loop.run_in_executor(
                None, lambda: ydl.extract_info(f"ytsearch3:{last_title}", download=False)
            )
            if results and 'entries' in results:
                entries = [e for e in results['entries'] if e]
                # Pick 2nd result to avoid immediately replaying the same song
                entry = entries[1] if len(entries) > 1 else entries[0]
                return entry.get('url') or entry.get('id')
        return None

    async def play_next(self, guild):
        if self.loop and self.current:
            self.queue.appendleft(self.current)

        if not self.queue and self.autoplay and self.current_track:
            last_title = self.current_track.get('title', '')
            autoplay_query = await self.get_autoplay_track(last_title)
            if autoplay_query:
                self.queue.append({'query': autoplay_query, 'requested_by': 'Autoplay 🎲'})

        if not self.queue:
            self.current = None
            self.current_track = None
            if self.text_channel:
                await self.text_channel.send("✅ Queue is now empty! Add more songs with `/play`")
            if self._timeout_task:
                self._timeout_task.cancel()
            self._timeout_task = asyncio.ensure_future(self.start_timeout(guild))
            return

        if self.shuffle:
            idx = random.randint(0, len(self.queue) - 1)
            queue_list = list(self.queue)
            song = queue_list.pop(idx)
            self.queue = deque(queue_list)
        else:
            song = self.queue.popleft()

        self.current = song
        self.skip_votes = set()
        query = song['query']
        requested_by = song['requested_by']

        track = await self.get_audio(query)
        self.current_track = track

        self.history.append({
            'title': track['title'],
            'webpage_url': track['webpage_url'],
            'requested_by': requested_by,
        })

        if self._seek_offset is not None:
            seek_secs = self._seek_offset
            self._seek_offset = None
            ffmpeg_opts = {
                'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {seek_secs}',
                'options': '-vn'
            }
        else:
            ffmpeg_opts = FFMPEG_OPTS

        vc = guild.voice_client
        if vc:
            if self._timeout_task:
                self._timeout_task.cancel()
                self._timeout_task = None

            source = discord.FFmpegPCMAudio(track['url'], **ffmpeg_opts)
            source = discord.PCMVolumeTransformer(source, volume=self.volume)
            vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(
                self.play_next(guild), self.bot.loop))

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
            await self.text_channel.send(embed=embed)

    # ── Playback commands ──────────────────────────────────────────────────────

    @app_commands.command(name="play", description="Play a song or playlist from YouTube, Spotify, or SoundCloud")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        if not interaction.user.voice:
            await interaction.followup.send("You need to be in a voice channel!")
            return

        vc = interaction.guild.voice_client
        if not vc:
            self.queue.clear()
            self.current = None
            vc = await interaction.user.voice.channel.connect()

        self.text_channel = interaction.channel
        requester = interaction.user.display_name

        if query.startswith("http"):
            query = self.clean_youtube_url(query)

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
            if not vc.is_playing() and not vc.is_paused():
                await self.play_next(interaction.guild)
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
                if not vc.is_playing() and not vc.is_paused():
                    await self.play_next(interaction.guild)
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
                if not vc.is_playing() and not vc.is_paused():
                    await self.play_next(interaction.guild)
                return

        # --- Single song or multi-queue (| separated) ---
        queries = [q.strip() for q in query.split('|') if q.strip()]

        for q in queries:
            self.queue.append({'query': self.clean_youtube_url(q), 'requested_by': requester})

        if len(queries) > 1:
            await interaction.followup.send(f"Added **{len(queries)}** songs to the queue!")
        elif vc.is_playing() or vc.is_paused():
            try:
                track = await self.get_audio(queries[0])
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
        else:
            if not queries[0].startswith("http"):
                suggestions = await self.suggest_query(queries[0])
                if suggestions:
                    suggestion_text = "\n".join([f"`{i+1}.` {s}" for i, s in enumerate(suggestions)])
                    embed = discord.Embed(
                        title="Did you mean...? 🔍",
                        description=f"Closest matches for **{queries[0]}**:\n\n{suggestion_text}\n\nPlaying the top result!",
                        color=discord.Color.blurple()
                    )
                    await interaction.followup.send(embed=embed)

        if not vc.is_playing() and not vc.is_paused():
            await self.play_next(interaction.guild)

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.followup.send("Skipped! ⏭️")
        else:
            await interaction.followup.send("Nothing is playing!")

    @app_commands.command(name="pause", description="Pause the current song")
    async def pause(self, interaction: discord.Interaction):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.followup.send("Paused ⏸️")
        else:
            await interaction.followup.send("Nothing is playing!")

    @app_commands.command(name="resume", description="Resume the current song")
    async def resume(self, interaction: discord.Interaction):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.followup.send("Resumed ▶️")
        else:
            await interaction.followup.send("Nothing is paused!")

    @app_commands.command(name="stop", description="Stop music and clear the queue")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.has_dj_permission(interaction):
            await interaction.followup.send(f"❌ You need the **{self.dj_role_name}** role or be alone in the VC!")
            return
        vc = interaction.guild.voice_client
        if vc:
            self.queue.clear()
            self.current = None
            self.current_track = None
            self.history.clear()
            if self._timeout_task:
                self._timeout_task.cancel()
                self._timeout_task = None
            vc.stop()
            await vc.disconnect()
            await interaction.followup.send("Stopped and disconnected 👋")
        else:
            await interaction.followup.send("I'm not in a voice channel!")

    @app_commands.command(name="replay", description="Restart the current song from the beginning")
    async def replay(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.current:
            await interaction.followup.send("Nothing is playing!")
            return
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.followup.send("Not connected to a voice channel!")
            return
        replay_song = self.current
        # Prepend current to queue; clear self.current so loop logic in play_next won't double-add
        self.queue.appendleft(replay_song)
        self.current = None
        vc.stop()  # after callback fires play_next, which pops our prepended song
        await interaction.followup.send(f"Restarting **{replay_song['query']}**! 🔄")

    @app_commands.command(name="seek", description="Seek to a position in the current song (in seconds)")
    async def seek(self, interaction: discord.Interaction, seconds: int):
        await interaction.response.defer()
        if not self.current:
            await interaction.followup.send("Nothing is playing!")
            return
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.followup.send("Not connected to a voice channel!")
            return
        if seconds < 0:
            await interaction.followup.send("Seek position must be positive!")
            return
        # Prepend current to queue with seek offset; play_next picks up _seek_offset
        self.queue.appendleft(self.current)
        self.current = None
        self._seek_offset = seconds
        vc.stop()
        mins, secs = divmod(seconds, 60)
        await interaction.followup.send(f"Seeking to **{mins:02}:{secs:02}**! ⏩")

    @app_commands.command(name="voteskip", description="Vote to skip the current song (requires 50% of VC members)")
    async def voteskip(self, interaction: discord.Interaction):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.followup.send("Nothing is playing!")
            return
        human_members = [m for m in vc.channel.members if not m.bot]
        needed = (len(human_members) + 1) // 2  # ceiling of 50%
        if interaction.user.id in self.skip_votes:
            await interaction.followup.send("You already voted to skip!")
            return
        self.skip_votes.add(interaction.user.id)
        votes = len(self.skip_votes)
        if votes >= needed:
            self.skip_votes.clear()
            vc.stop()
            await interaction.followup.send(f"Vote passed ({votes}/{needed})! Skipping! ⏭️")
        else:
            await interaction.followup.send(f"Vote to skip: **{votes}/{needed}** votes needed.")

    @app_commands.command(name="lyrics", description="Fetch lyrics for the currently playing song")
    async def lyrics(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.current_track:
            await interaction.followup.send("Nothing is playing!")
            return
        title = self.current_track.get('title', '')
        if ' - ' in title:
            parts = title.split(' - ', 1)
            artist, song_title = parts[0].strip(), parts[1].strip()
        else:
            artist = title
            song_title = title
        try:
            url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(artist)}/{urllib.parse.quote(song_title)}"
            req = urllib.request.urlopen(url, timeout=10)
            data = json.loads(req.read().decode())
            lyrics_text = data.get('lyrics', '').strip()
            if not lyrics_text:
                await interaction.followup.send("No lyrics found for this song.")
                return
            if len(lyrics_text) > 3900:
                lyrics_text = lyrics_text[:3900] + "\n...(truncated)"
            embed = discord.Embed(
                title=f"Lyrics: {title}",
                description=lyrics_text,
                color=discord.Color.blurple()
            )
            await interaction.followup.send(embed=embed)
        except Exception:
            await interaction.followup.send("Couldn't find lyrics for this song.")

    # ── Queue management commands ──────────────────────────────────────────────

    @app_commands.command(name="queue", description="Show the current queue")
    async def show_queue(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.queue and not self.current:
            await interaction.followup.send("The queue is empty!")
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
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="remove", description="Remove a song from the queue by position")
    async def remove(self, interaction: discord.Interaction, position: int):
        await interaction.response.defer()
        if not self.has_dj_permission(interaction):
            await interaction.followup.send(f"❌ You need the **{self.dj_role_name}** role or be alone in the VC!")
            return
        if not self.queue:
            await interaction.followup.send("The queue is empty!")
            return
        if position < 1 or position > len(self.queue):
            await interaction.followup.send(f"Invalid position! Queue has **{len(self.queue)}** songs.")
            return
        queue_list = list(self.queue)
        removed = queue_list.pop(position - 1)
        self.queue = deque(queue_list)
        await interaction.followup.send(f"Removed **{removed['query']}** from position **{position}**.")

    @app_commands.command(name="move", description="Move a song in the queue from one position to another")
    async def move(self, interaction: discord.Interaction, from_pos: int, to_pos: int):
        await interaction.response.defer()
        if not self.has_dj_permission(interaction):
            await interaction.followup.send(f"❌ You need the **{self.dj_role_name}** role or be alone in the VC!")
            return
        n = len(self.queue)
        if not self.queue:
            await interaction.followup.send("The queue is empty!")
            return
        if not (1 <= from_pos <= n and 1 <= to_pos <= n):
            await interaction.followup.send(f"Invalid positions! Queue has **{n}** songs.")
            return
        queue_list = list(self.queue)
        song = queue_list.pop(from_pos - 1)
        queue_list.insert(to_pos - 1, song)
        self.queue = deque(queue_list)
        await interaction.followup.send(f"Moved **{song['query']}** from position **{from_pos}** to **{to_pos}**.")

    @app_commands.command(name="clear", description="Clear the queue without stopping the current song")
    async def clear(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.has_dj_permission(interaction):
            await interaction.followup.send(f"❌ You need the **{self.dj_role_name}** role or be alone in the VC!")
            return
        self.queue.clear()
        await interaction.followup.send("Queue cleared! 🗑️")

    @app_commands.command(name="skipto", description="Skip to a specific position in the queue")
    async def skipto(self, interaction: discord.Interaction, position: int):
        await interaction.response.defer()
        if not self.has_dj_permission(interaction):
            await interaction.followup.send(f"❌ You need the **{self.dj_role_name}** role or be alone in the VC!")
            return
        if not self.queue:
            await interaction.followup.send("The queue is empty!")
            return
        if position < 1 or position > len(self.queue):
            await interaction.followup.send(f"Invalid position! Queue has **{len(self.queue)}** songs.")
            return
        for _ in range(position - 1):
            self.queue.popleft()
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        await interaction.followup.send(f"Skipping to position **{position}**! ⏭️")

    @app_commands.command(name="shuffle", description="Toggle shuffle mode")
    async def toggle_shuffle(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.shuffle = not self.shuffle
        state = "on 🔀" if self.shuffle else "off"
        await interaction.followup.send(f"Shuffle is now **{state}**")

    @app_commands.command(name="loop", description="Toggle loop mode")
    async def toggle_loop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.loop = not self.loop
        state = "on 🔁" if self.loop else "off"
        await interaction.followup.send(f"Loop is now **{state}**")

    @app_commands.command(name="autoplay", description="Toggle autoplay (plays a related song when queue runs out)")
    async def toggle_autoplay(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.autoplay = not self.autoplay
        state = "on 🎲" if self.autoplay else "off"
        await interaction.followup.send(f"Autoplay is now **{state}**")

    @app_commands.command(name="volume", description="Set the volume (0-100)")
    async def set_volume(self, interaction: discord.Interaction, level: int):
        await interaction.response.defer()
        if not 0 <= level <= 100:
            await interaction.followup.send("Volume must be between 0 and 100!")
            return
        self.volume = level / 100
        vc = interaction.guild.voice_client
        if vc and vc.source:
            vc.source.volume = self.volume
        await interaction.followup.send(f"Volume set to **{level}%** 🔊")

    # ── Info commands ──────────────────────────────────────────────────────────

    @app_commands.command(name="nowplaying", description="Show the currently playing song")
    async def nowplaying(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.current:
            await interaction.followup.send("Nothing is playing right now!")
            return
        embed = discord.Embed(
            title="Now Playing 🎵",
            description=f"**{self.current['query']}**",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Requested by", value=self.current['requested_by'], inline=True)
        embed.add_field(name="Loop", value="🔁 On" if self.loop else "Off", inline=True)
        embed.add_field(name="Shuffle", value="🔀 On" if self.shuffle else "Off", inline=True)
        embed.add_field(name="Autoplay", value="🎲 On" if self.autoplay else "Off", inline=True)
        embed.add_field(name="Volume", value=f"🔊 {int(self.volume * 100)}%", inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="history", description="Show the last 10 songs played")
    async def history_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.history:
            await interaction.followup.send("No songs have been played yet!")
            return
        embed = discord.Embed(title="Recently Played 📜", color=discord.Color.blurple())
        lines = []
        for i, h in enumerate(reversed(list(self.history)), 1):
            title = h['title']
            url = h['webpage_url']
            req_by = h['requested_by']
            if url:
                lines.append(f"`{i}.` **[{title}]({url})** — *{req_by}*")
            else:
                lines.append(f"`{i}.` **{title}** — *{req_by}*")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ── Admin commands ─────────────────────────────────────────────────────────

    @app_commands.command(name="setdj", description="Set the DJ role name (Admin only)")
    async def setdj(self, interaction: discord.Interaction, role: str):
        await interaction.response.defer()
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You need **Administrator** permission to use this command!")
            return
        self.dj_role_name = role
        await interaction.followup.send(f"DJ role set to **{role}**! DJ-gated commands will now check for this role.")

    # ── Help ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="help", description="Show all DJ Doof commands")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.defer()
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
`/voteskip` — Vote to skip (needs 50% of VC members)
`/stop` — Stop music and disconnect *(DJ)*
`/replay` — Restart the current song from the beginning
`/seek <seconds>` — Seek to a timestamp in the current song
`/lyrics` — Show lyrics for the current song
`/nowplaying` — Show song info, loop, shuffle, volume
""", inline=False)
        embed.add_field(name="📋 Queue", value="""
`/queue` — Show the current queue
`/remove <pos>` — Remove a song by position *(DJ)*
`/move <from> <to>` — Reorder songs in the queue *(DJ)*
`/clear` — Clear the queue without stopping *(DJ)*
`/skipto <pos>` — Skip to a specific queue position *(DJ)*
`/shuffle` — Toggle shuffle mode
`/loop` — Toggle loop mode
`/autoplay` — Toggle autoplay when queue runs out
`/volume <0-100>` — Set the volume
""", inline=False)
        embed.add_field(name="📜 History", value="""
`/history` — Show the last 10 songs played
""", inline=False)
        embed.add_field(name="⚙️ Admin", value="""
`/setdj <role>` — Change the DJ role name *(Admin)*
""", inline=False)
        embed.add_field(name="💡 Tips", value="""
• Paste a YouTube, Spotify, or SoundCloud playlist URL to queue everything
• Use `|` to queue multiple songs: `/play song1 | song2 | song3`
• Spotify tracks, playlists, and albums are supported (no account needed)
• *(DJ)* commands require the DJ role, Administrator, or being alone in the VC with the bot
• Bot disconnects after 10 minutes of inactivity
""", inline=False)
        embed.set_footer(text="Curse you, Perry the Platypus, for interrupting my playlist. 🦆")
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(MusicCog(bot))
