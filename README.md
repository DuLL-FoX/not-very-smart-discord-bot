# Discord Bot Project

A versatile Discord bot providing music playback, daily destiny testing, and Ukrainian power outage monitoring capabilities.

## Features

### Music Bot
Play and manage music in your Discord server with support for multiple platforms:
- **Platform Support**: Play music from YouTube and Spotify
- **Queue Management**: Add, view, and manage your music queue
- **Playback Controls**: Play, pause, resume, skip, and stop playback
- **Now Playing**: Display current track information

### Test Your Destiny (TYD)
A fun daily luck-testing feature for server members:
- **Daily Command**: Users can test their luck once per day
- **Temporary Roles**: Assigns roles based on random outcomes
- **Customizable Messages**: Different messages for different result ranges
- **Owner Controls**: Admin commands for cooldown management and role purging

### DTEK Power Outage Monitor
Real-time monitoring of power outages in Ukraine (ДТЕК КРЕМ and ДТЕК КЕМ regions):
- **Address Monitoring**: Track power status for multiple addresses
- **Automatic Updates**: Status updates every 15 minutes
- **Live Embeds**: Discord embeds that update in real-time
- **Queue Information**: Shows your power outage queue and schedule
- **Multi-Region Support**: Supports both ДТЕК КРЕМ (Kyiv Oblast) and ДТЕК КЕМ (Kyiv City)
- **Hourly Schedule**: Visual timeline showing power availability throughout the day

## Setup

### Prerequisites
- Python 3.13 or higher
- FFmpeg (installed automatically in Docker; install locally if running without Docker)
- PostgreSQL database

### Environment Variables
Create a `.env` file in the root directory with the following variables:
```
DISCORD_TOKEN=your_discord_bot_token
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
DB_NAME=your_database_name
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=your_database_host
# Optional logging level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO
```

### Installation

#### Local Installation
1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up the PostgreSQL database
4. Create a `.env` file with your configuration
5. Run the bot:
   ```bash
   python main.py
   ```

