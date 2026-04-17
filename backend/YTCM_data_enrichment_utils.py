import logging
logger = logging.getLogger(__name__)

import json, os

from tqdm                          import tqdm
from langdetect                    import detect, LangDetectException
from textblob                      import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer            # vadersentiment

from YTCM_helper_utils             import safe_write_json
from YTCM_config                   import COMMENTS_ANONYMIZED_JSON, ANONYMIZATION_MAP_JSON

_VADER = SentimentIntensityAnalyzer()


def review(COMMENTS_JSON):
    """
    Do a manual review of the downloaded videos to purge unwanted content.
    """

    try:
        with open(COMMENTS_JSON, "r", encoding="utf-8") as f:
            comments_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: file '{COMMENTS_JSON}' not found.")
        return
    except json.JSONDecodeError as e:
        logger.error(f"Error: file '{COMMENTS_JSON}' contains invalid JSON: {e}.")
        return

    modified = False
    mod_counter = 0
    for video_id, video_data in comments_data.items():
        if "manual_review" not in video_data:
            print(f"Added 'manual_review' flag for video ID {video_id}.")
            video_data["manual_review"] = False
            modified = True
            mod_counter += 1

    if modified:
        safe_write_json(comments_data, COMMENTS_JSON)
        print(f"Added 'manual_review' flag to {mod_counter} videos.")

    to_delete = []
    del_counter = 0

    to_be_reviewed = [video for video, data in comments_data.items() if data.get("manual_review") is False]

    if not to_be_reviewed:
        print("All videos already reviewed.")
        return

    for video_id in to_be_reviewed:
        video_data = comments_data[video_id]
        print(f"\nReviewing video ID {video_id}:")
        info = video_data.get("video_info", {})
        print(f"-> Title      : {info.get('title', '[N/A]')}")
        print(f"-> Description: {info.get('description', '[N/A]')}")
        choice = input("Do you want to keep this video? (type 'no' to delete / 'q' to quit the process): ").strip().lower()
        if choice == "no":
            print("Marked for deletion.")
            to_delete.append(video_id)
            del_counter += 1
        elif choice == "q" :
            break
        else:
            print("Marked for keeping. Marked as reviewed.")
            video_data["manual_review"] = True

    print(f"\n{del_counter} video(s) marked for deletion.")
    choice = input("Do you want to proceed? (type 'yes' to confirm): ").strip().lower()

    if choice != "yes":
        print("Aborting. No changes were made to the JSON file.")
        return

    for video_id in to_delete:
        del comments_data[video_id]
        print(f"Deleted video ID {video_id}.")

    safe_write_json(comments_data, COMMENTS_JSON)

    print(f"\nManual review completed. {len(to_delete)} video(s) removed.")


def detect_languages(COMMENTS_JSON, force_rebuild=False):
    """
    Perform language detection for all videos, all comments, and all replies.
    """

    try:
        with open(COMMENTS_JSON, "r", encoding="utf-8") as f:
            all_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: file '{COMMENTS_JSON}' not found.")
        return
    except json.JSONDecodeError:
        logger.error(f"Error: file '{COMMENTS_JSON}' contains invalid JSON.")
        return

    print("Detecting languages for all videos, all comments, and all replies. This can take a while.")
    for video_id, video_data in tqdm(all_data.items(), desc="Videos", unit="video"):
        video_info = video_data.get("video_info", {})

        for field in ("title", "description"):
            lang_key = f"{field}_language"
            if force_rebuild or lang_key not in video_info:
                text = video_info.get(field, "")
                lang = detect_language(text) if text else "unknown"
                video_info[lang_key] = lang

        for comment in video_data.get("comments", []):
            if force_rebuild or "language" not in comment:
                comment_text = comment.get("text", "")
                comment["language"] = detect_language(comment_text) if comment_text else "unknown"

            for reply in comment.get("replies", []):
                if force_rebuild or "language" not in reply:
                    reply_text = reply.get("text", "")
                    reply["language"] = detect_language(reply_text) if reply_text else "unknown"

    safe_write_json(all_data, COMMENTS_JSON)

    print("Language detection completed.")


