import json, os, sys
import networkx          as nx
import matplotlib        as mpl
import matplotlib.pyplot as plt
import numpy             as np

from collections import Counter
from dataclasses import dataclass
from datetime    import datetime, timezone
from typing      import Optional

from YTCM_config import TUBECONNECTSETTINGS

@dataclass
class Edge:
    source_channel_id: str
    target_video_id  : str
    event_type       : str
    weight           : int
    fandom_label     : str
    comment_id       : Optional[str]
    reply_id         : Optional[str]
    comment_datetime : Optional[str]
    reply_datetime   : Optional[str]


def parse_dt(timestamp):
    """
    Parse and convert to UTC timestamps (all YouTube info should be in UTC when downloaded).
    """

    if not timestamp:
        return None

    try:
        if timestamp.endswith("Z"):
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)

        return datetime.fromisoformat(timestamp).astimezone(timezone.utc)

    except Exception:
        try:
            base = timestamp.split(".")[0]
            return datetime.fromisoformat(base).replace(tzinfo=timezone.utc)

        except Exception:
            return None


def ensure_channel_exists(channel_map, channel_id):
    """
    Make sure that a channel dict with role flags really exists.
    """

    if channel_id not in channel_map:
        channel_map[channel_id] = {
            "uploader" : False,
            "commenter": False,
            "replier"  : False,
        }

    return channel_map[channel_id]


def provide_roles_set(role_dict):
    result = set()

    if role_dict.get("uploader"):
        result.add("uploader")
    if role_dict.get("commenter"):
        result.add("commenter")
    if role_dict.get("replier"):
        result.add("replier")

    return result


def provide_roles_string(role_dict):
    return ",".join(sorted(provide_roles_set(role_dict)))


def load_fandom_json(path, label, name=None):
    """
    Return data for one fandom (or comments network) from JSON file.
    """

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if name is None:
        name = os.path.splitext(os.path.basename(path))[0]

    fandom = {
        "label"   : label,
        "name"    : name,
        "raw"     : data,
        "videos"  : {},
        "channels": {},
        "edges"   : []
    }

    for video_id, data in data.items():
        vinfo    = data.get("video_info", {}) or {}
        comments = data.get("comments", []) or []

        video_data = {
            "video_id": video_id,
            "fandom_label": label,
            "title": vinfo.get("title"),
            "published_at": vinfo.get("published_at"),
            "channel_id": vinfo.get("channel_id"),
            "channel_name": vinfo.get("channel_name"),
            "duration": vinfo.get("duration"),
            "raw": vinfo
        }
        fandom["videos"][video_id] = video_data

        if video_data["channel_id"]:                                # edge: uploader
            channel = ensure_channel_exists(fandom["channels"], video_data["channel_id"])
            channel["uploader"] = True
            fandom["edges"].append(Edge(video_data["channel_id"], video_id, "uploader", 1, label, None, None, None, None))

        for comment in comments:                                    # comments and replies
            comment_channel = comment.get("author_channel_id")
            if comment_channel:
                ch = ensure_channel_exists(fandom["channels"], comment_channel)
                ch["commenter"] = True
                fandom["edges"].append(Edge(comment_channel, video_id, "commenter", 1, label, comment.get("youtube_comment_id"), None, comment.get("date"), None))

            for reply in comment.get("replies", []) or []:
                reply_channel = reply.get("author_channel_id")
                if reply_channel:
                    ch = ensure_channel_exists(fandom["channels"], reply_channel)
                    ch["replier"] = True
                    fandom["edges"].append(Edge(reply_channel, video_id, "replier", 1, label, comment.get("youtube_comment_id"), reply.get("youtube_reply_id"), None, reply.get("date")))

    return fandom


