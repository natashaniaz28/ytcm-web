import os, sqlite3, html
from pathlib import Path
import pandas as pd

DB_PATH  = "data/corpus.db"
IMG_DIR  = "data/thumbnails"
MEDIA_DIR = "data/reels"
OUT_HTML = "outputs/report_out/validation_visual.html"
PER_CAT  = 20
MIN_CONF = 0.2
ONLY_DIM = None
SEED     = 42


def build(db_path=DB_PATH, out_html=OUT_HTML, img_dir=IMG_DIR, media_dir=MEDIA_DIR,
          min_conf=MIN_CONF, per_cat=PER_CAT, only_dim=ONLY_DIM):
    """
    Build an HTML page showing example reels for each vision category, so a person can check the tags by eye.
    """
    conn = sqlite3.connect(db_path)
    ann = pd.read_sql("""
        SELECT a.reel_pk, a.dimension, a.category, a.confidence,
               r.caption_text, r.code
        FROM annotations a JOIN reels r ON r.reel_pk=a.reel_pk
        WHERE a.source='vision' AND a.confidence >= ?
    """, conn, params=(min_conf,))
    conn.close()
    if only_dim:
        ann = ann[ann["dimension"] == only_dim]
    if ann.empty:
        print("No vision tags found."); return

    img_dir = Path(img_dir)
    media_dir = Path(media_dir)

    parts = ["<html><head><meta charset='utf-8'><style>",
             "body{background:#1a1a2e;color:#eee;font-family:sans-serif;padding:20px}",
             "h2{color:#ffd700;border-bottom:1px solid #444;margin-top:40px}",
             ".grid{display:flex;flex-wrap:wrap;gap:10px}",
             ".card{width:160px;background:#16213e;border-radius:8px;padding:6px;font-size:11px}",
             ".card img,.card video{width:160px;height:160px;object-fit:cover;border-radius:4px}",
             ".conf{color:#ffd700} .cap{color:#aaa;max-height:48px;overflow:hidden}",
             ".lnk a{color:#7fd1ff;text-decoration:none}",
             "</style></head><body>",
             "<h1>Vision Tag Validation</h1>",
             "<p>Random reels per category. Play the clip (or view the thumbnail) and "
             "check whether the category fits the actual content.</p>"]

    out_parent = Path(out_html).resolve().parent
    def _src(p: Path) -> str:
        return os.path.relpath(p.resolve(), out_parent).replace(os.sep, "/")

    for (dim, cat), grp in ann.groupby(["dimension", "category"]):
        take = grp.sample(min(per_cat, len(grp)), random_state=SEED)
        parts.append(f"<h2>{dim} / {cat} &nbsp;<small>({len(grp)} reels in total)</small></h2>")
        parts.append("<div class='grid'>")
        for _, r in take.iterrows():
            pk = r["reel_pk"]
            mp4 = media_dir / f"{pk}.mp4"
            jpg = img_dir / f"{pk}.jpg"
            cap = html.escape((r["caption_text"] or "")[:80])
            link = ""
            if r.get("code"):
                url = f"https://www.instagram.com/reel/{r['code']}"
                link = f"<div class='lnk'><a href='{url}' target='_blank'>open reel ↗</a></div>"
            if mp4.exists():
                media_tag = f"<video controls preload='metadata' src='{_src(mp4)}'></video>"
            elif jpg.exists():
                media_tag = f"<img src='{_src(jpg)}'>"
            else:
                media_tag = "[no media]"
            parts.append(
                f"<div class='card'>{media_tag}"
                f"<div class='conf'>{r['confidence']:.2f}</div>"
                f"<div class='cap'>{cap}</div>{link}</div>")
        parts.append("</div>")
    parts.append("</body></html>")
    Path(out_html).parent.mkdir(parents=True, exist_ok=True)
    Path(out_html).write_text("\n".join(parts), encoding="utf-8")
    print(f"Gallery saved: {out_html}")
    print("Please open in your local browser.")


if __name__ == "__main__":
    build()
