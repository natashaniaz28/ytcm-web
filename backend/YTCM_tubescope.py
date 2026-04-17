""" TubeScope contains a set of statistical analysis functions for the YouTube Comment Miner.
Originally, it was a standalone script, but I decided to move it directly into YTCM.

Ideas and code snippets for this came from a lot of books in addition to the matplotlib, numpy, pandas, and seaborn
documentation:

    Alby, Tom:        "Data Science in der Praxis", Bonn:       Rheinwerk,       2022,
    McKinney, Wes:    "Datenanalyse mit Python",    Heidelberg: O'Reilly,        2023,
    Sarkar, Dipanjan: "Text Analytics with Python", New York:   Springer/Apress, 2019,
    VanderPlas, Jake: "Data Science mit Python",    Frechen:    mitp,            2018,
                                                                        and many more.                               """

import json, logging, warnings
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning, message=r"Glyph \d+ .* missing from font.*")


def load_data(file_path):
    """
    Load comments JSON from disk.
    Returns data as a dict.
    """
    print("LOAD_DATA RECEIVED PATH:", file_path)
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        print("✅ JSON LOADED SUCCESSFULLY")
        return data

    except FileNotFoundError:
        logging.error(f"❌ File not found: {file_path}")
        return None

    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {e}")
        return None

    except Exception as e:
        logging.error(f"❌ Unexpected error: {e}")
        return None

def interaction_density(df_comments, video_info):
    """
    Calculates a interaction density score for one video, consisting of:
    - replies per comment
    - share of comments that triggered replies
    This is normalized by views. This approach is a bit experimental!
    """

    total_comments = len(df_comments)
    total_replies = sum(len(r) for r in df_comments["replies"])
    comments_with_replies = (df_comments["replies"].apply(len) > 0).sum()
    views = video_info.get("views", 1)  # fallback to 1 to avoid division by zero

    replies_per_comment = total_replies / total_comments if total_comments else 0
    reply_trigger_ratio = comments_with_replies / total_comments if total_comments else 0
    replies_per_view = total_replies / views if views else 0

    # This formula is more of a "well, why not" than something really deep :)
    score = 0.4 * replies_per_comment + 0.4 * reply_trigger_ratio + 0.2 * replies_per_view

    return {
        "replies_per_comment": replies_per_comment,
        "comments_with_replies_ratio": reply_trigger_ratio,
        "replies_per_view": replies_per_view,
        "interaction_density_score": score
    }


def plot_interaction_density_distribution(data, bin_count=30):
    """
    Compute and plot the distribution of interaction density scores across all videos.
    Includes mean, median, and top-5 videos as legend.
    """

    scores = []
    labels = []

    for video_id, video_data in data.items():
        video_info, comments = extract_video_info(video_id, video_data)

        # Skip videos without comments or missing dates
        if not comments or not all("date" in comment for comment in comments):
            continue

        try:
            df_comments = analyze_comments(comments)
            result = interaction_density(df_comments, video_info)
            score = result["interaction_density_score"]

            scores.append(score)
            labels.append({
                "id": video_id,
                "title": video_info.get("title", "[No Title]"),
                "score": score
            })

        except Exception as e:
            logger.error(f"Skipping video {video_id} due to error: {e}.")
            print(f"Skipping video {video_id}.")
            continue

    if not scores:
        print("No interaction density scores found.")
        return

    scores_series = pd.Series(scores)
    mean_val = scores_series.mean()
    median_val = scores_series.median()

    # Sort Top 5 videos by score in descending order
    top_videos = sorted(labels, key=lambda x: x["score"], reverse=True)[:5]

    plt.figure(figsize=(10, 6))
    sns.histplot(scores_series, bins=bin_count, color="cornflowerblue", kde=False)

    plt.axvline(mean_val, color="red", linestyle="--", linewidth=1.5, label=f"Mean: {mean_val:.4f}")
    plt.axvline(median_val, color="orange", linestyle="--", linewidth=1.5, label=f"Median: {median_val:.4f}")

    top_lines = ["Top 5 Videos by Interaction Density Score:"]
    for entry in top_videos:
        short_title = entry["title"][:60] + "…" if len(entry["title"]) > 60 else entry["title"]
        top_lines.append(f"- {entry['id']}: {short_title} ({entry['score']:.4f})")

    top_text = mlines.Line2D([], [], color="white", label="\n".join(top_lines))

    plt.legend(handles=[top_text], loc="upper right", fontsize=9)
    plt.title("Interaction Density Scores")
    plt.xlabel("Interaction Density Score")
    plt.ylabel("Number of Videos")
    plt.tight_layout()
    plt.show()


