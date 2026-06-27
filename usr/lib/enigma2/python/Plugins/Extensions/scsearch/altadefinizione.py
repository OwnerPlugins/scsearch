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
        Fetch a page with automatic decompression if needed.
        """
        log.debug("Altadefinizione: Fetching URL: {}".format(url))
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=30)

                # Check if response is compressed
                content_encoding = response.headers.get('Content-Encoding', '').lower()
                content = response.content

                if 'gzip' in content_encoding:
                    try:
                        import gzip
                        import io
                        with gzip.GzipFile(fileobj=io.BytesIO(content), mode='rb') as f:
                            html = f.read().decode('utf-8')
                            log.info("Altadefinizione: Decompressed gzip, {} chars".format(len(html)))
                    except Exception as e:
                        log.warning("Altadefinizione: Gzip decompression failed: {}, using raw content".format(e))
                        html = response.text
                else:
                    # Not compressed - use directly
                    html = response.text
                    log.info("Altadefinizione: Response not compressed, {} chars".format(len(html)))

                if html:
                    self._save_cookies()
                    return html

            except Exception as e:
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

    def _extract_poster_from_page(self, html):
        """Extract poster URL from Altadefinizione page."""
        poster = ''
        patterns = [
            r'<img[^>]+class="[^"]*poster[^"]*"[^>]+src="([^"]+)"',
            r'<meta property="og:image"[^>]+content="([^"]+)"',
            r'<div[^>]*class="[^"]*poster[^"]*"[^>]*>.*?<img[^>]+src="([^"]+)"',
            r'<img[^>]+src="(/img/w200/[^"]+)"[^>]*alt="[^"]*"'
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                poster = match.group(1)
                if poster and not poster.startswith('http'):
                    poster = self.base_film + poster
                break
        return poster

    def _extract_tmdb_id_from_page(self, html, url=''):
        """Extract TMDB ID from page HTML."""
        patterns = [
            r'var\s+tmdbID\s*=\s*["\']?(\d+)["\']?',
            r'tmdb_id["\']?\s*[:=]\s*["\']?(\d+)["\']?',
            r'data-tmdb-id=["\'](\d+)["\']',
            r'/movie/(\d+)',
            r'/tv/(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1)
        if url:
            match = re.search(r'/(?:film|tv)-[^/]+-(\d+)/', url)
            if match:
                return match.group(1)
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
                log.warning("Altadefinizione: No HTML received")
                return []

            # Save HTML for debug
            try:
                with open('/tmp/altadef_html_decompressed.txt', 'w', encoding='utf-8') as f:
                    f.write(html[:15000])
                log.info("Altadefinizione: HTML saved to /tmp/altadef_html_decompressed.txt")
            except:
                pass

            results = self._parse_search_results(html, 'movie')
            log.info("Altadefinizione: Found {} movies.".format(len(results)))
            return results

        except Exception as e:
            log.error("Altadefinizione: Error searching movies: {}".format(e))
            return []

    def _parse_search_results(self, html, media_type='movie'):
        """
        Parse search results from Altadefinizione HTML.
        Returns list of dictionaries with title, url, rating, poster, type.
        """
        results = []
        if not html:
            log.warning("Altadefinizione: HTML is empty")
            return results

        # Save HTML for inspection
        try:
            with open('/tmp/altadef_html_debug.txt', 'w', encoding='utf-8') as f:
                f.write(html[:15000])
            log.info("Altadefinizione: HTML saved to /tmp/altadef_html_debug.txt (first 15000 chars)")
        except Exception as e:
            log.error("Altadefinizione: Error saving HTML: {}".format(e))

        # Pattern based on current HTML structure
        pattern = r'<a\s+href="(/detail/[^"]+)"\s+class="movie-card">.*?<h6\s+class="movie-card-title">(.*?)</h6>'
        matches = re.findall(pattern, html, re.DOTALL)

        log.info("Altadefinizione: Found {} raw links".format(len(matches)))

        # Log first 3 matches for debugging
        if matches:
            for i, (url, title) in enumerate(matches[:3]):
                log.info("Altadefinizione: Match {} - URL: {}, Title: {}".format(i + 1, url, title.strip()))
        else:
            log.warning("Altadefinizione: No matches found with pattern")
            # Try simpler pattern
            fallback_pattern = r'href="(/detail/[^"]+)"'
            fallback_matches = re.findall(fallback_pattern, html)
            log.info("Altadefinizione: Fallback found {} links".format(len(fallback_matches)))
            if fallback_matches:
                for i, url in enumerate(fallback_matches[:5]):
                    log.info("Altadefinizione: Fallback link {}: {}".format(i + 1, url))

        for url, title in matches:
            title = self.clean_html(title)
            if not title:
                continue

            is_tv = '/tv-' in url or '/detail/tv-' in url

            if media_type == 'movie' and is_tv:
                continue
            if media_type == 'tv' and not is_tv:
                continue

            # Extract rating
            rating = 'N/A'
            poster = ''
            card_pattern = r'<a\s+href="' + re.escape(url) + r'"[^>]*>.*?</a>'
            card_match = re.search(card_pattern, html, re.DOTALL)
            if card_match:
                rating_match = re.search(r'<span class="label rate">([\d.]+)</span>', card_match.group(0))
                if rating_match:
                    rating = rating_match.group(1)
                img_match = re.search(r'<img[^>]+src="([^"]+)"', card_match.group(0))
                if img_match:
                    poster = img_match.group(1)
                    if poster and not poster.startswith('http'):
                        poster = self.base_film + poster

            results.append({
                'title': title,
                'url': self.base_film + url,
                'rating': rating,
                'poster': poster,
                'source': 'altadefinizione',
                'type': 'tv' if is_tv else 'movie',
                'raw': {
                    'url': self.base_film + url,
                    'poster': poster,
                    'source': 'altadefinizione',
                    'type': 'tv' if is_tv else 'movie'
                }
            })

        log.info("Altadefinizione: Parsed {} results".format(len(results)))
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
            tmdb_id = self._extract_tmdb_id_from_page(html, page_url)
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
            details['poster'] = self._extract_poster_from_page(html)

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
        """Extract streaming links from the movie page."""
        if not self.base_film:
            log.error("Altadefinizione: Cannot get streaming links, base URL not configured")
            return []

        try:
            log.info("Altadefinizione: Extracting streaming links from {}".format(movie_url))
            html = self._get_page(movie_url)
            if not html:
                return []

            # find iframe VixSrc
            iframe_match = re.search(r'<iframe[^>]+src="([^"]*vixsrc[^"]+)"', html, re.IGNORECASE)
            if iframe_match:
                embed_url = iframe_match.group(1)
                if not embed_url.startswith('http'):
                    embed_url = 'https:' + embed_url if embed_url.startswith('//') else 'https://' + embed_url
                log.info("Altadefinizione: Found embed URL: {}".format(embed_url))

                stream_url = self._extract_vixsrc_stream(embed_url, movie_url)
                if stream_url:
                    return [{
                        'url': stream_url,
                        'quality': 'HD',
                        'service': 'vixsrc'
                    }]

            # find direct URL
            direct_patterns = [
                r'(https?://[^\s"\']+\.vix-content\.net[^\s"\']+\.m3u8[^\s"\']*)',
            ]
            for pattern in direct_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    stream_url = match.group(1)
                    if stream_url:
                        return [{
                            'url': stream_url,
                            'quality': 'HD',
                            'service': 'vixsrc'
                        }]

            log.warning("Altadefinizione: No stream URL found")
            return []

        except Exception as e:
            log.error("Altadefinizione: Error extracting streaming links: {}".format(e))
            return []

    def _extract_vixsrc_stream(self, embed_url, referer):
        """Extract master M3U8 URL from VixSrc page."""
        try:
            log.info("Altadefinizione: Extracting stream from {}".format(embed_url))

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Referer': referer,
            }

            response = self.session.get(embed_url, headers=headers, timeout=15, allow_redirects=True)
            response.raise_for_status()

            # --- DECOMPRESS ---
            content = response.content
            content_encoding = response.headers.get('Content-Encoding', '').lower()
            html = None

            if 'gzip' in content_encoding:
                try:
                    import gzip
                    import io
                    with gzip.GzipFile(fileobj=io.BytesIO(content), mode='rb') as f:
                        html = f.read().decode('utf-8')
                    log.info("Altadefinizione: Decompressed gzip, {} chars".format(len(html)))
                except Exception as e:
                    log.warning("Gzip decompression failed: {}, using raw content".format(e))
                    html = response.text
            elif 'br' in content_encoding:
                try:
                    import brotli
                    html = brotli.decompress(content).decode('utf-8')
                    log.info("Altadefinizione: Decompressed brotli, {} chars".format(len(html)))
                except:
                    log.warning("Brotli not available, using raw content")
                    html = response.text
            else:
                html = response.text
                log.info("Altadefinizione: Response not compressed, {} chars".format(len(html)))

            if not html:
                log.warning("Altadefinizione: No HTML after decompression")
                return None

            # save HTML decompressed
            try:
                with open('/tmp/vixsrc_decompressed.html', 'w', encoding='utf-8') as f:
                    f.write(html)
                log.info("Altadefinizione: Decompressed HTML saved to /tmp/vixsrc_decompressed.html")
            except:
                pass

            # --- PATTERN MASTER PLAYLIST ---
            # 1. find /playlist/ token ed expires
            pattern_playlist = r'(https?://[^\s"\']+/playlist/\d+\?token=[^\s"\']+&expires=\d+[^\s"\']*)'
            matches = re.findall(pattern_playlist, html, re.IGNORECASE)
            if matches:
                stream_url = matches[0]
                log.info("Altadefinizione: Found master playlist: {}".format(stream_url))
                return stream_url

            # 2. find oggept JSON
            json_patterns = [
                r'"url"\s*:\s*"([^"]+/playlist/[^"]+)"',
                r'"file"\s*:\s*"([^"]+/playlist/[^"]+)"',
                r'"masterPlaylist"\s*:\s*"([^"]+)"',
            ]
            for pattern in json_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    stream_url = matches[0]
                    if stream_url.startswith('//'):
                        stream_url = 'https:' + stream_url
                    if not stream_url.startswith('http'):
                        stream_url = 'https://vixsrc.to' + stream_url
                    log.info("Altadefinizione: Found master playlist in JSON: {}".format(stream_url))
                    return stream_url

            # 3. find JavaScript variable
            js_patterns = [
                r'masterPlaylist\s*=\s*["\']([^"\']+)["\']',
                r'playlistUrl\s*=\s*["\']([^"\']+)["\']',
                r'window\.masterPlaylist[^;]+url[^:]+:\s*["\']([^"\']+)["\']',
            ]
            for pattern in js_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    stream_url = match.group(1)
                    if stream_url.startswith('//'):
                        stream_url = 'https:' + stream_url
                    if not stream_url.startswith('http'):
                        stream_url = 'https://vixsrc.to' + stream_url
                    log.info("Altadefinizione: Found master playlist in JS: {}".format(stream_url))
                    return stream_url

            # 4. find iframe nested
            iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"', html, re.IGNORECASE)
            if iframe_match:
                new_url = iframe_match.group(1)
                if not new_url.startswith('http'):
                    new_url = 'https:' + new_url if new_url.startswith('//') else 'https://' + new_url
                log.info("Altadefinizione: Found nested iframe: {}".format(new_url))
                return self._extract_vixsrc_stream(new_url, embed_url)

            log.warning("Altadefinizione: No stream URL found.")
            log.warning("Altadefinizione: First 1000 chars of decompressed HTML:")
            log.warning(html[:1000])
            return None

        except Exception as e:
            log.error("Altadefinizione: Error extracting VixSrc stream: {}".format(e))
            import traceback
            log.error(traceback.format_exc())
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