def get_overlap(fandoms, basis):
    """
    Calculate the data overlap period between fandom datasets.
    """

    if basis == "none":
        return None, None

    overlap_start, overlap_end = None, None

    for fandom_data in fandoms:
        fandom_start, fandom_end = None, None

        if basis == "video":
            for video in fandom_data.get("videos", {}).values():
                timestamp = video.get("published_at")
                if timestamp:
                    date = parse_dt(timestamp)
                else:
                    date = None

                if date:
                    if fandom_start is None:
                        fandom_start = date
                    else:
                        fandom_start = min(fandom_start, date)

                    if fandom_end is None:
                        fandom_end = date
                    else:
                        fandom_end = max(fandom_end, date)

        elif basis == "comment":
            for edge in fandom_data.get("edges", []):
                timestamp = None
                if edge.event_type == "commenter":
                    timestamp = edge.comment_datetime
                elif edge.event_type == "replier":
                    timestamp = edge.reply_datetime

                if timestamp:
                    date = parse_dt(timestamp)
                else:
                    date = None

                if date:
                    if fandom_start is None:
                        fandom_start = date
                    else:
                        fandom_start = min(fandom_start, date)

                    if fandom_end is None:
                        fandom_end = date
                    else:
                        fandom_end = max(fandom_end, date)

        if fandom_start is not None and fandom_end is not None:
            if overlap_start is None:
                overlap_start = fandom_start
            else:
                overlap_start = max(overlap_start, fandom_start)

            if overlap_end is None:
                overlap_end = fandom_end
            else:
                overlap_end = min(overlap_end, fandom_end)

    if overlap_start is None or overlap_end is None or overlap_start > overlap_end:
        return None, None

    return overlap_start, overlap_end


def update_channel_roles(fandom):
    """
    Look through the edges of a fandom and reevaluate the channel roles.
    Updates may be necessary if time caps were applied.
    """

    new_roles = {}

    for edge in fandom["edges"]:
        source_id = edge.source_channel_id
        event_type = edge.event_type
        if source_id not in new_roles:
            new_roles[source_id] = {
                "uploader" : False,
                "commenter": False,
                "replier"  : False,
            }

        if event_type == "uploader":
            new_roles[source_id]["uploader"] = True
        elif event_type == "commenter":
            new_roles[source_id]["commenter"] = True
        elif event_type == "replier":
            new_roles[source_id]["replier"] = True

    fandom["channels"] = new_roles


def cap_fandoms_to_overlap_time(fandoms, start, end, basis):
    """
    Extract the overlap period from the fandom datasets.
    """

    if start is None or end is None or basis == "none":
        return

    for fandom in fandoms:
        if basis == "video":
            keep_video_ids = set()
            for video_id, video in list(fandom["videos"].items()):
                ts = video.get("published_at")
                dt = parse_dt(ts) if ts else None
                if dt and (start <= dt <= end):
                    keep_video_ids.add(video_id)
                else:
                    del fandom["videos"][video_id]

            # Only keep edges that connect to still-existing nodes
            fandom["edges"] = [
                Edge(
                    edge.source_channel_id,
                    edge.target_video_id,
                    edge.event_type,
                    edge.weight,
                    edge.fandom_label,
                    edge.comment_id,
                    edge.reply_id,
                    edge.comment_datetime,
                    edge.reply_datetime
                )
                for edge in fandom["edges"]
                if edge.target_video_id in keep_video_ids
            ]

        elif basis == "comment":
            kept_edges = []
            videos_with_edges = set()
            upload_edges_buffer = []

            # Collect comments & replies
            for edge in fandom["edges"]:

                if edge.event_type == "commenter" and edge.comment_datetime:
                    dt = parse_dt(edge.comment_datetime)
                    if dt and (start <= dt <= end):
                        kept_edges.append(Edge(edge.source_channel_id, edge.target_video_id, edge.event_type, edge.weight,
                                               edge.fandom_label, edge.comment_id, edge.reply_id, edge.comment_datetime, edge.reply_datetime))
                        videos_with_edges.add(edge.target_video_id)

                elif edge.event_type == "replier" and edge.reply_datetime:
                    dt = parse_dt(edge.reply_datetime)
                    if dt and (start <= dt <= end):
                        kept_edges.append(Edge(edge.source_channel_id, edge.target_video_id, edge.event_type, edge.weight,
                                               edge.fandom_label, edge.comment_id, edge.reply_id, edge.comment_datetime, edge.reply_datetime))
                        videos_with_edges.add(edge.target_video_id)

                elif edge.event_type == "uploader":
                    # keep for now, decide later
                    upload_edges_buffer.append(Edge(edge.source_channel_id, edge.target_video_id, edge.event_type, edge.weight,
                                                    edge.fandom_label, edge.comment_id, edge.reply_id, edge.comment_datetime, edge.reply_datetime))

            # Keep edges if video was either published or commented/replied during the overlap time
            for edge in upload_edges_buffer:

                keep = False
                if edge.target_video_id in videos_with_edges:
                    keep = True
                else:
                    video = fandom["videos"].get(edge.target_video_id)
                    if video and video.get("published_at"):
                        dt = parse_dt(video["published_at"])
                        keep = bool(dt and (start <= dt <= end))

                if keep:
                    kept_edges.append(Edge(edge.source_channel_id, edge.target_video_id, edge.event_type, edge.weight,
                                           edge.fandom_label, edge.comment_id, edge.reply_id, edge.comment_datetime, edge.reply_datetime))

            fandom["edges"] = kept_edges

        update_channel_roles(fandom)


