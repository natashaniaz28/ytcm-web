""" TubeGraph contains a set of network analysis functions for the YouTube Comment Miner.

Some functions adapt example code and usage patterns from the
-- NetworkX (parts are heavily inspired),
-- Seaborn,
-- Matplotlib, and
-- tqdm (to a lesser extent) documentations.

I found inspiration about possible network analysis metrics in both the Gephi app and in a monograph about it:

Ken Cherven, "Mastering Gephi Network Visualization: Produce Advanced Network Graphs in Gephi and Gain Valuable Insights
              Into Your Network Datasets", Birmingham and Mumbai: Packt open source, 2015.

Then, the following article provided a useful overview about key concepts with regards to the Digital Humanities:

Fotos Jannidis, "Netzwerke", in: "Digital Humanities. Eine Einführung", ed. by ibid., Hubertus Kohle, and Malte Rehbein,
                 Stuttgart: Metzler, 2017, pp. 147-161.

Finally, a lot of the code snippets are taken from or heavily influenced by

Edward L. Platt, "Network Science with Python and NetworkX Quick Start Guide: Explore and Visualize Network Data
                  Effectively", Birmingham and Mumbai: Packt open source, 2019.                                      """

import gc, heapq, json, logging, warnings
import matplotlib.lines   as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot  as plt
import networkx           as nx
import numpy              as np
import pandas             as pd
import seaborn            as sns

from collections                   import defaultdict, Counter
from matplotlib                    import colormaps
from networkx.algorithms.community import greedy_modularity_communities
from scipy.sparse                  import csr_matrix
from tqdm                          import tqdm

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)


import io
import base64

def fig_to_base64():
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    img = base64.b64encode(buf.read()).decode("utf-8")
    buf.close()
    plt.close()
    return f"data:image/png;base64,{img}"

def load_data(file_path):
    """
    Load comments JSON from disk.
    """

    try:
        with open(file_path, "r", encoding="utf-8") as f:   # or "utf-8-sig" for better Windws support
            return json.load(f)

    except FileNotFoundError:
        logger.error(f"Input file not found: {file_path}")
        print(f"Could not find input file: {file_path}")
        return None

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {file_path}: {e}")
        print(f"Invalid JSON in {file_path} at line {e.lineno}, column {e.colno}: {e.msg}")
        return None

    except UnicodeDecodeError as e:
        logger.error(f"Encoding error reading {file_path}: {e}")
        print("Encoding error.")
        return None

    except PermissionError as e:
        logger.error(f"Permission error for {file_path}: {e}")
        print("Permission error.")
        return None

    except Exception as e:
        logger.exception(f"Unexpected error opening {file_path}: {e}")
        print(f"Unexpected error opening {file_path}: {e}")
        return None


def extract_participants(video_data, roles=("uploader", "commenter", "replier")):
    """
    Returns a set of unique channel IDs participating in a video's discussion for certain roles.
    """

    parts = set()

    if "uploader" in roles:
        parts.add(video_data["video_info"]["channel_id"])

    if "commenter" in roles or "replier" in roles:
        for comment in video_data["comments"]:
            if "commenter" in roles:
                a = comment.get("author_channel_id")
                if a:
                    parts.add(a)

            if "replier" in roles:
                for reply in comment.get("replies", []):
                    r = reply.get("author_channel_id")
                    if r:
                        parts.add(r)

    return parts


def channel_occurrence_stats(data):
    """
    Count how often a channel appears in various roles:
    as uploader, as commenter, as replier, in how many unique videos
    """

    stats = defaultdict(lambda: {
        "as_uploader"  : 0,
        "as_commenter" : 0,
        "as_replier"   : 0,
        "unique_videos": set()
    })

    for video_id, video_data in tqdm(data.items(), desc="Scanning videos for channel stats"):
        uploader_id = video_data["video_info"]["channel_id"]
        stats[uploader_id]["as_uploader"] += 1
        stats[uploader_id]["unique_videos"].add(video_id)

        for comment in video_data["comments"]:
            commenter_id = comment.get("author_channel_id")
            if commenter_id:
                stats[commenter_id]["as_commenter"] += 1
                stats[commenter_id]["unique_videos"].add(video_id)

            for reply in comment.get("replies", []):
                replier_id = reply.get("author_channel_id")
                if replier_id:
                    stats[replier_id]["as_replier"] += 1
                    stats[replier_id]["unique_videos"].add(video_id)

    data_list = []

    for channel_id, counts in stats.items():
        data_list.append({
            "channel_id"      : channel_id,
            "as_uploader"     : counts["as_uploader"],
            "as_commenter"    : counts["as_commenter"],
            "as_replier"      : counts["as_replier"],
            "total_activity"  : counts["as_uploader"] + counts["as_commenter"] + counts["as_replier"],
            "videos_active_in": len(counts["unique_videos"])
        })

    df = pd.DataFrame(data_list)

    return df.sort_values(by="total_activity", ascending=False).reset_index(drop=True)


