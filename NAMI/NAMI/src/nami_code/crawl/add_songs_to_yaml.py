"""
Search a song on Instagram via HikerAPI, show variants,
and add to songs.yaml
"""

from dotenv   import load_dotenv
from hikerapi import Client
import os, yaml

load_dotenv()
cl = Client(token=os.environ["HIKER_TOKEN"])
YAML_PATH = "config/songs.yaml"

def load_yaml():
    """
    Read the songs config file, returning an empty structure if it does not exist yet.
    """
    try:
        with open(YAML_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    except FileNotFoundError:
        data = {}

    data.setdefault("songs", {})
    return data


def save_yaml(data):
    """
    Write the songs config back to disk.
    """
    with open(YAML_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    print(f"\n✅ {YAML_PATH} saved.")


def search_and_add():
    """
    Search Instagram for a song, let the user pick which audio variants to keep, and add them to the songs config.
    """
    query = input("Enter search term (for example, artist and title): ").strip()
    results = cl.search_music_v1(query=query)
    hits = results if isinstance(results, list) else results.get("response", [])

    if not hits:
        print("No search results.")
        return

    print(f"\n{len(hits)} search results:\n")
    for i, h in enumerate(hits):
        dur = (h.get("duration_in_ms") or 0) / 1000
        print(f"  [{i}] {h.get('display_artist','?'):20s} | "
              f"{h.get('title','?')[:45]:45s} | {dur:5.0f}s | id={h.get('id')}")

    print("\nWhich results shall be processed? (Enter list of IDs, eg. 0,1,4, or empty to quit)")
    sel = input("> ").strip()
    if not sel:
        print("Aborted.")
        return

    idxs = [int(x) for x in sel.split(",") if x.strip().isdigit()]

    song_id = input("Internal song_id (no spaces, eg. 'plastic_love'): ").strip()
    title   = input("Title (for display): ").strip()
    artist  = input("Artist: ").strip()
    year    = input("Release year (optional): ").strip()

    variants = []
    for i in idxs:
        h = hits[i]
        suggested = h.get("title","var").lower()
        suggested = "".join(ch if ch.isalnum() else "_" for ch in suggested)[:30].strip("_")
        label = input(f"  Label for [{i}] '{h.get('title')}' "
                      f"(Enter = '{suggested}'): ").strip() or suggested
        variants.append({"asset_id": str(h["id"]), "label": label})

    data = load_yaml()
    if song_id in data["songs"]:
        print(f"\n ️  '{song_id}' is already in database. Variants will be added.")
        existing = {v["asset_id"] for v in data["songs"][song_id].get("variants", [])}
        for v in variants:
            if v["asset_id"] not in existing:
                data["songs"][song_id]["variants"].append(v)

    else:
        entry = {"title": title, "artist": artist}
        if year.isdigit():
            entry["release_year"] = int(year)
        entry["variants"] = variants
        data["songs"][song_id] = entry

    save_yaml(data)
    print(f"\nSong '{song_id}' with {len(variants)} variant(s) added to database.")
    print("Next step: run crawl_index.py to fetch new Instagram IDs.")

if __name__ == "__main__":
    search_and_add()
