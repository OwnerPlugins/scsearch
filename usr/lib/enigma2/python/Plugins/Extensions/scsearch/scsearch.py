# -*- coding: utf-8 -*-

import threading
import re
import urllib.request
import urllib.error
import os
import tempfile
import subprocess
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.ScrollLabel import ScrollLabel
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from enigma import eTimer

from .logger import get_logger
from .TmdbFetcher import TmdbFetcher
from .search_functions import perform_search, get_title_details
from . import _, load_skin

log = get_logger()


def get_config_path():
    """Return the path of the config.txt file."""
    return os.path.join(os.path.dirname(__file__), 'config.txt')


def ensure_config_exists():
    """Create the config.txt file if it does not exist."""
    config_path = get_config_path()
    if not os.path.exists(config_path):
        try:
            default_config = """# SC Search Plugin Configuration
STREAMING_COMMUNITY_URL=https://streamingcommunityz.organic/
REQUEST_TIMEOUT=30
USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36
LOG_ENABLED=true
LOG_LEVEL=INFO
LOG_MAX_SIZE=1048576
LOG_BACKUP_COUNT=3
TMDB_API_KEY=3c3efcf47c3577558812bb9d64019d65
MOVIE_HISTORY=
TV_HISTORY=
"""
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(default_config)
            log.info("Config file created: {}".format(config_path))
        except Exception as e:
            log.error("Error creating config.txt: {}".format(e))


def load_api_key():
    """Load TMDB API key from config.txt file."""
    try:
        ensure_config_exists()
        config_path = get_config_path()
        log.info("Loading API key from: {}".format(config_path))
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('TMDB_API_KEY='):
                    api_key = line.strip().split('=', 1)[1].strip()
                    if api_key and api_key != "YOUR_API_KEY_HERE":
                        log.info("API key loaded successfully")
                        return api_key
    except Exception as e:
        log.error("Unable to read API key from config file: {}".format(e))

    # Fallback hardcoded key
    log.warning("Using hardcoded TMDB API key")
    return "3c3efcf47c3577558812bb9d64019d65"


def load_search_history():
    try:
        ensure_config_exists()
        config_path = get_config_path()
        log.info("Loading history from: {}".format(config_path))
        history = {'movie': [], 'tv': []}
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('MOVIE_HISTORY='):
                    movies = line.strip().split('=', 1)[1].strip()
                    if movies:
                        history['movie'] = [s.strip()
                                            for s in movies.split('|') if s.strip()]
                    log.info("Movie history loaded: {} items".format(
                        len(history['movie'])))
                elif line.strip().startswith('TV_HISTORY='):
                    tvs = line.strip().split('=', 1)[1].strip()
                    if tvs:
                        history['tv'] = [s.strip()
                                         for s in tvs.split('|') if s.strip()]
                    log.info("TV series history loaded: {} items".format(
                        len(history['tv'])))
        return history
    except Exception as e:
        log.error("Error loading history: {}".format(e))
        return {'movie': [], 'tv': []}