def compute_pairwise_overlaps(fandoms):
    """
    Calculate metrics showing how two fandom datasets overlap.
    """

    summary = {}
    channels_by_fandom = {}
    pairwise_results = []

    role_names = ["uploader", "commenter", "replier"]

    summary["fandoms"] = []
    for fandom in fandoms:
        fandom_info = {
            "label"     : fandom["label"],
            "name"      : fandom["name"],
            "n_videos"  : len(fandom["videos"]),
            "n_channels": len(fandom["channels"]),
        }
        summary["fandoms"].append(fandom_info)

    for fandom in fandoms:
        label = fandom["label"]
        channel_ids = set(fandom["channels"].keys())
        channels_by_fandom[label] = channel_ids

    for index_a in range(len(fandoms)):
        for index_b in range(index_a + 1, len(fandoms)):
            fandom_a = fandoms[index_a]
            fandom_b = fandoms[index_b]

            channels_a = channels_by_fandom[fandom_a["label"]]
            channels_b = channels_by_fandom[fandom_b["label"]]

            intersection_all = channels_a & channels_b
            union_all = channels_a | channels_b

            pair_entry = {
                "pair"         : [fandom_a["label"], fandom_b["label"]],
                "overlap_count": len(intersection_all),
                "jaccard"      : (len(intersection_all) / len(union_all)) if union_all else 0.0,
                "role_overlap" : {}
            }

            # Role-based overlaps
            for role in role_names:
                channels_a_with_role = set()
                for channel_id, roles in fandom_a["channels"].items():
                    if roles.get(role):
                        channels_a_with_role.add(channel_id)

                channels_b_with_role = set()
                for channel_id, roles in fandom_b["channels"].items():
                    if roles.get(role):
                        channels_b_with_role.add(channel_id)

                intersection_role = channels_a_with_role & channels_b_with_role
                union_role = channels_a_with_role | channels_b_with_role

                pair_entry["role_overlap"][role] = {
                    "A_count"      : len(channels_a_with_role),
                    "B_count"      : len(channels_b_with_role),
                    "overlap_count": len(intersection_role),
                    "jaccard"      : (len(intersection_role) / len(union_role)) if union_role else 0.0
                }

            pairwise_results.append(pair_entry)

    summary["pairwise"] = pairwise_results

    return summary


def build_labels_and_index(fandoms):
    """
    Build a list of fandom labels and a reference from label to index position.
    """

    labels = []
    for fandom in fandoms:
        labels.append(fandom["label"])

    label_to_index = {}
    for position in range(len(labels)):
        label_to_index[labels[position]] = position

    return labels, label_to_index


def initialize_matrices(labels, role_names):
    """
    Initialize the total interaction matrix and one interaction matrix for each role.
    """

    size = len(labels)

    total_matrix = np.zeros((size, size), dtype=int)

    role_matrices = {}
    for role in role_names:
        role_matrices[role] = np.zeros((size, size), dtype=int)

    return total_matrix, role_matrices


def map_channel_to_fandom_labels(fandoms):
    """
    Build a reference from channel IDs to fandom labels in which each channel appears.
    """

    channel_to_fandom_labels = {}

    for fandom in fandoms:
        current_label = fandom["label"]
        for channel_id in fandom["channels"].keys():
            if channel_id not in channel_to_fandom_labels:
                channel_to_fandom_labels[channel_id] = set()

            channel_to_fandom_labels[channel_id].add(current_label)

    return channel_to_fandom_labels