def plot_channel_role_proportions(df, roles=("as_uploader", "as_commenter", "as_replier"), top_n=None, normalize=False,
                                  figsize=(12,6), palette=None):
    """
    Bar chart of role counts per channel with optional filtering/normalization.
    """

    cols = [c for c in roles if c in df.columns]
    use = df.copy()

    if normalize:
        use[cols] = use[cols].div(use[cols].sum(axis=1).replace(0, 1), axis=0)

    if top_n:
        use = use.sort_values(by=cols, ascending=False).head(top_n)

    df_long = use.melt(id_vars="channel_id", value_vars=cols, var_name="role", value_name="count")
    plt.figure(figsize=figsize)
    sns.barplot(data=df_long, x="channel_id", y="count", hue="role", palette=palette)
    plt.title("Channel Roles")
    plt.xticks(rotation=45, ha="right")

    plt.tight_layout()
    plt.show()


def build_reply_network(data, include_self=False, min_weight=1):
    """
    Construct a directed reply graph with options to include self-replies and drop light edges.
    """

    G = nx.DiGraph()

    for _, video_data in tqdm(data.items(), desc="Scanning videos for reply stats"):
        for comment in video_data["comments"]:
            parent = comment.get("author_channel_id")
            if not parent:
                continue

            for reply in comment.get("replies", []):
                child = reply.get("author_channel_id")
                if not child:
                    continue

                if not include_self and parent == child:
                    continue
                if G.has_edge(child, parent):
                    G[child][parent]["weight"] += 1
                else:
                    G.add_edge(child, parent, weight=1)

    to_remove = [(u, v) for u, v, d in G.edges(data=True) if d.get("weight", 0) < min_weight]
    G.remove_edges_from(to_remove)

    nx.write_gexf(G, "directed_reply_graph.gexf")

    return G


def plot_reply_network(G, top_n=30):
    """
    Visualize top reply interactions as a directed graph.
    """

    degrees = dict(G.degree())                                      # Choose the most important nodes
    top_nodes = sorted(degrees, key=degrees.get, reverse=True)[:top_n]
    subG = G.subgraph(top_nodes).copy()

    subG.remove_nodes_from(list(nx.isolates(subG)))                 # Remove isolated nodes

    pos = nx.spring_layout(subG, k=0.25, seed=42)
    node_sizes = [300 + 20 * subG.degree(n) for n in subG.nodes()]  # Node sizes should be proportional with degrees
    edge_weights = [subG[u][v]['weight'] for u, v in subG.edges()]

    plt.figure(figsize=(14, 14))
    nx.draw_networkx_edges(subG, pos, edge_color="gray", arrows=True, width=edge_weights, alpha=0.6)
    nx.draw_networkx_nodes(subG, pos, node_size=node_sizes, node_color="skyblue", alpha=0.9)
    nx.draw_networkx_labels(subG, pos, font_size=8)

    label = f"Directed Reply Network of YouTube Channels\n(top {top_n} by interaction degree)"
    plt.title(label, fontsize=16)
    plt.axis("off")

    legend_elements = [
        mpatches.Patch(color="skyblue", label="YouTube Channel (Node)"),
        mpatches.Patch(color="gray", label="Reply from one channel to another (Edge)"),
    ]
    plt.legend(handles=legend_elements, loc="upper left", fontsize=10)

    plt.tight_layout()
    # plt.show()
    return fig_to_base64()


def build_interaction_graph_OLD(data, roles=("uploader", "commenter", "replier"), weight="video"):
    """
    Construct an undirected interaction graph between selected roles.
    The parameter 'weight' currently only supports 'video' (each adds 1).
    """

    G = nx.Graph()

    for _, video_data in data.items():
        participants = sorted(extract_participants(video_data, roles))
        for i, a in enumerate(participants):
            for b in participants[i+1:]:
                if G.has_edge(a, b):
                    G[a][b]["weight"] += 1
                else:
                    G.add_edge(a, b, weight=1)

    nx.write_gexf(G, "undirected_interaction_graph.gexf")

    return G