def extract_video_info(video_id, video_data):
    """
    Separate video info and comments and return them as a tuple.
    """

    try:
        return video_data["video_info"], video_data["comments"]
    except Exception as e:
        logger.error(f"Error extracting video info for video {video_id}: {e}.")
        print(f"Error erctracting video info for {video_id}.")
        return None, None


def display_video_stats(video_info, total_comments):
    """
    Display basic info about a video.
    """

    print(f"Title         : {video_info['title']}")
    print(f"Views         : {video_info['views']}")
    print(f"Likes         : {video_info['likes']}")
    print(f"Published     : {video_info['published_at']}")
    print(f"Total comments: {total_comments}")


def analyze_comments(comments):
    """
    Process the VADER sentiment analysis for all comments.
    """

    df_comments = pd.DataFrame(comments)
    df_comments["date"] = pd.to_datetime(df_comments["date"])
    df_comments["sentiment"] = df_comments.apply(
        lambda row: row.get("vader_sentiment", "N/A"),
        axis=1
    )

    return df_comments


def get_most_liked_comments(df_comments, top_n=5):
    """
    Return the top n liked comments.
    """

    return df_comments.sort_values("likes", ascending=False).head(top_n)


def calculate_average_sentiment(df_comments):
    """
    Return the average sentiment (VADER) of the dataframe (excluding N/A values).
    """

    sentiment_numeric = pd.to_numeric(df_comments["sentiment"], errors="coerce")
    return sentiment_numeric.dropna().mean()


def group_comments_by_date(df_comments):
    """
    Group comments by date.
    Returns a pd.Series; date is index, numbers are referenced to the indices.
    - dt.date extracts the date (ignoring the time).
    - groupby() groups the DataFrame rows according to this date.
    - size() finally calculates the size of each group.
    """

    return df_comments.groupby(df_comments["date"].dt.date).size()


def plot_comment_likes_distribution(df_comments, cap_height=100, bin_count=30, x_min=None, x_max=None):
    """
    Plot like distribution in dynamic buckets.
    The plot will be capped at cap_height.
    bin_count is the max number of bins/buckets. (30 is a good default value.)
    x_min and x_max can define left and right borders of slices.
    """

    total_comments = len(df_comments)
    zero_likes_count = (df_comments["likes"] == 0).sum()
    non_zero_df = df_comments[df_comments["likes"] > 0]
    non_zero_count = len(non_zero_df)
    zero_percent = zero_likes_count / total_comments * 100
    non_zero_percent = non_zero_count / total_comments * 100

    if non_zero_count == 0:
        print("No comments containing likes in the dataset.")
        return

    # Generate the buckets
    min_likes = max(1, non_zero_df["likes"].min())  # 1 excludes the 0-like comments
    max_likes = non_zero_df["likes"].max()

    x_min = x_min if x_min is not None else min_likes
    x_max = x_max if x_max is not None else max_likes

    filtered_df = non_zero_df[(non_zero_df["likes"] >= x_min) & (non_zero_df["likes"] <= x_max)]

    if filtered_df.empty:
        print(f"No comments with >0 likes in range {x_min}–{x_max}.")
        return

    bin_edges = np.linspace(x_min, x_max, bin_count + 1)
    bins = pd.cut(filtered_df["likes"], bins=bin_edges, right=True, include_lowest=False)
    bucket_counts = bins.value_counts().sort_index()

    fig, ax = plt.subplots(figsize=(12, 6))
    outliers = {}

    for i, (bucket, count) in enumerate(bucket_counts.items()):
        label = f"{int(bucket.left)}–{int(bucket.right)}"

        if count > cap_height:
            ax.bar(label, cap_height, color="tomato")
            ax.plot(i, cap_height, marker="^", color="black", markersize=8)
            ax.text(i, cap_height + 1, str(count), ha="center", va="bottom", fontsize=8)
            outliers[label] = count
        else:
            ax.bar(label, count, color="steelblue")
            ax.text(i, count + 0.5, str(count), ha="center", va="bottom", fontsize=8)

    ax.set_title("Comments Likes")
    ax.set_xlabel("Likes per Comment")
    ax.set_ylabel("Number of Comments")
    plt.xticks(rotation=45, ha="right")

    legend_lines = [
        f"{zero_likes_count} comments without likes ({zero_percent:.2f} %)",
        f"{non_zero_count} comments with 1 or more likes ({non_zero_percent:.2f} %)",
        "",
    ]

    if outliers:
        legend_lines.append("Absolute Counts for Clipped Bins:")
        for label, count in outliers.items():
            legend_lines.append(f"  - {label}: {count} comments")

    text_legend = mlines.Line2D([], [], color="white", label="\n".join(legend_lines))
    capped_patch = mpatches.Patch(color="tomato", label="Capped Bins")
    normal_patch = mpatches.Patch(color="steelblue", label="Uncapped Bins")

    ax.legend(
        handles=[normal_patch, capped_patch, text_legend],
        loc="upper right",
        fontsize=9
    )

    plt.tight_layout()
    plt.show()


