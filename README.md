# DJ Doof 🎧

> *Behold! The Music-inator!* A Discord music bot that plays from YouTube, Spotify, and SoundCloud with full queue controls, shuffle, loop, and volume.

---

## Features

- Play music from YouTube, Spotify, and SoundCloud
- Queue system with shuffle and loop
- Volume control (0–100)
- Pause, resume, skip, and stop
- Now playing display with queue info
- Slash command support

---

## Requirements

- Python 3.10+
- FFmpeg installed and added to PATH
- A Discord bot token
- A Spotify Developer account (Client ID + Secret)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/djdoof.git
cd djdoof
```

### 2. Create and activate a virtual environment

```bash
# Windows
py -m venv venv
venv\Scripts\activate

# Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install discord.py yt-dlp spotipy PyNaCl python-dotenv
```

### 4. Install FFmpeg

- Download from https://www.gyan.dev/ffmpeg/builds/ (grab `ffmpeg-release-essentials.zip`)
- Extract it and move the folder somewhere permanent (e.g. `C:\ffmpeg\`)
- Add the `bin` folder to your system PATH
- Test with `ffmpeg -version` in a new terminal

### 5. Create your `.env` file

Create a file called `.env` in the project root and fill in your credentials:

```
DISCORD_TOKEN=your_discord_bot_token_here
SPOTIFY_CLIENT_ID=your_spotify_client_id_here
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret_here
```

#### Getting your Discord token
1. Go to https://discord.com/developers/applications
2. Create a new application and go to the **Bot** tab
3. Click **Reset Token** and copy it
4. Under **Privileged Gateway Intents**, enable all three intents
5. Invite the bot using **OAuth2 → URL Generator** with `bot` + `applications.commands` scopes and permissions: `Connect`, `Speak`, `Send Messages`, `Embed Links`, `Read Message History`

#### Getting your Spotify credentials
1. Go to https://developer.spotify.com/dashboard
2. Create an app with redirect URI `http://127.0.0.1:8888/callback`
3. Copy your **Client ID** and **Client Secret** from the app settings

### 6. Run the bot

```bash
py main.py
```

You should see:
```
Synced 10 command(s)
DJ Doof is online and ready to drop bangers!
```

---

## Commands

| Command | Description |
|---|---|
| `/play <song or URL>` | Play a song from YouTube, Spotify, or SoundCloud |
| `/pause` | Pause the current song |
| `/resume` | Resume playback |
| `/skip` | Skip to the next song |
| `/stop` | Stop music and disconnect |
| `/queue` | Show the current queue |
| `/nowplaying` | Show the currently playing song |
| `/shuffle` | Toggle shuffle mode |
| `/loop` | Toggle loop mode |
| `/volume <0-100>` | Set the volume |

---

## Notes

- Spotify links play audio via YouTube search (Spotify does not allow direct audio streaming)
- The bot must be in the same voice channel as you to accept commands
- Keep your `.env` file private — never commit it to GitHub

---

## .gitignore

Make sure to create a `.gitignore` file with the following to keep your credentials safe:

```
.env
venv/
__pycache__/
*.pyc
```

---

*Curse you, Perry the Platypus, for interrupting my playlist.* 🦆
