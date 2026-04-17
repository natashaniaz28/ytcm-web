
import json, logging, re, os

from collections import defaultdict
from YTCM_io_utils  import load_existing_comments
from YTCM_tubescope import analyze_comments

logger = logging.getLogger(__name__)


def safeint(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def safe_write_json(data, target_file):
    temp_file = target_file + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, target_file)
    except Exception as e:
        logger.error(f"Error: could not write to '{target_file}': {e}.")
        if os.path.exists(temp_file):
            os.remove(temp_file)


def is_youtube_video_id(id_string):
    return bool(re.compile(r"^[A-Za-z0-9_-]{11}$").match(id_string))


def check_pending_downloads(filename):
    try:
        with open(filename, "r") as id_file:
            temp_ids = [line.strip() for line in id_file if line.strip()]
        if temp_ids:
            return len(temp_ids)
        else:
            return 0
    except Exception as e:
        logger.error(f"Could not check for pending downloads in '{filename}': {e}.")
        return -1


def merge_schemas(schema1, schema2):
    if isinstance(schema1, dict) and isinstance(schema2, dict):
        merged = dict(schema1)
        for key, value in schema2.items():
            if key in merged:
                merged[key] = merge_schemas(merged[key], value)
            else:
                merged[key] = value
        return merged
    elif isinstance(schema1, list) and isinstance(schema2, list):
        return schema1 + schema2
    elif isinstance(schema1, list):
        return schema1 + [schema2]
    elif isinstance(schema2, list):
        return [schema1] + schema2
    else:
        return schema1


def validate_data_structure(file_path, verbose=True):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            json_data = json.load(file)
    except json.JSONDecodeError as e:
        logger.error(f"JSON error in '{file_path}': {e}.")
        print("fJSON error in '{file_path}'.")
        return
    except FileNotFoundError:
        logger.error(f"File not found error: '{file_path}'.")
        print(f"File not found error: '{file_path}'.")
        return

    if not isinstance(json_data, dict):
        logger.error("Error: no (dict) object found on top level.")
        print(f"JSON structure in '{file_path}' is invalid.")
        return

    def extract_schema(obj):
        if isinstance(obj, dict):
            return {
                key: extract_schema(value) for key, value in obj.items()
            }
        elif isinstance(obj, list):
            combined_schema = {}
            for item in obj:
                item_schema = extract_schema(item)
                combined_schema = merge_schemas(combined_schema, item_schema)
            return [combined_schema]
        else:
            return type(obj).__name__

    combined_schema = {}
    for video_id, video_entry in json_data.items():
        if not isinstance(video_entry, dict):
            logger.warning(f"Warning: ID '{video_id}' has no object.")
            print(f"Problem encountered in VideoID {video_id}. Continuing")
            continue

        entry_schema = extract_schema(video_entry)
        combined_schema = merge_schemas(combined_schema, entry_schema)

    def print_schema(schema, indent=0, root="video_ID"):
        indent_str = "  " * indent
        if isinstance(schema, dict):
            print(f"{indent_str}\"{root}\" (dict):")
            for key, value in schema.items():
                print_schema(value, indent + 1, key)
        elif isinstance(schema, list):
            print(f"{indent_str}\"{root}\" (list):")
            if schema:
                print_schema(schema[0], indent + 1, "<item>")
            else:
                print(f"{indent_str}  <empty>")
        else:
            print(f"{indent_str}\"{root}\" ({schema})")

    if verbose:
        print_schema(combined_schema)


def get_df_comments(filename):
    data = load_existing_comments(filename)
    if not data:
        print("Error: Could not load data.")
        return None, None

    all_comments = []
    for vid, content in data.items():
        all_comments.extend(content["comments"])
    df = analyze_comments(all_comments)
    df["date"] = df["date"].dt.tz_localize(None)        # delete timezone info

    return df, data



def add_occurrence(occurrences, bucket, id, path):
    if id is None:
        return

    id = str(id)
    if bucket not in occurrences:
        occurrences[bucket] = defaultdict(list)

    occurrences[bucket][id].append(path)


