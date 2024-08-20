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
- Python 3.11.8 or higher
- FFmpeg
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

## Docker
A Dockerfile is provided for containerization. To build and run the Docker image:

```
docker build -t discord-bot .
docker run -d discord-bot
```

## Project Structure
- `main.py`: Bot initialization and event handlers
- `cogs/`:
  - `music.py`: Music-related commands and functionality
  - `tyd.py`: Test Your Destiny feature
- `utils/`:
  - `database.py`: Database connection and queries
  - `music_utils.py`: YouTube and Spotify utilities
  - `queue_manager.py`: Music queue management

## Commands
- `/play`: Play a song from YouTube or Spotify
- `/queue`: Display the current music queue
- `/skip`: Skip the current track
- `/pause`: Pause playback
- `/resume`: Resume playback
- `/stop`: Stop playback and clear the queue
- `/now_playing`: Show information about the current track
- `/tyd`: Test your destiny (daily command)

## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.