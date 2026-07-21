# -*- coding: utf-8 -*-

import os
import json
import threading
import time
import subprocess
import shutil
from Components.config import config
from .logger import get_logger

log = get_logger()

# Persistente: salva la coda in /etc/enigma2/
QUEUE_FILE = os.path.join("/etc/enigma2", "scsearch_download_queue.json")
MIN_FREE_BYTES = 256 * 1024 * 1024


class DownloadManager:
    """Singleton manager for download queue and workers."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DownloadManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.download_folder = self._get_default_download_folder()
        self.queue = []
        self.workers = {}
        self.processes = {}
        self.running = False
        self.max_parallel = 1
        self.ui_callbacks = []
        self._load_queue()
        self._start_worker()

    @staticmethod
    def _get_default_download_folder():
        """Get the first valid movie directory from Enigma2 config."""
        try:
            if config.movielist.videodirs.value and len(
                    config.movielist.videodirs.value) > 0:
                for path in config.movielist.videodirs.value:
                    if os.path.exists(path):
                        return path
        except BaseException:
            pass
        return "/media/hdd/movie/"

    def set_download_folder(self, path):
        """Set a custom download folder at runtime."""
        if os.path.exists(path):
            self.download_folder = path
            log.info("DM: Download folder changed to: {}".format(path))
            return True
        else:
            log.error("DM: Download folder does not exist: {}".format(path))
            return False

    def _ensure_queue_dir(self):
        """Ensure the directory for QUEUE_FILE exists."""
        queue_dir = os.path.dirname(QUEUE_FILE)
        if not os.path.exists(queue_dir):
            try:
                os.makedirs(queue_dir, mode=0o755)
            except Exception as e:
                log.error("DM: Failed to create queue directory: {}".format(e))

    def _load_queue(self):
        """Load queue from JSON file."""
        self._ensure_queue_dir()
        try:
            if os.path.exists(QUEUE_FILE):
                with open(QUEUE_FILE, 'r') as f:
                    self.queue = json.load(f)
                log.info("DM: Loaded {} items from queue".format(len(self.queue)))
            else:
                self.queue = []
        except Exception as e:
            log.error("DM: Failed to load queue: {}".format(e))
            self.queue = []

    def _save_queue(self):
        """Save queue to JSON file."""
        self._ensure_queue_dir()
        try:
            with open(QUEUE_FILE, 'w') as f:
                json.dump(self.queue, f, indent=2)
        except Exception as e:
            log.error("DM: Failed to save queue: {}".format(e))

    def _get_duration(self, url):
        """Get duration in seconds from a stream URL using ffprobe."""
        try:
            ffprobe_path = shutil.which("ffprobe")
            if not ffprobe_path:
                log.warning("DM: ffprobe not found")
                return 0
            cmd = [
                ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                duration = float(result.stdout.strip())
                log.info("DM: Duration = {} seconds".format(int(duration)))
                return int(duration)
        except Exception as e:
            log.warning("DM: Could not get duration: {}".format(e))
        return 0

    def add_item(
            self,
            title,
            url,
            media_type="movie",
            season=0,
            episode=0,
            poster="",
            resolver=None,
            duration=0):
        """Add a new item to the queue."""
        item_id = str(int(time.time() * 1000))
        item = {
            "id": item_id,
            "title": title,
            "url": url,
            "media_type": media_type,
            "season": season,
            "episode": episode,
            "poster": poster,
            "resolver": resolver,
            "duration": duration,
            "status": "pending",
            "progress": 0,
            "size": 0,
            "downloaded": 0,
            "output_path": "",
            "error": ""
        }
        self.queue.append(item)
        self._save_queue()
        self._notify_ui()
        log.info("DM: Added item: {}".format(title))
        return item_id

    def remove_item(self, item_id):
        """Remove an item from the queue."""
        if item_id in self.processes:
            self._terminate_download(item_id, user_paused=False)
        self.queue = [item for item in self.queue if item["id"] != item_id]
        self._save_queue()
        self._notify_ui()

    def start_item(self, item_id):
        """Start or resume a download."""
        item = self._get_item(item_id)
        if not item:
            return
        if item["status"] == "downloading":
            return
        item["status"] = "pending"
        item["error"] = ""
        item["downloaded"] = 0
        item["progress"] = 0
        self._save_queue()
        self._notify_ui()

    def pause_item(self, item_id):
        """Pause a download."""
        item = self._get_item(item_id)
        if not item:
            return
        if item["status"] == "downloading":
            self._terminate_download(item_id, user_paused=True)
        else:
            item["status"] = "paused"
            self._save_queue()
            self._notify_ui()

    def _terminate_download(self, item_id, user_paused=True):
        """Terminate the download process."""
        if item_id in self.processes:
            try:
                self.processes[item_id].terminate()
                self.processes[item_id].wait(timeout=2)
            except BaseException:
                pass
            self.processes.pop(item_id, None)
        if item_id in self.workers:
            self.workers.pop(item_id, None)
        item = self._get_item(item_id)
        if item:
            if user_paused:
                item["status"] = "paused"
            else:
                item["status"] = "error"
            self._save_queue()
            self._notify_ui()

    def _get_item(self, item_id):
        for item in self.queue:
            if item["id"] == item_id:
                return item
        return None

    def _start_worker(self):
        """Start the background worker thread."""
        self.worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def _worker_loop(self):
        """Main loop for the download worker."""
        while True:
            try:
                # Find items that are ready to start
                pending = [item for item in self.queue if item["status"] == "pending"]
                for item in pending:
                    if len(self.workers) < self.max_parallel:
                        item["status"] = "waiting"
                        self._save_queue()
                        self._notify_ui()
                        self._start_download(item)
                    else:
                        break
                time.sleep(2)
            except Exception as e:
                log.error("DM worker error: {}".format(e))
                time.sleep(5)

    def _start_download(self, item):
        """Start download for a single item."""
        item_id = item["id"]
        output_filename = self._generate_filename(item)

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            item["status"] = "error"
            item["error"] = "FFmpeg is not installed or is not in PATH"
            self._save_queue()
            self._notify_ui()
            log.error("DM: FFmpeg check failed: {}".format(item["error"]))
            return

        log.info("DM: FFmpeg check OK: {}".format(ffmpeg_path))

        # Resolve stream URL before starting
        try:
            url = self._resolve_item_url(item)
        except Exception as e:
            item["status"] = "error"
            item["error"] = "Unable to resolve stream: {}".format(e)
            self._save_queue()
            self._notify_ui()
            log.error("DM: {}".format(item["error"]))
            return

        if not url:
            item["status"] = "error"
            item["error"] = "Unable to resolve stream URL"
            self._save_queue()
            self._notify_ui()
            return

        item["url"] = url

        # Get duration for progress calculation
        duration = self._get_duration(url)
        if duration > 0:
            item["duration"] = duration
            log.info("DM: Duration set to {} seconds".format(duration))
        else:
            # Fallback: assume 3600 seconds (1 hour) if ffprobe fails
            item["duration"] = 3600
            log.warning("DM: Using fallback duration of 3600 seconds")
        self._save_queue()

        # Check free space
        try:
            free_bytes = shutil.disk_usage(self.download_folder).free
            if free_bytes < MIN_FREE_BYTES:
                external_folder = self._find_external_download_folder()
                if external_folder:
                    self.download_folder = external_folder
                    free_bytes = shutil.disk_usage(external_folder).free
                    log.info(
                        "DM: Using external storage: {} ({} MB free)".format(
                            external_folder, free_bytes // (1024 * 1024)))
                    self._notify_ui()
                else:
                    item["status"] = "error"
                    item["error"] = (
                        "Insufficient free space ({} MB); no writable USB "
                        "storage found").format(free_bytes // (1024 * 1024))
                    self._save_queue()
                    self._notify_ui()
                    log.error("DM: {}".format(item["error"]))
                    return

            if free_bytes < MIN_FREE_BYTES:
                item["status"] = "error"
                item["error"] = "Insufficient free space ({} MB)".format(
                    free_bytes // (1024 * 1024))
                self._save_queue()
                self._notify_ui()
                log.error("DM: {}".format(item["error"]))
                return
        except Exception as e:
            log.warning("DM: Unable to check free space: {}".format(e))
            external_folder = self._find_external_download_folder()
            if external_folder:
                self.download_folder = external_folder
                log.info("DM: Using external storage: {}".format(external_folder))
                self._notify_ui()
            else:
                item["status"] = "error"
                item["error"] = "Download folder unavailable; no writable USB storage found"
                self._save_queue()
                self._notify_ui()
                log.error("DM: {}".format(item["error"]))
                return

        output_path = os.path.join(self.download_folder, output_filename)
        item["output_path"] = output_path
        item["status"] = "downloading"
        item["progress"] = 0
        item["downloaded"] = 0
        self._save_queue()
        self._notify_ui()

        log.info(
            "DM: Starting download: {} -> {}".format(item["title"], output_path))

        thread = threading.Thread(
            target=self._download_worker, args=(
                item, ffmpeg_path), daemon=True)
        self.workers[item_id] = thread
        thread.start()

    def _find_external_download_folder(self):
        """Return the roomiest writable movie folder on mounted block media."""
        candidates = []
        try:
            with open('/proc/mounts', 'r') as mounts_file:
                mounts = mounts_file.readlines()
        except Exception as e:
            log.warning("DM: Unable to inspect mounted storage: {}".format(e))
            return None

        for entry in mounts:
            fields = entry.split()
            if len(fields) < 4:
                continue

            device = fields[0]
            mountpoint = fields[1].replace('\\040', ' ')
            options = fields[3].split(',')

            # Enigma2 USB disks and pendrives are normally block devices
            # mounted below one of these media roots.  Network shares and the
            # receiver's internal root filesystem are intentionally excluded.
            if not device.startswith('/dev/'):
                continue
            if not mountpoint.startswith(('/media/', '/mnt/', '/autofs/')):
                continue
            if 'ro' in options or not os.path.isdir(mountpoint):
                continue

            try:
                free_bytes = shutil.disk_usage(mountpoint).free
                if free_bytes < MIN_FREE_BYTES:
                    continue

                movie_folder = os.path.join(mountpoint, 'movie')
                if not os.path.isdir(movie_folder):
                    os.makedirs(movie_folder)
                if os.access(movie_folder, os.W_OK):
                    candidates.append((free_bytes, movie_folder))
                    log.info(
                        "DM: External storage candidate: {} ({} MB free)".format(
                            movie_folder, free_bytes // (1024 * 1024)))
            except Exception as e:
                log.warning(
                    "DM: Storage candidate {} unavailable: {}".format(
                        mountpoint, e))

        if not candidates:
            return None

        candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        return candidates[0][1]

    def _download_worker(self, item, ffmpeg_path):
        """Actual download logic using ffmpeg."""
        item_id = item["id"]
        output_path = item["output_path"]
        url = item["url"]

        cmd = [
            ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-nostats",
            "-progress", "pipe:2",
            "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36",
            "-referer", "https://vixsrc.to/",
            "-i", url,
            "-map", "0:v:0?",
            "-map", "0:a:0?",
            "-c", "copy",
            "-movflags", "+faststart",
            "-y",
            output_path
        ]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            self.processes[item_id] = process
            last_progress_update = -5
            error_lines = []
            progress_keys = set((
                "bitrate", "codec_type", "drop_frames", "dup_frames",
                "end_time", "fps", "frame", "out_time", "out_time_ms",
                "out_time_us", "packet", "progress", "speed",
                "stream_0_0_q", "total_size"))
            total_duration = item.get("duration", 3600)

            while True:
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                if line.startswith("out_time_ms="):
                    try:
                        seconds = int(line.split("=", 1)[1].strip()) // 1000000
                        if seconds - last_progress_update >= 5:
                            last_progress_update = seconds
                            item["downloaded"] = seconds
                            if total_duration > 0:
                                progress = int((seconds / total_duration) * 100)
                                item["progress"] = min(progress, 99)
                            self._save_queue()
                            self._notify_ui()
                    except BaseException:
                        pass
                elif (line.strip() and
                      line.split("=", 1)[0].strip() not in progress_keys):
                    error_lines.append(line.strip())
                    if len(error_lines) > 20:
                        error_lines.pop(0)

            # Check if process was terminated by user (pause)
            if item.get("status") == "paused":
                log.info("DM: Download paused by user: {}".format(output_path))
                return

            if process.returncode == 0:
                item["status"] = "completed"
                item["progress"] = 100
                log.info("DM: Download completed: {}".format(output_path))
                self._create_meta_file(item)
            elif item.get("status") != "paused":
                item["status"] = "error"
                detail = " | ".join(error_lines[-5:])
                item["error"] = "ffmpeg error (code {}){}".format(
                    process.returncode,
                    ": {}".format(detail) if detail else "")
                log.error("DM: Download failed: {}".format(item["error"]))

        except Exception as e:
            if item.get("status") != "paused":
                item["status"] = "error"
                item["error"] = str(e)
                log.error("DM: Download error: {}".format(e))

        finally:
            if item_id in self.processes:
                del self.processes[item_id]
            if item_id in self.workers:
                del self.workers[item_id]
            self._save_queue()
            self._notify_ui()

    def _create_meta_file(self, item):
        """Create a .meta file with metadata for the downloaded content."""
        try:
            meta_path = item["output_path"] + ".meta"
            with open(meta_path, "w", encoding='utf-8') as f:
                f.write("title:{}\n".format(item["title"]))
                f.write("media_type:{}\n".format(item["media_type"]))
                if item["media_type"] == "tv":
                    f.write("season:{}\n".format(item["season"]))
                    f.write("episode:{}\n".format(item["episode"]))
                f.write("date:{}\n".format(int(time.time())))
                f.write("downloaded_from:SC Search\n")
                if item.get("error"):
                    f.write("error:{}\n".format(item["error"]))
            log.info("DM: Meta file created: {}".format(meta_path))
        except Exception as e:
            log.error("DM: Failed to create meta file: {}".format(e))

    def _resolve_item_url(self, item):
        """Resolve stream URL just before download starts."""
        resolver = item.get("resolver") or {}
        resolver_type = resolver.get("type")

        if resolver_type == "vixsrc":
            tmdb_id = resolver.get("tmdb_id")
            if not tmdb_id:
                return None
            season = resolver.get("season", 0)
            episode = resolver.get("episode", 0)
            from .search_functions import resolve_vixsrc_stream
            log.info("DM: Resolving VixSrc M3U8 for item {}".format(item["id"]))
            return resolve_vixsrc_stream(tmdb_id, season, episode)

        elif resolver_type == "direct":
            url = resolver.get("url")
            if url:
                # Ensure URL has protocol
                if not url.startswith("http://") and not url.startswith("https://"):
                    url = "https://" + url
                log.info("DM: Using direct URL for item {}".format(item["id"]))
                return url
            return item.get("url")

        elif resolver_type == "onlineserietv":
            log.warning("DM: OnlineSerieTV resolver not yet implemented")
            return item.get("url")

        # Fallback: ensure URL has protocol
        url = item.get("url")
        if url and not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        return url

    def _generate_filename(self, item):
        """Generate a safe filename from title and metadata."""
        title = item["title"].replace(" ", "_").replace("/", "_")
        if item["media_type"] == "tv" and item["season"] > 0 and item["episode"] > 0:
            return "{}_S{:02d}E{:02d}.mp4".format(
                title, item["season"], item["episode"])
        else:
            return "{}.mp4".format(title)

    def get_status(self, item_id):
        """Get status of a download item."""
        item = self._get_item(item_id)
        if item:
            return {
                "status": item["status"],
                "progress": item["progress"],
                "downloaded": item["downloaded"],
                "size": item["size"],
                "output_path": item["output_path"],
                "error": item["error"]
            }
        return None

    def register_ui_callback(self, callback):
        """Register a function to be called when queue changes."""
        if callback not in self.ui_callbacks:
            self.ui_callbacks.append(callback)

    def unregister_ui_callback(self, callback):
        if callback in self.ui_callbacks:
            self.ui_callbacks.remove(callback)

    def _notify_ui(self):
        """Notify all registered UI callbacks."""
        for cb in self.ui_callbacks:
            try:
                cb()
            except Exception as e:
                log.error("DM: UI callback error: {}".format(e))

    def get_queue(self):
        """Return a copy of the queue."""
        return self.queue[:]

    def clear_completed(self):
        """Remove all completed items from queue."""
        self.queue = [
            item for item in self.queue if item["status"] not in (
                "completed", "error")]
        self._save_queue()
        self._notify_ui()

    def get_free_space(self):
        try:
            return shutil.disk_usage(self.download_folder).free
        except Exception:
            return 0

    def get_total_space(self):
        try:
            return shutil.disk_usage(self.download_folder).total
        except Exception:
            return 0


# Global instance
download_manager = DownloadManager()
