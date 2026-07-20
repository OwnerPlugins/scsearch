# -*- coding: utf-8 -*-

import os
import json
import threading
import time
import subprocess
from Components.config import config
from .logger import get_logger

log = get_logger()

QUEUE_FILE = "/tmp/scsearch_download_queue.json"


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

    def _load_queue(self):
        """Load queue from JSON file."""
        try:
            if os.path.exists(QUEUE_FILE):
                with open(QUEUE_FILE, 'r') as f:
                    self.queue = json.load(f)
                log.info("DM: Loaded {} items from queue".format(len(self.queue)))
        except Exception as e:
            log.error("DM: Failed to load queue: {}".format(e))
            self.queue = []

    def _save_queue(self):
        """Save queue to JSON file."""
        try:
            with open(QUEUE_FILE, 'w') as f:
                json.dump(self.queue, f, indent=2)
        except Exception as e:
            log.error("DM: Failed to save queue: {}".format(e))

    def add_item(
            self,
            title,
            url,
            media_type="movie",
            season=0,
            episode=0,
            poster=""):
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
            self._terminate_download(item_id)
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
        self._save_queue()
        self._notify_ui()

    def pause_item(self, item_id):
        """Pause a download."""
        if item_id in self.processes:
            self._terminate_download(item_id)
        item = self._get_item(item_id)
        if item:
            item["status"] = "paused"
            self._save_queue()
            self._notify_ui()

    def _terminate_download(self, item_id):
        """Terminate the download process."""
        if item_id in self.processes:
            try:
                self.processes[item_id].terminate()
            except BaseException:
                pass
            self.processes.pop(item_id, None)
        if item_id in self.workers:
            self.workers.pop(item_id, None)
        item = self._get_item(item_id)
        if item:
            item["status"] = "paused"

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
                pending = [
                    item for item in self.queue if item["status"] == "pending"]
                if pending and len(self.workers) < self.max_parallel:
                    item = pending[0]
                    self._start_download(item)
                time.sleep(2)
            except Exception as e:
                log.error("DM worker error: {}".format(e))
                time.sleep(5)

    def _start_download(self, item):
        """Start download for a single item."""
        item_id = item["id"]
        output_filename = self._generate_filename(item)
        output_path = os.path.join(self.download_folder, output_filename)
        item["output_path"] = output_path
        item["status"] = "downloading"
        self._save_queue()
        self._notify_ui()

        log.info(
            "DM: Starting download: {} -> {}".format(item["title"], output_path))

        thread = threading.Thread(
            target=self._download_worker, args=(
                item,), daemon=True)
        self.workers[item_id] = thread
        thread.start()

    def _download_worker(self, item):
        """Actual download logic using ffmpeg."""
        item_id = item["id"]
        url = item["url"]
        output_path = item["output_path"]

        cmd = [
            "ffmpeg",
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
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

            while True:
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                if "time=" in line:
                    try:
                        time_str = line.split("time=")[1].split()[0]
                        h, m, s = time_str.split(':')
                        seconds = int(h) * 3600 + int(m) * 60 + float(s)
                        item["downloaded"] = int(seconds)
                        self._save_queue()
                        self._notify_ui()
                    except BaseException:
                        pass

            if process.returncode == 0:
                item["status"] = "completed"
                log.info("DM: Download completed: {}".format(output_path))
            else:
                item["status"] = "error"
                item["error"] = "ffmpeg error (code {})".format(
                    process.returncode)
                log.error("DM: Download failed: {}".format(item["error"]))

        except Exception as e:
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


# Global instance
download_manager = DownloadManager()
