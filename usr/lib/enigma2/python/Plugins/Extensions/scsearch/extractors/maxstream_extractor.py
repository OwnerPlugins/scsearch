# -*- coding: utf-8 -*-

import urllib.request
import urllib.parse
import re

from scsearch.logger import get_logger
from scsearch.captcha_input import CaptchaInputScreen

log = get_logger()


class MaxStreamExtractor:
    def __init__(self):
        self.name = "MaxStream"
        self.main_url = "https://maxstream.video/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0'
        }

    def _unpack_js(self, packed_js):
        """Simple JavaScript unpacker for eval(function(p,a,c,k,e,d))"""
        try:
            # Basic unpacker - handles most common packed JS
            if 'eval(function(p,a,c,k,e,d)' in packed_js:
                # Extract packed data
                match = re.search(
                    r"'([^']+)'\s*\.\s*split\s*\(\s*'\|'\s*\)", packed_js)
                if match:
                    data = match.group(1)
                    words = data.split('|')

                    # Simple substitution
                    result = packed_js
                    for i, word in enumerate(words):
                        if word:
                            result = result.replace('\\b{}\\b'.format(i), word)

                    return result
            return packed_js
        except Exception:
            return packed_js

    def extract(self, url):
        """Extract video URL from maxstream page"""
        html = self._download(url)
        log.info("MAXSTREAM (extract): Downloaded HTML length: {}".format(len(html)))
        if not html:
            return None

        # Look for iframe
        iframe = self._find_match(html, r'<iframe[^>]+src=["\']([^"\']+)["\']')
        if iframe:
            log.info("MAXSTREAM (extract): Iframe found: {}".format(len(iframe)))
            html = self._download(iframe)
            if not html:
                log.info("MAXSTREAM (extract): Iframe HTML not found")
                return None

        # Pattern matching for video URLs
        patterns = [
            r'sources:\s*\[\s*\{\s*src:\s*["\']([^"\']+)["\']',
            r'src:\s*["\']([^"\']+\.(?:mp4|m3u8|webm))["\']',
            r'https?://[^\s"\'<>]*host-cdn\.net[^\s"\'<>]*\.m3u8',
            r'file:\s*["\']([^"\']+)["\']'
        ]

        # Search in HTML
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                video_url = matches[0]
                log.info("MAXSTREAM: URL found: {}".format(video_url))
                if '.m3u8' in video_url:
                    return self._get_best_quality(video_url)
                return video_url

        # Look for packed JavaScript
        js_match = self._find_match(
            html, r'(eval\s*\(\s*function\s*\([^}]+\}\s*\([^)]+\)\s*\))')
        if js_match:
            log.info("MAXSTREAM (extract): Found packed HTML: {}".format(js_match))
            unpacked = self._unpack_js(js_match)

            # Search in unpacked JS
            for pattern in patterns:
                matches = re.findall(pattern, unpacked, re.IGNORECASE)
                if matches:
                    video_url = matches[0]
                    log.info("MAXSTREAM (extract): Resolved HTML, new URL: {}".format(video_url))
                    if '.m3u8' in video_url:
                        return self._get_best_quality(video_url)
                    return video_url
        log.info("MAXSTREAM (extract): HTML not packed")
        return None

    def extract_url(self, url, referer=None):
        """Extract the final URL from MaxStream"""
        try:
            log.info("MAXSTREAM: Extracting URL from: {}".format(url))

            headers_copy = self.headers.copy()
            if referer:
                headers_copy['Referer'] = referer

            req = urllib.request.Request(url, headers=headers_copy)

            import time
            time.sleep(0.5)

            with urllib.request.urlopen(req, timeout=15) as response:
                html = response.read().decode('utf-8')
                log.info("MAXSTREAM: HTML received - Length: {}".format(len(html)))

            # Look for the packed script
            script_start = "<script type='text/javascript'>eval(function(p,a,c,k,e,d)"

            if script_start not in html:
                log.error("MAXSTREAM: Packed script not found")
                return None

            # Extract the packed script
            script_part = html.split(script_start)[1]
            script_end = script_part.find(")))") + 3
            if script_end == 2:
                log.error("MAXSTREAM: End of packed script not found")
                return None

            packed_script = "eval(function(p,a,c,k,e,d)" + \
                script_part[:script_end] + ")"

            # Unpack the script
            unpacked = self._unpack_script(packed_script)
            if not unpacked:
                log.error("MAXSTREAM: Unable to unpack script")
                return None

            # Extract the src URL
            src_match = re.search(r'src:"([^"]+)"', unpacked)
            if not src_match:
                # Alternative patterns
                alt_patterns = [
                    r"src:'([^']+)'",
                    r'"file":"([^"]+)"',
                    r"'file':'([^']+)'",
                    r'source:"([^"]+)"',
                    r"source:'([^']+)'"
                ]
                for pattern in alt_patterns:
                    alt_match = re.search(pattern, unpacked)
                    if alt_match:
                        src_match = alt_match
                        break
                else:
                    log.error("MAXSTREAM: src URL not found")
                    return None

            final_url = src_match.group(1)
            log.info("MAXSTREAM: Final URL extracted: {}".format(final_url))
            return final_url

        except Exception as e:
            log.error("MAXSTREAM: Error extracting URL: {}".format(e))
            return None

    def _unpack_script(self, packed_script):
        """Unpack the packed JavaScript script"""
        try:
            params_match = re.search(
                r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('([^']+)',(\d+),(\d+),'([^']+)'\.split\('\|'\)",
                packed_script)
            if not params_match:
                return None

            payload = params_match.group(1)
            base = int(params_match.group(2))
            count = int(params_match.group(3))
            keywords = params_match.group(4).split('|')

            result = payload

            for i in reversed(range(count)):
                if i < len(keywords) and keywords[i]:
                    if base > 10:
                        if i < base:
                            replacement = str(i) if i < 10 else chr(
                                ord('a') + i - 10)
                        else:
                            replacement = self._to_base(i, base)
                    else:
                        replacement = str(i)

                    pattern = r'\b' + re.escape(replacement) + r'\b'
                    result = re.sub(pattern, keywords[i], result)

            return result

        except Exception as e:
            log.error("MAXSTREAM: Error unpacking script: {}".format(e))
            return None

    def _to_base(self, num, base):
        """Convert a number to the specified base"""
        if num == 0:
            return "0"

        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        result = ""

        while num > 0:
            result = digits[num % base] + result
            num //= base

        return result

    def bypass_uprot(self, uprot_url, session=None, callback=None):
        """Bypass the uprot link with captcha handling"""
        try:
            log.info("MAXSTREAM_UPROT: ===== STARTING UPROT BYPASS =====")
            log.info("MAXSTREAM_UPROT: URL to bypass: {}".format(uprot_url))

            headers_copy = self.headers.copy()
            headers_copy['Referer'] = 'https://onlineserietv.com/'
            log.info("MAXSTREAM_UPROT: Headers: {}".format(headers_copy))

            req = urllib.request.Request(uprot_url, headers=headers_copy)

            phpsessid = None
            with urllib.request.urlopen(req, timeout=15) as response:
                log.info(
                    "MAXSTREAM_UPROT: Response status: {}".format(
                        response.getcode()))
                # Extract PHPSESSID from response cookies
                cookies_header = response.getheader('Set-Cookie')
                log.info(
                    "MAXSTREAM_UPROT: Set-Cookie header: {}".format(cookies_header))
                if cookies_header:
                    phpsessid_match = re.search(
                        r'PHPSESSID=([^;\s]+)', cookies_header)
                    if phpsessid_match:
                        phpsessid = phpsessid_match.group(1)
                        log.info(
                            "MAXSTREAM_UPROT: PHPSESSID extracted: {}".format(phpsessid))
                html = response.read().decode('utf-8')
                log.info(
                    "MAXSTREAM_UPROT: HTML received - Length: {}".format(len(html)))
                log.info(
                    "MAXSTREAM_UPROT: HTML (first 2000 chars): {}".format(html[:2000]))

            # Check for captcha
            captcha_pattern = r'data:image/[^;]+;base64,([A-Za-z0-9+/=]+)'
            captcha_match = re.search(captcha_pattern, html)
            log.info(
                "MAXSTREAM_UPROT: Captcha found: {}".format(
                    captcha_match is not None))
            if captcha_match:
                log.info(
                    "MAXSTREAM_UPROT: Captcha detected - requesting user interaction")
                captcha_data = "data:image/png;base64," + \
                    captcha_match.group(1)

                if session and callback:
                    self._handle_captcha_async(
                        session, captcha_data, uprot_url, html, callback, phpsessid)
                    return
                else:
                    log.error(
                        "MAXSTREAM: Session or callback not available for captcha")
                    return None

            # Look for MaxStream link in the page
            maxstream_pattern = r'https://maxstream\.video/[^"\s]+'
            maxstream_match = re.search(maxstream_pattern, html)
            log.info(
                "MAXSTREAM_UPROT: Searching for MaxStream URL with pattern: {}".format(maxstream_pattern))
            log.info(
                "MAXSTREAM_UPROT: MaxStream URL found: {}".format(
                    maxstream_match is not None))

            if maxstream_match:
                maxstream_url = maxstream_match.group(0)
                log.info(
                    "MAXSTREAM_UPROT: MaxStream URL extracted: {}".format(maxstream_url))
                log.info(
                    "MAXSTREAM_UPROT: ===== ENDING UPROT BYPASS (SUCCESS) =====")
                if callback:
                    callback(maxstream_url)
                else:
                    return maxstream_url
            else:
                log.error("MAXSTREAM_UPROT: MaxStream URL not found in page")
                log.info(
                    "MAXSTREAM_UPROT: ===== ENDING UPROT BYPASS (FAILED) =====")
                if callback:
                    callback(None)
                else:
                    return None

        except Exception as e:
            log.error("MAXSTREAM_UPROT: Error bypassing uprot: {}".format(e))
            import traceback
            log.error("MAXSTREAM_UPROT: Traceback: {}".format(traceback.format_exc()))
            log.info("MAXSTREAM_UPROT: ===== ENDING UPROT BYPASS (ERROR) =====")
            if callback:
                callback(None)
            return None

    def _handle_captcha_async(
            self,
            session,
            captcha_data,
            uprot_url,
            html,
            callback,
            phpsessid=None):
        """Handle captcha asynchronously with callback"""
        try:
            from threading import Thread
            log.info("MAXSTREAM: Opening captcha screen asynchronously")

            def submit_in_thread(captcha_code):
                """Run network operations in a separate thread to avoid blocking the UI."""
                log.info(
                    "MAXSTREAM: Starting captcha submit in thread with code: {}".format(captcha_code))
                maxstream_url = self._submit_captcha_and_retry(
                    uprot_url, captcha_code, html, phpsessid)
                log.info(
                    "MAXSTREAM: Captcha submit completed, MaxStream URL: {}".format(maxstream_url))

                if maxstream_url:
                    log.info(
                        "MAXSTREAM: Extracting video URL from: {}".format(maxstream_url))
                    video_url = self.extract(maxstream_url)
                    log.info(
                        "MAXSTREAM: Final video URL extracted: {}".format(video_url))
                    callback(video_url)
                else:
                    log.error(
                        "MAXSTREAM: No MaxStream URL obtained after submit")
                    callback(None)

            # Flag to ensure the process is executed only once
            submitted = False

            def captcha_callback(result=None):
                nonlocal submitted
                if submitted:
                    log.info(
                        "MAXSTREAM: Captcha callback ignored (already submitted)")
                    return

                log.info("MAXSTREAM: Captcha callback received: {}".format(result))
                if result:
                    submitted = True
                    # Start the submit process in a new thread
                    thread = Thread(target=submit_in_thread, args=(result,))
                    thread.start()
                else:
                    log.error(
                        "MAXSTREAM: Captcha cancelled or callback without result")
                    callback(None)

            # Open the captcha input screen with callback
            session.openWithCallback(
                captcha_callback,
                CaptchaInputScreen,
                captcha_data,
                captcha_callback)
        except Exception as e:
            log.error("MAXSTREAM: Error handling captcha asynchronously: {}".format(e))
            callback(None)

    def _submit_captcha_and_retry(
            self,
            uprot_url,
            captcha_code,
            original_html,
            phpsessid=None):
        """Submit captcha and retry the bypass"""
        try:
            log.info("MAXSTREAM: Submitting captcha: {}".format(captcha_code))

            # Look for the captcha form
            form_match = re.search(
                r'<form[^>]*>(.*?)</form>',
                original_html,
                re.DOTALL | re.IGNORECASE)
            if not form_match:
                log.error("MAXSTREAM: Captcha form not found")
                return None

            form_content = form_match.group(1)
            log.info("MAXSTREAM: Form found")

            # Look for the captcha field
            captcha_field = 'captcha'
            input_matches = re.findall(
                r'<input[^>]*name=["\']([^"\']*)["\'][^>]*>',
                form_content,
                re.IGNORECASE)
            for match in input_matches:
                if 'captcha' in match.lower():
                    captcha_field = match
                    break

            log.info("MAXSTREAM: Input field: {}".format(captcha_field))

            # Prepare form data with explicit Continue button
            form_data = {
                captcha_field: captcha_code,
                'submit': 'Continue'
            }

            # Look for submit button to include its data
            submit_match = re.search(
                r'<(?:input|button)[^>]*type=["\']submit["\'][^>]*>',
                form_content,
                re.IGNORECASE)
            if submit_match:
                submit_tag = submit_match.group(0)
                name_match = re.search(r'name=["\']([^"\']*)["\']', submit_tag)
                value_match = re.search(
                    r'value=["\']([^"\']*)["\']', submit_tag)
                if name_match and value_match:
                    form_data[name_match.group(1)] = value_match.group(1)

            # Cookie management
            import hashlib
            captcha_hash = hashlib.md5(captcha_code.encode()).hexdigest()

            # Read cf_clearance from config
            cf_clearance = None
            try:
                with open('/usr/lib/enigma2/python/Plugins/Extensions/scsearch/config.txt', 'r') as f:
                    for line in f:
                        if line.startswith('cf_clearance='):
                            cf_clearance = line.split('=', 1)[1].strip()
                            break
            except Exception:
                pass

            # Build cookies using the PHPSESSID passed as parameter
            cookies = ['uprot_session_px3=2']
            if phpsessid:
                cookies.append('PHPSESSID={}'.format(phpsessid))
            if cf_clearance:
                cookies.append('cf_clearance={}'.format(cf_clearance))
            cookies.append('captcha={}'.format(captcha_hash))

            cookie_string = '; '.join(cookies)
            log.info("MAXSTREAM: Cookies: {}".format(cookie_string))

            # Headers for submit
            submit_headers = self.headers.copy()
            submit_headers.update({
                'Content-Type': 'application/x-www-form-urlencoded',
                'Cookie': cookie_string,
                'Referer': uprot_url,
                'Origin': 'https://uprot.net'
            })

            # Encode form data
            encoded_data = urllib.parse.urlencode(form_data).encode('utf-8')

            # Send POST request
            req = urllib.request.Request(
                uprot_url, data=encoded_data, headers=submit_headers)

            with urllib.request.urlopen(req, timeout=15) as response:
                response_html = response.read().decode('utf-8')
                log.info(
                    "MAXSTREAM: Response received - Length: {}".format(len(response_html)))
                log.info("MAXSTREAM: ===== END OF COMPLETE HTML =====")

            # Look specifically for URL in ad_space div with button id="buttok"
            # Simplified pattern to find the correct URL
            buttok_pattern = r'<button[^>]*id=["\']buttok["\'][^>]*>.*?</button>'
            buttok_match = re.search(
                buttok_pattern,
                response_html,
                re.IGNORECASE | re.DOTALL)

            if buttok_match:
                # Look for URL in the area around the buttok button
                buttok_area = response_html[max(
                    0, buttok_match.start() - 200):buttok_match.end() + 200]
                url_pattern = r'href=["\']([^"\']+ maxstream\.video[^"\']+ )["\']'
                url_match = re.search(url_pattern, buttok_area, re.IGNORECASE)

                if url_match:
                    maxstream_url = url_match.group(1)
                    log.info(
                        "MAXSTREAM: URL found near buttok: {}".format(maxstream_url))
                    return maxstream_url

            # Look for all MaxStream URLs and take the one in the ad_space div
            all_maxstream_urls = re.findall(
                r'https://maxstream\.video/[^"\s<>]+',
                response_html,
                re.IGNORECASE)
            log.info(
                "MAXSTREAM: Found {} total MaxStream URLs".format(
                    len(all_maxstream_urls)))

            # Look for the ad_space div
            ad_space_match = re.search(
                r'<div[^>]*id=["\']аd_spаce["\'][^>]*>(.*?)</div>',
                response_html,
                re.IGNORECASE | re.DOTALL)

            if ad_space_match and all_maxstream_urls:
                ad_space_content = ad_space_match.group(1)
                # Look for MaxStream URL in the ad_space div content
                for url in all_maxstream_urls:
                    if url in ad_space_content:
                        log.info(
                            "MAXSTREAM: URL found in ad_space div: {}".format(url))
                        return url

            # If nothing found, use the first MaxStream URL
            if all_maxstream_urls:
                maxstream_url = all_maxstream_urls[0]
                log.info(
                    "MAXSTREAM: URL found with fallback (first available): {}".format(maxstream_url))
                return maxstream_url

            log.error("MAXSTREAM: No MaxStream URL found")
            return None

        except Exception as e:
            log.error("MAXSTREAM: Error submitting captcha: {}".format(e))
            return None

    def _download(self, url):
        """Download webpage content"""
        try:
            log.info("MAXSTREAM: Downloading page: {}".format(url))
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read().decode('utf-8', errors='ignore')
                log.info(
                    "MAXSTREAM: Content downloaded - Length: {}".format(len(content)))
                return content
        except Exception as e:
            log.error("MAXSTREAM: Download error: {}".format(e))
            return ""

    def _find_match(self, data, pattern):
        """Find regex match"""
        try:
            match = re.search(pattern, data, re.DOTALL | re.IGNORECASE)
            result = match.group(1) if match else ""
            if result:
                log.info("MAXSTREAM: Pattern found: {}...".format(pattern[:50]))
            return result
        except Exception as e:
            log.error("MAXSTREAM: Pattern search error: {}".format(e))
            return ""

    def _get_best_quality(self, m3u8_url):
        """Select highest quality from HLS manifest"""
        try:
            log.info("MAXSTREAM: Analyzing M3U8 manifest: {}".format(m3u8_url))
            manifest = self._download(m3u8_url)
            if not manifest:
                log.warning("MAXSTREAM: Empty manifest, using original URL")
                return m3u8_url

            streams = []
            lines = manifest.split('\n')

            for i, line in enumerate(lines):
                if 'EXT-X-STREAM-INF' in line and 'BANDWIDTH=' in line:
                    bandwidth_match = re.search(r'BANDWIDTH=(\d+)', line)
                    if bandwidth_match and i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if next_line and not next_line.startswith('#'):
                            bandwidth = int(bandwidth_match.group(1))
                            streams.append({
                                'bandwidth': bandwidth,
                                'url': next_line
                            })
                            log.info(
                                "MAXSTREAM: Stream found - Bandwidth: {}".format(bandwidth))

            if streams:
                best = max(streams, key=lambda x: x['bandwidth'])
                log.info(
                    "MAXSTREAM: Best quality selected - Bandwidth: {}".format(best['bandwidth']))
                return best['url']

            log.warning("MAXSTREAM: No streams found, using original URL")
            return m3u8_url

        except Exception as e:
            log.error("MAXSTREAM: Error analyzing M3U8: {}".format(e))
            return m3u8_url

    def extract_video_url(self, url):
        """Extract video URL from maxstream page"""
        try:
            log.info("MAXSTREAM: Starting video extraction from: {}".format(url))

            # First GET request to get Location header
            headers_copy = self.headers.copy()
            headers_copy['Referer'] = 'https://uprot.net/'
            headers_copy['Cookie'] = '_ga=GA1.1.1699191900.1758982925; _ga_PXCHK654EC=GS2.1.s1758985666$o2$g0$t1758985666$j60$l0$h0; prefetchAd_5867823=true; dw=1'

            class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                def redirect_request(
                        self, req, fp, code, msg, headers, newurl):
                    return None

            opener = urllib.request.build_opener(NoRedirectHandler)
            req = urllib.request.Request(url, headers=headers_copy)

            try:
                response = opener.open(req, timeout=15)
                log.info("MAXSTREAM: No redirect found: {}".format(response))
                return None
            except urllib.error.HTTPError as e:
                if e.code in [301, 302, 303, 307, 308]:
                    location = e.headers.get('Location')
                    if location:
                        log.info(
                            "MAXSTREAM: Location header found: {}".format(location))

                        # GET request with browser headers for the Location URL
                        browser_headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                            'Accept-Language': 'it-IT,it;q=0.9',
                            'Cache-Control': 'no-cache',
                            'DNT': '1'}
                        req2 = urllib.request.Request(
                            location, headers=browser_headers)
                        with urllib.request.urlopen(req2, timeout=15) as response2:
                            html = response2.read().decode('utf-8', errors='ignore')
                            log.info(
                                "MAXSTREAM: Location page downloaded - Length: {}".format(len(html)))

                        # Decode obfuscated script in the Location page
                        log.info(
                            "MAXSTREAM: Attempting to decode obfuscated script in Location page")
                        decoded_url = self._decode_obfuscated_script(html)
                        if decoded_url:
                            return decoded_url

                        # Look for iframe in the page as fallback
                        iframe_match = re.search(
                            r'<iframe[^>]+src=["\']([^"\']+ )["\']', html, re.IGNORECASE)
                        if not iframe_match:
                            iframe_match = re.search(
                                r'src=["\']([^"\']+ maxstream\.video[^"\']+ )["\']', html, re.IGNORECASE)

                        if iframe_match:
                            iframe_url = iframe_match.group(1)
                            log.info("MAXSTREAM: Iframe found: {}".format(iframe_url))

                            # Download iframe content
                            req3 = urllib.request.Request(
                                iframe_url, headers=headers_copy)
                            with urllib.request.urlopen(req3, timeout=15) as response3:
                                iframe_html = response3.read().decode('utf-8')
                                log.info(
                                    "MAXSTREAM: Iframe HTML downloaded - Length: {}".format(len(iframe_html)))

                            # Decode obfuscated script in the iframe
                            iframe_decoded_url = self._decode_obfuscated_script(
                                iframe_html)
                            if iframe_decoded_url:
                                return iframe_decoded_url
                        else:
                            log.error(
                                "MAXSTREAM: No iframe found in Location page")
                            log.info(
                                "MAXSTREAM: First 1000 chars for debug: {}".format(html[:1000]))
                    else:
                        log.error(
                            "MAXSTREAM: Redirect without Location header")
                        return None
                else:
                    log.error("MAXSTREAM: HTTP error {}".format(e.code))
                    return None

            log.error("MAXSTREAM: No video URL found")
            return None

        except Exception as e:
            log.error("MAXSTREAM: Error extracting video: {}".format(e))
            return None

    def _decode_obfuscated_script(self, html):
        """Decode the obfuscated JavaScript script from the log pattern"""
        try:
            # Pattern for the obfuscated script from the log
            script_pattern = r'\(\(\)=>\{var K=\'([^\']+ )\'[^}]+ \}\)\(\)'
            script_match = re.search(script_pattern, html)

            if not script_match:
                log.info("MAXSTREAM: Obfuscated script not found")
                return None

            obfuscated_string = script_match.group(1)
            log.info(
                "MAXSTREAM: Obfuscated string found: {}...".format(obfuscated_string[:100]))

            # Decode according to the pattern from the log
            # split("").reduce((v,g,L)=>L%2?v+g:g+v).split("z")
            chars = list(obfuscated_string)
            decoded_chars = []

            # Apply reduce logic: L%2?v+g:g+v
            for i, char in enumerate(chars):
                if i % 2 == 1:  # L%2 is true (odd)
                    decoded_chars.append(char)  # v+g
                else:  # L%2 is false (even)
                    decoded_chars.insert(0, char)  # g+v

            decoded_string = ''.join(decoded_chars)
            parts = decoded_string.split('z')

            log.info("MAXSTREAM: Decoded parts: {}".format(len(parts)))

            # Reconstruct JavaScript code from parts
            js_code = ''.join(parts)
            log.info(
                "MAXSTREAM: Decoded JS code (first 500 chars): {}".format(js_code[:500]))

            # Look for video URL in the decoded code
            video_patterns = [
                r'src["\']?:\s*["\']([^"\']+ \.(?:mp4|m3u8|webm))["\']',
                r'file["\']?:\s*["\']([^"\']+ \.(?:mp4|m3u8|webm))["\']',
                r'source["\']?:\s*["\']([^"\']+ \.(?:mp4|m3u8|webm))["\']',
                r'(https?://[^\s"\']+ \.(?:mp4|m3u8|webm))'
            ]

            for i, pattern in enumerate(video_patterns, 1):
                log.info("MAXSTREAM: Testing decode pattern {}: {}".format(i, pattern))
                match = re.search(pattern, js_code, re.IGNORECASE)
                if match:
                    video_url = match.group(1)
                    log.info(
                        "MAXSTREAM: Video URL found with decoding: {}".format(video_url))
                    if '.m3u8' in video_url:
                        return self._get_best_quality(video_url)
                    return video_url
                else:
                    log.info("MAXSTREAM: Decode pattern {} did not match".format(i))

            return None

        except Exception as e:
            log.error("MAXSTREAM: Error decoding obfuscated script: {}".format(e))
            return None


def get_video_url(url):
    """Main function for Enigma2 compatibility"""
    extractor = MaxStreamExtractor()
    return extractor.extract_video_url(url)
