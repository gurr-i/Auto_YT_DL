# yt_live_watcher.py
"""
Handles YouTube channel live detection including scheduled (upcoming) streams.
Monitors the /live endpoint directly and records streams when they become available.
Uploads completed recordings to Google Drive immediately via rclone.
"""

import time
import os
import signal
import sys
import subprocess
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import yt_dlp
from yt_dlp.utils import DownloadError

# --- Configuration (env overrides) ---
DEBUG = True
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://www.youtube.com/@parmarssc/live")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "15"))
QUIET_LOG_INTERVAL = int(os.getenv("QUIET_LOG_INTERVAL", "120"))
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "300"))
OUT_DIR = os.getenv("OUT_DIR", "./downloads")
OUT_TEMPLATE = os.path.join(OUT_DIR, "%(upload_date)s - %(title)s - %(id)s.%(ext)s")
MAX_RUN_SECONDS = int(os.getenv("MAX_RUN_SECONDS", "0"))  # 0 => no limit

# --- rclone Configuration --- # <--- NEW SECTION
# This remote name 'gdrive' MUST match the 'RCLONE_CONFIG_GDRIVE_...' env var prefix
RCLONE_REMOTE_NAME = "gdrive"  
GDRIVE_FOLDER = os.getenv("GDRIVE_UPLOAD_FOLDER", "YTUploads") # Target folder name on Drive

# --- Setup ---
os.makedirs(OUT_DIR, exist_ok=True)
YTDLP_CMD = [sys.executable, "-m", "yt_dlp"]

start_time = datetime.now()
end_time = start_time + timedelta(seconds=MAX_RUN_SECONDS) if MAX_RUN_SECONDS > 0 else None

