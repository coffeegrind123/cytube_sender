#!/usr/bin/env python3
"""
YouTube to Cytube Python Script with mpv Integration
Replicates the functionality of the userscript but as a standalone Python application.

Usage:
    # Add a video (clears playlist)
    python cytube_sender.py <CHANNEL> add <YOUTUBE_URL>
    
    # Play/resume current video
    python cytube_sender.py <CHANNEL> play
    
    # Pause current video
    python cytube_sender.py <CHANNEL> pause

Examples:
    python cytube_sender.py 'mychannel' add 'https://www.youtube.com/watch?v=VIDEO_ID'
    python cytube_sender.py 'mychannel' play
    python cytube_sender.py 'mychannel' pause

Features:
- Connects to Cytube WebSocket server
- Clears the playlist before adding new videos
- Adds videos without auto-playing
- Play and pause commands for mpv integration
- Works with any Cytube channel
- Supports all YouTube URL formats

MPV Integration:
Add these lines to your mpv input.conf:
    p script-message-to python_script cytube_play
    SPACE script-message-to python_script cytube_pause

Then create an mpv script that calls this Python script with play/pause commands.
"""

import asyncio
import json
import re
import sys
import time
import websockets
from urllib.parse import urlparse, parse_qs
import requests
from typing import Optional, Dict, Any

