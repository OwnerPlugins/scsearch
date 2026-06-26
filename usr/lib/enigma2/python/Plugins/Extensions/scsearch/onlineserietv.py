# -*- coding: utf-8 -*-

import urllib.parse
import re
import os
import requests
from .logger import get_logger

log = get_logger()


def load_olstv_cookie():
    """Load the OLSTV cookie from config.txt."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config.txt')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('CookieOLSTV='):
                    return line.strip().split('=', 1)[1].strip()
    except Exception as e:
        log.error(f"Error loading OLSTV cookie: {e}")
    return None


class OnlineSerieTV:
    def __init__(self):
        self.base_url = "https://onlineserietv.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
            "DNT": "1",
            "Origin": "https://onlineserietv.com",
            "Referer": "https://onlineserietv.com"
        })

        # Load and set the cookie from config.txt
        cookie = load_olstv_cookie()
        if cookie:
            self.session.headers['Cookie'] = cookie
            log.info("OLSTV: Cookie loaded from config and added to headers.")
        else:
            log.warning(
                "OLSTV: Cookie not found in config, requests may fail.")

    def _make_request(self, url, retries=3, delay=5):
        """
        Perform a GET request, handling Cloudflare 5-second challenge.
        """
        import time
        for i in range(retries):
            try:
                log.info(f"OLSTV: Attempt {i + 1}/{retries} for URL: {url}")
                resp = self.session.get(url, timeout=20)

                if resp.status_code == 503 and "cf-browser-verification" in resp.text:
                    log.warning(
                        f"OLSTV: Cloudflare challenge detected. Waiting {delay} seconds...")
                    time.sleep(delay)
                    continue  # Retry

                resp.raise_for_status()
                log.info(
                    "OLSTV: Request successful with status {}".format(
                        resp.status_code))
                return resp.text

            except requests.exceptions.RequestException as e:
                log.error(f"OLSTV: Attempt {i + 1} failed: {e}")
                time.sleep(2)

        log.error(f"OLSTV: Unable to access {url} after {retries} attempts.")
        return None

    def search_series(self, query):
        """Search for TV series on onlineserietv."""
        log.info("### ONLINESERIETV SEARCH START ###")
        log.info(f"ONLINESERIETV: Query received: '{query}'")
        log.info(f"ONLINESERIETV: Headers used: {dict(self.session.headers)}")

        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"{self.base_url}/?s={encoded_query}"

        html = self._make_request(search_url)
        if html:
            log.info(f"OLSTV: HTML received - Length: {len(html)}")
            results = self._parse_search_results(html)
            log.info(f"ONLINESERIETV: Found {len(results)} results.")
            log.info("### ONLINESERIETV SEARCH END ###")
            return results

        log.error("### ONLINESERIETV SEARCH FAILED ###")
        return []

    def _parse_search_results(self, html):
        """Extract search results from HTML."""
        results = []

        try:
            log.info("ONLINESERIETV: Starting HTML parsing...")
            log.info(f"ONLINESERIETV: First 500 chars of HTML: {html[:500]}")

            # Find all movie elements directly in the HTML
            movie_pattern = r'<div class="movie">.*?<img src="([^"]+)".*?<a href="([^"]+)">.*?<h2>([^<]+)</h2>.*?</div>'
            movie_matches = re.findall(movie_pattern, html, re.DOTALL)
            log.info("ONLINESERIETV: Found {} results".format(len(movie_matches)))

            for i, (poster, url, title) in enumerate(movie_matches):
                try:
                    log.info(
                        f"ONLINESERIETV: Element {
                            i + 1} - Title: '{title}', URL: {url}")

                    # Filter only TV series
                    if '/serietv/' in url:
                        slug = url.split(
                            '/')[-2] if url.endswith('/') else url.split('/')[-1]
                        result = {
                            'name': title.strip(),
                            'title': title.strip(),
                            'slug': slug,
                            'url': url,
                            'poster': poster,
                            'source': 'onlineserietv'
                        }
                        results.append(result)
                        log.info(f"ONLINESERIETV: TV series added: '{title}'")
                    else:
                        log.info(
                            f"ONLINESERIETV: '{title}' is a movie, skipped")

                except Exception as e:
                    log.error(
                        f"ONLINESERIETV: Error parsing element {
                            i + 1}: {e}")

        except Exception as e:
            log.error(f"ONLINESERIETV: General parsing error: {e}")

        return results

    def get_series_details(self, url, title):
        """Get series details by parsing JSON-LD and season/episode info."""
        try:
            log.info("### ONLINESERIETV DETAILS START ###")
            log.info(f"ONLINESERIETV: Requesting details for URL: {url}")
            log.info(f"ONLINESERIETV: Title: {title}")

            html = self._make_request(url)
            if html:
                log.info(
                    f"ONLINESERIETV: Details HTML received - Length: {len(html)}")
                details = self._parse_series_details(html, url, title)
                log.info(f"ONLINESERIETV: Details extracted: {details}")
                log.info("### ONLINESERIETV DETAILS END ###")
                return details

        except Exception as e:
            log.error(
                f"ONLINESERIETV: Error extracting details from {url}: {e}")
            log.error("### ONLINESERIETV DETAILS FAILED ###")
            return None

    def _parse_series_details(self, html, url, title):
        """Parse series details from JSON-LD and season/episode information."""
        try:
            import json

            # Extract JSON-LD
            json_ld_match = re.search(
                r'<script type="application/ld\+json"[^>]*>\s*({.*?})\s*</script>',
                html,
                re.DOTALL)
            if not json_ld_match:
                log.warning("ONLINESERIETV: JSON-LD not found")
                return None

            try:
                json_data = json.loads(json_ld_match.group(1))
            except json.JSONDecodeError as je:
                log.error(f"ONLINESERIETV: Failed to parse JSON-LD: {je}")
                return None

            log.info(f"ONLINESERIETV: JSON-LD parsed: {json_data}")

            # Extract base info
            series_title = json_data.get('name', title)
            description = json_data.get('description', '')

            # Robust poster extraction
            poster = json_data.get('image')
            if not poster:
                # Look for <img> inside <div class="imgs">
                img_match = re.search(
                    r'<div class="imgs.*?<img[^>]+src="([^"]+)"', html, re.DOTALL)
                if img_match:
                    poster = img_match.group(1)
            if not poster:
                # Look for background-image in <div class="cover">
                bg_match = re.search(
                    r'<div class="cover"[^>]+style="background-image: url\(([^)]+)\);"', html)
                if bg_match:
                    poster = bg_match.group(1)

            # Extract rating
            rating = ''
            if 'aggregateRating' in json_data:
                rating_value = json_data['aggregateRating'].get(
                    'ratingValue', '')
                if rating_value:
                    rating = f"{rating_value}/10"

            # Extract actors
            actors = []
            if 'actor' in json_data:
                for actor in json_data['actor']:
                    if isinstance(actor, dict) and 'name' in actor:
                        actors.append(actor['name'])

            # Extract creator
            creator = ''
            if 'author' in json_data and isinstance(json_data['author'], dict):
                creator = json_data['author'].get('name', '')

            # Extract season/episode info
            seasons_info = self._extract_seasons_info(html)

            # Extract base streaming URL
            stream_base_url = self._extract_stream_base_url(html)

            details = {
                'type': 'TvSeries',
                'title': series_title,
                'description': description,
                'poster': poster,
                'rating': rating,
                'actors': actors,
                'creator': creator,
                'seasons_info': seasons_info,
                'stream_base_url': stream_base_url,
                'source': 'onlineserietv',
                'url': url
            }

            log.info(f"ONLINESERIETV: Details extracted: {details}")
            return details

        except Exception as e:
            log.error(f"ONLINESERIETV: Error parsing series details: {e}")
            return None

    def _extract_seasons_info(self, html):
        """Extract season and episode information."""
        try:
            # Dictionary to convert words to numbers
            word_to_num = {
                'una': 1,
                'un': 1,
                'due': 2,
                'tre': 3,
                'quattro': 4,
                'cinque': 5,
                'sei': 6,
                'sette': 7,
                'otto': 8,
                'nove': 9,
                'dieci': 10}
            word_pattern = '|'.join(word_to_num.keys())

            # Pattern captures both digits (\d+) and words for seasons and
            # episodes
            pattern = (
                r'La serie è composta da <b>((\d+)|' + word_pattern + r') stagion[ei]</b>'
                r' e <b>((\d+)|' + word_pattern + r') episodi?</b>')
            seasons_match = re.search(pattern, html, re.IGNORECASE)

            if seasons_match:
                season_str = seasons_match.group(1).lower()
                episode_str = seasons_match.group(3).lower()

                # Convert season number
                if season_str.isdigit():
                    total_seasons = int(season_str)
                else:
                    total_seasons = word_to_num.get(season_str, 1)

                # Convert episode number
                if episode_str.isdigit():
                    total_episodes = int(episode_str)
                else:
                    total_episodes = word_to_num.get(episode_str, 1)

                log.info(
                    f"ONLINESERIETV: Found {total_seasons} seasons and {total_episodes} episodes")

                return {
                    'total_seasons': total_seasons,
                    'total_episodes': total_episodes
                }

            log.warning(
                "ONLINESERIETV: Season/episode info not found with main pattern.")
            return None

        except Exception as e:
            log.error(f"ONLINESERIETV: Error extracting season info: {e}")
            return None

    def _extract_stream_base_url(self, html):
        """Extract the base streaming URL from the iframe pattern."""
        try:
            # Look for: <iframe
            # src='https://onlineserietv.com/streaming-serie-tv/80153/1/0/'
            iframe_match = re.search(
                r'<iframe[^>]*src=[\'"]([^\'"]*\/streaming-serie-tv\/[^/]+\/)[^\'"]*\/[^\'"]*\/[\'"]',
                html)
            if iframe_match:
                base_url = iframe_match.group(1)
                log.info(
                    f"ONLINESERIETV: Streaming base URL found: {base_url}")
                return base_url

            log.warning("ONLINESERIETV: Streaming base URL not found")
            return None

        except Exception as e:
            log.error(f"ONLINESERIETV: Error extracting base URL: {e}")
            return None

    def get_maxstream_url(
            self,
            series_main_url,
            season,
            episode,
            session,
            callback):
        """Extract MaxStream URL for a specific season/episode from the main series page."""
        try:
            log.info("### ONLINESERIETV MAXSTREAM START ###")
            log.info(
                f"ONLINESERIETV: Requesting MaxStream for {series_main_url} S{season}E{episode}")

            html = self._make_request(series_main_url)
            if html:
                log.info(
                    f"ONLINESERIETV: Series HTML received - Length: {len(html)}")
                maxstream_url = self._extract_maxstream_for_episode(
                    html, season, episode)
            else:
                maxstream_url = None

            if maxstream_url:
                log.info(
                    f"ONLINESERIETV: MaxStream URL found: {maxstream_url}")

                # Use maxstream_extractor to resolve the URL
                try:
                    from scsearch.extractors.maxstream_extractor import MaxStreamExtractor
                    extractor = MaxStreamExtractor()
                except Exception as ie:
                    log.error(
                        f"ONLINESERIETV: Error importing maxstream_extractor: {ie}")
                    return None

                log.info("ONLINESERIETV: Resolving MaxStream with extractor...")
                # The extractor will handle the captcha and call the callback
                # with the final URL
                extractor.bypass_uprot(maxstream_url, session, callback)
            else:
                log.error("ONLINESERIETV: MaxStream URL not found")
                log.error("### ONLINESERIETV MAXSTREAM FAILED ###")
                if callback:
                    callback(None)

        except Exception as e:
            log.error(f"ONLINESERIETV: Error extracting MaxStream: {e}")
            log.error("### ONLINESERIETV MAXSTREAM FAILED ###")
            if callback:
                callback(None)

    def _extract_maxstream_for_episode(self, html, season, episode):
        """Extract MaxStream URL for a specific episode, isolating the correct season block."""
        try:
            log.info(
                f"ONLINESERIETV: Looking for MaxStream for S{
                    season:02d}E{
                    episode:02d}...")

            # 1. Isolate the HTML block for the correct season
            season_start_pattern = re.compile(
                rf"<b>Stagione\s+{season}\s*-", re.IGNORECASE)
            season_start_match = season_start_pattern.search(html)

            if not season_start_match:
                log.error(f"ONLINESERIETV: Season {season} header not found.")
                return None

            # Define search area: from the found season onwards
            search_area = html[season_start_match.start():]

            # Find the start of the next season to delimit the block
            next_season_start_pattern = re.compile(
                rf"<b>Stagione\s+{season + 1}\s*-", re.IGNORECASE)
            next_season_match = next_season_start_pattern.search(search_area)

            season_block = search_area
            if next_season_match:
                season_block = search_area[:next_season_match.start()]

            log.info(
                f"ONLINESERIETV: HTML block for Season {season} isolated.")

            # 2. Look for the specific episode row within the season block
            episode_marker = f"{season:02d}x{episode:02d}"

            pattern = re.compile(
                re.escape(episode_marker) +
                r".*?" +
                r"<a\s+href='([^']+)'" +
                r"[^>]*?title='[^']*Max[^>]*>.*?MaxStream",
                re.IGNORECASE | re.DOTALL
            )

            match = pattern.search(season_block)
            if match:
                url = match.group(1)
                log.info(
                    f"ONLINESERIETV: MaxStream URL successfully extracted: {url}")
                return url

            log.error(
                f"ONLINESERIETV: MaxStream link for episode {episode_marker} not found in Season {season} block.")
            return None

        except Exception as e:
            log.error(
                f"ONLINESERIETV: Error extracting MaxStream for episode: {e}")
            return None


def search_onlineserietv(query):
    """Search function for TV series on OnlineSerieTV."""
    try:
        log.info("### ONLINESERIETV FUNCTION START ###")
        log.info(
            f"ONLINESERIETV: Calling search function with query: '{query}'")

        ostv = OnlineSerieTV()
        log.info("ONLINESERIETV: OnlineSerieTV instance created")

        results = ostv.search_series(query)
        log.info(
            f"ONLINESERIETV: Function completed - Results: {len(results)}")
        log.info("### ONLINESERIETV FUNCTION END ###")

        return results
    except Exception as e:
        log.error(f"ONLINESERIETV: ERROR in search function: {e}")
        log.error("### ONLINESERIETV FUNCTION FAILED ###")
        return []


def get_onlineserietv_details(url, title):
    """Get details of an OnlineSerieTV series including TMDB_ID."""
    try:
        log.info("### ONLINESERIETV GET_DETAILS START ###")
        ostv = OnlineSerieTV()
        details = ostv.get_series_details(url, title)
        log.info("### ONLINESERIETV GET_DETAILS END ###")
        return details
    except Exception as e:
        log.error(f"ONLINESERIETV: Error in get_details: {e}")
        log.error("### ONLINESERIETV GET_DETAILS FAILED ###")
        return None


def get_onlineserietv_stream_url(
        series_url,
        season,
        episode,
        session,
        callback):
    """Get resolved M3U8 URL for a specific episode with captcha support."""
    try:
        log.info("### ONLINESERIETV STREAM_URL START ###")
        log.info(
            f"ONLINESERIETV: Requesting stream for {series_url} S{season}E{episode}")

        ostv = OnlineSerieTV()
        ostv.get_maxstream_url(series_url, season, episode, session, callback)
    except Exception as e:
        log.error(f"ONLINESERIETV: Error in get_stream_url: {e}")
        log.error("### ONLINESERIETV STREAM_URL FAILED ###")
