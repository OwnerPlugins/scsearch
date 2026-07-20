# -*- coding: utf-8 -*-

from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.LocationBox import LocationBox
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
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
        self.update_timer.start(2000, False)

        download_manager.register_ui_callback(self.refresh)
        self.onClose.append(self._on_close)
        self.onLayoutFinish.append(self.refresh)

    def _on_close(self):
        self.update_timer.stop()
        download_manager.unregister_ui_callback(self.refresh)

    def refresh(self):
        """Refresh the list from download manager."""
        queue = download_manager.get_queue()
        if not queue:
            self["list"].setList([(_("No downloads in queue"), None)])
            self["status_label"].setText("")
            return

        items = []
        for item in queue:
            status_map = {
                "pending": _("Pending"),
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
            display = "[{}] {}".format(status, title)
            items.append((display, item["id"]))

        self["list"].setList(items)
        total = len(queue)
        active = len([i for i in queue if i["status"] == "downloading"])
        folder = download_manager.download_folder
        self["status_label"].setText(
            _("Total: {}  |  Active: {}  |  Folder: {}").format(
                total, active, folder))

    def select_item(self):
        """Select an item from the list."""
        selection = self["list"].getCurrent()
        if selection and selection[1]:
            self.selected_item_id = selection[1]
            log.info("DM UI: Selected item: {}".format(self.selected_item_id))

    def remove_selected(self):
        """Remove selected item from queue."""
        if not self.selected_item_id:
            return
        download_manager.remove_item(self.selected_item_id)
        self.selected_item_id = None
        self.refresh()

    def toggle_selected(self):
        """Toggle start/pause for selected item."""
        if not self.selected_item_id:
            return
        item = download_manager._get_item(self.selected_item_id)
        if not item:
            return
        if item["status"] in ("pending", "paused", "error"):
            download_manager.start_item(self.selected_item_id)
        elif item["status"] == "downloading":
            download_manager.pause_item(self.selected_item_id)
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
