# Cytube Sender

A Python script to send YouTube videos to Cytube channels. Connects to Cytube WebSocket servers to clear playlists, skip current videos, and queue new YouTube content automatically.

## Usage

```bash
python cytube_sender.py <CHANNEL> <YOUTUBE_URL>
```

### Examples

```bash
python cytube_sender.py 'suckingonit' 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
python cytube_sender.py 'mychannel' 'https://youtu.be/VIDEO_ID'
python cytube_sender.py 'music' 'https://youtube.com/shorts/VIDEO_ID'
```

For use with openwith extensions, use `%s` as URL placeholder:
```bash
python cytube_sender.py 'mychannel' %s
```

## Features

- Connects to any Cytube channel via WebSocket
- Clears the current playlist
- Skips the playing video
- Queues YouTube videos (supports all YouTube URL formats)
- Auto-plays newly added content
- Works with guest access on most channels

## Requirements

- Python 3.6+
- `websockets` and `requests` packages

Install dependencies:
```bash
pip install websockets requests
```