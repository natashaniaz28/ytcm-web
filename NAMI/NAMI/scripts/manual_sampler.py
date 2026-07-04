from pathlib import Path
from nami_code.analysis import analyse as A
from nami_code.analysis.manual_sampler import close_reading_sample, curated_close_reading_sample, write_sample_html

if __name__ == "__main__":
    schema = A.load_schema()
    df = A.classify(A.load_reels(), schema, sources=["keyword"])
    out = Path("outputs/package_b_report/tables")
    out.mkdir(parents=True, exist_ok=True)

    sample = close_reading_sample(df)
    sample.to_csv(out / "close_reading_sample.csv", index=False)
    print(write_sample_html(sample, "outputs/package_b_report/close_reading_sample.html"))

    curated = curated_close_reading_sample(df)
    curated.to_csv(out / "close_reading_curated.csv", index=False)
    print(write_sample_html(curated, "outputs/package_b_report/close_reading_curated.html"))