#### Docker Installation
See the [Docker section](#docker) below for containerized deployment.

### Startup Information
On startup, the bot logs:
- Python logger initialization with configured `LOG_LEVEL`
- Bot identity, guild count, latency, loaded cogs and slash commands
- Database connection ping and applied migrations
- FFmpeg presence/version, yt-dlp and spotipy versions
- Spotify credentials status

## Commands

### Music Commands
- `/play <url>` - Play a song from YouTube or Spotify
- `/queue` - Display the current music queue
- `/skip` - Skip the current track
- `/pause` - Pause playback
- `/resume` - Resume playback
- `/stop` - Stop playback and clear the queue
- `/now_playing` - Show information about the current track

### TYD Commands
- `/tyd` - Test your destiny (daily command with 24-hour cooldown)

#### TYD Owner Commands (Bot Owner Only)
- `/tyd_owner reset_cooldown [user]` - Reset `/tyd` cooldown for a user (defaults to self)
- `/tyd_owner cooldown_status [user]` - Show remaining `/tyd` cooldown for a user
- `/tyd_owner purge_expired [user]` - Remove expired TYD roles for a user or scan guild

Note: These maintenance commands are grouped under `tyd_owner` and are enforced to only run for the bot owner. Responses are ephemeral to avoid cluttering channels.

### DTEK Commands (Administrator Only)
All DTEK commands require Administrator permissions.

- `/dtek add_address` - Add an address to monitor for power outages
  - `region` - ДТЕК region (КРЕМ or КЕМ)
  - `street` - Street name in Ukrainian (e.g., "вул. Васильківська")
  - `house` - House number (e.g., "9Г")
  - `label` - Friendly display name for this address
  - `city` - City name (required for КРЕМ, not needed for КЕМ)
  - `channel` - Channel for status updates (optional, defaults to current channel)

- `/dtek remove_address <label>` - Remove a monitored address
- `/dtek list_addresses` - List all monitored addresses for this server
- `/dtek status` - Show current power status for all monitored addresses
- `/dtek refresh` - Force refresh power status for all addresses
- `/dtek set_channel <label> <channel>` - Change the channel where status updates are displayed
- `/dtek task_status` - Check the status of the automatic update task
- `/dtek restart_task` - Restart the automatic update task if it stopped

## Docker

A Dockerfile is provided for easy deployment. The image does not bake secrets; pass them at runtime with `--env-file`.

### Build

#### Basic Build
```bash
docker build -t not-very-smart-discord-bot:latest .
```

#### Multi-Architecture Builds
For deploying to different platforms (e.g., ARM64 for Raspberry Pi):

```bash
# ARM64 only (loads into local Docker)
docker buildx build --platform linux/arm64 -t not-very-smart-discord-bot:arm64 --load .

# Multi-arch build and push to registry
docker buildx build --platform linux/amd64,linux/arm64 -t <your-registry>/not-very-smart-discord-bot:latest --push .
```

### Run

```bash
docker run --rm -it \
  --env-file .env \
  -v ${PWD}/data:/app/data \
  -v ${PWD}/downloads:/app/downloads \
  --name discord-bot not-very-smart-discord-bot:latest
```

**Important Notes:**
- Do **not** copy `.env` into the image. Always use `--env-file` at runtime.
- `.dockerignore` excludes secrets and local clutter by default.
- The Dockerfile includes necessary dependencies for web scraping (for DTEK monitoring).

### Production Deployment with Docker Compose

`docker-compose.yml` is included for a simpler, persistent production setup.

#### Commands
```bash
# First run (creates and starts)
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down

# Update to latest image and restart
docker compose pull && docker compose up -d
```

#### Default Configuration
By default, Docker Compose:
- Uses `dullfox/not-very-smart-discord-bot:latest`
- Reads environment variables from `.env`
- Mounts `./data` and `./downloads` into the container
- Restarts unless stopped
- Rotates logs (max 10MB per file, 3 files)

## Project Structure

```
.
├── main.py                 # Bot initialization and event handlers
├── cogs/                   # Bot command modules (cogs)
│   ├── music.py           # Music playback commands and functionality
│   ├── tyd.py             # Test Your Destiny feature
│   └── dtek/              # DTEK power outage monitoring
│       ├── cog.py         # Main cog with slash commands
│       ├── constants.py   # Region configurations
│       ├── models.py      # Data models
│       ├── scraper_service.py  # Web scraping logic
│       └── embed_builder.py    # Discord embed formatting
├── utils/
│   ├── database.py        # Database connection and queries
│   └── music_utils.py     # YouTube and Spotify utilities
├── migrations/            # SQL migrations (applied automatically on startup)
│   ├── 001_init.sql       # Initial schema (roles, phrases)
│   └── 002_dtek_addresses.sql  # DTEK monitoring schema
├── data/                  # Runtime data directory (mounted as volume in Docker)
├── downloads/             # Temporary audio file storage
├── Dockerfile             # Docker image configuration
├── docker-compose.yml     # Docker Compose configuration
└── requirements.txt       # Python dependencies
```

## Database Migrations and Management

This bot supports automatic SQL migrations applied on startup.

### How Migrations Work
- Migrations are stored in the `migrations/` directory as sequential `.sql` files (e.g., `001_init.sql`, `002_dtek_addresses.sql`)
- On startup, the bot applies any new migrations not yet recorded in `schema_migrations`
- Applied migrations are tracked in the `schema_migrations` table

### Database Tables

#### TYD Feature
- `schema_migrations` - Tracks applied migrations
  - `version` (TEXT, PRIMARY KEY)
  - `applied_at` (TIMESTAMP)
- `roles` - User role assignments
  - `user_id` (BIGINT)
  - `role` (TEXT)
  - `time_assigned` (TIMESTAMP)
  - `expiration` (TIMESTAMP)
- `phrases` - Customizable messages for TYD results
  - `id` (SERIAL)
  - `range_key` (TEXT) - e.g., "0", "50", "2-10", "30-49"
  - `message` (TEXT)

#### DTEK Feature
- `dtek_addresses` - Monitored addresses for power outages
  - `id` (SERIAL, PRIMARY KEY)
  - `region` (TEXT) - 'krem' or 'kem'
  - `city` (TEXT) - City in Ukrainian
  - `street` (TEXT) - Street in Ukrainian
  - `house` (TEXT) - House number
  - `label` (TEXT) - Friendly display name
  - `guild_id` (BIGINT) - Discord guild ID
  - `channel_id` (BIGINT) - Discord channel ID for updates
  - `message_id` (BIGINT) - Discord message ID (for live updates)
  - `created_at` (TIMESTAMP)
  - `updated_at` (TIMESTAMP)

### Adding or Updating TYD Phrases

1. Create a new SQL file in `migrations/`, incrementing the number (e.g., `003_add_funny_phrases.sql`)
2. Insert phrases with placeholders:

```sql
-- 003_add_funny_phrases.sql
INSERT INTO phrases(range_key, message) VALUES
('2-10', 'Сегодня удача на твоей стороне, {user_mention}!'),
('78-99', '{user_mention}, ты почти у вершины! {random_number} это почти 100.');
```

3. Restart the bot; the migration will be applied automatically

#### Available Placeholders
- `{user_mention}` - Mentions the user
- `{bot_mention}` - Mentions the bot
- `{random_number}` - The rolled number (0–101)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is provided as-is for educational and personal use.
