import logging
logger = logging.getLogger(__name__)

from datetime                  import datetime, timezone
from dateutil.parser           import isoparse                  # python-dateutil
from googleapiclient.discovery import build                     # google-api-python-client

from YTCM_helper_utils         import safeint

def load_api_key(file_path):
    """
    Load API key from disk.
    """

    try:
        with open(file_path, "r") as file:
            return file.read().strip()

    except FileNotFoundError:
        logger.error(f"Error: Could not find '{file_path}'.")
        return None

    except Exception as e:
        logger.error(f"An unexpected error occured: {e}")
        return None


def init_youtube_service(api_key):
    """
    Create and return a service object for interaction with the YouTube Data API.
    "build" is a function provided by "googleapiclient.discovery".
    """
    
    return build("youtube", "v3", developerKey=api_key)


def get_video_ids(search_terms, youtube, **kwargs):
    """
    Download video IDs.
    The function retrieves video IDs for videos that match all SEARCH_TERMS in any list and were published in SEARCH_YEAR.
    It handles YouTube's pagination to retrieve all relevant video IDs.
    "*kwargs" allows flexible passing of arguments.
    """

    video_ids = set()
    excluded_terms = [term.lower() for term in kwargs.get("excluded_terms", [])]
    search_year = kwargs.get("year")

    if search_year is None:
        print("Search year is not specified.")
        return

    for terms_list in search_terms:
        page_token = None

        while True:
            try:
                search_response = youtube.search().list(
                    q=" ".join(terms_list),
                    type="video",
                    pageToken=page_token,
                    part="snippet",
                    maxResults=kwargs.get("maxResults", 50),
                    publishedAfter=f"{search_year}-01-01T00:00:00Z",
                    publishedBefore=f"{search_year + 1}-01-01T00:00:00Z",
                ).execute()

                # ✅ ADD THESE DEBUGS
                print("\n========== YOUTUBE API RESPONSE ==========")
                print("QUERY:", " ".join(terms_list))
                print("ITEMS RETURNED:", len(search_response.get("items", [])))
                print("FULL RESPONSE KEYS:", search_response.keys())

                for search_result in search_response.get("items", []):
                    year = int(search_result["snippet"]["publishedAt"].split("-")[0])
                    title = search_result["snippet"]["title"].lower()
                    if (
                        year == search_year
                        and all(term.lower() in title for term in terms_list)
                        and not any(exclusion in title for exclusion in excluded_terms)
                    ):
                        video_ids.add(search_result["id"]["videoId"])

                page_token = search_response.get("nextPageToken")
                if not page_token:
                    break

            except Exception as e:
                logger.error(f"An error occurred with search request \'{' '.join(terms_list)}\': {e}. No results retrieved.")
                break

    return list(video_ids)


def get_video_information(youtube, video_id):
    """
    Load video metadata for a given video ID.
    """

    try:
        response = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=video_id
        ).execute()

        if not response.get("items"):
            logger.warning(f"Video ID {video_id} not found or no longer available.")
            return None

        snippet = response["items"][0].get("snippet", {})
        statistics = response["items"][0].get("statistics", {})
        content_details = response["items"][0].get("contentDetails", {})

        description = snippet.get("description", "")

        published_at_raw = snippet.get("publishedAt", "")
        try:
            published_at = isoparse(published_at_raw).astimezone(timezone.utc).isoformat()
        except Exception:
            published_at = published_at_raw

        video_data = {
            "title": snippet.get("title", ""),
            "description"  : description,
            "published_at" : published_at,
            "channel_name" : snippet.get("channelTitle", ""),
            "channel_id"   : snippet.get("channelId", ""),
            "duration"     : content_details.get("duration", ""),
            "likes"        : safeint(statistics.get("likeCount", 0)),
            "dislikes"     : safeint(statistics.get("dislikeCount", 0)),
            "views"        : safeint(statistics.get("viewCount", 0)),
            "download_time": datetime.now(timezone.utc).isoformat(),
            "manual_review": False
        }

        return video_data

    except KeyError as e:
        logger.error(f"Error retrieving data for video ID {video_id}: {e}")
        return None
    except ValueError as e:
        logger.error(f"Invalid value error for video ID {video_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing video ID {video_id}: {e}")
        return None
