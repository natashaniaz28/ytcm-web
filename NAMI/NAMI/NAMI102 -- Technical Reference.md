# NAMI -- Technical Reference

## 1. Data structures and data files

NAMI uses three places to store data:

+ a SQLite database,
+ a set of YAML config files,
+ and an `outputs/` tree of generated results.

Nothing is written outside the repository root.

### 1.1 SQLite corpus (`data/corpus.db`)

The database is managed by `src/nami_code/db.py` and `src/nami_code/analysis/snapshot_churn.py`. The schema is the same for every project, only the rows differ.

**`songs`** -- one row per logical song.

| Column         | Type    | Notes                            |
|----------------|---------|----------------------------------|
| `song_id`      | TEXT PK | Stable slug from `songs.yaml`.   |
| `title`        | TEXT    | Display title.                   |
| `artist`       | TEXT    | Display artist.                  |
| `release_year` | INTEGER | Optional.                        |

**`track_variants`** -- one row per Instagram audio asset: On Instagram, a song may be uploaded multiple times by different rights holders, mash-ups, lo-fi versions, etc.).

| Column          | Type    | Notes                                      |
|-----------------|---------|--------------------------------------------|
| `asset_id`      | TEXT PK | Instagram audio asset ID.                  |
| `song_id`       | TEXT FK | Maps the variant back to its logical song. |
| `variant_label` | TEXT    | Free-form variant name from `songs.yaml`.  |

**`reel_index`** -- Every Reel ID that the API ever returned for any asset, before metadata enrichment.

| Column         | Type    | Notes                                                    |
|----------------|---------|----------------------------------------------------------|
| `reel_pk`      | TEXT    | Instagram reel primary key. Composite PK with asset_id.  |
| `asset_id`     | TEXT FK |                                                          |
| `play_count`   | INTEGER | Snapshot at index time, may be `NULL`.                   |
| `details_done` | INTEGER | `0` = pending Stage B, `1` = enriched.                   |
| `seen_at`      | TEXT    | First time this row was inserted.                        |

**`reels`** -- Stage B output: full metadata for data-enriched reels. One row per `reel_pk`.

| Column           | Type    | Notes                                                                     |
|------------------|---------|---------------------------------------------------------------------------|
| `reel_pk`        | TEXT PK |                                                                           |
| `song_id`        | TEXT FK |                                                                           |
| `asset_id`       | TEXT    |                                                                           |
| `variant_label`  | TEXT    |                                                                           |
| `code`           | TEXT    | URL-safe shortcode -> `https://www.instagram.com/reel/{code}/`.           |
| `creator_pseudo` | TEXT    | 24-character HMAC-SHA256 of the original user ID, keyed by `PSEUDO_SALT`. |
| `taken_at`       | TEXT    | ISO-8601 UTC.                                                             |
| `caption_text`   | TEXT    | Raw caption.                                                              |
| `like_count`     | INTEGER |                                                                           |
| `play_count`     | INTEGER |                                                                           |
| `view_count`     | INTEGER |                                                                           |
| `comment_count`  | INTEGER |                                                                           |
| `video_duration` | REAL    | Seconds.                                                                  |
| `thumbnail_url`  | TEXT    | CDN URL at download time. Usually expires within hours.                   |
| `video_url`      | TEXT    | CDN MP4 URL at download time. Expires within hours; used by `fetchmedia`. |
| `media_path`     | TEXT    | Local path of the downloaded reel video, or `NULL`.                       |
| `ingested_at`    | TEXT    | When the row was written.                                                 |
| `is_spam`        | INTEGER | Added by `checkspam`. `0` or `1`. Excluded from analyses by default.      |

**`reel_hashtags`** -- Link table for every hashtag found in any caption.

| Column    | Type | Notes                                                         |
|-----------|------|---------------------------------------------------------------|
| `reel_pk` | TEXT | Composite PK with `hashtag`.                                  |
| `hashtag` | TEXT | Lowercased, no leading `#`. Extracted from caption text only. |

**`annotations`** -- Classification output, multi-row per reel (one row per `(reel_pk, dimension, category, source)`).

| Column       | Type    | Notes                                                                                |
|--------------|---------|--------------------------------------------------------------------------------------|
| `reel_pk`    | TEXT    | Composite PK with `dimension`, `category`, `source`.                                 |
| `dimension`  | TEXT    | A key from `schema.yaml` --> `dimensions` (e.g. `context`, `format`).                |
| `category`   | TEXT    | A key from `schema.yaml` --> `dimensions.<dim>.categories`.                          |
| `source`     | TEXT    | `keyword`, `vision`, `manual`, ...                                                   |
| `confidence` | REAL    | `1.0` for keyword matches; the model's confidence (0–1) for vision; `1.0` for manual. |
| `model`      | TEXT    | Model identifier (e.g. `gemini-2.5-flash`, `qwen3-vl-8b`, `stub`, `null` for manual). |
| `created_at` | TEXT    | Default `datetime('now')`.                                                           |

**`vision_state`** -- Resume marker for the vision tagger. One row per reel.

| Column       | Type    | Notes                                              |
|--------------|---------|----------------------------------------------------|
| `reel_pk`    | TEXT PK |                                                    |
| `status`     | TEXT    | `pending`, `done`, `no_media`, or `failed`.        |
| `media_path` | TEXT    | Local path of the reel video that was classified.  |
| `updated_at` | TEXT    |                                                    |

**`media_state`** -- Resume marker for the reel-video download. One row per reel.

| Column       | Type    | Notes                                          |
|--------------|---------|------------------------------------------------|
| `reel_pk`    | TEXT PK |                                                |
| `status`     | TEXT    | `pending`, `done`, `failed`, or `no_video` (terminal: API returned no `video_url`, so `fetchmedia` skips it). |
| `media_path` | TEXT    | Local path of the downloaded MP4 when `done`.  |
| `updated_at` | TEXT    |                                                |

**`index_state`** -- Resume marker for the indexer. One row per asset.

| Column         | Type    | Notes                                                      |
|----------------|---------|------------------------------------------------------------|
| `asset_id`     | TEXT PK |                                                            |
| `next_page_id` | TEXT    | HikerAPI continuation token. Empty when fully crawled.     |
| `pages_done`   | INTEGER |                                                            |
| `ids_seen`     | INTEGER | Cumulative count, may include duplicates the API returned. |
| `status`       | TEXT    | `pending`, `running`, `done`, `failed`.                    |
| `updated_at`   | TEXT    |                                                            |

**`crawl_runs`** -- One row per refresh crawl or manual snapshot.

| Column        | Type    | Notes                                              |
|---------------|---------|----------------------------------------------------|
| `crawl_id`    | TEXT PK | Timestamp + random hex.                            |
| `started_at`  | TEXT    | UTC ISO.                                           |
| `finished_at` | TEXT    |                                                    |
| `mode`        | TEXT    | `refresh` (real visibility refresh) or `snapshot`. |
| `status`      | TEXT    | `running`, `done`, `failed`.                       |
| `notes`       | TEXT    |                                                    |
| `note`        | TEXT    | Legacy duplicate column.                           |

**`reel_seen`** -- Per-crawl visibility log: which reels appeared in which run, in which rank position, at what observed metrics.

| Column          | Type    | Notes                                                  |
|-----------------|---------|--------------------------------------------------------|
| `crawl_id`      | TEXT    | Composite PK with `reel_pk` and `asset_id`.            |
| `reel_pk`       | TEXT    |                                                        |
| `asset_id`      | TEXT    |                                                        |
| `song_id`       | TEXT    |                                                        |
| `seen_at`       | TEXT    | UTC ISO of observation.                                |
| `page_no`       | INTEGER | Which API page this row came from (refresh runs only). |
| `page_pos`      | INTEGER | Position within that page.                             |
| `rank_pos`      | INTEGER | Cumulative rank across pages.                          |
| `play_count`    | INTEGER | Observed play count at this run.                       |
| `like_count`    | INTEGER |                                                        |
| `comment_count` | INTEGER |                                                        |

Churn analysis (retained / new / lost reels per asset between consecutive crawls) is computed by `snapshot_churn.churn_summary()` from this table; it ignores rows whose run had `mode='snapshot'` because manual corpus snapshots are not a real visibility refresh.

### 1.2 Configuration files (`config/`)

Four YAML files, all loaded read-only at runtime. Editing them changes behavior, but does not require a code change.

| File                  | Purpose                                                                                                                                                                                                   |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `config/project.yaml` | Project ID, display name, platform, media type, and the paths to the other config files and to the database.                                                                                              |
| `config/songs.yaml`   | The list of songs and their audio-asset variants. This is the input to crawling.                                                                                                                          |
| `config/schema.yaml`  | Classification dimensions and categories. Each category has keyword lists (multilingual) and optional `vision_prompt` / `vision_description` text for the vision model. A top-level `vision:` block sets the default model, media resolution, frames-per-second, the per-dimension category cap, and the model instruction template. Bump `version:` when categories change. |
| `config/domain.yaml`  | Project-specific vocabularies: shared term groups, audio-filter scoring, hashtag semantic rules and stoplists, sampling slots, robustness audit terms, moderation spam terms, and report labels/sections. |

`schema.yaml` defines what categories exist, `domain.yaml` defines what counts as a particular kind of discourse, plus all per-project lexical choices that should not be hard-coded.

### 1.3 Downloaded source data (`data/reels/`, `data/thumbnails/`)

Reel videos and cover thumbnails are downloaded primary source data, not generated
artifacts: their CDN links expire within hours and cannot be regenerated from the
repo, so they live under `data/` alongside the corpus DB (`data/corpus.db`),
deliberately **not** under `outputs/`. `build_zip.sh` excludes both (they are large
and reproducible only by re-crawling) while still bundling `data/corpus.db`.