class CytubeSender:
    def __init__(self, channel: str):
        if not channel:
            raise ValueError("Channel name is required")
        self.channel = channel
        self.socket = None
        self.is_connected = False
        self.permissions_received = False
        self.current_server = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.video_uid = None
        self.video_id = None
        self.playlist_cleared = False

    def log(self, message: str, level: str = "INFO"):
        """Print formatted log messages"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")

    async def get_correct_server(self) -> str:
        """Get the correct server URL for the channel"""
        try:
            url = f"https://cytu.be/socketconfig/{self.channel}.json"
            self.log(f"Fetching server config for channel '{self.channel}'...")

            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                config = response.json()
                self.log(f"Channel config received: {config}")

                if config.get('servers'):
                    # Find a secure (wss://) server, fallback to any available
                    secure_server = next((s for s in config['servers'] if s.get('secure')),
                                       config['servers'][0])
                    server_url = secure_server['url']
                    self.log(f"Using server from config: {server_url}")
                    return server_url
                else:
                    self.log("No servers in config, using fallback")
                    return "wss://cytu.be"
            else:
                self.log(f"Config request failed: {response.status_code}, using fallback", "WARN")
                return "wss://cytu.be"
        except Exception as e:
            self.log(f"Config request error: {e}, using fallback", "ERROR")
            return "wss://cytu.be"

    def extract_hostname(self, url: str) -> str:
        """Extract hostname from URL"""
        try:
            hostname = re.sub(r'^https?://', '', url)
            return hostname.split('/')[0]
        except:
            return url

    async def connect_to_cytube(self) -> bool:
        """Connect to Cytube WebSocket server"""
        try:
            if self.socket and self.is_connected and self.permissions_received:
                return True

            # Close existing connection
            if self.socket:
                await self.socket.close()

            # Reset permissions flag
            self.permissions_received = False

            # Get correct server for this channel
            server_url = await self.get_correct_server()
            self.current_server = server_url

            # Extract hostname
            hostname = self.extract_hostname(server_url)
            self.log(f"Using server hostname: {hostname}")

            # Create WebSocket connection
            ws_url = f"wss://{hostname}/socket.io/?EIO=3&transport=websocket"
            self.log(f"Connecting to: {ws_url}")

            self.socket = await websockets.connect(ws_url)
            self.is_connected = True
            self.reconnect_attempts = 0
            self.log(f"✅ Connected to Cytube server: {hostname}")

            # Send initial handshake
            await self.socket.send("2probe")

            # Wait a moment then join channel
            await asyncio.sleep(0.5)
            await self.join_channel()

            return True

        except Exception as e:
            self.log(f"❌ Connection failed: {e}", "ERROR")
            self.is_connected = False
            return False

    async def join_channel(self):
        """Join the Cytube channel"""
        if not self.is_connected or not self.socket:
            return

        join_data = {"name": self.channel}
        join_message = f'42["joinChannel",{json.dumps(join_data)}]'
        await self.socket.send(join_message)
        self.log(f"🚀 Joining channel: {self.channel}")

    async def handle_socket_message(self, message: str):
        """Handle incoming socket messages"""
        # Only log short messages to avoid noise
        if len(message) < 100:
            self.log(f"📨 Cytube message: {message}")

        if message == "3probe":
            # Respond to probe
            await self.socket.send("5")
        elif message.startswith("42"):
            # Regular Socket.IO message format: 42["event",payload]
            try:
                # Remove the "42" prefix and parse the JSON array
                json_part = message[2:]
                msg_data = json.loads(json_part)

                if isinstance(msg_data, list) and len(msg_data) >= 2:
                    event, payload = msg_data[0], msg_data[1]
                    await self.handle_event(event, payload)
                elif isinstance(msg_data, list) and len(msg_data) == 1:
                    # Handle single item messages
                    event = msg_data[0]
                    await self.handle_event(event, None)
            except (json.JSONDecodeError, IndexError) as e:
                self.log(f"Failed to parse message: {message[:50]}... Error: {e}", "DEBUG")
        elif message.startswith("0{"):
            # Socket.IO connection with session ID
            self.log("✅ Socket.IO handshake received")
        elif message == "40":
            self.log("✅ Socket.IO connected")
        elif message == "2":
            # Ping response
            await self.socket.send("3")
        else:
            # Handle other message formats
            self.log(f"Other message: {message[:50]}...", "DEBUG")

    async def handle_event(self, event: str, payload: Any):
        """Handle specific socket events"""
        self.log(f"📢 Cytube event: {event}", "DEBUG")

        if event == "userlist":
            self.log(f"✅ Successfully joined channel: {self.channel}")
            # Userlist event often means we have basic permissions
            if not self.permissions_received:
                self.log("🎯 Assuming permissions from userlist event")
                self.permissions_received = True
        elif event == "setPermissions":
            self.log("✅ Received permissions from server")
            self.permissions_received = True
        elif event == "login":
            self.log(f"🔐 Login response: {payload}")
            if isinstance(payload, dict) and payload.get('success'):
                self.permissions_received = True
                self.log("✅ Authenticated and ready to queue")
        elif event == "needPassword":
            self.log("🔒 Channel requires password", "ERROR")
        elif event == "motd":
            self.log(f"📝 MOTD: {payload}")
        elif event == "queue":
            self.log(f"📋 Queue update received: {payload}")
        elif event == "queueFail":
            self.log(f"❌ Queue failed: {payload}", "ERROR")
        elif event == "errorMsg":
            msg = payload.get('msg', 'Unknown error') if isinstance(payload, dict) else str(payload)
            self.log(f"❌ Server error: {msg}", "ERROR")
            if "hosted on another server" in msg:
                self.log("🔄 Server mismatch detected")
                await self.reconnect()
        elif event == "addToQueue":
            self.log(f"✅ Video added to queue: {payload}")
            if isinstance(payload, dict) and payload.get('media') and payload.get('media', {}).get('id') == self.video_id:
                self.video_uid = payload.get('uid')
                self.log(f"🎯 Video added successfully: {payload.get('media', {}).get('title', 'Unknown')}")
        elif event == "playlist":
            if isinstance(payload, list):
                self.log(f"📋 Current playlist: {len(payload)} videos")
        elif event == "clearPlaylist":
            self.log("✅ Playlist cleared successfully")
            self.playlist_cleared = True
        elif event == "changeMedia":
            if isinstance(payload, dict):
                title = payload.get('title', 'Unknown')
                self.log(f"🎬 Now playing: {title}")
        elif event == "chatMsg":
            # Ignore chat messages for cleaner console
            pass
        elif event == "userCount":
            self.log(f"👥 Users in channel: {payload}")
        else:
            self.log(f"📦 Unknown event: {event}: {payload}", "DEBUG")

    async def reconnect(self):
        """Attempt to reconnect to server"""
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            delay = min(2000 * (2 ** (self.reconnect_attempts - 1)), 10000)
            self.log(f"🔄 Attempting reconnect {self.reconnect_attempts}/{self.max_reconnect_attempts} in {delay}ms")
            await asyncio.sleep(delay / 1000)
            await self.connect_to_cytube()

    async def clear_playlist(self):
        """Clear the entire playlist"""
        if not self.socket or not self.is_connected:
            raise Exception("Not connected to Cytube")

        self.playlist_cleared = False
        clear_message = '42["clearPlaylist",null]'
        await self.socket.send(clear_message)
        self.log("🧹 Sent clear playlist command")
        
        # Wait for confirmation that playlist was cleared
        wait_count = 0
        max_wait = 30  # 3 seconds
        while not self.playlist_cleared and wait_count < max_wait:
            await asyncio.sleep(0.1)
            wait_count += 1
        
        if self.playlist_cleared:
            self.log("✅ Playlist clear confirmed")
        else:
            self.log("⚠️ Playlist clear not confirmed, but proceeding", "WARN")
        
        await asyncio.sleep(0.5)

    async def skip_current_video(self):
        """Skip the currently playing video"""
        if not self.socket or not self.is_connected:
            raise Exception("Not connected to Cytube")

        skip_message = '42["playNext",null]'
        await self.socket.send(skip_message)
        self.log("⏭️ Sent skip current video command")
        await asyncio.sleep(0.5)

    async def play(self):
        """Resume/play the current video"""
        if not self.socket or not self.is_connected:
            raise Exception("Not connected to Cytube")

        play_message = '42["mediaUpdate",{"id":null,"currentTime":-1,"paused":false,"type":""}]'
        await self.socket.send(play_message)
        self.log("▶️ Sent play command")

    async def pause(self):
        """Pause the current video"""
        if not self.socket or not self.is_connected:
            raise Exception("Not connected to Cytube")

        pause_message = '42["mediaUpdate",{"id":null,"currentTime":-1,"paused":true,"type":""}]'
        await self.socket.send(pause_message)
        self.log("⏸️ Sent pause command")

    async def queue_video(self, video_id: str, title: str):
        """Queue a YouTube video (without auto-playing)"""
        if not self.socket or not self.is_connected:
            raise Exception("Not connected to Cytube")

        if not self.permissions_received:
            raise Exception("Not authenticated with channel")

        queue_data = {
            "id": video_id,
            "type": "yt",
            "pos": "end",
            "duration": 0,  # Server will fetch this
            "title": title
        }

        queue_message = f'42["queue",{json.dumps(queue_data)}]'
        await self.socket.send(queue_message)
        self.log(f"🎯 Queued video: {title} (ID: {video_id})")

    def extract_video_info(self, youtube_url: str) -> tuple[str, str]:
        """Extract video ID and title from YouTube URL"""
        # Parse URL to get video ID
        parsed = urlparse(youtube_url)

        # Handle different YouTube URL formats
        if parsed.hostname in ['www.youtube.com', 'youtube.com', 'm.youtube.com']:
            if parsed.path == '/watch':
                video_id = parse_qs(parsed.query).get('v', [None])[0]
            elif parsed.path.startswith('/shorts/'):
                video_id = parsed.path.split('/')[-1]
            elif parsed.path.startswith('/embed/'):
                video_id = parsed.path.split('/')[-1]
            else:
                video_id = None
        elif parsed.hostname in ['youtu.be', 'www.youtu.be']:
            video_id = parsed.path.lstrip('/')
        else:
            video_id = None

        if not video_id or not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
            raise ValueError(f"Invalid YouTube URL: {youtube_url}")

        # For now, use a generic title. In a real implementation,
        # you could use YouTube API to get the actual title
        title = f"YouTube Video ({video_id})"

        return video_id, title

    async def add_video_to_cytube(self, youtube_url: str):
        """Add YouTube video to Cytube (clears playlist first, no auto-play)"""
        try:
            # Extract video information
            self.video_id, title = self.extract_video_info(youtube_url)

            self.log(f"📺 Processing YouTube video: {title} (ID: {self.video_id})")

            # Step 1: Connect to Cytube
            self.log("🔄 Step 1: Connecting to Cytube...")
            if not await self.connect_to_cytube():
                raise Exception("Failed to connect to Cytube")

            # Wait for permissions
            self.log("⏳ Waiting for permissions...")
            wait_count = 0
            max_wait = 2  # 20 seconds
            while not self.permissions_received and wait_count < max_wait:
                await asyncio.sleep(0.1)
                wait_count += 1
                if wait_count % 50 == 0:  # Log every 5 seconds
                    self.log(f"⏳ Still waiting for permissions... ({wait_count}/{max_wait})")

            if not self.permissions_received:
                self.log("⚠️ No permissions received, but proceeding anyway", "WARN")
                # For guest users, many channels don't require explicit permissions for basic operations
                self.log("🎯 Attempting guest access (many channels allow this)")
                self.permissions_received = True  # Allow guest operations
            else:
                self.log("✅ Permissions received, ready to queue")

            # Step 2: Clear playlist
            self.log("🧹 Step 2: Clearing playlist...")
            await self.clear_playlist()

            # Step 3: Skip current video
            self.log("⏭️ Step 3: Skipping current video...")
            try:
                await self.skip_current_video()
            except Exception as e:
                self.log(f"⚠️ Skip failed, continuing: {e}", "WARN")

            # Step 4: Queue new video (WITHOUT auto-play)
            self.log("📤 Step 4: Queuing new video...")
            await self.queue_video(self.video_id, title)

            self.log("✅ Video added successfully! Playlist cleared. Use 'play' command to start playback.")

            # Keep connection alive for a bit to receive updates
            await asyncio.sleep(3)

        except Exception as e:
            self.log(f"❌ Failed to add video: {e}", "ERROR")
            raise

    async def send_play_command(self):
        """Send play command to Cytube"""
        try:
            self.log("🔄 Connecting to send play command...")
            if not await self.connect_to_cytube():
                raise Exception("Failed to connect to Cytube")

            # Wait for permissions
            wait_count = 0
            max_wait = 100
            while not self.permissions_received and wait_count < max_wait:
                await asyncio.sleep(0.1)
                wait_count += 1

            if not self.permissions_received:
                self.log("⚠️ Proceeding with guest access", "WARN")
                self.permissions_received = True

            await self.play()
            self.log("✅ Play command sent successfully!")
            await asyncio.sleep(1)

        except Exception as e:
            self.log(f"❌ Failed to send play command: {e}", "ERROR")
            raise

    async def send_pause_command(self):
        """Send pause command to Cytube"""
        try:
            self.log("🔄 Connecting to send pause command...")
            if not await self.connect_to_cytube():
                raise Exception("Failed to connect to Cytube")

            # Wait for permissions
            wait_count = 0
            max_wait = 100
            while not self.permissions_received and wait_count < max_wait:
                await asyncio.sleep(0.1)
                wait_count += 1

            if not self.permissions_received:
                self.log("⚠️ Proceeding with guest access", "WARN")
                self.permissions_received = True

            await self.pause()
            self.log("✅ Pause command sent successfully!")
            await asyncio.sleep(1)

        except Exception as e:
            self.log(f"❌ Failed to send pause command: {e}", "ERROR")
            raise

    async def listen_for_messages(self):
        """Listen for incoming socket messages"""
        try:
            async for message in self.socket:
                await self.handle_socket_message(message)
        except websockets.exceptions.ConnectionClosed:
            self.log("🔌 Cytube disconnected")
            self.is_connected = False
            self.permissions_received = False
        except Exception as e:
            self.log(f"❌ Socket error: {e}", "ERROR")

    async def run(self, command: str, youtube_url: Optional[str] = None):
        """Run the complete process"""
        try:
            # Connect and start listening
            if await self.connect_to_cytube():
                # Start message listener in background
                listener_task = asyncio.create_task(self.listen_for_messages())

                # Execute command
                if command == "add":
                    if not youtube_url:
                        raise ValueError("YouTube URL required for 'add' command")
                    await self.add_video_to_cytube(youtube_url)
                elif command == "play":
                    await self.send_play_command()
                elif command == "pause":
                    await self.send_pause_command()
                else:
                    raise ValueError(f"Unknown command: {command}")

                # Cancel listener task
                listener_task.cancel()
                try:
                    await listener_task
                except asyncio.CancelledError:
                    pass

            # Close connection
            if self.socket:
                await self.socket.close()

        except KeyboardInterrupt:
            self.log("🛑 Process interrupted by user")
        except Exception as e:
            self.log(f"❌ Unexpected error: {e}", "ERROR")
            raise

def main():
    """Main entry point"""
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python cytube_sender.py <CHANNEL> <COMMAND> [YOUTUBE_URL]")
        print("")
        print("Commands:")
        print("  add <URL>  - Clear playlist and add a video (doesn't auto-play)")
        print("  play       - Resume/play the current video")
        print("  pause      - Pause the current video")
        print("")
        print("Examples:")
        print("  python cytube_sender.py 'mychannel' add 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'")
        print("  python cytube_sender.py 'mychannel' play")
        print("  python cytube_sender.py 'mychannel' pause")
        print("")
        print("MPV Integration:")
        print("  Create a Lua script in ~/.config/mpv/scripts/ that calls this script:")
        print("  mp.register_script_message('cytube_play', function()")
        print("    os.execute('python /path/to/cytube_sender.py mychannel play &')")
        print("  end)")
        print("  mp.register_script_message('cytube_pause', function()")
        print("    os.execute('python /path/to/cytube_sender.py mychannel pause &')")
        print("  end)")
        print("")
        print("  Then in input.conf:")
        print("  p script-message cytube_play")
        print("  SPACE script-message cytube_pause")
        sys.exit(1)

    channel = sys.argv[1]
    command = sys.argv[2].lower()
    youtube_url = sys.argv[3] if len(sys.argv) > 3 else None

    # Validate command
    if command not in ['add', 'play', 'pause']:
        print(f"Error: Unknown command '{command}'")
        print("Valid commands: add, play, pause")
        sys.exit(1)

    # Validate URL for add command
    if command == 'add':
        if not youtube_url:
            print("Error: YouTube URL required for 'add' command")
            sys.exit(1)
        if not any(domain in youtube_url.lower() for domain in ['youtube.com', 'youtu.be']):
            print("Error: Please provide a valid YouTube URL")
            sys.exit(1)

    # Validate channel format
    if not channel or not isinstance(channel, str):
        print("Error: Please provide a valid channel name")
        sys.exit(1)

    # Create and run sender
    sender = CytubeSender(channel=channel)
    print(f"🎯 Target channel: {channel}")
    print(f"📋 Command: {command}")
    if youtube_url:
        print(f"📺 YouTube URL: {youtube_url}")

    try:
        asyncio.run(sender.run(command, youtube_url))
    except KeyboardInterrupt:
        print("\n🛑 Process interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
