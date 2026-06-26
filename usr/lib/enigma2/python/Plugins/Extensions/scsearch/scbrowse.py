# -*- coding: utf-8 -*-

import re
import threading
import os
import hashlib
import urllib.request
try:
    from queue import Queue
except ImportError:
    from Queue import Queue

from enigma import eTimer, ePicLoad
from Screens.Screen import Screen
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from .logger import get_logger
from .search_functions import scrape_category_page, get_api_instance, get_title_details
from .TmdbFetcher import TmdbFetcher
from . import _, load_skin

log = get_logger()


def get_streaming_community_url():
    api = get_api_instance()
    return "https://%s" % api.domain


BASE_URL = get_streaming_community_url()

CATEGORIES = {
    "Top 10 di oggi": "%s/it/browse/top10" % BASE_URL,
    "I Titoli Del Momento": "%s/it/browse/trending" % BASE_URL,
    "Aggiunti di Recente": "%s/it/browse/latest" % BASE_URL,
    "Animazione": "%s/it/browse/genre?g=Animation" % BASE_URL,
    "Avventura": "%s/it/browse/genre?g=Adventure" % BASE_URL,
    "Azione": "%s/it/browse/genre?g=Action" % BASE_URL,
    "Commedia": "%s/it/browse/genre?g=Comedy" % BASE_URL,
    "Crime": "%s/it/browse/genre?g=Crime" % BASE_URL,
    "Documentario": "%s/it/browse/genre?g=Documentary" % BASE_URL,
    "Dramma": "%s/it/browse/genre?g=Drama" % BASE_URL,
    "Famiglia": "%s/it/browse/genre?g=Family" % BASE_URL,
    "Fantascienza": "%s/it/browse/genre?g=Science%%20Fiction" % BASE_URL,
    "Fantasy": "%s/it/browse/genre?g=Fantasy" % BASE_URL,
    "Horror": "%s/it/browse/genre?g=Horror" % BASE_URL,
    "Reality": "%s/it/browse/genre?g=Reality" % BASE_URL,
    "Romance": "%s/it/browse/genre?g=Romance" % BASE_URL,
    "Thriller": "%s/it/browse/genre?g=Thriller" % BASE_URL,
}

LOADING_CARD = {
    "title": _("Loading..."),
    "slug": "_loading",
    "poster_url": "",
    "type": _("Updating"),
    "source": "SC Search",
}

EMPTY_CARD = {
    "title": _("No content"),
    "slug": "_empty",
    "poster_url": "",
    "type": _("Retry"),
    "source": "SC Search",
}

ERROR_CARD = {
    "title": _("Load error"),
    "slug": "_error",
    "poster_url": "",
    "type": _("Refresh"),
    "source": "SC Search",
}

CARD_SLOTS = [{"x": 356,
               "y": 204,
               "w": 130,
               "h": 306,
               "poster_w": 110,
               "poster_h": 176,
               "font": 15,
               "focus": False},
              {"x": 500,
               "y": 184,
               "w": 150,
               "h": 346,
               "poster_w": 128,
               "poster_h": 204,
               "font": 16,
               "focus": False},
              {"x": 664,
               "y": 154,
               "w": 196,
               "h": 406,
               "poster_w": 160,
               "poster_h": 256,
               "font": 18,
               "focus": True},
              {"x": 874,
               "y": 184,
               "w": 150,
               "h": 346,
               "poster_w": 128,
               "poster_h": 204,
               "font": 16,
               "focus": False},
              {"x": 1038,
               "y": 204,
               "w": 130,
               "h": 306,
               "poster_w": 110,
               "poster_h": 176,
               "font": 15,
               "focus": False},
              ]

POSTER_CACHE_DIR = "/tmp/scsearch_browse_posters"