def find_duplicate_ids(data, video_bucket_name="video_id", comment_bucket_name="comment_id",
                       reply_bucket_name="reply_id", comments_key="comments", replies_key="replies",
                       comment_id_key="youtube_comment_id", reply_id_key="youtube_reply_id",
                       video_id_field_fallback=None):
    """
    Scan the dataset for duplicate IDs
    """

    occurrences = {}

    if isinstance(data, dict):
        for vid in data.keys():
            add_occurrence(occurrences, video_bucket_name, vid, f"/{vid}")
    elif isinstance(data, list) and video_id_field_fallback:
        for i, item in enumerate(data):
            if isinstance(item, dict):
                add_occurrence(occurrences, video_bucket_name, item.get(video_id_field_fallback), f"/videos[{i}]")

    def walk_video(vid, node, base_path):
        if not isinstance(node, dict):
            return
        comments = node.get(comments_key, [])
        if isinstance(comments, list):
            for ci, c in enumerate(comments):
                cpath = f"{base_path}/{comments_key}[{ci}]"
                if isinstance(c, dict):
                    add_occurrence(occurrences, comment_bucket_name, c.get(comment_id_key), cpath)
                    replies = c.get(replies_key, [])
                    if isinstance(replies, list):
                        for ri, r in enumerate(replies):
                            rpath = f"{cpath}/{replies_key}[{ri}]"
                            if isinstance(r, dict):
                                add_occurrence(occurrences, reply_bucket_name, r.get(reply_id_key), rpath)

    if isinstance(data, dict):
        for vid, payload in data.items():
            walk_video(str(vid), payload, f"/{vid}")
    elif isinstance(data, list):
        for i, payload in enumerate(data):
            walk_video(f"videos[{i}]", payload, f"/videos[{i}]")

    dupes = {}
    for bucket, id_map in occurrences.items():
        for _id, paths in id_map.items():
            if len(paths) > 1:
                if bucket not in dupes:
                    dupes[bucket] = {}
                dupes[bucket][_id] = paths

    return dupes, occurrences

def print_dupe_report(dupes):
    if not dupes:
        print("✅ No duplicate IDs found in any bucket.")
        return
    for bucket, id_map in dupes.items():
        print(f"\nDuplicates in bucket '{bucket}':")
        for _id, paths in id_map.items():
            print(f"  - ID '{_id}' appears {len(paths)}x")
            for p in paths[:10]:
                print(f"      • {p}")
            if len(paths) > 10:
                print(f"      • … (+{len(paths)-10} more)")


def duplicate_check(file_path, comments_key="comments", replies_key="replies", comment_id_key="youtube_comment_id",
                    reply_id_key="youtube_reply_id"):
    """
    Load JSON and run the duplicate finder with dataset defaults.
    """

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    dupes, occurrences = find_duplicate_ids(
        data,
        comments_key=comments_key,
        replies_key=replies_key,
        comment_id_key=comment_id_key,
        reply_id_key=reply_id_key
    )
    print_dupe_report(dupes)
    return dupes, occurrences


def string_len(x):
    try:
        return len(x)
    except Exception:
        return 0


def content_score(obj):
    """
    Higher score means 'richer' item (which will be kept).
    """

    if obj is None:
        return 0

    if isinstance(obj, dict):
        score = len(obj)  # number of keys
        for v in obj.values():
            score += content_score(v)
        return score

    if isinstance(obj, list):
        score = len(obj)  # number of items
        for it in obj:
            score += content_score(it)
        return score

    if isinstance(obj, (str,)):
        return 1 + string_len(obj)
    if isinstance(obj, (int, float, bool)):
        return 1

    return 0


def parse_segment(seg):
    """
    Parse a path segment like comments[3] and returns (key, index).
    """

    if "[" in seg and seg.endswith("]"):
        key = seg[:seg.index("[")]
        idx_str = seg[seg.index("[")+1:-1]

        try:
            idx = int(idx_str)
        except ValueError:
            idx = None

        return key, idx

    return seg, None