def accumulate_interaction_matrices(fandoms, label_to_index, channel_to_fandom_labels, total_matrix, role_matrices):
    """
    Build both the total and the per-role interaction matrices.
    """

    for fandom in fandoms:
        for edge in fandom["edges"]:

            target_label = edge.fandom_label
            target_index = label_to_index[target_label]

            source_labels_for_channel = channel_to_fandom_labels.get(edge.source_channel_id, set())
            for source_label in source_labels_for_channel:
                source_index = label_to_index[source_label]
                weight_value = int(edge.weight)

                total_matrix[source_index, target_index] += weight_value
                if edge.event_type in role_matrices:
                    role_matrices[edge.event_type][source_index, target_index] += weight_value


def compute_cross_share(labels, label_to_index, total_matrix):
    """
    Calculate the share of outgoing interactions from each source fandom toward the other fandoms ("cross-share").
    """

    result = {}

    for source_label in labels:
        source_index = label_to_index[source_label]

        total_outgoing = int(total_matrix[source_index, :].sum())
        diagonal_value = int(total_matrix[source_index, source_index])
        outgoing_to_other = int(total_outgoing - diagonal_value)

        if total_outgoing > 0:
            share_value = outgoing_to_other / total_outgoing
        else:
            share_value = 0.0

        result[source_label] = {
            "out_total": total_outgoing,
            "out_cross": outgoing_to_other,
            "cross_share": share_value
        }

    return result


def compute_cross_share_by_role(labels, label_to_index, role_names, role_matrices):
    """
    As above, but based on the role-specific interactions.
    """

    result = {}
    for role in role_names:
        result[role] = {}

    for source_label in labels:
        source_index = label_to_index[source_label]

        for role in role_names:
            row_sum = int(role_matrices[role][source_index, :].sum())
            diagonal_value = int(role_matrices[role][source_index, source_index])
            outgoing_to_other = int(row_sum - diagonal_value)

            if row_sum > 0:
                share_value = outgoing_to_other / row_sum
            else:
                share_value = 0.0

            result[role][source_label] = {
                "out_total": row_sum,
                "out_cross": outgoing_to_other,
                "cross_share": share_value
            }

    return result


def compute_cross_channels(fandoms, labels, role_names, channel_to_fandom_labels):
    """
    Count the unique channels from each fandom interacting with videos in other fandoms (overall and by role).
    """

    cross_channels = {}
    for label in labels:
        cross_channels[label] = set()

    cross_channels_by_role = {}
    for role in role_names:
        cross_channels_by_role[role] = {}
        for label in labels:
            cross_channels_by_role[role][label] = set()

    for fandom in fandoms:
        for edge in fandom["edges"]:

            target_label = edge.fandom_label
            source_labels_for_channel = channel_to_fandom_labels.get(edge.source_channel_id, set())

            for source_label in source_labels_for_channel:
                if source_label != target_label:
                    cross_channels[source_label].add(edge.source_channel_id)
                    if edge.event_type in cross_channels_by_role:
                        cross_channels_by_role[edge.event_type][source_label].add(edge.source_channel_id)

    cross_channel_counts = {}
    for label in labels:
        cross_channel_counts[label] = len(cross_channels[label])

    cross_channel_counts_by_role = {}
    for role in role_names:
        cross_channel_counts_by_role[role] = {}
        for label in labels:
            cross_channel_counts_by_role[role][label] = len(cross_channels_by_role[role][label])

    return cross_channel_counts, cross_channel_counts_by_role


def compute_edges_per_video(fandoms):
    """
    Calculate mean and median incoming edge weights per video for each fandom.
    """

    result = {}

    for fandom in fandoms:
        target_label = fandom["label"]

        incoming_counts_by_video = Counter()
        for edge in fandom["edges"]:

            if edge.fandom_label == target_label:
                incoming_counts_by_video[edge.target_video_id] += int(edge.weight)

        counts = []
        for video_id in list(fandom["videos"].keys()):
            counts.append(incoming_counts_by_video.get(video_id, 0))

        if len(counts) > 0:
            values_array = np.array(counts, dtype=float)
            mean_value = float(values_array.mean())
            median_value = float(np.median(values_array))
            number_of_videos = int(len(values_array))
        else:
            mean_value = 0.0
            median_value = 0.0
            number_of_videos = 0

        result[target_label] = {
            "mean": mean_value,
            "median": median_value,
            "n_videos": number_of_videos
        }

    return result


