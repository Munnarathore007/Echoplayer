import discord
from discord.ext import commands
import yt_dlp
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from dotenv import load_dotenv
import os

load_dotenv()

# --- CONFIGURATION ---
TOKEN = os.getenv("MTUxMzU0Njc4NjAwMDg2NzUzOQ.GE_w4v.r2VjWjwoGqzQPwYwXhVBmlg1okQmo4YKU7Je1I")
SPOTIFY_CLIENT_ID = os.getenv("b12ba2f86f4649a7a352c5f2f54d00b6")
SPOTIFY_CLIENT_SECRET = os.getenv("11a0683fe2f54a0fb9588aa69755f997")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Spotify setup
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=b12ba2f86f4649a7a352c5f2f54d00b6,
    client_secret=b12ba2f86f4649a7a352c5f2f54d00b6
))

# Music queue (per guild)
queues = {}
voice_clients = {}

# yt-dlp options for best audio
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'extractaudio': True,
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

def get_youtube_url(query: str) -> str:
    """Search YouTube with yt-dlp and return the first video URL."""
    with yt_dlp.YoutubeDL({'quiet': True, 'format': 'bestaudio/best', 'noplaylist': True}) as ydl:
        info = ydl.extract_info(f"ytsearch:{query}", download=False)
        if 'entries' in info:
            return info['entries'][0]['webpage_url']
        return info['webpage_url']

def resolve_spotify(url_or_id: str) -> str:
    """Resolve a Spotify track or playlist link into a YouTube search string.
       Returns a tuple (type, data) where type is 'track' or 'playlist'."""
    if 'track' in url_or_id:
        track = sp.track(url_or_id)
        name = track['name']
        artists = ', '.join(a['name'] for a in track['artists'])
        return 'track', f"{name} {artists}"
    elif 'playlist' in url_or_id:
        playlist = sp.playlist(url_or_id)
        tracks = playlist['tracks']['items']
        search_terms = []
        for item in tracks:
            t = item['track']
            if t:
                name = t['name']
                artists = ', '.join(a['name'] for a in t['artists'])
                search_terms.append(f"{name} {artists}")
        return 'playlist', search_terms
    else:
        # Could be an album, etc. – treat as track search
        return 'track', url_or_id

async def play_next(guild_id):
    """Play the next song in the queue."""
    if guild_id in queues and queues[guild_id]:
        url = queues[guild_id].pop(0)
        voice_client = voice_clients.get(guild_id)
        if voice_client and voice_client.is_connected():
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                url2 = info['url']
                title = info.get('title', 'Unknown')
            source = await discord.FFmpegOpusAudio.from_probe(url2, **FFMPEG_OPTIONS)
            voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild_id), bot.loop))
            # Send now playing message
            channel = voice_client.channel
            # We can store a text channel for updates, but here we just print to console.
            print(f"Now playing: {title}")
        else:
            # Cleanup if disconnected
            if guild_id in queues:
                del queues[guild_id]
            if guild_id in voice_clients:
                del voice_clients[guild_id]
    else:
        # Queue empty – disconnect after optional timeout
        if guild_id in voice_clients:
            await asyncio.sleep(300)  # wait 5 min before disconnecting (optional)
            if guild_id in voice_clients and not voice_clients[guild_id].is_playing():
                await voice_clients[guild_id].disconnect()
                del voice_clients[guild_id]
                if guild_id in queues:
                    del queues[guild_id]

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    await bot.change_presence(activity=discord.Game(name="Echoplayer 🎵"))

@bot.command(name='play', aliases=['p'])
async def play(ctx, *, query: str):
    """Play a song from YouTube or Spotify. Usage: !play <link or search term>"""
    voice_state = ctx.author.voice
    if not voice_state or not voice_state.channel:
        await ctx.send("You must be in a voice channel first!")
        return

    channel = voice_state.channel
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if not voice_client:
        voice_client = await channel.connect()
        voice_clients[ctx.guild.id] = voice_client
    elif voice_client.channel != channel:
        await voice_client.move_to(channel)

    # Initialize queue for guild if not present
    if ctx.guild.id not in queues:
        queues[ctx.guild.id] = []

    # Determine if query is a Spotify link
    if "spotify.com" in query or "spotify:" in query:
        # Extract ID
        if "spotify:" in query:
            # URI like spotify:track:xxxx
            parts = query.split(":")
            spotify_id = parts[-1]
            query_type = parts[-2] if len(parts) >= 3 else "track"
            url_id = f"spotify:{query_type}:{spotify_id}"
        else:
            # URL
            from urllib.parse import urlparse
            parsed = urlparse(query)
            path_parts = parsed.path.strip('/').split('/')
            spotify_id = path_parts[-1]
            query_type = path_parts[-2]
            url_id = f"spotify:{query_type}:{spotify_id}"

        result = resolve_spotify(url_id)
        if result[0] == 'track':
            search_term = result[1]
            youtube_url = get_youtube_url(search_term)
            queues[ctx.guild.id].append(youtube_url)
            await ctx.send(f"Added to queue: **{search_term}**")
        elif result[0] == 'playlist':
            search_terms = result[1]
            for term in search_terms:
                yt_url = get_youtube_url(term)
                queues[ctx.guild.id].append(yt_url)
            await ctx.send(f"Added {len(search_terms)} tracks from Spotify playlist to the queue.")
    else:
        # YouTube link or search term
        if "youtube.com" in query or "youtu.be" in query:
            yt_url = query
        else:
            yt_url = get_youtube_url(query)
        queues[ctx.guild.id].append(yt_url)
        await ctx.send(f"Added to queue: {query}")

    # If not currently playing, start playing
    if not voice_client.is_playing():
        await play_next(ctx.guild.id)

@bot.command(name='skip')
async def skip(ctx):
    """Skip the current song."""
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("Skipped ⏭")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name='pause')
async def pause(ctx):
    """Pause the current song."""
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await ctx.send("Paused ⏸")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name='resume')
async def resume(ctx):
    """Resume the paused song."""
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await ctx.send("Resumed ▶")
    else:
        await ctx.send("Nothing is paused.")

@bot.command(name='queue', aliases=['q'])
async def queue_list(ctx):
    """Show the current queue."""
    guild_id = ctx.guild.id
    if guild_id in queues and queues[guild_id]:
        q = queues[guild_id]
        display = "\n".join(f"{i+1}. {url}" for i, url in enumerate(q[:10]))
        await ctx.send(f"**Queue ({len(q)} songs):**\n{display}")
    else:
        await ctx.send("Queue is empty.")

@bot.command(name='disconnect', aliases=['leave', 'dc'])
async def disconnect(ctx):
    """Disconnect the bot from voice."""
    voice_client = ctx.voice_client
    if voice_client:
        await voice_client.disconnect()
        if ctx.guild.id in voice_clients:
            del voice_clients[ctx.guild.id]
        if ctx.guild.id in queues:
            del queues[ctx.guild.id]
        await ctx.send("Disconnected 👋")
    else:
        await ctx.send("I'm not in a voice channel.")

bot.run(MTUxMzU0Njc4NjAwMDg2NzUzOQ.GE_w4v.r2VjWjwoGqzQPwYwXhVBmlg1okQmo4YKU7Je1I)
