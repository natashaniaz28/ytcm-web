import logging
logger = logging.getLogger(__name__)

from googleapiclient.errors        import HttpError                     # google-api-python-client

from YTCM_channel_utils            import get_channel_data


def get_comments(youtube, **kwargs):
    """
    Download comments. This is the most complex function as it handles subcases (replies to comments).
    The function retrieves all comments for a specific video.
    It also retrieves replies to comments and appends them to the respective comment.
    It checks for multiple pages of comments and iterates through them until all comments are collected.
    returns a list and a "quota exceeded" flag.
    """

    video_id = kwargs.get("videoId", "unknown")

    try:
        results = youtube.commentThreads().list(**kwargs).execute()
    except HttpError as e:
        if e.resp.status == 403:
            logger.info("Comments are disabled for this video.")
            return [], False
        elif e.resp.status == 404:
            logger.warning(f"Video ID {video_id} not found.")
            return [], False
        elif e.resp.status == 429:
            logger.error(f"API quota exceeded while retrieving comments for video ID {video_id}.")
            return [], True
        else:
            logger.error(f"Error while retrieving comments for video ID {video_id}: {e}.")
            return [], False
    except Exception as e:
        logger.error(f"Unexpected error while retrieving comments for video ID {video_id}: {e}.")
        return None, False

    comments = []
    ccounter = 0

    try:
        while results:
            if "items" not in results:
                break

            for item in results["items"]:
                try:
                    if "snippet" not in item or "topLevelComment" not in item["snippet"]:
                        continue

                    top_level_comment = item["snippet"].get("topLevelComment", {})
                    if "snippet" not in top_level_comment:
                        continue

                    comment_snippet = top_level_comment["snippet"]
                    text_display = comment_snippet.get("textDisplay", "")

                    comment_data = {
                        "youtube_comment_id": item.get("id", ""),
                        "text"              : text_display,
                        "date"              : comment_snippet.get("publishedAt", ""),
                        "likes"             : comment_snippet.get("likeCount", 0),
                        "replies"           : []
                    }

                    if item["snippet"].get("totalReplyCount", 0) > 0:
                        reply_kwargs = {
                            "parentId"  : item.get("id", ""),
                            "part"      : "snippet",
                            "textFormat": "plainText"
                        }

                        try:
                            reply_results = youtube.comments().list(**reply_kwargs).execute()

                            while reply_results:
                                for reply in reply_results.get("items", []):
                                    try:
                                        reply_snippet = reply.get("snippet", {})
                                        reply_text = reply_snippet.get("textDisplay", "")

                                        author_channel_id = ""
                                        if "authorChannelId" in reply_snippet and isinstance(
                                                reply_snippet["authorChannelId"], dict):
                                            author_channel_id = reply_snippet["authorChannelId"].get("value", "")

                                        reply_data = {
                                            "youtube_reply_id" : reply.get("id", ""),
                                            "youtube_parent_id": reply_snippet.get("parentId", ""),
                                            "text"             : reply_text,
                                            "date"             : reply_snippet.get("publishedAt", ""),
                                            "likes"            : reply_snippet.get("likeCount", 0),
                                            "author_name"      : reply_snippet.get("authorDisplayName", ""),
                                            "author_channel_id": author_channel_id
                                        }

                                        comment_data["replies"].append(reply_data)
                                    except Exception as e:
                                        if isinstance(e, HttpError) and e.resp.status == 429:
                                            logger.error(f"API quota exceeded while retrieving replies for video ID {video_id}.\n")
                                            return None, True
                                        logger.error(f"Error loading replies for video {video_id}: {e}")
                                        continue

                                if "nextPageToken" in reply_results:
                                    reply_kwargs["pageToken"] = reply_results["nextPageToken"]
                                    try:
                                        reply_results = youtube.comments().list(**reply_kwargs).execute()
                                    except Exception as e:
                                        if isinstance(e, HttpError) and e.resp.status == 429:
                                            logger.error(f"API quota exceeded while retrieving replies for video ID {video_id}.\n")
                                            return None, True
                                        logger.error(f"Error loading replies for video {video_id}: {e}")
                                        break
                                else:
                                    break
                        except Exception as e:
                            if isinstance(e, HttpError) and e.resp.status == 429:
                                logger.error(f"API quota exceeded while retrieving replies for video ID {video_id}.\n")
                                return None, True
                            logger.error(f"Error loading replies for video {video_id}: {e}")

                    # Author data for main comment
                    try:
                        author_channel_id = ""
                        if "authorChannelId" in comment_snippet and isinstance(comment_snippet["authorChannelId"], dict):
                            author_channel_id = comment_snippet["authorChannelId"].get("value", "")

                        if author_channel_id:
                            author_data = get_channel_data(youtube, author_channel_id)
                            if author_data:
                                comment_data.update(author_data)
                    except Exception as e:
                        logger.warning(f"Error retrieving author data for comment in video ID {video_id}: {e}.")

                    comments.append(comment_data)
                    ccounter += 1
                    print(f"\r{ccounter} comments processed ...", end="")

                except Exception as e:
                    logger.error(f"Error processing comment in video ID {video_id}: {e}.")
                    continue

            # Pagination
            if "nextPageToken" in results:
                kwargs["pageToken"] = results["nextPageToken"]
                try:
                    results = youtube.commentThreads().list(**kwargs).execute()
                except Exception as e:
                    logger.error(f"Error loading more comments for video {video_id}: {e}")
                    break
            else:
                break

    except Exception as e:
        logger.error(f"Unexpected error processing comments for video {video_id}: {e}")
        return None, False

    print(f"\r{ccounter} comments downloaded for this video.\n")
    logger.info(f"{ccounter} comments downloaded for video ID {video_id}.")

    return comments, False          # flag shows that quota has not been exceeded
