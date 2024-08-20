import yt_dlp
import spotipy
import os
from spotipy.oauth2 import SpotifyClientCredentials

# yt_dlp setup
yt_dlp.utils.bug_reports_message = lambda: ''
ytdl_format_options = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'outtmpl': 'downloads/%(id)s.%(ext)s',
    'keepvideo': True
}
ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# Spotify client setup
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=os.getenv("SPOTIFY_CLIENT_ID"),
                                                           client_secret=os.getenv("SPOTIFY_CLIENT_SECRET")))