def sentiment_analysis(COMMENTS_JSON, force_rebuild=False):
    """
    Perform sentiment analysis for all English-language comments and replies.
    """

    try:
        with open(COMMENTS_JSON, "r", encoding="utf-8") as f:
            all_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: file '{COMMENTS_JSON}' not found.")
        return
    except json.JSONDecodeError:
        logger.error(f"Error: file '{COMMENTS_JSON}' contains invalid JSON.")
        return

    print("Checking if language detection has been completed for all items ...")
    incomplete = False
    for video_id, video_data in all_data.items():
        video_info = video_data.get("video_info", {})
        for field in ("title_language", "description_language"):
            if field not in video_info:
                logger.warning(f"Missing language info for video {video_id} field '{field}'.")
                incomplete = True

        for comment in video_data.get("comments", []):
            if "language" not in comment:
                logger.warning(f"Missing language info for comment in video {video_id}.")
                incomplete = True
            for reply in comment.get("replies", []):
                if "language" not in reply:
                    logger.warning(f"Missing language info for reply in video {video_id}.")
                    incomplete = True

    if incomplete:
        print("Aborting sentiment analysis: not all language fields are present.")
        print("Please run 'language' command first to perform language detection.")
        return

    print("\nRunning sentiment analysis on English comments and replies ...")
    for video_id, video_data in tqdm(all_data.items(), desc="Videos", unit="video"):
        for comment in video_data.get("comments", []):
            lang = comment.get("language", "")
            text = comment.get("text", "")

            if text and lang == "en":
                if force_rebuild or "blob_sentiment" not in comment:
                    try:
                        comment["blob_sentiment"] = blob_analysis(text)
                    except Exception:
                        comment["blob_sentiment"] = "N/A"               # 0.0

                if force_rebuild or "vader_sentiment" not in comment:
                    try:
                        comment["vader_sentiment"] = vader_analysis(text)
                    except Exception:
                        comment["vader_sentiment"] = "N/A"              # 0.0
            else:
                if "blob_sentiment" not in comment:
                    comment["blob_sentiment"] = "N/A"
                if "vader_sentiment" not in comment:
                    comment["vader_sentiment"] = "N/A"

            for reply in comment.get("replies", []):
                reply_lang = reply.get("language", "")
                reply_text = reply.get("text", "")

                if reply_text and reply_lang == "en":
                    if force_rebuild or "blob_sentiment" not in reply:
                        try:
                            reply["blob_sentiment"] = blob_analysis(reply_text)
                        except Exception:
                            reply["blob_sentiment"] = "N/A"             # 0.0

                    if force_rebuild or "vader_sentiment" not in reply:
                        try:
                            reply["vader_sentiment"] = vader_analysis(reply_text)
                        except Exception:
                            reply["vader_sentiment"] = "N/A"                # 0.0
                else:
                    if "blob_sentiment" not in reply:
                        reply["blob_sentiment"] = "N/A"
                    if "vader_sentiment" not in reply:
                        reply["vader_sentiment"] = "N/A"

    safe_write_json(all_data, COMMENTS_JSON)
    print("Sentiment analysis completed.")


def blob_analysis(text):
    """
    Use the TextBlob library for automatic sentiment analysis.
    """

    analysis = TextBlob(text)
    sentiment_score = analysis.sentiment.polarity

    return round(sentiment_score, 2)


def vader_analysis(text):
    """
    Use the VADER (Valence Aware Dictionary and sEntiment Reasoner) library for automatic sentiment analysis
    """

    analysis = _VADER
    sentiment_score = analysis.polarity_scores(text)["compound"]

    return round(sentiment_score, 2)


def detect_language(text):
    """
    Detect the language of the given text (description or comment).
    """

    try:
        return detect(text)
    except (LangDetectException, ValueError, TypeError):
        return "unknown"


