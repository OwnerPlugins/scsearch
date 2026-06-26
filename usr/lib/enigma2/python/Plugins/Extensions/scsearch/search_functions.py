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
        log.info(f"API initialized for domain: {domain}")

    def _wbpage_as_text(self, url):
        log.debug(f"Fetching URL: {url}")
        try:
            response = self.session.get(url, timeout=REQ_TIMEOUT)
            response.raise_for_status()
            return response.text
        except requests.exceptions.Timeout:
            log.error(f"Timeout fetching URL: {url}")
            raise WebPageTimeOutError(url)
        except requests.exceptions.RequestException as e:
            log.error(f"Error fetching URL: {url} - {e}")
            raise WebPageStatusCodeError(f"Request failed: {e}")

    def search(self, query):
        """Search using TMDB HTML parsing"""
        import urllib.parse

        encoded_query = urllib.parse.quote(query)
        url = f"https://www.themoviedb.org/search?query={encoded_query}"
        log.info(f"TMDB API.search: Searching on {url}")

        try:
            response = self.session.get(url, timeout=REQ_TIMEOUT)
            response.raise_for_status()
            html_content = response.text

            log.info(f"TMDB API.search: HTML length: {len(html_content)}")

            results = []

            # Pattern to extract cards
            card_pattern = r'<div[^>]*class="card v4 tight"[^>]*>.*?</div>\s*</div>\s*</div>'
            cards = re.findall(card_pattern, html_content, re.DOTALL)

            log.info(f"TMDB API.search: Found {len(cards)} cards")

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
                            release_date = f"{year}-01-01"  # simplified format

                    results.append({
                        'id': item_id,
                        'slug': slug,
                        'name': title,
                        'type': media_type,
                        'release_date': release_date if media_type == 'movie' else '',
                        'first_air_date': release_date if media_type == 'tv' else ''
                    })

                    log.info(
                        f"TMDB API.search: Parsed - ID: {item_id}, Title: {title}, Type: {media_type}")

                except Exception as e:
                    log.error(f"TMDB API.search: Error parsing card: {e}")
                    continue

            log.info(
                "TMDB API.search: Successfully parsed {} results".format(
                    len(results)))
            return {'data': results}

        except Exception as e:
            log.error(f"TMDB API.search: Error - {e}")
            import traceback
            log.error(f"TMDB API.search: Traceback: {traceback.format_exc()}")
            return {'data': []}

    def load(self, content_slug):
        url = f"https://{self.domain}/it/titles/{content_slug}"
        log.info(f"API.load: Loading URL: {url}")
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
                        f"API.load: Found potential JSON with pattern: {pattern[:30]}...")
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
                                f"API.load: JSON from pattern '{pattern[:30]}' is incomplete. Trying next pattern.")
                            continue

                        data = parsed_json
                        log.info(
                            "API.load: Successfully parsed complete JSON data.")
                        break
                    except (json.JSONDecodeError, IndexError, Exception) as e:
                        log.debug(
                            f"API.load: Failed to parse JSON from pattern '{pattern[:30]}': {e}")
                        continue
        except Exception as e:
            log.error(f"API.load: Error parsing {url}: {e}")
            data = None

        if not data:
            log.error(
                f"API.load: Unable to find or parse JSON data-page in {url}")
            return None

        props = data.get("props", {})
        title_data = props.get("title", {})

        media_type = "Movie" if title_data.get(
            "type") == "movie" else "TvSeries"
        name = title_data.get("name")
        vix_url = props.get("vix_url")
        log.info(f"API.load: Vix URL found: {vix_url}")

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
                        "url": f"https://{self.domain}/it/watch/{content_slug}/{episode_id}"
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
        # headers = self.session.headers.copy()
        media_type = "tv" if tv else "movie"
        episode_path = "/" + str(tv[0]) + "/" + str(tv[1]) if tv else ""
        vixsrc_iframe_url = "https://{}/{}/{}{}".format(
            vixsrc_url, media_type, tmdb_id, episode_path)
        log.info(f"GET_LINKS: Fetching iframe_page: {vixsrc_iframe_url}")
        iframe_page = self._wbpage_as_text(vixsrc_iframe_url)

        try:
            playlist_params_match = re.search(
                r"window\\.masterPlaylist[^:]+params:[^{]+({[^<]+?})", iframe_page)
            playlist_url_match = re.search(
                r"window\\.masterPlaylist[^<]+url:[^<]+\'([^<]+?)\'", iframe_page)
            can_play_fhd_match = re.search(
                r"window\\.canPlayFHD\\s+?=\\s+?(\\w+)", iframe_page)

            playlist_params = json.loads(
                re.sub(
                    r',[^\\\"]+}',
                    "}",
                    playlist_params_match.group(1).replace(
                        "'",
                        '"'))) if playlist_params_match else {}
            playlist_url = playlist_url_match.group(
                1) if playlist_url_match else None
            can_play_fhd = can_play_fhd_match and can_play_fhd_match.group(
                1) == "true"

            if not playlist_url or not playlist_params.get("token"):
                log.error(
                    "GET_LINKS: Unable to extract playlist_url or token from page.")
                return None

            dl_url = (
                playlist_url
                + ("&" if bool(re.search(r"\\?[^#]+", playlist_url)) else "?")
                + "expires="
                + str(playlist_params.get("expires", ""))
                + "&token="
                + playlist_params.get("token", "")
                + ("&h=1" if can_play_fhd else "")
            )
            log.info(f"GET_LINKS: Built M3U8 URL: {dl_url}")
            return dl_url
        except Exception as e:
            log.error(f"GET_LINKS: Error parsing playlist data: {e}")
            return None


