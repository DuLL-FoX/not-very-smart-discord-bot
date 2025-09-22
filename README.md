# Discord Bot Project

This Discord bot is a versatile application that provides music playback capabilities and a fun "Test Your Destiny" (TYD) feature for server members.

## Features

### Music Bot
- Play music from YouTube and Spotify
- Queue management
- Playback controls (play, pause, resume, skip)
- Display current queue and now playing information

### Test Your Destiny (TYD)
- Daily command to test user's luck
- Assigns temporary roles based on random outcomes
- Customizable messages for different result ranges

## Setup

### Prerequisites
- Python 3.13 or higher
- FFmpeg (installed automatically in Docker image; install locally if running without Docker)
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
1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set up the PostgreSQL database and run the necessary migrations (not provided in the current codebase)

### Running the Bot
```
python main.py
```

On startup the bot logs:
- Python logger init with `LOG_LEVEL`
- Bot identity, guild count, latency, loaded cogs and slash commands
- Database connection ping and applied migrations
- FFmpeg presence/version, yt-dlp and spotipy versions, and Spotify creds presence

## Docker
A Dockerfile is provided. The image does not bake secrets; pass them at runtime with `--env-file`.

### Build
```
docker build -t not-very-smart-discord-bot:latest .
```

Multi-arch and ARM64 builds (optional, uses Buildx):
```
# ARM64 only (loads into local Docker)
docker buildx build --platform linux/arm64 -t not-very-smart-discord-bot:arm64 --load .

# Multi-arch and push to a registry
docker buildx build --platform linux/amd64,linux/arm64 -t <your-registry>/not-very-smart-discord-bot:latest --push .
```

### Run
```
docker run --rm -it \
  --env-file .env \
  -v ${PWD}/data:/app/data \
  -v ${PWD}/downloads:/app/downloads \
  --name discord-bot not-very-smart-discord-bot:latest
```

Notes:
- Do not copy `.env` into the image. Use `--env-file`.
- `.dockerignore` excludes secrets and local clutter by default.

### Production with Docker Compose
`docker-compose.yml` is included for a simpler, persistent prod setup.

Commands:
```
# First run (creates and starts)
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down

# Update to latest image and restart
docker compose pull && docker compose up -d
```

By default it:
- Uses `dullfox/not-very-smart-discord-bot:latest`
- Reads environment variables from `.env`
- Mounts `./data` and `./downloads` into the container
- Restarts unless stopped and rotates logs

## Project Structure
- `main.py`: Bot initialization and event handlers
- `cogs/`:
  - `music.py`: Music-related commands and functionality
  - `tyd.py`: Test Your Destiny feature
- `utils/`:
  - `database.py`: Database connection and queries
  - `music_utils.py`: YouTube and Spotify utilities
  
- `migrations/`: SQL migrations applied automatically on startup
- `data/`: runtime data directory (mounted as a volume in Docker examples)

## Commands
- `/play`: Play a song from YouTube or Spotify
- `/queue`: Display the current music queue
- `/skip`: Skip the current track
- `/pause`: Pause playback
- `/resume`: Resume playback
- `/stop`: Stop playback and clear the queue
- `/now_playing`: Show information about the current track
- `/tyd`: Test your destiny (daily command)
  
Owner-only (for bot owner):
- `/tyd_owner reset_cooldown [user]`: Reset `/tyd` cooldown for a user (defaults to self)
- `/tyd_owner cooldown_status [user]`: Show remaining `/tyd` cooldown for a user
- `/tyd_owner purge_expired [user]`: Remove expired TYD roles for a user or scan guild

Notes:
- These maintenance commands are grouped under `tyd_owner` and are visible primarily to admins but are enforced to only run for the bot owner (e.g., `dull_fox`).
- Responses are ephemeral to avoid cluttering channels.

## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## Database migrations and phrases

This bot supports simple SQL migrations and seeded phrases for the `/tyd` command.

- Migrations live in `migrations/` as sequential `.sql` files like `001_init.sql`, `002_more_phrases.sql`.
- On startup, the bot applies any new migrations and records them in `schema_migrations`.
- The `phrases` table stores messages keyed by `range_key` (e.g., `"0"`, `"50"`, `"2-10"`, `"30-49"`).

### Add or update phrases

1. Create a new SQL file in `migrations/`, incrementing the number, e.g. `003_add_funny_phrases.sql`.
2. Insert phrases, for example:

```sql
-- 003_add_funny_phrases.sql
INSERT INTO phrases(range_key, message) VALUES
('2-10', 'Сегодня удача на твоей стороне, {user_mention}!'),
('78-99', '{user_mention}, ты почти у вершины! {random_number} это почти 100.');
```

3. Restart the bot; the migration will be applied automatically.

Placeholders available in `message`:
- `{user_mention}`: mentions the user
- `{bot_mention}`: mentions the bot
- `{random_number}`: the rolled number (0–101)

### Tables

- `schema_migrations(version TEXT PRIMARY KEY, applied_at TIMESTAMP)`
- `roles(user_id BIGINT, role TEXT, time_assigned TIMESTAMP, expiration TIMESTAMP)`
- `phrases(id SERIAL, range_key TEXT, message TEXT)`