def anonymize(COMMENTS_JSON, purge=False):
    """
    Anonymize YouTube channel IDs (and optionally names).
    If purge=True, overwrite all real channel IDs and save to a new file.
    Otherwise, just add anonymized tokens to the existing JSON.
    """

    try:
        with open(COMMENTS_JSON, "r", encoding="utf-8") as json_file:
            all_data = json.load(json_file)
    except FileNotFoundError:
        logger.error(f"Error: file '{COMMENTS_JSON}' not found.")
        return
    except json.JSONDecodeError as e:
        logger.error(f"Error: JSON structure in '{COMMENTS_JSON}' is corrupt: {e}.")
        return

    if not all_data:
        print("No data to anonymize.")
        return

    mapping = {}
    counter = 1

    if os.path.exists(ANONYMIZATION_MAP_JSON):
        try:
            with open(ANONYMIZATION_MAP_JSON, "r", encoding="utf-8") as mapping_file:
                mapping = json.load(mapping_file)
                counter = len(mapping) + 1
        except Exception as e:
            logger.warning(f"Could not load anonymization map: {e}. Starting fresh.")
            mapping = {}
            counter = 1

    found_ids = set()

    for video_data in all_data.values():
        info = video_data.get("video_info", {})
        if "channel_id" in info:
            found_ids.add(info["channel_id"])

        for comment in video_data.get("comments", []):
            ch_id = comment.get("author_channel_id")
            if ch_id:
                found_ids.add(ch_id)
            for reply in comment.get("replies", []):
                rep_id = reply.get("author_channel_id")
                if rep_id:
                    found_ids.add(rep_id)

    for ch_id in sorted(found_ids):
        if ch_id not in mapping:
            token = f"User{counter}"
            mapping[ch_id] = token
            counter += 1

    for video_data in all_data.values():
        info = video_data.get("video_info", {})
        ch_id = info.get("channel_id")
        if ch_id and ch_id in mapping:
            if purge:
                info["channel_id"] = mapping[ch_id]
                info.pop("anonymized_channel_id", None)
                if "channel_name" in info:
                    info["channel_name"] = mapping[ch_id].replace("User", "Channel")
            else:
                info["anonymized_channel_id"] = mapping[ch_id]
                info["anonymized_channel_name"] = mapping[ch_id].replace("User", "Channel")

        for comment in video_data.get("comments", []):
            ch_id = comment.get("author_channel_id")
            if ch_id and ch_id in mapping:
                if purge:
                    comment["author_channel_id"] = mapping[ch_id]
                    comment.pop("anonymized_author_id", None)
                    if "author_name" in comment:
                        comment["author_name"] = mapping[ch_id]
                else:
                    comment["anonymized_author_id"] = mapping[ch_id]
                    comment["anonymized_author_name"] = mapping[ch_id]

            for reply in comment.get("replies", []):
                rep_id = reply.get("author_channel_id")
                if rep_id and rep_id in mapping:
                    if purge:
                        reply["author_channel_id"] = mapping[rep_id]
                        reply.pop("anonymized_author_id", None)
                        if "author_name" in reply:
                            reply["author_name"] = mapping[rep_id]
                    else:
                        reply["anonymized_author_id"] = mapping[rep_id]
                        reply["anonymized_author_name"] = mapping[rep_id]

    if purge:
        print(f"Purging original IDs in new file '{COMMENTS_ANONYMIZED_JSON}' ...")
        safe_write_json(all_data, COMMENTS_ANONYMIZED_JSON)
        print("Anonymized file successfully written.")
    else:
        print(f"Adding anonymized tokens to '{COMMENTS_JSON}' ...")
        safe_write_json(all_data, COMMENTS_JSON)
        try:
            with open(ANONYMIZATION_MAP_JSON, "w", encoding="utf-8") as mapping_file:
                json.dump(mapping, mapping_file, indent=2, ensure_ascii=False)
            print(f"Updated anonymization map written to '{ANONYMIZATION_MAP_JSON}'.")
        except Exception as e:
            logger.error(f"Could not save mapping file {ANONYMIZATION_MAP_JSON}: {e}.")

def deanonymize(COMMENTS_JSON):
    """
    Deletes all anonymized IDs and the mapping file, so a new anonymization process can be started:
    - video_info: 'anonymized_channel_id', 'anonymized_channel_name'
    - comments / replies: 'anonymized_author_id', 'anonymized_author_name'
    """

    try:
        with open(COMMENTS_JSON, "r", encoding="utf-8") as f:
            all_data = json.load(f)

    except FileNotFoundError:
        logger.error(f"Error: file '{COMMENTS_JSON}' not found.")
        print(f"Error: file '{COMMENTS_JSON}' not found.")
        return

    except json.JSONDecodeError as e:
        logger.error(f"Error: file '{COMMENTS_JSON}' contains invalid JSON: {e}.")
        print("JSON error in input file.")
        return

    if not isinstance(all_data, dict) or not all_data:
        print("File contains no data.")
        return

    removed_video_fields = 0
    removed_comment_fields = 0
    removed_reply_fields = 0

    for video_id, video_data in all_data.items():
        info = video_data.get("video_info", {})                                 # videos
        for key in ("anonymized_channel_id", "anonymized_channel_name"):
            if key in info:
                info.pop(key, None)
                removed_video_fields += 1

        for comment in video_data.get("comments", []):                          # comments
            for key in ("anonymized_author_id", "anonymized_author_name"):
                if key in comment:
                    comment.pop(key, None)
                    removed_comment_fields += 1

            for reply in comment.get("replies", []):                            # replies
                for key in ("anonymized_author_id", "anonymized_author_name"):
                    if key in reply:
                        reply.pop(key, None)
                        removed_reply_fields += 1

    safe_write_json(all_data, COMMENTS_JSON)

    if os.path.exists(ANONYMIZATION_MAP_JSON):                                  # mapping
        try:
            os.remove(ANONYMIZATION_MAP_JSON)
            print(f"Mapping file '{ANONYMIZATION_MAP_JSON}' deleted.")
        except Exception as e:
            logger.error(f"Error: Could not delete mapping file {ANONYMIZATION_MAP_JSON}: {e}")
            print(f"Could not delete mapping file {ANONYMIZATION_MAP_JSON}.")

    print("Removed entries:")
    print(f"Video level   : {removed_video_fields}")
    print(f"Comments level: {removed_comment_fields}")
    print(f"Replies       : {removed_reply_fields}")
