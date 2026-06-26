from Plugins.Plugin import PluginDescriptor


def main(session, **kwargs):
    # Initialize logger first
    try:
        from .logger import setup_logger, get_log_path
        logger = setup_logger()
        log_path = get_log_path()
        print("[SC Search] Plugin started - Log: %s" % log_path)
        if logger:
            logger.info("Plugin main() called")
    except Exception as e:
        print("[SC Search] Logger init failed: %s" % e)

    # Open main screen
    from . import scbrowse
    session.open(scbrowse.SCBrowseMain)


def Plugins(**kwargs):
    return [PluginDescriptor(
        name="SC Search",
        description="Search for anything on your Enigma2 box",
        where=[PluginDescriptor.WHERE_PLUGINMENU],
        icon="sc_search.png",
        fnc=main
    )]
