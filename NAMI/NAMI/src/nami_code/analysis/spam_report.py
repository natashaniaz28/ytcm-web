"""
Build an HTML spam report: an embedded gallery of the flagged reels followed by
statistics on what attracts spam.

Read-only. The spam set is recomputed here the same way ``checkspam`` marks it —
caption spam-term matches (config/domain.yaml) unioned with vision ``blocked``
reels (content-policy refusals) — so the report is self-contained and works even
before ``checkspam`` has persisted the ``is_spam`` column. Each reel keeps its
provenance (which terms fired, and/or "blocked"), and the stats cover: the spam
terms that fired, the vision/Gemini block+error counts, which song/asset attracts
spam, whether uploads come in temporal spikes, uploader (channel) concentration,
duplicate captions, and engagement vs. the rest of the corpus.
"""
from __future__ import annotations

import os
import sqlite3
import html
from pathlib import Path

import pandas as pd

from nami_code.analysis.check_spam import load_spam_terms

DB_PATH = "data/corpus.db"
OUT_HTML = "outputs/report_out/spam_report.html"
IMG_DIR = "data/thumbnails"
MEDIA_DIR = "data/reels"
GALLERY_LIMIT = 150


def _matched_terms(caption: str | None, terms: list[str]) -> list[str]:
    """The configured spam terms that occur in *caption* (case-insensitive)."""
    text = (caption or "").lower()
    return [t for t in terms if t in text]


def _bar(n: float, maxn: float, color: str = "#e0566f", w: int = 240) -> str:
    """A fixed-scale inline bar with its value, for the stat tables."""
    px = 0 if not maxn else max(2, int(round(w * n / maxn)))
    return (f"<span class='bar' style='width:{px}px;background:{color}'></span>"
            f"<span class='barn'>{n:g}</span>")


def _section(title: str) -> str:
    return f"<h2>{html.escape(title)}</h2>"


