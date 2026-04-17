import logging, re

logger = logging.getLogger(__name__)


def filter_data(data, query, mode="or"):
    if isinstance(query, str):
        query_list = [query.lower()]
    else:
        query_list = [q.lower() for q in query]

    if mode not in ("and", "or"):
        mode = "and"

    def matches_query(text):
        if not text:
            return False
        text_lower = text.lower()
        return any(q in text_lower for q in query_list) if mode == "or" else all(q in text_lower for q in query_list)

    filtered_data = {}

    for video_id, content in data.items():
        include = False
        new_comments = []

        description = content.get("video_info", {}).get("description", "")
        if matches_query(description):
            include = True

        for comment in content.get("comments", []):
            comment_matches = matches_query(comment.get("text", ""))
            new_replies = []

            for reply in comment.get("replies", []):
                if matches_query(reply.get("text", "")):
                    new_replies.append(reply)

            if comment_matches or new_replies:
                new_comment = comment.copy()
                new_comment["replies"] = new_replies
                new_comments.append(new_comment)
                include = True

        if include:
            new_entry = {
                "video_info": content["video_info"],
                "comments": new_comments
            }
            filtered_data[video_id] = new_entry

    return filtered_data


def hits(data, query_list):
    def extract_snippets(text, query_list, context=50):
        text = re.sub(r'\s+', ' ', text.strip())  # delete \n and similar stuff
        text_lower = text.lower()
        snippets = []

        COLOR = "\033[34m"  # blue highlight
        RESET = "\033[0m"

        for q in query_list:
            q_lower = q.lower()
            start = 0
            while True:
                idx = text_lower.find(q_lower, start)
                if idx == -1:
                    break
                snippet_start = max(0, idx - context)
                snippet_end = min(len(text), idx + len(q) + context)
                highlighted = COLOR + text[idx:idx + len(q)] + RESET
                snippet = text[snippet_start:idx] + highlighted + text[idx + len(q):snippet_end]
                snippets.append("..." + snippet.strip() + "...")
                start = idx + len(q)

        return snippets

    for video_id, content in data.items():
        info = content.get("video_info", {})
        title = info.get("title", "[no title]").strip()
        description = info.get("description", "").strip()
        comments = content.get("comments", [])

        header = f"{video_id} | {title}"
        print(f"\n{video_id} | {title}")
        print("=" * len(header))

        desc_snips = extract_snippets(description, query_list)
        if desc_snips:
            print("desc:")
            for s in desc_snips:
                print(f"  {s}")

        for comment in comments:
            author = comment.get("author_name", "[unknown]")
            c_text = comment.get("text", "")
            c_snips = extract_snippets(c_text, query_list)
            if c_snips:
                print(f"{author}:")
                for s in c_snips:
                    print(f"  {s}")

            for reply in comment.get("replies", []):
                r_author = reply.get("author_name", "[unknown]")
                r_text = reply.get("text", "")
                r_snips = extract_snippets(r_text, query_list)
                if r_snips:
                    print(f"  ↳ {r_author}:")
                    for s in r_snips:
                        print(f"    {s}")
