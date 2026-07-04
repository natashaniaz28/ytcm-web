import sqlite3, random, csv
from pathlib import Path
import pandas as pd

DB_PATH   = "data/corpus.db"
CSV_PATH  = "validation_sample.csv"
SAMPLE_N  = 12
MIN_CONF  = 0.2
SEED      = 42

def sample(db_path):
    """
    Pick a handful of tagged reels per category and write them to a CSV for a person to judge by hand.
    """
    conn = sqlite3.connect(db_path)
    ann = pd.read_sql("""
        SELECT a.reel_pk, a.dimension, a.category, a.confidence,
               r.caption_text, r.code
        FROM annotations a JOIN reels r ON r.reel_pk=a.reel_pk
        WHERE a.source='vision' AND a.confidence >= ?
    """, conn, params=(MIN_CONF,))
    conn.close()
    if ann.empty:
        print("No vision tags found. Run tag_vision.py first."); return

    ann["instagram_url"] = "https://www.instagram.com/reel/" + ann["code"].fillna("")
    random.seed(SEED)
    rows = []
    for (dim, cat), grp in ann.groupby(["dimension", "category"]):
        take = grp.sample(min(SAMPLE_N, len(grp)), random_state=SEED)
        for _, r in take.iterrows():
            rows.append({
                "dimension": dim, "category": cat,
                "confidence": round(r["confidence"], 3),
                "reel_pk": r["reel_pk"],
                "thumbnail": f"data/thumbnails/{r['reel_pk']}.jpg",
                "caption": (r["caption_text"] or "").replace("\n", " ")[:120],
                "url": r["instagram_url"],
                "verdict": ""
            })
    out = pd.DataFrame(rows)
    out.to_csv(CSV_PATH, index=False)
    print(f"Wrote {len(out)} reels in {CSV_PATH} "
          f"({out['category'].nunique()} categories).")
    print("\nNext steps:")
    print(f"  1. Open {CSV_PATH}.")
    print("  2. Open link, watch reel. enter 0/1 fpr 'verdict'.")
    print("  3. Save, then re-run this script with MODE='score'.")

def score(csv_path):
    """
    Read back the hand-checked CSV and report how accurate each category's tags were.
    """
    if not Path(csv_path).exists():
        print(f"{csv_path} not found. Run in MODE='sample' first."); return
    df = pd.read_csv(csv_path)
    df = df[df["verdict"].notna() & (df["verdict"].astype(str).str.strip() != "")]
    if df.empty:
        print("No 'verdict's entered."); return
    df["verdict"] = df["verdict"].astype(float)
    res = (df.groupby(["dimension", "category"])
             .agg(checked=("verdict", "count"), correct=("verdict", "sum"))
             .reset_index())
    res["precision"] = (res["correct"] / res["checked"]).round(2)
    res = res.sort_values("precision")
    print("=== Precision per category ===")
    print(res.to_string(index=False))
    print(f"\nTotal precision for all checked reels: "
          f"{df['verdict'].mean():.2f}  (n={len(df)})")
    weak = res[res["precision"] < 0.7]
    if not weak.empty:
        print("\nCategories below 0.70 precision:")
        print("  " + ", ".join(weak["category"].tolist()))

if __name__ == "__main__":
    MODE = "sample"

    if MODE == "sample":
        sample(DB_PATH)
    else:
        score(CSV_PATH)
