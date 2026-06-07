"""
Quick Report PDF generator for YTCM.
Converts a collection of analysis images into a styled PDF report.
"""

import base64
import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Image as RLImage, PageBreak, HRFlowable,
)

PAGE_W, PAGE_H = A4
MARGIN = 0.75 * inch
CONTENT_W = PAGE_W - 2 * MARGIN

# Ordered sections: (images_key, display_title, plain-English description)
SECTIONS = [
    (
        "activity",
        "Comment Activity Over Time",
        "Shows how comment volume has changed over time across all videos in the dataset. "
        "Each bar represents a time period — taller bars mean more comments were posted. "
        "Peaks often correspond to viral moments, trending topics, or new video uploads "
        "that sparked audience discussion.",
    ),
    (
        "sentiment_trend",
        "Sentiment Trend Over Time",
        "Tracks how the emotional tone of comments has shifted over time. "
        "Positive values reflect enthusiasm or support; negative values reflect criticism "
        "or dissatisfaction. Use this chart to spot whether audience mood changed "
        "after specific events or video releases.",
    ),
    (
        "sentiment_dist",
        "Sentiment Distribution",
        "A snapshot of the overall emotional balance across all comments — "
        "showing how many are positive, neutral, or negative. "
        "A mostly positive distribution suggests the content resonates well with its audience.",
    ),
    (
        "likes",
        "Comment Likes Distribution",
        "Shows how many likes individual comments received. Most comments get very few likes, "
        "but a small number attract many — these represent the opinions the audience found "
        "most relatable, funny, or insightful. A long tail indicates strong community "
        "consensus around certain views.",
    ),
    (
        "weekdays",
        "Engagement by Day of Week",
        "Reveals which days of the week see the highest comment activity. "
        "Spikes on certain days may reflect when videos were published, "
        "when they were shared on social media, or simply when the target audience "
        "is most active online.",
    ),
    (
        "views",
        "Views vs. Comment Count",
        "Compares how many views each video received against how many comments it generated. "
        "Videos above the trend line generated more discussion than expected for their "
        "view count — these are the ones that truly sparked conversation.",
    ),
    (
        "uploads",
        "Video Uploads Over Time",
        "Maps the publication dates of all videos in the dataset. "
        "Gaps indicate periods of inactivity; clusters show bursts of content creation. "
        "This chart helps you understand the content cadence of the channels involved.",
    ),
    (
        "channels",
        "Channel Participation Timeline",
        "Shows when different channels first appeared in the conversation — "
        "either as video uploaders or as commenters. "
        "An expanding cast of participants over time suggests a growing and "
        "diversifying community around this topic.",
    ),
    (
        "languages",
        "Comment Language Distribution",
        "Breaks down what languages commenters used. "
        "A single dominant language suggests a local or niche audience; "
        "a diverse mix indicates international reach. "
        "Language is detected automatically from comment text.",
    ),
    (
        "wordcloud",
        "Word Cloud",
        "Visualises the most frequently used words in comments — the larger the word, "
        "the more often it appeared. Common stop words are filtered out to reveal "
        "the actual topics, names, and themes dominating the conversation.",
    ),
    (
        "channelstats",
        "Top Channels by Role",
        "Ranks the most active channels segmented by their role: "
        "uploaders (video creators), commenters (top-level comment authors), "
        "repliers (those who responded to others), and total activity. "
        "This reveals the key players in this topic space.",
    ),
    (
        "network",
        "Interaction Network",
        "A force-directed graph where each node is a channel and each edge represents "
        "an interaction (comment or reply). Nodes with more connections are the most "
        "influential participants. Tight clusters indicate sub-communities within "
        "the broader conversation.",
    ),
]


def _b64_to_rl_image(b64_str: str, max_width: float = CONTENT_W):
    """Decode a base64 PNG string and return a ReportLab Image flowable."""
    if not b64_str:
        return None
    if "," in b64_str:
        b64_str = b64_str.split(",", 1)[1]
    try:
        img_bytes = base64.b64decode(b64_str)
        buf = io.BytesIO(img_bytes)
        reader = ImageReader(buf)
        iw, ih = reader.getSize()
        width = min(max_width, iw)
        height = width * (ih / iw)
        buf.seek(0)
        return RLImage(buf, width=width, height=height)
    except Exception:
        return None


def generate_pdf(output_path: str, summary: dict, images: dict) -> None:
    """Build and write the Quick Report PDF to output_path."""

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "QRTitle",
        parent=styles["Title"],
        fontSize=26,
        textColor=colors.HexColor("#C6F135"),
        spaceAfter=4,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        "QRSubtitle",
        parent=styles["Normal"],
        fontSize=13,
        textColor=colors.HexColor("#94a3b8"),
        spaceAfter=4,
        fontName="Helvetica",
        alignment=TA_CENTER,
    )
    meta_style = ParagraphStyle(
        "QRMeta",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#e2e8f0"),
        spaceAfter=3,
        fontName="Helvetica",
    )
    vid_head_style = ParagraphStyle(
        "QRVidHead",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#C6F135"),
        spaceBefore=12,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    vid_item_style = ParagraphStyle(
        "QRVidItem",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#94a3b8"),
        spaceAfter=2,
        leading=14,
        fontName="Helvetica",
    )
    section_title_style = ParagraphStyle(
        "QRSectionTitle",
        parent=styles["Heading1"],
        fontSize=15,
        textColor=colors.HexColor("#C6F135"),
        spaceBefore=14,
        spaceAfter=5,
        fontName="Helvetica-Bold",
    )
    desc_style = ParagraphStyle(
        "QRDesc",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#94a3b8"),
        spaceAfter=8,
        leading=15,
        fontName="Helvetica",
    )

    story = []

    # ── Cover page ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.2 * inch))
    story.append(Paragraph("YTCM Quick Report", title_style))
    story.append(Paragraph(f'Keyword: <b>{summary.get("keyword", "")}</b>', subtitle_style))
    story.append(Spacer(1, 0.25 * inch))
    story.append(HRFlowable(
        width="100%", thickness=1,
        color=colors.HexColor("#C6F135"), spaceAfter=16,
    ))
    story.append(Paragraph(f'Videos analysed: {summary.get("num_videos", 0)}', meta_style))
    story.append(Paragraph(
        f'Total comments: {summary.get("total_comments", 0):,}', meta_style,
    ))
    story.append(Paragraph(
        f'Generated: {datetime.now().strftime("%B %d, %Y at %H:%M")}', meta_style,
    ))

    titles = summary.get("video_titles", [])
    if titles:
        story.append(Paragraph("Videos included:", vid_head_style))
        for i, t in enumerate(titles, 1):
            story.append(Paragraph(f"{i}. {t}", vid_item_style))

    story.append(PageBreak())

    # ── Analysis sections ─────────────────────────────────────────────────────
    for key, title, description in SECTIONS:
        imgs = images.get(key) or []
        if not imgs:
            continue

        story.append(Paragraph(title, section_title_style))
        story.append(Paragraph(description, desc_style))
        story.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#334155"), spaceAfter=6,
        ))

        for b64 in imgs:
            rl_img = _b64_to_rl_image(b64)
            if rl_img:
                story.append(rl_img)
                story.append(Spacer(1, 0.12 * inch))

        story.append(Spacer(1, 0.25 * inch))

    doc.build(story)
