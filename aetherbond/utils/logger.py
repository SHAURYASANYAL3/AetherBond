"""
Terminal Logging and ANSI Styling for AetherBond
"""

import logging
import sys

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
RESET = "\033[0m"


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        level_color = {
            logging.DEBUG: "\033[90m",
            logging.INFO: CYAN,
            logging.WARNING: YELLOW,
            logging.ERROR: RED,
            logging.CRITICAL: RED + BOLD,
        }.get(record.levelno, RESET)

        prefix = f"{BOLD}[AetherBond]{RESET} {level_color}{record.levelname:<5}{RESET}"
        return f"{prefix} {record.getMessage()}"


def setup_logger(level=logging.INFO):
    logger = logging.getLogger("aetherbond")
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter())
    logger.handlers = [handler]
    return logger