class SCBrowseMain(Screen):
    def __init__(self, session):
        skin_data = load_skin("SCBrowseMain")
        if skin_data:
            self.skin = skin_data
        Screen.__init__(self, session)
        self.session = session
        log.info("BROWSE: __init__ started")
        self.category_names = list(CATEGORIES.keys())
        self.category_data = dict((name, None) for name in self.category_names)
        self.category_errors = set()
        self.dirty_categories = set()
        self.current_items = []
        self.active_list = "categories"
        self.pending_count = 0
        self.loaded_count = 0
        self._closed = False
        self._queue = None
        self._workers = []
        self._load_generation = 0
        self.carousel_index = 0
        self.visible_carousel_items = []
        self._poster_jobs = {}
        self._poster_resolve_jobs = {}
        self._poster_url_cache = {}
        self._poster_pixmaps = [None, None, None, None, None]
        self._poster_picloads = []
        self._slot_poster_paths = ["", "", "", "", ""]
        self._slot_slugs = ["", "", "", "", ""]
        self._slot_generations = [0, 0, 0, 0, 0]
        self.tmdb_api_key = self._load_tmdb_api_key()

        self["bg"] = Label()
        self["top_band"] = Label()
        self["side_panel"] = Label()
        self["content_panel"] = Label()
        self["brand"] = Label("SC Search")
        self["subtitle"] = Label(
            _("Browse groups and cards with horizontal scrolling"))
        self["status"] = Label("")
        self["category_title"] = Label(_("GROUPS"))
        self["carousel_title"] = Label(_("CONTENTS"))
        self["counter"] = Label("")
        self["hint"] = Label(
            _("UP/DOWN groups  |  LEFT/RIGHT cards  |  OK open"))
        self["key_red"] = Label(_("EXIT"))
        self["key_green"] = Label(_("SEARCH"))
        self["key_blue"] = Label(_("REFRESH"))

        self["category_list"] = MenuList(self.category_names)
        for index in range(5):
            self["card_bg_%d" % index] = Label()
            self["card_poster_%d" % index] = Pixmap()
            self["card_source_%d" % index] = Label("")
            self["card_title_%d" % index] = Label("")
            self["card_meta_%d" % index] = Label("")
            self._poster_picloads.append(None)
        self.placeholder_path = os.path.join(
            os.path.dirname(__file__), "placeholder.png")
        if not os.path.exists(self.placeholder_path):
            self.placeholder_path = os.path.join(
                os.path.dirname(__file__), "sc_search.png")
        log.info(
            "BROWSE: fixed carousel widgets created placeholder=%s" %
            self.placeholder_path)

        self.poster_timer = eTimer()
        self.poster_timer.callback.append(self.process_poster_updates)

        self["actions"] = ActionMap(["ColorActions", "OkCancelActions", "DirectionActions"], {
            "cancel": self.close,
            "red": self.close,
            "green": self.open_search,
            "blue": self.refresh_categories,
            "ok": self.ok_pressed,
            "left": self.keyLeft,
            "right": self.keyRight,
            "up": self.keyUp,
            "down": self.keyDown,
        }, -2)

        self["category_list"].onSelectionChanged.append(
            self.on_category_selected)

        self.ui_timer = eTimer()
        self.ui_timer.callback.append(self.process_pending_updates)
        self.onLayoutFinish.append(self.initialize_home)
        log.info("BROWSE: __init__ completed")

    def initialize_home(self):
        self.update_poster_carousel()
        self.refresh_categories()

    def _load_tmdb_api_key(self):
        try:
            from .scsearch import get_config_path, ensure_config_exists
            ensure_config_exists()
            config_path = get_config_path()
            log.info(f"BROWSE: Loading TMDB API key from: {config_path}")
            with open(config_path, "r", encoding="utf-8") as config_file:
                for line in config_file:
                    if line.strip().startswith("TMDB_API_KEY="):
                        api_key = line.strip().split("=", 1)[1].strip()
                        log.info(
                            "BROWSE: TMDB API key available: {}".format(
                                bool(api_key)))
                        return api_key
        except Exception as e:
            log.error(f"BROWSE: Error reading TMDB API key: {e}")
        return None

    def refresh_categories(self):
        self.category_data = dict((name, None) for name in self.category_names)
        self.category_errors.clear()
        self.dirty_categories.clear()
        self.loaded_count = 0
        self.pending_count = len(self.category_names)
        self._load_generation += 1
        self.update_status()
        self.update_poster_carousel()
        self.start_scraping()

    def start_scraping(self):
        self._queue = Queue()
        current = self["category_list"].getCurrent() or self.category_names[0]
        ordered = [current] + \
            [name for name in self.category_names if name != current]
        for name in ordered:
            self._queue.put((name, CATEGORIES[name]))

        self._workers = []
        worker_count = min(3, len(ordered))
        generation = self._load_generation
        for index in range(worker_count):
            thread = threading.Thread(
                target=self._scrape_worker, args=(
                    generation,), name="SCBrowseWorker%d" %
                index)
            thread.daemon = True
            self._workers.append(thread)
            thread.start()

        self.ui_timer.start(250, False)

    def _scrape_worker(self, generation):
        while not self._closed:
            try:
                category_name, category_url = self._queue.get(False)
            except Exception:
                return
            if self._closed:
                return

            try:
                log.info("BROWSE: scraping %s" % category_name)
                items = scrape_category_page(category_url)
                if getattr(self, '_load_generation', None) != generation:
                    return
                self.category_data[category_name] = self._normalize_items(
                    items)
                log.info("BROWSE: %s loaded with %d items" %
                         (category_name, len(self.category_data[category_name])))
            except Exception as e:
                log.error("BROWSE: error scraping %s: %s" % (category_name, e))
                if getattr(self, '_load_generation', None) != generation:
                    return
                self.category_data[category_name] = []
                self.category_errors.add(category_name)
            finally:
                if getattr(self, '_load_generation', None) == generation:
                    self.dirty_categories.add(category_name)
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def _normalize_items(self, items):
        normalized = []
        for item in (items or [])[:24]:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name")
            slug = item.get("slug")
            if not title or not slug:
                continue
            normalized.append({
                "title": title,
                "slug": slug,
                "tmdb_id": item.get("tmdb_id") or item.get("tmdbId"),
                "poster_url": item.get("poster_url") or item.get("poster") or "",
                "type": item.get("type") or _("Title"),
                "source": item.get("source") or "StreamingCommunity",
            })
        return normalized

    def process_pending_updates(self):
        if self._closed:
            return

        if self.dirty_categories:
            dirty = set(self.dirty_categories)
            self.dirty_categories.clear()
            self.loaded_count = len(
                [name for name in self.category_names if self.category_data.get(name) is not None])
            current = self["category_list"].getCurrent(
            ) or self.category_names[0]
            if current in dirty:
                self.update_poster_carousel()
            self.update_status()

        if self.loaded_count >= len(self.category_names):
            self.ui_timer.stop()
            self.update_status()

    def update_status(self):
        total = len(self.category_names)
        if self.loaded_count < total:
            self["status"].setText(
                _("Updating cards %d/%d") %
                (self.loaded_count, total))
        else:
            errors = len(self.category_errors)
            if errors:
                self["status"].setText(
                    _("Updated, %d groups unavailable") %
                    errors)
            else:
                self["status"].setText(_("Cards updated"))

    def on_category_selected(self):
        self.active_list = "categories"
        self.carousel_index = 0
        self.update_poster_carousel()

    def update_poster_carousel(self):
        try:
            current_category = self["category_list"].getCurrent(
            ) or self.category_names[0]
            items = self.category_data.get(current_category)
            self["carousel_title"].setText(current_category)
            log.info(
                "BROWSE: update_poster_carousel category=%s items=%s" %
                (current_category, "None" if items is None else len(items)))

            if items is None:
                self.current_items = []
                self.carousel_index = 0
                self.update_carousel_cards([LOADING_CARD])
                self["counter"].setText(_("loading"))
            elif not items:
                self.current_items = []
                card = ERROR_CARD if current_category in self.category_errors else EMPTY_CARD
                self.carousel_index = 0
                self.update_carousel_cards([card])
                self["counter"].setText(_("0 titles"))
            else:
                self.current_items = items
                if self.carousel_index >= len(items):
                    self.carousel_index = 0
                self.update_carousel_cards(items)
                self["counter"].setText(_("%d titles") % len(items))
        except Exception as e:
            log.error("BROWSE: update carousel error: %s" % e)
            self.current_items = []
            self.carousel_index = 0
            self.update_carousel_cards([ERROR_CARD])
            self["counter"].setText(_("error"))

    def update_carousel_cards(self, items):
        self.visible_carousel_items = items or []
        total = len(items or [])
        log.info(
            "BROWSE_CAROUSEL: render total=%d center_index=%d" %
            (total, self.carousel_index))
        if total:
            self.carousel_index = self.carousel_index % total
        for slot in range(5):
            offset = slot - 2
            if total > 0:
                item_index = (self.carousel_index + offset) % total
                item = items[item_index]
                self._render_card(slot, item, item_index)
            else:
                self._clear_card(slot)

    def _can_scroll_carousel(self):
        if not self.visible_carousel_items or len(
                self.visible_carousel_items) < 2:
            return False
        first_slug = (self.visible_carousel_items[0].get("slug") or "")
        if first_slug.startswith("_"):
            return False
        return True

    def _render_card(self, slot, item, item_index):
        title = item.get("title") or item.get("name") or _("N/A")
        source = item.get("source") or item.get(
            "provider") or "StreamingCommunity"
        meta = item.get("type") or item.get("media_type") or _("Press OK")
        poster_url = item.get("poster_url") or item.get("poster") or ""
        slug = item.get("slug") or "item_%d" % item_index
        self._slot_slugs[slot] = slug
        self["card_source_%d" % slot].setText(source)
        self["card_title_%d" % slot].setText(title)
        self["card_meta_%d" % slot].setText(meta)
        if not poster_url:
            poster_url = self._poster_url_cache.get(slug, "")
        if poster_url and poster_url.lower().split(
                "?", 1)[0].endswith(".webp") and self.tmdb_api_key:
            cached_url = self._poster_url_cache.get(slug, "")
            if cached_url:
                poster_url = cached_url
            else:
                log.info(
                    "BROWSE_CAROUSEL: webp poster detected, resolving jpg fallback slug=%s url=%s" %
                    (slug, poster_url))
                self._resolve_missing_poster(slot, item, slug)
                poster_url = ""
        if not poster_url:
            self._resolve_missing_poster(slot, item, slug)
        self._set_card_poster(slot, poster_url, slug)
        log.info(
            "BROWSE_CAROUSEL: slot=%d item_index=%d title=%s slug=%s poster=%s" %
            (slot, item_index, title, slug, bool(poster_url), ))

    def _clear_card(self, slot):
        self["card_source_%d" % slot].setText("")
        self["card_title_%d" % slot].setText("")
        self["card_meta_%d" % slot].setText("")
        self._set_pixmap_from_path(
            slot,
            self.placeholder_path,
            CARD_SLOTS[slot]["poster_w"],
            CARD_SLOTS[slot]["poster_h"])

    def _set_card_poster(self, slot, poster_url, slug):
        if not poster_url:
            self._slot_poster_paths[slot] = self.placeholder_path
            self._set_pixmap_from_path(
                slot,
                self.placeholder_path,
                CARD_SLOTS[slot]["poster_w"],
                CARD_SLOTS[slot]["poster_h"])
            return
        log.info(
            "BROWSE_CAROUSEL: set poster slot=%d slug=%s url=%s" %
            (slot, slug, poster_url))
        path = self._poster_cache_path(poster_url, slug)
        self._slot_poster_paths[slot] = path
        if os.path.exists(path):
            self._set_pixmap_from_path(
                slot,
                path,
                CARD_SLOTS[slot]["poster_w"],
                CARD_SLOTS[slot]["poster_h"])
            return
        self._set_pixmap_from_path(
            slot,
            self.placeholder_path,
            CARD_SLOTS[slot]["poster_w"],
            CARD_SLOTS[slot]["poster_h"])
        key = "%s_%d" % (slug, slot)
        if self._poster_jobs.get(key):
            return
        self._poster_jobs[key] = {
            "slot": slot,
            "url": poster_url,
            "path": path,
            "done": False}
        thread = threading.Thread(
            target=self._download_card_poster, args=(key,))
        thread.daemon = True
        thread.start()
        self.poster_timer.start(250, False)

    def _resolve_missing_poster(self, slot, item, slug):
        if not slug or slug.startswith("_") or not self.tmdb_api_key:
            return
        if self._poster_url_cache.get(slug):
            return
        if self._poster_resolve_jobs.get(slug):
            return
        media_hint = (item.get("type") or item.get("media_type") or "").lower()
        self._poster_resolve_jobs[slug] = {
            "slot": slot,
            "slug": slug,
            "title": item.get("title") or item.get("name") or "",
            "media_hint": media_hint,
            "done": False,
        }
        thread = threading.Thread(
            target=self._resolve_missing_poster_worker, args=(
                slug,))
        thread.daemon = True
        thread.start()
        self.poster_timer.start(250, False)
        log.info(
            "BROWSE_CAROUSEL: resolving missing poster slug=%s slot=%d title=%s" %
            (slug, slot, self._poster_resolve_jobs[slug]["title"], ))

    def _resolve_missing_poster_worker(self, slug):
        if not self.tmdb_api_key:
            return
        job = self._poster_resolve_jobs.get(slug)
        if not job:
            return

        try:
            hint = job.get("media_hint") or ""
            if hint in ("tv", "tvseries", "serie", "series"):
                media_type = "tv"
            elif hint in ("movie", "film"):
                media_type = "movie"
            else:
                media_type = "movie"
            tmdb = TmdbFetcher(self.tmdb_api_key)
            title = job.get("title") or ""
            poster_url = None
            tmdb_id = None
            search_results = tmdb.search(title, media_type) or []
            if not search_results and media_type == "movie":
                media_type = "tv"
                search_results = tmdb.search(title, media_type) or []
            elif not search_results and media_type == "tv":
                media_type = "movie"
                search_results = tmdb.search(title, media_type) or []
            if search_results:
                first = search_results[0]
                tmdb_id = first.get("id")
                poster_path = first.get("poster_path")
                if poster_path:
                    poster_url = "%s%s" % (TmdbFetcher.IMAGE_BASE, poster_path)
                    job["poster_url"] = poster_url
                    log.info(
                        "BROWSE_CAROUSEL: resolved poster via tmdb search slug=%s title=%s tmdb_id=%s media=%s poster=True" %
                        (slug, title, tmdb_id, media_type, ))
                    return

            details = get_title_details(slug, title_name=title)
            tmdb_id = details.get("tmdb_id") if details else None
            media_type = "tv" if (details and details.get(
                "type") == "TvSeries") else media_type
            if not tmdb_id:
                log.info(
                    "BROWSE_CAROUSEL: resolve poster no tmdb_id slug=%s details=%s" %
                    (slug, bool(details)))
                job["poster_url"] = None
                return
            tmdb_details = tmdb.get_details(tmdb_id, media_type)
            poster_url = tmdb_details.get("poster") if tmdb_details else None
            job["poster_url"] = poster_url
            log.info(
                "BROWSE_CAROUSEL: resolved poster slug=%s tmdb_id=%s media=%s poster=%s" %
                (slug, tmdb_id, media_type, bool(poster_url), ))
        except Exception as e:
            job["poster_url"] = None
            log.error(
                "BROWSE_CAROUSEL: resolve poster failed slug=%s error=%s" %
                (slug, e))
        finally:
            job["done"] = True

    def _poster_cache_path(self, url, slug):
        try:
            if not os.path.exists(POSTER_CACHE_DIR):
                os.makedirs(POSTER_CACHE_DIR)
        except Exception:
            pass
        digest = hashlib.md5(("%s_%s" %
                              (slug, url)).encode("utf-8")).hexdigest()
        return os.path.join(POSTER_CACHE_DIR, "%s.jpg" % digest)

    def _download_card_poster(self, key):
        job = self._poster_jobs.get(key)
        if not job:
            return
        try:
            req = urllib.request.Request(
                job["url"], headers={
                    "User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=8).read()
            if data and len(data) > 512:
                with open(job["path"], "wb") as poster_file:
                    poster_file.write(data)
                job["ok"] = True
                log.info(
                    "BROWSE_CAROUSEL: poster downloaded slot=%d bytes=%d path=%s url=%s" %
                    (job["slot"], len(data), job["path"], job["url"]))
        except Exception as e:
            job["ok"] = False
            log.error(
                "BROWSE_CAROUSEL: poster download failed url=%s error=%s" %
                (job.get("url"), e))
        job["done"] = True

    def process_poster_updates(self):
        if self._closed:
            return
        pending = False
        for slug, job in list(self._poster_resolve_jobs.items()):
            if not job.get("done"):
                pending = True
                continue
            poster_url = job.get("poster_url")
            if poster_url:
                self._poster_url_cache[slug] = poster_url
                for slot, slot_slug in enumerate(self._slot_slugs):
                    if slot_slug == slug:
                        self._set_card_poster(slot, poster_url, slug)
                        log.info(
                            "BROWSE_CAROUSEL: applied resolved poster slot=%d slug=%s" %
                            (slot, slug))
            del self._poster_resolve_jobs[slug]
        for key, job in list(self._poster_jobs.items()):
            if not job.get("done"):
                pending = True
                continue
            if job.get("ok") and os.path.exists(job["path"]):
                slot = job["slot"]
                if self._slot_poster_paths[slot] == job["path"]:
                    self._set_pixmap_from_path(
                        slot,
                        job["path"],
                        CARD_SLOTS[slot]["poster_w"],
                        CARD_SLOTS[slot]["poster_h"])
            del self._poster_jobs[key]
        if pending:
            self.poster_timer.start(250, False)

    def _set_pixmap_from_path(self, slot, path, width, height):
        try:
            picload = ePicLoad()
            self._poster_picloads[slot] = picload
            picload.setPara([width, height, 1, 1, False, 1, "#00000000"])
            result = picload.startDecode(path, 0, 0, False)
            log.info(
                "BROWSE_CAROUSEL: decode slot=%d result=%s path=%s exists=%s size=%s" %
                (slot,
                 result,
                 path,
                 os.path.exists(path),
                 os.path.getsize(path) if os.path.exists(path) else 0,
                 ))
            if result != 0:
                log.error(
                    "BROWSE_CAROUSEL: decode start failed slot=%d path=%s" %
                    (slot, path))
                return
            ptr = picload.getData()
            log.info(
                "BROWSE_CAROUSEL: decode data slot=%d ptr=%s" %
                (slot, bool(ptr)))
            if ptr:
                self["card_poster_%d" % slot].instance.setPixmap(ptr)
                self["card_poster_%d" % slot].show()
        except Exception as e:
            log.error(
                "BROWSE_CAROUSEL: decode failed slot=%d path=%s error=%s" %
                (slot, path, e))

    def ok_pressed(self):
        if self.active_list == "categories":
            self.active_list = "carousel"
            self["hint"].setText(
                _("LEFT/RIGHT navigate  |  OK open  |  UP back to groups"))
            return
        self.poster_selected()

    def poster_selected(self):
        try:
            selection = None
            if self.visible_carousel_items and 0 <= self.carousel_index < len(
                    self.visible_carousel_items):
                selection = self.visible_carousel_items[self.carousel_index]
            if not selection:
                return
            slug = selection.get("slug")
            if not slug or slug.startswith("_"):
                return
            title = selection.get("title", _("N/A"))
            item_type = selection.get("type", "")

            # Extract TMDB ID from slug format "{id}-{name}"
            tmdb_id = selection.get("tmdb_id")
            id_match = re.match(r"^(\d+)-", slug)
            if not tmdb_id and id_match:
                tmdb_id = id_match.group(1)

            # Determine media_type from normalized type field
            type_lower = item_type.lower()
            if type_lower in ("tv", "tvseries"):
                media_type = "tv"
            elif type_lower in ("movie",):
                media_type = "movie"
            else:
                media_type = "movie"  # default SC

            vixsrc_type = "tv" if media_type == "tv" else "movie"
            vixsrc_url = "https://vixsrc.to/%s/%s" % (
                vixsrc_type, tmdb_id) if tmdb_id else ""

            sc_data = {
                "source": "streamingcommunity",
                "tmdb_id": tmdb_id,
                "title": title,
                "type": media_type,
                "slug": slug,
                "vixsrc_url": vixsrc_url,
                "poster_url": selection.get("poster_url") or selection.get("poster") or "",
            }

            log.info(
                "BROWSE: opening details slug=%s tmdb_id=%s type=%s" %
                (slug, tmdb_id, media_type))
            from .scdetails import SCDetailsScreen
            self.session.open(SCDetailsScreen, slug, title, sc_data)
        except Exception as e:
            log.error("BROWSE: poster selected error: %s" % e)

    def open_search(self):
        from .scsearch import SCSearchMain
        self.session.open(SCSearchMain)

    def keyUp(self):
        self.active_list = "categories"
        self["hint"].setText(
            _("UP/DOWN groups  |  LEFT/RIGHT cards  |  OK open"))
        self["category_list"].up()

    def keyDown(self):
        self.active_list = "categories"
        self["hint"].setText(
            _("UP/DOWN groups  |  LEFT/RIGHT cards  |  OK open"))
        self["category_list"].down()

    def keyLeft(self):
        if not self._can_scroll_carousel():
            log.info("BROWSE_CAROUSEL: keyLeft ignored, carousel not ready")
            return
        self.active_list = "carousel"
        self["hint"].setText(
            _("LEFT/RIGHT navigate  |  OK open  |  UP back to groups"))
        self.carousel_index = (self.carousel_index -
                               1) % len(self.visible_carousel_items)
        log.info("BROWSE_CAROUSEL: keyLeft new_center=%d total=%d" %
                 (self.carousel_index, len(self.visible_carousel_items)))
        self.update_carousel_cards(self.visible_carousel_items)

    def keyRight(self):
        self.active_list = "carousel"
        self["hint"].setText(
            _("LEFT/RIGHT navigate  |  OK open  |  UP back to groups"))
        if self._can_scroll_carousel():
            self.carousel_index = (
                self.carousel_index + 1) % len(self.visible_carousel_items)
            log.info("BROWSE_CAROUSEL: keyRight new_center=%d total=%d" %
                     (self.carousel_index, len(self.visible_carousel_items)))
            self.update_carousel_cards(self.visible_carousel_items)

    def close(self):
        self._closed = True

        try:
            self.ui_timer.stop()
        except Exception:
            pass
        try:
            self.poster_timer.stop()
        except Exception:
            pass
        for thread in self._workers:
            if thread.is_alive():
                thread.join(timeout=1.0)

        self._queue = None
        self._poster_jobs.clear()
        self._poster_resolve_jobs.clear()
        Screen.close(self)
