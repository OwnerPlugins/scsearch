# -*- coding: utf-8 -*-

from __future__ import absolute_import
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from Components.Language import language
import gettext
import os

__license__ = "GPL-2.0"
__version__ = "1.0_beta"

# Domain and path for translation files
PLUGIN_DOMAIN = "scsearch"
PLUGIN_LOCALE_PATH = os.path.join("Extensions", "scsearch", "locale")


def locale_init():
    """Initialize gettext with the current system language."""
    lang = language.getLanguage()[:2]  # e.g. "en", "it"
    os.environ["LANGUAGE"] = lang
    gettext.bindtextdomain(
        PLUGIN_DOMAIN,
        resolveFilename(SCOPE_PLUGINS, PLUGIN_LOCALE_PATH)
    )


def _(txt):
    """Translate the given text using the plugin's domain."""
    return gettext.dgettext(PLUGIN_DOMAIN, txt) if txt else ""


# Apply initialisation and register callback for language changes
locale_init()
language.addCallback(locale_init)
