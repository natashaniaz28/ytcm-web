"""
Detect and optionally mark spam/bot clusters in the reels table.

When executed directly it uses MARK=True and marks matching rows as is_spam=1.
Spam terms are loaded from config/domain.yaml when available. By default the spam
set also unions in reels the vision tagger flagged 'blocked' (content-policy
refusals — adult/prohibited content); their 'blocked' state is preserved so the
exclusion reason stays recoverable. Pass include_blocked=False to skip that.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from nami_code.domain_config import load_domain_config

DB_PATH = "data/corpus.db"
MARK = True
GENERIC_SPAM_TERMS_FALLBACK = ["crypto", "bitcoin", "nft", "forex", "casino"]


def load_spam_terms(
    domain_config: dict | None = None,
    domain_path: str = "config/domain.yaml",
) -> list[str]:
    """
    Load moderation spam terms from domain config.

    Missing config falls back to a short neutral moderation list. Project-specific
    moderation policy belongs in config/domain.yaml.
    """

    if domain_config is None:
        domain_config = load_domain_config(domain_path)
    moderation = domain_config.get("moderation", {}) if isinstance(domain_config, dict) else {}
    terms = moderation.get("spam_terms", []) if isinstance(moderation, dict) else []
    if not isinstance(terms, list) or not terms:
        terms = GENERIC_SPAM_TERMS_FALLBACK
    return [str(term).lower().strip() for term in terms if str(term).strip()]


def find_spam_reels(df: pd.DataFrame, spam_terms: list[str] | None = None) -> pd.DataFrame:
    """
    Return rows whose captions contain any configured spam term.
    """

    terms = spam_terms or load_spam_terms()
    out = df.copy()
    out["caption_text"] = out["caption_text"].fillna("").str.lower()
    mask = out["caption_text"].apply(lambda text: any(term in text for term in terms))
    return out[mask]


def mark_spam_reels(conn: sqlite3.Connection, reel_pks) -> None:
    """
    Set the spam flag on exactly the supplied reels, clearing it on all others.

    Each run is a full recompute, not an addition: every is_spam flag is first
    cleared, then set on the reels passed in. So a reel that was flagged on an
    earlier run but is not in this list gets unflagged — narrowing the spam-term
    list quietly de-flags reels. To make that visible, the count of reels whose
    flag changed (newly flagged and newly unflagged) is printed.
    """

    cols = [r[1] for r in conn.execute("PRAGMA table_info(reels)")]
    if "is_spam" not in cols:
        conn.execute("ALTER TABLE reels ADD COLUMN is_spam INTEGER DEFAULT 0")
    new_set = {str(pk) for pk in reel_pks}
    old_set = {str(r[0]) for r in conn.execute("SELECT reel_pk FROM reels WHERE is_spam=1")}
    conn.execute("UPDATE reels SET is_spam=0")
    conn.executemany("UPDATE reels SET is_spam=1 WHERE reel_pk=?", [(pk,) for pk in reel_pks])
    conn.commit()
    newly_flagged = len(new_set - old_set)
    newly_unflagged = len(old_set - new_set)
    print(f"is_spam changes: +{newly_flagged} newly flagged, "
          f"-{newly_unflagged} unflagged (now {len(new_set)} flagged in total).")


def blocked_reels(conn: sqlite3.Connection) -> set[str]:
    """Reel PKs the vision tagger marked terminally ``blocked`` (content-policy
    refusals). By the model's own safety classifier these are prohibited/adult
    content, so the spam check treats them as spam. Returns an empty set if the
    ``vision_state`` table is absent (a corpus that was never vision-tagged)."""
    try:
        return {str(r[0]) for r in conn.execute(
            "SELECT reel_pk FROM vision_state WHERE status='blocked'")}
    except Exception:
        return set()


def run_check_spam(
    db_path: str = DB_PATH,
    mark: bool = MARK,
    include_blocked: bool = True,
    domain_config: dict | None = None,
    domain_path: str = "config/domain.yaml",
) -> pd.DataFrame:
    """
    Run the spam check and optionally persist is_spam markers.

    With ``include_blocked`` (default), reels the vision tagger flagged ``blocked``
    are unioned into the spam set: they are content-policy refusals (adult/
    prohibited content) that can never be tagged and only dilute the corpus, so
    excluding them via ``is_spam`` is the right call. Their original reason is not
    lost — ``vision_state='blocked'`` persists and is listable with ``visionblocked``.
    """

    spam_terms = load_spam_terms(domain_config=domain_config, domain_path=domain_path)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql("SELECT reel_pk, song_id, creator_pseudo, caption_text FROM reels", conn)
        spam = find_spam_reels(df, spam_terms=spam_terms)

        term_pks = {str(p) for p in spam["reel_pk"]}
        blocked = blocked_reels(conn) if include_blocked else set()
        blocked_extra = blocked - term_pks
        marked = term_pks | blocked

        print(f"Suspicious reels (caption term): {len(spam)} of {len(df)} ({len(spam)/len(df)*100:.1f}%)")
        if include_blocked:
            print(f"Vision-blocked reels: {len(blocked)} "
                  f"(+{len(blocked_extra)} not already caught by a term)")
            print(f"Total to mark as spam: {len(marked)}")
        print(f"Distinct creators behind caption-term reels (pseudonymized): {spam['creator_pseudo'].nunique()}")
        print()
        if not spam.empty:
            print("=== Distribution across songs (caption-term reels) ===")
            print(spam.groupby("song_id").size().sort_values(ascending=False).to_string())
            print()
            print("=== Top creators (caption-term spam reels per account) ===")
            print(spam["creator_pseudo"].value_counts().head(10).to_string())
            print()

        if mark and marked:
            mark_spam_reels(conn, marked)
            src = "caption terms + vision blocks" if include_blocked and blocked else "caption terms"
            print(f"MARKED: {len(marked)} reels with is_spam=1 ({src}). "
                  f"analyse.py now excludes them automatically.")
            print("(To undo: manually run UPDATE reels SET is_spam=0.)")
        else:
            print("MARK=False or nothing to mark -> nothing changed.")
        return spam
    finally:
        conn.close()


if __name__ == "__main__":
    run_check_spam()
