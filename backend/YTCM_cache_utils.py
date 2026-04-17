import logging
logger = logging.getLogger(__name__)

import json, os

from YTCM_config       import CACHE_FILE, CACHING
from YTCM_helper_utils import safe_write_json

def load_channel_data_cache(filename=CACHE_FILE):
    """
    Load the current cache version if it already exists.
    Self-explanatory.
    """

    if not CACHING:
        return {}

    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Error: JSON data in cache file '{filename}' is corrupt: {e}.")
        except Exception as e:
            logger.error(f"Unexpected error loading data from cache file '{filename}': {e}.")
    else:
        logger.warning(f"Cache file '{filename}' does not exist. Building a new cache.")
    return {}


def save_channel_data_cache(cache, filename=CACHE_FILE):
    """
    Save the current cache version.
    Self-explanatory.
    """

    if not CACHING:
        return

    safe_write_json(cache, filename)
