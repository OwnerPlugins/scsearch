# -*- coding: utf-8 -*-
#
# Altadefinizione module for SC Search
# Structure identical to cb01.py
# Uses only requests, no e2iplayer dependencies
#

import urllib.parse
import html as html_module
import json
import re
import requests
import os
import time
import queue
import threading

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
    SEARCH_CONNECT_TIMEOUT = 4
    SEARCH_READ_TIMEOUT = 8
    SEARCH_TOTAL_TIMEOUT = 12
    SEARCH_MAX_BYTES = 4 * 1024 * 1024

    def __init__(self):
        """
        Initialize the client for the Altadefinizione website.
        Reads URLs from config.txt (same as CB01).
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
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        })

        log.info("Altadefinizione: Client initialized.")

    # ---------------------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------------------
    def _is_tv_series(self, url):
        """Determine if a URL belongs to a TV series"""
        return ('/tv-' in url or '/serietv/' in url or
                '/serie-tv/' in url)

    def clean_html(self, text):
        """Remove HTML tags and entities from text"""
        if not text:
            return ''
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        return text.strip()

    def _extract_series_seasons(self, html):
        """Extract normalized seasons from Next.js flight-data packets."""
        marker = '"seasons":'
        for raw_packet in re.findall(
                r'self\.__next_f\.push\((.*?)\)</script>',
                html,
                re.DOTALL):
            try:
                packet = json.loads(raw_packet)
                payload = (packet[1] if len(packet) > 1 and
                           isinstance(packet[1], str) else '')
                position = payload.find(marker)
                if position < 0:
                    continue
                seasons, _ = json.JSONDecoder().raw_decode(
                    payload, position + len(marker))
            except (TypeError, ValueError, IndexError):
                continue

            normalized = []
            for season in seasons if isinstance(seasons, list) else []:
                try:
                    season_number = int(season.get('number'))
                except (TypeError, ValueError, AttributeError):
                    continue
                episodes = []
                for episode in season.get('episodes') or []:
                    try:
                        episode_number = int(episode.get('number'))
                    except (TypeError, ValueError, AttributeError):
                        continue
                    episodes.append({
                        'episode_number': episode_number,
                        'title': episode.get('title') or
                        'Episodio {}'.format(episode_number),
                        'description': episode.get('plot') or '',
                        'poster': episode.get('still') or '',
                        'url': '',
                        'type': 'vidxgo',
                        'quality': 'HD',
                    })
                if episodes:
                    normalized.append({
                        'season_number': season_number,
                        'episodes': episodes,
                    })
            if normalized:
                return normalized

        # Lightweight fallback when Next.js changes packet serialization.
        episode_pairs = re.findall(r'data-episode="(\d+)-(\d+)"', html)
        grouped = {}
        for season_number, episode_number in episode_pairs:
            grouped.setdefault(int(season_number), set()).add(
                int(episode_number))
        return [
            {
                'season_number': season_number,
                'episodes': [
                    {
                        'episode_number': episode_number,
                        'title': 'Episodio {}'.format(episode_number),
                        'url': '',
                        'type': 'vidxgo',
                        'quality': 'HD',
                    }
                    for episode_number in sorted(grouped[season_number])
                ],
            }
            for season_number in sorted(grouped)
        ]

    # ---------------------------------------------------------------------
    # Search methods (same interface as cb01)
    # ---------------------------------------------------------------------
    def _download_search_page(self, url):
        """Download and decode one search response."""
        started = time.monotonic()
        chunks = []
        size = 0
        with self.session.get(
                url,
                timeout=(self.SEARCH_CONNECT_TIMEOUT,
                         self.SEARCH_READ_TIMEOUT),
                allow_redirects=True,
                stream=True) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if time.monotonic() - started > self.SEARCH_TOTAL_TIMEOUT:
                    raise requests.exceptions.Timeout(
                        "search exceeded {} seconds".format(
                            self.SEARCH_TOTAL_TIMEOUT))
                if not chunk:
                    continue
                chunks.append(chunk)
                size += len(chunk)
                if size > self.SEARCH_MAX_BYTES:
                    raise requests.exceptions.RequestException(
                        "search response exceeded {} bytes".format(
                            self.SEARCH_MAX_BYTES))

            content = b''.join(chunks)
            # ``apparent_encoding`` accesses response.content and cannot be
            # used reliably after a streamed body has already been consumed.
            encoding = response.encoding or 'utf-8'
            return content.decode(encoding, errors='replace')

    def _get_search_page(self, url):
        """Download a search page with a hard caller-visible time limit.

        ``requests`` timeouts only limit the time between socket reads.  A
        server sending a few bytes periodically can therefore keep a normal
        ``get`` alive for several minutes.
        """
        result_queue = queue.Queue(maxsize=1)

        def download():
            try:
                result_queue.put((True, self._download_search_page(url)))
            except Exception as error:
                result_queue.put((False, error))

        worker = threading.Thread(target=download)
        worker.daemon = True
        worker.start()
        worker.join(self.SEARCH_TOTAL_TIMEOUT)
        if worker.is_alive():
            raise requests.exceptions.Timeout(
                "search exceeded {} seconds".format(
                    self.SEARCH_TOTAL_TIMEOUT))

        success, value = result_queue.get_nowait()
        if not success:
            raise value
        return value

    def _fetch_search_html(self, base, query):
        """Fetch the current JSON archive search endpoint."""
        params = urllib.parse.urlencode({
            'offset': 0,
            'limit': 30,
            'q': query,
            'sort': 'Data di aggiornamento',
            'count': 1,
        })
        url = "{}/api/v1/web/archive?{}".format(base.rstrip('/'), params)
        try:
            log.info(f"Altadefinizione: Search URL: {url}")
            return self._get_search_page(url)
        except requests.exceptions.Timeout as e:
            log.warning(f"Altadefinizione: Search timed out for {url}: {e}")
        except Exception as e:
            log.warning(f"Altadefinizione: Search failed for {url}: {e}")
        return ''

    def _parse_matches(self, payload, base=''):
        """Extract (url, img, alt, title) tuples from API JSON or old HTML."""
        try:
            data = json.loads(payload)
            if isinstance(data, dict) and isinstance(data.get('items'), list):
                matches = []
                for item in data['items']:
                    item_id = item.get('id')
                    slug = item.get('slug')
                    title = item.get('title')
                    if not item_id or not slug or not title:
                        continue
                    category = ('serie-tv' if item.get('kind') == 'series'
                                else 'film')
                    url = "{}/{}/{}-{}-streaming.html".format(
                        base.rstrip('/'), category, item_id, slug)
                    matches.append((
                        url,
                        item.get('posterUrl') or item.get('tileUrl') or '',
                        '',
                        title,
                    ))
                return matches
        except (TypeError, ValueError):
            # Compatibility with installations still pointing to an older
            # Altadefinizione domain returning HTML.
            pass

        # Primary: data-link + img src + h2 > a title (altadefinizione.hot
        # structure)
        pattern = re.compile(
            r'<div class="movie"[^>]*data-link="([^"]+)"[^>]*>.*?'
            r'<img[^>]+src="([^"]+)"[^>]*>.*?'
            r'<h2[^>]*>\s*<a[^>]*>([^<]+)</a>',
            re.IGNORECASE | re.DOTALL
        )
        matches = [(m[0], m[1], '', m[2]) for m in pattern.findall(payload)]

        if not matches:
            # Fallback: classic <div class="movie"> with alt-filled img
            pattern = re.compile(
                r'<div class="movie">\s*<a href="([^"]+)"[^>]*>.*?'
                r'<img[^>]+src="([^"]+)"[^>]+alt="([^"]+)"[^>]*>.*?'
                r'<h2[^>]*>([^<]+)</h2>',
                re.IGNORECASE | re.DOTALL
            )
            matches = pattern.findall(payload)

        if not matches:
            # Last resort: generic a+img+heading
            pattern = re.compile(
                r'<a href="([^"]+)"[^>]*>.*?'
                r'<img[^>]+src="([^"]+)"[^>]+alt="([^"]+)"[^>]*>.*?'
                r'<h[2-3][^>]*>([^<]+)</h[2-3]>',
                re.IGNORECASE | re.DOTALL
            )
            matches = pattern.findall(payload)

        return matches

    def _search(self, query, series_only):
        """Core search logic with base_film → base_fallback fallback."""
        if not self.base_film:
            log.error("Altadefinizione: Cannot search, base URL not configured")
            return []

        results = []
        # Do not query the same host twice when main and fallback are equal.
        bases = list(dict.fromkeys(
            base.rstrip('/') for base in
            [self.base_film, self.base_fallback] if base
        ))
        for base in bases:
            payload = self._fetch_search_html(base, query)
            matches = self._parse_matches(payload, base)
            log.info(
                "Altadefinizione: %d raw results from %s",
                len(matches),
                base,
            )

            for match in matches:
                url, img_src, alt, title = match if len(
                    match) == 4 else (match[0], match[1], '', match[2])
                title = self.clean_html(title)
                if not title:
                    continue
                # resolve relative img paths
                if img_src.startswith('/'):
                    img_src = base + img_src
                is_series = self._is_tv_series(url)
                if series_only and not is_series:
                    continue
                if not series_only and is_series:
                    continue
                results.append({
                    'url': url,
                    'poster': img_src,
                    'title': title,
                    'description': '',
                    'source': 'altadefinizione'
                })

            if results:
                break

        log.info(f"Altadefinizione: Found {len(results)} results.")
        return results

    def search_movies(self, query):
        return self._search(query, series_only=False)

    def search_series(self, query):
        return self._search(query, series_only=True)

    # ---------------------------------------------------------------------
    # VixSrc resolution
    # ---------------------------------------------------------------------
    def _extract_tmdb_id(self, html, url=''):
        """Extract TMDB ID from page HTML or URL"""
        # Look in page
        tmdb_match = re.search(r'var tmdbID\s*=\s*(\d+);', html, re.IGNORECASE)
        if tmdb_match:
            return tmdb_match.group(1)

        # Look in URL (pattern /film-title-123/ or /tv-title-123/)
        if url:
            id_match = re.search(
                r'/(?:film|tv)-[^/]+-(\d+)/', url, re.IGNORECASE)
            if id_match:
                return id_match.group(1)

        return None

    def _get_embed_url(self, page_url):
        """Extract the embed URL from the movie/series page"""
        if not self.base_film:
            return None

        try:
            log.info(f"Altadefinizione: Extracting embed from {page_url}")
            response = self.session.get(page_url, timeout=15)
            response.raise_for_status()
            html = response.text

            # 1. dle-player script: 'https://v.vidxgo.co/' +
            # 'ttXXXX'.replace('tt','')
            m = re.search(
                r"getElementById\(['\"]dle-player['\"]\)\.src\s*=\s*"
                r"'([^']+)'\s*\+\s*'(tt\d+)'\.replace\('tt',\s*''\)",
                html
            )
            if m:
                return m.group(1) + m.group(2).replace('tt', '')

            # 3. iframe with vixsrc or vidxgo in src
            m = re.search(
                r'<iframe[^>]+src="(https?://[^"]*(?:vixsrc|vidxgo)[^"]+)"',
                html,
                re.IGNORECASE)
            if m:
                return m.group(1)

            # 4. any iframe src
            m = re.search(
                r'<iframe[^>]+src="(https?://[^"]+)"',
                html,
                re.IGNORECASE)
            if m:
                return m.group(1)

            # 5. TMDB ID fallback → vixsrc
            tmdb_id = self._extract_tmdb_id(html, page_url)
            if tmdb_id:
                if self._is_tv_series(page_url):
                    return f"https://vixsrc.to/tv/{tmdb_id}/1/1?lang=it"
                return f"https://vixsrc.to/movie/{tmdb_id}?lang=it"

            log.warning("Altadefinizione: No embed URL found")
            return None

        except Exception as e:
            log.error(f"Altadefinizione: Error extracting embed: {e}")
            return None

    def _extract_vixsrc_stream(self, embed_url, referer):
        """Extract M3U8 URL from VixSrc page"""
        try:
            log.info(f"Altadefinizione: Extracting stream from {embed_url}")

            headers = dict(self.session.headers)
            headers['Referer'] = referer
            headers['Origin'] = 'https://vixsrc.to'

            response = self.session.get(embed_url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.text

            # Patterns to find M3U8 URL
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
                    log.info(
                        f"Altadefinizione: Stream URL found: {stream_url}")
                    return stream_url

            log.warning("Altadefinizione: No stream URL found")
            return None

        except Exception as e:
            log.error(f"Altadefinizione: Error extracting stream: {e}")
            return None

    # ---------------------------------------------------------------------
    # Streaming links extraction (for movies)
    # ---------------------------------------------------------------------
    # known embed domains that can be sent directly to the player
    _DIRECT_DOMAINS = (
        'vidxgo.co',
        'vixsrc.to',
        'vidhide.com',
        'streamtape.com')

    def get_streaming_links(self, movie_url):
        """
        Extract streaming links from the movie page.
        Returns a list of dicts with: url, quality, service
        """
        if not self.base_film:
            log.error(
                "Altadefinizione: Cannot get streaming links, base URL not configured")
            return []

        try:
            log.info(
                f"Altadefinizione: Extracting streaming links from {movie_url}")

            embed_url = self._get_embed_url(movie_url)
            if not embed_url:
                log.warning("Altadefinizione: No embed URL found")
                return []

            # If the embed is a known player domain, use it directly
            if any(d in embed_url for d in self._DIRECT_DOMAINS):
                log.info(
                    f"Altadefinizione: Using embed URL directly: {embed_url}")
                service = next(
                    (d.split('.')[0] for d in self._DIRECT_DOMAINS if d in embed_url),
                    'embed')
                return [{'url': embed_url, 'quality': 'HD',
                         'service': service, 'type': service}]

            stream_url = self._extract_vixsrc_stream(embed_url, movie_url)
            if not stream_url:
                log.warning("Altadefinizione: No stream URL found")
                return []

            quality = 'HD' if '1080' in stream_url else 'SD'
            return [{'url': stream_url, 'quality': quality,
                     'service': 'vixsrc', 'type': 'vixsrc'}]

        except Exception as e:
            log.error(
                f"Altadefinizione: Error extracting streaming links: {e}")
            return []

    # ---------------------------------------------------------------------
    # Full details extraction (for movies and series)
    # ---------------------------------------------------------------------
    def get_page_details(self, page_url):
        """
        Extract details from the page (movie or TV series).
        """
        if not self.base_film:
            log.error(
                "Altadefinizione: Cannot get page details, base URL not configured")
            return None

        try:
            log.info(f"Altadefinizione: Loading page: {page_url}")
            response = self.session.get(page_url, timeout=15)
            response.raise_for_status()
            html = response.text

            details = {
                'title': '',
                'year': '',
                'description': '',
                'poster': '',
                'type': 'TvSeries' if self._is_tv_series(page_url) else 'Movie',
                'genre': '',
                'seasons': [],
                'streaming_links': []}

            # Title: og:title or h1
            m = re.search(
                r'<meta property="og:title" content="([^"]+)"',
                html,
                re.IGNORECASE)
            if not m:
                m = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
            if m:
                details['title'] = self.clean_html(m.group(1))

            # Year: label "Anno:" followed by the value div
            m = re.search(
                r'Anno:\s*</div>\s*<div[^>]*>\s*(\d{4})\s*</div>',
                html, re.IGNORECASE | re.DOTALL)
            if m:
                details['year'] = m.group(1).strip()

            # Genre: links inside the Genere row
            m = re.search(
                r'Genere:\s*</div>\s*<div[^>]*>(.*?)</div>',
                html, re.IGNORECASE | re.DOTALL)
            if m:
                details['genre'] = ', '.join(
                    re.findall(r'>([^<]+)</a>', m.group(1)))

            # Description: movie_entry-plot block
            m = re.search(
                r'<div class="movie_entry-plot">(.*?)</div>',
                html, re.IGNORECASE | re.DOTALL)
            if m:
                details['description'] = self.clean_html(m.group(1))

            # Poster: og:image
            m = re.search(
                r'<meta property="og:image" content="([^"]+)"',
                html,
                re.IGNORECASE)
            if m:
                details['poster'] = m.group(1)

            # Streaming links for movies
            if details['type'] == 'Movie':
                details['streaming_links'] = self.get_streaming_links(page_url)
            else:
                details['seasons'] = self._extract_series_seasons(html)
                log.info(
                    "Altadefinizione: Found %d seasons and %d episodes",
                    len(details['seasons']),
                    sum(len(season['episodes'])
                        for season in details['seasons']))

            return details

        except Exception as e:
            log.error(f"Altadefinizione: Error extracting details: {e}")
            return None

    def get_episode_stream(self, series_url, season, episode):
        """
        Get streaming link for a specific episode of a series.
        """
        if not self.base_film:
            log.error(
                "Altadefinizione: Cannot get episode stream, base URL not configured")
            return None

        try:
            response = self.session.get(series_url, timeout=15)
            response.raise_for_status()
            html = response.text

            # The current site exposes its numeric VidXGo token in the player
            # iframe (for example /3514324/1/1?se=0).
            token_match = re.search(
                r'https?://v\.vidxgo\.co/(\d+)(?:/\d+/\d+)?',
                html,
                re.IGNORECASE)
            if token_match:
                embed_url = "https://v.vidxgo.co/{}/{}/{}?se=0".format(
                    token_match.group(1), season, episode)
                log.info(
                    f"Altadefinizione: Episode embed URL: {embed_url}")
                return {
                    'url': embed_url,
                    'quality': 'HD',
                    'service': 'vidxgo',
                    'type': 'vidxgo'}

            tmdb_id = self._extract_tmdb_id(html, series_url)
            if not tmdb_id:
                log.error("Altadefinizione: Could not find TMDB ID for series")
                return None

            embed_url = f"https://vixsrc.to/tv/{tmdb_id}/{season}/{episode}?lang=it"
            log.info(f"Altadefinizione: Episode embed URL: {embed_url}")
            return {
                'url': embed_url,
                'quality': 'HD',
                'service': 'vixsrc',
                'type': 'vixsrc'}

        except Exception as e:
            log.error(f"Altadefinizione: Error extracting episode: {e}")
            return None
