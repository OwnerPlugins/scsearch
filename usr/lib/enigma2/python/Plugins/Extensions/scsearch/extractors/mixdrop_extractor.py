# -*- coding: utf-8 -*-
"""
Mixdrop Extractor - Adapted from webstreamr
Extracts video URLs from Mixdrop embed pages
"""

import urllib.request
import urllib.parse
import re
from html import unescape

try:
    from ..logger import get_logger
    log = get_logger()
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class MixdropExtractor:
    def __init__(self):
        self.name = "Mixdrop"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
            'DNT': '1'}

    def supports(self, url):
        """Check if the URL is supported."""
        return bool(re.search(r'mixdrop', url, re.IGNORECASE))

    def extract_video_url(self, url, referer=None):
        """Extract video URL from Mixdrop."""
        try:
            log.info(f"MIXDROP: Starting extraction from: {url}")
            embed_url = self._normalize_url(url)
            log.info(f"MIXDROP: Embed URL: {embed_url}")

            embed_html = self._fetch_page(embed_url, referer)
            if not embed_html:
                log.error("MIXDROP: Unable to download embed page")
                return None

            if re.search(
                r"can't find the (file|video)|not found|unavailable",
                embed_html,
                    re.IGNORECASE):
                log.warning("MIXDROP: Video not available or not found")
                return None

            video_url = self._extract_video_from_embed(embed_html, embed_url)
            if video_url:
                if len(video_url) < 10:
                    log.error(f"MIXDROP: Extracted URL invalid: {video_url}")
                    return None
                log.info(f"MIXDROP: Video URL extracted: {video_url[:80]}...")
                return video_url

            log.error("MIXDROP: No video URL found")
            return None

        except Exception as e:
            log.error(f"MIXDROP: Extraction error: {e}")
            return None

    def _normalize_url(self, url):
        """Normalize Mixdrop URL to .ps domain."""
        url = url.strip()

        # Normalize to .ps domain and remove trailing segments
        if "club" in url:
            url = url.replace("club", "ps").split("/2")[0]
        elif "ag" in url:
            url = url.replace("ag", "ps").split("/2")[0]
        elif any(domain in url for domain in ["mdy48tn97.com", "mixdrop.to", "mixdrop.co"]):
            for domain in ["mdy48tn97.com", "mixdrop.to", "mixdrop.co"]:
                if domain in url:
                    url = url.replace(domain, "mixdrop.ps").split("/2")[0]
                    break

        # Ensure /e/ for embed
        if '/f/' in url:
            url = url.replace('/f/', '/e/')
        elif '/e/' not in url:
            match = re.search(r'(mixdrop\.[^/]+)/([^/]+)', url, re.IGNORECASE)
            if match:
                domain = match.group(1)
                file_id = match.group(2)
                url = f"https://{domain}/e/{file_id}"

        return url

    def _fetch_page(self, url, referer=None):
        """Download an HTML page."""
        try:
            headers = self.headers.copy()
            if referer:
                headers['Referer'] = referer

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                html = response.read().decode('utf-8', errors='ignore')
                log.info(f"MIXDROP: Page downloaded - Length: {len(html)}")
                return html
        except Exception as e:
            log.error(f"MIXDROP: Page download error: {e}")
            return None

    def _extract_video_from_embed(self, html, embed_url):
        """Extract video URL from embed page (ResolveURL style)."""
        try:
            log.info(f"MIXDROP: Starting extraction (length: {len(html)})")

            # Step 1: Look for iframe and follow it
            iframe_match = re.search(
                r'<iframe[^>]+src=["\']([^"\'\s]+)["\']', html, re.IGNORECASE)
            if iframe_match:
                iframe_url = iframe_match.group(1)
                if iframe_url.startswith('//'):
                    iframe_url = 'https:' + iframe_url
                log.info(f"MIXDROP: Found iframe: {iframe_url}")
                iframe_html = self._fetch_page(iframe_url, embed_url)
                if iframe_html:
                    log.info("MIXDROP: Iframe downloaded (length: {})".format(len(iframe_html)))
                    return self._extract_video_from_embed(
                        iframe_html, iframe_url)

            # Step 2: Look for redirect location
            location_match = re.search(
                r'''location\s*=\s*["']([^'"]+)''', html)
            if location_match:
                redirect_path = location_match.group(1)
                log.info(f"MIXDROP: Found redirect: {redirect_path}")
                redirect_url = urllib.parse.urljoin(embed_url, redirect_path)
                redirect_html = self._fetch_page(redirect_url, embed_url)
                if redirect_html:
                    html = redirect_html

            # Step 3: Unpack JavaScript
            if '(p,a,c,k,e,d)' in html:
                log.info("MIXDROP: Unpacking JS...")
                unpacked = self._unpack_js(html)
                if unpacked:
                    log.info(f"MIXDROP: Unpacked (length: {len(unpacked)})")
                    html = unpacked

            # Step 4: Search multiple patterns with priority
            match = re.search(r'MDCore\.wurl\s*=\s*["\']([^"\']+)["\']', html)
            if match:
                surl = match.group(1)
                if surl.startswith('//'):
                    surl = 'https:' + surl
                surl = unescape(surl)
                log.info(f"MIXDROP: URL found (MDCore.wurl): {surl[:80]}...")
                return surl

            match = re.search(
                r'(?:vsr|wurl|surl)[^=]*=\s*["\']([^"\']+)["\']', html)
            if match:
                surl = match.group(1)
                if surl.startswith('//'):
                    surl = 'https:' + surl
                surl = unescape(surl)
                log.info(f"MIXDROP: URL found: {surl[:80]}...")
                return surl

            log.error("MIXDROP: No video URL found")
            return None

        except Exception as e:
            log.error(f"MIXDROP: Extraction error: {e}")
            return None

    def _find_video_url(self, text):
        """Search for video URL in text."""
        patterns = [
            (r'MDCore\.wurl\s*=\s*["\']([^"\']+)["\']', 'MDCore.wurl'),
            (r'wurl\s*=\s*["\']([^"\']+)["\']', 'wurl'),
            (r'surl\s*=\s*["\']([^"\']+)["\']', 'surl'),
            (r'vsr\s*=\s*["\']([^"\']+)["\']', 'vsr'),
            (r'vsrc\s*=\s*["\']([^"\']+)["\']', 'vsrc'),
            (r'src:\s*["\']([^"\']+\.(?:mp4|m3u8))["\']', 'src:'),
            (r'file:\s*["\']([^"\']+\.(?:mp4|m3u8))["\']', 'file:'),
            (r'source:\s*["\']([^"\']+\.(?:mp4|m3u8))["\']', 'source:'),
            (r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', 'URL MP4'),
            (r'(//[^\s"\'<>]+(?:mixdrop|mxdcontent)[^\s"\'<>]+\.(?:mp4|m3u8))', 'Relative URL')
        ]

        for i, (pattern, name) in enumerate(patterns, 1):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                url = match.group(1)
                if url.startswith('//'):
                    url = 'https:' + url
                # Decode HTML entities (&amp; -> &)
                url = unescape(url)
                log.info(
                    f"MIXDROP: URL found with pattern #{i} ({name}): {url[:100]}...")
                return url

        log.warning(
            f"MIXDROP: No URL found in {
                len(patterns)} tested patterns")
        return None

    def _unpack_js(self, html_content):
        """Unpack packed JavaScript."""
        try:
            match = re.search(
                r"eval\(function\(p,a,c,k,e,(?:d|r)\).*?\}\('([^']+)',(\d+),(\d+),'([^']+)'\.split\('\|'\)",
                html_content,
                re.DOTALL)
            if not match:
                return html_content

            payload = match.group(1)
            base = int(match.group(2))
            # count = int(match.group(3))
            keywords = match.group(4).split('|')

            def lookup(m):
                word = m.group(0)
                try:
                    idx = int(word, base) if base <= 36 else int(word)
                    if 0 <= idx < len(keywords) and keywords[idx]:
                        return keywords[idx]
                except Exception:
                    pass
                return word

            pattern = r'\b[0-9a-z]+\b' if base > 10 else r'\b\d+\b'
            result = re.sub(pattern, lookup, payload)
            log.info(f"MIXDROP: Unpacked (length: {len(result)})")
            return result

        except Exception as e:
            log.error(f"MIXDROP: Unpack error: {e}")
            return html_content


def extract_video_url(url, referer=None):
    """Helper function for compatibility."""
    extractor = MixdropExtractor()
    return extractor.extract_video_url(url, referer)
