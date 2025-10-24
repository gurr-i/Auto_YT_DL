"""
Handles YouTube channel live detection including scheduled (upcoming) streams.
Monitors the /live endpoint directly and records streams when they become available.
"""

import time
import os
import signal
import sys
import subprocess
import re
from datetime import datetime
from typing import Optional, Dict, Any

import yt_dlp
from yt_dlp.utils import DownloadError

# --- Configuration ---
DEBUG = True
CHANNEL_URL = "https://www.youtube.com/@parmarssc/live"
CHECK_INTERVAL = 15      # How often to check the channel status
QUIET_LOG_INTERVAL = 120 # How often to log "waiting" messages when idle
## FIX: New setting for the recording heartbeat message
HEARTBEAT_INTERVAL = 300 # (in seconds) Print a "still recording" message every 5 minutes.
OUT_DIR = "./downloads"
OUT_TEMPLATE = os.path.join(OUT_DIR, "%(upload_date)s - %(title)s - %(id)s.%(ext)s")

# --- Setup ---
os.makedirs(OUT_DIR, exist_ok=True)
YTDLP_CMD = [sys.executable, "-m", "yt_dlp"]

# --- Helper Functions ---
def get_video_info(video_url: str, deep_scan: bool = False) -> Dict[str, Any]:
    """Gets info for a video/live stream URL."""
    try:
        ydl_opts = {
            "quiet": True, # Keep yt-dlp's own info extraction quiet
            "no_warnings": True,
            "extract_flat": not deep_scan,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if DEBUG:
                scan_type = "DEEP" if deep_scan else "QUICK"
                print(f"[{datetime.now()}] Performing {scan_type} scan for: {video_url}")
            info = ydl.extract_info(video_url, download=False)

            if not info: return {"status": "not_live"}

            video_id = info.get("id")
            title = info.get("title")

            if info.get("is_live"):
                if DEBUG: print(f"[{datetime.now()}] Status for '{title or video_id}': LIVE")
                return {"status": "live", "video_id": video_id, "title": title}

            if info.get("is_upcoming") or info.get("live_status") == 'is_upcoming':
                if DEBUG: print(f"[{datetime.now()}] Status for '{title or video_id}': UPCOMING")
                return {"status": "upcoming", "video_id": video_id, "title": title}

            if not deep_scan and video_id:
                if DEBUG: print(f"[{datetime.now()}] Quick scan found video ID '{video_id}'. Needs deep scan.")
                return {"status": "inconclusive", "video_id": video_id, "title": title}

            if DEBUG: print(f"[{datetime.now()}] Status for '{title or video_id}': NOT LIVE")
            return {"status": "not_live", "video_id": video_id, "title": title}

    except DownloadError as e:
        msg = str(e)
        if "live event will begin" in msg:
            m = re.search(r"\[youtube\]\s*([A-Za-z0-9_-]{11})", msg)
            vid = m.group(1) if m else None
            return {"status": "upcoming", "video_id": vid, "errmsg": msg}
        return {"status": "error", "errmsg": msg}
    except Exception as e:
        return {"status": "error", "errmsg": str(e)}

def start_record(video_url: str) -> Optional[subprocess.Popen]:
    """Start downloading a stream using yt-dlp in a subprocess, showing progress."""
    try:
        cmd = YTDLP_CMD + [
            "--no-warnings",
            "--newline",
            "--no-overwrites",
            "--live-from-start",
            "--hls-use-mpegts",
            "--progress",  # Show download progress
            "-o", OUT_TEMPLATE,
            video_url
        ]
        if DEBUG:
            print(f"[{datetime.now()}] Starting download command: {' '.join(cmd)}")
        
        # Show the output in real-time
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
    except Exception as e:
        if DEBUG:
            print(f"[{datetime.now()}] Error starting download: {str(e)}")
        return None

# --- Main Watch Loop ---
def watch_loop():
    """Monitors the channel and manages recording with a two-step check."""
    current_proc: Optional[subprocess.Popen] = None
    current_vid_id: Optional[str] = None
    last_logged_state: str = "initial"
    last_logged_time: datetime = datetime.fromtimestamp(0) # Set to a long time ago

    def stop_current_recording():
        nonlocal current_proc, current_vid_id
        if current_proc:
            print(f"[{datetime.now()}] Terminating recording for {current_vid_id}...")
            try:
                current_proc.terminate()
                current_proc.wait(timeout=5)
                if current_proc.poll() is None:
                    print(f"[{datetime.now()}] Process for {current_vid_id} did not terminate gracefully, killing...")
                    current_proc.kill()
            except Exception as e:
                print(f"[{datetime.now()}] Error while stopping process: {e}")
            finally:
                print(f"[{datetime.now()}] Recording for {current_vid_id} stopped.")
                current_proc = None
                current_vid_id = None

    def handle_sigint(sig, frame):
        print(f"\n[{datetime.now()}] Received SIGINT. Exiting gracefully...")
        stop_current_recording()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    print(f"[{datetime.now()}] Monitoring YouTube channel: {CHANNEL_URL}")

    while True:
        try:
            # 1. Check if a recording is active
            if current_proc:
                if current_proc.poll() is not None: # Process has finished
                    print(f"[{datetime.now()}] Recorder for {current_vid_id} exited with code {current_proc.returncode}.")
                    stop_current_recording()
                    last_logged_state = "stopped"
                else:
                    ## FIX: Add a heartbeat log message for long-running recordings
                    if (datetime.now() - last_logged_time).total_seconds() > HEARTBEAT_INTERVAL:
                        print(f"[{datetime.now()}] Heartbeat: Recording for video {current_vid_id} is still in progress...")
                        last_logged_time = datetime.now()
                    time.sleep(CHECK_INTERVAL)
                    continue # Skip to the next loop iteration to re-check the process

            # 2. If not recording, scan for a live stream
            channel_info = get_video_info(CHANNEL_URL, deep_scan=False)
            candidate_vid_id = channel_info.get("video_id")

            if not candidate_vid_id:
                if last_logged_state != "no_video" or (datetime.now() - last_logged_time).total_seconds() > QUIET_LOG_INTERVAL:
                    print(f"[{datetime.now()}] No video found on channel page. Waiting...")
                    last_logged_state = "no_video"
                    last_logged_time = datetime.now()
                time.sleep(CHECK_INTERVAL)
                continue

            # 3. Perform a DEEP scan on the candidate video
            video_url = f"https://www.youtube.com/watch?v={candidate_vid_id}"
            final_status_info = get_video_info(video_url, deep_scan=True)
            status = final_status_info.get("status")
            title = final_status_info.get("title", f"Video {candidate_vid_id}")

            # 4. Act on the final status
            if status == "live":
                if candidate_vid_id != current_vid_id:
                    print(f"[{datetime.now()}] *** LIVE stream detected: '{title}' ({candidate_vid_id}) ***")
                    stop_current_recording()
                    current_proc = start_record(video_url)
                    if current_proc:
                        print(f"[{datetime.now()}] Recording process started successfully.")
                        current_vid_id = candidate_vid_id
                        last_logged_state = "recording"
                        last_logged_time = datetime.now()
                        
                        # Read and display progress
                        while current_proc.poll() is None:  # While the process is still running
                            output = current_proc.stdout.readline()
                            if output:
                                output = output.strip()
                                if "[download]" in output and not "Destination:" in output:
                                    # Use \r to overwrite the line and end with a space to clear any trailing characters
                                    print(f"\r[{datetime.now()}] {output}", end="  ", flush=True)
                            time.sleep(0.1)  # Small delay to prevent CPU overuse
                        print()  # Print a newline after download completes
                    else:
                        print(f"[{datetime.now()}] ERROR: Failed to start recording process for {candidate_vid_id}.")
                        last_logged_state = "error"
            else:
                log_key = f"waiting_{candidate_vid_id}"
                if last_logged_state != log_key or (datetime.now() - last_logged_time).total_seconds() > QUIET_LOG_INTERVAL:
                    msg_map = {
                        "upcoming": f"UPCOMING stream scheduled: '{title}'. Waiting...",
                        "not_live": f"No live stream. Last checked: '{title}'. Waiting...",
                        "error": f"ERROR checking '{title}': {final_status_info.get('errmsg')}"
                    }
                    print(f"[{datetime.now()}] {msg_map.get(status, f'Unknown status: {status}. Waiting...')}")
                    last_logged_state = log_key
                    last_logged_time = datetime.now()

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"[{datetime.now()}] An unexpected error occurred in watch_loop: {e}")
            time.sleep(CHECK_INTERVAL * 2)

# --- Main Execution ---
if __name__ == "__main__":
    print(f"[{datetime.now()}] YouTube Live Auto-Downloader started. Press Ctrl+C to stop.")
    try:
        watch_loop()
    except SystemExit:
        print(f"[{datetime.now()}] Exiting YouTube Live Auto-Downloader.")