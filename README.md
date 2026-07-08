# 🚀 SC Search

**SC Search** is a powerful search and streaming plugin for **Enigma2** receivers.  
It allows you to search, browse, and play movies and TV series from multiple streaming sources directly on your Enigma2 device.

<p align="center">
  <a href="https://www.gnu.org/licenses/gpl-3.0">
    <img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="License">
  </a>

  <a href="https://www.python.org">
    <img src="https://img.shields.io/badge/Python-3.x-blue.svg" alt="Python">
  </a>

  <a href="https://www.opendreambox.org/">
    <img src="https://img.shields.io/badge/Enigma2-Compatible-green.svg" alt="Enigma2">
  </a>
</p>

<p align="center">
  <a href="https://github.com/Belfagor2005">
    <img src="https://komarev.com/ghpvc/?username=Belfagor2005&label=Repository%20Views&color=blueviolet" alt="Visitors">
  </a>
</p>

<p align="center">
  <a href="https://ko-fi.com/lululla">
    <img src="https://img.shields.io/badge/_-Donate-red.svg?logo=githubsponsors&labelColor=555555&style=for-the-badge" alt="Ko-fi">
  </a>

  <a href="https://paypal.me/belfagor2005">
    <img src="https://img.shields.io/badge/_-Donate-green.svg?logo=githubsponsors&labelColor=555555&style=for-the-badge" alt="PayPal">
  </a>
</p>

---