def build_interaction_graph(data, roles=("uploader","commenter","replier"), exclude_uploader=True, top_channels=8000,
                            min_videos_per_channel=2, max_participants_per_video=200, min_weight=2, top_k_per_node=50,
                            max_edges=200_000):
    participation = defaultdict(set)
    for vid, vdata in tqdm(data.items(), desc="Indexing participation (interaction)"):
        parts = extract_participants(vdata, roles)
        if exclude_uploader and "uploader" in roles:
            parts.discard(vdata["video_info"]["channel_id"])
        if max_participants_per_video and len(parts) > max_participants_per_video:
            continue
        for ch in parts:
            participation[ch].add(vid)

    counts = {ch: len(vids) for ch, vids in participation.items()}
    keep = [ch for ch, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)
            if c >= min_videos_per_channel][:top_channels]
    if not keep:
        return nx.Graph()

    ch2i = {ch:i for i,ch in enumerate(keep)}
    vids = sorted({v for ch in keep for v in participation[ch]})
    v2i = {v:i for i,v in enumerate(vids)}

    rows, cols = [], []
    for ch in keep:
        i = ch2i[ch]
        for v in participation[ch]:
            rows.append(i); cols.append(v2i[v])

    X = csr_matrix((np.ones(len(rows), dtype=np.uint8), (rows, cols)),
                   shape=(len(keep), len(vids)))

    S = (X @ X.T).tocsr()
    S.setdiag(0); S.eliminate_zeros()

    edges = []
    indptr, indices, data_arr = S.indptr, S.indices, S.data
    for i in range(S.shape[0]):
        start, end = indptr[i], indptr[i+1]
        neigh = [(int(data_arr[p]), int(indices[p])) for p in range(start, end) if data_arr[p] >= min_weight]
        if not neigh:
            continue
        k = min(top_k_per_node, len(neigh))
        topk = heapq.nlargest(k, neigh, key=lambda t: t[0])
        for w, j in topk:
            if i < j:
                edges.append((i, j, int(w)))

    if len(edges) > max_edges:
        edges.sort(key=lambda t: t[2], reverse=True)
        edges = edges[:max_edges]

    G = nx.Graph()
    idx2ch = np.array(keep)
    for i, j, w in edges:
        G.add_edge(idx2ch[i], idx2ch[j], weight=w)

    del X, S, rows, cols, edges
    gc.collect()
    return G


def channel_video_participation_matrix(data, roles=("uploader", "commenter", "replier"), dtype=bool,
                                       top_channels=None, top_videos=None):
    """
    Build a participation matrix with role and size filters. dtype may be bool or int (no longer in use).
    """

    participation = defaultdict(set)

    for video_id, video_data in tqdm(data.items(), desc="Scanning videos for channel video participation stats:"):
        for ch in extract_participants(video_data, roles):
            participation[ch].add(video_id)

    all_channels = list(participation.keys())
    all_videos = list(data.keys())

    if top_channels:
        counts = {ch: len(vids) for ch, vids in participation.items()}
        all_channels = [ch for ch, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_channels]]

    if top_videos:                                                  # Rank videos by number of participating channels
        vcount = Counter(v for vids in participation.values() for v in vids)
        all_videos = [v for v, _ in vcount.most_common(top_videos)]

    matrix = pd.DataFrame(False if dtype is bool else 0, index=all_channels, columns=all_videos)

    for ch in all_channels:
        vids = list(participation.get(ch, set()) & set(all_videos))
        if vids:
            matrix.loc[ch, vids] = True if dtype is bool else 1

    if dtype is bool and matrix.dtypes.nunique() == 1:
        matrix = matrix.astype(bool)

    return matrix