def resolve_parent_and_index(data, path):
    """
    Given a path like '/VIDEO123/comments[4]' or '/VIDEO123/comments[4]/replies[2]',
    return (parent_list, index) so that parent_list[index] is the target item.
    If the last query is into a dict (no index), returns (parent_container, key).
    """

    if not path or path[0] != "/":
        raise ValueError(f"Unsupported path format: {path}")

    node = data
    parent = None
    key_or_index = None

    # split and ignore first empty segment due to leading '/'
    parts = [p for p in path.split("/") if p]

    for i, seg in enumerate(parts):
        key, idx = parse_segment(seg)

        if isinstance(node, dict):
            if key not in node:
                # Path became invalid after previous edits; signal by returning None
                return None, None
            parent = node
            key_or_index = key
            node = node[key]
            if idx is not None:
                # expect list
                if not isinstance(node, list):
                    return None, None
                if idx < 0 or idx >= len(node):
                    return None, None
                parent = node
                key_or_index = idx
                node = node[idx]
        elif isinstance(node, list):
            # when current node is a list, segment must provide an index
            if idx is None:
                return None, None
            if idx < 0 or idx >= len(node):
                return None, None
            parent = node
            key_or_index = idx
            node = node[idx]
            # if a key follows after list hop, it will be handled next loop
            if key is not None and key != "":
                # this covers rare cases like '[3]something', which we don't produce
                pass
        else:
            return None, None

    return parent, key_or_index


def gather_items_for_paths(data, paths):
    items = []
    for p in paths:
        parent, key_or_idx = resolve_parent_and_index(data, p)
        if parent is None:
            # item might already be removed by earlier operation in this batch
            continue
        try:
            item = parent[key_or_idx] if isinstance(parent, list) else parent.get(key_or_idx)
        except Exception:
            item = None
        items.append((p, parent, key_or_idx, item))

    return items

def delete_many(grouped):
    """
    grouped: list of tuples (parent_list, index). This function deletes by descending index per parent.
    Returns count of deletions.
    """

    deletions = 0
    # group by parent container identity
    buckets = {}
    for parent, idx in grouped:
        if isinstance(parent, list):
            buckets.setdefault(id(parent), (parent, []))[1].append(idx)
        elif isinstance(parent, dict):
            buckets.setdefault(id(parent), (parent, []))[1].append(idx)  # here idx is a key
    for _, (parent, indices) in buckets.items():
        # sort appropriately
        if isinstance(parent, list):
            for i in sorted(set(indices), reverse=True):
                try:
                    del parent[i]
                    deletions += 1
                except Exception:
                    pass
        else:
            # dict: indices represent keys; delete unique keys
            for k in set(indices):
                if k in parent:
                    try:
                        del parent[k]
                        deletions += 1
                    except Exception:
                        pass
    return deletions


def clean_dupes(data, dupes, comments_key="comments", replies_key="replies", comment_bucket_name="comment_id",
                reply_bucket_name="reply_id"):
    """
    Purge duplicates in-place based on the 'dupes' structure from find_duplicate_ids.
    Keeps the occurrence with the highest content score; removes the others.
    """

    report = {'kept': {}, 'removed': {}, 'stats': {'removed_count': 0, 'buckets': {}}}

    # We only act on comment/reply buckets, since top-level video IDs are unique as JSON keys.
    for bucket in [comment_bucket_name, reply_bucket_name]:
        if bucket not in dupes:
            continue
        id_map = dupes[bucket]
        for _id, paths in id_map.items():
            # fetch items and compute scores
            packed = gather_items_for_paths(data, paths)
            # filter out paths that no longer resolve (may have been removed by earlier steps)
            packed = [t for t in packed if t[3] is not None]
            if len(packed) <= 1:
                continue

            scored = []
            for pth, parent, key_or_idx, item in packed:
                score = content_score(item)
                # small bonus if comment has replies (for comment bucket), to prefer richer threads
                if bucket == comment_bucket_name and isinstance(item, dict):
                    reps = item.get(replies_key, [])
                    if isinstance(reps, list):
                        score += max(0, len(reps)) * 2
                scored.append((score, pth, parent, key_or_idx))

            # determine winner (highest score, stable by original order)
            scored.sort(key=lambda x: (-x[0], paths.index(x[1])))
            keep_score, keep_path, keep_parent, keep_k = scored[0]

            # everything else to delete
            to_delete = []
            removed_paths = []
            for sc, pth, par, k in scored[1:]:
                to_delete.append((par, k))
                removed_paths.append(pth)

            # perform deletions safely (descending indices per parent list)
            removed_count = delete_many(to_delete)

            # write report
            report['kept'].setdefault(bucket, {})[_id] = keep_path
            if removed_paths:
                report['removed'].setdefault(bucket, {})[_id] = removed_paths
            report['stats']['removed_count'] += removed_count
            report['stats']['buckets'][bucket] = report['stats']['buckets'].get(bucket, 0) + removed_count

    return report


def load_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