# --- Helper Functions (Identical to original) ---
def get_video_info(video_url: str, deep_scan: bool = False) -> Dict[str, Any]:
    try:
        ydl_opts = {
            "quiet": True,
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
    try:
        cmd = YTDLP_CMD + [
            "--no-warnings",
            "--newline",
            "--no-overwrites",
            "--live-from-start",
            "--hls-use-mpegts",
            "--progress",
            "-o", OUT_TEMPLATE,
            video_url
        ]
        if DEBUG:
            print(f"[{datetime.now()}] Starting download command: {' '.join(cmd)}")
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
    except Exception as e:
        if DEBUG:
            print(f"[{datetime.now()}] Error starting download: {str(e)}")
        return None

# --- NEW UPLOAD FUNCTION ---
def upload_downloads_to_drive():
    """
    Calls rclone to upload the contents of OUT_DIR to Google Drive.
    Assumes rclone is configured via environment variables from the workflow.
    """
    print(f"[{datetime.now()}] Attempting to upload files from {OUT_DIR} to GDrive...")
    try:
        # rclone will automatically use the 'gdrive' config from env vars
        # We sync the *entire* download directory.
        # Quoting the folder name handles spaces.
        upload_cmd = [
            "rclone", "copy", OUT_DIR,
            f"{RCLONE_REMOTE_NAME}:\"{GDRIVE_FOLDER}\"",
            "--create-empty-src-dirs",
            "--progress",
            "--drive-chunk-size", "64M" # Good for runners
        ]
        print(f"[{datetime.now()}] Running upload: {' '.join(upload_cmd)}")
        
        # Run upload in a blocking way with a 30-minute timeout
        up_result = subprocess.run(upload_cmd, capture_output=True, text=True, timeout=1800) 
        
        if up_result.returncode == 0:
            print(f"[{datetime.now()}] Upload complete.")
            # rclone logs to stderr, even on success
            if DEBUG and up_result.stderr:
                print(f"[{datetime.now()}] rclone log:\n{up_result.stderr}")
        else:
            # Log rclone errors
            print(f"[{datetime.now()}] ERROR during upload. rclone exited with {up_result.returncode}.")
            print(f"[{datetime.now()}] rclone stderr: {up_result.stderr}")
            print(f"[{datetime.now()}] rclone stdout: {up_result.stdout}")

    except subprocess.TimeoutExpired:
         print(f"[{datetime.now()}] ERROR: rclone upload timed out after 30 minutes.")
    except Exception as e:
        print(f"[{datetime.now()}] UNEXPECTED ERROR during upload: {str(e)}")

# --- Main Watch Loop (Modified) ---
def watch_loop():
    current_proc: Optional[subprocess.Popen] = None
    current_vid_id: Optional[str] = None
    last_logged_state: str = "initial"
    last_logged_time: datetime = datetime.fromtimestamp(0)

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
        # Attempt one final upload on graceful exit
        upload_downloads_to_drive() # <--- NEW
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    print(f"[{datetime.now()}] Monitoring YouTube channel: {CHANNEL_URL}")

    while True:
        # --- MODIFIED: Check for timeout ---
        if end_time and datetime.now() >= end_time:
            print(f"[{datetime.now()}] Reached MAX_RUN_SECONDS limit. Exiting loop.")
            if current_proc:
                stop_current_recording()
            # Attempt one final upload on time-out
            upload_downloads_to_drive() # <--- NEW
            break

        try:
            if current_proc:
                # --- MODIFIED: Check if recording process finished ---
                if current_proc.poll() is not None:
                    print(f"[{datetime.now()}] Recorder for {current_vid_id} exited with code {current_proc.returncode}.")
                    
                    # --- NEW UPLOAD LOGIC ---
                    # The stream finished, so upload the result *now*.
                    upload_downloads_to_drive()
                    # --- END NEW LOGIC ---

                    stop_current_recording()
                    last_logged_state = "stopped"
                else:
                    # Heartbeat log
                    if (datetime.now() - last_logged_time).total_seconds() > HEARTBEAT_INTERVAL:
                        print(f"[{datetime.now()}] Heartbeat: Recording for video {current_vid_id} is still in progress...")
                        last_logged_time = datetime.now()
                    time.sleep(CHECK_INTERVAL)
                    continue

            # (The rest of the loop for finding a new stream is identical to your original)
            
            channel_info = get_video_info(CHANNEL_URL, deep_scan=False)
            candidate_vid_id = channel_info.get("video_id")

            if not candidate_vid_id:
                if last_logged_state != "no_video" or (datetime.now() - last_logged_time).total_seconds() > QUIET_LOG_INTERVAL:
                    print(f"[{datetime.now()}] No video found on channel page. Waiting...")
                    last_logged_state = "no_video"
                    last_logged_time = datetime.now()
                time.sleep(CHECK_INTERVAL)
                continue

            video_url = f"https://www.youtube.com/watch?v={candidate_vid_id}"
            final_status_info = get_video_info(video_url, deep_scan=True)
            status = final_status_info.get("status")
            title = final_status_info.get("title", f"Video {candidate_vid_id}")

            if status == "live":
                if candidate_vid_id != current_vid_id:
                    print(f"[{datetime.now()}] *** LIVE stream detected: '{title}' ({candidate_vid_id}) ***")
                    stop_current_recording() # Stop previous, if any
                    
                    current_proc = start_record(video_url)
                    if current_proc:
                        print(f"[{datetime.now()}] Recording process started successfully.")
                        current_vid_id = candidate_vid_id
                        last_logged_state = "recording"
                        last_logged_time = datetime.now()

                        # --- MODIFIED: Inner loop to watch the recorder ---
                        while current_proc.poll() is None:
                            # Check for timeout *inside* the recording loop
                            if end_time and datetime.now() >= end_time:
                                print(f"[{datetime.now()}] MAX_RUN_SECONDS reached during recording. Stopping.")
                                break # This will exit the inner 'while'

                            output = current_proc.stdout.readline()
                            if output:
                                output = output.strip()
                                # Print streaming download progress
                                if "[download]" in output and "Destination:" not in output:
                                    print(f"\r[{datetime.now()}] {output}", end="  ", flush=True)
                            time.sleep(0.1) # Sleep briefly to avoid busy-waiting
                        
                        print() # Add a newline after the progress output
                        # After this inner loop finishes (either by timeout or stream end),
                        # the outer loop will cycle, detect `current_proc.poll() is not None`,
                        # and trigger the upload.
                        
                    else:
                        print(f"[{datetime.now()}] ERROR: Failed to start recording process for {candidate_vid_id}.")
                        last_logged_state = "error"
            else:
                # (Identical logging for 'upcoming' or 'not_live' status)
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

if __name__ == "__main__":
    print(f"[{datetime.now()}] YouTube Live Auto-Downloader started. Press Ctrl+C to stop.")
    try:
        watch_loop()
    except SystemExit:
        print(f"[{datetime.now()}] Exiting YouTube Live Auto-Downloader.")