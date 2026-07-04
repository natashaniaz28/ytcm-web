from nami_code.analysis.snapshot_churn import snapshot_current

if __name__ == "__main__":
    crawl_id = snapshot_current()
    print(f"Snapshot saved: {crawl_id}.")