def matrices_to_lists(role_names, total_matrix, role_matrices):
    """
    Convert matrices to lists.
    """

    interaction_matrix = total_matrix.tolist()

    interaction_matrix_by_role = {}
    for role in role_names:
        interaction_matrix_by_role[role] = role_matrices[role].tolist()

    return interaction_matrix, interaction_matrix_by_role


def compute_cross_fandom_interactions(fandoms):
    """
    Calculate cross-fandom interaction info.
    """

    role_names = ["uploader", "commenter", "replier"]

    # Preparation & accumulation
    labels, label_to_index = build_labels_and_index(fandoms)
    total_matrix, role_matrices = initialize_matrices(labels, role_names)
    channel_to_fandom_labels = map_channel_to_fandom_labels(fandoms)

    accumulate_interaction_matrices(
        fandoms,
        label_to_index,
        channel_to_fandom_labels,
        total_matrix,
        role_matrices,
    )

    # Calculate metrics
    cross_share = compute_cross_share(labels, label_to_index, total_matrix)
    cross_share_by_role = compute_cross_share_by_role(labels, label_to_index, role_names, role_matrices)

    # Process cross-fandom channel links
    cross_channel_counts, cross_channel_counts_by_role = compute_cross_channels(
        fandoms, labels, role_names, channel_to_fandom_labels
    )

    # Calculate edges per video and convert data
    edges_per_video = compute_edges_per_video(fandoms)
    interaction_matrix, interaction_matrix_by_role = matrices_to_lists(role_names, total_matrix, role_matrices)

    return {
        "labels"                            : labels,
        "interaction_matrix"                : interaction_matrix,
        "interaction_matrix_by_role"        : interaction_matrix_by_role,
        "cross_share"                       : cross_share,
        "cross_share_by_role"               : cross_share_by_role,
        "cross_fandom_channel_count"        : cross_channel_counts,
        "cross_fandom_channel_count_by_role": cross_channel_counts_by_role,
        "edges_per_video"                   : edges_per_video
    }


def compute_summary(fandoms, overlap_time):
    """
    Calculate the combined summary of pairwise overlaps and cross-fandom interactions, including the overlap time info.
    """

    base = compute_pairwise_overlaps(fandoms)
    cross = compute_cross_fandom_interactions(fandoms)
    base.update(cross)

    start, end, basis = overlap_time

    if start and end:
        base["overlap_window"] = {
            "basis"    : basis,
            "start_utc": start.isoformat(),
            "end_utc"  : end.isoformat(),
            "days"     : (end - start).days
        }
    else:
        base["overlap_window"] = {
            "basis"    : basis,
            "start_utc": None,
            "end_utc"  : None,
            "days"     : None
        }

    return base


def add_video_nodes(graph, fandoms):
    """
    Add all video nodes to the graph with basic metadata.
    """

    for fandom in fandoms:
        fandom_label = fandom["label"]

        for video_id, video_meta in fandom["videos"].items():
            graph.add_node(
                video_id,
                label=video_meta.get("title") or video_id,
                node_type="video",
                fandoms=fandom_label,
                roles="",
                fandom_count=1,
                in_multiple=False,
                degree_est=0,
                video_title=video_meta.get("title") or "",
                video_published_at=video_meta.get("published_at") or "",
                video_channel_name=video_meta.get("channel_name") or "",
            )

    return graph


def ensure_channel_node(graph, fandom, channel_id):
    """
    Ensure that a channel node exists; if it already exists, merge metadata.
    """

    if not graph.has_node(channel_id):
        roles_info = fandom["channels"].get(channel_id, {})
        graph.add_node(
            channel_id,
            label=channel_id,
            node_type="channel",
            fandoms=fandom["label"],
            roles=provide_roles_string(roles_info),
            fandom_count=1,
            in_multiple=False,
            degree_est=0,
            video_title="",
            video_published_at="",
            video_channel_name="",
        )

        return graph

    node_data = graph.nodes[channel_id]
    if node_data.get("node_type") == "channel":
        existing_labels = set(
            [label for label in (node_data.get("fandoms") or "").split(",") if label]
        )
        if fandom["label"] not in existing_labels:
            existing_labels.add(fandom["label"])
            node_data["fandoms"] = ",".join(sorted(existing_labels))
            node_data["fandom_count"] = len(existing_labels)
            if node_data["fandom_count"] >= 2:
                node_data["in_multiple"] = True
            else:
                node_data["in_multiple"] = False

        previous_roles = set(
            [role for role in (node_data.get("roles") or "").split(",") if role]
        )
        current_roles = provide_roles_set(fandom["channels"].get(channel_id, {}))
        node_data["roles"] = ",".join(sorted(previous_roles | current_roles))

    return graph