def search_streaming_community_cool(query):
    """Fallback search using streaming-community.cool GET method"""
    try:
        import urllib.request
        import urllib.parse
        import re

        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://streaming-community.cool/index.php?story={encoded_query}&do=search&subaction=search"

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
                r'[^"\'>]*)["\']']

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

            log.info(f"SC_COOL: Found {len(unique_results)} unique results")
            return unique_results[:10]  # Limit to 10 results

    except Exception as e:
        log.error(f"SC_COOL: Search failed - {e}")
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
        log.info(f"SEARCH: Searching TMDB for '{query}', type={media_type}")

        session = requests.Session()
        session.headers.update(
            {'User-Agent': config.get('USER_AGENT', 'Mozilla/5.0')})

        url = f"https://api.themoviedb.org/3/search/{media_type}"
        params = {'api_key': api_key, 'language': 'it-IT', 'query': query}
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        results = response.json().get('results', [])
        log.info(f"SEARCH: TMDB returned {len(results)} results")

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
            log.info(f"SEARCH: {name} (tmdb_id={tmdb_id}) -> {vixsrc_url}")

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
                    'name': f"[CB01] {cb01_item['title']}",
                    'release_date': '',
                    '_raw': {
                        'id': 'cb01',
                        'type': cb01_type,
                        'source': 'cb01',
                        'poster': cb01_item.get('poster', ''),
                        'url': cb01_item['url']
                    }
                })
            log.info(f"SEARCH: Added {len(cb01_results)} results from CB01")
        except Exception as e:
            log.error(f"SEARCH: CB01 search failed - {e}")

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
                    'name': f"[Altadefinizione] {altadef_item['title']}",
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
                f"SEARCH: Added {
                    len(altadef_results)} results from Altadefinizione")
        except Exception as e:
            log.error(f"SEARCH: Altadefinizione search failed - {e}")

        log.info(
            f"SEARCH: Returning {
                len(normalized_list)} normalized results")
        return {'data': normalized_list}
    except Exception as e:
        log.error(f"perform_search failed for query: {query} - {e}")
        return {'data': []}


def get_title_details(slug, domain=None, title_name=None):
    try:
        api = get_api_instance(domain)
        details = api.load(slug)
        return details
    except Exception as e:
        log.error(f"get_title_details failed for slug: {slug} - {e}")
        return None


def get_stream_links(vixsrc_url, tmdb_id, tv=None, domain=None):
    try:
        api = get_api_instance(domain)
        return api.get_links(vixsrc_url, tmdb_id, tv)
    except Exception as e:
        log.error(f"get_stream_links failed: {e}")
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
                poster = "%s/images/%s" % (cdn_url.rstrip('/'),
                                           filename.lstrip('/'))
            elif filename:
                poster = urljoin(base_url, "/images/%s" % filename.lstrip('/'))
            else:
                poster = None
            if poster:
                if poster.startswith('//'):
                    return 'https:%s' % poster
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
        return 'https:%s' % poster
    if poster.startswith('http'):
        return poster
    return urljoin(base_url, poster)


def scrape_category_page(category_url, domain=None):
    """Scrapes a category page for content items."""
    log.info(f"Scraping category page: {category_url}")
    items = []
    try:
        api = get_api_instance(domain)
        base_url = f"https://{api.domain}"
        html_content = api._wbpage_as_text(category_url)

        json_patterns = [
            r'window\.__NUXT__\s*=\s*({.+?});',
            r"data-page=(['\"])(.*?)\1",
            r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
            r'__NEXT_DATA__[\'\"]\s*type\s*=\s*[\'"]application/json[\'"]\s*[^>]*>([^<]+)<']

        for pattern in json_patterns:
            matches = re.findall(pattern, html_content, re.DOTALL)
            if matches:
                log.info(f"Found JSON data using pattern: {pattern[:30]}...")
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
                                        slug = f"{item_id}-{slug_part}" if item_id else slug_part

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
                                        log.info("CATEGORY_PARSE: title=%s slug=%s type=%s poster=%s keys=%s" % (
                                            name,
                                            slug,
                                            item_type,
                                            bool(poster),
                                            sorted(title_data.keys())[:20],
                                        ))

                        if items:
                            break

                    except (json.JSONDecodeError, Exception) as e:
                        log.debug(f"Failed to parse JSON match: {e}")
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
            f"Successfully extracted {
                len(items)} items from category page")

    except Exception as e:
        log.error(f"Failed to scrape category page {category_url}: {e}")

    return items
