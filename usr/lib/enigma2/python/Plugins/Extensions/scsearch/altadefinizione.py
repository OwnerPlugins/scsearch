# -*- coding: utf-8 -*-
#
# Altadefinizione module for SC Search
# Structure identical to cb01.py
# Uses only requests, no e2iplayer dependencies
#

import urllib.parse
import html as html_module
import re
import requests
import os

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
        return '/tv-' in url or '/serietv/' in url

    def clean_html(self, text):
        """Remove HTML tags and entities from text"""
        if not text:
            return ''
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        return text.strip()

    # ---------------------------------------------------------------------
    # Search methods (same interface as cb01)
    # ---------------------------------------------------------------------
    def search_movies(self, query):
        """
        Search for movies on Altadefinizione.
        Uses URL /?s= and parses results.
        """
        if not self.base_film:
            log.error("Altadefinizione: Cannot search, base URL not configured")
            return []

        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"{self.base_film}/?s={encoded_query}"
            log.info(f"Altadefinizione: Movie search URL: {search_url}")

            response = self.session.get(
                search_url, timeout=15, allow_redirects=True)
            response.raise_for_status()
            html = response.text

            # Pattern for movie cards (based on working e2iplayer code)
            # Looks for <div class="movie"> with <a href="...">, <img>, <h2>
            movie_pattern = re.compile(
                r'<div class="movie">\s*'
                r'<a href="([^"]+)"[^>]*>.*?'
                r'<img[^>]+src="([^"]+)"[^>]+alt="([^"]+)"[^>]*>.*?'
                r'<h2[^>]*>([^<]+)</h2>',
                re.IGNORECASE | re.DOTALL
            )

            matches = movie_pattern.findall(html)

            # Fallback: more generic pattern
            if not matches:
                movie_pattern = re.compile(
                    r'<a href="([^"]+)"[^>]*>.*?'
                    r'<img[^>]+src="([^"]+)"[^>]+alt="([^"]+)"[^>]*>.*?'
                    r'<h[2-3][^>]*>([^<]+)</h[2-3]>',
                    re.IGNORECASE | re.DOTALL
                )
                matches = movie_pattern.findall(html)

            log.info("Altadefinizione: Found {} results from pattern".format(len(matches)))

            results = []
            for match in matches:
                if len(match) == 4:
                    url, img_src, alt, title = match
                else:
                    url, img_src, title = match[0], match[1], match[2]

                title = self.clean_html(title)
                if not title:
                    continue

                # Skip if it's a TV series (when searching for movies)
                if self._is_tv_series(url):
                    log.info(f"Altadefinizione: Skipped TV series: {title}")
                    continue

                results.append({
                    'url': url,
                    'poster': img_src,
                    'title': title,
                    'description': '',
                    'source': 'altadefinizione'
                })
                log.info(f"Altadefinizione: Movie found: {title}")

            log.info(f"Altadefinizione: Found {len(results)} movies.")
            return results

        except Exception as e:
            log.error(f"Altadefinizione: Error searching movies: {e}")
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
            search_url = f"{self.base_film}/?s={encoded_query}"
            log.info(f"Altadefinizione: TV series search URL: {search_url}")

            response = self.session.get(
                search_url, timeout=15, allow_redirects=True)
            response.raise_for_status()
            html = response.text

            # Same card pattern
            movie_pattern = re.compile(
                r'<div class="movie">\s*'
                r'<a href="([^"]+)"[^>]*>.*?'
                r'<img[^>]+src="([^"]+)"[^>]+alt="([^"]+)"[^>]*>.*?'
                r'<h2[^>]*>([^<]+)</h2>',
                re.IGNORECASE | re.DOTALL
            )

            matches = movie_pattern.findall(html)
            if not matches:
                movie_pattern = re.compile(
                    r'<a href="([^"]+)"[^>]*>.*?'
                    r'<img[^>]+src="([^"]+)"[^>]+alt="([^"]+)"[^>]*>.*?'
                    r'<h[2-3][^>]*>([^<]+)</h[2-3]>',
                    re.IGNORECASE | re.DOTALL
                )
                matches = movie_pattern.findall(html)

            log.info(f"Altadefinizione: Found {len(matches)} total results")

            results = []
            for match in matches:
                if len(match) == 4:
                    url, img_src, alt, title = match
                else:
                    url, img_src, title = match[0], match[1], match[2]

                title = self.clean_html(title)
                if not title:
                    continue

                # Keep only TV series
                if not self._is_tv_series(url):
                    log.info(f"Altadefinizione: Skipped movie: {title}")
                    continue

                results.append({
                    'url': url,
                    'poster': img_src,
                    'title': title,
                    'description': '',
                    'source': 'altadefinizione'
                })
                log.info(f"Altadefinizione: TV series found: {title}")

            log.info(f"Altadefinizione: Found {len(results)} TV series.")
            return results

        except Exception as e:
            log.error(f"Altadefinizione: Error searching TV series: {e}")
            return []

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
        """Extract the VixSrc embed URL from the movie/series page"""
        if not self.base_film:
            log.error(
                "Altadefinizione: Cannot get embed, base URL not configured")
            return None

        try:
            log.info(f"Altadefinizione: Extracting embed from {page_url}")
            response = self.session.get(page_url, timeout=15)
            response.raise_for_status()
            html = response.text

            # Look for iframe with vixsrc
            iframe_match = re.search(
                r'<iframe[^>]+src="([^"]*vixsrc[^"]+)"', html, re.IGNORECASE)
            if iframe_match:
                return iframe_match.group(1)

            # Look for TMDB ID and construct URL
            tmdb_id = self._extract_tmdb_id(html, page_url)

            if tmdb_id:
                if self._is_tv_series(page_url):
                    return f"https://vixsrc.to/tv/{tmdb_id}/1/1?lang=it"
                else:
                    return f"https://vixsrc.to/movie/{tmdb_id}?lang=it"

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

            stream_url = self._extract_vixsrc_stream(embed_url, movie_url)
            if not stream_url:
                log.warning("Altadefinizione: No stream URL found")
                return []

            quality = 'HD' if '1080' in stream_url else 'SD'
            return [{'url': stream_url, 'quality': quality, 'service': 'vixsrc'}]

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

            # Extract title
            title_match = re.search(
                r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
            if title_match:
                details['title'] = self.clean_html(title_match.group(1))
            else:
                title_match = re.search(
                    r'<meta property="og:title" content="([^"]+)"', html, re.IGNORECASE)
                if title_match:
                    details['title'] = self.clean_html(title_match.group(1))

            # Extract year
            year_match = re.search(
                r'<span class="meta-item">(\d{4})</span>',
                html,
                re.IGNORECASE)
            if year_match:
                details['year'] = year_match.group(1)

            # Extract description
            desc_match = re.search(
                r'<p class="detail-overview">([^<]+)</p>',
                html,
                re.IGNORECASE)
            if desc_match:
                details['description'] = self.clean_html(desc_match.group(1))

            # Extract poster
            poster_match = re.search(
                r'<img[^>]+src="([^"]+)"[^>]*class="[^"]*poster[^"]*"',
                html,
                re.IGNORECASE)
            if poster_match:
                details['poster'] = poster_match.group(1)

            # For movies, extract streaming links
            if details['type'] == 'Movie':
                details['streaming_links'] = self.get_streaming_links(page_url)

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

            tmdb_id = self._extract_tmdb_id(html, series_url)
            if not tmdb_id:
                log.error("Altadefinizione: Could not find TMDB ID for series")
                return None

            embed_url = f"https://vixsrc.to/tv/{tmdb_id}/{season}/{episode}?lang=it"
            stream_url = self._extract_vixsrc_stream(embed_url, series_url)

            if stream_url:
                return {
                    'url': stream_url,
                    'quality': 'HD' if '1080' in stream_url else 'SD',
                    'service': 'vixsrc'
                }
            return None

        except Exception as e:
            log.error(f"Altadefinizione: Error extracting episode: {e}")
            return None
