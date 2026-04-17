import logging
logger = logging.getLogger(__name__)

from googleapiclient.errors import HttpError                     # google-api-python-client

from YTCM_api_utils         import get_video_information
from YTCM_comments_utils    import get_comments
from YTCM_config            import MAX_RESULTS, COMMENTS_JSON
from YTCM_export_utils      import save_comments_to_text, save_comments_to_json


def process_videos(youtube, video_ids, all_comments):
    """
    Process metadata retrieval for a list of videos including their comments.
    """

    total_videos = len(video_ids)
    processed_videos = 0
    failed_videos = 0

    for index, video_id in enumerate(video_ids, start=1):
        print(f"Processing video {index} of {total_videos} (ID: {video_id}).")

        old_entry = all_comments.get(video_id)
        old_entry_exists = old_entry is not None
        update_successful = False

        try:
            try:
                video_info = get_video_information(youtube, video_id)
                if not video_info:
                    logger.error(f"Failed to retrieve information for video ID {video_id}. Skipping this video ID.")
                    failed_videos += 1
                    if old_entry_exists and not update_successful:
                        all_comments[video_id] = old_entry
                    continue
            except HttpError as e:
                logger.error(f"HTTP error when retrieving video information for video ID {video_id}: {e}.")
                failed_videos += 1
                if old_entry_exists and not update_successful:
                    all_comments[video_id] = old_entry
                continue
            except Exception as e:
                logger.error(f"Unexpected error retrieving video information for video ID {video_id}: {e}.")
                failed_videos += 1
                if old_entry_exists and not update_successful:
                    all_comments[video_id] = old_entry
                continue

            try:
                comments, quota_exceeded = get_comments(
                    youtube, part="snippet", videoId=video_id, maxResults=MAX_RESULTS, textFormat="plainText"
                )

                if quota_exceeded:
                    logger.error(f"Quota exceeded for video ID {video_id}. Please retry next time.")
                    continue

                if comments is None:
                    logger.error(f"Failed to retrieve comments for video ID {video_id} for unknown reason. Skipping this ID.")
                    failed_videos += 1
                    if old_entry_exists and not update_successful:
                        all_comments[video_id] = old_entry
                    continue

            except Exception as e:
                logger.error(f"Unexpected error retrieving comments for video ID {video_id}: {e}.")
                failed_videos += 1
                comments = []
                if old_entry_exists and not update_successful:
                    all_comments[video_id] = old_entry
                continue

            try:
                all_comments[video_id] = {
                    "video_info": video_info,
                    "comments": comments
                }
                update_successful = True
            except Exception as e:
                logger.error(f"Error adding data for video ID {video_id} to collection: {e}.")
                failed_videos += 1
                if old_entry_exists and not update_successful:
                    all_comments[video_id] = old_entry
                continue

            try:
                sorted_items = []
                for vid_id, vid_data in all_comments.items():
                    if "video_info" in vid_data and "published_at" in vid_data["video_info"]:
                        sorted_items.append((vid_id, vid_data))
                    else:
                        logger.warning(f"Missing publication date for video ID {vid_id}. Skipping this video ID in sort.")

                # Sorting would delete elements without a "published_at" key. Although this should never happen because
                # YouTube always provides this information, I do a little extra stuff to prevent data loss.
                if sorted_items:
                    unsortable_items = [
                        (vid_id, vid_data) for vid_id, vid_data in all_comments.items()
                        if not ("video_info" in vid_data and "published_at" in vid_data["video_info"])
                    ]
                    sorted_items = sorted(sorted_items, key=lambda x: x[1]["video_info"].get("published_at", ""))
                    all_comments.clear()
                    all_comments.update(sorted_items + unsortable_items)
            except Exception as e:
                logger.error(f"Error sorting video data: {e}.")

            try:
                save_comments_to_text(video_id, video_info, comments)
            except Exception as e:
                logger.error(f"Error saving comments to text file for video ID {video_id}: {e}.")

            try:
                save_comments_to_json(all_comments, COMMENTS_JSON)
            except Exception as e:
                logger.error(f"Error saving comments to JSON file: {e}.")

            processed_videos += 1
            print(f"Successfully processed video {index} of {total_videos} (ID: {video_id}).")

        except HttpError as e:
            logger.error(f"HTTP error processing video ID {video_id}: {e}.")
            failed_videos += 1
            if old_entry_exists and not update_successful:
                all_comments[video_id] = old_entry
            continue
        except Exception as e:
            logger.error(f"Unexpected error processing video ID {video_id}: {e}.")
            failed_videos += 1
            if old_entry_exists and not update_successful:
                all_comments[video_id] = old_entry
            continue

    print(f"\nProcessing complete. Processed {processed_videos} of {total_videos} videos.")
    if failed_videos > 0:
        logger.error(f"Failed to process {failed_videos} videos, see above for specific errors.")


def generate_search_list(primary_lists, secondary_list):
    """
    Combine primary and secondary lists to a list of search terms.
    """

    combined = []

    if not primary_lists:
        return []

    if not secondary_list:
        return primary_lists

    for primary in primary_lists:
        for secondary in secondary_list:
            combined.append(primary + [secondary])
    return combined