| Path                             | Written by                    | Content                                                                                                  |
|----------------------------------|-------------------------------|----------------------------------------------------------------------------------------------------------|
| `data/thumbnails/<reel_pk>.jpg`  | `crawldetails`, `fetchthumbs` | JPEG cover thumbnails downloaded from the CDN. Thumbnail fallback for vision and the validation gallery. |
| `data/reels/<reel_pk>.mp4`       | `crawldetails`, `fetchmedia`  | Reel videos (with audio) downloaded from the CDN. The input the vision tagger classifies.                |

### 1.4 The `outputs/` folder

Everything generated will be saved under `outputs/`.

| Path                                            | Written by                    | Content                                                                                                                                            |
|-------------------------------------------------|-------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| `outputs/report_out/report.html`                | `report`                      | The main combined HTML report with embedded charts.                                                                                                |
| `outputs/report_out/charts/`                    | `report`                      | PNG charts.                                                                                                                                        |
| `outputs/report_out/tables/`                    | `report`, `robustness`        | CSV exports of every analysis the report computes.                                                                                                 |
| `outputs/report_out/close_reading_sample.html`  | `report`, `sample`            | HTML for the random close-reading sample.                                                                                                          |
| `outputs/report_out/close_reading_curated.html` | `report`                      | HTML for the curated, slot-driven close-reading sample.                                                                                            |
| `outputs/analysis/`                             | scope / talk commands         | CSVs from `timeline`, `dist`, `topreels`, `correlate`, `weekdays`, `impact`, `captionterms`, `hashtagterms`, `distinctiveterms`, `captionmarkers`. |
| `outputs/graphs/`                               | graph commands                | Three files per graph type: `<type>_edges.csv`, `<type>_nodes.csv`, `<type>.gexf` (GEXF only if `networkx` is installed).                          |
| `outputs/visuals/`                              | viz commands                  | PNG plots derived from CSVs in `outputs/analysis/` and `outputs/graphs/`.                                                                          |
| `outputs/explorer/views.json`                   | `saveview`, `dropview`        | Named persistent ID lists, restorable with `useview`.                                                                                              |
| `outputs/explorer/manual_annotations.json`      | `annotationsave`              | Manual tags, notes, and review flags (keep, manual spam, exclude, reviewed).                                                                       |
| `outputs/explorer/<file>.{json,csv,md}`         | `exportview`, `filtersave`    | User-named exports of the active Explorer set.                                                                                                     |
| `logs/nami_<timestamp>.log`                     | shell startup                 | Per-session log; the shell prints `ERROR` to the console and the full level to the file.                                                           |
| `validation_visual.html`                        | `validatevisual`              | A flat HTML gallery for manual inspection of vision tags. Written to `outputs/report_out/` (media referenced relative to that folder).             |

### 1.5 Environment

NAMI reads non-public information from `.env` (loaded via `python-dotenv`):

| Variable       | Required for                  | Notes                                                                                                                                                      |
|----------------|-------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `HIKER_TOKEN`  | All crawl commands            | HikerAPI access token.                                                                                                                                     |
| `PSEUDO_SALT`  | `crawldetails`, `fetchthumbs` | Random bytes for HMAC-SHA256 pseudonymization of creator user IDs. Generate with `scripts/create_salt.sh`. Lose this and pseudonyms become irreproducible. |
| `GEMINI_API_KEY` | `tagvision --model gemini*` | Google API key for the Gemini vision model. Only needed for the cloud vision backend; the self-hosted Qwen backends need no key.                          |

### 1.6 The Python package

The runtime code lives in `src/nami_code/` and is installed in editable mode via `pyproject.toml`. The package has no required side-effects on import. Large imports (`torch`, `transformers`, `hikerapi`, `scipy`, `networkx`) are deferred to the functions that need them.

---

## 2. Code file guide

### 2.1 Entry points and top-level scripts

These files are the user-facing launchers. Most of them are intentionally thin wrappers around modules inside `src/nami_code/`.

#### `scripts/NAMI.py`

**Purpose.** Main interactive shell entry point. Running `python scripts/NAMI.py` starts the NAMI command prompt.

**Functions and classes.** `_bootstrap_paths()` makes the repository root and `src/` importable, then changes the working directory to the repository root. `NAMIShell` combines all command mixins from `scripts/nami_shell/` with Python's `cmd.Cmd`. Its `cmdloop()` prints the intro and status; `precmd()` maps `quit` and `q` to `exit`; `default()` handles unknown commands. `parse_arguments()` reads `--db` and `--command`; `main()` either starts the interactive shell or runs one command non-interactively.

**How it works with other files.** It imports `NAMI_shell_commands.py`, which re-exports all shell mixins. Each `do_*` method in those mixins becomes one shell command.

#### `scripts/NAMI_shell_commands.py`

**Purpose.** Aggregation module for the shell command mixins.

**Functions and classes.** It defines no runtime logic of its own. It imports common helpers, the Explorer state class, and every command mixin, then exposes them through `__all__`.

**How it works with other files.** `scripts/NAMI.py` imports from here to keep the main shell file small and stable.

#### `scripts/add_songs.py`

**Purpose.** Backward-compatible script launcher for adding Instagram audio assets to `config/songs.yaml`.

**Functions and classes.** It has no local functions. It calls `runpy.run_module("nami_code.crawl.add_songs_to_yaml", run_name="__main__")`.

**How it works with other files.** Delegates all real work to `src/nami_code/crawl/add_songs_to_yaml.py`.

#### `scripts/analyse.py`

**Purpose.** Backward-compatible script launcher for the console analysis module.

**Functions and classes.** It has no local functions. It runs `nami_code.analysis.analyse` as `__main__`.

**How it works with other files.** Delegates to `src/nami_code/analysis/analyse.py`.

#### `scripts/check_spam.py`

**Purpose.** Backward-compatible script launcher for spam detection.

**Functions and classes.** It has no local functions. It runs `nami_code.analysis.check_spam` as `__main__`.

**How it works with other files.** Delegates to `src/nami_code/analysis/check_spam.py`.

#### `scripts/crawl_details.py`

**Purpose.** Backward-compatible launcher for Stage B crawling.

**Functions and classes.** It has no local functions. It runs `nami_code.crawl.crawl_details` as `__main__`.

**How it works with other files.** Delegates to `src/nami_code/crawl/crawl_details.py`.

#### `scripts/crawl_index.py`

**Purpose.** Backward-compatible launcher for Stage A crawling.

**Functions and classes.** It has no local functions. It runs `nami_code.crawl.crawl_index` as `__main__`.

**How it works with other files.** Delegates to `src/nami_code/crawl/crawl_index.py`.

#### `scripts/fetch_thumbnails.py`

**Purpose.** Backward-compatible launcher for thumbnail recovery.

**Functions and classes.** It has no local functions. It runs `nami_code.crawl.fetch_thumbnails` as `__main__`.

**How it works with other files.** Delegates to `src/nami_code/crawl/fetch_thumbnails.py`.

#### `scripts/fetch_media.py`

**Purpose.** Backward-compatible launcher for reel-video recovery.

**Functions and classes.** It has no local functions. It runs `nami_code.crawl.fetch_media` as `__main__`.

**How it works with other files.** Delegates to `src/nami_code/crawl/fetch_media.py`.

#### `scripts/manual_sampler.py`

**Purpose.** Standalone close-reading sample generator.

**Functions and classes.** It has no local functions. In its `__main__` block it loads the schema, loads and keyword-classifies reels, writes a random sample CSV/HTML, then writes a curated sample CSV/HTML.

**How it works with other files.** Uses `src/nami_code/analysis/analyse.py` for loading and classification and `src/nami_code/analysis/manual_sampler.py` for sampling and HTML rendering.

#### `scripts/run_report.py`

**Purpose.** Backward-compatible launcher for the HTML report builder.

**Functions and classes.** It has no local functions. It runs `nami_code.reports.report` as `__main__`.

**How it works with other files.** Delegates to `src/nami_code/reports/report.py`.

#### `scripts/snapshot_current.py`

**Purpose.** Tiny script for writing a corpus snapshot from the current `reels` table.

**Functions and classes.** It imports `snapshot_current()` and calls it in the `__main__` block, then prints the created crawl/snapshot ID.

**How it works with other files.** Delegates to `src/nami_code/analysis/snapshot_churn.py`.

#### `scripts/tag_vision.py`

**Purpose.** Backward-compatible launcher for the vision tagger.

**Functions and classes.** It has no local functions. It runs `nami_code.vision.tag_vision` as `__main__`.

**How it works with other files.** Delegates to `src/nami_code/vision/tag_vision.py`.

#### `scripts/create_salt.sh`

**Purpose.** Generates a random `PSEUDO_SALT` line and appends it to `.env`.

**Functions and classes.** Shell one-liner: calls Python's `secrets.token_hex(32)` and writes `PSEUDO_SALT=<hex>`.

**How it works with other files.** `src/nami_code/crawl/crawl_details.py` reads `PSEUDO_SALT` to HMAC-pseudonymize creator IDs.

### 2.2 Interactive shell modules: `scripts/nami_shell/`

The shell is split into mixins. `NAMIShell` inherits from all of them. Each method named `do_<command>` becomes an interactive shell command.

#### `scripts/nami_shell/__init__.py`

**Purpose.** Package marker for the shell command modules.

**Functions and classes.** No local functions or classes.

**How it works with other files.** Allows imports such as `from nami_shell.common import *`.

#### `scripts/nami_shell/common.py`

**Purpose.** Shared shell utilities for argument parsing, filtering, comparison, CSV/JSON export, and database-table checks.