def plot_sentiment_distribution(df_comments):
    """
    Plot the distribution of sentiment scores using VADER. Filters out non-numeric "N/A"s.
    Adds additional info about mean and median.
    """

    # Convert to float and filter out N/A scores
    df = df_comments.copy()
    df["sentiment"] = pd.to_numeric(df["sentiment"], errors="coerce")
    total_count = len(df)
    valid_scores = df["sentiment"].dropna()
    valid_count = len(valid_scores)
    na_count = total_count - valid_count
    na_percent = na_count / total_count * 100

    if valid_scores.empty:
        print("No sentiment scores to plot.")
        return

    mean_val = valid_scores.mean()
    median_val = valid_scores.median()

    plt.figure(figsize=(10, 6))
    sns.histplot(valid_scores, kde=True, bins=100, color="steelblue")

    plt.axvline(mean_val, color="red", linestyle="--", linewidth=1.5, label=f"Mean  : {mean_val:.2f}")
    plt.axvline(median_val, color="orange", linestyle="--", linewidth=1.5, label=f"Median: {median_val:.2f}")

    na_text = f"{na_count} of {total_count} sentiment values were N/A ({na_percent:.1f} %)."
    plt.gca().text(0.99, 0.95, na_text, transform=plt.gca().transAxes,
                   fontsize=9, ha="right", va="top",
                   bbox=dict(boxstyle="round", facecolor="white", edgecolor="grey")
                   )

    plt.title("Distribution of Comment Sentiment Scores")
    plt.xlabel("VADER Score")
    plt.ylabel("Number")
    plt.legend()
    plt.tight_layout()
    plt.show()