def _img_data_uri(path: Path) -> str:
    """Inline a thumbnail JPEG as a base64 data-URI so the still travels with the
    HTML (the MP4 itself is left as a local reference — too large to embed)."""
    import base64
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build(db_path: str = DB_PATH, out_html: str = OUT_HTML,
          img_dir: str = IMG_DIR, media_dir: str = MEDIA_DIR,
          gallery_limit: int = GALLERY_LIMIT, include_blocked: bool = True,
          domain_config: dict | None = None,
          domain_path: str = "config/domain.yaml") -> str:
    """Write the spam report HTML and return its path."""
    terms = load_spam_terms(domain_config=domain_config, domain_path=domain_path)

    conn = sqlite3.connect(db_path)
    reels = pd.read_sql(
        "SELECT reel_pk, song_id, asset_id, variant_label, code, creator_pseudo, "
        "taken_at, caption_text, like_count, play_count, comment_count FROM reels", conn)
    try:
        vstate = pd.read_sql("SELECT reel_pk, status FROM vision_state", conn)
    except Exception:
        vstate = pd.DataFrame(columns=["reel_pk", "status"])
    conn.close()

    reels["reel_pk"] = reels["reel_pk"].astype(str)
    vmap = dict(zip(vstate["reel_pk"].astype(str), vstate["status"]))
    reels["vstatus"] = reels["reel_pk"].map(vmap)
    reels["matched_terms"] = reels["caption_text"].apply(lambda c: _matched_terms(c, terms))
    reels["is_term"] = reels["matched_terms"].apply(bool)
    reels["is_blocked"] = reels["vstatus"].eq("blocked") & bool(include_blocked)
    reels["is_spam"] = reels["is_term"] | reels["is_blocked"]

    spam = reels[reels["is_spam"]].copy()
    total, n_spam = len(reels), len(spam)
    n_term = int(reels["is_term"].sum())
    n_blocked = int(reels["is_blocked"].sum())
    n_both = int((reels["is_term"] & reels["is_blocked"]).sum())

    P: list[str] = [
        "<html><head><meta charset='utf-8'><title>NAMI spam report</title><style>",
        "body{background:#15151f;color:#e8e8ee;font-family:sans-serif;padding:24px;max-width:1180px;margin:auto}",
        "h1{color:#ff6b81}h2{color:#ffd479;border-bottom:1px solid #3a3a4a;margin-top:46px;padding-bottom:4px}",
        ".sub{color:#9aa;margin-top:-6px}",
        "table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}",
        "td,th{padding:4px 8px;text-align:left;border-bottom:1px solid #2a2a38;vertical-align:middle}",
        "th{color:#ffd479}",
        ".bar{display:inline-block;height:11px;border-radius:3px;vertical-align:middle}",
        ".barn{color:#cdd;margin-left:7px;font-size:12px}",
        ".kpis{display:flex;flex-wrap:wrap;gap:14px;margin:14px 0}",
        ".kpi{background:#1f1f2e;border-radius:10px;padding:12px 18px;min-width:120px}",
        ".kpi b{display:block;font-size:24px;color:#ff6b81}.kpi span{color:#9aa;font-size:12px}",
        ".grid{display:flex;flex-wrap:wrap;gap:12px}",
        ".card{width:190px;background:#1b1b2a;border-radius:9px;padding:8px;font-size:11px}",
        ".card img,.card video,.card iframe{width:174px;height:174px;object-fit:cover;border:0;border-radius:5px;background:#000}",
        ".cap{color:#9aa;max-height:54px;overflow:hidden;margin-top:4px}",
        ".meta{color:#bcd;margin-top:3px}.lnk a{color:#7fd1ff;text-decoration:none}",
        ".badge{display:inline-block;border-radius:4px;padding:1px 6px;margin:2px 2px 0 0;font-size:10px;font-weight:bold}",
        ".b-term{background:#7a3b00;color:#ffce8a}.b-block{background:#5e1024;color:#ff9db0}",
        ".note{color:#9aa;font-size:12px}",
        "</style></head><body>",
        "<h1>🚫 NAMI spam report</h1>",
        f"<p class='sub'>{n_spam} flagged reels of {total} "
        f"({(100*n_spam/total if total else 0):.1f}% of the corpus). Spam = caption "
        f"spam-term match {'∪ vision content-policy block' if include_blocked else ''}.</p>",
    ]

    P.append("<div class='kpis'>")
    for val, lab in [(n_spam, "flagged total"), (n_term, "caption-term"),
                     (n_blocked, "vision-blocked"), (n_both, "both reasons"),
                     (spam["creator_pseudo"].nunique() if n_spam else 0, "distinct uploaders")]:
        P.append(f"<div class='kpi'><b>{val}</b><span>{lab}</span></div>")
    P.append("</div>")

    if n_spam == 0:
        P.append("<p>No spam reels found. 🎉</p></body></html>")
        Path(out_html).parent.mkdir(parents=True, exist_ok=True)
        Path(out_html).write_text("\n".join(P), encoding="utf-8")
        print(f"Spam report saved: {out_html}")
        return out_html

    P.append(_section("Spam terms that fired"))
    term_counts = (spam.explode("matched_terms")["matched_terms"]
                   .dropna().value_counts())
    if term_counts.empty:
        P.append("<p class='note'>No caption-term matches (all flags are vision blocks).</p>")
    else:
        mx = int(term_counts.max())
        P.append("<table><tr><th>term</th><th>reels</th></tr>")
        for term, c in term_counts.items():
            P.append(f"<tr><td>{html.escape(str(term))}</td><td>{_bar(int(c), mx)}</td></tr>")
        P.append("</table>")

    P.append(_section("Vision / Gemini outcomes"))
    P.append("<p class='note'>How the vision tagger resolved reels. <b>blocked</b> = content-policy "
             "refusal (counted as spam); <b>failed</b> = a genuine tagging error (not spam, shown for context).</p>")
    vc = reels["vstatus"].value_counts(dropna=True)
    P.append("<table><tr><th>vision_state</th><th>reels</th></tr>")
    mxv = int(vc.max()) if not vc.empty else 0
    for st, c in vc.items():
        col = "#5e1024" if st == "blocked" else ("#704000" if st == "failed" else "#2f4858")
        P.append(f"<tr><td>{html.escape(str(st))}</td><td>{_bar(int(c), mxv, color=col)}</td></tr>")
    P.append(f"<tr><td>(no vision record)</td><td>{int(reels['vstatus'].isna().sum())}</td></tr>")
    P.append("</table>")

    P.append(_section("Which song / track variant attracts spam"))
    P.append("<p class='note'>Spam count and share within each song's reels (rate = spam ÷ total). "
             "A high rate means the song disproportionately attracts spam.</p>")
    for key, label in [("song_id", "Song"), ("variant_label", "Track variant")]:
        g = reels.groupby(key).agg(total=("reel_pk", "size"), spam=("is_spam", "sum"))
        g = g[g["spam"] > 0].copy()
        g["rate"] = g["spam"] / g["total"]
        g = g.sort_values("spam", ascending=False).head(15)
        if g.empty:
            continue
        mxs = int(g["spam"].max())
        P.append(f"<h3 style='color:#cdd'>{label}</h3><table>"
                 "<tr><th>" + label.lower() + "</th><th>spam</th><th>of total</th><th>rate</th></tr>")
        for name, row in g.iterrows():
            P.append(f"<tr><td>{html.escape(str(name))}</td>"
                     f"<td>{_bar(int(row['spam']), mxs)}</td>"
                     f"<td>{int(row['total'])}</td>"
                     f"<td>{row['rate']*100:.1f}%</td></tr>")
        P.append("</table>")

    P.append(_section("Upload timing — are there spikes?"))
    spam["dt"] = pd.to_datetime(spam["taken_at"], utc=True, errors="coerce")
    dated = spam.dropna(subset=["dt"]).copy()
    if dated.empty:
        P.append("<p class='note'>No usable timestamps.</p>")
    else:
        dated["date"] = dated["dt"].dt.date
        daily = dated.groupby("date").size().sort_index()
        mean, std = daily.mean(), daily.std(ddof=0)
        thr = mean + 2 * std
        spikes = daily[(daily >= max(thr, 2)) & (daily > mean)]
        P.append(f"<p class='note'>{len(daily)} active days, mean {mean:.1f} spam/day, "
                 f"σ {std:.1f}. A spike day = ≥ mean+2σ ({thr:.1f}). "
                 f"<b>{len(spikes)}</b> spike day(s); top spam days:</p>")
        top_days = daily.sort_values(ascending=False).head(15)
        mxd = int(top_days.max())
        P.append("<table><tr><th>date</th><th>spam reels</th><th></th></tr>")
        for d, c in top_days.items():
            flag = " 🔺spike" if d in spikes.index else ""
            P.append(f"<tr><td>{d}{flag}</td><td>{_bar(int(c), mxd, color='#c06')}</td><td></td></tr>")
        P.append("</table>")

    P.append(_section("Uploader concentration — same channels?"))
    by_creator = spam.groupby("creator_pseudo").size().sort_values(ascending=False)
    n_creators = int(by_creator.size)
    top5_share = by_creator.head(5).sum() / n_spam * 100
    repeat = int((by_creator >= 3).sum())
    P.append(f"<p class='note'>{n_spam} spam reels from <b>{n_creators}</b> uploaders "
             f"(avg {n_spam/n_creators:.1f} each). Top-5 uploaders account for "
             f"<b>{top5_share:.0f}%</b> of spam; <b>{repeat}</b> uploader(s) posted ≥3 spam reels "
             f"(likely dedicated spam channels).</p>")
    mxc = int(by_creator.max())
    P.append("<table><tr><th>uploader (pseudonymized)</th><th>spam reels</th></tr>")
    for cr, c in by_creator.head(15).items():
        P.append(f"<tr><td>{html.escape(str(cr))}</td><td>{_bar(int(c), mxc, color='#3a8')}</td></tr>")
    P.append("</table>")

    P.append(_section("Repeated captions (copy-paste / bot signature)"))
    capn = spam["caption_text"].fillna("").str.strip().str.lower()
    dup = capn[capn != ""].value_counts()
    dup = dup[dup > 1].head(12)
    if dup.empty:
        P.append("<p class='note'>No caption repeated across multiple spam reels.</p>")
    else:
        P.append("<table><tr><th>caption (truncated)</th><th>reels</th></tr>")
        for cap, c in dup.items():
            P.append(f"<tr><td>{html.escape(cap[:110])}</td><td>{int(c)}</td></tr>")
        P.append("</table>")

    P.append(_section("Engagement: spam vs. rest of corpus"))
    P.append("<table><tr><th>metric (mean)</th><th>spam</th><th>non-spam</th></tr>")
    for col, lab in [("like_count", "likes"), ("play_count", "plays"), ("comment_count", "comments")]:
        s = reels.loc[reels["is_spam"], col].mean()
        n = reels.loc[~reels["is_spam"], col].mean()
        P.append(f"<tr><td>{lab}</td><td>{(s or 0):,.0f}</td><td>{(n or 0):,.0f}</td></tr>")
    P.append("</table>")

    P.append(_section(f"Flagged reels (showing up to {gallery_limit})"))
    P.append("<p class='note'>Ordered by uploader then date so same-channel clusters sit together. "
             "Thumbnail stills are embedded (so this page is shareable as-is); the playable MP4 "
             "is a local reference and only plays from your machine.</p>")
    img_p, media_p = Path(img_dir), Path(media_dir)
    out_dir = Path(out_html).resolve().parent
    def _src(p: Path) -> str:
        return os.path.relpath(p.resolve(), out_dir).replace(os.sep, "/")
    gal = spam.sort_values(["creator_pseudo", "taken_at"]).head(gallery_limit)
    P.append("<div class='grid'>")
    for _, r in gal.iterrows():
        pk = r["reel_pk"]
        mp4, jpg = media_p / f"{pk}.mp4", img_p / f"{pk}.jpg"
        code = r.get("code")
        if mp4.exists():
            poster = f' poster="{_img_data_uri(jpg)}"' if jpg.exists() else ""
            media = f"<video controls preload='none'{poster} src='{_src(mp4)}'></video>"
        elif jpg.exists():
            media = f'<img loading="lazy" src="{_img_data_uri(jpg)}">'
        elif code:
            media = (f"<iframe loading='lazy' src='https://www.instagram.com/reel/"
                     f"{html.escape(str(code))}/embed'></iframe>")
        else:
            media = "<div class='note'>[no media]</div>"
        badges = "".join(f"<span class='badge b-term'>{html.escape(t)}</span>"
                         for t in (r["matched_terms"] or []))
        if r["is_blocked"]:
            badges += "<span class='badge b-block'>BLOCKED</span>"
        date = str(r["taken_at"] or "")[:10]
        cap = html.escape((r["caption_text"] or "")[:90])
        link = (f"<div class='lnk'><a href='https://www.instagram.com/reel/{html.escape(str(code))}'"
                f" target='_blank'>open ↗</a></div>") if code else ""
        P.append(
            f"<div class='card'>{media}<div>{badges}</div>"
            f"<div class='meta'>♪ {html.escape(str(r['song_id'] or '?'))} · {date}</div>"
            f"<div class='meta'>@{html.escape(str(r['creator_pseudo'] or '?'))}</div>"
            f"<div class='cap'>{cap}</div>{link}</div>")
    P.append("</div>")

    P.append("</body></html>")
    Path(out_html).parent.mkdir(parents=True, exist_ok=True)
    Path(out_html).write_text("\n".join(P), encoding="utf-8")
    print(f"Spam report saved: {out_html}  ({n_spam} flagged reels)")
    return out_html


if __name__ == "__main__":
    build()