def add_edge_and_update_degrees(graph, source_channel_id, target_video_id, event_type, weight, fandom_origin,
                                comment_id, reply_id):
    """
    Add an edge from channel to video, update degrees for both nodes.
    """

    graph.add_edge(
        source_channel_id,
        target_video_id,
        edge_type=event_type,
        weight=int(weight),
        fandom_origin=fandom_origin,
        video_id=target_video_id if event_type in {"uploader", "commenter", "replier"} else "",
        comment_id=comment_id or "",
        reply_id=reply_id or ""
    )

    # Update degree estimate: sum of all edge weights connected to the node
    graph.nodes[source_channel_id]["degree_est"] = int(graph.nodes[source_channel_id].get("degree_est", 0)) + int(weight)
    graph.nodes[target_video_id]["degree_est"] = int(graph.nodes[target_video_id].get("degree_est", 0)) + int(weight)

    return graph


def build_graph(fandoms):
    """
    Build a graph (as a "MultiDiGraph)" from the given fandom datasets.
    """

    graph = nx.MultiDiGraph()

    graph = add_video_nodes(graph, fandoms)                 # add video nodes plus metadata

    for fandom in fandoms:                                  # add channels & edge info
        for edge in fandom["edges"]:
            source_channel_id = edge.source_channel_id
            target_video_id = edge.target_video_id
            event_type = edge.event_type
            weight = edge.weight
            fandom_origin = edge.fandom_label
            comment_id = edge.comment_id
            reply_id = edge.reply_id

            # Ensure channel node exists, combine the metadata
            graph = ensure_channel_node(graph, fandom, source_channel_id)

            # Skip if the target video node was filtered out earlier
            if not graph.has_node(target_video_id):
                continue

            # Add edge, update degrees
            graph = add_edge_and_update_degrees(graph, source_channel_id, target_video_id, event_type, weight,
                                                fandom_origin, comment_id, reply_id)

    return graph


def export_gexf(G, out_path, graph_label=None):
    """
    Save the graph as GEXF for Gephi.
    """

    if graph_label:
        G.graph["label"] = graph_label

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    nx.write_gexf(G, out_path, encoding="utf-8")

    return out_path


def save_summary_json(summary, out_path):
    """
    Save general summary info as JSON.
    """

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return out_path


def plot_interaction_matrix(fandom_labels, matrix, title):
    array = np.array(matrix, dtype=float)

    fig, ax = plt.subplots()
    im = ax.imshow(array)

    ticks = np.arange(len(fandom_labels))
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    ax.set_xticklabels(fandom_labels)
    ax.set_yticklabels(fandom_labels)

    ax.set_xlabel("Target fandom")
    ax.set_ylabel("Source fandom")
    ax.set_title(title)

    cmap = im.get_cmap()
    norm = im.norm

    n_rows, n_cols = array.shape
    for row in range(n_rows):
        for col in range(n_cols):
            val = array[row, col]

            rgba = cmap(norm(val))
            r, g, b, _ = rgba
            brightness = 0.299*r + 0.587*g + 0.114*b
            text_color = "black" if brightness > 0.5 else "white"

            ax.text(col, row, str(int(val)),
                    ha="center", va="center",
                    color=text_color, fontsize=8)

    fig.colorbar(im, ax=ax)
    plt.tight_layout()
    plt.show()


def plot_bar(data_dict, title, ylabel):
    """
    Plot a bar chart from a dictionary.
    """

    labels = list(data_dict.keys())
    values = [data_dict[label] for label in labels]
    positions = np.arange(len(labels))

    figure = plt.figure()
    axes = figure.gca()
    axes.bar(positions, values)

    axes.set_xticks(positions)
    axes.set_xticklabels(labels, rotation=45, ha="right")
    axes.set_ylabel(ylabel)
    axes.set_title(title)

    plt.tight_layout()
    plt.show()