def plot_channel_clustering_heatmap(matrix, max_channels=400, cluster_max=None, fast=True, both=True, cmap="viridis",
                                    heatmap_figsize=(10, 8), clustermap_figsize=(12, 10), *,
                                    auto=True,                 # if True, choose sensible defaults based on data stats
                                    similarity="dot",          # "dot" | "cosine" | "corr"
                                    transform="none",          # "none" | "log1p"
                                    clip_vmax=None             # None | "p99" | "p995"
):
    """
    Plot a channel co-occurrence heatmap and a clustermap with hierarchical clustering,
    applying an upper limit to the number of channels for plotting to manage performance.
    This code is taken from lots of examples on the web, with some modifications. I hope it all fits together!!
    """

    def auto_settings(X):
        """
        Derive simple heuristics from sparsity and skewness.
        """

        n_rows, n_cols = X.shape
        nnz = (X.values != 0).sum()                             # sparsity of the raw matrix (fraction of non-zeros)
        sparsity = nnz / (n_rows * n_cols) if n_rows * n_cols > 0 else 0.0
        row_sum = pd.Series(X.sum(axis=1))                      # skewness of row activity (heavy tails suggest log1p)
        skew = float(row_sum.skew()) if len(row_sum) else 0.0

        s = {}
        s["transform"] = "log1p" if skew > 1.0 else "none"
        s["similarity"] = "cosine" if sparsity < 0.10 else "corr"
        s["clip_vmax"] = "p99" if sparsity < 0.10 else "p995"

        return s, {"sparsity": sparsity, "skew": skew}

    def apply_transform(X, how):
        """
        Apply a monotone transform to stabilize heavy tails (if requested).
        """

        if how == "log1p":
            return np.log1p(X)
        return X

    def build_similarity(X, how):
        """
        Compute channel-by-channel similarity.
        """

        if how == "dot":
            S = X.T.dot(X)
            S = S.astype(float)
        elif how == "cosine":
            A = X.values.astype(float)
            denom = np.linalg.norm(A, axis=1, keepdims=True)            # L2-normalize rows (channels)
            denom[denom == 0] = 1.0
            A = A / denom
            S = pd.DataFrame(A @ A.T, index=X.index, columns=X.index)
        elif how == "corr":
            A = X.values.astype(float)                                  # Pearson correlation between channel profiles
            if A.shape[0] == 0:
                S = pd.DataFrame(A, index=X.index, columns=X.index)
            else:
                C = np.corrcoef(A)
                S = pd.DataFrame(C, index=X.index, columns=X.index)
        else:
            raise ValueError(f"Unknown similarity '{how}'")
        if len(S) > 0:                                                  # zero diagonal so self-similarities do not dominate the colormap
            np.fill_diagonal(S.values, 0.0)
        return S

    def clip_upper(S, mode):
        """
        Return a vmax value from upper percentile to tame outliers (None = no clipping).
        """

        if mode is None or S.size == 0:
            return None
        vals = S.values
        vals = vals[np.isfinite(vals)]
        vals = vals[vals > 0]                                           # ignore zeros for percentile of positive mass
        if vals.size == 0:
            return None
        p = 99.0 if mode == "p99" else 99.5
        return float(np.percentile(vals, p))

    if auto:
        auto_s, stats = auto_settings(matrix)
        if transform == "none":                                         # only override when user left defaults
            transform = auto_s["transform"]
        if similarity == "dot":
            similarity = auto_s["similarity"]
        if clip_vmax is None:
            clip_vmax = auto_s["clip_vmax"]
        print(f"[auto] sparsity≈{stats['sparsity']:.3f}, skew≈{stats['skew']:.2f} → "
              f"transform={transform}, similarity={similarity}, clip_vmax={clip_vmax}")

    if cluster_max is None:
        cluster_max = max_channels

    print("Calculating co-occurrence matrix. This may take a while!")
    num_channels = matrix.shape[0]
    print(f"Co-occurrence matrix has {num_channels} channels.")

    if num_channels > max_channels and fast:            # fast mode: reduce to top N channels for heatmap
        print(f"The matrix exceeds the limit of {max_channels} channels and may be too large to plot entirely.")
        print(f"Reducing heatmap to top {max_channels} active channels...")
        top_indices = matrix.sum(axis=1).nlargest(max_channels).index
        matrix = matrix.loc[top_indices]
        num_channels = matrix.shape[0]
        print(f"Heatmap will use {num_channels} channels after reduction.")

    matrix_t = apply_transform(matrix, transform)
    similarity_mat = build_similarity(matrix_t, similarity)

    vmax = clip_upper(similarity_mat, clip_vmax)
    vmin = 0

    print("Plotting co-occurrence heatmap...")
    plt.figure(figsize=heatmap_figsize)
    sns.heatmap(similarity_mat, cmap=cmap, vmin=vmin, vmax=vmax)
    plt.title("Channel Co-Occurrence Heatmap")
    plt.tight_layout()
    plt.show()

    if both:                                                        # clustermap/dendrogram
        print("Plotting clustermap (hierarchical clustering of channels)...")
        try:
            if similarity_mat.shape[0] > cluster_max:               # too large? reduce data
                subset_size = cluster_max
                print(f"Clustermap dataset is large ({similarity_mat.shape[0]} channels).")
                print(f"Reducing to top {subset_size} channels by co-occurrence frequency for dendrogram...")
                # Select top channels by total similarity to others (most connected channels)
                top_cluster_indices = similarity_mat.sum(axis=1).nlargest(subset_size).index
                similarity_subset = similarity_mat.loc[top_cluster_indices, top_cluster_indices]
            else:
                similarity_subset = similarity_mat  # use full similarity if it's within the limit

            cg = sns.clustermap(
                similarity_subset, cmap=cmap, figsize=clustermap_figsize,
                vmin=vmin, vmax=vmax
            )       # build map
            cg.fig.suptitle("Channel Co-Occurrence Heatmap (Hierarchical Clustering)")
            plt.show()
        except Exception as e:
            print(f"Clustermap generation failed: {e}")
            print("Skipping clustermap. Try a smaller 'cluster_max' or increase the recursion limit.")


