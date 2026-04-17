import logging
logger = logging.getLogger(__name__)

from googleapiclient.errors import HttpError
from YTCM_cache_utils       import load_channel_data_cache, save_channel_data_cache
from YTCM_config            import CACHING


def get_channel_data(youtube, channel_id):
    """
    Load channel information data.
    """
    
    # Read cache
    if CACHING:
        channel_data_cache = load_channel_data_cache()
    else:
        channel_data_cache = {}

    # Look up channel ID in cache. If it exists, return the existing information.
    if CACHING and channel_id in channel_data_cache:
        return channel_data_cache[channel_id]
    
    # Request channel ID data from the API.
    # "snippet" includes general metadata, including the channel title,
    # "statistics" includes further metadata, including subscriber and likes count.
    # "response" is a list of nested dictionaries. If you download just one, it is stored in [0].
    # The "snippet" and "statistics" info are stored in response["items"][0] with these two keys as we're only asking for one ID each time.
    # This data is extracted to "snippet" and "statistics".
    try:
        response = youtube.channels().list(
            id   = channel_id,
            part = "snippet,statistics"
        ).execute()
    
        if "items" not in response or len(response["items"]) == 0:
            logger.warning(f"No data found for channel ID {channel_id}.")
            return {
                "author_name"       : "Unknown",
                "author_channel_id" : channel_id,
                "author_subscribers": 0
            }

        snippet      = response["items"][0].get("snippet", {})
        statistics   = response["items"][0].get("statistics", {})

        # Extract data from the API response and store it in channel_data dictionary.
        # There used to be a likeCount entry earlier:
        # "author_likes"      : statistics.get("likeCount", 0)
        # However, the API no longer offers that value.

        channel_data = {
            "author_name"       : snippet.get("title", "N/A"),
            "author_channel_id" : channel_id,
            "author_subscribers": statistics.get("subscriberCount", 0)      # default to 0 if missing
        }

        # Update cache
        if CACHING:
            channel_data_cache[channel_id] = channel_data
            save_channel_data_cache(channel_data_cache)

        return channel_data

    except HttpError as e:
        logger.error(f"HTTP error while retrieving data for channel ID {channel_id}: {e}.")
    except Exception as e:
        logger.error(f"Unexpected error while retrieving data for channel ID {channel_id}: {e}")

    return {
        "author_name": "Unknown",
        "author_channel_id": channel_id,
        "author_subscribers": 0
    }