**Functions and classes.** `_field_name()`, `_field_values()`, `_stringify()`, `_needle_match()`, and `_record_search_matches()` normalize records and implement text matching. `_coerce_for_compare()` and `_compare_values()` power structured filters such as `where likes > 1000`. `_extract_hit_snippets()` builds visible snippets for `hits`. `_value_counts()` supports `top` and `compare`. `_flatten_for_csv()` and `_write_records()` serialize Explorer records. `_bool_from_flag()` and `_parse_kv_args()` parse shell-style options. `_table_exists()` checks SQLite tables.

**How it works with other files.** Imported by almost every shell command file. It is the shared glue that keeps command parsing and record handling consistent.

#### `scripts/nami_shell/state.py`

**Purpose.** Holds the mutable Explorer state.

**Functions and classes.** `NAMIExplorerState` stores `data`, the current `filtered` list, source metadata, and last filter/query metadata. `active()` returns the filtered list when present or the full data otherwise. `reset_filter()` clears filters. `total_count` and `active_count` expose counts.

**How it works with other files.** Used by `NAMIExplorerCommands`; attached to the running shell instance.

#### `scripts/nami_shell/core_commands.py`

**Purpose.** Basic shell commands: help-like info, status, paths, opening outputs, OS shell calls, and exit.

**Functions and classes.** `NAMICoreCommands` defines `do_info()`, `do_howto()`, `do_status()`, `do_paths()`, `do_open()`, `do_shell()`, and `do_exit()`. `do_status()` inspects repository paths and database tables. `do_open()` maps shortcuts such as `report` and `sample` to local HTML outputs.

**How it works with other files.** Uses constants and helpers from `common.py`; complements every other command family by showing the current project state.

#### `scripts/nami_shell/setup_commands.py`

**Purpose.** Setup-related shell commands.

**Functions and classes.** `NAMISetupCommands` defines `do_setupdb()`, `do_annotations()`, and `do_addsongs()`. `do_setupdb()` creates or updates the SQLite schema and syncs `songs.yaml`. `do_annotations()` creates the vision tagging tables (`annotations`, `vision_state`, `media_state`). `do_addsongs()` opens the interactive Instagram music search workflow.

**How it works with other files.** Calls `src/nami_code/db.py`, `src/nami_code/vision/db_annotations.py`, and `src/nami_code/crawl/add_songs_to_yaml.py`.

#### `scripts/nami_shell/crawl_commands.py`

**Purpose.** Crawl orchestration commands.

**Functions and classes.** `NAMICrawlCommands` defines `do_crawlindex()`, `do_crawldetails()`, `do_fetchthumbs()`, `do_fetchmedia()`, and `do_crawl()`. `do_crawlindex()` passes arguments to the Stage A crawler. `do_crawldetails()` runs Stage B metadata enrichment (including the inline thumbnail and video download). `do_fetchthumbs()` recovers thumbnails and `do_fetchmedia()` recovers reel videos. `do_crawl()` chains setup, Stage A, Stage B, optional snapshot, and report creation.

**How it works with other files.** Calls modules in `src/nami_code/crawl/`, database helpers in `src/nami_code/db.py`, and report/snapshot commands through other mixins.

#### `scripts/nami_shell/analysis_commands.py`

**Purpose.** Analysis and report commands in the shell.

**Functions and classes.** `NAMIAnalysisCommands` defines `do_analyse()`, `do_checkspam()`, `do_spamreport()`, `do_snapshot()`, `do_sample()`, `do_robustness()`, `do_concordance()`, and `do_report()`. These run the console analysis, spam check, spam HTML report, snapshot writer, close-reading sampler, robustness diagnostics, keyword-vs-vision concordance check, and full report builder. `do_spamreport()` calls `spam_report.build()` (read-only) and opens the resulting HTML unless `--silent`. `do_concordance()` loads reels + schema, runs `concordance.run_concordance()`, prints a per-dimension summary, and writes the concordance CSVs (read-only — never writes the DB).

**How it works with other files.** Connects shell commands to `src/nami_code/analysis/` and `src/nami_code/reports/report.py`.

#### `scripts/nami_shell/explorer_commands.py`

**Purpose.** Interactive Explorer: loading records, filtering, inspecting, saving views, manual annotation, and exporting subsets.

**Functions and classes.** `NAMIExplorerCommands` contains both private helpers and public commands. `_load_reels_from_db()` builds Explorer records from SQLite, including hashtags and vision annotations. `_load_records_from_file()` reads JSON/CSV exports. `_require_loaded()`, `_resolve_record_target()`, and `_print_record_brief()` support user-facing commands. `_load_views()`, `_save_views()`, `_restore_records_by_ids()`, and `_validate_view_name()` manage persistent views. `_load_manual_annotations()`, `_save_manual_annotations()`, `_ensure_manual_entry()`, `_set_manual_flag()`, and related helpers manage manual tags, notes, and review flags. Public commands include `do_load()`, `do_filter()`, `do_fieldfilter()`, `do_where()`, `do_unfilter()`, `do_xsample()`, `do_inspect()`, `do_top()`, `do_compare()`, `do_hits()`, `do_saveview()`, `do_useview()`, `do_views()`, `do_dropview()`, `do_review()`, `do_keep()`, `do_markspam()`, `do_exclude()`, `do_tag()`, `do_note()`, `do_annotationsave()`, and `do_exportview()`.

**How it works with other files.** Uses `NAMIExplorerState` for state and `common.py` for matching/export. It sits on top of the database and produces JSON/CSV/Markdown outputs for qualitative work.

#### `scripts/nami_shell/vision_commands.py`

**Purpose.** Shell commands for vision tagging and validation.

**Functions and classes.** `NAMIVisionCommands` defines `do_tagvision()`, `do_visionstatus()`, `do_visionblocked()`, `do_validatevisual()`, `do_validatetags()`, and `do_visionreport()`. `do_tagvision()` upgrades the tagging tables if necessary and runs the tagger, forwarding `--model` (default `gemini-2.5-flash`), `--stub`, `--limit`, `--reset`, `--resolution`, `--fps`, and `--workers` (parallel reels in flight; default 8 for Gemini, 1 for local GPU models and stub). `do_visionstatus()` is a read-only progress summary: it counts reels by `vision_state.status` (`done`/`pending`/`no_media`/`blocked`/`failed`), derives how many have no record yet (`reels` minus `vision_state` rows), shows tagged-vs-open percentages, and lists the model(s) in the `source='vision'` annotations. `do_visionblocked()` lists the reels in the terminal `blocked` state (content-policy refusals that are never retried), joining `vision_state` to `reels` for shortcode/URL, song & variant, creator and caption plus any keyword-source tags, with `--limit` to truncate the console list and `--csv PATH` to export the full set. The others build the HTML validation gallery, create/score the validation CSV, and trigger the report builder.

**How it works with other files.** Calls `src/nami_code/vision/tag_vision.py`, `src/nami_code/vision/validate_visual.py`, `src/nami_code/diagnostics/validate_tags.py`, and `src/nami_code/reports/report.py`.

#### `scripts/nami_shell/raw_module_commands.py`

**Purpose.** Escape hatch for running arbitrary modules or scripts from inside the NAMI shell.

**Functions and classes.** `NAMIRawModuleCommands` defines `do_runmodule()` and `do_runscript()`. They validate that an argument was provided, then call `runpy.run_module()` or `runpy.run_path()`.

**How it works with other files.** Useful when a module exists but has no dedicated shell command.

#### `scripts/nami_shell/graph_commands.py`

**Purpose.** Shell commands for exporting graph data.

**Functions and classes.** `_GraphArgumentParser` raises Python exceptions instead of exiting the shell. `_parse_args()`, `_common_graph_options()`, `_paths()`, `_write_graph()`, and `_print_export_summary()` share parsing and output logic. `NAMIGraphCommands` defines `do_graphstatus()`, `do_taggraph()`, `do_creatorgraph()`, `do_songtaggraph()`, and `do_exportgraph()`.

**How it works with other files.** Calls `src/nami_code/analysis/namigraph.py` to build nodes/edges and write CSV/GEXF outputs.

#### `scripts/nami_shell/scope_commands.py`

**Purpose.** Shell commands for time series, distributions, top reels, correlations, weekdays, and impact summaries.

**Functions and classes.** `_ScopeArgumentParser`, `_parse_args()`, `_default_out()`, `_load()`, and `_write()` provide shared command plumbing. `NAMIScopeCommands` defines `do_timeline()`, `do_dist()`, `do_topreels()`, `do_correlate()`, `do_weekdays()`, and `do_impact()`.

**How it works with other files.** Calls `src/nami_code/analysis/namiscope.py`, writes CSVs under `outputs/analysis/`, and feeds the visualization commands.

#### `scripts/nami_shell/talk_commands.py`

**Purpose.** Shell commands for caption and hashtag term analysis.

**Functions and classes.** `_TalkArgumentParser`, `_parse_args()`, `_default_out()`, `_load()`, and `_write()` provide common command plumbing. `NAMITalkCommands` defines `do_captionterms()`, `do_hashtagterms()`, `do_distinctiveterms()`, and `do_captionmarkers()`.

**How it works with other files.** Calls `src/nami_code/analysis/namitalk.py` and writes CSVs under `outputs/analysis/`.

#### `scripts/nami_shell/viz_commands.py`

**Purpose.** Shell commands for plotting CSV outputs.