def top_connected_channels(G, top_n=10):
    """
    Return the top_n channels with the highest degree in the graph.
    """

    degrees = dict(G.degree())
    top = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:top_n]

    return pd.DataFrame(top, columns=["channel_id", "degree"])


def plot_channel_degree_distribution(G, cap_height=100, bin_count=30, x_min=None, x_max=None, figsize=(12,6),
                                     capped_color="tomato", normal_color="steelblue"):
    """
    Plot degree distribution with clipping, bin control and some useless eye candy.
    """

    degrees = [d for _, d in G.degree()]
    total_nodes = len(degrees)
    zero_degree_count = sum(1 for d in degrees if d == 0)
    non_zero_degrees = [d for d in degrees if d > 0]
    non_zero_count = len(non_zero_degrees)

    if non_zero_count == 0:
        print("No nodes with degree > 0 in the graph.")
        return

    zero_percent = zero_degree_count / total_nodes * 100
    non_zero_percent = non_zero_count / total_nodes * 100

    min_degree = max(1, min(non_zero_degrees))
    max_degree = max(non_zero_degrees)

    x_min = x_min if x_min is not None else min_degree
    x_max = x_max if x_max is not None else max_degree
    if x_min <= 0:
        x_min = min_degree
    if x_max <= x_min:
        x_max = max_degree

    filtered_degrees = [d for d in non_zero_degrees if x_min <= d <= x_max]
    if not filtered_degrees:
        print(f"No nodes with degree >0 in range {x_min}–{x_max}.")
        return

    bin_edges = np.linspace(x_min, x_max, bin_count + 1)
    bins = pd.cut(filtered_degrees, bins=bin_edges, right=True, include_lowest=False)
    bucket_counts = bins.value_counts().sort_index()

    fig, ax = plt.subplots(figsize=figsize)
    outliers = {}
    for i, (bucket, count) in enumerate(bucket_counts.items()):
        label = f"{int(bucket.left)}–{int(bucket.right)}"
        if count > cap_height:
            ax.bar(label, cap_height, color=capped_color)
            ax.plot(i, cap_height, marker="^")
            ax.text(i, cap_height + 1, str(count), ha="center", va="bottom", fontsize=8)
            outliers[label] = count
        else:
            ax.bar(label, count, color=normal_color)
            ax.text(i, count + 0.5, str(count), ha="center", va="bottom", fontsize=8)

    ax.set_title(f"Degree Distribution of Channel Network\n(Max. Bins: {bin_count}, Range: {x_min}–{x_max}, Cap: {cap_height})")
    ax.set_xlabel("Node Degree")
    ax.set_ylabel("Number of Nodes")
    plt.xticks(rotation=45, ha="right")

    legend_lines = [
        f"{zero_degree_count} nodes with degree 0 ({zero_percent:.2f} %)",
        f"{non_zero_count} nodes with degree ≥1 ({non_zero_percent:.2f} %)",
        ""
    ]

    if outliers:
        legend_lines.append("Absolute Counts for Clipped Bins:")
        for label, count in outliers.items():
            legend_lines.append(f"  - {label}: {count} nodes")

    text_legend = mlines.Line2D([], [], color="white", label="\n".join(legend_lines))
    capped_patch = mpatches.Patch(color=capped_color, label="Capped Bins")
    normal_patch = mpatches.Patch(color=normal_color, label="Uncapped Bins")
    ax.legend(handles=[normal_patch, capped_patch, text_legend], loc="upper right", fontsize=9)

    plt.tight_layout()
    plt.show()