def generate_plots(summary):
    """
    Create overview plots.
    """

    labels = summary.get("labels", [])
    interaction_matrix = summary.get("interaction_matrix", [])
    plot_interaction_matrix(labels, interaction_matrix, "Cross-fandom interaction matrix (edges)")

    interaction_matrix_by_role = summary.get("interaction_matrix_by_role", {})
    for role in interaction_matrix_by_role:
        role_matrix = interaction_matrix_by_role[role]
        plot_interaction_matrix(labels, role_matrix, f"Interaction matrix by role: {role}")

    cross_share = summary.get("cross_share", {})
    cross_share_map = {}
    for label in labels:
        value = 0.0
        if label in cross_share and "cross_share" in cross_share[label]:
            value = cross_share[label]["cross_share"]
        cross_share_map[label] = value
    plot_bar(cross_share_map, "Cross-share by source fandom", "share")

    cross_share_by_role = summary.get("cross_share_by_role", {})
    for role in cross_share_by_role:
        role_map = {}
        per_label = cross_share_by_role[role]
        for label in labels:
            value = 0.0
            if label in per_label and "cross_share" in per_label[label]:
                value = per_label[label]["cross_share"]
            role_map[label] = value
        plot_bar(role_map, f"Cross-share by source fandom ({role})", "share")

    cross_fandom_channel_count = summary.get("cross_fandom_channel_count", {})
    overall_counts = {}
    for label in labels:
        overall_counts[label] = cross_fandom_channel_count.get(label, 0)
    plot_bar(overall_counts, "Unique channels interacting cross-fandom", "count")

    cross_fandom_channel_count_by_role = summary.get("cross_fandom_channel_count_by_role", {})
    for role in cross_fandom_channel_count_by_role:
        role_counts_map = {}
        per_label_counts = cross_fandom_channel_count_by_role[role]
        for label in labels:
            role_counts_map[label] = per_label_counts.get(label, 0)
        plot_bar(role_counts_map, f"Unique channels cross-fandom ({role})", "count")

    edges_per_video = summary.get("edges_per_video", {})
    mean_map = {}
    median_map = {}
    for label in labels:
        stats = edges_per_video.get(label, {})
        mean_map[label] = stats.get("mean", 0.0)
        median_map[label] = stats.get("median", 0.0)

    plot_bar(mean_map, "Edges per video (mean) by target fandom", "edges/video")
    plot_bar(median_map, "Edges per video (median) by target fandom", "edges/video")