def save_search_history(history):
    try:
        ensure_config_exists()
        config_path = get_config_path()
        log.info("Saving history to: {}".format(config_path))
        lines = []

        # Read existing file
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            log.warning("Unable to read existing config.txt: {}".format(e))

        # Update lines
        movie_line = 'MOVIE_HISTORY=' + '|'.join(history['movie'][:10]) + '\n'
        tv_line = 'TV_HISTORY=' + '|'.join(history['tv'][:10]) + '\n'

        # Remove old history lines
        lines = [ls for ls in lines if not ls.startswith(
            'MOVIE_HISTORY=') and not ls.startswith('TV_HISTORY=')]

        # Add new lines
        lines.append(movie_line)
        lines.append(tv_line)

        with open(config_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        log.info(
            "History saved: {} movies, {} TV series".format(
                len(history['movie']), len(history['tv'])))
    except Exception as e:
        log.error("Error saving history: {}".format(e))


API_KEY = load_api_key()


class SCSearchMain(Screen):

    def __init__(self, session, initial_item=None, close_callback=None):
        skin_data = load_skin("SCSearchMain")
        if skin_data:
            self.skin = skin_data
        Screen.__init__(self, session)
        self.session = session
        self.initial_item = initial_item
        self.close_callback = close_callback
        self.api_key_error = False

        if not API_KEY:
            log.critical("TMDB_API_KEY not found or invalid in config.txt.")
            self.api_key_error = True

        self.tmdb_fetcher = TmdbFetcher(API_KEY)
        self.current_search = ""
        self.search_type = "movie"
        self.search_history = load_search_history()

        # Threading & Timers
        self._search_thread = None
        self._search_results = []
        self._search_ready = False
        self._search_timer = eTimer()
        self._search_timer.callback.append(self._on_sc_search_timer)

        self._details_thread = None
        self._details_result = None
        self._details_ready = False
        self._details_request_id = 0
        self._pending_details_request = None
        self._details_timer = eTimer()
        self._details_timer.callback.append(self._on_tmdb_details_timer)

        self._initial_details_thread = None
        self._initial_details_result = None
        self._initial_details_ready = False
        self._initial_details_timer = eTimer()
        self._initial_details_timer.callback.append(
            self._on_initial_details_timer)
        self._ostv_cover_ready = False
        self._ostv_cover_success = False
        self._ostv_cover_timer = eTimer()
        self._ostv_cover_timer.callback.append(self._update_ostv_cover)

        # UI Widgets
        self["background"] = Label()
        self["divider"] = Label()
        self["search_term"] = Label(
            _("Press GREEN (Movie) or YELLOW (TV Series) to search..."))
        self["results_list"] = MenuList([])
        self["details_title"] = Label(_("No content selected"))
        self["details_year"] = Label("")
        self["details_description"] = ScrollLabel("")
        self["cover_pixmap"] = Pixmap()
        self["key_red"] = Label(_("Exit"))
        self["key_green"] = Label(_("Search Movie"))
        self["key_yellow"] = Label(_("Search TV Series"))
        self["key_blue"] = Label(_("History"))
        self["key_erase"] = Label(_("<<< Erase Cron >>>"))

        # Action Map
        self["actions"] = ActionMap(["ColorActions", "OkCancelActions", "InfobarMenuActions"], {
            "cancel": self.close,
            "red": self.close,
            "green": self.start_search_movie,
            "yellow": self.start_search_tv,
            "blue": self.show_search_history,
            "ok": self.ok_pressed,
            "menu": self.erase_history,
        }, -2)

        # Listeners
        self["results_list"].onSelectionChanged.append(self.on_result_selected)
        self.onLayoutFinish.append(self.initial_setup)
        self.onClose.append(self.__onClose)

        self.picload = None
        self.cover_temp_path = "/tmp/scsearch_cover.jpg"

    def initial_setup(self):
        if self.api_key_error:
            self.session.open(
                MessageBox,
                _("TMDB API key not found or invalid!"),
                MessageBox.TYPE_ERROR)
            self.close()
            return

        if self.initial_item:
            self._start_initial_details_fetch()
        else:
            self.clear_details_panel()

    def _start_initial_details_fetch(self):
        if not self.initial_item:
            return
        if self._initial_details_thread and self._initial_details_thread.is_alive():
            return

        title = self.initial_item.get("title", "N/A")
        self["search_term"].setText(_("Details for: '%s'") % title)
        self["results_list"].setList([(title, self.initial_item)])
        self["details_title"].setText(_("Loading details..."))
        self["details_year"].setText("")
        self["details_description"].setText("")
        self.hide_cover_image()

        self._initial_details_thread = threading.Thread(
            target=self._do_initial_details_fetch, args=(self.initial_item,))
        self._initial_details_thread.daemon = True
        self._initial_details_ready = False
        self._initial_details_timer.start(50, False)
        self._initial_details_thread.start()

    def _do_initial_details_fetch(self, item):
        try:
            slug = item.get("slug")
            title = item.get("title")
            if not slug or not title:
                self._initial_details_result = None
                return

            sc_details = get_title_details(slug, title_name=title)
            if not sc_details:
                self._initial_details_result = None
                return

            sc_type = sc_details.get("type")
            media_type = "tv" if sc_type == "TvSeries" else "movie"

            tmdb_id = None
            search_results = self.tmdb_fetcher.search(title, media_type)
            if search_results:
                tmdb_id = search_results[0].get("id")

            if tmdb_id:
                details = self.tmdb_fetcher.get_details(tmdb_id, media_type)
                if details:
                    details['sc_slug'] = slug
                    details['sc_name'] = title
                    details['media_type'] = media_type
                    details['tmdb_id'] = tmdb_id
                self._initial_details_result = details
            else:
                self._initial_details_result = None

        except Exception as e:
            log.error("Error fetching initial details: {}".format(e))
            self._initial_details_result = None
        finally:
            self._initial_details_ready = True

    def _on_initial_details_timer(self):
        if not self._initial_details_ready:
            return
        self._initial_details_timer.stop()

        if self._initial_details_result:
            current_selection = self["results_list"].getCurrent()
            if current_selection:
                display_text = current_selection[0]
                self["results_list"].setList(
                    [(display_text, self._initial_details_result)])

        self.display_tmdb_details(self._initial_details_result)
        self._initial_details_ready = False
        self._initial_details_result = None
        self._initial_details_thread = None

    def start_search_movie(self):
        self.search_type = "movie"
        self.show_search_with_history()

    def start_search_tv(self):
        self.search_type = "tv"
        self.show_search_with_history()

    def show_search_with_history(self):
        """Show history then open the virtual keyboard."""
        self.search_history = load_search_history()
        history_list = self.search_history.get(self.search_type, [])

        log.info(
            "show_search_with_history: {} - {} items".format(
                self.search_type, len(history_list)))

        if not history_list:
            self.open_virtual_keyboard()
            return

        from Screens.ChoiceBox import ChoiceBox
        choices = []

        for term in history_list:
            choices.append((term, term))

        choices.append((_("--- New search ---"), "new"))
        choices.append((_("<<< Erase Cron >>>"), "erase"))

        title = _("Movie History") if self.search_type == "movie" else _(
            "TV Series History")
        self.session.openWithCallback(
            self.on_history_item_selected,
            ChoiceBox,
            title=title,
            list=choices
        )

    def erase_history(self, search_type=None):
        if search_type:
            self.search_history[search_type] = []
            msg = _("Movie history cleared") if search_type == 'movie' else _(
                "TV series history cleared")
        else:
            self.search_history['movie'] = []
            self.search_history['tv'] = []
            msg = _("Search history cleared")
        save_search_history(self.search_history)
        self.session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=3)

    def on_history_item_selected(self, choice):
        """Handle selection from history."""
        if not choice:
            return

        if choice[1] == "new":
            self.open_virtual_keyboard()
        elif choice[1] == "erase":
            self.erase_history(self.search_type)
        else:
            self.run_sc_search(choice[1])

    def open_virtual_keyboard(self):
        title = _("Search Movie") if self.search_type == "movie" else _(
            "Search TV Series")
        self.session.openWithCallback(
            lambda text: self.run_sc_search(text) if text else None,
            VirtualKeyBoard, title=title, text=self.current_search
        )

    def show_search_history(self):
        # Reload history from file
        self.search_history = load_search_history()
        movie_history = self.search_history.get('movie', [])
        tv_history = self.search_history.get('tv', [])

        log.info(
            "Showing history: {} movies, {} TV series".format(
                len(movie_history),
                len(tv_history)))

        if not movie_history and not tv_history:
            self.session.open(
                MessageBox,
                _("No previous searches found"),
                MessageBox.TYPE_INFO)
            return

        from Screens.ChoiceBox import ChoiceBox
        choices = []

        # Add movie history
        if movie_history:
            choices.append((_("--- MOVIES ---"), None))
            for term in movie_history:
                choices.append(("🎬 {}".format(term), ("movie", term)))

        # Add TV series history
        if tv_history:
            choices.append((_("--- TV SERIES ---"), None))
            for term in tv_history:
                choices.append(("📺 {}".format(term), ("tv", term)))

        choices.append((_("New search..."), "new"))
        choices.append((_("<<< Erase Cron >>>"), "erase"))

        self.session.openWithCallback(
            self.on_history_selected,
            ChoiceBox,
            title=_("Search History"),
            list=choices
        )

    def on_history_selected(self, choice):
        if choice and choice[1] == "new":
            self.open_virtual_keyboard()
        elif choice and choice[1] == "erase":
            self.erase_history()
        elif choice and choice[1] and isinstance(choice[1], tuple):
            search_type, term = choice[1]
            self.search_type = search_type
            self.run_sc_search(term)
        elif choice and choice[1] is None:
            # Separator selected, ignore
            pass

    def run_sc_search(self, search_term):
        term = (search_term or "").strip()
        if not term:
            return
        if self._search_thread and self._search_thread.is_alive():
            return

        self.current_search = term
        self.add_to_search_history(term)
        self["search_term"].setText(
            _("Searching for: '%s'") %
            self.current_search)
        self.clear_details_panel()
        self["results_list"].setList([(_("Searching..."), {})])

        self._search_thread = threading.Thread(
            target=self._do_sc_search, args=(
                self.current_search,))
        self._search_thread.daemon = True
        self._search_ready = False
        self._search_timer.start(50, False)
        self._search_thread.start()

    def add_to_search_history(self, term):
        history_list = self.search_history[self.search_type]
        if term in history_list:
            history_list.remove(term)
        history_list.insert(0, term)
        self.search_history[self.search_type] = history_list[:10]
        save_search_history(self.search_history)

    def _do_sc_search(self, term):
        try:
            # Main search on StreamingCommunity and CB01
            response = perform_search(term, search_type=self.search_type)
            sc_results = response.get('data', [])

            # If searching for TV series, also add results from OnlineSerieTV
            if self.search_type == "tv":
                try:
                    from .onlineserietv import search_onlineserietv
                    ostv_results = search_onlineserietv(term)

                    # Add OnlineSerieTV results
                    for ostv_result in ostv_results:
                        ostv_result['_raw'] = {
                            'id': 'ostv',
                            'slug': ostv_result.get('slug', ''),
                            'source': 'onlineserietv'
                        }
                        ostv_result['name'] = ostv_result.get('name', '')
                        ostv_result['release_date'] = ''

                    sc_results.extend(ostv_results)
                    log.info(
                        "SEARCH: Added {} OnlineSerieTV results".format(
                            len(ostv_results)))

                except Exception as e:
                    log.error("OnlineSerieTV search error: {}".format(e))

            self._search_results = sc_results

        except Exception as e:
            log.error("SC search error: {}".format(e))
            self._search_results = []
        finally:
            self._search_ready = True

    def _on_sc_search_timer(self):
        if not self._search_ready:
            return
        self._search_timer.stop()
        self.display_sc_results(self._search_results)
        self._search_ready = False
        self._search_results = []
        self._search_thread = None

    def display_sc_results(self, results):
        if not results:
            self["results_list"].setList([(_("No results found on SC."), {})])
            return

        search_words = self.current_search.strip().split()
        filtered_results = []
        try:
            patterns = [
                re.compile(
                    r'\b' +
                    re.escape(word) +
                    r'\b',
                    re.IGNORECASE) for word in search_words]
            for r in results:
                name = r.get("name", "")
                if all(p.search(name) for p in patterns):
                    raw_data = r.get('_raw', {})
                    item_type = raw_data.get('type')
                    source = raw_data.get('source')
                    log.info(
                        "FILTER: Item '{}' type={} source={}".format(
                            name, item_type, source))

                    # Filter by search type
                    if self.search_type == "tv":
                        # Accept external sources (OSTV, CB01, Altadefinizione)
                        if source in (
                                'onlineserietv', 'cb01', 'altadefinizione'):
                            filtered_results.append(r)
                        elif item_type == 'tv':
                            filtered_results.append(r)
                    elif self.search_type == "movie":
                        if source in ('cb01', 'altadefinizione'):
                            filtered_results.append(r)
                        elif item_type == 'movie':
                            filtered_results.append(r)
                    else:
                        filtered_results.append(r)
        except re.error as e:
            log.error("Regex error: {}".format(e))
            filtered_results = []

        if not filtered_results:
            # Fallback search
            try:
                from .search_functions import search_streaming_community_cool
                fallback_results = search_streaming_community_cool(
                    self.current_search)
                if fallback_results:
                    for fb_result in fallback_results:
                        fb_raw = fb_result.get('_raw', {})
                        fb_type = fb_raw.get('type')
                        if (self.search_type == 'movie' and fb_type == 'movie') or \
                           (self.search_type == 'tv' and fb_type == 'tv') or \
                           self.search_type not in ['movie', 'tv']:
                            filtered_results.append(fb_result)
            except Exception as e:
                log.error("FALLBACK: Error: {}".format(e))

            if not filtered_results:
                self["results_list"].setList(
                    [(_("No relevant results found."), {})])
                return

        items = []
        for r in filtered_results:
            raw_data = r.get('_raw', {})
            source = raw_data.get('source')
            name = r.get("name", "N/A")

            # --- CB01 ---
            if source == 'cb01':
                display_text = name
                item_data = {
                    "sc_name": name,
                    "sc_slug": raw_data.get('url', ''),
                    "media_type": self.search_type,
                    "_raw": raw_data
                }
                items.append((display_text, item_data))

            # --- ALTADEFINIZIONE (identical to CB01) ---
            elif source == 'altadefinizione':
                display_text = name
                item_data = {
                    "sc_name": name,
                    "sc_slug": raw_data.get('url', ''),
                    "media_type": self.search_type,
                    "_raw": raw_data
                }
                items.append((display_text, item_data))

            # --- OnlineSerieTV ---
            elif source == 'onlineserietv':
                name_clean = name.replace(' (ostv)', '').replace('[OSTV] ', '')
                display_text = "[OSTV] {}".format(name_clean)
                item_data = {
                    "sc_name": name_clean,
                    "sc_slug": r.get('slug', ''),
                    "media_type": self.search_type,
                    "_raw": raw_data,
                    "url": r.get('url', ''),
                    "poster": r.get('poster', ''),
                    "slug": r.get('slug', '')
                }
                items.append((display_text, item_data))

            # --- StreamingCommunity (default) ---
            else:
                tmdb_id = raw_data.get('tmdb_id')
                vixsrc_url = raw_data.get('vixsrc_url')
                if not tmdb_id or not vixsrc_url:
                    log.warning(
                        "Skipping result missing tmdb_id/vixsrc_url: {}".format(raw_data))
                    continue
                year = (r.get("release_date", "")[:4]) if r.get(
                    "release_date") else ""
                display_text = "{} ({})".format(name, year) if year else name
                item_data = {
                    "sc_name": name,
                    "sc_slug": str(tmdb_id),
                    "media_type": self.search_type,
                    "tmdb_id": tmdb_id,
                    "vixsrc_url": vixsrc_url,
                    "_raw": raw_data,
                }
                items.append((display_text, item_data))

        self["results_list"].setList(items)

    def on_result_selected(self):
        sel = self["results_list"].getCurrent()
        if not sel or not isinstance(sel[1], dict):
            self.clear_details_panel()
            return

        item_data = sel[1]
        raw_data = item_data.get('_raw', {})
        source = raw_data.get('source')

        # --- OnlineSerieTV ---
        if source == 'onlineserietv':
            self._details_request_id += 1
            self._pending_details_request = None
            title = item_data.get('sc_name', 'N/A')
            poster_url = item_data.get('poster')
            log.info(
                "OSTV_SELECTION: Title={}, Poster={}".format(
                    title, poster_url))
            self["details_title"].setText(title)
            self["details_year"].setText(_("OnlineSerieTV - TV Series"))
            self["details_description"].setText(
                _("Press OK to view full details..."))
            if poster_url:
                self._load_ostv_cover(poster_url)
            else:
                self.hide_cover_image()
            return

        # --- CB01 ---
        if source == 'cb01':
            self._details_request_id += 1
            self._pending_details_request = None
            title = item_data.get('sc_name', 'N/A').replace('[CB01] ', '')
            poster_url = raw_data.get('poster')
            log.info(
                "CB01_SELECTION: Title={}, Poster={}".format(
                    title, poster_url))
            self["details_title"].setText(_("[CB01] %s") % title)
            self["details_year"].setText("CB01")
            self["details_description"].setText(
                _("Content from CB01 - Press OK to open..."))
            if poster_url:
                self.show_cover_image(poster_url)
            else:
                self.hide_cover_image()
            return

        # --- ALTADEFINIZIONE (identical to CB01) ---
        if source == 'altadefinizione':
            self._details_request_id += 1
            self._pending_details_request = None
            title = item_data.get(
                'sc_name', 'N/A').replace('[Altadefinizione] ', '')
            poster_url = raw_data.get('poster')
            log.info(
                "ALTADEFINIZIONE_SELECTION: Title={}, Poster={}".format(
                    title, poster_url))
            self["details_title"].setText(_("[Altadefinizione] %s") % title)
            self["details_year"].setText("Altadefinizione")
            self["details_description"].setText(
                _("Content from Altadefinizione - Press OK to open..."))
            if poster_url:
                self.show_cover_image(poster_url)
            else:
                self.hide_cover_image()
            return

        # --- StreamingCommunity (default) ---
        title_to_search = item_data.get("sc_name", "")
        title_to_search = re.sub(
            r'^\[(SC|CB01|OSTV|Altadefinizione)\]\s*',
            '',
            title_to_search)
        media_type = item_data.get("media_type")
        if not title_to_search or not media_type:
            return

        if self._details_thread and self._details_thread.is_alive():
            self._pending_details_request = (
                title_to_search, media_type, item_data)
            self["details_title"].setText(_("Loading details from TMDB..."))
            self["details_year"].setText("")
            self["details_description"].setText("")
            self.hide_cover_image()
            return

        self._start_tmdb_details_fetch(title_to_search, media_type, item_data)

    def _start_tmdb_details_fetch(
            self,
            title_to_search,
            media_type,
            item_data):
        self._details_request_id += 1
        request_id = self._details_request_id
        self["details_title"].setText(_("Loading details from TMDB..."))
        self["details_year"].setText("")
        self["details_description"].setText("")
        self.hide_cover_image()

        self._details_thread = threading.Thread(
            target=self._do_tmdb_fetch, args=(
                title_to_search, media_type, item_data, request_id))
        self._details_thread.daemon = True
        self._details_ready = False
        self._details_timer.start(50, False)
        self._details_thread.start()

    def _do_tmdb_fetch(self, title, media_type, item_data, request_id):
        result = None
        try:
            # Check if we already have a tmdb_id in the raw data
            raw_data = item_data.get('_raw', {})
            existing_tmdb_id = raw_data.get(
                'tmdb_id') or item_data.get('tmdb_id')

            if existing_tmdb_id:
                # Use existing tmdb_id directly
                log.info(
                    "TMDB_FETCH: Using existing tmdb_id: {}".format(existing_tmdb_id))
                item_data['tmdb_id'] = existing_tmdb_id
                result = self.tmdb_fetcher.get_details(
                    existing_tmdb_id, media_type)
            else:
                # Search TMDB by title
                item_data.pop('tmdb_id', None)

                # For SC movies, try to extract the year from the original
                # display_text
                year = None
                sel = self["results_list"].getCurrent()
                if sel and isinstance(sel[0], str):
                    display_text = sel[0]
                    source = raw_data.get('source')
                    if not source and media_type == 'movie':
                        year_match = re.search(r'\((\d{4})\)', display_text)
                        if year_match:
                            year = year_match.group(1)
                            log.info(
                                "TMDB_FETCH: Year extracted from SC display: {}".format(year))

                # Search TMDB
                search_results = self.tmdb_fetcher.search(title, media_type)

                if search_results:
                    item_id = None
                    # If we have the year, look for exact match
                    if year:
                        for result in search_results:
                            result_year = (result.get('release_date') or result.get(
                                'first_air_date') or '')[:4]
                            if result_year == year:
                                item_id = result.get('id')
                                log.info(
                                    "TMDB_FETCH: Exact year match found: {}".format(year))
                                break

                    # If we didn't find a year match or don't have the year,
                    # look for exact title match
                    if not item_id:
                        title_lower = title.lower().strip()
                        for result in search_results:
                            result_title = (
                                result.get('title') or result.get('name') or '').lower().strip()
                            if result_title == title_lower:
                                item_id = result.get('id')
                                log.info(
                                    "TMDB_FETCH: Exact title match found: '{}'".format(result_title))
                                break

                    # Fallback: use first result
                    if not item_id:
                        item_id = search_results[0].get('id')
                        log.info(
                            "TMDB_FETCH: No exact match, using first result")

                    if item_id:
                        item_data['tmdb_id'] = item_id
                        result = self.tmdb_fetcher.get_details(
                            item_id, media_type)
        except Exception as e:
            log.error("Error fetching TMDB details: {}".format(e))
            import traceback
            log.error(traceback.format_exc())
        finally:
            self._details_result = (request_id, result)
            self._details_ready = True

    def _on_tmdb_details_timer(self):
        if not self._details_ready:
            return
        self._details_timer.stop()
        result = self._details_result
        self._details_ready = False
        self._details_result = None
        self._details_thread = None

        pending = self._pending_details_request
        if pending:
            self._pending_details_request = None
            self._start_tmdb_details_fetch(*pending)
            return

        request_id, data = result if isinstance(
            result, tuple) else (
            self._details_request_id, result)
        if request_id == self._details_request_id:
            self.display_tmdb_details(data)
        else:
            log.info(
                "TMDB_FETCH: Obsolete result ignored ({} != {})".format(
                    request_id, self._details_request_id))

    def display_tmdb_details(self, data):
        if not data:
            self["details_title"].setText(_("Details not available"))
            self["details_description"].setText(
                _("Unable to retrieve information from TMDB."))
            log.warning("TMDB_DETAILS: No data received")
            return

        poster_url = data.get('poster')
        log.info(
            "TMDB_DETAILS: Displaying details - Title: {}, Poster: {}".format(
                data.get('titolo', 'N/A'), poster_url))

        self["details_title"].setText(data.get('titolo', _('N/A')))
        self["details_year"].setText((data.get('data_uscita') or '')[:4])
        self["details_description"].setText(
            data.get('descrizione', _('Description not available.')))

        if poster_url:
            log.info(
                "TMDB_DETAILS: Loading poster from TMDB: {}".format(poster_url))
            self.show_cover_image(poster_url)
        else:
            log.warning("TMDB_DETAILS: No poster URL in TMDB data")
            self.hide_cover_image()

    def ok_pressed(self):
        log.info("OK_PRESSED: OK button pressed.")
        sel = self["results_list"].getCurrent()
        if not sel or not isinstance(sel[1], dict):
            log.warning("OK_PRESSED: No valid item selected.")
            return

        item_data = sel[1]
        raw_data = item_data.get('_raw', {})
        source = raw_data.get('source')
        media_type = item_data.get("media_type")
        sc_name = item_data.get("sc_name", "N/A")
        tmdb_id = item_data.get("tmdb_id")

        # Import needed only when opening details
        from .scdetails import SCDetailsScreen

        # PRIORITY 1: CB01 handling - open details screen
        if source == 'cb01':
            movie_url = raw_data.get('url')
            log.info(
                "OK_PRESSED: CB01 movie selected: '{}', URL: '{}'".format(
                    sc_name, movie_url))

            cb01_data = {
                'source': 'cb01',
                'cb01_url': movie_url,
                'title': sc_name,
                'poster': raw_data.get('poster', '')
            }

            self.session.open(SCDetailsScreen, movie_url, sc_name, cb01_data)
            return

        # PRIORITY 2: Altadefinizione handling (like CB01)
        if source == 'altadefinizione':
            movie_url = raw_data.get('url')
            log.info(
                "OK_PRESSED: Altadefinizione selected: '{}', URL: '{}'".format(
                    sc_name, movie_url))

            altadef_data = {
                'source': 'altadefinizione',
                'altadef_url': movie_url,
                'title': sc_name,
                'poster': raw_data.get('poster', '')
            }

            self.session.open(
                SCDetailsScreen,
                movie_url,
                sc_name,
                altadef_data)
            return

        # PRIORITY 3: OnlineSerieTV handling
        if source == 'onlineserietv':
            log.info(
                "OK_PRESSED: Opening OnlineSerieTV details screen for: '{}', URL: '{}'".format(
                    sc_name,
                    item_data.get(
                        'url',
                        '')))

            ostv_data = {
                'source': 'onlineserietv',
                'url': item_data.get('url', ''),
                'poster': item_data.get('poster', ''),
                'title': sc_name,
                'slug': item_data.get('slug', '')
            }
            self.session.open(
                SCDetailsScreen, item_data.get(
                    'url', ''), sc_name, ostv_data)
            return

        # PRIORITY 4: Movies and TV series via TMDB/vixsrc
        tmdb_id = item_data.get("tmdb_id")
        vixsrc_url = item_data.get("vixsrc_url")
        if tmdb_id and vixsrc_url:
            log.info(
                "OK_PRESSED: Opening TMDB details: '{}', tmdb_id={}".format(
                    sc_name, tmdb_id))

            sc_data = {
                'source': 'streamingcommunity',
                'tmdb_id': tmdb_id,
                'title': sc_name,
                'type': media_type,
                'vixsrc_url': vixsrc_url,
            }
            self.session.open(SCDetailsScreen, str(tmdb_id), sc_name, sc_data)
            return

        log.warning(
            "OK_PRESSED: No action available for: '{}'".format(sc_name))
        self.session.open(
            MessageBox,
            _("Unable to open details for this content"),
            MessageBox.TYPE_ERROR)

    def clear_details_panel(self):
        self["details_title"].setText(_("No content selected"))
        self["details_year"].setText("")
        self["details_description"].setText("")
        self.hide_cover_image()

    def clear_search(self):
        self.current_search = ""
        self["search_term"].setText(
            _("Press GREEN (Movie) or YELLOW (TV Series) to search..."))
        self["results_list"].setList([])
        self.clear_details_panel()

    def show_cover_image(self, url):
        try:
            log.info("COVER_DOWNLOAD: Starting download from {}".format(url))

            if self.picload is None:
                from enigma import ePicLoad
                self.picload = ePicLoad()
                log.info("COVER_DOWNLOAD: ePicLoad initialized")

            self._download_cover_image(url, self.cover_temp_path)
            log.info(
                "COVER_DOWNLOAD: Image downloaded to {}".format(
                    self.cover_temp_path))

            # Check and convert format if necessary
            if os.path.exists(self.cover_temp_path):
                with open(self.cover_temp_path, 'rb') as f:
                    content = f.read()

                # Convert WebP to JPEG if needed
                if content.startswith(b'RIFF') and b'WEBP' in content[:12]:
                    log.info(
                        "COVER_DOWNLOAD: WebP format detected, converting to JPEG")
                    content = self._convert_webp_to_jpeg(content)
                    if content:
                        with open(self.cover_temp_path, 'wb') as f:
                            f.write(content)
                        log.info("COVER_DOWNLOAD: WebP converted to JPEG")

            self.picload.setPara([200, 300, 1, 1, False, 1, "#00000000"])
            decode_result = self.picload.startDecode(
                self.cover_temp_path, 0, 0, False)
            log.info("COVER_DOWNLOAD: Decode result: {}".format(decode_result))

            if decode_result == 0:
                ptr = self.picload.getData()
                if ptr:
                    self["cover_pixmap"].instance.setPixmap(ptr)
                    self["cover_pixmap"].show()
                    log.info("COVER_DOWNLOAD: Image displayed successfully")
                else:
                    log.error("COVER_DOWNLOAD: Failed to get pixmap data")
            else:
                log.error(
                    "COVER_DOWNLOAD: Failed to decode image, trying format conversion")
                # Try to convert to JPEG using PIL/Pillow if available
                if self._try_convert_to_jpeg_pil(self.cover_temp_path):
                    log.info(
                        "COVER_DOWNLOAD: Retrying decode after PIL conversion")
                    decode_result = self.picload.startDecode(
                        self.cover_temp_path, 0, 0, False)
                    if decode_result == 0:
                        ptr = self.picload.getData()
                        if ptr:
                            self["cover_pixmap"].instance.setPixmap(ptr)
                            self["cover_pixmap"].show()
                            log.info(
                                "COVER_DOWNLOAD: Image displayed successfully after conversion")
                        else:
                            log.error(
                                "COVER_DOWNLOAD: Failed to get pixmap data after conversion")
                    else:
                        log.error(
                            "COVER_DOWNLOAD: Still failed to decode after conversion: {}".format(decode_result))
        except Exception as e:
            log.error("COVER_DOWNLOAD: Error - {}".format(e))
            import traceback
            log.error(
                "COVER_DOWNLOAD: Traceback - {}".format(traceback.format_exc()))
            self.hide_cover_image()

    def _download_cover_image(self, url, target_path):
        from urllib.parse import urlsplit

        candidates = [url]
        resized_match = re.search(r'(-\d+x\d+)(\.[a-zA-Z0-9]+)(?:\?.*)?$', url)
        if resized_match:
            candidates.append(
                url.replace(
                    resized_match.group(1) +
                    resized_match.group(2),
                    resized_match.group(2)))

        last_error = None
        for candidate in dict.fromkeys(candidates):
            parts = urlsplit(candidate)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Referer': "{}://{}/".format(parts.scheme, parts.netloc),
            }
            try:
                req = urllib.request.Request(candidate, headers=headers)
                with urllib.request.urlopen(req, timeout=12) as response:
                    with open(target_path, 'wb') as image_file:
                        image_file.write(response.read())
                if candidate != url:
                    log.info(
                        "COVER: Fallback poster download succeeded: {}".format(candidate))
                return
            except Exception as e:
                last_error = e
                log.warning(
                    "COVER: Download failed for {}: {}".format(
                        candidate, e))

        raise last_error

    def _load_ostv_cover(self, url):
        self._ostv_cover_ready = False
        self._ostv_cover_success = False
        self._ostv_cover_timer.start(100, False)
        threading.Thread(
            target=self._load_ostv_cover_async, args=(
                url,), daemon=True).start()

    def _load_ostv_cover_async(self, url):
        try:
            log.info("OSTV_COVER: Starting download from {}".format(url))
            from .onlineserietv import load_olstv_cookie

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
                'Referer': 'https://onlineserietv.com/',
            }

            cookie = load_olstv_cookie()
            if cookie:
                headers['Cookie'] = cookie
                log.info("OSTV_COVER: Using cookie for authentication")

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                log.info(
                    "OSTV_COVER: Response status: {}".format(
                        response.getcode()))

                # Read content
                content = response.read()

                # Verify it's a valid image
                if not self._is_valid_image(content):
                    log.error(
                        "OSTV_COVER: Downloaded content is not a valid image")
                    return

                # Convert WebP to JPEG if needed
                if content.startswith(b'RIFF') and b'WEBP' in content[:12]:
                    log.info("OSTV_COVER: Converting WebP to JPEG")
                    content = self._convert_webp_to_jpeg(content)
                    if not content:
                        log.error("OSTV_COVER: Failed to convert WebP")
                        return

                with open(self.cover_temp_path, 'wb') as f:
                    f.write(content)

            log.info(
                "OSTV_COVER: Image saved to {}".format(
                    self.cover_temp_path))
            self._ostv_cover_success = True

        except Exception as e:
            log.error("OSTV_COVER: Error downloading: {}".format(e))
        finally:
            self._ostv_cover_ready = True

    def _update_ostv_cover(self):
        if not self._ostv_cover_ready:
            return
        self._ostv_cover_timer.stop()
        self._ostv_cover_ready = False
        if not self._ostv_cover_success:
            return
        try:
            log.info("OSTV_COVER: Updating UI with downloaded image")

            # Verify file exists and is valid
            if not os.path.exists(self.cover_temp_path):
                log.error("OSTV_COVER: Image file does not exist")
                return

            # Check file size
            file_size = os.path.getsize(self.cover_temp_path)
            if file_size < 1024:  # Less than 1KB likely not an image
                log.error(
                    "OSTV_COVER: Image file too small: {} bytes".format(file_size))
                return

            if self.picload is None:
                from enigma import ePicLoad
                self.picload = ePicLoad()

            self.picload.setPara([200, 300, 1, 1, False, 1, "#00000000"])
            decode_result = self.picload.startDecode(
                self.cover_temp_path, 0, 0, False)

            if decode_result == 0:
                ptr = self.picload.getData()
                if ptr:
                    self["cover_pixmap"].instance.setPixmap(ptr)
                    self["cover_pixmap"].show()
                    log.info("OSTV_COVER: Image displayed successfully")
                else:
                    log.error("OSTV_COVER: Failed to get pixmap data")
            else:
                log.error(
                    "OSTV_COVER: Failed to decode image, result: {}".format(decode_result))
                # Try to read file content for debug
                try:
                    with open(self.cover_temp_path, 'rb') as f:
                        header = f.read(20)
                        log.error("OSTV_COVER: File header: {}".format(header))
                except Exception:
                    pass

        except Exception as e:
            log.error("OSTV_COVER: Error updating UI: {}".format(e))

    def hide_cover_image(self):
        try:
            self["cover_pixmap"].hide()
        except Exception as e:
            log.error("hide_cover_image error: {}".format(e))

    def _get_tmdb_description_for_epg(self, tmdb_id, media_type):
        """Get content description from TMDB for EPG."""
        try:
            if not tmdb_id:
                return None

            details = self.tmdb_fetcher.get_details(tmdb_id, media_type)
            if details:
                description = details.get('descrizione', '')
                # Limit description for EPG (max 200 characters)
                if len(description) > 200:
                    description = description[:197] + "..."
                return description

        except Exception as e:
            log.error("Error getting TMDB description for EPG: {}".format(e))

        return None

    def _set_service_info_for_epg(self, service_ref, name, description):
        """Set extended service information for the EPG."""
        try:
            # Method 1: Use setName with extended info
            service_ref.setName(name)

            # Method 2: Try to set description using Enigma2 methods
            try:
                from enigma import iServiceInformation
                if hasattr(service_ref, 'setInfo'):
                    service_ref.setInfo(
                        iServiceInformation.sDescription, description)
                elif hasattr(service_ref, 'setData'):
                    service_ref.setData(1, description)  # 1 = description
            except Exception:
                # If advanced methods are not supported, add description to
                # name
                if description and len(description) < 100:
                    extended_name = "{}\n{}".format(name, description)
                    service_ref.setName(extended_name)

            log.info(
                "EPG_INFO: Set service info - Name: {}, Description: {}...".format(
                    name, description[:50]))

        except Exception as e:
            log.error("Error setting service info for EPG: {}".format(e))
            # Fallback: use only the name
            service_ref.setName(name)

    def _is_valid_image(self, content):
        """Check if the content is a valid image."""
        try:
            if len(content) < 10:
                return False

            # Check if it's HTML (common error)
            try:
                content_str = content[:200].decode(
                    'utf-8', errors='ignore').lower()
                if '<html' in content_str or '<!doctype' in content_str:
                    log.error("OSTV_COVER: Received HTML instead of image")
                    return False
            except Exception:
                pass

            # Check magic bytes for common image formats
            if content.startswith(b'\xff\xd8\xff'):  # JPEG
                return True
            elif content.startswith(b'\x89PNG\r\n\x1a\n'):  # PNG
                return True
            elif content.startswith(b'GIF87a') or content.startswith(b'GIF89a'):  # GIF
                return True
            # WebP
            elif content.startswith(b'RIFF') and b'WEBP' in content[:12]:
                return True
            elif content.startswith(b'BM'):  # BMP
                return True

            # Accept any binary content that is not HTML
            log.info("OSTV_COVER: Unknown image format, accepting anyway. Header: {}".format(
                content[:20]))
            return True

        except Exception as e:
            log.error("OSTV_COVER: Error validating image: {}".format(e))
            return True  # In case of error, accept anyway

    def _convert_webp_to_jpeg(self, webp_data):
        """Convert WebP to JPEG using ffmpeg if available."""
        try:
            # Create temporary files
            with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as webp_file:
                webp_file.write(webp_data)
                webp_path = webp_file.name

            jpeg_path = webp_path.replace('.webp', '.jpg')

            # Try with ffmpeg
            try:
                subprocess.run(
                    ['ffmpeg', '-i', webp_path, '-y', jpeg_path],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                with open(jpeg_path, 'rb') as f:
                    jpeg_data = f.read()

                # Clean up temporary files
                os.unlink(webp_path)
                os.unlink(jpeg_path)

                log.info("OSTV_COVER: WebP converted to JPEG successfully")
                return jpeg_data

            except (subprocess.CalledProcessError, FileNotFoundError):
                log.warning(
                    "OSTV_COVER: ffmpeg not available, trying alternative")

                # Fallback: save as is and hope Enigma2 handles it
                os.unlink(webp_path)
                return webp_data

        except Exception as e:
            log.error("OSTV_COVER: Error converting WebP: {}".format(e))
            return webp_data

    def _try_convert_to_jpeg_pil(self, image_path):
        """Try to convert an image to JPEG using PIL/Pillow."""
        try:
            from PIL import Image
            log.info(
                "COVER_CONVERT: Trying PIL conversion for {}".format(image_path))

            img = Image.open(image_path)

            # Convert to RGB if necessary (for PNG with transparency, etc.)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()
                                 [-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Save as JPEG
            img.save(image_path, 'JPEG', quality=90)
            log.info("COVER_CONVERT: PIL conversion successful")
            return True

        except ImportError:
            log.warning("COVER_CONVERT: PIL/Pillow not available")
            return False
        except Exception as e:
            log.error("COVER_CONVERT: PIL conversion failed: {}".format(e))
            return False

    def __onClose(self):
        for timer, cb in (
            (self._search_timer, self._on_sc_search_timer),
            (self._details_timer, self._on_tmdb_details_timer),
            (self._initial_details_timer, self._on_initial_details_timer),
            (self._ostv_cover_timer, self._update_ostv_cover),
        ):
            try:
                timer.stop()
                if cb in timer.callback:
                    timer.callback.remove(cb)
            except Exception:
                pass
        self.picload = None

    def close(self):
        self._search_timer.stop()
        self._details_timer.stop()
        self._initial_details_timer.stop()
        self._ostv_cover_timer.stop()
        super(SCSearchMain, self).close()