def compute_centrality_measures(G, skip_slow=False, speed_up=True):
    """
    Compute centrality scores for nodes.
    skip_slow=True skips slow metrics. speed_up=True uses approximate betweenness in large graphs.
    """

    def choose_approx_k(n_nodes):
        if n_nodes < 1000:
            return n_nodes
        elif n_nodes < 5000:
            return 100
        elif n_nodes < 10000:
            return 50
        elif n_nodes < 30000:
            return 25
        else:
            return 10

    print("Calculating degree centrality...")
    print(f"Graph stats: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"Graph density: {nx.density(G):.5f}")

    degree = nx.degree_centrality(G)
    results = {
        "channel_id": list(degree.keys()),
        "degree_centrality": list(degree.values()),
    }

    if skip_slow:
        print("Skipping slow metrics (betweenness, eigenvector).")
        return pd.DataFrame(results).sort_values("degree_centrality", ascending=False)

    node_count = G.number_of_nodes()
    k_value = choose_approx_k(node_count)

    if speed_up and node_count > 500:
        print(f"Graph has {node_count} nodes – using k-approximate betweenness with k = {k_value}...")
        try:
            betweenness = nx.betweenness_centrality(G, k=k_value, seed=42)
        except Exception as e:
            logger.error(f"Approximate betweenness calculation failed. Error: {e}.")
            print("Could not calculate the betweenness centrality.")
            betweenness = {}
    else:
        print("Calculating exact betweenness centrality. This may take a while.")
        try:
            betweenness = nx.betweenness_centrality(G)
        except Exception as e:
            logger.error(f"Betweenness calculation failed. Error: {e}.")
            print("Could not calculate the betweenness centrality.")
            betweenness = {}

    results["betweenness"] = [betweenness.get(n, 0.0) for n in degree.keys()]

    try:
        print("Calculating eigenvector centrality...")
        eigenvector = nx.eigenvector_centrality(G, max_iter=1000, tol=1e-06)
        results["eigenvector"] = [eigenvector.get(n, 0.0) for n in degree.keys()]
    except Exception as e:
        logger.error(f"Eigenvector calculation failed. Error: {e}.")
        print("Could not calculate the eigenvector centrality.")
        results["eigenvector"] = [0.0 for _ in degree.keys()]

    return pd.DataFrame(results).sort_values("degree_centrality", ascending=False)


def plot_centrality_results(centrality_df, top_n=20, both=True, bar_figsize=(16,6), scatter_figsize=(8,6)):
    """
    Plot centrality analysis results, configurable sizes; 'both' toggles scatter.
    """

    df = centrality_df.copy()
    cols = ["degree_centrality", "betweenness", "eigenvector"]
    df = df[["channel_id"] + cols]
    top = df.sort_values("degree_centrality", ascending=False).head(top_n)

    fig, axes = plt.subplots(1, 3, figsize=bar_figsize, sharey=False)

    for ax, metric, title in zip(axes, cols, ["Degree Centrality", "Betweenness", "Eigenvector"]):
        tmp = top.sort_values(metric, ascending=True)
        ax.barh(tmp["channel_id"], tmp[metric])
        ax.set_title(title)
        ax.set_xlabel(metric)
        ax.set_ylabel("channel_id")

    plt.tight_layout()
    plt.show()

    if both:
        plt.figure(figsize=scatter_figsize)
        max_ev = top["eigenvector"].max() or 1
        sizes = 200 * (top["eigenvector"] / max_ev + 0.1)
        plt.scatter(top["degree_centrality"], top["betweenness"], s=sizes, alpha=0.7)

        for _, row in top.iterrows():
            plt.text(row["degree_centrality"], row["betweenness"], row["channel_id"], fontsize=8, ha="left", va="center")

        plt.xlabel("degree_centrality")
        plt.ylabel("betweenness")
        plt.title("Degree vs. Betweenness (marker size ~ eigenvector)")

        plt.tight_layout()
        plt.show()


def plot_top_channels(df, role="commenter", top_n=10):
    """
    Plot the top channels by role.
    """

    column_map = {
        "uploader" : "as_uploader",
        "commenter": "as_commenter",
        "replier"  : "as_replier",
        "total"    : "total_activity"
    }

    col = column_map.get(role, "as_commenter")
    top_df = df.sort_values(by=col, ascending=False).head(top_n)

    plt.figure(figsize=(10,6))
    plt.barh(top_df["channel_id"], top_df[col], color="steelblue")
    plt.gca().invert_yaxis()
    plt.title(f"Top {top_n} Channels by {role.title()}")
    plt.xlabel("Activity Count")

    plt.tight_layout()
    plt.show()


def plot_network_graph(G, top_n=None, layout="spring", seed=42, figsize=(12,12), node_size=200, with_labels=True,
                       edge_cmap=plt.cm.Blues,):
    """
    Plot a (sub)graph with configurable layout and styling.
    layout might be 'spring', 'kamada_kawai', 'circular', 'random'. Some take ages to complete!
    """

    H = G

    if top_n:
        degrees = dict(G.degree())
        top_nodes = sorted(degrees, key=degrees.get, reverse=True)[:top_n]
        H = G.subgraph(top_nodes).copy()

    if layout == "spring":
        pos = nx.spring_layout(H, k=0.15, iterations=20, seed=seed)
    elif layout == "kamada_kawai":
        pos = nx.kamada_kawai_layout(H)
    elif layout == "circular":
        pos = nx.circular_layout(H)
    else:
        pos = nx.random_layout(H, seed=seed)

    weights = [H[u][v]["weight"] for u, v in H.edges()]

    plt.figure(figsize=figsize)
    fig, ax = plt.subplots(figsize=figsize)

    nx.draw(H, pos, with_labels=with_labels, node_size=node_size, edge_color=weights, edge_cmap=edge_cmap, ax=ax)

    ax.set_title("Co-Occurrence Network of YouTube Channels in Comment Sections:\n" +
                 "YouTube Channels Connected by Shared Comment Activity", fontsize=16, pad=20)
    ax.axis("off")

    plt.tight_layout()
    # plt.show()
    return fig_to_base64()


def frequent_channel_pairs(data, threshold=3, roles=("uploader","commenter","replier"), exclude_uploader=True,
                           top_channels=5000, min_videos_per_channel=2, max_participants_per_video=200, top_n=None):
    participation = defaultdict(set)
    for vid, vdata in tqdm(data.items(), desc="Indexing participation"):
        parts = extract_participants(vdata, roles)
        if exclude_uploader and "uploader" in roles:
            parts.discard(vdata["video_info"]["channel_id"])
        if max_participants_per_video and len(parts) > max_participants_per_video:      # exclude
            continue
        for ch in parts:
            participation[ch].add(vid)

    counts = {ch: len(vids) for ch, vids in participation.items()}
    keep = [ch for ch, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)
            if c >= min_videos_per_channel][:top_channels]
    if not keep:
        return pd.DataFrame(columns=["channel_1","channel_2","co_occurrence"])

    ch2i = {ch:i for i,ch in enumerate(keep)}
    vids = sorted({v for ch in keep for v in participation[ch]})
    v2i = {v:i for i,v in enumerate(vids)}

    rows, cols = [], []
    for ch in keep:
        i = ch2i[ch]
        for v in participation[ch]:
            rows.append(i); cols.append(v2i[v])

    X = csr_matrix((np.ones(len(rows), dtype=np.uint8), (rows, cols)),
                   shape=(len(keep), len(vids)))

    S = X @ X.T
    S.setdiag(0)
    S.eliminate_zeros()

    S.data = S.data.astype(np.int32)
    mask = S.data >= threshold
    if not np.any(mask):
        return pd.DataFrame(columns=["channel_1","channel_2","co_occurrence"])

    indptr = S.indptr
    row_ids = np.repeat(np.arange(S.shape[0]), np.diff(indptr))
    i_all = row_ids[mask]
    j_all = S.indices[mask]
    w_all = S.data[mask]

    keep_names = np.array(keep)
    df = pd.DataFrame({
        "channel_1": keep_names[np.minimum(i_all, j_all)],
        "channel_2": keep_names[np.maximum(i_all, j_all)],
        "co_occurrence": w_all
    }).drop_duplicates(subset=["channel_1","channel_2"])

    df = df.sort_values("co_occurrence", ascending=False)
    if top_n:
        df = df.head(top_n)

    del X, S
    gc.collect()

    return df


