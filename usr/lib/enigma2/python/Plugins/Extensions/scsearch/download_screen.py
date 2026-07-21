# -*- coding: utf-8 -*-

from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.LocationBox import LocationBox
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.ProgressBar import ProgressBar
from enigma import eTimer
from .logger import get_logger
from . import _, load_skin
from .download_manager import download_manager

log = get_logger()


class DownloadManagerScreen(Screen):
    def __init__(self, session):
        skin_data = load_skin("DownloadManagerScreen")
        if skin_data:
            self.skin = skin_data
        Screen.__init__(self, session)
        self.session = session
        self.selected_item_id = None

        self["info"] = Label(_("Download Queue"))
        self["list"] = MenuList([])
        self["status_label"] = Label("")
        self["diskspace"] = Label("")
        self["progress_bar"] = ProgressBar()
        self["key_red"] = Label(_("Remove"))
        self["key_green"] = Label(_("Start/Pause"))
        self["key_yellow"] = Label(_("Clear Done"))
        self["key_blue"] = Label(_("Change Folder"))
        self["hint"] = Label(
            _("OK = Select  |  RED = Remove  |  GREEN = Start/Pause  |  BLUE = Change Folder"))

        self["actions"] = ActionMap(["ColorActions", "OkCancelActions"], {
            "red": self.remove_selected,
            "green": self.toggle_selected,
            "yellow": self.clear_completed,
            "blue": self.change_folder,
            "ok": self.select_item,
            "cancel": self.close,
        }, -2)

        self.update_timer = eTimer()
        self.update_timer.callback.append(self.refresh)
        self.update_timer.start(1500, False)

        download_manager.register_ui_callback(self.refresh)
        self.onClose.append(self._on_close)
        self.onLayoutFinish.append(self.refresh)

    def _on_close(self):
        self.update_timer.stop()
        download_manager.unregister_ui_callback(self.refresh)

    def get_current_item_id(self):
        """Return the ID of the currently highlighted item."""
        selection = self["list"].getCurrent()
        if selection and len(selection) > 1 and selection[1]:
            return selection[1]
        return None

    def refresh(self):
        """Refresh the list from download manager."""
        queue = download_manager.get_queue()
        if not queue:
            self["list"].setList([(_("No downloads in queue"), None)])
            self["status_label"].setText("")
            self["diskspace"].setText("")
            self["progress_bar"].setValue(0)
            return

        items = []
        active_count = 0
        total_progress = 0
        progress_count = 0

        for item in queue:
            status_map = {
                "pending": _("Pending"),
                "waiting": _("Waiting"),
                "downloading": _("Downloading"),
                "paused": _("Paused"),
                "completed": _("Completed"),
                "error": _("Error")
            }
            status = status_map.get(item["status"], item["status"])
            title = item["title"]
            if item["media_type"] == "tv" and item["season"] > 0 and item["episode"] > 0:
                title = "{} S{:02d}E{:02d}".format(
                    title, item["season"], item["episode"])

            if item["status"] == "downloading":
                progress = item.get("progress", 0)
                # downloaded = item.get("downloaded", 0)
                # duration = item.get("duration", 0)

                # Barra di progresso disegnata con caratteri
                bar_length = 20
                filled = int(
                    (progress / 100) * bar_length) if progress > 0 else 0
                bar = "█" * filled + "░" * (bar_length - filled)
                display = "[{}] {}  {}  {}%".format(
                    status, title, bar, progress)

                active_count += 1
                total_progress += progress
                progress_count += 1
            elif item["status"] == "waiting":
                display = "[{}] {} - Queued".format(status, title)
                active_count += 1
            else:
                display = "[{}] {}".format(status, title)
            items.append((display, item["id"]))

        self["list"].setList(items)
        self.update_button_labels()

        # Update global progress bar (average of active downloads)
        if progress_count > 0:
            avg_progress = total_progress // progress_count
            self["progress_bar"].setValue(avg_progress)
        else:
            self["progress_bar"].setValue(0)

        total = len(queue)
        completed = len([i for i in queue if i["status"] == "completed"])
        errors = len([i for i in queue if i["status"] == "error"])
        # folder = download_manager.download_folder

        status_text = _("Total: {}  |  Active: {}  |  Completed: {}  |  Errors: {}").format(
            total, active_count, completed, errors)
        self["status_label"].setText(status_text)

        free = download_manager.get_free_space()
        total_space = download_manager.get_total_space()
        if free > 0 and total_space > 0:
            free_gb = free / (1024 * 1024 * 1024)
            total_gb = total_space / (1024 * 1024 * 1024)
            self["diskspace"].setText(
                _("Free: {:.2f} GB / {:.2f} GB").format(free_gb, total_gb))
        else:
            self["diskspace"].setText("")

    def update_button_labels(self):
        """Update GREEN button label based on selected item status."""
        item_id = self.get_current_item_id()
        if not item_id:
            self["key_green"].setText(_("Start/Pause"))
            return
        item = download_manager._get_item(item_id)
        if not item:
            self["key_green"].setText(_("Start/Pause"))
            return
        status = item.get("status")
        if status in ("pending", "waiting", "paused", "error"):
            self["key_green"].setText(_("Start"))
        elif status == "downloading":
            self["key_green"].setText(_("Pause"))
        elif status == "completed":
            self["key_green"].setText("")
        else:
            self["key_green"].setText(_("Start"))

    def select_item(self):
        """Select an item from the list."""
        item_id = self.get_current_item_id()
        if item_id:
            self.selected_item_id = item_id
            log.info("DM UI: Selected item: {}".format(self.selected_item_id))
            self.update_button_labels()

    def toggle_selected(self):
        """Toggle start/pause for selected item."""
        item_id = self.get_current_item_id()
        if not item_id:
            self.session.open(
                MessageBox,
                _("No item selected!"),
                MessageBox.TYPE_INFO)
            return
        item = download_manager._get_item(item_id)
        if not item:
            return
        status = item.get("status")
        if status in ("pending", "waiting", "paused", "error"):
            download_manager.start_item(item_id)
        elif status == "downloading":
            download_manager.pause_item(item_id)
        elif status == "completed":
            self.session.open(
                MessageBox,
                _("Download already completed!"),
                MessageBox.TYPE_INFO)
        self.refresh()

    def remove_selected(self):
        """Remove selected item from queue."""
        item_id = self.get_current_item_id()
        if not item_id:
            self.session.open(
                MessageBox,
                _("No item selected!"),
                MessageBox.TYPE_INFO)
            return
        download_manager.remove_item(item_id)
        self.refresh()

    def clear_completed(self):
        """Remove all completed and error items from queue."""
        download_manager.clear_completed()
        self.refresh()

    def change_folder(self):
        """Open LocationBox to select a new download folder."""
        self.session.openWithCallback(
            self._folder_selected,
            LocationBox,
            text=_("Choose download folder"),
            currDir=download_manager.download_folder
        )

    def _folder_selected(self, path):
        if path:
            if download_manager.set_download_folder(path):
                self.session.open(
                    MessageBox,
                    _("Download folder changed to:\n{}").format(path),
                    MessageBox.TYPE_INFO)
                self.refresh()
            else:
                self.session.open(
                    MessageBox,
                    _("Invalid folder!"),
                    MessageBox.TYPE_ERROR)

    def close(self):
        self._on_close()
        Screen.close(self)