def plot_jaccard_over_time(fandoms, include_by_role=True, out_dir="output"):
    """
    Plot the development of the Jaccard index over time.
    """

    os.makedirs(out_dir, exist_ok=True)
    role_names = ["uploader", "commenter", "replier"]
    channel_sets = {}
    video_year = {}
    fandom_label_by_video = {}

    for fandom in fandoms:
        label = fandom["label"]
        channel_sets[label] = {}
        for vid, vmeta in fandom.get("videos", {}).items():
            fandom_label_by_video[vid] = label
            ts = vmeta.get("published_at")
            dt = parse_dt(ts) if ts else None
            if dt:
                video_year[vid] = dt.year

    def ensure_year(label, year):
        if year is None:
            return
        if year not in channel_sets[label]:
            channel_sets[label][year] = {
                "all"      : set(),
                "uploader" : set(),
                "commenter": set(),
                "replier"  : set(),
            }

    for fandom in fandoms:
        label = fandom["label"]
        for edge in fandom.get("edges", []):
            ch_id = edge.source_channel_id
            if edge.event_type == "uploader":
                yr = video_year.get(edge.target_video_id, None)
                ensure_year(label, yr)
                if yr is not None:
                    channel_sets[label][yr]["uploader"].add(ch_id)
                    channel_sets[label][yr]["all"].add(ch_id)
            elif edge.event_type == "commenter":
                dt = parse_dt(edge.comment_datetime) if edge.comment_datetime else None
                yr = dt.year if dt else None
                ensure_year(label, yr)
                if yr is not None:
                    channel_sets[label][yr]["commenter"].add(ch_id)
                    channel_sets[label][yr]["all"].add(ch_id)
            elif edge.event_type == "replier":
                dt = parse_dt(edge.reply_datetime) if edge.reply_datetime else None
                yr = dt.year if dt else None
                ensure_year(label, yr)
                if yr is not None:
                    channel_sets[label][yr]["replier"].add(ch_id)
                    channel_sets[label][yr]["all"].add(ch_id)

    labels = [f["label"] for f in fandoms]
    unique_pairs = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            unique_pairs.append((labels[i], labels[j]))

    all_years = sorted({yr for lab in channel_sets for yr in channel_sets[lab].keys()})
    details = {}

    for A, B in unique_pairs:
        if A not in channel_sets or B not in channel_sets:
            continue

        x_years = []
        y_jacc_all = []
        details[(A, B)] = {}

        for yr in all_years:
            A_all = channel_sets[A].get(yr, {}).get("all", set())
            B_all = channel_sets[B].get(yr, {}).get("all", set())

            inter = A_all & B_all
            union = A_all | B_all

            if len(union) > 0:
                jacc = len(inter) / len(union)
            else:
                jacc = 0.0

            x_years.append(yr)
            y_jacc_all.append(jacc)

            entry = {
                "intersection": sorted(inter),
                "A_only"      : sorted(A_all - B_all),
                "B_only"      : sorted(B_all - A_all),
            }

            if include_by_role:
                entry["by_role"] = {}
                for role in role_names:
                    A_r = channel_sets[A].get(yr, {}).get(role, set())
                    B_r = channel_sets[B].get(yr, {}).get(role, set())
                    entry["by_role"][role] = {
                        "intersection": sorted(A_r & B_r),
                        "A_only": sorted(A_r - B_r),
                        "B_only": sorted(B_r - A_r),
                    }

            details[(A, B)][yr] = entry

        if not x_years:
            continue

        plt.figure()
        plt.plot(x_years, y_jacc_all, marker="o")

        plt.xlabel("Year")
        plt.ylabel("Jaccard Index")
        plt.title(f"Jaccard over Time: {A} ↔ {B}")
        plt.xticks(x_years, rotation=45, ha="right")

        if y_jacc_all and max(y_jacc_all) > 0:
            plt.ylim(0, max(y_jacc_all))
        else:
            plt.ylim(0, 1)

        plt.tight_layout()

        png_path = os.path.join(out_dir, f"jaccard_{A}__and__{B}.png")
        plt.savefig(png_path, dpi=150)

        plt.show()
        plt.close()

        json_path = os.path.join(out_dir, f"jaccard_{A}__and__{B}.details.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(details[(A, B)], f, ensure_ascii=False, indent=2)

    return details


def tubeconnect():
    logo = """
┌───────────────────────────────────────────────────────────┐
│          ●───●───●                  ●───●───●             │
│         ╱    │    ╲   Welcome to   ╱    │    ╲            │
│      ●─●     ●     ●──────────────●     ●     ●─●         │
│         ╲    │    ╱  TubeConnect!  ╲    │    ╱            │
│          ●───●───●                  ●───●───●             │
└───────────────────────────────────────────────────────────┘
"""
    print(logo)

    # Step 1: Define the input JSONs (YTCM data). This is a list of file path, short label, description.
    #         Then, load it.
    input_data = TUBECONNECTSETTINGS

    print("Settings:", input_data)

    if not input("Continue (y/n)? ").lower().startswith("y"):
        return

    fandoms = []
    for path, label, name in input_data:
        fandoms.append(load_fandom_json(path, label=label, name=name))

    # Step 2: Overlap capping method ("none", "video", "comment").
    cap_basis = "comment"

    start, end = get_overlap(fandoms, basis=cap_basis)
    if start and end:
        print(f"Applying {cap_basis}-based overlap window: {start.isoformat()} to {end.isoformat()}")
        cap_fandoms_to_overlap_time(fandoms, start, end, basis=cap_basis)
    elif cap_basis != "none":
        print("Could not compute a valid overlapping window; proceeding without capping.")

    # Step 3: Analyze, export & display
    summary = compute_summary(fandoms, (start, end, cap_basis))
    graph = build_graph(fandoms)

    output_gexf_path = "output/fandom_network.gexf"
    label_str = " vs ".join([fandom["name"] for fandom in fandoms])
    export_gexf(graph, output_gexf_path, graph_label=label_str)
    print(f"GEXF exported: {output_gexf_path}.")

    summary_path = "output/fandom_network.summary.json"
    save_summary_json(summary, summary_path)
    print(f"Summary written: {summary_path}")

    generate_plots(summary)

    plot_jaccard_over_time(fandoms)


if __name__ == "__main__":
    tubeconnect()
    sys.exit()