## 📖 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Supported Sources](#-supported-sources)
- [How It Works](#-how-it-works)
- [Installation](#-installation)
- [Usage](#-usage)
- [Configuration](#-configuration)
- [Project Structure](#-project-structure)
- [Requirements](#-requirements)
- [License](#-license)
- [Disclaimer](#-disclaimer)

---

## ℹ️ Overview

**SC Search** transforms your Enigma2 receiver into a comprehensive streaming search engine.  
Instead of manually navigating multiple websites, you can search for movies and TV series from a single interface.

The plugin integrates with:

- **StreamingCommunity** – One of the largest Italian streaming databases
- **CB01** – Popular Italian streaming platform (movies and TV series)
- **Altadefinizione** – Italian streaming platform (movies and TV series)
- **OnlineSerieTV** – Italian TV series platform (requires Cloudflare cookie)

All searches are unified, and results are displayed in a clean, user-friendly interface.

---

## ✨ Features

- **Unified Search** – Search once across multiple sources
- **Smart Filtering** – Results filtered by type (Movie / TV Series)
- **Search History** – Automatic saving of your searches (movie & TV separately)
- **Poster Display** – Movie and TV series posters fetched from TMDB
- **TMDB Integration** – Full metadata, descriptions, ratings, and genres
- **Multi-Source Playback** – Stream from:
  - StreamingCommunity (via vixsrc.to)
  - CB01 (via Mixdrop / Maxstream / Uprot)
  - Altadefinizione (via vixsrc.to)
  - OnlineSerieTV (via Maxstream)
- **Captcha Support** – Automatic handling of Cloudflare and custom captchas
- **Carousel Browse** – Browse categories like "Top 10", "Trending", "Latest", and genres
- **Local Caching** – Posters and metadata cached for faster loading
- **Full English Localization** – All UI strings in English with translation support
- **EPG Integration** – Extended service information for streaming

---

## 🌐 Supported Sources

| Source | Movies | TV Series | Links | Playback |
|--------|--------|-----------|-------|----------|
| **StreamingCommunity** | ✅ | ✅ | vixsrc.to | ✅ |
| **CB01** | ✅ | ✅ | Mixdrop / Maxstream / Uprot | ✅ |
| **Altadefinizione** | ✅ | ✅ | vixsrc.to | ✅ |
| **OnlineSerieTV** | ❌ | ✅ | Maxstream | ✅ |

---

## 🔧 How It Works

### 1. Search Flow

1. User enters a search term (or uses history).
2. Plugin queries multiple sources in parallel:
   - StreamingCommunity (via TMDB API)
   - CB01 (via web scraping)
   - Altadefinizione (via web scraping)
   - OnlineSerieTV (via web scraping with cookie)
3. Results are filtered by type (Movie / TV Series).
4. Results are displayed in a list with posters and metadata.

### 2. Details View

- Selecting a result opens the **Details Screen**.
- If the content is from **StreamingCommunity** or **Altadefinizione**:
  - Full TMDB metadata is displayed (title, year, description, rating, genres).
  - For TV series, seasons and episodes are shown.
  - Press **GREEN** to play.
- If the content is from **CB01**:
  - Parsed streaming links (Mixdrop, Maxstream, Uprot) are displayed.
  - Select quality and press **GREEN** to play.
- If the content is from **OnlineSerieTV**:
  - Seasons and episodes are displayed.
  - Press **GREEN** to start the extraction process.
  - Captcha handling is automatic when required.

### 3. Playback

- **StreamingCommunity / Altadefinizione**:  
  Uses `vixsrc.to` to generate an M3U8 URL.
- **CB01**:  
  Resolves `stayonline.pro` links to Mixdrop/Maxstream/Uprot URLs.
- **OnlineSerieTV**:  
  Bypasses `uprot.net` links, handles captchas, and extracts Maxstream URLs.

All playback uses Enigma2's built-in `MoviePlayer`.

---

## 📦 Installation

### ZIP Installation

1. Extract the archive to the decoder root filesystem:
   ```bash
   unzip enigma2-plugin-extensions-scsearch.zip -d /
   ```
2. Restart Enigma2:
   ```bash
   init 4 && init 3
   ```

### IPK Installation

```bash
opkg install enigma2-plugin-extensions-scsearch_all.ipk
```

### Manual Installation

```bash
cp -r scsearch /usr/lib/enigma2/python/Plugins/Extensions/
chmod -R 755 /usr/lib/enigma2/python/Plugins/Extensions/scsearch
```

---

## 🎮 Usage

### Main Menu

- **GREEN** – Search Movies
- **YELLOW** – Search TV Series
- **BLUE** – Search History
- **RED** / **EXIT** – Close plugin

### Browsing Categories

From the main screen, you can browse categories:

- **Top 10 di oggi** – Today's most popular content
- **I Titoli Del Momento** – Trending titles
- **Aggiunti di Recente** – Recently added
- **Genres** – Action, Comedy, Drama, Horror, etc.

Navigation:
- **UP/DOWN** – Select category
- **RIGHT/LEFT** – Scroll through carousel
- **OK** – Open details

### Search

1. Press **GREEN** (Movies) or **YELLOW** (TV Series).
2. Enter a search term using the virtual keyboard.
3. Results are displayed on the left panel.
4. Select a result to view details on the right panel.
5. Press **OK** to open the full details screen.
6. Press **GREEN** to play the content.

---

## ⚙️ Configuration

### Config File (`config.txt`)

The plugin uses a `config.txt` file located in the plugin directory.

```ini
# SC Search Plugin Configuration
STREAMING_COMMUNITY_URL=https://streamingcommunityz.organic/
CB01_URL=https://cb01uno.pics/
CB01_URL_FALLBACK=https://
ALTADEFINIZIONE_URL=https://altadefinizione.you/
ALTADEFINIZIONE_URL_FALLBACK=https://altadefinizione.you/
REQUEST_TIMEOUT=30
USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
LOG_ENABLED=true
LOG_LEVEL=INFO
LOG_MAX_SIZE=1048576
LOG_BACKUP_COUNT=3
TMDB_API_KEY=your_api_key_here
CookieOLSTV=your_cloudflare_cookie_here
MOVIE_HISTORY=
TV_HISTORY=
```

### TMDB API Key

You need a **TMDB API key** to use the plugin.

1. Register at [TMDB](https://www.themoviedb.org/signup).
2. Request an API key from your account settings.
3. Add the key to `config.txt`:
   ```
   TMDB_API_KEY=your_api_key_here
   ```

### OnlineSerieTV Cookie

For OnlineSerieTV to work, you need a Cloudflare bypass cookie:

1. Open `https://onlineserietv.com` in a browser.
2. Open Developer Tools (`F12`) → **Network** tab.
3. Look for a request to `onlineserietv.com`.
4. Copy the `Cookie` header value.
5. Add it to `config.txt`:
   ```
   CookieOLSTV=your_cookie_here
   ```

---

## 📂 Project Structure

```
scsearch/
├── __init__.py               # Localization, translation, e carica le skin
├── plugin.py                 # Plugin entry point
├── scsearch.py               # Main search UI (ora usa load_skin)
├── scbrowse.py               # Category browser UI (ora usa load_skin)
├── scdetails.py              # Details & playback UI (ora usa load_skin)
├── search_functions.py       # Multi-source search logic
├── cb01.py                   # CB01 extraction
├── altadefinizione.py        # Altadefinizione extraction
├── onlineserietv.py          # OnlineSerieTV extraction
├── TmdbFetcher.py            # TMDB API integration
├── logger.py                 # Logging system
├── poster_carousel.py        # Carousel GUI component
├── components.py             # GUI components
├── maxstream_extractor.py    # Maxstream URL extraction
├── mixdrop_extractor.py      # Mixdrop URL extraction
├── captcha_input.py          # Captcha input screen (ora usa load_skin)
├── captcha_screen.py         # Captcha screen (ora usa load_skin)
├── config.txt                # User configuration
├── locale/                   # Translation files
│   ├── en/
│   │   └── LC_MESSAGES/
│   │       └── scsearch.mo
│   └── it/
│       └── LC_MESSAGES/
│           └── scsearch.mo
└── skins/                    # 🆕 NUOVA CARTELLA PER LE SKIN
    ├── hd/                   # 1280x720
    │   ├── SCSearchMain.xml
    │   ├── SCBrowseMain.xml
    │   ├── SCDetailsScreen.xml
    │   ├── CaptchaInputScreen.xml
    │   └── CaptchaScreen.xml
    ├── wqhd/                 # 2560x1440
    │   ├── SCSearchMain.xml
    │   ├── SCBrowseMain.xml
    │   ├── SCDetailsScreen.xml
    │   ├── CaptchaInputScreen.xml
    │   └── CaptchaScreen.xml
    ├── fhd/                  # 1920x1080
    │   ├── SCSearchMain.xml
    │   ├── SCBrowseMain.xml
    │   ├── SCDetailsScreen.xml
    │   ├── CaptchaInputScreen.xml
    │   └── CaptchaScreen.xml
    ├── uhd/                  # 3840x2160
    │   ├── SCSearchMain.xml
    │   ├── SCBrowseMain.xml
    │   ├── SCDetailsScreen.xml
    │   ├── CaptchaInputScreen.xml
    │   └── CaptchaScreen.xml
    └── sd/                   # 720x576
        ├── SCSearchMain.xml
        ├── SCBrowseMain.xml
        ├── SCDetailsScreen.xml
        ├── CaptchaInputScreen.xml
        └── CaptchaScreen.xml
```

---

## 📋 Requirements

- **Enigma2** receiver (DreamOS, OpenATV, OpenPLi, etc.)
- **Python 3.x**
- **Python packages**:
  - `requests`
  - `beautifulsoup4`
  - `html5lib`
  - `pycryptodome` (for decryption)
- **Optional**:
  - `Pillow` (for image conversion)
  - `ffmpeg` (for WebP conversion)

---

## 🛠️ Development

### Linting

The project uses `pylama` for code quality checks:

```bash
pylama --max-line-length=800 --ignore=E722,W605,C901,W293 scsearch/
```

### Translation

To update translation files:

```bash
cd scsearch
xgettext -o locale/scsearch.pot *.py
msgmerge -U locale/it/LC_MESSAGES/scsearch.po locale/scsearch.pot
msgfmt locale/it/LC_MESSAGES/scsearch.po -o locale/it/LC_MESSAGES/scsearch.mo
```

---

## 📜 License

```
This plugin is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.

This plugin is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.
```

![GPLv3 Logo](https://www.gnu.org/graphics/gplv3-127x51.png)

---

## ⚠️ Disclaimer

> **IMPORTANT**: The author of this plugin is not responsible for how this software is used.  
> It is not intended for accessing or distributing copyrighted materials without authorization.  
> Users are solely responsible for ensuring compliance with all applicable laws in their jurisdiction.

- The plugin does **not** host or store any content.
- All streams are provided by third-party sources.
- The plugin merely indexes and organizes publicly available information.
- Users should verify the legality of content before accessing it.

---

## 🌟 Support

If you find this plugin useful, please consider:

- ⭐ **Starring** the repository on GitHub
- 🐛 **Reporting issues** with detailed logs
- 💡 **Suggesting improvements** or new features

---

## 👥 Credits

- **Developer**: SC Search Team
- **TMDB**: The Movie Database for metadata and poster images
- **Enigma2 Community**: For the amazing open-source platform

---

## 📞 Contact

For questions, bug reports, or suggestions:

- **GitHub Issues**: [https://github.com/OwnerPlugins/scsearch/issues](https://github.com/OwnerPlugins/scsearch/issues)
- **Email**: scsearch@example.com

---

*Made with ❤️ for the Enigma2 community*

```text
Target path: /usr/lib/enigma2/python/Plugins/Extensions/scsearch
```

---

# 📚 Changelog

## v1.24 – 2026-06-26
- Full English localization
- Added Altadefinizione support
- Improved OnlineSerieTV captcha handling
- Fixed linting errors (E741, E731)
- TMDB integration improvements
- Search history enhancements
```
