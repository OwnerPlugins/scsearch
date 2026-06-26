# -*- coding: utf-8 -*-

import urllib.parse
import html as html_module
import re
import requests

try:
    from .logger import get_logger
    log = get_logger()
except ImportError:
    import logging
    log = logging.getLogger(__name__)


def _read_cb01_urls():
    """Read CB01 base URLs from config.txt file."""
    import os
    config_path = os.path.join(os.path.dirname(__file__), 'config.txt')
    url = ''
    fallback = ''
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('CB01_URL='):
                    url = line.split('=', 1)[1].strip().rstrip('/')
                elif line.startswith('CB01_URL_FALLBACK='):
                    fallback = line.split('=', 1)[1].strip().rstrip('/')
    except Exception:
        pass
    return url, fallback


class CB01:
    def __init__(self):
        """
        Initialize the client for the CB01 website.
        Sets base URLs and request headers.
        """
        base_url, fallback_url = _read_cb01_urls()
        self.base_film = base_url
        self.base_serie = base_url + '/serietv'
        self.base_fallback = fallback_url

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        })

        log.info("CB01: Client initialized.")

    def _find_hoster_url(self, text):
        """Find a Mixdrop/Maxstream/Uprot URL in text or HTML."""
        if not text:
            return None

        value = html_module.unescape(str(text))
        value = urllib.parse.unquote(value)
        patterns = [
            r'https?://[^"\'<>\s]*(?:m1xdrop|mixdrop|mdy48tn97)[^"\'<>\s]*',
            r'https?://[^"\'<>\s]*(?:maxstream|uprot)[^"\'<>\s]*',
        ]

        for pattern in patterns:
            match = re.search(pattern, value, re.IGNORECASE)
            if match:
                return match.group(0).rstrip('\\/')

        return None

    def _detect_service(self, url, label=''):
        """
        Detect the streaming service type based on URL or label.
        Returns: 'maxstream', 'mixdrop', or 'hoster'.
        """
        value = f"{url or ''} {label or ''}".lower()
        if 'maxstream' in value or 'uprot' in value:
            return 'maxstream'
        if 'mixdrop' in value or 'm1xdrop' in value or 'mdy48tn97' in value:
            return 'mixdrop'
        return 'hoster'

    def _make_streaming_link(
            self,
            url,
            quality='SD',
            label='',
            original_url=None):
        """Build a streaming link dictionary."""
        service = self._detect_service(url, label)
        return {
            'url': url,
            'original_url': original_url or url,
            'type': service,
            'quality': quality
        }

    def _extract_cb01_series_seasons(self, html):
        """
        Extract seasons and episodes from CB01 series page.
        Looks for sp-wrap blocks and extracts Mixdrop/Maxstream links.
        """
        seasons = []
        season_blocks = re.findall(
            r'<div class="sp-head[^"]*"[^>]*>\s*STAGIONE\s+(\d+).*?</div>\s*'
            r'<div class="sp-body">(.*?)(?:<div class="spdiv">|</div>\s*</div>)',
            html,
            re.IGNORECASE | re.DOTALL)

        log.info(f"CB01_DETAILS: Found {len(season_blocks)} sp-wrap blocks")

        for season_num, season_content in season_blocks:
            season_data = {
                'season_number': int(season_num),
                'episodes': []
            }

            rows = re.findall(
                r'<p[^>]*>(.*?)</p>',
                season_content,
                re.IGNORECASE | re.DOTALL)
            log.info(
                "CB01_DETAILS: Season {}, episode rows found: {}".format(
                    season_num, len(rows)))

            for row in rows:
                row_text = html_module.unescape(re.sub(r'<[^>]+>', ' ', row))
                episode_match = re.search(r'(\d+)\s*[xX×]\s*(\d+)', row_text)
                if not episode_match:
                    continue

                episode_number = int(episode_match.group(2))
                links = re.findall(
                    r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>',
                    row,
                    re.IGNORECASE | re.DOTALL)

                for url, label in links:
                    label = html_module.unescape(
                        re.sub(r'<[^>]+>', '', label)).strip()
                    service = self._detect_service(url, label)
                    if service not in ('mixdrop', 'maxstream'):
                        continue

                    resolved_url = self.resolve_stayonline_url(
                        url) if 'stayonline.pro' in url.lower() else url
                    if not resolved_url:
                        resolved_url = url
                        log.warning(
                            f"CB01_DETAILS: Using unresolved page link for {label}: {url}")

                    season_data['episodes'].append({
                        'episode_number': episode_number,
                        'url': resolved_url,
                        'original_url': url,
                        'type': self._detect_service(resolved_url, label),
                        'quality': label or service.title()
                    })
                    log.info(
                        f"CB01_DETAILS: Episode {episode_number} {label}: {resolved_url}")

            if season_data['episodes']:
                seasons.append(season_data)
                log.info(
                    f"CB01_DETAILS: Season {season_num} added with "
                    f"{len(season_data['episodes'])} episode links"
                )

        return seasons

    def search_movies(self, query):
        """
        Search for movies on CB01 and parse results.
        Returns a list of result dictionaries.
        """
        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"{self.base_film}/?s={encoded_query}"
            log.info(f"CB01: Movie search URL: {search_url}")

            response = self.session.get(
                search_url, timeout=15, allow_redirects=True)
            response.raise_for_status()

            log.info(
                "CB01: Movie search response received. Status: {}".format(
                    response.status_code))
            html = response.text
            log.info(
                "CB01: HTML length: {}, final URL: {}".format(
                    len(html), response.url))

            movie_pattern = re.compile(
                r'<div class="card mp-post horizontal">.*?'
                r'<a href="([^"]+)">.*?'
                r'<img src="([^"]+)" alt="([^"]+)".*?'
                r'<h3 class="card-title"><a href="[^"]+">([^<]+)</a></h3>',
                re.DOTALL | re.IGNORECASE
            )

            matches = movie_pattern.findall(html)
            log.info(f"CB01: Pattern found {len(matches)} potential results")

            if not matches:
                log.warning("CB01: No results found with pattern")
                return []

            results = []
            for match in matches:
                title = match[3].strip()
                title = re.sub(r'\s*\[HD\]\s*', '', title)
                title = re.sub(r'\s*\(\d{4}\)\s*$', '', title)

                result = {
                    'url': match[0],
                    'poster': match[1],
                    'title': title,
                    'description': '',
                    'source': 'cb01'
                }
                results.append(result)
                log.info(f"CB01: Parsed movie: {result['title']}")

            log.info(f"CB01: Found {len(results)} movies on page.")
            return results

        except requests.exceptions.RequestException as e:
            log.error(f"CB01: Error during movie search: {e}")
            return []

    def search_series(self, query):
        """
        Search for TV series on CB01 and parse results.
        Returns a list of result dictionaries.
        """
        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"{self.base_serie}/?s={encoded_query}"
            log.info(f"CB01: TV series search URL: {search_url}")

            response = self.session.get(
                search_url, timeout=15, allow_redirects=True)
            response.raise_for_status()

            log.info("CB01: TV series search response received. Status: {}".format(response.status_code))
            html = response.text

            series_pattern = re.compile(
                r'<div class="card mp-post horizontal">.*?'
                r'<a href="([^"]+)">.*?'
                r'<img src="([^"]+)" alt="([^"]+)".*?'
                r'<h3 class="card-title"><a href="[^"]+">([^<]+)</a></h3>',
                re.DOTALL | re.IGNORECASE
            )

            matches = series_pattern.findall(html)
            log.info(f"CB01: Found {len(matches)} TV series on page.")

            results = []
            for match in matches:
                title = match[3].strip()
                title = re.sub(r'\s*\[HD\]\s*', '', title)
                title = re.sub(r'\s*\(\d{4}\)\s*$', '', title)

                result = {
                    'url': match[0],
                    'poster': match[1],
                    'title': title,
                    'description': '',
                    'source': 'cb01'
                }
                results.append(result)
                log.info(f"CB01: Parsed TV series: {result['title']}")

            return results

        except requests.exceptions.RequestException as e:
            log.error(f"CB01: Error during TV series search: {e}")
            return []

    def resolve_stayonline_url(self, stayonline_url):
        """
        Resolve a stayonline.pro URL to get the direct Mixdrop or Maxstream link.
        Does not decrypt the hoster; returns the link to be passed to the player.
        """
        try:
            log.info(f"CB01: Resolving stayonline URL: {stayonline_url}")

            parts = [part for part in stayonline_url.split('/') if part]
            link_id = parts[-1] if parts else ''

            if not link_id:
                log.error("CB01: Could not extract ID from stayonline URL")
                return None

            ajax_url = 'https://stayonline.pro/ajax/linkEmbedView.php'
            data = {'id': link_id, 'ref': ''}
            headers = {
                'User-Agent': self.session.headers['User-Agent'],
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json',
                'Origin': 'https://stayonline.pro',
                'Referer': 'https://stayonline.pro/'
            }

            response = self.session.post(
                ajax_url, data=data, headers=headers, timeout=10)
            log.info(f"CB01: Stayonline AJAX status: {response.status_code}")

            if response.ok:
                json_data = response.json()
                value = json_data.get('data', {}).get('value', '')

                if value:
                    log.info(
                        f"CB01: Stayonline value received (first 200 chars): {value[:200]}")

                    hoster_url = self._find_hoster_url(value)
                    if hoster_url:
                        log.info(f"CB01: Resolved hoster URL: {hoster_url}")
                        return hoster_url

            embed_url = f'https://stayonline.pro/e/{link_id}/'
            response = self.session.get(embed_url, timeout=10)
            if response.ok:
                hoster_url = self._find_hoster_url(response.text)
                if hoster_url:
                    log.info(f"CB01: Fallback hoster URL: {hoster_url}")
                    return hoster_url

            log.warning("CB01: Could not resolve stayonline URL")
            return None

        except Exception as e:
            log.error(f"CB01: Error resolving stayonline: {e}")
            return None

    def get_streaming_links(self, movie_url):
        """
        Extract streaming links from the movie/series page.
        Returns a list of dictionaries with url, quality, service.
        """
        try:
            log.info(f"CB01_PLAY: Loading page: {movie_url}")
            response = self.session.get(movie_url, timeout=15)
            response.raise_for_status()
            html = response.text

            # Log HTML for debug (first 2000 chars)
            log.info(f"CB01_PLAY: HTML (first 2000 chars): {html[:2000]}")
            log.info(
                f"CB01_PLAY: HTML contains 'stayonline': {
                    'stayonline' in html.lower()}")
            log.info(
                f"CB01_PLAY: HTML contains 'streaming': {
                    'streaming' in html.lower()}")
            log.info(
                f"CB01_PLAY: HTML contains 'stagione': {
                    'stagione' in html.lower()}")
            log.info(
                f"CB01_PLAY: HTML contains 'episodio': {
                    'episodio' in html.lower()}")
            log.info(
                f"CB01_PLAY: URL contains '/serietv/': {'/serietv/' in movie_url}")

            # Look for stayonline links (for movies) or uprot/maxstream (for
            # series)
            stayonline_pattern = r'https?://stayonline\.pro/[^"\'<>]+'
            stayonline_links = re.findall(
                stayonline_pattern, html, re.IGNORECASE)

            # If no stayonline, look for uprot/maxstream (TV series)
            if not stayonline_links:
                uprot_pattern = r'https?://uprot\.net/[^"\'<>]+'
                uprot_links = re.findall(uprot_pattern, html, re.IGNORECASE)
                if uprot_links:
                    log.info(
                        f"CB01_PLAY: Found {
                            len(uprot_links)} uprot/maxstream links (TV series)")
                    return [
                        {'url': url, 'quality': 'Maxstream', 'service': 'maxstream'}
                        for url in dict.fromkeys(uprot_links)
                    ]

            stayonline_links = stayonline_links or []

            if not stayonline_links:
                log.warning("CB01_PLAY: No stayonline or uprot links found")
                return []

            log.info(
                f"CB01_PLAY: Found {
                    len(stayonline_links)} stayonline links")

            results = []
            for link in stayonline_links:
                resolved = self.resolve_stayonline_url(link)
                if not resolved:
                    continue

                quality = self._extract_quality(resolved)
                service = self._detect_service(resolved)
                results.append(
                    {'url': resolved, 'quality': quality, 'service': service})
                log.info(
                    f"CB01_PLAY: {service} URL added ({quality}): {resolved}")

            return results

        except Exception as e:
            log.error(f"CB01_PLAY: Error extracting links: {e}")
            return []

    def _extract_quality(self, url):
        """Extract quality from Mixdrop URL."""
        quality_patterns = [
            (r'2160p|4K', '4K'),
            (r'1080p', '1080p'),
            (r'720p', '720p'),
            (r'480p', '480p'),
            (r'360p', '360p')
        ]

        for pattern, label in quality_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return label

        return 'SD'

    def get_page_details(self, page_url):
        """
        Extract details from CB01 page (movie or TV series).
        Returns a dictionary with title, year, description, poster, genre,
        seasons (if series), streaming_links (if movie).
        """
        try:
            log.info(f"CB01_DETAILS: Loading page: {page_url}")
            response = self.session.get(page_url, timeout=15)
            response.raise_for_status()
            html = response.text

            log.info(f"CB01_DETAILS: HTML length: {len(html)}")
            log.info(
                f"CB01_DETAILS: HTML sample (first 3000 chars): {html[:3000]}")

            details = {
                'title': '',
                'year': '',
                'description': '',
                'poster': '',
                'type': 'Movie' if '/serietv/' not in page_url else 'TvSeries',
                'genre': '',
                'seasons': [],
                'streaming_links': []
            }

            # Extract title - try multiple sources
            title = ''

            # First try og:title (most reliable)
            og_title_match = re.search(
                r'<meta property="og:title" content="([^"]+)"', html, re.IGNORECASE)
            if og_title_match:
                title = og_title_match.group(1).strip()
                # Remove " Streaming - FILM GRATIS by CB01 OFFICIAL"
                title = re.sub(
                    r'\s+Streaming.*$',
                    '',
                    title,
                    flags=re.IGNORECASE)
                log.info(f"CB01_DETAILS: Title from og:title: {title}")

            # Fallback: <title> tag
            if not title:
                title_match = re.search(
                    r'<title>([^<]+)</title>', html, re.IGNORECASE)
                if title_match:
                    title = title_match.group(1).strip()
                    # Remove " Streaming - FILM GRATIS by CB01 OFFICIAL"
                    title = re.sub(
                        r'\s+Streaming.*$', '', title, flags=re.IGNORECASE)
                    log.info(f"CB01_DETAILS: Title from <title>: {title}")

            details['title'] = title

            # Extract year from title
            year_match = re.search(
                r'\[(HD|SD)\]\s*\((\d{4})\)',
                details['title'])
            if year_match:
                details['year'] = year_match.group(2)
                log.info(f"CB01_DETAILS: Year found: {details['year']}")

            # Extract poster from og:image
            poster_match = re.search(
                r'<meta property="og:image" content="([^"]+)"',
                html,
                re.IGNORECASE)
            if poster_match:
                details['poster'] = poster_match.group(1)
                log.info(f"CB01_DETAILS: Poster found: {details['poster']}")

            # Extract description from og:description
            desc_match = re.search(
                r'<meta property="og:description" content="([^"]+)"',
                html,
                re.IGNORECASE)
            if desc_match:
                desc_text = desc_match.group(1).strip()
                # Decode HTML entities
                desc_text = desc_text.replace('&#8217;', "'")
                desc_text = desc_text.replace('&#8230;', '...')
                desc_text = desc_text.replace('&amp;', '&')
                desc_text = desc_text.replace('&#8242;', "'")
                desc_text = desc_text.replace('&quot;', '"')

                # Extract genre from description (first uppercase word(s))
                genre_match = re.match(
                    r'^([A-Z]+(?:\s+[A-Z]+)*)\s+', desc_text)
                if genre_match:
                    details['genre'] = genre_match.group(1)
                    # Remove genre from description
                    desc_text = desc_text[len(details['genre']):].strip()
                    # Remove "– DURATA XX' – PAESE" pattern
                    desc_text = re.sub(
                        r'^–\s+DURATA\s+\d+[^–]*–\s+[A-Z]+\s+', '', desc_text)
                    log.info(f"CB01_DETAILS: Genre found: {details['genre']}")

                details['description'] = desc_text.strip()
                log.info(
                    f"CB01_DETAILS: Description: {details['description'][:100]}...")

            # If it's a TV series, extract seasons and uprot links
            if details['type'] == 'TvSeries':
                log.info("CB01_DETAILS: Parsing TV series...")
                details['seasons'] = self._extract_cb01_series_seasons(html)
                log.info(
                    f"CB01_DETAILS: Found {len(details['seasons'])} seasons")
            else:
                # For movies, extract Mixdrop/Maxstream links with quality
                log.info("CB01_DETAILS: Parsing movie...")

                # Extract all stayonline links with link text
                link_pattern = r'<a href="(https://stayonline\.pro/[^"]+)"[^>]*>([^<]+)</a>'
                all_links = re.findall(link_pattern, html, re.IGNORECASE)

                log.info(f"CB01_DETAILS: Found {len(all_links)} total links")

                seen_urls = set()

                for url, link_text in all_links:
                    label_service = self._detect_service('', link_text)
                    if label_service not in ('mixdrop', 'maxstream'):
                        continue
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    pos = html.find(url)
                    hd_pos = html.find('<strong>Streaming HD:</strong>')
                    quality = 'HD' if hd_pos > 0 and pos > hd_pos else 'SD'

                    resolved_url = self.resolve_stayonline_url(url)
                    if not resolved_url:
                        log.warning(
                            f"CB01_DETAILS: Unresolved link, skipping: {url}")
                        continue
                    seen_urls.add(resolved_url)

                    details['streaming_links'].append(
                        self._make_streaming_link(
                            resolved_url, quality, link_text, url))
                    log.info(
                        f"CB01_DETAILS: Added {
                            self._detect_service(
                                resolved_url,
                                link_text)} {quality} link: {resolved_url}")

                direct_link_pattern = r'href="(https?://(?:[^"]*(?:m1xdrop|mixdrop|mdy48tn97|maxstream|uprot)[^"]*))"[^>]*>([^<]*)</a>'
                for url, link_text in re.findall(
                        direct_link_pattern, html, re.IGNORECASE):
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    quality = self._extract_quality(url)
                    details['streaming_links'].append(
                        self._make_streaming_link(url, quality, link_text)
                    )
                    log.info(
                        f"CB01_DETAILS: Added direct {
                            self._detect_service(
                                url, link_text)} {quality} link: {url}")

                log.info(
                    f"CB01_DETAILS: Total {len(details['streaming_links'])} unique hoster links")

            log.info(
                f"CB01_DETAILS: Extracted details - Title: {
                    details['title']}, Year: {
                    details['year']}, Genre: {
                    details['genre']}, Seasons: {
                    len(
                        details['seasons'])}")
            return details

        except Exception as e:
            log.error(f"CB01_DETAILS: Error extracting details: {e}")
            import traceback
            log.error(f"CB01_DETAILS: Traceback: {traceback.format_exc()}")
            return None