def plot_comments_over_time(comments_per_day):
    """
    Plot comment activity over time with raw counts, rolling average over 1/50th of duration,
    and Top 10 comment days.
    """

    total_days = (comments_per_day.index[-1] - comments_per_day.index[0]).days  # calculate rolling avg. window
    rolling_window = max(3, total_days // 50)
    rolling_avg = comments_per_day.rolling(window=rolling_window, min_periods=1).mean()

    top_days = comments_per_day.sort_values(ascending=False).head(10)  # prepare top comment days

    plt.figure(figsize=(14, 7))

    raw_line, = plt.plot(
        comments_per_day.index,
        comments_per_day.values,
        label="Raw",
        color="cornflowerblue",
        linewidth=1,
        alpha=0.9
    )

    rolling_line, = plt.plot(
        rolling_avg.index,
        rolling_avg.values,
        label=f"Rolling Avg. ({rolling_window} days)",
        color="midnightblue",
        linewidth=2
    )

    plt.title("Comment Activity Over Time")
    plt.show()

    fig, ax_left = plt.subplots(figsize=(14, 7))
    raw_line, = ax_left.plot(
        comments_per_day.index,
        comments_per_day.values,
        label = "Raw",
        color = "cornflowerblue",
        linewidth = 1,
        alpha = 0.9
    )
    ax_left.set_ylabel("Number of Comments", color="cornflowerblue")
    ax_left.tick_params(axis="y", labelcolor="cornflowerblue")
    ax_left.grid(True, linestyle="--", alpha=0.3)

    ax_right = ax_left.twinx()
    rolling_line, = ax_right.plot(
        rolling_avg.index,
        rolling_avg.values,
        label = f"Rolling Avg. ({rolling_window} days)",
        color = "midnightblue",
        linewidth = 2
    )
    ax_right.set_ylabel("Rolling Average", color="midnightblue")
    ax_right.tick_params(axis="y", labelcolor="midnightblue")

    top_lines = ["Top Comment Days:"]
    for date, count in top_days.items():
        top_lines.append(f"- {date.strftime('%Y-%m-%d')}: {count} comments")
    text_box = mlines.Line2D([], [], color='white', label="\n".join(top_lines))

    plt.legend(handles=[raw_line, rolling_line, text_box], loc="upper right", fontsize=9)

    handles_left, labels_left = ax_left.get_legend_handles_labels()
    handles_right, labels_right = ax_right.get_legend_handles_labels()
    ax_left.legend(
        handles_left + handles_right + [text_box],
        labels_left + labels_right + [text_box.get_label()],
        loc = "upper right",
        fontsize = 9
    )

    plt.title("Comment Activity Over Time")
    plt.xlabel("Date")
    plt.ylabel("Number of Comments")
    plt.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()

    plt.show()

    ax_left.set_title(f"Comment Activity Over Time (Rolling Avg. of {rolling_window} Days)")
    ax_left.set_xlabel("Date")
    fig.tight_layout()
    plt.show()


def analyze_replies(df_comments):
    """
    Calculate the percentage of comments with replies.
    This might indicate how much actual 'discussion' takes place.
    """

    # The lambda function creates a True/False boolean indicating if there are replies.
    # This is added as a new column to the DataFrame.
    df_comments["has_replies"] = df_comments["replies"].apply(
        lambda x: len(x) > 0
    )

    # As each True is 1 and each False is 0, calculating the average will be a value between 0 and 1.
    # This is converted to a percentage and then returned.
    return df_comments["has_replies"].mean() * 100


def analyze_sentiment_over_time(df_comments):
    """
    Extract VADER sentiment scores over time.
    Missing values are skipped; only valid numeric sentiment scores are averaged.
    """

    df_comments["sentiment"] = df_comments.apply(
        lambda row: row.get("vader_sentiment", "N/A"), axis=1
    )

    df_filtered = df_comments[df_comments["sentiment"] != "N/A"].copy()
    df_filtered["sentiment"] = pd.to_numeric(df_filtered["sentiment"], errors="coerce")

    sentiment_per_day = df_filtered.groupby(df_filtered["date"].dt.date)["sentiment"].mean()  # group per date

    return sentiment_per_day


def plot_sentiment_over_time(sentiment_per_day):
    """
    Plot daily average sentiment (VADER) over time, with dynamic rolling average, mean, and median lines.
    """

    if sentiment_per_day.empty:
        print("No sentiment data available to plot.")
        return

    total_days = (sentiment_per_day.index[-1] - sentiment_per_day.index[0]).days
    rolling_window = max(3, total_days // 50)
    rolling_avg = sentiment_per_day.rolling(window=rolling_window, min_periods=1).mean()

    mean_sentiment = sentiment_per_day.mean()
    median_sentiment = sentiment_per_day.median()

    plt.figure(figsize=(14, 7))

    raw_line, = plt.plot(
        sentiment_per_day.index,
        sentiment_per_day.values,
        label="Raw",
        color="mediumseagreen",
        linewidth=1.2,
        alpha=0.8
    )

    rolling_line, = plt.plot(
        rolling_avg.index,
        rolling_avg.values,
        label=f"Rolling Avg. ({rolling_window} days)",
        color="darkgreen",
        linewidth=2
    )

    plt.axhline(mean_sentiment, color="gray", linestyle="--", linewidth=1.2, label=f"Mean: {mean_sentiment:.2f}")
    plt.axhline(median_sentiment, color="black", linestyle=":", linewidth=1.2, label=f"Median: {median_sentiment:.2f}")

    text_lines = [
        "Sentiment Trends:",
        "- Raw = daily average VADER sentiment",
        f"- Rolling = smoothed over {rolling_window} days",
        "",
        f"Mean  : {mean_sentiment:.2f}",
        f"Median: {median_sentiment:.2f}",
        f"Total Days: {len(sentiment_per_day)}"
    ]
    text_box = mlines.Line2D([], [], color="white", label="\n".join(text_lines))

    plt.legend(handles=[raw_line, rolling_line, text_box], loc="upper right", fontsize=9)

    plt.title("Sentiment Scores over Time")
    plt.xlabel("Date")
    plt.ylabel("Average Sentiment Score")
    plt.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()

    plt.show()


def plot_participation_timeline(data):
    """
    Plot the timeline of participating channels in the discussion,
    both as rolling average over time and cumulative unique count.
    """

    events = []                                         # collect info about ...
    for video_id, video_data in data.items():
        vi = video_data.get("video_info", {})

        uploader = vi.get("channel_id")                 # uploaders,
        upload_date = vi.get("published_at")
        if uploader and upload_date:
            events.append((upload_date, uploader))

        for comment in video_data.get("comments", []):  # commentators, and
            c_id = comment.get("author_channel_id")
            c_date = comment.get("date")
            if c_id and c_date:
                events.append((c_date, c_id))

            for reply in comment.get("replies", []):    # replies
                r_id = reply.get("author_channel_id")
                r_date = reply.get("date")
                if r_id and r_date:
                    events.append((r_date, r_id))

    if not events:
        print("No participation data available.")
        return

    df = pd.DataFrame(events, columns=["date", "channel_id"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date", "channel_id"])

    daily = df.groupby("date")["channel_id"].nunique()

    total_days = (daily.index[-1] - daily.index[0]).days
    rolling_window = max(3, total_days // 50)
    rolling = daily.rolling(window=rolling_window, min_periods=1).mean()

    first_seen = df.groupby("channel_id")["date"].min()
    cumulative_unique = (
        first_seen.value_counts()
        .sort_index()
        .reindex(pd.date_range(daily.index.min(), daily.index.max(), freq="D"), fill_value=0)
        .cumsum()
    )

    fig, ax1 = plt.subplots(figsize=(14, 7))

    ax1.plot(daily.index, rolling, label=f"Rolling Avg. ({rolling_window} days)",
             color="steelblue", linewidth=2)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Daily Active Channels (Rolling Avg.)", color="steelblue")
    ax1.tick_params(axis="y", labelcolor="steelblue")
    ax1.grid(True, linestyle="--", alpha=0.3)

    ax2 = ax1.twinx()
    ax2.plot(cumulative_unique.index, cumulative_unique.values,
             label="Cumulative Unique Channels",
             color="orange", linestyle="--", linewidth=2)
    ax2.set_ylabel("Cumulative Unique Channels", color="orange")
    ax2.tick_params(axis="y", labelcolor="orange")

    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels + labels2, loc="upper left", fontsize=9)

    plt.title("Active Channels Over Time")
    plt.tight_layout()
    plt.show()


def plot_interactions_by_weekday(data, figsize=(12,6), normalize=False):
    """
    Interactions by weekday, broken down by uploads, comments, replies, plus total.
    'normalize=True' would show each series as shares, summing to 1 within series.
    """

    upload_dates, comment_dates, reply_dates = [], [], []               # Start collecting dates

    for _, video_data in data.items():
        vi = video_data.get("video_info", {})
        up = vi.get("published_at")
        if up:
            upload_dates.append(up)

        for c in video_data.get("comments", []):
            d = c.get("date")
            if d:
                comment_dates.append(d)
            for r in c.get("replies", []):
                rd = r.get("date")
                if rd:
                    reply_dates.append(rd)

    if not (upload_dates or comment_dates or reply_dates):
        print("No uploads/comments/replies with valid dates found.")
        return

    def to_weekday(dates):
        if not dates:
            return pd.Series(dtype=int)                                 # empty
        s = pd.to_datetime(pd.Series(dates), errors="coerce").dropna()
        return s.dt.dayofweek                                           # 0 = Mon, and so on

    wd_uploads = to_weekday(upload_dates)
    wd_comments = to_weekday(comment_dates)
    wd_replies = to_weekday(reply_dates)

    order = [0, 1, 2, 3, 4, 5, 6]
    names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    idx = [names[i] for i in order]

    def count_series(wd):
        return (
            wd.map(names)
            .value_counts()
            .reindex(idx)
            .fillna(0)
            .astype(int)
        ) if len(wd) else pd.Series(0, index=idx, dtype=int)

    s_uploads = count_series(wd_uploads)
    s_comments = count_series(wd_comments)
    s_replies = count_series(wd_replies)
    s_total = s_uploads + s_comments + s_replies

    if normalize:
        def norm(s):
            denom = s.sum()
            return s / denom if denom else s

        s_uploads, s_comments, s_replies, s_total = map(norm, [s_uploads, s_comments, s_replies, s_total])

    fig, ax_left = plt.subplots(figsize=figsize)

    x = np.arange(len(idx))
    width = 0.35
    ax_left.bar(x - width / 2, s_comments.values, width, label="Comments")
    ax_left.bar(x + width / 2, s_replies.values, width, label="Replies")

    ax_left.plot(x, s_total.values, linewidth=2, linestyle="-", marker="o", label="Total")

    ax_left.set_xticks(x)
    ax_left.set_xticklabels(idx)
    ax_left.set_xlabel("Weekday")
    ax_left.set_ylabel("Count" if not normalize else "Share")
    ax_left.grid(True, axis="y", linestyle="--", alpha=0.3)

    ax_right = ax_left.twinx()
    line_up, = ax_right.plot(x, s_uploads.values, linestyle="--", marker="s", label="Uploads", color="tab:red")
    ax_right.set_ylabel("Uploads" if not normalize else "Uploads (share)")

    handles_left, labels_left = ax_left.get_legend_handles_labels()
    ax_left.legend(handles_left + [line_up], labels_left + ["Uploads"], loc="upper left", fontsize=9)

    plt.title("Interactions by Weekday")
    plt.tight_layout()
    plt.show()


def plot_views_vs_comments(data, include_replies=True, color_by="year", annotate_top=5, figsize=(8,7), cmap="viridis",
                           alpha=0.6, edgecolor="white", linewidth=0.4, logx=True, logy=True):
    """
    View counts vs. discussion volume.
    Coloring can be done by year or by discussion-per-view ratio.
    "annotate_top" refers to outliers that will be labeled.
    Actually, this looks like a "Hertzsprung Russell Diagram" in astronomy, when stars move on the "main sequence".
    It would be super cool having an animated version, showing how videos climb upwards during their "lifetime"
    until they finally stop. However, YT does not provide the view count history.


    """

    rows = []

    for vid, vdata in data.items():
        vi = vdata.get("video_info", {}) or {}
        views = vi.get("views")
        published = vi.get("published_at")
        if views is None:
            continue

        comments = vdata.get("comments", []) or []
        n_comm = len(comments)
        n_repl = sum(len(c.get("replies", [])) for c in comments)
        total_disc = n_comm + (n_repl if include_replies else 0)

        try:
            year = pd.to_datetime(published).year if published else None
        except Exception:
            year = None

        rows.append({
            "video_id": vid,
            "views": views,
            "discussion": total_disc,
            "year": year
        })

    df = pd.DataFrame(rows)
    if df.empty:
        print("No data for correlation plot.")
        return

    eps = 1e-9
    df["ratio"] = df["discussion"] / (df["views"] + eps)

    q90 = np.percentile(df["discussion"], 90) if (df["discussion"] > 0).any() else 1
    df["size"] = 20 + 120 * np.clip(df["discussion"] / (q90 if q90 else 1), 0, 1)

    if color_by == "ratio":
        colors = df["ratio"]
        cbar_label = "Discussion per View"
    else:
        min_year = int(df["year"].dropna().min()) if df["year"].notna().any() else 0
        colors = df["year"].fillna(min_year - 1)
        cbar_label = "Upload Year"

    fit_df = df[(df["views"] > 0) & (df["discussion"] > 0)].copy()
    if not fit_df.empty:
        xlog = np.log10(fit_df["views"])
        ylog = np.log10(fit_df["discussion"])
        slope, intercept = np.polyfit(xlog, ylog, 1)
        vx = np.logspace(np.log10(df["views"].replace(0, np.nan).min()),
                         np.log10(df["views"].max()), 200)
        vy = 10 ** (intercept + slope * np.log10(vx))
    else:
        vx = vy = None
        slope = intercept = np.nan

    df["discussion_plot"] = df["discussion"] + 1e-3     # create a minimal offset to avoid 0s disapperaring in log scale

    plt.figure(figsize=figsize)
    sc = plt.scatter(
        df["views"], df["discussion_plot"],             # discussion/discussion_plot: switch 0-commen vids off/on
        c=colors, cmap=cmap, s=df["size"],
        alpha=alpha, edgecolors=edgecolor, linewidths=linewidth
    )

    if vx is not None:
        plt.plot(vx, vy, linestyle="--", linewidth=1.8, color="black",
                 label=f"Trend ~ views^{slope:.2f}")

    if logx: plt.xscale("log")
    if logy: plt.yscale("log")

    plt.xlabel("Views")
    plt.ylabel("Comments + Replies" if include_replies else "Comments")
    plt.title("Views vs. Discussion Volume")

    cbar = plt.colorbar(sc)
    cbar.set_label(cbar_label)

    if annotate_top and len(df) > 0:
        top = df.sort_values("ratio", ascending=False).head(annotate_top)
        for _, r in top.iterrows():
            plt.annotate(
                r["video_id"],
                xy=(r["views"], r["discussion"]),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=8,
                alpha=0.9
            )

    if vx is not None:
        plt.legend(loc="lower right", bbox_to_anchor=(1, 0.1), frameon=True)    # bbox: move a bit upwards, stay right

    plt.tight_layout()
    plt.show()


def plot_uploads_over_time(data, freq="M"):
    """
    Plot the number of uploaded videos over time.
    freq: "D" = daily, "W" = weekly, "M" = monthly, "Y" = yearly
    """

    if freq not in ["D", "W", "M", "Y"]:
        freq = "M"

    dates = []
    for _, vdata in data.items():
        video = vdata.get("video_info", {}) or {}
        date = video.get("published_at")
        if date:
            dates.append(date)

    if not dates:
        print("No data on video update.")
        return

    series = pd.to_datetime(pd.Series(dates), errors="coerce").dropna().dt.normalize()
    if series.empty:
        print("Could not parse dates.")
        return

    counts = series.value_counts().sort_index()
    full_index = pd.date_range(counts.index.min(), counts.index.max(), freq="D")
    daily = counts.reindex(full_index, fill_value=0)

    if freq != "D":
        series = daily.resample(freq).sum()
    else:
        series = daily

    total_span = (series.index[-1] - series.index[0]).days or 1     # rolling average as usual
    rolling_window = max(3, total_span // 50)
    rolling = series.rolling(window=rolling_window, min_periods=1).mean()

    top = series.sort_values(ascending=False).head(10)

    plt.figure(figsize=(14, 7))

    raw_line, = plt.plot(series.index, series.values, label="Raw", linewidth=1.2, alpha=0.9)
    roll_line, = plt.plot(rolling.index, rolling.values, label=f"Rolling Avg. ({rolling_window} units)", linewidth=2)

    top_lines = [f"Top Periods ({freq}):"]
    if freq == "D":
        fmt = "%Y-%m-%d"
    elif freq == "W":
        fmt = "CW %G-%V"
    elif freq == "M":
        fmt = "%Y-%m"
    else:
        fmt = "%Y-%m-%d"

    for idx, val in top.items():
        label = idx.strftime(fmt) if hasattr(idx, "strftime") else str(idx)
        top_lines.append(f"- {label}: {int(val)} uploads")

    text_box = mlines.Line2D([], [], color="white", label="\n".join(top_lines))

    plt.legend(handles=[raw_line, roll_line, text_box], loc="upper right", fontsize=9)

    if freq == "D":
        title_suffix = "Daily"
        x_label = "Date"
    elif freq == "W":
        title_suffix = "Weekly"
        x_label = "Week"
    elif freq == "M":
        title_suffix = "Monthly"
        x_label = "Month"
    else:
        title_suffix = f"Resampled ({freq})"
        x_label = "Time"

    plt.title(f"Video Uploads Over Time ({title_suffix})")
    plt.xlabel(x_label)
    plt.ylabel("Number of Uploads")
    plt.grid(True, linestyle="--", alpha=0.3)
    plt.tight_layout()
    plt.show()


def collect_views_dataframe(data):
    """
    Extract a tuple of (video_id, title, views), return DataFrame video_id, title, views.
    """

    rows = []
    for vid, vdata in data.items():
        vi = vdata.get("video_info", {}) or {}
        views = vi.get("views", None)
        title = vi.get("title", "[No Title]")

        if views is None:
            continue

        rows.append({
            "video_id": vid,
            "title"   : title,
            "views"   : views
        })

    df = pd.DataFrame(rows)
    if df.empty:
        print("No valid views counts in data.")
        return df

    return df.sort_values("views", ascending=False).reset_index(drop=True)


def shorten(text, n=60):
    return (text[:n] + "…") if isinstance(text, str) and len(text) > n else (text if text else "")


def plot_top_videos_by_views(df, top_n=15, title_suffix=""):
    top = df.head(top_n).copy()
    if top.empty:
        print("No data for top-n views plots.")
        return

    top = top.iloc[::-1]            #   largest count on top
    labels = [f"{shorten(t)}" for t in top["title"]]

    plt.figure(figsize=(12, max(6, 0.45 * len(top))))
    plt.barh(labels, top["views"].values)
    plt.xlabel("Views")
    plt.title(f"Top {len(top)} Viewed Videos" + (f" — {title_suffix}" if title_suffix else ""))

    for i, v in enumerate(top["views"].values):
        plt.text(v, i, f" {int(v):,}".replace(",", "."), va="center", fontsize=9)
    plt.tight_layout()
    plt.show()


def plot_views_distribution(df):
    views = df["views"].astype(float).values

    if views.size == 0:
        print("No data for view plots.")
        return

    finite_mask = np.isfinite(views)
    views_finite = views[finite_mask]
    if views_finite.size == 0:
        print("No finite data for plots.")
        return

    pos_mask = (views_finite > 0)
    vpos = views_finite[pos_mask]
    if vpos.size == 0:
        print("No positive values; skipping log-space plots.")
        return

    plt.figure(figsize=(12, 6))
    plt.hist(vpos, bins=np.logspace(np.log10(vpos.min()), np.log10(vpos.max()), 50))
    plt.xscale("log")
    plt.xlabel("Views (log scale)")
    plt.ylabel("Number of Videos")
    plt.title("Video View Counts")
    plt.tight_layout()
    plt.show()

    logv = np.log10(vpos)

    median = np.median(logv)
    q1 = np.percentile(logv, 25)
    q3 = np.percentile(logv, 75)
    mean = np.mean(logv)

    plt.figure(figsize=(10, 4))
    parts = plt.violinplot(dataset=[logv], vert=False, showmeans=True, showextrema=False, showmedians=True)
    plt.yticks([])
    plt.xlabel("log10(Views)")
    plt.title("Video View Counts")

    stats_text = (
        f"Mean: {10 ** mean:,.0f}\n"
        f"Median: {10 ** median:,.0f}\n"
        f"Q1: {10 ** q1:,.0f}\n"
        f"Q3: {10 ** q3:,.0f}"
    ).replace(",", ".")

    plt.legend([parts['bodies'][0]], [stats_text], loc="upper right", fontsize=9, frameon=True)
    plt.tight_layout()
    plt.show()


def analyze_views_static(data, top_n=15, log_hist=True, bins="auto"):
    """
    View counts plots
    """

    df = collect_views_dataframe(data)
    if df.empty:
        return
    plot_top_videos_by_views(df, top_n=top_n)
    plot_views_distribution(df)


def tubescope(filename):
    """
    Run the analyses for all video IDs in the data.
    """

    data = load_data(filename)

    if not data:
        logger.error("No data to analyze.")
        print("No data to analyze.")
        return



    logo = """
┌───────────────────────────────────────────────────────────────────┐
│ Welcome to ______      __        _____                         __ │
│           ╱_  __╱_  __╱ ╱_  ___ ╱ ___╱_________  ____  ___    ╱╱╱ │
│            ╱ ╱ ╱ ╱ ╱ ╱ __ ╲╱ _ ╲╲__ ╲╱ ___╱ __ ╲╱ __ ╲╱ _ ╲  ╱╱╱  │
│           ╱ ╱ ╱ ╱_╱ ╱ ╱_╱ ╱  __╱__╱ ╱ ╱__╱ ╱_╱ ╱ ╱_╱ ╱  __╱       │
│          ╱_╱  ╲__,_╱_.___╱╲___╱____╱╲___╱╲____╱ .___╱╲___╱ ╱╱╱    │
│    							      		   ╱_╱                  │
└───────────────────────────────────────────────────────────────────┘
"""

    print(logo)

    all_comments = []

    for video_id, video_data in data.items():
        video_ids, comments = extract_video_info(video_id, video_data)
        all_comments.extend(comments)

    df_comments = analyze_comments(all_comments)

    print(f"Generating cumulative analysis plots for {len(data)} videos with {len(df_comments)} comments.")

    plot_comments_over_time(group_comments_by_date(df_comments))
    plot_participation_timeline(data)

    plot_comment_likes_distribution(df_comments)
    plot_sentiment_over_time(analyze_sentiment_over_time(df_comments))
    plot_sentiment_distribution(df_comments)

    plot_interaction_density_distribution(data)
    plot_interactions_by_weekday(data)

    plot_uploads_over_time(data)

    plot_views_vs_comments(data)

    analyze_views_static(data)

    return
