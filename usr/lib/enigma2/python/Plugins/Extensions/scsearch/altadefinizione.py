# -*- coding: utf-8 -*-
#
# Altadefinizione module for SC Search
# Updated: 27.06.2026
#

import urllib.parse
import html as html_module
import re
import requests
import os
import time

try:
    from .logger import get_logger
    log = get_logger()
except ImportError:
    import logging
    log = logging.getLogger(__name__)


def _read_altadefinizione_urls():
    """Read Altadefinizione URLs from config.txt"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.txt')
    url = ''
    fallback = ''
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('ALTADEFINIZIONE_URL='):
                    url = line.split('=', 1)[1].strip().rstrip('/')
                elif line.startswith('ALTADEFINIZIONE_URL_FALLBACK='):
                    fallback = line.split('=', 1)[1].strip().rstrip('/')
    except Exception:
        pass
    return url, fallback


class Altadefinizione:
    def __init__(self):
        """
        Initialize the client for the Altadefinizione website.
        """
        base_url, fallback_url = _read_altadefinizione_urls()

        # Check if URL is configured
        if not base_url or base_url == 'https://':
            log.error("Altadefinizione: URL not configured in config.txt")
            self.base_film = ''
            self.base_serie = ''
            self.base_fallback = ''
        else:
            self.base_film = base_url
            self.base_serie = base_url + '/serietv'
            self.base_fallback = fallback_url

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

        # Cookie file for persistence (helps with Cloudflare)
        self.cookie_file = '/tmp/altadefinizione.cookie'
        self._load_cookies()

        log.info("Altadefinizione: Client initialized.")

    def _load_cookies(self):
        """Load cookies from file if exists."""
        try:
            if os.path.exists(self.cookie_file):
                import pickle
                with open(self.cookie_file, 'rb') as f:
                    cookies = pickle.load(f)
                    self.session.cookies.update(cookies)
                log.info("Altadefinizione: Cookies loaded from file.")
        except Exception as e:
            log.debug("Altadefinizione: Could not load cookies: {}".format(e))

    def _save_cookies(self):
        """Save cookies to file."""
        try:
            import pickle
            with open(self.cookie_file, 'wb') as f:
                pickle.dump(self.session.cookies, f)
            log.debug("Altadefinizione: Cookies saved to file.")
        except Exception as e:
            log.debug("Altadefinizione: Could not save cookies: {}".format(e))

    def _get_page(self, url, retries=3, delay=5):
        """
        Fetch a page with Cloudflare protection handling.
        """
        log.debug("Altadefinizione: Fetching URL: {}".format(url))

        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=30)

                # Check for Cloudflare challenge
                if response.status_code == 503 and 'cf-browser-verification' in response.text:
                    log.warning("Altadefinizione: Cloudflare challenge detected. Waiting {} seconds...".format(delay))
                    time.sleep(delay)
                    continue

                response.raise_for_status()
                self._save_cookies()
                return response.text

            except requests.exceptions.RequestException as e:
                log.warning("Altadefinizione: Attempt {} failed: {}".format(attempt + 1, e))
                time.sleep(2)

        log.error("Altadefinizione: Failed to fetch {} after {} attempts".format(url, retries))
        return None

    # ---------------------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------------------
    def _is_tv_series(self, url):
        """Determine if a URL belongs to a TV series."""
        return '/tv-' in url or '/serietv/' in url or '/detail/tv-' in url

    def clean_html(self, text):
        """Remove HTML tags and entities from text."""
        if not text:
            return ''
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        return text.strip()

    def _extract_tmdb_id(self, html, url=''):
        """Extract TMDB ID from page HTML or URL."""
        # Look in page
        tmdb_match = re.search(r'var tmdbID\s*=\s*(\d+);', html, re.IGNORECASE)
        if tmdb_match:
            return tmdb_match.group(1)

        # Look in URL (pattern /film-titolo-123/ or /tv-titolo-123/)
        if url:
            id_match = re.search(r'/(?:film|tv)-[^/]+-(\d+)/', url, re.IGNORECASE)
            if id_match:
                return id_match.group(1)

        return None

    def _extract_media_type(self, html, url=''):
        """Extract media type from page."""
        # Check URL first
        if url and '/tv-' in url:
            return 'tv'
        if url and '/film-' in url:
            return 'movie'

        # Check HTML
        media_match = re.search(r'var mediaType\s*=\s*"([^"]+)"', html, re.IGNORECASE)
        if media_match:
            return media_match.group(1)

        # Check title or description
        if 'serie tv' in html.lower() or 'stagione' in html.lower():
            return 'tv'

        return 'movie'

    # ---------------------------------------------------------------------
    # Search methods
    # ---------------------------------------------------------------------
    def search_movies(self, query):
        """
        Search for movies on Altadefinizione.
        """
        if not self.base_film:
            log.error("Altadefinizione: Cannot search, base URL not configured")
            return []

        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = "{}/search?q={}".format(self.base_film, encoded_query)
            log.info("Altadefinizione: Movie search URL: {}".format(search_url))

            html = self._get_page(search_url)
            if not html:
                return []

            results = self._parse_search_results(html, 'movie')
            log.info("Altadefinizione: Found {} movies.".format(len(results)))
            return results

        except Exception as e:
            log.error("Altadefinizione: Error searching movies: {}".format(e))
            return []

    def search_series(self, query):
        """
        Search for TV series on Altadefinizione.
        """
        if not self.base_film:
            log.error("Altadefinizione: Cannot search, base URL not configured")
            return []

        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = "{}/search?q={}".format(self.base_film, encoded_query)
            log.info("Altadefinizione: TV series search URL: {}".format(search_url))

            html = self._get_page(search_url)
            if not html:
                return []

            results = self._parse_search_results(html, 'tv')
            log.info("Altadefinizione: Found {} TV series.".format(len(results)))
            return results

        except Exception as e:
            log.error("Altadefinizione: Error searching TV series: {}".format(e))
            return []

    def _parse_search_results(self, html, media_type='movie'):
        """Parse search results from HTML."""
        results = []

        # Pattern for movie/TV cards
        card_pattern = r'<a href="([^"]+)" class="movie-card">.*?<img[^>]+src="([^"]+)"[^>]*alt="([^"]+)".*?<h6 class="movie-card-title">([^<]+)</h6>'
        matches = re.findall(card_pattern, html, re.DOTALL)

        for match in matches:
            url, img_src, alt_title, h6_title = match
            title = alt_title if alt_title else h6_title

            if not url or not title:
                continue

            # Determine type from URL
            is_tv = '/tv-' in url or '/serietv/' in url

            # Filter by requested type
            if media_type == 'movie' and is_tv:
                continue
            if media_type == 'tv' and not is_tv:
                continue

            # Extract TMDB ID from URL
            tmdb_id = None
            id_match = re.search(r'/(?:film|tv)-[^/]+-(\d+)/', url)
            if id_match:
                tmdb_id = id_match.group(1)

            results.append({
                'url': url,
                'poster': img_src,
                'title': title,
                'tmdb_id': tmdb_id,
                'description': '',
                'source': 'altadefinizione'
            })

        return results

    # ---------------------------------------------------------------------
    # Series details extraction
    # ---------------------------------------------------------------------
    def get_page_details(self, page_url):
        """
        Extract details from the page (movie or TV series).
        """
        if not self.base_film:
            log.error("Altadefinizione: Cannot get page details, base URL not configured")
            return None

        try:
            log.info("Altadefinizione: Loading page: {}".format(page_url))
            html = self._get_page(page_url)
            if not html:
                return None

            details = {
                'title': '',
                'year': '',
                'description': '',
                'poster': '',
                'type': 'TvSeries' if self._is_tv_series(page_url) else 'Movie',
                'genre': '',
                'seasons': [],
                'streaming_links': [],
                'tmdb_id': None,
                'media_type': 'tv' if self._is_tv_series(page_url) else 'movie'
            }

            # Extract TMDB ID
            tmdb_id = self._extract_tmdb_id(html, page_url)
            if tmdb_id:
                details['tmdb_id'] = tmdb_id

            # Extract title
            title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
            if title_match:
                details['title'] = self.clean_html(title_match.group(1))
            else:
                title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html, re.IGNORECASE)
                if title_match:
                    details['title'] = self.clean_html(title_match.group(1))

            # Extract year
            year_match = re.search(r'<span class="meta-item">(\d{4})</span>', html, re.IGNORECASE)
            if year_match:
                details['year'] = year_match.group(1)

            # Extract description
            desc_match = re.search(r'<p class="detail-overview">([^<]+)</p>', html, re.IGNORECASE)
            if desc_match:
                details['description'] = self.clean_html(desc_match.group(1))
            if not details['description']:
                desc_match = re.search(r'<meta name="description" content="([^"]+)"', html, re.IGNORECASE)
                if desc_match:
                    details['description'] = self.clean_html(desc_match.group(1))

            # Extract poster
            poster_match = re.search(r'<img[^>]+src="([^"]+)"[^>]*class="[^"]*poster[^"]*"', html, re.IGNORECASE)
            if poster_match:
                details['poster'] = poster_match.group(1)

            # If it's a TV series, extract seasons and episodes
            if details['type'] == 'TvSeries':
                details['seasons'] = self._extract_seasons(html, page_url, tmdb_id)

            # For movies, extract streaming links
            if details['type'] == 'Movie':
                details['streaming_links'] = self.get_streaming_links(page_url)

            return details

        except Exception as e:
            log.error("Altadefinizione: Error extracting details: {}".format(e))
            return None

    def _extract_seasons(self, html, page_url, tmdb_id=None):
        """Extract seasons and episodes from TV series page."""
        seasons = []

        # If we have TMDB ID, build VixSrc URLs
        if tmdb_id:
            # Extract season numbers from dropdown or episode groups
            season_items = re.findall(r'data-season="(\d+)"', html, re.IGNORECASE)

            if not season_items:
                season_items = re.findall(r'<span[^>]*data-season="(\d+)"[^>]*>Stagione\s*\d+</span>', html, re.IGNORECASE)

            if not season_items:
                # Try to find seasons from episode groups
                season_items = re.findall(r'data-group-season="(\d+)"', html, re.IGNORECASE)

            unique_seasons = sorted(set(season_items))

            for season_num in unique_seasons:
                season_num = int(season_num)
                episodes = []

                # Extract episodes for this season
                episode_pattern = r'data-episode="{}-(\d+)"'.format(season_num)
                ep_matches = re.findall(episode_pattern, html)

                if ep_matches:
                    episodes = sorted(set([int(e) for e in ep_matches]))
                else:
                    # Fallback: estimate episodes
                    ep_count_match = re.search(r'Stagione\s+{}\s*\((?:[^)]*\s+)?(\d+)\s+episodi?\)'.format(season_num), html, re.IGNORECASE)
                    if ep_count_match:
                        episodes = list(range(1, int(ep_count_match.group(1)) + 1))

                if episodes:
                    seasons.append({
                        'season_number': season_num,
                        'episodes': [
                            {
                                'episode_number': ep_num,
                                'name': 'Episodio {}'.format(ep_num),
                                'url': 'https://vixsrc.to/tv/{}/{}/{}?lang=it'.format(tmdb_id, season_num, ep_num)
                            }
                            for ep_num in episodes
                        ]
                    })

        # If no TMDB ID or no seasons found, try HTML parsing
        if not seasons:
            # Try to find episode links
            ep_links = re.findall(r'<a[^>]+href="([^"]*vixsrc[^"]*tv[^"]+)"[^>]*>.*?Stagione\s+(\d+)\s*[x×:]\s*Episodio\s+(\d+)', html, re.IGNORECASE)
            if ep_links:
                season_dict = {}
                for link, season_str, episode_str in ep_links:
                    season = int(season_str)
                    episode = int(episode_str)
                    if season not in season_dict:
                        season_dict[season] = []
                    season_dict[season].append({
                        'episode_number': episode,
                        'name': 'Episodio {}'.format(episode),
                        'url': link
                    })

                for season_num, eps in season_dict.items():
                    seasons.append({
                        'season_number': season_num,
                        'episodes': sorted(eps, key=lambda x: x['episode_number'])
                    })

        return seasons

    # ---------------------------------------------------------------------
    # Streaming links extraction (for movies)
    # ---------------------------------------------------------------------
    def get_streaming_links(self, movie_url):
        """
        Extract streaming links from the movie page.
        """
        if not self.base_film:
            log.error("Altadefinizione: Cannot get streaming links, base URL not configured")
            return []

        try:
            log.info("Altadefinizione: Extracting streaming links from {}".format(movie_url))
            html = self._get_page(movie_url)
            if not html:
                return []

            # Get TMDB ID
            tmdb_id = self._extract_tmdb_id(html, movie_url)
            if not tmdb_id:
                log.warning("Altadefinizione: No TMDB ID found for movie")
                return []

            # Build VixSrc URL
            embed_url = "https://vixsrc.to/movie/{}?lang=it".format(tmdb_id)
            stream_url = self._extract_vixsrc_stream(embed_url, movie_url)

            if stream_url:
                return [{
                    'url': stream_url,
                    'quality': 'HD' if '1080' in stream_url else 'SD',
                    'service': 'vixsrc'
                }]

            log.warning("Altadefinizione: No stream URL found")
            return []

        except Exception as e:
            log.error("Altadefinizione: Error extracting streaming links: {}".format(e))
            return []

    def _extract_vixsrc_stream(self, embed_url, referer):
        """Extract M3U8 URL from VixSrc page."""
        try:
            log.info("Altadefinizione: Extracting stream from {}".format(embed_url))

            headers = {
                'User-Agent': self.session.headers['User-Agent'],
                'Referer': referer,
                'Origin': 'https://vixsrc.to',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }

            response = self.session.get(embed_url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.text

            # Patterns for M3U8 URL
            patterns = [
                r'(https?://[^\s"\']+\.m3u8[^\s"\']*)',
                r'file\s*:\s*["\']([^"\']+\.m3u8[^"\']*)',
                r'src\s*:\s*["\']([^"\']+\.m3u8[^"\']*)',
                r'url\s*:\s*["\']([^"\']+\.m3u8[^"\']*)',
                r'"file"\s*:\s*"([^"]+\.m3u8[^"]*)"',
                r'"url"\s*:\s*"([^"]+\.m3u8[^"]*)"',
                r'(https?://[^\s]+vix-content\.net[^\s]+\.m3u8[^\s]*)',
                r'(https?://[^\s]+\.vix-content\.net[^\s]+)',
            ]

            for pattern in patterns:
                matches = re.findall(pattern, data, re.IGNORECASE)
                if matches:
                    stream_url = matches[0].strip()
                    if stream_url.startswith('//'):
                        stream_url = 'https:' + stream_url
                    log.info("Altadefinizione: Stream URL found: {}".format(stream_url))
                    return stream_url

            return None

        except Exception as e:
            log.error("Altadefinizione: Error extracting VixSrc stream: {}".format(e))
            return None

    # ---------------------------------------------------------------------
    # Episode stream (for TV series)
    # ---------------------------------------------------------------------
    def get_episode_stream(self, series_url, season, episode):
        """
        Get streaming link for a specific episode of a series.
        """
        if not self.base_film:
            log.error("Altadefinizione: Cannot get episode stream, base URL not configured")
            return None

        try:
            log.info("Altadefinizione: Getting episode stream for S{}E{}".format(season, episode))

            # If we already have a VixSrc URL in the details, use it
            details = self.get_page_details(series_url)
            if details and details.get('tmdb_id'):
                tmdb_id = details['tmdb_id']
                embed_url = "https://vixsrc.to/tv/{}/{}/{}?lang=it".format(tmdb_id, season, episode)
                stream_url = self._extract_vixsrc_stream(embed_url, series_url)

                if stream_url:
                    return {
                        'url': stream_url,
                        'quality': 'HD' if '1080' in stream_url else 'SD',
                        'service': 'vixsrc'
                    }

            # Fallback: try to extract from page
            html = self._get_page(series_url)
            if html:
                # Look for episode link
                pattern = r'data-episode="{}-{}"'.format(season, episode)
                if re.search(pattern, html):
                    tmdb_id = self._extract_tmdb_id(html, series_url)
                    if tmdb_id:
                        embed_url = "https://vixsrc.to/tv/{}/{}/{}?lang=it".format(tmdb_id, season, episode)
                        stream_url = self._extract_vixsrc_stream(embed_url, series_url)
                        if stream_url:
                            return {
                                'url': stream_url,
                                'quality': 'HD' if '1080' in stream_url else 'SD',
                                'service': 'vixsrc'
                            }

            log.warning("Altadefinizione: No stream found for S{}E{}".format(season, episode))
            return None

        except Exception as e:
            log.error("Altadefinizione: Error getting episode stream: {}".format(e))
            return None
