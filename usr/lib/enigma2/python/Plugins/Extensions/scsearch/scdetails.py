# -*- coding: utf-8 -*-

import threading
import os
import re
import urllib.request
from enigma import eTimer, eServiceReference
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Screens.InfoBar import MoviePlayer
from .logger import get_logger
from .search_functions import get_title_details
from . import _, load_skin

log = get_logger()


class SCDetailsScreen(Screen):

    def __init__(self, session, slug, title, ostv_data=None):
        skin_data = load_skin("SCDetailsScreen")
        if skin_data:
            self.skin = skin_data
        Screen.__init__(self, session)
        self.session = session
        self.slug = slug
        self.title = title
        self.ostv_data = ostv_data
        self.details = None
        self.seasons_data = {}
        self.selected_season = 1
        self.selected_episode = 1
        self.selected_cb01_link_index = 0
        self.selected_cb01_episode_index = 0

        self["title"] = Label(title)
        self["type_info"] = Label(_("Loading..."))
        self["season_label"] = Label(_("Seasons:"))
        self["episode_label"] = Label(_("Episodes:"))
        self["season_list"] = MenuList([])
        self["episode_list"] = MenuList([])
        self["cover_pixmap"] = Pixmap()
        self["info_panel"] = Label("")
        self["description_panel"] = Label("")
        self["key_red"] = Label(_("EXIT"))
        self["key_green"] = Label(_("PLAY MEDIA"))

        self.picload = None
        self.cover_temp_path = "/tmp/scdetails_cover.jpg"
        self._closed = False
        self._details_ready = False
        self._tmdb_info_ready = False
        self._tmdb_info_result = None
        self._tmdb_info_context = None
        self._tmdb_sc_ready = False
        self._tmdb_sc_result = None
        self._cover_ready = False
        self._cover_success = False
        self._ostv_cover_ready = False
        self._ostv_cover_success = False

        self.ui_timer = eTimer()
        self.ui_timer.callback.append(self._on_details_timer)
        self._tmdb_info_timer = eTimer()
        self._tmdb_info_timer.callback.append(self._on_tmdb_info_timer)
        self._tmdb_sc_timer = eTimer()
        self._tmdb_sc_timer.callback.append(self._on_tmdb_sc_timer)
        self._cover_timer = eTimer()
        self._cover_timer.callback.append(self._update_cover)
        self._ostv_cover_timer = eTimer()
        self._ostv_cover_timer.callback.append(self._update_ostv_cover)

        self["actions"] = ActionMap(["ColorActions", "OkCancelActions", "DirectionActions"], {
            "cancel": self.close,
            "red": self.close,
            "green": self.play_content,
            "left": self.keyLeft,
            "right": self.keyRight,
            "up": self.keyUp,
            "down": self.keyDown,
        }, -2)

        self.active_list = "seasons"
        self["season_list"].onSelectionChanged.append(self.on_season_selected)
        self["episode_list"].onSelectionChanged.append(
            self.on_episode_selected)
        self.onLayoutFinish.append(self.load_details)

        # Reference for playback end callback
        self.playback_session = None

    def load_details(self):
        self._details_ready = False
        self.ui_timer.start(100, False)
        thread = threading.Thread(target=self._fetch_details)
        thread.daemon = True
        thread.start()

    def _fetch_details(self):
        try:
            log.info(
                "DETAILS: Fetching details for slug='{}', title='{}'".format(
                    self.slug, self.title))

            # --- OnlineSerieTV ---
            if self.ostv_data and self.ostv_data.get(
                    'source') == 'onlineserietv':
                log.info("DETAILS: OnlineSerieTV content detected")
                from .onlineserietv import get_onlineserietv_details
                url = self.ostv_data.get('url', '')
                self.details = get_onlineserietv_details(url, self.title)
                log.info(
                    "DETAILS: OnlineSerieTV details: {}".format(
                        self.details))

            # --- StreamingCommunity ---
            elif self.ostv_data and self.ostv_data.get('source') == 'streamingcommunity':
                log.info("DETAILS: StreamingCommunity content detected")
                content_type = self.ostv_data.get('type', 'movie')
                media_type = 'tv' if content_type == 'tv' else 'movie'
                from .TmdbFetcher import TmdbFetcher
                from .scsearch import load_api_key
                api_key = load_api_key()
                real_tmdb_id = None
                if api_key:
                    tmdb = TmdbFetcher(api_key)
                    results = tmdb.search(self.title, media_type) or []
                    if results:
                        real_tmdb_id = results[0].get('id')
                if not real_tmdb_id:
                    real_tmdb_id = self.ostv_data.get('tmdb_id')
                vixsrc_type = 'tv' if media_type == 'tv' else 'movie'
                vixsrc_url = "https://vixsrc.to/{}/{}".format(
                    vixsrc_type, real_tmdb_id)
                self.details = {
                    'name': self.title,
                    'type': 'Movie' if media_type == 'movie' else 'TvSeries',
                    'tmdb_id': real_tmdb_id,
                    'source': 'streamingcommunity',
                    'vixsrc_url': vixsrc_url,
                }

            # --- CB01 ---
            elif self.ostv_data and self.ostv_data.get('source') == 'cb01':
                log.info("DETAILS: CB01 content detected")
                from .cb01 import CB01
                cb01_url = self.ostv_data.get('cb01_url', '')
                cb01_client = CB01()
                self.details = cb01_client.get_page_details(cb01_url)
                if self.details:
                    self.details['source'] = 'cb01'
                    self.details['cb01_url'] = cb01_url

            # --- ALTADEFINIZIONE (IDENTICAL TO CB01) ---
            elif self.ostv_data and self.ostv_data.get('source') == 'altadefinizione':
                log.info("DETAILS: Altadefinizione content detected")
                from .altadefinizione import Altadefinizione
                altadef_url = self.ostv_data.get('altadef_url', '')
                altadef_client = Altadefinizione()
                self.details = altadef_client.get_page_details(altadef_url)
                if self.details:
                    self.details['source'] = 'altadefinizione'
                    self.details['altadef_url'] = altadef_url
                log.info(
                    "DETAILS: Altadefinizione details: {}".format(
                        self.details))

            # --- Default: get_title_details ---
            else:
                self.details = get_title_details(
                    self.slug, title_name=self.title)

            # If it's a TV series with no episodes, try to parse the page
            if (self.details and
                self.details.get("type") == "TvSeries" and
                not self.details.get("episodeList") and
                    self.details.get('source') not in ['onlineserietv', 'streamingcommunity']):
                self._parse_seasons_from_page()

        except Exception as e:
            log.error("DETAILS: Error loading details: {}".format(e))
        finally:
            self._details_ready = True

    def _on_details_timer(self):
        if self._closed:
            self.ui_timer.stop()
            return
        if not self._details_ready:
            return
        self.ui_timer.stop()
        self._details_ready = False
        self.update_ui()

    def update_ui(self):
        log.info(
            "DETAILS: update_ui called with details: {}".format(
                self.details))
        try:
            if not self.details:
                log.error("DETAILS: No details available")
                self["type_info"].setText(_("Error loading details"))
                self["info_panel"].setText(_("Unable to load content details"))
                return

            content_type = self.details.get("type", _("Unknown"))
            log.info("DETAILS: Content type detected: {}".format(content_type))
            self["type_info"].setText(_("Type: %s") % content_type)

            if content_type == "TvSeries":
                log.info("DETAILS: Setting up TV series")
                self.setup_tv_series()
            else:
                log.info("DETAILS: Setting up movie")
                self.setup_movie()

            log.info("DETAILS: UI update completed")
        except Exception as e:
            log.error("DETAILS: Error in update_ui: {}".format(e))
            self["type_info"].setText(_("Error updating UI"))

    def setup_tv_series(self):
        # --- CB01 ---
        if self.details.get('source') == 'cb01':
            self._setup_cb01_series()
            return

        # --- ALTADEFINIZIONE (IDENTICAL TO CB01) ---
        if self.details.get('source') == 'altadefinizione':
            # Reuse the same logic as CB01 for series
            self._setup_cb01_series()
            return

        # --- OnlineSerieTV ---
        if self.details.get('source') == 'onlineserietv':
            self._setup_onlineserietv_series()
            return

        episodes = self.details.get("episodeList") or []
        log.info(
            "DETAILS: Found {} episodes for TV series".format(
                len(episodes)))

        if not episodes:
            # Check if we parsed seasons from the page
            if hasattr(self, 'parsed_seasons') and self.parsed_seasons:
                log.info(
                    "DETAILS: Using parsed seasons: {}".format(
                        self.parsed_seasons))
                seasons = sorted(self.parsed_seasons.keys())
                season_items = [
                    _("Season %d (%d episodes)") %
                    (s, self.parsed_seasons[s]) for s in seasons]
                self["season_list"].setList(season_items)

                # Episodes for the first season
                if seasons:
                    self.selected_season = seasons[0]
                    episode_count = self.parsed_seasons[self.selected_season]
                    episode_items = [
                        _("Episode %d") %
                        i for i in range(
                            1, episode_count + 1)]
                    self["episode_list"].setList(episode_items)
                    self.selected_episode = 1

                total_seasons = len(seasons)
                total_episodes = sum(self.parsed_seasons.values())

                # Load TMDB details
                tmdb_id = self.details.get("tmdb_id")
                if tmdb_id:
                    self._load_tmdb_info(
                        tmdb_id, total_seasons, total_episodes)
                else:
                    info_text = _("TV Series\nSeasons: %d\nTotal episodes: %d\nPress GREEN to play") % (
                        total_seasons, total_episodes)
                    self["info_panel"].setText(info_text)

                self.update_labels()
                log.info("DETAILS: TV series setup completed with parsed seasons")
                return

            # For StreamingCommunity, load TMDB anyway
            if self.details.get('source') == 'streamingcommunity':
                tmdb_id = self.details.get("tmdb_id")
                if tmdb_id:
                    log.info(
                        "DETAILS: Loading TMDB info for StreamingCommunity series: {}".format(tmdb_id))
                    self._load_tmdb_info_streamingcommunity(tmdb_id)
                    return

            log.warning("DETAILS: No episodes found for TV series")
            self["info_panel"].setText(_("No episodes available"))
            return

        # Group episodes by season
        for ep in episodes:
            season = ep.get("season", 1)
            if season not in self.seasons_data:
                self.seasons_data[season] = []
            self.seasons_data[season].append(ep)

        log.info("DETAILS: Grouped episodes into {} seasons: {}".format(
            len(self.seasons_data),
            list(self.seasons_data.keys())
        ))

        # Populate season list
        seasons = sorted(self.seasons_data.keys())
        season_items = [_("Season %d") % s for s in seasons]
        self["season_list"].setList(season_items)

        # Show episodes of the first season
        if seasons:
            self.selected_season = seasons[0]
            log.info(
                "DETAILS: Selected first season: {}".format(
                    self.selected_season))
            self.update_episodes()

        # Show info
        total_seasons = len(seasons)
        total_episodes = len(episodes)
        info_text = _("TV Series\nSeasons: %d\nTotal episodes: %d") % (
            total_seasons, total_episodes)
        log.info("DETAILS: TV series info: {}".format(info_text))
        self["info_panel"].setText(info_text)

    def setup_movie(self):
        log.info("DETAILS: Setting up movie interface")
        self["season_label"].setText("")
        self["episode_label"].setText("")
        self["season_list"].setList([])
        self["episode_list"].setList([])

        # For CB01, show parsed details
        if self.details.get('source') == 'cb01':
            streaming_links = self.details.get('streaming_links', [])
            link_count = len(streaming_links)

            info_text = _("CB01 Movie\n\nYear: %s\nGenre: %s\n\nLinks available: %d\n\nPress GREEN to play") % (
                self.details.get('year', _('N/A')), self.details.get('genre', _('N/A')), link_count)
            self["info_panel"].setText(info_text)

            description = self.details.get(
                'description', _('Description not available.'))
            self["description_panel"].setText(
                _("Description:\n\n%s") % description)

            # Show links in the season list
            if streaming_links:
                self["season_label"].setText(_("Available links:"))
                link_items = [
                    _("%s %s") %
                    (link.get(
                        'type', 'Hoster').title(), link.get(
                        'quality', 'SD')) for link in streaming_links]
                self["season_list"].setList(link_items)
                self.selected_cb01_link_index = 0

            poster_url = self.details.get('poster')
            if poster_url:
                self._load_cover(poster_url)
            return

        tmdb_id = self.details.get("tmdb_id")
        if tmdb_id:
            self._load_tmdb_info(tmdb_id, is_movie=True)
        else:
            info_text = _("Movie\nTMDB ID: %s\nPress GREEN to play") % tmdb_id
            self["info_panel"].setText(info_text)

    def update_episodes(self):
        # For OnlineSerieTV, calculate episodes per season
        if self.details and self.details.get('source') == 'onlineserietv':
            if hasattr(self, 'episodes_per_season'):
                # Calculate episodes for selected season
                base_episodes = self.episodes_per_season
                extra_episode = 1 if self.selected_season <= self.remaining_episodes else 0
                season_episodes = base_episodes + extra_episode

                episode_items = [
                    _("Episode %d") %
                    i for i in range(
                        1, season_episodes + 1)]
                self["episode_list"].setList(episode_items)
                self.selected_episode = 1
            return

        if hasattr(
                self,
                'seasons_data') and self.selected_season in self.seasons_data:
            episodes = self.seasons_data[self.selected_season]
            episode_items = [
                _("Episode %d: %s") %
                (ep.get(
                    'episode', 1), ep.get(
                    'name', _('N/A'))) for ep in episodes]
            self["episode_list"].setList(episode_items)
            if episodes:
                self.selected_episode = episodes[0].get("episode", 1)
        elif hasattr(self, 'parsed_seasons') and self.selected_season in self.parsed_seasons:
            # Use data parsed from the page
            episode_count = self.parsed_seasons[self.selected_season]
            episode_items = [
                _("Episode %d") %
                i for i in range(
                    1,
                    episode_count +
                    1)]
            self["episode_list"].setList(episode_items)
            self.selected_episode = 1

    def on_season_selected(self):
        try:
            selection = self["season_list"].getCurrent()
            if selection:
                # For CB01, the selection is the link index, not a season
                # number
                if self.details and self.details.get(
                        'source') == 'cb01' and self.details.get('type') == 'TvSeries':
                    # Extract season number from "Season X (Y episodes)"
                    import re
                    match = re.search(r'Season\s+(\d+)', selection)
                    if match:
                        season_num = int(match.group(1))
                        self.selected_season = season_num
                        self.selected_cb01_episode_index = 0
                        self.update_episodes()
                elif self.details and self.details.get('source') == 'cb01':
                    # Find the selected link index
                    streaming_links = self.details.get('streaming_links', [])
                    for i, link in enumerate(streaming_links):
                        link_label = _("%s %s") % (
                            link.get('type', 'Hoster').title(), link.get('quality', 'SD'))
                        if link_label == selection:
                            self.selected_cb01_link_index = i
                            log.info(
                                "CB01: Selected link index {} ({})".format(
                                    i, selection))
                            break
                else:
                    # Extract season number
                    import re
                    match = re.search(r'Season\s+(\d+)', selection)
                    if match:
                        season_num = int(match.group(1))
                        self.selected_season = season_num
                        # For StreamingCommunity, update episodes per season
                        if self.details and self.details.get(
                                'source') == 'streamingcommunity' and hasattr(self, 'sc_episodes_per_season'):
                            episode_items = [
                                _("Episode %d") %
                                i for i in range(
                                    1, self.sc_episodes_per_season + 1)]
                            self["episode_list"].setList(episode_items)
                            self.selected_episode = 1
                        else:
                            self.update_episodes()
        except Exception as e:
            log.error("Error in season selection: {}".format(e))

    def on_episode_selected(self):
        try:
            selection = self["episode_list"].getCurrent()
            if selection:
                if self.details and self.details.get(
                        'source') == 'cb01' and self.details.get('type') == 'TvSeries':
                    episodes = self.seasons_data.get(self.selected_season, [])
                    for i, episode in enumerate(episodes):
                        label = _("Episode %d: %s") % (episode.get(
                            'episode', 1), episode.get('name', _('N/A')))
                        if label == selection:
                            self.selected_cb01_episode_index = i
                            self.selected_episode = episode.get('episode', 1)
                            log.info(
                                "CB01: Selected episode link index {} ({})".format(
                                    i, selection))
                            return

                # Extract episode number
                import re
                match = re.search(r'Episode\s+(\d+)', selection)
                if match:
                    self.selected_episode = int(match.group(1))
        except Exception as e:
            log.error("Error in episode selection: {}".format(e))

    def play_content(self):
        if not self.details:
            return

        # --- OnlineSerieTV ---
        if self.details.get('source') == 'onlineserietv':
            self._build_onlineserietv_url()
            return

        # --- CB01 ---
        elif self.details.get('source') == 'cb01':
            self._play_cb01_content()
            return

        # --- ALTADEFINIZIONE ---
        elif self.details.get('source') == 'altadefinizione':
            if self.details.get('type') == 'TvSeries':
                self._play_altadefinizione_episode()
            else:
                self._play_altadefinizione_content()
            return

        # --- StreamingCommunity ---
        else:
            tmdb_id = self.details.get("tmdb_id")
            if not tmdb_id:
                self.session.open(
                    MessageBox,
                    _("TMDB ID not found"),
                    MessageBox.TYPE_ERROR)
                return

            if self.details.get("type") == "Movie":
                stream_url = "https://vixsrc.to/movie/{}".format(tmdb_id)
            else:
                stream_url = "https://vixsrc.to/tv/{}/{}/{}".format(
                    tmdb_id,
                    self.selected_season,
                    self.selected_episode
                )

            log.info("PLAY: Built URL: {}".format(stream_url))
            service_ref = eServiceReference(4097, 0, stream_url)

            if self.details.get("type") == "Movie":
                service_ref.setName(self.title)
            else:
                service_name = "{} - S{:02d}E{:02d}".format(
                    self.title,
                    self.selected_season,
                    self.selected_episode
                )
                service_ref.setName(service_name)

            self.session.openWithCallback(
                self.on_playback_stopped, MoviePlayer, service_ref)

    def _setup_onlineserietv_series(self):
        """Setup for OnlineSerieTV TV series."""
        try:
            log.info("DETAILS: Setting up OnlineSerieTV series")

            # Get season/episode information
            seasons_info = self.details.get('seasons_info')

            # Show general info even if seasons are not found
            info_text = _("OnlineSerieTV\n\nRating: %s\n\nCreator: %s") % (
                self.details.get('rating', _('N/A')),
                self.details.get('creator', _('N/A'))
            )
            description = self.details.get(
                'description', _('Description not available.'))

            self["description_panel"].setText(
                _("Description:\n\n%s") % description)

            poster_url = self.details.get('poster')
            if poster_url:
                log.info("OSTV_DETAILS: Loading poster: {}".format(poster_url))
                self._load_ostv_cover(poster_url)

            if seasons_info:
                total_seasons = seasons_info.get('total_seasons', 1)
                total_episodes = seasons_info.get('total_episodes', 1)

                season_items = [
                    _("Season %d") %
                    i for i in range(
                        1, total_seasons + 1)]
                self["season_list"].setList(season_items)

                self.selected_season = 1

                episodes_per_season = total_episodes // total_seasons
                remaining_episodes = total_episodes % total_seasons

                first_season_episodes = episodes_per_season + \
                    (1 if remaining_episodes > 0 else 0)
                episode_items = [
                    _("Episode %d") %
                    i for i in range(
                        1, first_season_episodes + 1)]
                self["episode_list"].setList(episode_items)
                self.selected_episode = 1

                self.episodes_per_season = episodes_per_season
                self.remaining_episodes = remaining_episodes
                self.total_seasons = total_seasons
                self.total_episodes = total_episodes

                # Add season info to panel
                info_text += _("\n\nSeasons: %d\nTotal episodes: %d") % (
                    total_seasons, total_episodes)

                self.update_labels()
                log.info("DETAILS: OnlineSerieTV series setup completed")
            else:
                log.warning("DETAILS: No seasons info found for OnlineSerieTV")
                info_text += _("\n\nSeason information not available")

            self["info_panel"].setText(info_text)

        except Exception as e:
            log.error(
                "DETAILS: Error setting up OnlineSerieTV series: {}".format(e))
            self["info_panel"].setText(_("Error loading OnlineSerieTV series"))

    def _play_altadefinizione_episode(self):
        """Play a TV series episode from Altadefinizione."""
        try:
            from .altadefinizione import Altadefinizione
            altadef_client = Altadefinizione()

            # Get the series URL from details
            series_url = self.details.get('altadef_url', '')
            if not series_url:
                self.session.open(
                    MessageBox,
                    _("Series URL not found"),
                    MessageBox.TYPE_ERROR)
                return

            # Get stream for selected episode
            stream_data = altadef_client.get_episode_stream(
                series_url,
                self.selected_season,
                self.selected_episode
            )

            if not stream_data or not stream_data.get('url'):
                self.session.open(
                    MessageBox,
                    _("Unable to get stream for this episode"),
                    MessageBox.TYPE_ERROR)
                return

            stream_url = stream_data['url']
            service_name = "{} - S{:02d}E{:02d} [Altadefinizione]".format(
                self.title,
                self.selected_season,
                self.selected_episode
            )

            log.info(
                "ALTADEFINIZIONE_EPISODE: Playing episode: {}".format(service_name))
            service_ref = eServiceReference(4097, 0, stream_url)
            service_ref.setName(service_name)
            self.session.openWithCallback(
                self.on_playback_stopped, MoviePlayer, service_ref)

        except Exception as e:
            log.error("ALTADEFINIZIONE_EPISODE: Error: {}".format(e))
            self.session.open(
                MessageBox, _("Error playing episode: %s") %
                e, MessageBox.TYPE_ERROR)

    def _play_altadefinizione_content(self):
        """Send Altadefinizione hoster link to decoder without decrypting."""
        try:
            if self.details.get('type') == 'TvSeries':
                # For TV series
                episodes = self.seasons_data.get(self.selected_season, [])
                selected_episode_data = None
                selected_index = getattr(
                    self, 'selected_altadef_episode_index', 0)
                if 0 <= selected_index < len(episodes):
                    selected_episode_data = episodes[selected_index]
                if not selected_episode_data and episodes:
                    selected_episode_data = episodes[0]

                if not selected_episode_data:
                    self.session.open(
                        MessageBox,
                        _("No Altadefinizione episode found"),
                        MessageBox.TYPE_ERROR)
                    return

                stream_url = selected_episode_data.get('url', '')
                quality = selected_episode_data.get('quality', 'Maxstream')
                service = selected_episode_data.get('type', 'maxstream')
                service_name = "{} - S{:02d}E{:02d} [{}]".format(
                    self.title,
                    self.selected_season,
                    self.selected_episode,
                    service.title()
                )
            else:
                # For movies
                streaming_links = self.details.get('streaming_links', [])
                if not streaming_links:
                    self.session.open(
                        MessageBox,
                        _("No streaming links found"),
                        MessageBox.TYPE_ERROR)
                    return

                link_index = getattr(self, 'selected_altadef_link_index', 0)
                if link_index >= len(streaming_links):
                    link_index = 0

                selected_link = streaming_links[link_index]
                log.info(
                    "ALTADEFINIZIONE_PLAY: Using link index {}: {}".format(
                        link_index, selected_link))

                stream_url = selected_link['url']
                quality = selected_link.get('quality', 'SD')
                service = selected_link.get(
                    'type') or selected_link.get('service') or 'hoster'
                service_name = "{} [{} {}]".format(
                    self.title, service.title(), quality)

            if not stream_url:
                self.session.open(
                    MessageBox,
                    _("Invalid streaming URL"),
                    MessageBox.TYPE_ERROR)
                return

            log.info(
                "ALTADEFINIZIONE_PLAY: Sending {} URL to decoder: {}".format(
                    service, stream_url))
            service_ref = eServiceReference(4097, 0, stream_url)
            service_ref.setName(service_name)
            self.session.openWithCallback(
                self.on_playback_stopped, MoviePlayer, service_ref)

        except Exception as e:
            log.error("ALTADEFINIZIONE_PLAY: Error: {}".format(e))
            import traceback
            log.error(
                "ALTADEFINIZIONE_PLAY: Traceback: {}".format(
                    traceback.format_exc()))
            self.session.open(
                MessageBox, _("Altadefinizione playback error: %s") %
                e, MessageBox.TYPE_ERROR)

    def _setup_cb01_series(self):
        """Setup for CB01 TV series with already extracted hoster links."""
        try:
            seasons = self.details.get('seasons', [])
            self.seasons_data = {}
            self.selected_cb01_episode_index = 0

            for season in seasons:
                season_number = season.get('season_number', 1)
                episodes = []
                for episode in season.get('episodes', []):
                    episode_number = episode.get('episode_number', 1)
                    service = episode.get('type', 'maxstream')
                    quality = episode.get('quality', service.title())
                    display_name = "{} {}".format(
                        service.title(),
                        quality) if quality.lower() != service.lower() else service.title()
                    episodes.append({
                        'episode': episode_number,
                        'name': display_name,
                        'url': episode.get('url', ''),
                        'original_url': episode.get('original_url', episode.get('url', '')),
                        'type': service,
                        'quality': quality
                    })
                if episodes:
                    self.seasons_data[season_number] = episodes

            season_numbers = sorted(self.seasons_data.keys())
            self["season_list"].setList(
                [_("Season %d") % s for s in season_numbers])

            if season_numbers:
                self.selected_season = season_numbers[0]
                self.update_episodes()

            total_episodes = sum(len(episodes)
                                 for episodes in self.seasons_data.values())
            info_text = _("CB01 TV Series\n\nSeasons: %d\nTotal episodes: %d\n\nPress GREEN to play") % (
                len(season_numbers), total_episodes)
            self["info_panel"].setText(info_text)

            description = self.details.get(
                'description', _('Description not available.'))
            self["description_panel"].setText(
                _("Description:\n\n%s") % description)

            poster_url = self.details.get('poster')
            if poster_url:
                self._load_cover(poster_url)

            self.update_labels()
            log.info(
                "DETAILS: CB01 series setup completed: {} seasons, {} episodes".format(
                    len(season_numbers), total_episodes))
        except Exception as e:
            log.error("DETAILS: Error setting up CB01 series: {}".format(e))
            self["info_panel"].setText(_("Error loading CB01 series"))

    def _play_cb01_content(self):
        """Send CB01 hoster link to decoder without decrypting."""
        try:
            if self.details.get('type') == 'TvSeries':
                episodes = self.seasons_data.get(self.selected_season, [])
                selected_episode_data = None
                selected_index = getattr(
                    self, 'selected_cb01_episode_index', 0)
                if 0 <= selected_index < len(episodes):
                    selected_episode_data = episodes[selected_index]
                if not selected_episode_data and episodes:
                    selected_episode_data = episodes[0]

                if not selected_episode_data:
                    self.session.open(
                        MessageBox,
                        _("No CB01 episode found"),
                        MessageBox.TYPE_ERROR)
                    return

                stream_url = selected_episode_data.get('url', '')
                quality = selected_episode_data.get('quality', 'Maxstream')
                service = selected_episode_data.get('type', 'maxstream')
                service_name = "{} - S{:02d}E{:02d} [{}]".format(
                    self.title,
                    self.selected_season,
                    self.selected_episode,
                    service.title()
                )
            else:
                streaming_links = self.details.get('streaming_links', [])

                if not streaming_links:
                    self.session.open(
                        MessageBox,
                        _("No streaming links found"),
                        MessageBox.TYPE_ERROR)
                    return

                link_index = getattr(self, 'selected_cb01_link_index', 0)
                if link_index >= len(streaming_links):
                    link_index = 0

                selected_link = streaming_links[link_index]
                log.info(
                    "CB01_PLAY: Using link index {}: {}".format(
                        link_index, selected_link))

                stream_url = selected_link['url']
                quality = selected_link.get('quality', 'SD')
                service = selected_link.get(
                    'type') or selected_link.get('service') or 'hoster'
                service_name = "{} [{} {}]".format(
                    self.title, service.title(), quality)

            if not stream_url:
                self.session.open(
                    MessageBox,
                    _("Invalid streaming URL"),
                    MessageBox.TYPE_ERROR)
                return

            log.info(
                "CB01_PLAY: Sending {} URL to decoder: {}".format(
                    service, stream_url))
            service_ref = eServiceReference(4097, 0, stream_url)
            service_ref.setName(service_name)
            self.session.openWithCallback(
                self.on_playback_stopped, MoviePlayer, service_ref)

        except Exception as e:
            log.error("CB01_PLAY: Error: {}".format(e))
            import traceback
            log.error(
                "CB01_PLAY: Traceback: {}".format(
                    traceback.format_exc()))
            self.session.open(
                MessageBox, _("CB01 playback error: %s") %
                e, MessageBox.TYPE_ERROR)

    def _build_onlineserietv_url(self):
        """Start asynchronous M3U8 URL extraction from OnlineSerieTV."""
        series_main_url = self.details.get('url')
        if not series_main_url:
            log.error("DETAILS: Main series URL not found for extraction.")
            self.session.open(
                MessageBox,
                _("Series URL not found."),
                MessageBox.TYPE_ERROR)
            return

        def stream_callback(stream_url):
            if stream_url:
                log.info("DETAILS: Stream URL received: {}".format(stream_url))
                self._play_stream_url(stream_url)
            else:
                log.error("DETAILS: No stream URL received")
                self.session.open(
                    MessageBox,
                    _("Unable to get streaming URL"),
                    MessageBox.TYPE_ERROR)

        from .onlineserietv import get_onlineserietv_stream_url
        get_onlineserietv_stream_url(
            series_main_url,
            self.selected_season,
            self.selected_episode,
            self.session,
            stream_callback)

    def _play_stream_url(self, stream_url):
        """Play the received stream URL."""
        try:
            log.info("PLAY: Playing stream URL: {}".format(stream_url))

            service_ref = self._create_ostv_service_ref(stream_url)

            # Set service name
            service_name = "{} - S{:02d}E{:02d}".format(
                self.title,
                self.selected_season,
                self.selected_episode
            )
            service_ref.setName(service_name)

            # Open player with callback for when it's closed
            self.session.openWithCallback(
                self.on_playback_stopped, MoviePlayer, service_ref)

        except Exception as e:
            log.error("PLAY: Playback error: {}".format(e))
            self.session.open(
                MessageBox, _("Playback error: %s") %
                e, MessageBox.TYPE_ERROR)

    def _create_ostv_service_ref(self, url):
        """Create service reference for M3U8 URL extracted from MaxStream."""
        try:
            log.info(
                "OSTV_SERVICE: Creating service ref for M3U8 URL: {}".format(url))

            # If it's an M3U8 URL, use it directly without additional headers
            if '.m3u8' in url:
                log.info("OSTV_SERVICE: M3U8 URL detected, using directly")
                return eServiceReference(4097, 0, url)
            else:
                # Fallback for non-M3U8 URLs (compatibility)
                log.warning(
                    "OSTV_SERVICE: Non-M3U8 URL, using with OnlineSerieTV headers")
                from .onlineserietv import load_olstv_cookie

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
                    'Referer': 'https://onlineserietv.com/'}

                cookie = load_olstv_cookie()
                if cookie:
                    headers['Cookie'] = cookie

                headers_str = '&'.join(
                    ["{}={}".format(k, v) for k, v in headers.items()])
                url_with_headers = "{}#{}".format(url, headers_str)

                log.info(
                    "OSTV_SERVICE: URL with headers: {}".format(url_with_headers))
                return eServiceReference(4097, 0, url_with_headers)

        except Exception as e:
            log.error("OSTV_SERVICE: Error creating service ref: {}".format(e))
            return eServiceReference(4097, 0, url)

    def on_playback_stopped(self, *args, **kwargs):
        """
        Callback executed when MoviePlayer is closed.
        Does nothing; Enigma2 will automatically return to this screen.
        """
        log.info(
            "DETAILS: Playback stopped callback - args: {}, kwargs: {}".format(args, kwargs))
        log.info("DETAILS: Returning to details screen.")
        # No action needed, Enigma2 handles the return.

    def keyLeft(self):
        self.active_list = "seasons"
        self.update_labels()

    def keyRight(self):
        if self.details and self.details.get("type") == "TvSeries":
            self.active_list = "episodes"
            self.update_labels()

    def update_labels(self):
        if self.active_list == "seasons":
            self["season_label"].setText(_(">>> Seasons <<<"))
            self["episode_label"].setText(_("Episodes"))
        else:
            self["season_label"].setText(_("Seasons"))
            self["episode_label"].setText(_(">>> Episodes <<<"))

    def keyUp(self):
        if self.active_list == "seasons":
            self["season_list"].up()
        elif self.active_list == "episodes":
            self["episode_list"].up()

    def keyDown(self):
        if self.active_list == "seasons":
            self["season_list"].down()
        elif self.active_list == "episodes":
            self["episode_list"].down()

    def _parse_seasons_from_page(self):
        try:
            # Only for StreamingCommunity, not OnlineSerieTV
            if self.ostv_data:
                return

            from .search_functions import get_api_instance
            api = get_api_instance()
            url = "https://{}/it/titles/{}".format(api.domain, self.slug)
            log.info("DETAILS: Parsing seasons from: {}".format(url))

            html_content = api._wbpage_as_text(url)

            # Look for season-item elements
            import re
            pattern = r'<li class="season-item"[^>]*>Stagione (\d+)[^<]*<span[^>]*>\((\d+) episodi\)</span></li>'
            matches = re.findall(pattern, html_content)

            log.info("DETAILS: Found season matches: {}".format(matches))

            if matches:
                self.parsed_seasons = {}
                for season_num, episode_count in matches:
                    season = int(season_num)
                    episodes = int(episode_count)
                    self.parsed_seasons[season] = episodes
                    log.info(
                        "DETAILS: Season {} has {} episodes".format(
                            season, episodes))

        except Exception as e:
            log.error("DETAILS: Error parsing seasons: {}".format(e))

    def _load_tmdb_info_streamingcommunity(self, tmdb_id):
        """Load TMDB info for StreamingCommunity TV series and populate seasons/episodes."""
        self._tmdb_sc_ready = False
        self._tmdb_sc_result = None
        self._tmdb_sc_timer.start(100, False)
        threading.Thread(
            target=self._fetch_tmdb_sc, args=(
                tmdb_id,), daemon=True).start()

    def _fetch_tmdb_sc(self, tmdb_id):
        try:
            from .TmdbFetcher import TmdbFetcher
            from .scsearch import load_api_key

            api_key = load_api_key()
            if not api_key:
                self._tmdb_sc_result = {'error': _('TMDB API key not found')}
                self._tmdb_sc_ready = True
                return

            tmdb = TmdbFetcher(api_key)
            details = tmdb.get_details(tmdb_id, "tv")

            self._tmdb_sc_result = details
            self._tmdb_sc_ready = True

        except Exception as e:
            log.error(
                "Error loading TMDB info for StreamingCommunity: {}".format(e))
            self._tmdb_sc_result = {'error': str(e)}
            self._tmdb_sc_ready = True

    def _on_tmdb_sc_timer(self):
        if self._closed:
            self._tmdb_sc_timer.stop()
            return
        if not self._tmdb_sc_ready:
            return
        self._tmdb_sc_timer.stop()

        details = self._tmdb_sc_result
        self._tmdb_sc_ready = False
        self._tmdb_sc_result = None

        if not details or 'error' in details:
            error_msg = details.get(
                'error', _('Error loading TMDB')) if details else _('Error loading TMDB')
            self["info_panel"].setText(_("TV Series\n%s") % error_msg)
            return

        num_seasons = details.get('numero_stagioni', 1)
        num_episodes = details.get('numero_episodi', 1)

        # Populate season list
        season_items = [_("Season %d") % i for i in range(1, num_seasons + 1)]
        self["season_list"].setList(season_items)
        self.selected_season = 1

        # Populate episodes for first season (estimate)
        episodes_per_season = max(1, num_episodes // num_seasons)
        episode_items = [
            _("Episode %d") %
            i for i in range(
                1,
                episodes_per_season +
                1)]
        self["episode_list"].setList(episode_items)
        self.selected_episode = 1

        # Save for later updates
        self.sc_num_seasons = num_seasons
        self.sc_num_episodes = num_episodes
        self.sc_episodes_per_season = episodes_per_season

        info_text = _("TV Series\n\nSeasons: %d\nTotal episodes: %d\n\nYear: %s\n\nRating: %s/10\n\nGenres:\n%s") % (
            num_seasons,
            num_episodes,
            details.get('data_uscita', _('N/A'))[:4],
            details.get('voto', _('N/A')),
            details.get('generi', _('N/A'))
        )
        self["info_panel"].setText(info_text)

        description = details.get(
            'descrizione', _('Description not available.'))
        self["description_panel"].setText(
            _("Description:\n\n%s") % description)

        poster_url = details.get('poster')
        if poster_url:
            self._load_cover(poster_url)

        self.update_labels()
        log.info(
            "DETAILS: StreamingCommunity TV series setup completed: {} seasons, {} episodes".format(
                num_seasons,
                num_episodes))

    def _load_tmdb_info(
            self,
            tmdb_id,
            total_seasons=0,
            total_episodes=0,
            is_movie=False):
        self._tmdb_info_ready = False
        self._tmdb_info_result = None
        self._tmdb_info_context = {
            "total_seasons": total_seasons,
            "total_episodes": total_episodes,
            "is_movie": is_movie,
        }
        self._tmdb_info_timer.start(100, False)
        threading.Thread(
            target=self._fetch_tmdb_info,
            args=(
                tmdb_id,
                is_movie),
            daemon=True).start()

    def _fetch_tmdb_info(self, tmdb_id, is_movie=False):
        try:
            from .TmdbFetcher import TmdbFetcher
            from .scsearch import load_api_key

            api_key = load_api_key()
            if not api_key:
                return

            tmdb = TmdbFetcher(api_key)
            media_type = "movie" if is_movie else "tv"
            self._tmdb_info_result = tmdb.get_details(tmdb_id, media_type)
        except Exception as e:
            log.error("Error loading TMDB info: {}".format(e))
            self._tmdb_info_result = None
        finally:
            self._tmdb_info_ready = True

    def _on_tmdb_info_timer(self):
        if self._closed:
            self._tmdb_info_timer.stop()
            return
        if not self._tmdb_info_ready:
            return
        self._tmdb_info_timer.stop()
        details = self._tmdb_info_result
        context = self._tmdb_info_context or {}
        self._tmdb_info_ready = False
        self._tmdb_info_result = None

        if not details:
            return

        is_movie = context.get("is_movie", False)
        total_seasons = context.get("total_seasons", 0)
        total_episodes = context.get("total_episodes", 0)
        if is_movie:
            info_text = _("Movie\n\nYear: %s\n\nRating: %s/10\n\nGenres:\n%s\n\nPress GREEN to play") % (
                details.get('data_uscita', _('N/A'))[:4],
                details.get('voto', _('N/A')),
                details.get('generi', _('N/A'))
            )
        else:
            info_text = _("TV Series\n\nSeasons: %d\nTotal episodes: %d\n\nYear: %s\n\nRating: %s/10\n\nGenres:\n%s") % (
                total_seasons,
                total_episodes,
                details.get('data_uscita', _('N/A'))[:4],
                details.get('voto', _('N/A')),
                details.get('generi', _('N/A'))
            )

        self["info_panel"].setText(info_text)
        description = details.get(
            'descrizione', _('Description not available.'))
        self["description_panel"].setText(
            _("Description:\n\n%s") % description)
        poster_url = details.get('poster')
        if poster_url:
            self._load_cover(poster_url)

    def _load_cover(self, url):
        self._cover_ready = False
        self._cover_success = False
        self._cover_timer.start(100, False)
        threading.Thread(
            target=self._load_cover_async, args=(
                url,), daemon=True).start()

    def _load_cover_async(self, url):
        try:
            self._download_cover_image(url, self.cover_temp_path)
            self._cover_success = True
        except Exception as e:
            log.error("Error loading cover: {}".format(e))
        finally:
            self._cover_ready = True

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
                        "COVER: Fallback poster download successful: {}".format(candidate))
                return
            except Exception as e:
                last_error = e
                log.warning(
                    "COVER: Download failed for {}: {}".format(
                        candidate, e))

        raise last_error

    def _update_cover(self):
        if self._closed:
            self._cover_timer.stop()
            return
        if not self._cover_ready:
            return
        self._cover_timer.stop()
        self._cover_ready = False
        if not self._cover_success:
            return
        try:
            from enigma import ePicLoad

            log.info(
                "DETAILS_COVER: Updating cover from {}".format(
                    self.cover_temp_path))

            # Check and convert format if necessary
            if os.path.exists(self.cover_temp_path):
                with open(self.cover_temp_path, 'rb') as f:
                    content = f.read()

                # Convert WebP to JPEG if needed
                if content.startswith(b'RIFF') and b'WEBP' in content[:12]:
                    log.info(
                        "DETAILS_COVER: WebP format detected, converting to JPEG")
                    content = self._convert_webp_to_jpeg(content)
                    if content:
                        with open(self.cover_temp_path, 'wb') as f:
                            f.write(content)
                        log.info("DETAILS_COVER: WebP converted to JPEG")

            if self.picload is None:
                self.picload = ePicLoad()

            self.picload.setPara([300, 450, 1, 1, False, 1, "#00000000"])
            decode_result = self.picload.startDecode(
                self.cover_temp_path, 0, 0, False)
            log.info("DETAILS_COVER: Decode result: {}".format(decode_result))

            if decode_result == 0:
                ptr = self.picload.getData()
                if ptr:
                    self["cover_pixmap"].instance.setPixmap(ptr)
                    self["cover_pixmap"].show()
                    log.info("DETAILS_COVER: Image displayed successfully")
                else:
                    log.error("DETAILS_COVER: Failed to get pixmap data")
            else:
                log.error(
                    "DETAILS_COVER: Failed to decode image, trying PIL conversion")
                # Try to convert to JPEG using PIL/Pillow if available
                if self._try_convert_to_jpeg_pil(self.cover_temp_path):
                    log.info(
                        "DETAILS_COVER: Retrying decode after PIL conversion")
                    decode_result = self.picload.startDecode(
                        self.cover_temp_path, 0, 0, False)
                    if decode_result == 0:
                        ptr = self.picload.getData()
                        if ptr:
                            self["cover_pixmap"].instance.setPixmap(ptr)
                            self["cover_pixmap"].show()
                            log.info(
                                "DETAILS_COVER: Image displayed successfully after conversion")
                        else:
                            log.error(
                                "DETAILS_COVER: Failed to get pixmap data after conversion")
                    else:
                        log.error(
                            "DETAILS_COVER: Still failed to decode after conversion: {}".format(decode_result))
        except Exception as e:
            log.error("DETAILS_COVER: Error updating cover: {}".format(e))
            import traceback
            log.error(
                "DETAILS_COVER: Traceback: {}".format(
                    traceback.format_exc()))

    def _load_ostv_cover(self, url):
        self._ostv_cover_ready = False
        self._ostv_cover_success = False
        self._ostv_cover_timer.start(100, False)
        threading.Thread(
            target=self._load_ostv_cover_async, args=(
                url,), daemon=True).start()

    def _load_ostv_cover_async(self, url):
        try:
            log.info(
                "OSTV_DETAILS_COVER: Starting download from {}".format(url))
            from .onlineserietv import load_olstv_cookie
            import urllib.request

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
                'Referer': 'https://onlineserietv.com/',
            }

            cookie = load_olstv_cookie()
            if cookie:
                headers['Cookie'] = cookie
                log.info("OSTV_DETAILS_COVER: Using cookie for authentication")

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                log.info(
                    "OSTV_DETAILS_COVER: Response status: {}".format(
                        response.getcode()))

                # Read the content
                content = response.read()

                # Verify it's a valid image
                if not self._is_valid_image(content):
                    log.error(
                        "OSTV_DETAILS_COVER: Downloaded content is not a valid image")
                    return

                # Convert WebP to JPEG if needed
                if content.startswith(b'RIFF') and b'WEBP' in content[:12]:
                    log.info("OSTV_DETAILS_COVER: Converting WebP to JPEG")
                    content = self._convert_webp_to_jpeg(content)
                    if not content:
                        log.error("OSTV_DETAILS_COVER: Failed to convert WebP")
                        return

                with open(self.cover_temp_path, 'wb') as f:
                    f.write(content)

            log.info(
                "OSTV_DETAILS_COVER: Image saved to {}".format(
                    self.cover_temp_path))
            self._ostv_cover_success = True

        except Exception as e:
            log.error("OSTV_DETAILS_COVER: Error downloading: {}".format(e))
        finally:
            self._ostv_cover_ready = True

    def _update_ostv_cover(self):
        if self._closed:
            self._ostv_cover_timer.stop()
            return
        if not self._ostv_cover_ready:
            return
        self._ostv_cover_timer.stop()
        self._ostv_cover_ready = False
        if not self._ostv_cover_success:
            return
        try:
            log.info("OSTV_DETAILS_COVER: Updating UI with downloaded image")

            # Verify file exists and is valid
            if not os.path.exists(self.cover_temp_path):
                log.error("OSTV_DETAILS_COVER: Image file does not exist")
                return

            # Check file size
            file_size = os.path.getsize(self.cover_temp_path)
            if file_size < 1024:  # Less than 1KB likely not an image
                log.error(
                    "OSTV_DETAILS_COVER: Image file too small: {} bytes".format(file_size))
                return

            if self.picload is None:
                from enigma import ePicLoad
                self.picload = ePicLoad()

            self.picload.setPara([300, 450, 1, 1, False, 1, "#00000000"])
            decode_result = self.picload.startDecode(
                self.cover_temp_path, 0, 0, False)

            if decode_result == 0:
                ptr = self.picload.getData()
                if ptr:
                    self["cover_pixmap"].instance.setPixmap(ptr)
                    self["cover_pixmap"].show()
                    log.info("OSTV_DETAILS_COVER: Image displayed successfully")
                else:
                    log.error("OSTV_DETAILS_COVER: Failed to get pixmap data")
            else:
                log.error(
                    "OSTV_DETAILS_COVER: Failed to decode image, result: {}".format(decode_result))
                # Try to read file content for debug
                try:
                    with open(self.cover_temp_path, 'rb') as f:
                        header = f.read(20)
                        log.error(
                            "OSTV_DETAILS_COVER: File header: {}".format(header))
                except Exception:
                    pass

        except Exception as e:
            log.error("OSTV_DETAILS_COVER: Error updating UI: {}".format(e))

    def _get_content_description(self):
        """Get content description from TMDB if available."""
        try:
            tmdb_id = self.details.get("tmdb_id")
            if not tmdb_id:
                return None

            from .TmdbFetcher import TmdbFetcher
            from .scsearch import load_api_key

            api_key = load_api_key()
            if not api_key:
                return None

            tmdb = TmdbFetcher(api_key)
            media_type = "movie" if self.details.get(
                "type") == "Movie" else "tv"
            details = tmdb.get_details(tmdb_id, media_type)

            if details:
                description = details.get('descrizione', '')
                # Limit description for EPG (max 200 characters)
                if len(description) > 200:
                    description = description[:197] + "..."
                return description

        except Exception as e:
            log.error("Error getting content description: {}".format(e))

        return None

    def _set_service_info(self, service_ref, name, description):
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
            log.error("Error setting service info: {}".format(e))
            # Fallback: use only the name
            service_ref.setName(name)

    def _is_valid_image(self, content):
        """Check if the content is a valid image."""
        try:
            if len(content) < 10:
                return False

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

            # Check if it's HTML (common error)
            content_str = content[:200].decode(
                'utf-8', errors='ignore').lower()
            if '<html' in content_str or '<!doctype' in content_str:
                log.error("OSTV_DETAILS_COVER: Received HTML instead of image")
                return False

            return False

        except Exception as e:
            log.error(
                "OSTV_DETAILS_COVER: Error validating image: {}".format(e))
            return False

    def _convert_webp_to_jpeg(self, webp_data):
        """Convert WebP to JPEG using ffmpeg if available."""
        try:
            import subprocess
            import tempfile

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

                log.info("OSTV_DETAILS_COVER: WebP converted to JPEG successfully")
                return jpeg_data

            except (subprocess.CalledProcessError, FileNotFoundError):
                log.warning(
                    "OSTV_DETAILS_COVER: ffmpeg not available, trying alternative")

                # Fallback: save as is and hope Enigma2 handles it
                os.unlink(webp_path)
                return webp_data

        except Exception as e:
            log.error(
                "OSTV_DETAILS_COVER: Error converting WebP: {}".format(e))
            return webp_data

    def _try_convert_to_jpeg_pil(self, image_path):
        """Try to convert an image to JPEG using PIL/Pillow."""
        try:
            from PIL import Image
            log.info(
                "DETAILS_COVER_CONVERT: Trying PIL conversion for {}".format(image_path))

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
            log.info("DETAILS_COVER_CONVERT: PIL conversion successful")
            return True

        except ImportError:
            log.warning("DETAILS_COVER_CONVERT: PIL/Pillow not available")
            return False
        except Exception as e:
            log.error(
                "DETAILS_COVER_CONVERT: PIL conversion failed: {}".format(e))
            return False

    def close(self):
        self._closed = True
        for timer in (
            self.ui_timer,
            self._tmdb_info_timer,
            self._tmdb_sc_timer,
            self._cover_timer,
            self._ostv_cover_timer,
        ):
            try:
                timer.stop()
            except Exception:
                pass
        Screen.close(self)
