# -*- coding: utf-8 -*-
#
# Altadefinizione module for SC Search
# Complete version - extracts search results AND streaming links
# Structure identical to cb01.py
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

        if not base_url or base_url == 'https://':
            log.error("Altadefinizione: URL not configured in config.txt")
            self.base_url = ''
            self.base_fallback = ''
        else:
            self.base_url = base_url
            self.base_fallback = fallback_url

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        })

        # Cookie file for Cloudflare
        self.cookie_file = '/tmp/altadefinizione.cookie'
        self._load_cookies()

        log.info("Altadefinizione: Client initialized.")

    def _load_cookies(self):
        """Load cookies from file."""
        try:
            if os.path.exists(self.cookie_file):
                import pickle
                with open(self.cookie_file, 'rb') as f:
                    cookies = pickle.load(f)
                    self.session.cookies.update(cookies)
        except Exception:
            pass

    def _save_cookies(self):
        """Save cookies to file."""
        try:
            import pickle
            with open(self.cookie_file, 'wb') as f:
                pickle.dump(self.session.cookies, f)
        except Exception:
            pass

    def _get_page(self, url, retries=3):
        """Fetch a page with Cloudflare handling."""
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=30)

                if response.status_code == 503 and 'cf-browser-verification' in response.text:
                    log.warning("Altadefinizione: Cloudflare detected, waiting...")
                    time.sleep(5)
                    continue

                if 'Just a moment' in response.text:
                    log.warning("Altadefinizione: Cloudflare challenge, waiting...")
                    time.sleep(5)
                    continue

                response.raise_for_status()
                self._save_cookies()
                return response.text

            except Exception as e:
                log.warning("Altadefinizione: Attempt {} failed: {}".format(attempt + 1, e))
                time.sleep(2)

        log.error("Altadefinizione: Failed to fetch {}".format(url))
        return None

    def _clean_html(self, text):
        """Remove HTML tags and entities."""
        if not text:
            return ''
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        return text.strip()

    def _is_tv_series(self, url):
        """Check if URL is a TV series."""
        return '/tv-' in url or '/serietv/' in url

    def _extract_tmdb_id(self, html, url=''):
        """Extract TMDB ID from page or URL."""
        tmdb_match = re.search(r'var tmdbID\s*=\s*(\d+);', html, re.IGNORECASE)
        if tmdb_match:
            return tmdb_match.group(1)

        if url:
            id_match = re.search(r'/(?:film|tv)-[^/]+-(\d+)/', url, re.IGNORECASE)
            if id_match:
                return id_match.group(1)

        return None

    # ---------------------------------------------------------------------
    # SEARCH METHODS
    # ---------------------------------------------------------------------
    def search_movies(self, query):
        """Search for movies."""
        if not self.base_url:
            return []

        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = "{}/search?q={}".format(self.base_url, encoded_query)
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
        """Search for TV series."""
        if not self.base_url:
            return []

        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = "{}/search?q={}".format(self.base_url, encoded_query)
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

        card_pattern = r'<a href="([^"]+)" class="movie-card">.*?<img[^>]+src="([^"]+)"[^>]*alt="([^"]+)".*?<h6 class="movie-card-title">([^<]+)</h6>'
        matches = re.findall(card_pattern, html, re.DOTALL)

        if not matches:
            card_pattern = r'<a href="([^"]+)"[^>]*>.*?<img[^>]+src="([^"]+)"[^>]*alt="([^"]+)".*?<h[2-6][^>]*>([^<]+)</h[2-6]>'
            matches = re.findall(card_pattern, html, re.DOTALL)

        for match in matches:
            url, img_src, alt_title, h6_title = match
            title = alt_title if alt_title else h6_title

            if not url or not title:
                continue

            title = self._clean_html(title)
            is_tv = self._is_tv_series(url)

            if media_type == 'movie' and is_tv:
                continue
            if media_type == 'tv' and not is_tv:
                continue

            if url.startswith('/'):
                url = self.base_url + url
            if img_src.startswith('/'):
                img_src = self.base_url + img_src

            results.append({
                'url': url,
                'poster': img_src,
                'title': title,
                'description': '',
                'source': 'altadefinizione'
            })

        return results

    # ---------------------------------------------------------------------
    # DETAILS & STREAMING LINKS (like CB01)
    # ---------------------------------------------------------------------
    def get_page_details(self, page_url):
        """
        Extract details from page (movie or TV series).
        Returns: title, year, description, poster, type, seasons, streaming_links
        """
        if not self.base_url:
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
                'streaming_links': []
            }

            # Extract TMDB ID
            tmdb_id = self._extract_tmdb_id(html, page_url)
            if tmdb_id:
                details['tmdb_id'] = tmdb_id

            # Extract title
            title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
            if title_match:
                details['title'] = self._clean_html(title_match.group(1))
            else:
                title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html, re.IGNORECASE)
                if title_match:
                    details['title'] = self._clean_html(title_match.group(1))

            # Extract year
            year_match = re.search(r'<span class="meta-item">(\d{4})</span>', html, re.IGNORECASE)
            if year_match:
                details['year'] = year_match.group(1)

            # Extract description
            desc_match = re.search(r'<p class="detail-overview">([^<]+)</p>', html, re.IGNORECASE)
            if desc_match:
                details['description'] = self._clean_html(desc_match.group(1))

            # Extract poster
            poster_match = re.search(r'<img[^>]+src="([^"]+)"[^>]*class="[^"]*poster[^"]*"', html, re.IGNORECASE)
            if poster_match:
                details['poster'] = poster_match.group(1)

            # If TV series, extract seasons
            if details['type'] == 'TvSeries':
                details['seasons'] = self._extract_seasons(html, page_url, tmdb_id)

            # If movie, extract streaming links
            if details['type'] == 'Movie':
                details['streaming_links'] = self.get_streaming_links(page_url)

            return details

        except Exception as e:
            log.error("Altadefinizione: Error extracting details: {}".format(e))
            return None

    def _extract_seasons(self, html, page_url, tmdb_id=None):
        """Extract seasons and episodes from TV series page."""
        seasons = []

        if not tmdb_id:
            tmdb_id = self._extract_tmdb_id(html, page_url)

        if tmdb_id:
            # Extract seasons from page
            season_items = re.findall(r'data-season="(\d+)"', html, re.IGNORECASE)

            if not season_items:
                season_items = re.findall(r'<span[^>]*data-season="(\d+)"[^>]*>Stagione\s*\d+</span>', html, re.IGNORECASE)

            unique_seasons = sorted(set(season_items))

            for season_num in unique_seasons:
                season_num = int(season_num)
                episodes = []

                ep_pattern = r'data-episode="{}-(\d+)"'.format(season_num)
                ep_matches = re.findall(ep_pattern, html)

                if ep_matches:
                    episodes = sorted(set([int(e) for e in ep_matches]))
                else:
                    ep_count_match = re.search(r'Stagione\s+{}\s*\((?:[^)]*\s+)?(\d+)\s+episodi?\)'.format(season_num), html, re.IGNORECASE)
                    if ep_count_match:
                        episodes = list(range(1, int(ep_count_match.group(1)) + 1))

                if episodes:
                    season_data = {
                        'season_number': season_num,
                        'episodes': []
                    }
                    for ep_num in episodes:
                        season_data['episodes'].append({
                            'episode_number': ep_num,
                            'name': 'Episodio {}'.format(ep_num),
                            'url': 'https://vixsrc.to/tv/{}/{}/{}?lang=it'.format(tmdb_id, season_num, ep_num)
                        })
                    seasons.append(season_data)

        return seasons

    def get_streaming_links(self, movie_url):
        """
        Extract streaming links from movie page.
        Returns list of dicts with url, quality, service.
        """
        if not self.base_url:
            return []

        try:
            log.info("Altadefinizione: Extracting streaming links from {}".format(movie_url))
            html = self._get_page(movie_url)
            if not html:
                return []

            tmdb_id = self._extract_tmdb_id(html, movie_url)
            if not tmdb_id:
                log.warning("Altadefinizione: No TMDB ID found")
                return []

            embed_url = "https://vixsrc.to/movie/{}?lang=it".format(tmdb_id)
            stream_url = self._extract_vixsrc_stream(embed_url, movie_url)

            if stream_url:
                return [{
                    'url': stream_url,
                    'quality': 'HD' if '1080' in stream_url else 'SD',
                    'service': 'vixsrc'
                }]

            return []

        except Exception as e:
            log.error("Altadefinizione: Error extracting streaming links: {}".format(e))
            return []

    def get_episode_stream(self, series_url, season, episode):
        """Get stream for a specific episode."""
        if not self.base_url:
            return None

        try:
            log.info("Altadefinizione: Getting episode stream for S{}E{}".format(season, episode))

            html = self._get_page(series_url)
            if not html:
                return None

            tmdb_id = self._extract_tmdb_id(html, series_url)
            if not tmdb_id:
                return None

            embed_url = "https://vixsrc.to/tv/{}/{}/{}?lang=it".format(tmdb_id, season, episode)
            stream_url = self._extract_vixsrc_stream(embed_url, series_url)

            if stream_url:
                return {
                    'url': stream_url,
                    'quality': 'HD' if '1080' in stream_url else 'SD',
                    'service': 'vixsrc'
                }

            return None

        except Exception as e:
            log.error("Altadefinizione: Error getting episode stream: {}".format(e))
            return None

    def _extract_vixsrc_stream(self, embed_url, referer):
        """Extract M3U8 URL from VixSrc page."""
        try:
            log.info("Altadefinizione: Extracting stream from {}".format(embed_url))

            headers = {
                'User-Agent': self.session.headers['User-Agent'],
                'Referer': referer,
                'Origin': 'https://vixsrc.to'
            }

            response = self.session.get(embed_url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.text

            patterns = [
                r'(https?://[^\s"\']+\.m3u8[^\s"\']*)',
                r'file\s*:\s*["\']([^"\']+\.m3u8[^"\']*)',
                r'src\s*:\s*["\']([^"\']+\.m3u8[^"\']*)',
                r'url\s*:\s*["\']([^"\']+\.m3u8[^"\']*)',
                r'"file"\s*:\s*"([^"]+\.m3u8[^"]*)"',
                r'"url"\s*:\s*"([^"]+\.m3u8[^"]*)"',
                r'(https?://[^\s]+vix-content\.net[^\s]+\.m3u8[^\s]*)',
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
