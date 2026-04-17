import logging
logger = logging.getLogger(__name__)

import json, os, shutil

from YTCM_config import (CACHE_FILE, COMMENTS_FOLDER,
                         COMMENTS_JSON, COMMENTS_HTML, COMMENTS_GEXF_ON, COMMENTS_GEXF_OFF, COMMENTS_CSV)

def prepare_output_directory(directory):
    """
    Create the output folder if necessary.
    Self-explanatory.
    """

    try:
        if not os.path.exists(directory):
            os.makedirs(directory)
    except Exception as e:
        logger.error(f"Error creating output directory '{directory}': {e}.")


def load_existing_comments(filename):
    """
    If there is a JSON with prior search results, load it.
    If not, return an empty dict.
    Self-explanatory.
    """

    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON format error reading from '{filename}': {e}.")
        except Exception as e:
            logger.error(f"Unexpected error reading from '{filename}': {e}.")
    else:
        logger.info(f"File '{filename}' does not exist. Starting with an empty collection.")
    return {}


def delete_all_files():
    files_to_delete = [
        CACHE_FILE,
        COMMENTS_JSON,
        COMMENTS_HTML,
        COMMENTS_GEXF_ON,
        COMMENTS_GEXF_OFF,
        COMMENTS_CSV
    ]

    for filepath in files_to_delete:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"{filepath} deleted.")
        except Exception as e:
            logger.error(f"Failed to delete {filepath}: {e}.")

    try:
        if os.path.isdir(COMMENTS_FOLDER):
            shutil.rmtree(COMMENTS_FOLDER)
            logger.info(f"{COMMENTS_FOLDER} and all files in it deleted.")
    except Exception as e:
        logger.error(f"Failed to delete {COMMENTS_FOLDER}: {e}.")
