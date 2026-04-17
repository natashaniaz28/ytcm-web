import csv, json, logging, re, unicodedata

import networkx as nx

from datetime          import datetime
from YTCM_config       import COMMENTS_FOLDER
from YTCM_helper_utils import safe_write_json

logger = logging.getLogger(__name__)
CTRL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]")

def save_comments_to_text(video_id, video_info, comments):
    """
    Save all collected comments and replies for one video.
    Messy, but self-explanatory.
    """

    filename = f"{COMMENTS_FOLDER}/{video_id}.TXT"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filename, "w", encoding="utf-8") as txt_file:
        # Write video metadata
        txt_file.write(f"YouTube Video ID      : {video_id}\n")
        txt_file.write(f"Title                 : {video_info.get('title', 'N/A')}\n")
        txt_file.write(f"Duration              : {video_info.get('duration', 'N/A')}\n")
        txt_file.write(f"Description           : {video_info.get('description', 'N/A')}\n")
        txt_file.write(f"Published at          : {video_info.get('published_at', 'N/A')}\n")
        txt_file.write(f"Channel Name          : {video_info.get('channel_name', 'N/A')}\n")
        txt_file.write(f"Channel ID            : {video_info.get('channel_id', 'N/A')}\n")
        txt_file.write(f"Number of Likes       : {video_info.get('likes', 0)}\n")
        txt_file.write(f"Number of Dislikes    : {video_info.get('dislikes', 0)}\n")
        txt_file.write(f"Views                 : {video_info.get('views', 0)}\n")
        txt_file.write(f"Retrieval Date        : {current_time}\n\n")

        # Iterate comments and write comments metadata
        for comment in comments:
            txt_file.write(f"YouTube Comment ID    : {comment.get('youtube_comment_id', '')}\n")
            txt_file.write(f"Comment Text          : {comment.get('text', '')}\n")
            txt_file.write(f"Published at          : {comment.get('date', '')}\n")
            txt_file.write(f"Number of Likes       : {comment.get('likes', 0)}\n")
            txt_file.write(f"Author Channel        : {comment.get('author_name', '')}\n")
            txt_file.write(f"Author Channel ID     : {comment.get('author_channel_id', '')}\n")
            txt_file.write(f"Subscribers Number    : {comment.get('author_subscribers', 'N/A')}\n")

            # Iterate replies
            for reply in comment.get("replies", []):
                txt_file.write("\n")
                txt_file.write("-> Reply:\n")
                txt_file.write(f"     YouTube Reply ID : {reply.get('youtube_reply_id', '')}\n")
                txt_file.write(f"     YouTube Parent ID: {reply.get('youtube_parent_id', '')}\n")
                txt_file.write(f"     Text             : {reply.get('text', '')}\n")
                txt_file.write(f"     Published at     : {reply.get('date', '')}\n")
                txt_file.write(f"     Likes            : {reply.get('likes', 0)}\n")
                txt_file.write(f"     Channel Name     : {reply.get('author_name', '')}\n")
                txt_file.write(f"     Channel ID       : {reply.get('author_channel_id', '')}\n")
                txt_file.write(f"     Subscribers      : {reply.get('author_subscribers', 'N/A')}\n")
            txt_file.write("\n")
        txt_file.write("\n")


def save_comments_to_json(all_comments, filename):
    """
    Save the collected comments to the JSON file.
    Self-explanatory.
    """

    safe_write_json(all_comments, filename)


