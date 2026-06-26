# -*- coding: utf-8 -*-

import os
import hashlib
import threading
import urllib.request
from enigma import eListbox, eListboxPythonMultiContent, gFont, RT_HALIGN_CENTER, RT_VALIGN_CENTER, ePicLoad, eTimer
from Components.GUIComponent import GUIComponent
from Tools.LoadPixmap import LoadPixmap
from .logger import get_logger
from . import _  # translation function

log = get_logger()

picloads = {}
MAX_POSTER_CACHE = 40
POSTER_CACHE_DIR = "/tmp/scsearch_posters"


def cleanup_picloads():
    """Clean up picload instances to free memory."""
    for key, data in list(picloads.items()):
        if "picload" in data and data["picload"]:
            if "callback" in data and data["callback"]:
                try:
                    data["picload"].PictureData.get().remove(data["callback"])
                except Exception:
                    pass
            del data["picload"]
    picloads.clear()


class PosterCarousel(GUIComponent):
    """
    A horizontal carousel component for displaying items with posters and text.
    Handles asynchronous poster downloading and caching.
    """
    GUI_WIDGET = eListbox

    def __init__(self):
        GUIComponent.__init__(self)
        self.listbox_content = eListboxPythonMultiContent()
        self.listbox_content.setBuildFunc(self.build_entry)
        self.itemHeight = 410
        self.itemWidth = 172
        self.posterHeight = 248
        self.fontSize = 18
        self._build_log_count = 0
        self.listbox_content.setItemHeight(self.itemHeight)
        if hasattr(self.listbox_content, "setItemWidth"):
            self.listbox_content.setItemWidth(self.itemWidth)
        self.listbox_content.setFont(0, gFont("Regular", self.fontSize))
        self.listbox_content.setFont(1, gFont("Regular", 15))
        self.listbox_content.setFont(2, gFont("Regular", 42))
        try:
            self.listbox_content.setOrientation(getattr(eListboxPythonMultiContent, "orHorizontal", 1))
        except Exception as e:
            log.error("CAROUSEL: content setOrientation failed: %s" % e)
        self.onSelectionChanged = []
        self.list = []
        self._download_timer = eTimer()
        self._download_timer.callback.append(self.refresh_downloaded_posters)
        self._debug_timer = eTimer()
        self._debug_timer.callback.append(self._debug_probe)
        try:
            base_dir = os.path.dirname(__file__)
            placeholder_path = os.path.join(base_dir, "placeholder.png")
            if not os.path.exists(placeholder_path):
                placeholder_path = os.path.join(base_dir, "sc_search.png")
            self.placeholder = LoadPixmap(placeholder_path)
            log.info("CAROUSEL: placeholder loaded from %s, ok=%s" % (placeholder_path, bool(self.placeholder)))
        except Exception:
            self.placeholder = None
            log.error("CAROUSEL: placeholder load failed")
        log.info("CAROUSEL: init itemWidth=%s itemHeight=%s content=%s has_setList=%s has_setBuildFunc=%s has_getCurrentSelection=%s" % (
            self.itemWidth,
            self.itemHeight,
            self.listbox_content.__class__.__name__,
            hasattr(self.listbox_content, "setList"),
            hasattr(self.listbox_content, "setBuildFunc"),
            hasattr(self.listbox_content, "getCurrentSelection"),
        ))

    def build_entry(self, *item_data):
        """
        Build a list entry for the carousel.
        Returns a list of tuples describing the entry's content (text, pixmap, etc.).
        """
        try:
            if len(item_data) == 1 and isinstance(item_data[0], (list, tuple)):
                item_data = item_data[0]
            slug, title, poster_url, meta, source = item_data
            if self._build_log_count < 10:
                log.info("CAROUSEL: build_entry #%d slug=%s title=%s poster=%s" % (
                    self._build_log_count + 1,
                    slug,
                    title,
                    bool(poster_url),
                ))
                self._build_log_count += 1
            width = self.itemWidth
            poster_pixmap = self.get_poster(poster_url, slug)
            entry = [
                None,
                (eListboxPythonMultiContent.TYPE_TEXT, 8, 8, width - 16, 28, 1, RT_HALIGN_CENTER | RT_VALIGN_CENTER, source),
                (eListboxPythonMultiContent.TYPE_TEXT, 10, self.posterHeight + 48, width - 20, 72, 0, RT_HALIGN_CENTER | RT_VALIGN_CENTER, title),
                (eListboxPythonMultiContent.TYPE_TEXT, 12, self.posterHeight + 126, width - 24, 30, 1, RT_HALIGN_CENTER | RT_VALIGN_CENTER, meta),
            ]
            if poster_pixmap:
                entry.insert(1, (eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST, 10, 42, width - 20, self.posterHeight, poster_pixmap))
            else:
                entry.insert(1, (eListboxPythonMultiContent.TYPE_TEXT, 10, 42, width - 20, self.posterHeight, 2, RT_HALIGN_CENTER | RT_VALIGN_CENTER, _("SC")))
            return entry
        except Exception as e:
            log.error("CAROUSEL: build_entry error: %s item=%s" % (e, str(item_data)[:160]))
            return [None, (eListboxPythonMultiContent.TYPE_TEXT, 8, 8, 150, 40, 0, RT_HALIGN_CENTER, _("Card error"))]

    def get_poster(self, url, slug):
        """
        Retrieve a poster pixmap for the given URL and slug.
        Handles caching, downloading, and asynchronous decoding.
        """
        if not url or not slug:
            return self.placeholder
        key = "poster_%s" % slug
        if key in picloads and picloads[key].get("ptr"):
            return picloads[key]["ptr"]
        if key not in picloads:
            if len(picloads) >= MAX_POSTER_CACHE:
                cleanup_picloads()
            picloads[key] = {"ptr": None, "url": url, "path": self._poster_path(url, slug)}

        local_path = picloads[key].get("path")
        if url.startswith("http") and local_path and not os.path.exists(local_path):
            if not picloads[key].get("downloading"):
                picloads[key]["downloading"] = True
                thread = threading.Thread(target=self._download_poster, args=(url, local_path, key))
                thread.daemon = True
                thread.start()
                self._download_timer.start(500, False)
            return self.placeholder

        decode_path = local_path if local_path and os.path.exists(local_path) else url
        if not picloads[key].get("picload"):
            picload = ePicLoad()

            def callback(pic_info, k=key):
                return self.pic_decoded(pic_info, k)

            picloads[key]["callback"] = callback
            picload.PictureData.get().append(callback)
            picload.setPara([self.itemWidth - 20, self.posterHeight, 1, 1, False, 1, "#00000000"])
            if picload.startDecode(decode_path, 0, 0, False) != 0:
                del picloads[key]
                return self.placeholder
            picloads[key]["picload"] = picload
        return self.placeholder

    def _poster_path(self, url, slug):
        """Generate a cache file path for a poster image."""
        try:
            if not os.path.exists(POSTER_CACHE_DIR):
                os.makedirs(POSTER_CACHE_DIR)
        except Exception:
            pass
        digest = hashlib.md5(("%s_%s" % (slug, url)).encode("utf-8")).hexdigest()
        return os.path.join(POSTER_CACHE_DIR, "%s.jpg" % digest)

    def _download_poster(self, url, path, key):
        """Download a poster image from URL and save to cache."""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            req = urllib.request.Request(url, headers=headers)
            data = urllib.request.urlopen(req, timeout=8).read()
            if data and len(data) > 512:
                with open(path, "wb") as f:
                    f.write(data)
                if key in picloads:
                    picloads[key]["downloaded"] = True
                log.info("CAROUSEL: poster downloaded key=%s bytes=%d" % (key, len(data)))
        except Exception:
            if key in picloads:
                picloads[key]["failed"] = True
            log.error("CAROUSEL: poster download failed key=%s url=%s" % (key, url))
        finally:
            if key in picloads:
                picloads[key]["downloading"] = False

    def refresh_downloaded_posters(self):
        """Check for newly downloaded posters and refresh the list entries."""
        pending = False
        for key, data in list(picloads.items()):
            if data.get("downloading"):
                pending = True
            if data.get("downloaded") and not data.get("ptr"):
                data["downloaded"] = False
                slug = key.replace("poster_", "")
                for index, entry in enumerate(self.list):
                    if entry[0] == slug:
                        try:
                            self.instance.invalidateEntry(index)
                        except Exception:
                            pass
                        break
        if pending:
            self._download_timer.start(500, False)

    def pic_decoded(self, pic_info, key):
        """Callback when a poster image has been decoded; update the entry."""
        if key not in picloads:
            return
        picload = picloads[key].get("picload")
        if picload:
            ptr = picload.getData()
            if ptr:
                picloads[key]["ptr"] = ptr
                for i, entry in enumerate(self.list):
                    if entry[0] == key.replace("poster_", ""):
                        try:
                            self.instance.invalidateEntry(i)
                        except Exception:
                            pass
                        break
            if picloads.get(key) and picloads[key].get("callback"):
                try:
                    picload.PictureData.get().remove(picloads[key]["callback"])
                except Exception:
                    pass
                picloads[key]["callback"] = None
            picloads[key]["picload"] = None

    def createWidget(self, parent):
        """Create the underlying eListbox widget."""
        log.info("CAROUSEL: createWidget called parent=%s" % parent.__class__.__name__)
        widget = eListbox(parent)
        log.info("CAROUSEL: createWidget returned widget=%s has_setContent=%s has_setItemWidth=%s has_invalidate=%s has_show=%s" % (
            widget.__class__.__name__,
            hasattr(widget, "setContent"),
            hasattr(widget, "setItemWidth"),
            hasattr(widget, "invalidate"),
            hasattr(widget, "show"),
        ))
        return widget

    def postWidgetCreate(self, instance):
        """Configure the widget after creation."""
        log.info("CAROUSEL: postWidgetCreate called")
        self.instance = instance
        instance.setContent(self.listbox_content)
        log.info("CAROUSEL: setContent done instance=%s content=%s same_content_object=%s" % (
            instance.__class__.__name__,
            self.listbox_content.__class__.__name__,
            bool(self.listbox_content),
        ))
        try:
            instance.setItemHeight(self.itemHeight)
            log.info("CAROUSEL: setItemHeight OK")
        except Exception as e:
            log.error("CAROUSEL: setItemHeight failed: %s" % e)
        try:
            if hasattr(instance, "setItemWidth"):
                instance.setItemWidth(self.itemWidth)
                log.info("CAROUSEL: setItemWidth OK")
        except Exception as e:
            log.error("CAROUSEL: setItemWidth failed: %s" % e)
        try:
            if hasattr(instance, "setOrientation"):
                horizontal = getattr(eListbox, "listHorizontal", 1)
                instance.setOrientation(horizontal)
                log.info("CAROUSEL: setOrientation OK")
        except Exception as e:
            log.error("CAROUSEL: setOrientation failed: %s" % e)
        try:
            instance.selectionChanged.get().append(self.selectionChanged)
        except Exception as e:
            log.error("CAROUSEL: selectionChanged append failed: %s" % e)
        self._log_instance_geometry("postWidgetCreate")
        log.info("CAROUSEL: widget ready")

    def preWidgetRemove(self, instance):
        """Clean up before widget removal."""
        try:
            instance.selectionChanged.get().remove(self.selectionChanged)
        except Exception:
            pass
        try:
            self._download_timer.stop()
        except Exception:
            pass
        try:
            self._debug_timer.stop()
        except Exception:
            pass
        cleanup_picloads()

    def selectionChanged(self, *args):
        """Callback when selection changes."""
        for f in self.onSelectionChanged:
            f()

    def setList(self, list_of_dicts):
        """Set the list of items to display in the carousel."""
        try:
            self.list = []
            self._build_log_count = 0
            for index, item in enumerate(list_of_dicts):
                slug = item.get("slug") or "item_%d" % index
                title = item.get("title") or item.get("name") or "N/A"
                poster_url = item.get("poster_url") or item.get("poster") or ""
                item_type = item.get("type") or item.get("media_type") or ""
                source = item.get("source") or item.get("provider") or "StreamingCommunity"
                meta = item_type if item_type else _("Press OK")
                self.list.append((slug, title, poster_url, meta, source))

            self.listbox_content.setList(self.list)
            first = self.list[0] if self.list else None
            log.info("CAROUSEL: setList with %d items first=%s content=%s" % (
                len(self.list),
                str(first)[:180],
                self.listbox_content.__class__.__name__,
            ))
            self._manual_build_entry_probe(first)
            try:
                if self.instance:
                    self.instance.invalidate()
                    self.instance.show()
                    log.info("CAROUSEL: instance invalidated and shown")
                    self._log_instance_geometry("setList")
                    self._debug_timer.start(250, True)
            except Exception as e:
                log.error("CAROUSEL: invalidate/show failed: %s" % e)

        except Exception as e:
            log.error("CAROUSEL: setList error: %s" % e)
            import traceback
            log.error(traceback.format_exc())
            self.list = []
            self.listbox_content.setList(self.list)

    def _manual_build_entry_probe(self, first):
        """Debug: manually build an entry to check for errors."""
        if not first:
            log.info("CAROUSEL_DIAG: manual_build skipped no first item")
            return
        try:
            before_count = self._build_log_count
            built = self.build_entry(first)
            self._build_log_count = before_count
            log.info("CAROUSEL_DIAG: manual_build OK len=%d first_type=%s entry0=%s" % (
                len(built),
                type(built[0]).__name__ if built else "none",
                str(built[0])[:80] if built else "none",
            ))
        except Exception as e:
            log.error("CAROUSEL_DIAG: manual_build FAILED: %s" % e)

    def _log_instance_geometry(self, where):
        """Log geometry information of the widget for debugging."""
        try:
            size = self.instance.size()
            log.info("CAROUSEL_DIAG: %s size=%sx%s" % (where, size.width(), size.height()))
        except Exception as e:
            log.error("CAROUSEL_DIAG: %s size unavailable: %s" % (where, e))
        try:
            position = self.instance.position()
            log.info("CAROUSEL_DIAG: %s position=%s,%s" % (where, position.x(), position.y()))
        except Exception as e:
            log.error("CAROUSEL_DIAG: %s position unavailable: %s" % (where, e))
        for method_name in ("isVisible", "isEnabled"):
            try:
                method = getattr(self.instance, method_name)
                log.info("CAROUSEL_DIAG: %s %s=%s" % (where, method_name, method()))
            except Exception as e:
                log.info("CAROUSEL_DIAG: %s %s unavailable: %s" % (where, method_name, e))

    def _debug_probe(self):
        """Periodic debug probe to check widget status."""
        log.info("CAROUSEL_DIAG: delayed_probe start list_len=%d build_calls_logged=%d instance=%s" % (
            len(self.list),
            self._build_log_count,
            bool(getattr(self, "instance", None)),
        ))
        self._log_instance_geometry("delayed_probe")
        try:
            current = self.listbox_content.getCurrentSelection()
            log.info("CAROUSEL_DIAG: delayed_probe content_current=%s" % (str(current)[:180],))
        except Exception as e:
            log.error("CAROUSEL_DIAG: delayed_probe content_current failed: %s" % e)
        for method_name in ("getCurrentIndex", "getSelectionIndex"):
            try:
                method = getattr(self.instance, method_name)
                log.info("CAROUSEL_DIAG: delayed_probe instance_%s=%s" % (method_name, method()))
            except Exception as e:
                log.info("CAROUSEL_DIAG: delayed_probe instance_%s unavailable: %s" % (method_name, e))
        if self.list:
            self._manual_build_entry_probe(self.list[0])
        log.info("CAROUSEL_DIAG: delayed_probe end")

    def getCurrent(self):
        """Return the currently selected item as a dictionary."""
        current_selection = self.listbox_content.getCurrentSelection()
        if current_selection:
            slug, title, poster_url, meta, source = current_selection
            return {"slug": slug, "title": title, "poster_url": poster_url, "type": meta, "source": source}
        return None

    def moveLeft(self):
        """Move selection left (previous item)."""
        try:
            self.instance.moveSelection(self.instance.moveLeft)
        except Exception:
            pass

    def moveRight(self):
        """Move selection right (next item)."""
        try:
            self.instance.moveSelection(self.instance.moveRight)
        except Exception:
            pass