def frequent_channel_pairs_OLD(data, threshold=3, roles=("uploader", "commenter", "replier"), exclude_uploader=False,
                           top_n=None):
    """
    Compute frequent co-occurring channel pairs with role control and thresholding.
    """

    pair_counts = Counter()

    for video_id, video_data in tqdm(data.items(), desc="Scanning videos for channel pairs"):
        parts = extract_participants(video_data, roles)
        if exclude_uploader and "uploader" in roles:
            parts.discard(video_data["video_info"]["channel_id"])

        parts = sorted(parts)

        for i, a in enumerate(parts):
            for b in parts[i+1:]:
                pair_counts[(a, b)] += 1

    items = [((a, b), c) for (a, b), c in pair_counts.items() if c >= threshold]    # threshold reduces noise
    items.sort(key=lambda x: x[1], reverse=True)
    if top_n:
        items = items[:top_n]
    result = [(a, b, c) for (a, b), c in items]

    return pd.DataFrame(result, columns=["channel_1", "channel_2", "co_occurrence"]).sort_values("co_occurrence", ascending=False)


def plot_channel_pair_network(pairs_df, top_n=50):
    """
    Visualize the most frequent co-occurring channel pairs as a network,
    including community detection and color-coded clusters, all done by networkx.
    """

    top_pairs = pairs_df.head(top_n)
    G = nx.Graph()

    for _, row in top_pairs.iterrows():
        a, b, w = row["channel_1"], row["channel_2"], row["co_occurrence"]
        G.add_edge(a, b, weight=w)

    if G.number_of_edges() == 0:
        print("No edges to plot.")
        return

    communities = list(greedy_modularity_communities(G))            # Detect communities
    node_community_map = {}
    for i, comm in enumerate(communities):
        for node in comm:
            node_community_map[node] = i

    pos = nx.spring_layout(G, k=0.4, seed=42)                       # Layout, weights, colors
    weights = [G[u][v]["weight"] for u, v in G.edges()]
    cmap = colormaps.get_cmap("tab10")
    palette = getattr(cmap, "colors", [cmap(i / 9) for i in range(10)])
    node_colors = [palette[node_community_map.get(n, 0) % len(palette)] for n in G.nodes()]

    plt.figure(figsize=(14, 14))
    maxw = max(weights) if weights else 1
    scaled_widths = [1 + 2 * (w / maxw) for w in weights]
    nx.draw_networkx_edges(G, pos, width=scaled_widths, alpha=0.6, edge_color="gray")
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=500, alpha=0.9)
    nx.draw_networkx_labels(G, pos, font_size=8)

    legend_colors = [palette[i % len(palette)] for i in range(len(communities))]
    for i, color in enumerate(legend_colors):
        plt.scatter([], [], color=color, label=f"Cluster {i+1}")
    plt.legend(title="Detected Communities", loc="upper left", fontsize=8)

    plt.title("Frequent Channel Pairs Network (Clustered)")
    plt.axis("off")
    plt.tight_layout()
    plt.show()

    nx.write_gexf(G, "frequent_channel_pairs_network.gexf")