def convert_json_to_html(json_file, output_html):
    """
    This part was written by Durga Ram!
    """

    try:
        with open(json_file, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error reading JSON file '{json_file}': {e}.")
        return

    html_content = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            h2 { color: #2c3e50; }
            .video-section { margin-bottom: 30px; }
            .comments { margin-left: 20px; margin-top: 10px; }
            .comment, .reply { margin-bottom: 15px; }
            .comment p, .reply p { margin: 0; }
            .comment-date, .comment-language, .comment-score, .reply-date, .reply-language, .reply-score {
                font-size: 0.9em; color: #7f8c8d;
            }
            .comment-author, .reply-author { font-weight: bold; }
            .divider { border-top: 1px solid #ecf0f1; margin-top: 20px; }
            summary { font-size: 1.2em; font-weight: bold; cursor: pointer; }
            details { margin-bottom: 20px; }
            .replies { margin-left: 20px; border-left: 2px solid #ccc; padding-left: 10px; }
        </style>
    </head>
    <body>
    <h1>Video Report</h1>
    """

    for video_id, details in data.items():
        video_info = details.get("video_info", {})
        comments = details.get("comments", [])

        html_content += f"""
        <details class="video-section">
            <summary>{video_info.get("title", "N/A")}</summary>
            <p><strong>Video ID:</strong> {video_id}</p>
            <p><strong>Description:</strong> {video_info.get("description", "N/A")}</p>
            <p><strong>Duration:</strong> {video_info.get("duration", "N/A")}</p>
            <p><strong>TextBlob score:</strong> {video_info.get("blob_sentiment", "N/A")}</p>
            <p><strong>VADER score:</strong> {video_info.get("vader_sentiment", "N/A")}</p>
            <p><strong>Language (title):</strong> {video_info.get("title_language", "N/A")}</p>
            <p><strong>Language (description):</strong> {video_info.get("description_language", "N/A")}</p>
            <p><strong>Published At:</strong> {video_info.get("published_at", "N/A")}</p>
            <p><strong>Channel Name:</strong> {video_info.get("channel_name", "N/A")}</p>
            <p><strong>Channel ID:</strong> {video_info.get("channel_id", "N/A")}</p>
            <p><strong>Likes:</strong> {video_info.get("likes", "N/A")}</p>
            <p><strong>Dislikes:</strong> {video_info.get("dislikes", "N/A")}</p>
            <p><strong>Views:</strong> {video_info.get("views", "N/A")}</p>
            <h3>Comments:</h3>
            <div class="comments">
        """

        for comment in comments:
            html_content += f"""
                <div class="comment">
                    <p class="comment-author">{comment.get("author_name", "N/A")}</p>
                    <p class="comment-date">{comment.get("date", "N/A")}</p>
                    <p class="comment-language">{comment.get("language", "N/A")}</p>
                    <p>{comment.get("text", "N/A")}</p>
                    <p class="comment-score">Blob: {comment.get("blob_sentiment", "N/A")}, VADER: {comment.get("vader_sentiment", "N/A")}</p>
                    <p><strong>Likes:</strong> {comment.get("likes", "N/A")}</p>
                    <p><strong>YouTube Comment ID:</strong> {comment.get("youtube_comment_id", "N/A")}</p>
                </div>
            """

            replies = comment.get("replies", [])
            if replies:
                html_content += "<div class='replies'>"
                for reply in replies:
                    html_content += f"""
                    <div class="reply">
                        <p class="reply-author">{reply.get("author_name", "N/A")}</p>
                        <p class="reply-date">{reply.get("date", "N/A")}</p>
                        <p class="reply-language">{reply.get("language", "N/A")}</p>
                        <p>{reply.get("text", "N/A")}</p>
                        <p class="reply-score">Blob: {reply.get("blob_sentiment", "N/A")}, VADER: {reply.get("vader_sentiment", "N/A")}</p>
                        <p><strong>Likes:</strong> {reply.get("likes", "N/A")}</p>
                        <p><strong>YouTube Reply ID:</strong> {reply.get("youtube_reply_id", "N/A")}</p>
                        <p><strong>Parent ID:</strong> {reply.get("youtube_parent_id", "N/A")}</p>
                    </div>
                    """
                html_content += "</div>"

        html_content += """
            </div>
        </details>
        <div class="divider"></div>
        """

    html_content += """
    </body>
    </html>
    """

    with open(output_html, "w", encoding="utf-8") as html_file:
        html_file.write(html_content)

    print(f"HTML report generated: {output_html}.")


def sanitize(string):
    """
    This avoids unicode encoding errors that prevent Gephi from loading the file.
    """

    if string is None:
        return ""

    string = str(string)
    string = unicodedata.normalize("NFC", string)
    string = CTRL_CHARS_PATTERN.sub("", string)

    return string


def convert_json_to_gephi(json_name, gephi_name, include_replies=False):
    """
    Create a directed graph representing relationships between video channels, commenters,
    and optionally repliers (if include_replies=True).

    Each edge is tagged with an 'edge_type': ('comment' for video -> commenter,
    'reply' for commenter -> replier) to allow their visual distinction in Gephi.

    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    !!! Network nodes are created channel-based, not video-based. Video IDs are not nodes, but channel IDs. !!!
    !!! Network edges “Channel -> User” mean “a user commented on a video from this channel”.               !!!
    !!! This is important to understand any possible Gephi representations.                                 !!!
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    """

    if not json_name or not gephi_name:
        return

    try:
        with open(json_name, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
    except (IOError, json.JSONDecodeError) as e:
        logger.error("Could not read JSON file.")
        return

    G = nx.DiGraph()  # create the graph

    # Outer loop: iterate all video IDs
    for video_id, video_data in data.items():
        video_info = video_data.get("video_info", {})
        comments = video_data.get("comments", [])

        channel_id = sanitize(video_info.get("channel_id"))
        channel_name = sanitize(video_info.get("channel_name"))

        if not channel_id:
            continue

        # If there's no node for a ChannelID already, add one.
        # "has_node" checks for a node's existence and returns a Boolean,
        # and "add_node" adds a tuple of ID and name
        if not G.has_node(channel_id):
            G.add_node(channel_id, name=channel_name, label=channel_name)

        # Middle loop: iterate comments
        for comment in comments:
            author_id = sanitize(comment.get("author_channel_id"))
            author_name = sanitize(comment.get("author_name"))

            if not author_id:
                continue

            # Check for existing nodes and edges
            if not G.has_node(author_id):
                G.add_node(author_id, name=author_name, label=author_name)

            if not G.has_edge(channel_id, author_id):
                G.add_edge(channel_id, author_id, weight=1, edge_type="comment")
            else:
                G[channel_id][author_id]["weight"] += 1

            # If replies are to be exported, here's the inner loop iterating them
            if include_replies:
                for reply in comment.get("replies", []):
                    reply_id = sanitize(reply.get("author_channel_id", ""))
                    reply_name = sanitize(reply.get("author_name", ""))

                    if not reply_id:
                        continue

                    # As above, check for existing nodes and edges
                    if not G.has_node(reply_id):
                        G.add_node(reply_id, name=reply_name, label=reply_name)

                    if not G.has_edge(author_id, reply_id):
                        G.add_edge(author_id, reply_id, weight=1, edge_type="reply")
                    else:
                        G[author_id][reply_id]["weight"] += 1

    try:
        nx.write_gexf(G, gephi_name, encoding="utf-8")
        print(f"Network data generated: {gephi_name}.")
    except IOError as e:
        logger.error(f"Could not create network data file: {e}.")


def convert_json_to_csv(json_file, csv_file):
    """
    Export comments and replies from JSON to a flattened CSV format.
    Each row represents one comment or one reply.
    Replies are marked with comment_type = "reply" and reference their parent comment.
    Additional fields include video and channel metadata to allow numeric/statistical aggregation.

    The CSV is somewhat bloated because video info is repeated several times.
    The only alternatives would be to either leave information out,
    or to generate multiple CSVs.
    """

    try:
        with open(json_file, "r", encoding="utf-8") as input_file:
            data = json.load(input_file)
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Error reading JSON file '{json_file}': {e}.")
        return

    rows = []

    for video_id, content in data.items():
        video_info = content.get("video_info", {})
        comments   = content.get("comments",   [])

        for comment in comments:
            base_row = {
                "video_id": video_id,
                "video_title": video_info.get("title", ""),
                "video_description": video_info.get("description", ""),
                "video_title_language": video_info.get("title_language", ""),
                "video_description_language": video_info.get("description_language", ""),
                "video_duration": video_info.get("duration", ""),
                "video_views": video_info.get("views", 0),
                "video_likes": video_info.get("likes", 0),
                "video_dislikes": video_info.get("dislikes", 0),
                "published_at": video_info.get("published_at", ""),
                "channel_name": video_info.get("channel_name", ""),
                "channel_id": video_info.get("channel_id", ""),
                "comment_type": "comment",
                "comment_id": comment.get("youtube_comment_id", ""),
                "reply_to_comment_id": "",
                "youtube_comment_id": comment.get("youtube_comment_id", ""),
                "youtube_reply_id": "",
                "youtube_parent_id": "",
                "author_name": comment.get("author_name", ""),
                "author_channel_id": comment.get("author_channel_id", ""),
                "author_subscribers": comment.get("author_subscribers", "N/A"),
                "text": comment.get("text", ""),
                "date": comment.get("date", ""),
                "likes": comment.get("likes", 0),
                "language": comment.get("language", ""),
                "blob_sentiment": comment.get("blob_sentiment", 0),
                "vader_sentiment": comment.get("vader_sentiment", 0)
            }
            rows.append(base_row)

            for reply in comment.get("replies", []):
                reply_row = {
                    "video_id": video_id,
                    "video_title": video_info.get("title", ""),
                    "video_description": video_info.get("description", ""),
                    "video_title_language": video_info.get("title_language", ""),
                    "video_description_language": video_info.get("description_language", ""),
                    "video_duration": video_info.get("duration", ""),
                    "video_views": video_info.get("views", 0),
                    "video_likes": video_info.get("likes", 0),
                    "video_dislikes": video_info.get("dislikes", 0),
                    "published_at": video_info.get("published_at", ""),
                    "channel_name": video_info.get("channel_name", ""),
                    "channel_id": video_info.get("channel_id", ""),
                    "comment_type": "reply",
                    "comment_id": reply.get("youtube_reply_id", ""),
                    "reply_to_comment_id": reply.get("youtube_parent_id", ""),
                    "youtube_comment_id": "",
                    "youtube_reply_id": reply.get("youtube_reply_id", ""),
                    "youtube_parent_id": reply.get("youtube_parent_id", ""),
                    "author_name": reply.get("author_name", ""),
                    "author_channel_id": reply.get("author_channel_id", ""),
                    "author_subscribers": reply.get("author_subscribers", "N/A"),
                    "text": reply.get("text", ""),
                    "date": reply.get("date", ""),
                    "likes": reply.get("likes", 0),
                    "language": reply.get("language", ""),
                    "blob_sentiment": reply.get("blob_sentiment", 0),
                    "vader_sentiment": reply.get("vader_sentiment", 0)
                }
                rows.append(reply_row)

    fieldnames = [
        "video_id", "video_title", "video_description",
        "video_title_language", "video_description_language", "video_duration",
        "video_views", "video_likes", "video_dislikes", "published_at",
        "channel_name", "channel_id",
        "comment_type", "comment_id", "reply_to_comment_id",
        "youtube_comment_id", "youtube_reply_id", "youtube_parent_id",
        "author_name", "author_channel_id", "author_subscribers",
        "text", "date", "likes", "language",
        "blob_sentiment", "vader_sentiment"
    ]

    try:
        with open(csv_file, "w", encoding="utf-8", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        print(f"CSV export completed: {csv_file}.")
    except IOError as e:
        logger.error(f"Error writing CSV: {e}.")
