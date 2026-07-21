# -*- coding: utf-8 -*-
"""
Robust API for StreamingCommunity with resilient parsing.
"""
import json
import re
import os
import requests
import html
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .logger import get_logger
from .cb01 import CB01
from .altadefinizione import Altadefinizione

log = get_logger()
REQ_TIMEOUT = 15


def read_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.txt')
    config = {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return config


CONFIG = read_config()


def normalize_domain(value):
    domain = (
        value or '').strip().replace(
        'https://',
        '').replace(
            'http://',
        '').strip('/')
    return domain or 'streamingcommunity.bingo'


DEFAULT_DOMAIN = normalize_domain(CONFIG.get('STREAMING_COMMUNITY_URL'))


class SCAPIError(Exception):
    pass


class WebPageTimeOutError(SCAPIError):
    pass


class WebPageStatusCodeError(SCAPIError):
    pass


class MatchNotFound(SCAPIError):
    pass


class API:
    def __init__(self, domain):
        self.domain = domain
        self.session = requests.Session()
        user_agent = CONFIG.get(
            'USER_AGENT',
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.session.headers.update({"User-Agent": user_agent})
        log.info("API initialized for domain: {}".format(domain))

    def _wbpage_as_text(self, url):
        log.debug("Fetching URL: {}".format(url))
        try:
            response = self.session.get(url, timeout=REQ_TIMEOUT)
            response.raise_for_status()
            return response.text
        except requests.exceptions.Timeout:
            log.error("Timeout fetching URL: {}".format(url))
            raise WebPageTimeOutError(url)
        except requests.exceptions.RequestException as e:
            log.error("Error fetching URL: {} - {}".format(url, e))
            raise WebPageStatusCodeError("Request failed: {}".format(e))

    def search(self, query):
        """Search using TMDB HTML parsing"""
        import urllib.parse

        encoded_query = urllib.parse.quote(query)
        url = "https://www.themoviedb.org/search?query={}".format(
            encoded_query)
        log.info("TMDB API.search: Searching on {}".format(url))

        try:
            response = self.session.get(url, timeout=REQ_TIMEOUT)
            response.raise_for_status()
            html_content = response.text

            log.info(
                "TMDB API.search: HTML length: {}".format(
                    len(html_content)))

            results = []

            # Pattern to extract cards
            card_pattern = r'<div[^>]*class="card v4 tight"[^>]*>.*?</div>\s*</div>\s*</div>'
            cards = re.findall(card_pattern, html_content, re.DOTALL)

            log.info("TMDB API.search: Found {} cards".format(len(cards)))

            for card in cards:
                try:
                    # Extract href and data-media-type
                    href_match = re.search(
                        r'href="/(movie|tv)/(\d+)-([^"]+)"', card)
                    if not href_match:
                        continue

                    media_type = href_match.group(1)  # 'movie' or 'tv'
                    item_id = href_match.group(2)
                    slug = href_match.group(3)

                    # Extract title
                    title_match = re.search(
                        r'<h2>([^<]+?)(?:\s*<span[^>]*>.*?</span>)?</h2>', card)
                    if not title_match:
                        continue
                    title = title_match.group(1).strip()

                    # Extract release date
                    date_match = re.search(
                        r'<span class="release_date">([^<]+)</span>', card)
                    release_date = ''
                    if date_match:
                        date_str = date_match.group(1).strip()
                        # Convert format "28 settembre, 1989" to "1989-09-28"
                        # (simplified)
                        date_parts = date_str.split(', ')
                        if len(date_parts) == 2:
                            year = date_parts[1]
                            release_date = "{}-01-01".format(year)

                    results.append({
                        'id': item_id,
                        'slug': slug,
                        'name': title,
                        'type': media_type,
                        'release_date': release_date if media_type == 'movie' else '',
                        'first_air_date': release_date if media_type == 'tv' else ''
                    })

                    log.info(
                        "TMDB API.search: Parsed - ID: {}, Title: {}, Type: {}".format(
                            item_id, title, media_type))

                except Exception as e:
                    log.error(
                        "TMDB API.search: Error parsing card: {}".format(e))
                    continue

            log.info(
                "TMDB API.search: Successfully parsed {} results".format(
                    len(results)))
            return {'data': results}

        except Exception as e:
            log.error("TMDB API.search: Error - {}".format(e))
            import traceback
            log.error(
                "TMDB API.search: Traceback: {}".format(
                    traceback.format_exc()))
            return {'data': []}

    def load(self, content_slug):
        url = "https://{}/it/titles/{}".format(self.domain, content_slug)
        log.info("API.load: Loading URL: {}".format(url))
        data = None
        try:
            html_content = self._wbpage_as_text(url)
            json_patterns = [
                r'window\.__NUXT__\s*=\s*({.+?});',
                r'data-page=([\'"])(.*?)\1',
            ]
            for pattern in json_patterns:
                match = re.search(pattern, html_content, re.DOTALL)
                if match:
                    log.info(
                        "API.load: Found potential JSON with pattern: {}...".format(pattern[:30]))
                    try:
                        group_index = 2 if 'data-page' in pattern else 1
                        json_str_raw = match.group(group_index)
                        json_str = html.unescape(
                            json_str_raw) if 'data-page' in pattern else json_str_raw

                        parsed_json = json.loads(json_str)

                        props = parsed_json.get('props', {})
                        title_data_check = props.get('title', {})
                        if title_data_check.get(
                                'type') == 'tv' and not title_data_check.get('seasons'):
                            log.warning(
                                "API.load: JSON from pattern '{}' is incomplete. Trying next pattern.".format(pattern[:30]))
                            continue

                        data = parsed_json
                        log.info(
                            "API.load: Successfully parsed complete JSON data.")
                        break
                    except (json.JSONDecodeError, IndexError, Exception) as e:
                        log.debug("API.load: Failed to parse JSON from pattern '{}': {}".format(
                            pattern[:30], e))
                        continue
        except Exception as e:
            log.error("API.load: Error parsing {}: {}".format(url, e))
            data = None

        if not data:
            log.error(
                "API.load: Unable to find or parse JSON data-page in {}".format(url))
            return None

        props = data.get("props", {})
        title_data = props.get("title", {})

        media_type = "Movie" if title_data.get(
            "type") == "movie" else "TvSeries"
        name = title_data.get("name")
        vix_url = props.get("vix_url")
        log.info("API.load: Vix URL found: {}".format(vix_url))

        episode_list = []
        if media_type == "TvSeries" and title_data.get("seasons"):
            for se in title_data.get("seasons"):
                season_number = int(se.get("number", 0))
                for ep in se.get("episodes", []):
                    episode_id = ep.get("id")
                    if not episode_id:
                        continue
                    episode = {
                        "name": ep.get("name"),
                        "season": season_number,
                        "episode": int(ep.get("number", 0)),
                        "id": episode_id,
                        "url": "https://{}/it/watch/{}/{}".format(
                            self.domain, content_slug, episode_id)
                    }
                    episode_list.append(episode)

        return {
            "name": name,
            "id": title_data.get("id"),
            "type": media_type,
            "tmdb_id": title_data.get("tmdb_id"),
            "vix_url": vix_url,
            "episodeList": episode_list if episode_list else None,
        }

    def get_links(self, vixsrc_url, tmdb_id, tv=None):
        try:
            base_url = "https://vixsrc.to"
            if vixsrc_url and '://' in vixsrc_url:
                match = re.match(r'(https?://[^/]+)', vixsrc_url)
                if match:
                    base_url = match.group(1)

            media_path = "tv/{}/{}/{}".format(
                tmdb_id, tv[0], tv[1]) if tv else "movie/{}".format(tmdb_id)
            api_url = "{}/api/{}".format(base_url, media_path)
            log.info("GET_LINKS: Fetching VixSrc API: {}".format(api_url))

            response = self.session.get(api_url, timeout=REQ_TIMEOUT)
            response.raise_for_status()
            embed_path = response.json().get('src')
            if not embed_path:
                log.error("GET_LINKS: Embed URL not found in API response")
                return None

            embed_url = urljoin(base_url, embed_path)
            headers = {'Referer': base_url + '/'}
            response = self.session.get(
                embed_url, headers=headers, timeout=REQ_TIMEOUT)
            response.raise_for_status()
            embed_page = response.text

            playlist_match = re.search(
                r"window\.masterPlaylist\s*=.*?url:\s*['\"]([^'\"]+)",
                embed_page, re.DOTALL)
            token_match = re.search(
                r"['\"]token['\"]\s*:\s*['\"]([^'\"]+)", embed_page)
            expires_match = re.search(
                r"['\"]expires['\"]\s*:\s*['\"]([^'\"]+)", embed_page)
            fhd_match = re.search(
                r"window\.canPlayFHD\s*=\s*(true|false)", embed_page)

            if not playlist_match or not token_match or not expires_match:
                log.error(
                    "GET_LINKS: Playlist parameters not found in embed page")
                return None

            separator = '&' if '?' in playlist_match.group(1) else '?'
            stream_url = "{}{}expires={}&token={}".format(
                playlist_match.group(1), separator,
                expires_match.group(1), token_match.group(1))
            if fhd_match and fhd_match.group(1) == 'true':
                stream_url += '&h=1'

            response = self.session.get(
                stream_url, headers={
                    'Referer': embed_url}, timeout=REQ_TIMEOUT)
            response.raise_for_status()
            if not response.text.lstrip().startswith('#EXTM3U'):
                log.error("GET_LINKS: VixSrc returned an invalid playlist")
                return None

            log.info("GET_LINKS: M3U8 playlist resolved")
            return stream_url
        except Exception as e:
            log.error(
                "GET_LINKS: Unable to resolve VixSrc stream: {}".format(e))
            return None


def search_streaming_community_cool(query):
    """Fallback search using streaming-community.cool GET method"""
    try:
        import urllib.request
        import urllib.parse
        import re

        encoded_query = urllib.parse.quote_plus(query)
        url = "https://streaming-community.cool/index.php?story={}&do=search&subaction=search".format(
            encoded_query)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Referer': 'https://streaming-community.cool/',
            'DNT': '1'}

        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read()

            if response.getheader('Content-Encoding') == 'gzip':
                import gzip
                content = gzip.decompress(content)

            html = content.decode('utf-8', errors='ignore')

            # Extract results from HTML page
            results = []

            # Patterns to find titles and links
            title_patterns = [
                r'<a[^>]+href=["\']([^"\'>]+)["\'][^>]*>([^<]*' +
                re.escape(
                    query.lower()) +
                r'[^<]*)</a>',
                r'<h[1-6][^>]*>([^<]*' +
                re.escape(
                    query.lower()) +
                r'[^<]*)</h[1-6]>',
                r'title=["\']([^"\'>]*' +
                re.escape(
                    query.lower()) +
                r'[^"\'>]*)["\']'
            ]

            for pattern in title_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        title = match[1] if len(match) > 1 else match[0]
                        url_part = match[0] if len(match) > 1 else ''
                    else:
                        title = match
                        url_part = ''

                    if title and len(title.strip()) > 2:
                        # Determine type with improved logic for TV series
                        tv_keywords = [
                            'serie',
                            'season',
                            'stagione',
                            'episod',
                            'puntata',
                            'ep.',
                            's01',
                            's02',
                            's03',
                            's04',
                            's05',
                            'streaming']
                        item_type = 'tv' if any(
                            word in title.lower() for word in tv_keywords) else 'movie'

                        results.append({'name': title.strip(),
                                        'release_date': '' if item_type == 'tv' else '',
                                        '_raw': {'id': 'sc_cool',
                                                 'slug': url_part.replace(' ',
                                                                          '-').replace('--',
                                                                                       '-') if url_part else title.lower().replace(' ',
                                                                                                                                   '-').replace('--',
                                                                                                                                                '-'),
                                                 'type': item_type,
                                                 'source': 'streaming-community.cool',
                                                 'first_air_date': '' if item_type == 'movie' else ''}})

            # Remove duplicates
            seen = set()
            unique_results = []
            for result in results:
                title_key = result['name'].lower().strip()
                if title_key not in seen and len(title_key) > 2:
                    seen.add(title_key)
                    unique_results.append(result)

            log.info(
                "SC_COOL: Found {} unique results".format(
                    len(unique_results)))
            return unique_results[:10]  # Limit to 10 results

    except Exception as e:
        log.error("SC_COOL: Search failed - {}".format(e))
        return []


# --- Global API Functions ---
_api_instance = None


def get_api_instance(domain=None):
    global _api_instance
    if _api_instance is None:
        use_domain = domain or DEFAULT_DOMAIN
        _api_instance = API(use_domain)
    return _api_instance


def perform_search(query, domain=None, search_type=None):
    try:
        config = read_config()
        api_key = config.get('TMDB_API_KEY', '')
        if not api_key:
            log.error("SEARCH: TMDB_API_KEY not found in config.txt")
            return {'data': []}

        media_type = search_type if search_type in ('movie', 'tv') else 'movie'
        log.info(
            "SEARCH: Searching TMDB for '{}', type={}".format(
                query, media_type))

        session = requests.Session()
        session.headers.update(
            {'User-Agent': config.get('USER_AGENT', 'Mozilla/5.0')})

        url = "https://api.themoviedb.org/3/search/{}".format(media_type)
        params = {'api_key': api_key, 'language': 'it-IT', 'query': query}
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        results = response.json().get('results', [])
        log.info("SEARCH: TMDB returned {} results".format(len(results)))

        normalized_list = []
        for r in results:
            tmdb_id = r.get('id')
            name = r.get('title') or r.get('name')
            if not tmdb_id or not name:
                continue
            release_date = r.get('release_date') or r.get('first_air_date', '')
            vixsrc_media_type = 'movie' if media_type == 'movie' else 'tv'
            vixsrc_url = "https://vixsrc.to/{}/{}".format(
                vixsrc_media_type, tmdb_id)
            normalized_list.append({
                'name': name,
                'release_date': release_date,
                '_raw': {
                    'id': tmdb_id,
                    'tmdb_id': tmdb_id,
                    'type': media_type,
                    'source': 'streamingcommunity',
                    'vixsrc_url': vixsrc_url,
                }
            })
            log.info(
                "SEARCH: {} (tmdb_id={}) -> {}".format(name, tmdb_id, vixsrc_url))

        # CB01
        try:
            cb01_client = CB01()
            if search_type == 'movie':
                cb01_results = cb01_client.search_movies(query)
                cb01_type = 'movie'
            elif search_type == 'tv':
                cb01_results = cb01_client.search_series(query)
                cb01_type = 'tv'
            else:
                cb01_results = []
                cb01_type = 'movie'
            for cb01_item in cb01_results:
                normalized_list.append({
                    'name': "[CB01] {}".format(cb01_item['title']),
                    'release_date': '',
                    '_raw': {
                        'id': 'cb01',
                        'type': cb01_type,
                        'source': 'cb01',
                        'poster': cb01_item.get('poster', ''),
                        'url': cb01_item['url']
                    }
                })
            log.info(
                "SEARCH: Added {} results from CB01".format(
                    len(cb01_results)))
        except Exception as e:
            log.error("SEARCH: CB01 search failed - {}".format(e))

        # Altadefinizione
        try:
            altadef_client = Altadefinizione()
            if search_type == 'movie':
                altadef_results = altadef_client.search_movies(query)
                altadef_type = 'movie'
            elif search_type == 'tv':
                altadef_results = altadef_client.search_series(query)
                altadef_type = 'tv'
            else:
                altadef_results = []
                altadef_type = 'movie'
            for altadef_item in altadef_results:
                normalized_list.append({
                    'name': "[Altadefinizione] {}".format(altadef_item['title']),
                    'release_date': '',
                    '_raw': {
                        'id': 'altadefinizione',
                        'type': altadef_type,
                        'source': 'altadefinizione',
                        'poster': altadef_item.get('poster', ''),
                        'url': altadef_item['url']
                    }
                })
            log.info(
                "SEARCH: Added {} results from Altadefinizione".format(
                    len(altadef_results)))
        except Exception as e:
            log.error("SEARCH: Altadefinizione search failed - {}".format(e))

        log.info(
            "SEARCH: Returning {} normalized results".format(
                len(normalized_list)))
        return {'data': normalized_list}
    except Exception as e:
        log.error("perform_search failed for query: {} - {}".format(query, e))
        return {'data': []}


def get_title_details(slug, domain=None, title_name=None):
    try:
        api = get_api_instance(domain)
        details = api.load(slug)
        return details
    except Exception as e:
        log.error("get_title_details failed for slug: {} - {}".format(slug, e))
        return None


def get_stream_links(vixsrc_url, tmdb_id, tv=None, domain=None):
    try:
        api = get_api_instance(domain)
        return api.get_links(vixsrc_url, tmdb_id, tv)
    except Exception as e:
        log.error("get_stream_links failed: {}".format(e))
        return None


def _find_first_value(data, key_names):
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = str(key).lower()
            if key_lower in key_names and isinstance(
                    value, str) and value.strip():
                return value.strip()
        for value in data.values():
            found = _find_first_value(value, key_names)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_first_value(value, key_names)
            if found:
                return found
    return None


def _extract_poster_url(title_data, base_url, cdn_url=None):
    images = title_data.get('images')
    if isinstance(images, list):
        selected = None
        for image in images:
            if isinstance(image, dict) and image.get(
                    'type') == 'poster' and image.get('lang') == 'it':
                selected = image
                break
        if not selected:
            for image in images:
                if isinstance(image, dict) and image.get('type') == 'poster':
                    selected = image
                    break
        if selected:
            direct_url = selected.get('url') or selected.get(
                'src') or selected.get('original_url_field')
            filename = selected.get('filename')
            if direct_url:
                poster = direct_url
            elif filename and cdn_url:
                poster = "{}/images/{}".format(cdn_url.rstrip('/'),
                                               filename.lstrip('/'))
            elif filename:
                poster = urljoin(base_url,
                                 "/images/{}".format(filename.lstrip('/')))
            else:
                poster = None
            if poster:
                if poster.startswith('//'):
                    return 'https:{}'.format(poster)
                if poster.startswith('http'):
                    return poster
                return urljoin(base_url, poster)

    poster = (
        title_data.get('poster_url') or
        title_data.get('poster') or
        title_data.get('cover') or
        title_data.get('image') or
        title_data.get('thumbnail')
    )
    if isinstance(poster, dict):
        poster = (
            poster.get('url') or
            poster.get('src') or
            poster.get('path') or
            poster.get('filename')
        )
    if not poster:
        poster = _find_first_value(title_data, set([
            'poster_url', 'poster', 'cover', 'image', 'thumbnail', 'src', 'path'
        ]))
    if not poster:
        return None
    if poster.startswith('//'):
        return 'https:{}'.format(poster)
    if poster.startswith('http'):
        return poster
    return urljoin(base_url, poster)


def scrape_category_page(category_url, domain=None):
    """Scrapes a category page for content items."""
    log.info("Scraping category page: {}".format(category_url))
    items = []
    try:
        api = get_api_instance(domain)
        base_url = "https://{}".format(api.domain)
        html_content = api._wbpage_as_text(category_url)

        json_patterns = [
            r'window\.__NUXT__\s*=\s*({.+?});',
            r"data-page=(['\"])(.*?)\1",
            r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
            r'__NEXT_DATA__[\'\"]\s*type\s*=\s*[\'"]application/json[\'"]\s*[^>]*>([^<]+)<']

        for pattern in json_patterns:
            matches = re.findall(pattern, html_content, re.DOTALL)
            if matches:
                log.info(
                    "Found JSON data using pattern: {}...".format(pattern[:30]))
                for match in matches:
                    try:
                        if 'data-page' in pattern:
                            json_str = html.unescape(match[1])
                        else:
                            json_str = match

                        data = json.loads(json_str)
                        titles = []

                        if isinstance(data, dict):
                            props = data.get('props', {})
                            cdn_url = props.get('cdn_url') or base_url
                            if 'titles' in props:
                                titles = props['titles']
                            elif 'data' in props:
                                titles = props['data']
                            elif 'results' in data:
                                titles = data['results']
                            elif 'data' in data:
                                titles = data['data']

                        for title_data in titles[:20]:
                            if isinstance(title_data, dict):
                                name = title_data.get(
                                    'name') or title_data.get('title')
                                slug = None

                                href = title_data.get(
                                    'href') or title_data.get('url')
                                if href and ('/titles/' in href):
                                    slug = href.split('/')[-1]

                                if not slug:
                                    slug_part = title_data.get('slug')
                                    item_id = title_data.get('id')
                                    if slug_part:
                                        slug = "{}-{}".format(
                                            item_id, slug_part) if item_id else slug_part

                                poster = _extract_poster_url(
                                    title_data, base_url, cdn_url)

                                if name and slug:
                                    item_type = title_data.get('type')
                                    items.append({
                                        'title': name,
                                        'slug': slug,
                                        'tmdb_id': title_data.get('tmdb_id') or title_data.get('tmdbId'),
                                        'poster_url': poster,
                                        'type': 'Movie' if item_type == 'movie' else ('TV' if item_type == 'tv' else None)
                                    })
                                    if len(items) <= 3:
                                        log.info("CATEGORY_PARSE: title={} slug={} type={} poster={} keys={}".format(
                                            name, slug, item_type, bool(poster), sorted(title_data.keys())[:20], ))

                        if items:
                            break

                    except (json.JSONDecodeError, Exception) as e:
                        log.debug("Failed to parse JSON match: {}".format(e))
                        continue

                if items:
                    break

        if not items:
            log.info("No JSON data found, trying HTML parsing...")
            soup = BeautifulSoup(html_content, 'html.parser')

            all_links = soup.find_all('a', href=True)
            for link in all_links[:50]:
                href = link.get('href', '')
                if '/titles/' in href or '/it/titles/' in href:
                    slug = href.split('/')[-1]
                    title = (link.get('title') or
                             link.get('aria-label') or
                             link.get_text(strip=True))

                    if title and slug and len(title) > 2:
                        items.append({
                            'title': title.strip(),
                            'slug': slug,
                            'poster_url': None,
                            'type': None
                        })

        log.info(
            "Successfully extracted {} items from category page".format(
                len(items)))

    except Exception as e:
        log.error(
            "Failed to scrape category page {}: {}".format(
                category_url, e))

    return items


def resolve_vixsrc_stream(tmdb_id, season=None, episode=None):
    """
    Resolve a fresh M3U8 URL from VixSrc.
    Returns the M3U8 URL or None if resolution fails.
    """
    try:
        from .search_functions import get_stream_links
        vix_domain = "vixsrc.to"
        tv_tuple = None
        if season is not None and episode is not None and season > 0 and episode > 0:
            tv_tuple = (season, episode)
        log.info(
            "RESOLVE: Resolving VixSrc for tmdb_id={}, tv={}".format(
                tmdb_id, tv_tuple))
        return get_stream_links(vix_domain, tmdb_id, tv=tv_tuple)
    except Exception as e:
        log.error("RESOLVE: Failed to resolve VixSrc stream: {}".format(e))
        return None