"""
    # 4) Undirected interaction network – ebenfalls deckeln

    # 5) Centrality: bei riesigen Graphen approximieren/abbrechen

    # 6) Directed reply graph
"""
def tubegraph(filename):
    data = load_data(filename)

    if not data:
        logger.error("No data to analyze.")
        print("No data to analyze.")
        return

    logo = """
┌───────────────────────────────────────────────────────────┐
│      Welcome to ●     ●───●   ●   ●                       │
│                ╱ ╲     ╲ ╱ ╲ ╱ ╲ ╱ ╲                      │
│               ●───●     ●   ●   ●   ●────●                │
│                  ╱ ╲   ╱     ╲ ╱     ╲  ╱                 │
│                 ●   ●─●       ●      ●──● TubeGraph!      │
└───────────────────────────────────────────────────────────┘
"""

    print(logo)
    print("WARNING: These functions may take a long time to run (minutes to hours).")

    if not input("Proceed (y/n)? ").lower().strip().startswith("y"):
        return

    # 1. Basic stats
    df_stats = channel_occurrence_stats(data)
    for role in ["uploader", "commenter", "replier", "total"]:
        plot_top_channels(df_stats, role=role)

    # 2. Participation matrix
    print("\nGenerating channel co-occurrence matrix. This may take a while!")
    matrix = channel_video_participation_matrix(data, roles=("uploader", "commenter", "replier"), top_channels=400,
                                                top_videos=None)
    plot_channel_clustering_heatmap(matrix, max_channels=400, cluster_max=300, fast=True, both=True)
    import gc, matplotlib.pyplot as plt
    del matrix
    plt.close("all")
    gc.collect()


    # 3. Channel pairs
    print("\nDetecting frequent channel pairs.")
    pairs = frequent_channel_pairs(data, threshold=3, roles=("uploader","commenter","replier"), exclude_uploader=True,
                                   top_channels=5000, min_videos_per_channel=2, max_participants_per_video=200,
                                   top_n=5000)
    plot_channel_pair_network(pairs, top_n=200)

    # 4. Undirected interaction network
    print("Building undirected interaction graph.")
    G = build_interaction_graph(data, roles=("uploader", "commenter", "replier"), exclude_uploader=True,
                                top_channels=8000, min_videos_per_channel=2, max_participants_per_video=200,
                                min_weight=2, top_k_per_node=50, max_edges=200_000)
    print("Plotting network graph...")
    plot_network_graph(G, top_n=50)
    print("Plotting channel degree distribution graph...")
    centrality_df = compute_centrality_measures(G, skip_slow=False, speed_up=True)
    plot_centrality_results(centrality_df, top_n=10)

    # 5. Centrality
    if "G" not in locals():
        print("Building undirected interaction graph.")
        G = build_interaction_graph(data)
    print("Calculating centrality measures.")
    centrality_df = compute_centrality_measures(G, skip_slow=False, speed_up=True)
    plot_centrality_results(centrality_df, top_n=10)

    # 6. Directed reply graph
    print("Constructing reply network...")
    reply_graph = build_reply_network(data, include_self=False, min_weight=2)  # Schwelle anheben
    plot_reply_network(reply_graph, top_n=50)


if __name__ == "__main__":
    tubegraph("E:\\Dropbox\\Python\\YouTube\\Comments.json")        # "E:\Dropbox\Python\YouTube\Comments.json" in Windows
