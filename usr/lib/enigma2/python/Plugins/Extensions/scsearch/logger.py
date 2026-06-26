import os
import logging
import logging.handlers

# --- Configuration ---
LOG_FILE_NAME = "scLog.txt"

# --- Global State ---
_global_logger = None
_log_path = None
_log_config = {
    "enabled": True,
    "level": logging.INFO,
    "max_size": 1048576,  # 1 MB
    "backup_count": 1
}


def _resolve_log_path():
    """Find a writable directory for the log file, with guaranteed fallback."""
    plugin_dir = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        plugin_dir,
        "/tmp",
        "/var/volatile/tmp",
        "/home/root",
    ]

    for log_dir in candidates:
        try:
            # Ensure directory exists
            if not os.path.exists(log_dir):
                try:
                    os.makedirs(log_dir, mode=0o755)
                except Exception:
                    continue

            # Test write permission
            test_path = os.path.join(log_dir, ".scsearch_test")
            with open(test_path, "w") as f:
                f.write("test")
            os.remove(test_path)

            # Writable directory found
            log_path = os.path.join(log_dir, LOG_FILE_NAME)
            # Use print here because logger is not yet initialized
            print("[SCLogger] Log path resolved: %s" % log_path)
            return log_path

        except Exception as e:
            print("[SCLogger] Cannot write to %s: %s" % (log_dir, e))
            continue

    # Absolute fallback: /tmp (should always work)
    fallback = os.path.join("/tmp", LOG_FILE_NAME)
    print("[SCLogger] Using fallback: %s" % fallback)
    return fallback


def _clear_old_logs(log_path, backup_count):
    """Remove main log file and its backups."""
    try:
        if os.path.exists(log_path):
            os.remove(log_path)
            print("[SCLogger] Removed old log: %s" % log_path)

        for i in range(1, backup_count + 1):
            backup_file = "%s.%d" % (log_path, i)
            if os.path.exists(backup_file):
                os.remove(backup_file)
                print("[SCLogger] Removed backup: %s" % backup_file)

    except Exception as e:
        print("[SCLogger] Error clearing logs: %s" % e)


def setup_logger(name="scsearch"):
    """Initialize the logger, clearing previous log files."""
    global _global_logger, _log_path

    if not _log_config["enabled"]:
        print("[SCLogger] Logging disabled")
        return None

    # Resolve log path
    _log_path = _resolve_log_path()

    # Clear old logs
    _clear_old_logs(_log_path, _log_config["backup_count"])

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(_log_config["level"])

    # Remove existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    try:
        # Create rotating file handler
        handler = logging.handlers.RotatingFileHandler(
            _log_path,
            maxBytes=_log_config["max_size"],
            backupCount=_log_config["backup_count"],
            encoding="utf-8"
        )

        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # Write header
        logger.info("=" * 80)
        logger.info("SC SEARCH PLUGIN STARTED")
        logger.info("Log file: %s" % _log_path)
        logger.info("=" * 80)

        # Now logger is ready, but keep print for console visibility
        print("[SCLogger] Logger initialized: %s" % _log_path)

    except Exception as e:
        print("[SCLogger] CRITICAL: Cannot create file handler: %s" % e)
        # Fallback: console logging
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
        logger.addHandler(console_handler)
        logger.error("File logging failed, using console: %s" % e)

    _global_logger = logger
    return _global_logger


def get_logger(name="scsearch"):
    """Get the global logger, initializing it if necessary."""
    if _global_logger is None:
        return setup_logger(name)
    return _global_logger


def get_log_path():
    """Return the path of the log file."""
    return _log_path


def configure_logging(config_dict):
    """Configure logging from a configuration dictionary."""
    _log_config["enabled"] = config_dict.get("LOG_ENABLED", "true").lower() == "true"
    level_str = config_dict.get("LOG_LEVEL", "INFO").upper()
    _log_config["level"] = getattr(logging, level_str, logging.INFO)
    _log_config["max_size"] = int(config_dict.get("LOG_MAX_SIZE", "1048576"))
    _log_config["backup_count"] = int(config_dict.get("LOG_BACKUP_COUNT", "1"))

    if _global_logger is not None:
        setup_logger()
