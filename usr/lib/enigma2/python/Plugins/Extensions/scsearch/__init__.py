# -*- coding: utf-8 -*-

from __future__ import absolute_import
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from Components.Language import language
import gettext
import os
import traceback

__license__ = "GPL-2.0"
__version__ = "1.27"

# Domain and path for translation files
PluginLanguageDomain = "scsearch"
PluginLanguagePath = os.path.join("Extensions", "scsearch", "locale")


def locale_init():
    """Initialize gettext with the current system language."""
    lang = language.getLanguage()[:2]  # e.g. "en", "it"
    os.environ["LANGUAGE"] = lang
    gettext.bindtextdomain(
        PluginLanguageDomain,
        resolveFilename(SCOPE_PLUGINS, PluginLanguagePath)
    )


def _(txt):
    """Translate the given text using the plugin's domain."""
    return gettext.dgettext(PluginLanguageDomain, txt) if txt else ""


# Apply initialisation and register callback for language changes
locale_init()
language.addCallback(locale_init)


PLUGIN_PATH = "/usr/lib/enigma2/python/Plugins/Extensions/scsearch"


def get_screen_resolution():
    """Get the current screen resolution."""
    print("[scsearch DEBUG] get_screen_resolution START")
    from enigma import getDesktop
    try:
        s = getDesktop(0).size()
        width, height = s.width(), s.height()
        print("[scsearch DEBUG] Resolution: {}x{}".format(width, height))
        return (width, height)
    except Exception as e:
        print("[scsearch DEBUG] get_screen_resolution ERROR: {}".format(e))
        return (1920, 1080)


def get_resolution_type():
    """Determine the resolution type based on screen width."""
    print("[scsearch DEBUG] get_resolution_type START")
    try:
        width = get_screen_resolution()[0]
        if width >= 3840:
            res = "uhd"
        elif width >= 2560:
            res = "wqhd"
        elif width >= 1920:
            res = "fhd"
        elif width >= 1280:
            res = "hd"
        else:
            res = "sd"
        print("[scsearch DEBUG] Resolution type: {}".format(res))
        return res
    except Exception as e:
        print("[scsearch DEBUG] get_resolution_type ERROR: {}".format(e))
        return "hd"


def load_skin(screen_name):
    """Load a skin file for the given screen name based on current resolution."""
    print("[scsearch DEBUG] load_skin START: {}".format(screen_name))
    try:
        res = get_resolution_type()
        skin_path = "{}/skins/{}/{}.xml".format(PLUGIN_PATH, res, screen_name)
        print("[scsearch DEBUG] Looking for skin: {}".format(skin_path))

        if not os.path.exists(skin_path):
            skin_path = "{}/skins/hd/{}.xml".format(PLUGIN_PATH, screen_name)
            print("[scsearch DEBUG] Fallback to: {}".format(skin_path))

        if os.path.exists(skin_path):
            with open(skin_path, "r") as f:
                content = f.read()
                print(
                    "[scsearch DEBUG] Skin loaded, size: {} bytes".format(
                        len(content)))
                return content
        else:
            print("[scsearch DEBUG] Skin file NOT FOUND")
            return None
    except Exception as e:
        print("[scsearch DEBUG] load_skin ERROR: {}".format(e))
        print("[scsearch DEBUG] Traceback: {}".format(traceback.format_exc()))
        return None
