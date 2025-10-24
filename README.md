# YouTube Live Auto-Downloader

This script automatically monitors a YouTube channel for live streams and upcoming live events, and downloads them when they go live.

## Features

- Monitors a YouTube channel for live streams
- Detects both live and upcoming streams
- Automatically starts recording when a stream goes live
- Downloads from the beginning of the stream
- Saves videos with timestamps in the filename
- Handles graceful shutdown with Ctrl+C

## Requirements

- Python 3.7+
- yt-dlp

## Installation

1. Install Python requirements:
```bash
pip install -r requirements.txt
```

2. Make sure you have yt-dlp installed and accessible in your PATH, or adjust the `YT_DLP_BIN` variable in the script.

## Usage

Simply run the script:
```bash
python auto_yt_live.py
```

The script will:
- Monitor the specified channel
- Detect and wait for upcoming streams
- Automatically start recording when streams go live
- Save recordings in the `downloads` folder

Press Ctrl+C to exit gracefully.

## Configuration

Edit these variables in `auto_yt_live.py`:

- `CHANNEL_VIDEOS`: YouTube channel URL to monitor
- `CHECK_INTERVAL`: How often to check for new streams (in seconds)
- `OUT_DIR`: Directory to save downloaded videos
- `OUT_TEMPLATE`: Filename template for saved videos