**Functions and classes.** `_VizArgumentParser`, `_parse_args()`, `_default_in()`, `_default_out()`, and `_require_viz()` provide common parsing and matplotlib availability checks. `_write_visual_report()` bundles rendered PNGs into one grouped HTML page (co-located with the PNGs, so `<img>` srcs are bare file names). `NAMIVizCommands` defines `do_vizstatus()`, `do_viztimeline()`, `do_vizdist()`, `do_viztopreels()`, `do_vizimpact()`, `do_vizterms()`, `do_vizgraph()`, and `do_vizall()`. The individual `viz*` commands are CSV-first (read a CSV, write a PNG). `do_vizall()` is the full-coverage one-shot: unless `--no-recompute`, it first re-runs every producer command on `self` (`do_timeline` for all four entities, `do_dist`/`do_topreels` for every numeric field, `do_impact` for every dimension, `do_captionterms`/`do_hashtagterms`/`do_distinctiveterms`, and `do_exportgraph` for all four graphs) so inputs are fresh; it then renders all 30 PNGs into `outputs/visuals/` and calls `_write_visual_report()` to emit `outputs/report_out/visual_report.html` (`DEFAULT_REPORT_OUT`, alongside `report.html`/`spam_report.html` so the HTML deliverables aren't scattered), grouped Timelines/Distributions/Top reels/Impact/Terms/Networks, opening it unless `--silent`. `_write_visual_report()` base64-embeds each PNG by default (`_png_data_uri()`) so the single file is self-contained and shareable; `--link-images` instead references the PNGs by a path computed relative to the report's folder (`os.path.relpath`), so the link resolves even though report and PNGs live in different folders. Each producer or plot failure is caught and surfaced as "(chart unavailable)" rather than aborting.

**How it works with other files.** Reads CSVs from `outputs/analysis/` or `outputs/graphs/` and calls `src/nami_code/analysis/namiviz.py` to write PNGs.

### 2.3 Database and configuration core

#### `src/nami_code/db.py`

**Purpose.** Defines and initializes the core SQLite schema.

**Functions and classes.** `get_conn()` opens `DB_PATH`, executes the DDL, commits, and returns a ready connection. `sync_songs_from_yaml()` inserts or replaces songs and track variants from `songs.yaml`. `migrate_old_reels()` is currently a placeholder.

**How it works with other files.** `setupdb`, crawling, and analysis all rely on this schema. Crawlers write into the tables defined here; reports read from them.

#### `src/nami_code/domain_config.py`

**Purpose.** Shared loader and validator for project, schema, domain, and song YAML configs.

**Functions and classes.** `load_yaml()` reads a YAML mapping with defaults and clear errors. `_merge_project_defaults()` ensures legacy path defaults exist. `load_project_config()`, `load_domain_config()`, `load_schema_config()`, and `load_songs_config()` load individual config files. `get_project_path()` resolves a path key. `load_nami_config()` returns a combined config bundle. `validate_schema_config()` and `validate_domain_config()` return warning strings instead of raising.

**How it works with other files.** Report generation, sampling, audio filtering, spam detection, hashtag analysis, and the config coach all use this module to avoid hard-coded project vocabularies.

### 2.4 Crawling modules: `src/nami_code/crawl/`

#### `src/nami_code/crawl/add_songs_to_yaml.py`

**Purpose.** Interactive Instagram music search and `songs.yaml` updater.

**Functions and classes.** `load_yaml()` reads the song config. `save_yaml()` writes it back while preserving Unicode. `search_and_add()` asks for a search query, calls HikerAPI, shows candidate audio assets, asks which to add, collects title/artist/year and variant labels, then appends or creates a song entry.

**How it works with other files.** Called by the shell `addsongs` command and `scripts/add_songs.py`. The resulting `songs.yaml` is synced into SQLite by `setupdb`.

#### `src/nami_code/crawl/crawl_index.py`

**Purpose.** Stage A crawler: collect Reel IDs for configured Instagram audio assets.

**Functions and classes.** `VariantResult` stores per-asset crawl counts. `log()` prints timestamped status. `get_client()` lazily creates the HikerAPI client. `load_config()` reads songs and track variants from SQLite. `call_track_stream()` wraps HikerAPI calls with retries and endpoint compatibility logic. `get_response()`, `get_next_page_id()`, and `iter_media_from_stream()` normalize API responses. `insert_reel_index_row()` writes new IDs. `ensure_index_state_row()` initializes resume state. `index_variant_full()` handles initial/resume backfills. `index_variant_refresh()` starts from page 1, records visibility rows, and inserts only unknown Reel IDs. `print_summary()`, `parse_args()`, and `main()` provide CLI behavior.

**How it works with other files.** Reads `track_variants` from `db.py`; writes `reel_index` and `index_state`; calls `snapshot_churn` functions during refresh runs; feeds `crawl_details.py` with pending Reel IDs.

#### `src/nami_code/crawl/crawl_details.py`

**Purpose.** Stage B crawler: enrich pending Reel IDs with metadata, captions, metrics, hashtags, thumbnails, reel videos, and pseudonymized creator IDs.

**Functions and classes.** `save_thumbnail()` downloads a thumbnail while its CDN URL is fresh. `save_video()` downloads the reel MP4 to `data/reels/<reel_pk>.mp4` while its CDN URL is fresh, returning the local path. `get_client()` lazily creates HikerAPI client. `get_salt()` reads `PSEUDO_SALT`. `pseudo()` HMAC-hashes creator IDs. `to_iso()` normalizes timestamps. `fetch_detail()` retries `media_by_id_v1()`. `run()` selects `details_done=0` rows, fetches metadata, downloads the thumbnail and video, inserts or replaces `reels` (now including `video_url` and `media_path`), extracts hashtags into `reel_hashtags`, records the video download in `media_state`, sets `details_done=1`, and commits after every reel.

**How it works with other files.** Consumes `reel_index` from Stage A, writes the main `reels` table used by all analysis and report modules, and the videos the vision tagger reads.

#### `src/nami_code/crawl/fetch_thumbnails.py`

**Purpose.** Recover missing thumbnails after metadata has already been downloaded.

**Functions and classes.** `_download()` downloads one URL to a destination file. `_hiker_fresh_url()` calls HikerAPI in a daemon thread to obtain a fresh CDN thumbnail URL with a timeout. `run()` scans all reels, skips existing thumbnails, tries stored URLs first, optionally refreshes expired URLs, and prints progress.

**How it works with other files.** Provides the thumbnail fallback for vision and the validation gallery. Called by shell `fetchthumbs` and wrapper `scripts/fetch_thumbnails.py`.

#### `src/nami_code/crawl/fetch_media.py`

**Purpose.** Recover missing reel videos after metadata has already been downloaded. The main capture happens inline in `crawl_details.py`; this is the best-effort safety net.

**Functions and classes.** `_download()` saves one URL to a destination file. `_get_client()` lazily creates the HikerAPI client (kept separate so it is easy to substitute). `_hiker_fresh_url()` fetches a fresh CDN video URL in a daemon thread with a timeout. `_set_state()` records a reel's download status in `media_state`. `run()` scans all reels except those marked terminal `media_state='no_video'` (the API never returned a `video_url`, so there is nothing to retry), skips those with a local MP4, tries the stored `video_url` first and a fresh URL as backup, writes `data/reels/<reel_pk>.mp4`, and updates `media_state`.

**How it works with other files.** Writes the videos the vision tagger reads. Called by shell `fetchmedia` and wrapper `scripts/fetch_media.py`.

### 2.5 Analysis modules: `src/nami_code/analysis/`

#### `src/nami_code/analysis/analyse.py`

**Purpose.** Core loading and classification logic, plus console diagnostics.

**Functions and classes.** `schema_dimensions()` returns configured dimensions. `load_reels()` loads reels, songs, variants, hashtags, and spam filtering from SQLite. `load_schema()` reads `schema.yaml`. `_theme_text()`, `_classify_row()`, and `_infer()` implement keyword matching. `_load_annotations()` loads DB annotations such as vision tags. `classify()` combines keyword and optional annotation sources. `explode_dimension()`, `dimension_distribution()`, `unknown_share()`, `combination_summary()`, `trend_series()`, `detect_peaks()`, `top_examples()`, `top_hashtags()`, `summary()`, `classifiable_rate()`, `distribution_classifiable()`, `song_profile()`, `song_distinctiveness()`, and `hashtag_cooccurrence()` compute reusable statistics.

**How it works with other files.** It is the analytical base used by the report builder, manual sampler, robustness checks, and standalone `analyse` command.

#### `src/nami_code/analysis/concordance.py`

**Purpose.** Measure whether the two independent classification signals — keyword and vision — agree, per reel and dimension. Where `report` *unions* the sources, this asks whether they *coalesce*: convergence is corroborating evidence; systematic divergence flags a weak keyword vocabulary, a mis-described vision category, or a genuinely ambiguous slice.

**Functions and classes.** `load_vision_annotations_conf()` reads `{reel_pk: {dimension: {category: confidence}}}` from `source='vision'` rows above `min_conf`. `vision_done_pks()` returns the comparable reels (`vision_state='done'`). `load_adjacency()` reads an optional `concordance.adjacent` map from `schema.yaml` (`{dimension: {(cat_a, cat_b): weight}}`) for near-synonym partial credit. `pair_concordance()` is the core primitive: a confidence-weighted (Ruzicka) Jaccard between one reel/dimension's keyword set (weight 1.0 each) and vision set (weight = confidence), returning a [0, 1] score or `None` for both-unknown; with no adjacency map it reduces exactly to the plain weighted Jaccard, and the soft form adds symmetric best-match similarity credit when a map is present. `run_concordance()` orchestrates it into three table groups: `concordance_by_dimension` (comparable-reel count, mean/median concordance, exact/zero-agreement shares, and the both-/keyword-only-/vision-only-unknown breakdown), `concordance_confusion_<dim>` (long-form keyword-category × vision-category co-occurrence, with `unknown` explicit), and `concordance_disagreements_<dim>` (per category: agreement vs. keyword-only/vision-only divergence, ranked).

**How it works with other files.** Reuses `analyse._classify_row()` / `_theme_text()` for the keyword side and reads `annotations` + `vision_state` for the vision side; surfaced by the shell `concordance` command. Read-only — never writes the database.

#### `src/nami_code/analysis/asset_profile.py`

**Purpose.** Compare individual audio assets against their parent songs.

**Functions and classes.** `asset_profile()` groups classified reels by song, asset, and variant label, then calculates counts, creator counts, median metrics, date range, and category shares. `asset_vs_song_delta()` compares each asset's profile to its song's overall profile and reports the strongest deviations. `asset_audio_filter_profile()` adds audio-filter scores and summarizes them by asset.

**How it works with other files.** Used by the report to detect whether different Instagram audio uploads of the same song travel through different visual or cultural contexts.

#### `src/nami_code/analysis/audio_filter_index.py`

**Purpose.** Distinguish music-discourse captions from visual-world captions.

**Functions and classes.** `_text()`, `_term_hits()`, `_clean_terms()`, and `_resolve_ref()` normalize terms and references. `load_audio_filter_terms()` reads term groups from `domain.yaml`. `add_audio_filter_scores()` adds per-reel booleans and scores. `audio_filter_summary()` aggregates those scores by song or asset.

**How it works with other files.** Used by the report and asset-profile analysis to show whether reels talk about the song/audio or use the audio as a background for other content.

#### `src/nami_code/analysis/caption_style.py`

**Purpose.** Classify broad caption styles and relate them to classifiability.

**Functions and classes.** `add_caption_features()` adds caption length, hashtag count, emoji count, script detection, and a simple `caption_type`. It can also add per-dimension classifiability flags. `caption_style_summary()` groups by caption type and reports median length, median hashtags, Japanese-script share, and classifiable shares.

**How it works with other files.** Used by the report to explain whether classification failures are linked to missing captions, hashtag-only captions, or language/script differences.

#### `src/nami_code/analysis/check_spam.py`

**Purpose.** Detect and optionally mark spam/bot-like reels using project-configured terms.

**Functions and classes.** `load_spam_terms()` reads `moderation.spam_terms` from `domain.yaml` with a neutral fallback. `find_spam_reels()` filters rows whose captions contain a spam term. `blocked_reels()` returns the reel PKs with `vision_state.status='blocked'` (vision content-policy refusals). `mark_spam_reels()` creates `is_spam` if necessary, resets flags, and marks matching reels. `run_check_spam()` loads data, prints diagnostics, and — when `mark=True` — persists the union of caption-term matches and (unless `include_blocked=False`) the blocked reels as `is_spam=1`; the `blocked` state itself is left intact so the exclusion reason stays recoverable. It returns the caption-term spam dataframe.

**How it works with other files.** Called by shell `checkspam`; `analyse.load_reels()` excludes `is_spam=1` rows by default.

#### `src/nami_code/analysis/spam_report.py`

**Purpose.** Build a standalone, read-only HTML spam report — an embedded reel gallery plus statistics on what attracts spam.

**Functions and classes.** `build()` recomputes the spam set in-module (caption spam-term matches from `load_spam_terms()`, unioned with `vision_state='blocked'` reels unless `include_blocked=False`) rather than reading the persisted `is_spam` column, so it is self-contained and works before `checkspam` runs. It loads `reels` (and `vision_state`) into pandas, tags each reel with its matched terms and block status, and writes one HTML page: a KPI strip, then sections for the spam terms that fired, vision/Gemini outcome counts, per-song and per-variant spam counts and rates, a daily-count spike test (mean+2σ), uploader concentration (top-5 share, channels with ≥3 spam reels), repeated captions, engagement vs. the rest, and finally a gallery ordered by uploader then date with term/`BLOCKED` badges. Each card embeds the reel's thumbnail still as a base64 data-URI (`_img_data_uri()`) — used directly when there's no MP4, or as the `<video poster=…>` otherwise — so the page is shareable as-is; the MP4 stays a local relative `src` (via `_src()`/`os.path.relpath`, too large to embed), and a missing thumbnail falls back to the live Instagram `…/embed` iframe. Helpers `_matched_terms()`, `_bar()`, and `_section()` build the term lists and HTML fragments.

**How it works with other files.** Called by shell `spamreport`; reuses `check_spam.load_spam_terms()`; reads the same `data/reels/` and `data/thumbnails/` assets as the vision tagger. Writes only an HTML file (never touches the database).

#### `src/nami_code/analysis/creator_structure.py`

**Purpose.** Analyze creator concentration and cross-song participation.

**Functions and classes.** `creator_summary()` groups by `creator_pseudo` and computes reel counts, song counts, asset counts, and play metrics. `creator_kpis()` derives corpus-wide creator metrics such as one-time creator share and top-1% shares. `multi_song_creators()` filters to creators appearing on multiple songs.

**How it works with other files.** Used by the report to describe whether a corpus is driven by many casual creators or a concentrated set of repeat accounts.

#### `src/nami_code/analysis/distinctive_hashtags.py`

**Purpose.** Find hashtags that are distinctive for a song or asset relative to the rest of the corpus.

**Functions and classes.** `load_distinctive_hashtag_stoplist()` reads stop terms from `domain.yaml`. `_flat_tags()` normalizes tag lists and removes stop terms. `distinctive_hashtags()` computes smoothed log-odds, share, and lift per group. `top_distinctive_by_song()` and `top_distinctive_by_asset()` are convenience wrappers.

**How it works with other files.** Used by reports and term diagnostics to identify song-specific or asset-specific hashtag signals.

#### `src/nami_code/analysis/hashtag_network.py`

**Purpose.** Build and summarize hashtag co-occurrence networks and semantic hashtag clusters.

**Functions and classes.** `normalize_hashtag()` and `normalize_tag()` clean tags. `_as_list()`, `_normalize_terms()`, `load_hashtag_stopwords()`, and `is_noise_tag()` manage stopwords. `reel_tag_sets()` creates per-reel tag sets. `cooccurrence_edges()` builds weighted hashtag pairs with Jaccard/PMI-style scores. `cluster_hashtags()` clusters tags using networkx when available. `load_hashtag_semantic_rules()`, `semantic_cluster_for_tag()`, and `semantic_cluster_summary()` map tags to configured semantic clusters. `run_network()` runs the full workflow.

**How it works with other files.** Used by report sections and graph-style hashtag diagnostics.

#### `src/nami_code/analysis/impact_by_theme.py`

**Purpose.** Compare category shares among high-impact reels against the rest.

**Functions and classes.** `add_top_quantile_flag()` marks reels in the top quantile of an impact metric within a group. `impact_by_theme()` calculates, per category, the share among top reels, share among non-top reels, and the delta.

**How it works with other files.** Used in the report to show which themes over-index among high-performing reels.

#### `src/nami_code/analysis/manual_sampler.py`

**Purpose.** Generate random and curated close-reading samples.

**Functions and classes.** `_cats()` reads category lists. `_resolve_config_ref()`, `_load_sampling_domain()`, `_load_sampling_schema()`, `_schema_category_ids()`, `_filter_valid_contexts()`, and `_coerce_terms()` load and normalize sampling settings. `load_sampling_config()` and `validate_sampling_config()` provide validated configuration. `sample_by_song()` and `sample_by_context()` create random samples. `close_reading_sample()` combines them. `_format_sample()` and `write_sample_html()` render HTML. `_text_blob()`, `_mask_context()`, `_mask_keywords()`, `_has_music_discourse()`, `_has_visual_world()`, and `curated_close_reading_sample()` implement slot-driven curated sampling.

**How it works with other files.** Called by `sample` and the report builder; reads sampling slots from `domain.yaml`.

#### `src/nami_code/analysis/namigraph.py`

**Purpose.** Build graph nodes and edges for hashtags, creators, songs, and assets.

**Functions and classes.** `_connect()`, `_table_exists()`, `_clean_text()`, `_node_id()`, `_song_label()`, `_asset_label()`, and `_dedupe()` prepare records. `load_graph_records()` loads graph-ready reel rows. `build_hashtag_cooccurrence()`, `build_creator_song_graph()`, `build_creator_asset_graph()`, and `build_song_hashtag_graph()` build graph variants. `_filter_edges()`, `_edge_weight()`, `_component_ids()`, `_to_networkx()`, and `compute_node_metrics()` add filtering and metrics. `write_edges_csv()`, `write_nodes_csv()`, and `write_gexf()` export files. `graph_status()` and `networkx_available()` report readiness.

**How it works with other files.** Used by graph shell commands and graph visualizations.

#### `src/nami_code/analysis/namiscope.py`

**Purpose.** Produce CSV-ready quantitative summaries from the corpus.

**Functions and classes.** `_connect()`, `_table_exists()`, `_empty_scope_frame()`, `_clean_text()`, `_field_column()`, `_ensure_impact()`, `_song_label()`, `_asset_label()`, and `_period_series()` prepare data. `load_scope_dataframe()` loads reel-level data. `make_timeline()`, `describe_distribution()`, `top_reels()`, `correlate_fields()`, `weekday_counts()`, and `impact_summary()` compute scope outputs. `write_csv()` saves results.

**How it works with other files.** Used by `timeline`, `dist`, `topreels`, `correlate`, `weekdays`, and `impact` shell commands; outputs feed `namiviz.py`.

#### `src/nami_code/analysis/namitalk.py`

**Purpose.** Analyze caption and hashtag language.

**Functions and classes.** `_connect()`, `_table_exists()`, `_clean_token()`, `_caption_tokens()`, and `_caption_hashtags()` prepare token streams. `load_caption_dataframe()` loads captions and hashtag lists. `extract_caption_terms()` and `extract_hashtag_terms()` count frequent terms. `_entity_fields()` and `_terms_for_source()` prepare grouping. `distinctive_terms()` computes over-represented terms by song or asset. `caption_markers()` adds simple marker columns. `write_csv()` saves outputs.

**How it works with other files.** Used by `captionterms`, `hashtagterms`, `distinctiveterms`, and `captionmarkers` commands.

#### `src/nami_code/analysis/namiviz.py`

**Purpose.** Plot CSV outputs as PNG files.

**Functions and classes.** `_require_matplotlib()` checks plotting availability. `matplotlib_available()` returns a boolean. `read_csv()`, `_ensure_parent()`, `_save_empty_plot()`, and `_clean_label()` handle input/output. `plot_timeline()`, `plot_distribution()`, `plot_top_reels()`, `plot_impact()`, `plot_terms()`, `plot_graph_edges()`, and `plot_graph_nodes()` create individual plot types.

**How it works with other files.** Used by `scripts/nami_shell/viz_commands.py`; it deliberately reads CSVs instead of recomputing database queries.

#### `src/nami_code/analysis/robustness_check.py`

**Purpose.** Run diagnostics for keyword classification robustness.

**Functions and classes.** `load_robustness_config()` reads broad keyword settings from `domain.yaml`. `unknown_hashtags()` finds frequent hashtags among unknown-classified reels. `multicategory_reels()` flags reels matched by many categories. `keyword_audit()` lists schema keywords and flags risky ones. `validation_sample()` creates manual-check samples. `run_robustness()` orchestrates all diagnostics for schema dimensions.

**How it works with other files.** Used by the `robustness` command and the full report builder.

#### `src/nami_code/analysis/snapshot_churn.py`

**Purpose.** Manage crawl-run snapshots and compute visibility churn.

**Functions and classes.** `_utc_now()`, `_new_crawl_id()`, `_coerce_conn()`, `_table_exists()`, `_columns()`, and `_add_column_if_missing()` support migration and connection handling. `ensure_snapshot_tables()` creates optional snapshot tables. `start_crawl_run()` and `finish_crawl_run()` mark crawl lifecycle. `record_reel_seen()` records one reel observation. `snapshot_current()` logs the current corpus as a snapshot. `load_snapshots()` reads snapshot tables without creating them. `_refresh_done_runs()` selects completed refresh runs. `churn_summary()` compares consecutive refresh runs. `snapshot_status()` reports snapshot/churn readiness.

**How it works with other files.** Used by `crawl_index.py` in refresh mode, by `snapshot`, and by the report's churn section.

### 2.6 Diagnostics and vision modules

#### `src/nami_code/diagnostics/validate_tags.py`

**Purpose.** Create and score manual validation CSVs for vision annotations.

**Functions and classes.** `sample()` selects vision annotations above a confidence threshold, joins captions and shortcodes, and writes `validation_sample.csv`. `score()` reads the filled CSV, filters rows with verdicts, computes per-category checked/correct counts and precision, and prints categories below the threshold.

**How it works with other files.** Called by shell `validatetags sample` and `validatetags score`; validates output produced by `tag_vision.py`.

#### `src/nami_code/vision/db_annotations.py`

**Purpose.** Create the `annotations`, `vision_state`, and `media_state` tables.

**Functions and classes.** `upgrade()` connects to a database, executes the DDL, commits, prints table status, and closes the connection.

**How it works with other files.** Called by shell `annotations`, automatically before `tagvision`, and by `fetch_media.py`.

#### `src/nami_code/vision/retag_nomedia.py`

**Purpose.** Reset `vision_state.status='no_media'` rows back to `pending` once their reel video has appeared on disk.

**Functions and classes.** `run()` loads all `no_media` reel IDs, checks for `data/reels/<reel_pk>.mp4`, flips the available ones back to `pending`, prints counts, and returns how many were re-queued.

**How it works with other files.** Helps recover after running `fetchmedia`; afterwards `tag_vision.py` can tag the newly available videos.

#### `src/nami_code/vision/tag_vision.py`

**Purpose.** Classify each reel's video against the schema with a video-language model and write the results as annotations. This is the heart of the vision module.

**Functions and classes.** It is built around a small `Backend` protocol — `classify(media_ref, schema)` returns, per dimension, a list of `(category, confidence)` pairs. The backends are: `StubModel` (offline, returns random but valid categories), `GeminiModel` (sends the MP4 to Gemini and parses its JSON answer), `QwenVLModel` and `QwenOmniModel` (self-hosted Qwen models that sample frames, and audio for Omni), and the legacy single-frame `VisionModel`. `GeminiModel._raw_response()` sends files of 18 MB or less **inline** (bytes in the request), which skips the Files-API upload and the asynchronous PROCESSING→ACTIVE wait; larger files fall back to `client.files.upload()` plus an ACTIVE poll (the Files API accepts up to 2 GB). That poll's deadline scales with file size — `120 s + 3 s/MB`, capped at 600 s — so a large reel (e.g. a 121 MB clip waits up to ~480 s) is not cut off early; if it still times out the error is classified **transient** (`"stuck in processing"` is in `_TRANSIENT_MARKERS`), so the reel is left `pending` and retried on the next run rather than dropped, while a genuine `FAILED` file state stays terminal. When `vision.fps` is set it is attached as `VideoMetadata(fps=...)` so Gemini samples at that rate. `GeminiModel.classify()` retries up to 4 times with **exponential backoff and jitter** (~2 s → ~4 s → ~8 s, capped 30 s) between *transient* attempts, so a brief demand spike is ridden out within the call instead of dropping the reel; deterministic errors (malformed JSON, 4xx) get only one quick retry and no backoff. `get_model()` picks the backend from the model name. `local_media()` finds a reel's video (with a thumbnail fallback). `_sample_frames()` pulls evenly spaced frames from a video. Helper functions build the prompt from the schema, parse the model's JSON, and validate it (rejecting unknown categories and clamping confidences). `_is_transient_error()` recognises temporary server errors (HTTP 5xx/429, "high demand", timeouts) and `_fmt_eta()` formats the progress ETA. `_CircuitBreaker` is a thread-safe global pause-on-burst gate: after `_BREAKER_THRESHOLD` (4) consecutive transient errors it opens for `_BREAKER_COOLDOWN` (60 s), all workers block in `wait()` until it closes, and a success resets the streak — this rides out a *sustained* wave (which per-call backoff is too short to cover) so reels are tagged in-run rather than dumped to `pending`. A separate **quota guard** distinguishes a 429 quota cap from a 503 demand spike: `_is_quota_error()` matches `429`/`RESOURCE_EXHAUSTED`/`quota`, and `run()` counts *consecutive* quota errors (reset by any success or non-quota outcome); after `_QUOTA_HALT_THRESHOLD` (8) in a row it sets a halt `Event`, since a quota cap will not clear by pausing. Remaining reels then short-circuit (returning the `_HALTED` sentinel, left untouched/`pending`) and queued futures are cancelled, so instead of churning the whole backlog into `pending` the run stops in seconds with a message pointing at the API quota/billing; the partial work is saved and a re-run resumes once quota is restored. `_RateLimiter` spaces request *starts* at least `min_interval` seconds apart (default 0.2 s for Gemini, via `--min-interval`): even when the per-minute average sits well under the TPM/RPM limit, firing many requests in a sub-second clump trips Gemini's burst/prepay throttle (a 429), so spacing the starts — which also de-clumps the thundering herd when all workers leave `breaker.wait()` together after a pause — prevents those burst 429s without capping steady-state throughput (the interval only bites during bursts). `GeminiModel` additionally accumulates each call's `usage_metadata` (input / audio / output / *thinking* tokens) under a lock, and at the end `run()` prints the token totals and an estimated cost at Flash Standard pricing (with a "check Cloud Billing for the exact charge" note). `run(..., workers=1)` queues every pending reel; with `workers>1` it runs the `classify()` calls (wrapped so each reports its outcome to the breaker) in a `ThreadPoolExecutor` while **all SQLite writes and progress prints stay on the calling thread**, so the database is only ever touched single-threaded. It writes `(reel_pk, dimension, category, source='vision', confidence, model)` rows, marks reels `done`, `no_media` (no local video, resolved without a model call), `failed` (genuine error), or leaves them `pending` on a transient error so a later run retries them, and commits per reel so it can resume. Each reel prints a progress line with a running ETA, and the run ends with a wall-clock total.

**How it works with other files.** Reads videos from `data/reels/`, the schema (categories and the `vision:` block) from `schema.yaml`, and the tagging tables from `db_annotations.py`. Its annotation rows are read downstream by `analyse.classify()` and Explorer loading, unchanged.

#### `src/nami_code/vision/validate_visual.py`

**Purpose.** Build an HTML gallery for checking vision tags against the actual clips.

**Functions and classes.** `build()` reads vision annotations and captions, samples reels per dimension/category, and writes a styled `validation_visual.html` (default `outputs/report_out/`, alongside the other reports) with a playable `<video>` per reel (thumbnail fallback) and a link to the Instagram reel; media `src`s are computed relative to the report folder (`os.path.relpath`) so the clips resolve.

**How it works with other files.** Called by shell `validatevisual`; uses the videos and thumbnails from crawling/fetching and the tags created by `tag_vision.py`.

#### `src/nami_code/vision/vision_diagnoser.py`

**Purpose.** Inspect a backend's raw per-category output for a few reels without writing to the database.

**Functions and classes.** `diagnose()` loads the schema, selects a few reels, builds the chosen backend through `get_model()` (the stub works offline), and prints each reel's per-dimension category picks. `main()` parses CLI options and calls `diagnose()`.

**How it works with other files.** Useful for sanity-checking prompts and `vision_description` text in `schema.yaml` before or after a full run.

#### The vision pipeline in one view

The input side and the model side are decoupled from the rest of NAMI by a single contract: vision only ever writes `(reel_pk, dimension, category, source='vision', confidence, model)` rows into `annotations`, and `analyse.classify()` is the only thing that reads them. Everything downstream — report, Explorer, graphs, validation — goes through that one path, so the model can change without touching the analysis layer.

- **Input.** `crawl_details.save_video()` downloads each reel's MP4 inline during the crawl (the CDN link expires within hours); `fetch_media.py` backfills any that were missed. `media_state` tracks the download.
- **Model.** `tag_vision.get_model()` selects a backend by the `--model` name, which **defaults to `gemini-2.5-flash`** (cloud, video + audio); the alternatives are `qwen3-vl-8b` (self-hosted, video), `qwen3-omni` (self-hosted, video + audio), or the offline `stub`. Each backend implements the same `classify(media_ref, schema)` method and returns categories with confidences, which `run()` validates against the schema and clamps to `[0, 1]`.
- **Throughput.** Per-reel time is dominated by network/server waits, not local compute, so `run()` parallelises with `--workers` (default 8 for Gemini) — the `classify()` calls fan out across a thread pool while DB writes stay single-threaded — and `GeminiModel` sends sub-18 MB reels inline to skip the upload + ACTIVE-poll round trip. Together these take a full-corpus pass from roughly a day down to a couple of hours. The 503s seen at higher concurrency are Gemini's **shared-capacity** "high demand", not a per-key quota, so the worker count is not the lever for them; resilience is layered instead: per-call exponential backoff absorbs brief spikes, a global circuit breaker (pause all workers 60 s after 4 consecutive transient errors) rides out sustained waves, and any reel still failing is left `pending` for a follow-up `tagvision` sweep. A **429 `RESOURCE_EXHAUSTED`** is *your* per-key limit, and it comes in two flavours. (1) A genuine **sustained cap** (free-tier daily limit, or billing exhausted) won't clear by pausing — so after 8 consecutive quota errors the run **halts deliberately** with a billing/quota pointer rather than thrashing the breaker, leaving the rest `pending`; enabling/raising billing is the fix. (2) A **burst spike** while the per-minute average is still well under the TPM/RPM ceiling — caused by many requests landing in a sub-second clump (the full-concurrency fan-out, or all workers resuming together after a breaker pause) tripping Gemini's burst throttle. The `_RateLimiter` (`--min-interval`, default 0.2 s for Gemini) smooths the (2) case by spacing request starts, so high `--workers` can run without bursting; lowering `--workers` is the cruder alternative. Because tagging only ever touches `pending` reels, runs are incremental: repeated `tagvision --limit N` builds the corpus up in batches, and any halted/interrupted run resumes cleanly.
- **Prompt.** The instruction sent to a reasoning model is assembled from the schema: the dimensions, their categories, and each category's `vision_description`, plus the `vision:` block's `instruction_template`, `media_resolution`, `fps`, and `max_categories_per_dim`.
- **Cost.** At default media resolution Gemini tokenizes video at ~258 tokens/frame × 1 fps (258 tok/s) plus ~32 tok/s of audio (~290 tok/s total); with the ~970-token schema prompt, a ~27 s reel is about 9k input tokens. On Gemini 2.5 Flash Standard pricing ($0.30 / 1M input video+text, $1.00 / 1M audio, $2.50 / 1M output, mid-2026), that is **~$0.0037 per reel → ~$3.70 per 1,000 reels, ~$37 per 10,000** — so the NAMI corpus (~5.7k reels) is roughly **$20** as a one-time pass. The **free tier** runs the same model at no charge but with low per-minute/per-day caps (a sustained run hits `429 RESOURCE_EXHAUSTED`; see the quota guard above). Cost levers: `media_resolution: low` cuts video to 66 tok/frame (~4× cheaper, but hurts OCR), and the **Batch API** is ~half price for non-real-time work. Self-hosting (Qwen) only pays off across very large or repeated runs, or when the corpus may not leave local machines.

### 2.7 Report modules: `src/nami_code/reports/`

#### `src/nami_code/reports/fonts.py`

**Purpose.** Configure matplotlib fonts so plots can show Japanese labels when system fonts are available.

**Functions and classes.** `available_font_families()` returns installed font names. `choose_plot_fonts()` selects the best available fallback list from preferred Japanese-capable fonts. `configure_plot_fonts()` updates matplotlib `rcParams` and returns the chosen list.

**How it works with other files.** Used by `report.py` before making charts.

#### `src/nami_code/reports/report.py`

**Purpose.** Build the main combined HTML report and all underlying CSV/chart outputs.

**Functions and classes.** `ReportConfig` stores report options. `_as_mapping()`, `_schema_dimension_label()`, `_first_schema_dimensions()`, `_load_report_framing()`, `_enabled()`, `_section_title()`, and `_report_label()` read report configuration. `_apply_plot_theme()`, `_b64()`, `_fmt_pct()`, `_table()`, `_save_csv()`, `_section()`, and `_grid()` format HTML and charts. Chart helpers include `chart_classifiable()`, `chart_distribution()`, `chart_song_heatmap()`, `chart_audio_filter()`, `chart_music_vs_visual()`, `chart_creator_distribution()`, `chart_semantic_clusters()`, `chart_cluster_sizes()`, `chart_network_edges()`, and `chart_combinations()`. `build()` orchestrates loading, classification, every report section, chart creation, CSV export, and final HTML writing.

**How it works with other files.** Pulls together nearly all analysis modules: `analyse`, `audio_filter_index`, `manual_sampler`, `robustness_check`, `snapshot_churn`, `distinctive_hashtags`, `asset_profile`, `creator_structure`, `caption_style`, `impact_by_theme`, `hashtag_network`, and font helpers.

### 2.8 Tools

#### `tools/build_zip.sh`

**Purpose.** Create a clean distributable ZIP archive of the NAMI repository.

**Functions and classes.** Shell script with no functions. It resolves the repository root, checks for `src` and `scripts`, removes any existing output ZIP, then runs `zip -r` with exclusions for `.git`, `.env`, virtual environments, outputs, thumbnails, logs, caches, IDE files, and macOS metadata.

**How it works with other files.** Used for packaging and sharing code/config/data while excluding generated or private files.

#### `tools/config_coach.py`

**Purpose.** Standalone interactive and CI-friendly YAML configuration editor/validator for NAMI v4.

**Functions and classes.** File I/O helpers include `load_yaml()`, `dump_yaml()`, `backup_file()`, `empty_configs()`, `resolve_path()`, `config_paths()`, `load_configs()`, and `save_configs()`. Shape helpers include `ensure_dict()`, `ensure_list()`, and `ensure_shapes()`. Lookup helpers include `dimensions()`, `category_ids()`, `song_ids()`, `parse_csv()`, `prompt()`, `choose()`, `pause()`, and `duplicate_terms()`. Validation is handled by `validate_configs()` and `validate_configs_detailed()`. Editing functions cover project metadata, paths, schema categories, keywords, vision prompts, audio-filter terms, hashtag clusters, stoplists, sampling contexts, curated slots, moderation spam terms, robustness keywords, and report labels. `run_interactive()` drives the menu UI. `print_validation()`, `print_check_report()`, and `run_check()` support `--check` mode. `main()` parses CLI arguments.

**How it works with other files.** Imports validators from `src/nami_code/domain_config.py` when available. It edits only YAML config files and deliberately does not touch Python code, SQLite databases, or generated outputs.

## Acoustic / audio-visual sidecar (`src/nami_av/`)

An optional, self-contained add-on (`[av]` extra; deps: librosa, soundfile, pyloudnorm,
scenedetect, opencv, imagehash, scikit-learn, scipy, ffmpeg — no torch). It reads NAMI's
tables and `data/reels/*.mp4` and writes **new tables into the same `data/corpus.db`**
(the single source of truth); it is never imported by `nami_code`. Driven by the `nami-av`
CLI (`python -m nami_av <cmd>`) and reachable from the NAMI shell as `av <cmd>` (which
injects the shell's `--db`). Every stage is resumable via `*_state` tables and idempotent.

**Modules.** `config.py` (paths + `param_hash`), `schema.py` (the sidecar DDL),
`state.py` (pending/done/failed machine), `audio.py` (ffmpeg WAV extraction, cache-first),
`asset_audio.py` (**the only network module** — fetches each asset's canonical audio +
metadata from Instagram via a HikerAPI client), `features.py` (level-A per-asset
acoustics — tempo/key/spectral/MFCC/segmentation/harmonic-change — measured on the canonical
audio, falling back to a cross-reel consensus), `variants.py` (**baseline-free, symmetric**
within-song variant comparison — `variant_pairs` octave-folded tempo-ratio magnitude + key/
spectral distances per unordered pair, `variant_dispersion` per-song spread, `variant_reach`
median impact + within-song rank + ratio-to-song-median, `variant_identity` duplicate-vs-
genuine grouping by acoustic near-identity, and one arrowless tempo × brightness scatter per
song; no "original" is anointed), `external_ids.py` (**a second network module** — the
`enrich-meta` stage: off the stored Spotify track id it walks **free/keyless** databases —
Odesli (same recording on other platforms) → Deezer (ISRC + release/rank/genres) → MusicBrainz
**by ISRC** for genres/tags + curated Discogs/Wikidata/VGMdb/AllMusic links → Last.fm (global
listeners/playcount, free key); optional Spotify `popularity` only with `--with-spotify` +
Premium creds; HTTP entry points are module-level), `alignment.py`
(per-reel used-segment via
encode-robust onset+chroma cross-correlation against the canonical track + segment heat
strips), `edits.py` (PySceneDetect cut detection + cross-reel alignment; then grouping an
asset's **confidently-aligned** reels into **near-identical edit clusters** by song-aligned
cut pattern — Chamfer distance + DBSCAN on `cut_times_aligned`, written to
`reel_edits.edit_cluster`), `bridge.py` (writes
`source='acoustic'` `sonic` annotations into NAMI's `annotations` table),
`report.py` (acoustic report + the `usage_heatmaps.html` builder), `assetfigures.py`
(per-asset five-panel, time-aligned figure with hook/beats/onsets/segment/refrain markers),
`lyrics.py` (refrain detection from timestamped lyrics: fuzzy repeated-block search),
`assetreport.py` (per-asset metadata report), `editing.py` (the `video_editing.html`
near-identical-edit report), `validate.py` (hand-check sample + alignment-confidence calibration
export). All four HTML reports are self-contained and link to the downloaded reel files on
disk (not Instagram).

**Tables added.** `asset_acoustics` (per asset; `audio_source` ∈ {canonical, preview,
reel_consensus}; key carries a second, independent Krumhansl-Schmuckler estimate in
`est_key_alt`/`est_key_alt_confidence` and a `key_agreement` score of 1 / 0.5 / 0 against
the chroma-peak `est_key`, so a disagreement flags a key worth hand-checking — surfaced
top-of-list in the `validate` export), `asset_music_meta` (per asset; canonical-audio metadata: title/artist/
duration/lyrics/cover/Spotify/hook + the downloaded `data/asset_audio/` path),
`asset_external_meta` (per asset; cross-platform identity & stats — ISRC + Deezer release/
rank/genres + Odesli platform links + MusicBrainz recording MBID/genres/tags and the outbound
Discogs/Wikidata/VGMdb/AllMusic links + Last.fm listeners/playcount, with an `external_state`
∈ {resolved, partial, unresolved}),
`reel_acoustics` / `reel_edits` (per reel; `reel_edits.edit_cluster` carries the
near-identical edit group, and `soft_times` / `n_soft` the flagged crossfades/zooms beside
the hard `cut_times`), and `acoustic_state` / `external_state` / `align_state` /
`edit_state`. The only NAMI-core change is adding `"acoustic"` to `analyse.KNOWN_SOURCES`.
Usage and the honest-limitations list are in `src/nami_av/README.md`.

**Canonical audio.** `extract-acoustic` fetches each asset's **complete canonical audio**
from Instagram (HikerAPI `track_by_canonical_id_v2` by `asset_id`, fresh URL per call so
expiry is a non-issue; 3-tier fallback to reel detail then local reel-consensus) and measures
acoustics on that one file rather than mismatched reel slices. `align` references it, so offsets
are absolute positions in the real track, and uses **encode-robust feature-domain** matching
(onset envelope + chroma; `method="onset"`, `EXTRACTOR_VERSION` 0.3.0). `assetreport` emits the
per-asset metadata report. The pipeline is deterministic — stored JSON is `sort_keys`-serialised,
outputs are byte-stable across runs, and a re-run is idempotent. `validate` exports
`align_confidence.csv` and `--set-overlay-threshold` recomputes `has_overlay` without
re-aligning.

**Cross-platform enrichment (`enrich-meta` stage, `external_ids.py`).** Instagram hands us a
**Spotify track id** per asset (in `asset_music_meta.spotify_track_metadata`). The stage pulls
that thread to attach external *statistics* and **stable** links without artist+title
guesswork, via **free, keyless** services (Spotify's own Web API requires the app owner to hold
a Premium subscription — a free app issues a token but every data call returns
`403 "Active premium subscription required"`). The chain: (1) **Odesli / song.link**
`GET /v1-alpha.1/links` → the same recording's links on Apple Music / YouTube / Deezer / Tidal
/ Amazon (matched by platform id, not name); (2) **Deezer** `api.deezer.com/track` + `/album`
(keyless) → off the Deezer id, the track's **ISRC** (International Standard Recording Code — the
stable, unique-per-recording key) plus album, release date, a `rank` play-count proxy, BPM and
album genres; (3) **MusicBrainz** `GET /ws/2/isrc/{ISRC}` → a recording MBID, community
genres/tags and **curated** outbound URL relationships (Discogs, Wikidata, VGMdb — useful for
Japanese city pop — AllMusic). Looking MusicBrainz up *by ISRC* makes the match exact where the
data exists. (4) **Last.fm** `track.getInfo` (free API key `LASTFM_API_KEY`, no subscription) →
global **listeners** + **playcount** by artist+track — the cross-artist popularity signal, where
Spotify's `popularity` needs Premium and Deezer's `rank` is on an opaque scale; for a
reissue-heavy catalogue the count is for the indexed track, not necessarily the song's whole
history. Coverage is partial by nature (a track may be absent from Deezer, or carry an ISRC
MusicBrainz doesn't index — common for older Japanese recordings); the outcome is stored as
`external_state` (`resolved`/`partial`/`unresolved`) and missing fields are left blank, never
invented. `--with-spotify` opts into Spotify's `popularity` only (needs `SPOTIFY_*` keys **and**
a Premium app owner); Spotify's *audio-features* endpoint is unused — those measurements are the
sidecar's own (`features.py`). The stage is **network + rate-limited** (paces Odesli's ~10/min
free tier; MusicBrainz ≥1 s/req with `MUSICBRAINZ_CONTACT` in the User-Agent) and needs no
credentials. It is **opt-in** in the pipeline (`av all --enrich`) since it is slow, so the
default `all` stays offline-clean. `assetreport` reads `asset_external_meta` read-only and
renders a "cross-platform" block per card (shown only when something resolved) plus new CSV
columns. Like `asset_audio.py`, its HTTP entry points are module-level so the network can be
isolated.

**Edit detection & grouping (`detect-edits` + `group-edits` stages).** `detect-edits` finds
each reel's hard cuts with PySceneDetect (`ContentDetector`), stored as reel-local
`reel_edits.cut_times` and `cut_times_aligned` (= each cut + the reel's segment offset
`reel_acoustics.used_segment_start`, i.e. its absolute position on the song timeline). The same
stage also runs `detect_soft_transitions()` — a histogram-difference pass (HSV per-channel, max
Bhattacharyya distance between frames sampled ~4×/s) that flags *sustained* drift spanning
≥0.4 s, the signature of a crossfade or slow zoom rather than the single-frame spike of a hard
cut — and writes those to `soft_times` / `soft_times_aligned` / `n_soft`. Soft times within
0.5 s of a detected hard cut are dropped so the passes don't double-count. Soft transitions are
stored strictly *alongside* the hard cuts as a best-effort flag and are **not** fed into the
grouping, which keys on `cut_times` alone.
`group-edits` (`edits.run_grouping` → `edits.cluster_asset_edits`) answers one question:
*which of an asset's reels are edited identically or nearly so.* For each `asset_id` it measures
the **symmetric Chamfer distance** between reels' **song-aligned** cut-time sets
(`cut_times_aligned`; mean nearest-neighbour distance, identical patterns → 0) and runs
**DBSCAN** on that precomputed matrix (`eps` = the cut-matching tolerance in seconds, default
0.5; `min_samples` default **2**, so a bare pair already counts as a shared edit). Matching on
song-aligned (not reel-local) cuts is the key correctness property: two reels that share an
*elapsed-time* cadence while cutting **different parts of the song** land at different song
positions and do **not** group — only reels editing the *same passage the same way* do. A reel
is **eligible** only if it has ≥1 cut (a static reel shares no edit) **and** is confidently
aligned — it has a `reel_acoustics` segment offset and is not flagged `has_overlay` (added audio
makes its offset, hence its segment, untrustworthy). Eligible reels get `reel_edits.edit_cluster`
= group id (`≥0`) or `-1` (one-off / noise); zero-cut and not-confidently-aligned reels are set
`NULL`. Labels are deterministic (reel-pk-ordered input). Grouping therefore inherits the
`align` stage's accuracy: a wrong offset can mis-place or drop a reel. `bridge.py` writes only
the `sonic` annotation dimension. In `video_editing.html` the soft transitions are drawn as
dashed blue lines beside the red hard cuts (the drawing stays reel-local — within a group the
segment offset is shared, so the per-reel timeline is consistent).

**Reports (`av report`, run within `av all`).** Four self-contained HTML files under
`outputs/av/`, all grouped by song:
`acoustic_report.html` (baseline-free variant comparison — per-song spread, per-variant reach
with within-song rank, one arrowless tempo × brightness scatter per song, and the duplicate-
vs-genuine grouping — plus acoustic families; assets by descending popularity); `asset_report.html`
(per-asset Instagram metadata × measured acoustics × reach, with Spotify links);
`usage_heatmaps.html` (per asset, assets by descending popularity, five `librosa`-derived graphs
on one shared time axis — segment-usage heat strip, waveform, spectrogram, loudness, tonnetz —
with vertical markers for hook start, beats, onsets, structural-segment boundaries and
experimental lyric-derived refrain starts, plus a caption explaining each Y-axis + boundaries;
PNG panels base64-embedded, ~23 MB); and `video_editing.html` (**assets ascending**; for each
asset with a near-identical-edit group, one inline-SVG strip per group mapped to its song
segment — the segment's **waveform** (grey, decoded live from the local `.m4a`, once per asset,
degrading to a plain strip if absent), the shared **cuts** as full-height red lines, the
**gradual transitions** (crossfades/zooms) as **dashed blue lines**, and the **beats** as short
orange ticks so on/off-beat cutting reads directly (beats are librosa estimates) — plus a
collapsible list of the member videos linked to disk; static/zero-cut and one-off reels are
excluded). The
heavy stages print per-asset progress.

**Output layout (`outputs/av/`).** Only the four HTML reports live at the top of `outputs/av/`;
the generators drop their raw artefacts into subfolders — CSV tables under `data/`
(`asset_report.csv`, `variant_pairs/dispersion/reach/identity.csv`) and PNG figures under
`figures/` (`variant_reach.png`, `variant_feature_space_<song>.png`), exposed as
`AvConfig.data_dir` / `AvConfig.figures_dir`. The per-asset segment panels stay in `segments/`,
the validate hand-check sample (CSV + thumbnail gallery) in `validation/`, and the consensus-WAV
cache in `audio/`.
