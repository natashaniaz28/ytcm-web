# NAMI — Network Analysis of Music on Instagram

NAMI is a toolkit for collecting Instagram Reels associated with a defined set of music assets. It enriches collected data with text- and image-based classification and turns the result into quantitative reports, network exports, and close-reading samples. NAMI is built around a SQLite corpus, a configurable two-axis classification schema, and an interactive shell of currently about 80 commands. Crawling uses HikerAPI. Creator data is stored only as keyed HMAC-SHA256 pseudonyms, so the working corpus contains no Instagram user IDs in clear text. As project, schema, and analytical vocabularies are all defined in YAML, NAMI can be configured for various music corpora by editing config files alone.

---

## 1. Workflows -- The NAMI 101

### 1.0 Quick index

- **1.1** Starting a new project
- **1.2** Choosing what to crawl
- **1.3** First crawl
- **1.4** Weekly updates and visibility churn
- **1.5** Cleaning the corpus
- **1.6** Text classification vs vision classification
- **1.7** Building the report
- **1.8** Exploring the corpus interactively
- **1.9** Manual annotation, close reading, and persistent views
- **1.10** Exporting subsets for collaborators
- **1.11** Network graphs and Gephi
- **1.12** Scope and talk
- **1.13** Visualizations
- **1.14** Robustness, validation, and how to tell when results are bad

### 1.1 Starting a new project from scratch

The minimum setup is:

1. Clone or unzip the NAMI repository.
2. Create a virtual environment and install with the extras you need: `pip install -e .` for the core; `pip install -e ".[crawl]"` adds HikerAPI and tqdm; `pip install -e ".[vision-gemini]"` adds the cloud video classifier (Gemini); `pip install -e ".[vision-local]"` adds the self-hosted video models (Qwen); `pip install -e ".[network]"` adds networkx; `pip install -e ".[math]"` adds scipy; `pip install -e ".[all]"` installs everything.
3. Create a `.env` file at the repo root with `HIKER_TOKEN=...` and `PSEUDO_SALT=...`. Generate the salt with `bash scripts/create_salt.sh > .env` and then add the HikerAPI token by hand. Back up the salt file. Re-crawling with a different salt produces incompatible pseudonyms, so any creator-level continuity is lost. If you will tag reels with the Gemini vision model, add `GEMINI_API_KEY=...` here too.
4. Edit `config/project.yaml` to name your project.
5. Edit `config/songs.yaml` to list the songs and audio-asset variants you want to study.
6. Edit `config/schema.yaml` if you want a different classification scheme than `context × format`.
7. Edit `config/domain.yaml` if you want different audio-filter scoring vocabularies, hashtag stoplists, report labels, or sampling slots.
8. Launch the shell: `python scripts/NAMI.py`.

### 1.2 Choosing what to crawl

A *song* in NAMI is a logical work. Each song has one or more *variants*, which are Instagram *audio assets* that map to the same song. The crawler operates on `asset_id`s, not on songs. Use `addsongs` to search Instagram for audio assets interactively and append them, with their official `asset_id`s, to `config/songs.yaml`.

The *schema* is the analytical lens. By default NAMI uses two dimensions, `context` (what is the reel about) and `format` (how is it presented), each with several categories. Every category has (1) a `keywords:` list of case-insensitive substrings that are matched against the concatenated caption-plus-hashtag text in any language, and (2) optional `vision_prompt:` and `vision_description:` text that tell the vision model what the category looks like and how to tell it apart from similar ones. If you change `schema.yaml`, change its `version:`. Do not silently re-use existing IDs.

### 1.3 First crawl

Crawling is split into an indexing stage and a download stage so that you can stop, resume, and reason about progress.

```
NAMI> setupdb                                # create tables, sync songs.yaml into the DB
NAMI> *crawlindex*                             # Stage A: collect Reel IDs per asset
NAMI> *crawldetails*                           # Stage B: download captions, metrics, thumbnails, and reel videos
NAMI> snapshot --note "initial backfill"     # optional, freezes a corpus snapshot
NAMI> report                                 # build the HTML report
```

`crawlindex` calls HikerAPI once per asset and writes only `(reel_pk, asset_id, play_count)` to `reel_index`. The continuation token is persisted in `index_state.next_page_id`, so if you stop and re-run, it picks up where it left off. An asset whose status is `done` is not re-crawled in the default mode.

`crawldetails` walks `reel_index` rows where `details_done=0`, calls `media_by_id_v1` for each, downloads the thumbnail to `data/thumbnails/` and the reel video to `data/reels/` (both under `data/` alongside the corpus DB, since they are downloaded source data, not regenerable outputs), pseudonymizes the creator with HMAC-SHA256, and writes the full row to `reels`. The video is fetched here, during the crawl, because the CDN link expires within hours. It commits after every reel, so it is also resumable; an interruption costs at most one API call.

Or, in one go:

```
NAMI> *crawl*                                  # = setupdb + crawlindex + crawldetails + snapshot + report
```

### 1.4 Weekly updates and visibility churn

Instagram audio streams are seen through a moving window. New reels may continuously be added, old reels dropped from visibility. NAMI models this distinction explicitly.

To collect *new* reels for the same assets without touching existing rows, run:

```
NAMI> crawl --refresh
```

`crawlindex --refresh` rewinds every asset back to page 1, opens a `crawl_runs` row with `mode='refresh'`, walks all available pages, writes a `reel_seen` row for every observed reel (whether new or already known) with its rank position and current play count, and inserts only previously unknown reel IDs into `reel_index`. `crawldetails` then downloads just those new IDs.

After two or more refresh runs, `report` includes a real churn table per asset: how many reels were retained between runs, how many appeared as new, how many dropped out. Manual `snapshot`s do not feed this. `--pages N` caps the depth per asset; `--empty-stop N` stops crawling an asset after N consecutive pages with zero new IDs to save API calls when the new-content edge has been reached.

### 1.5 Cleaning the corpus

Two cleaning mechanisms run side by side separately.

**Automatic, term-driven.** `checkspam` reads `moderation.spam_terms` from `domain.yaml`, finds reels whose captions match any term (`crypto`, `binance`, `casino`, etc. by default), and writes `is_spam=1` for them in the `reels` table. By default it also marks reels the vision tagger flagged `blocked` — content the model's safety filter refused (adult/prohibited), which can never be tagged and only dilutes the corpus; their `blocked` state is kept, so `visionblocked` still lists them and the exclusion reason is recoverable (pass `--include-blocked false` to mark only caption-term matches). The classifier and report filter out `is_spam=1` rows by default. Edit the term list in `domain.yaml` and re-run `checkspam` to refresh.

**Manual, per-record.** In the Explorer, `markspam INDEX`, `exclude INDEX`, and `keep INDEX` write to an in-memory annotation store; `annotationsave` persists it to `outputs/explorer/manual_annotations.json`. Use this layer for case-by-case decisions that should survive changes to the spam-term list, and for keeping track of why specific reels were dropped. The Explorer JSON is separate from the `is_spam` DB column.

### 1.6 Text classification and vision classification

NAMI supports two annotation sources and they are combined per axis.

**Keyword.** Always computed in-memory by `analyse.classify()`. For each reel, the caption-plus-hashtag text is lowercased and checked against every category's `keywords:` list. Matches are added to the reel's category set for that dimension. Multi-word keywords like `"day in japan"` match captions but rarely hashtags.

**Vision.** Run `tagvision` to classify the *whole reel* — its video frames, any on-screen text, and its audio — against the schema. NAMI sends each reel's downloaded MP4 to a video-language model that is prompted as a zero-shot classifier: the model watches the clip, reasons about what it shows and how it is presented, and returns the matching categories per dimension, each with a confidence score. Results are written as `(reel_pk, dimension, category, source='vision', confidence, model)` rows in `annotations` — the same shape as keyword results, so the two sources combine cleanly. Tagging commits per reel and is resumable via `vision_state`; reels without a local video are marked `no_media` and skipped.

You pick the model with `--model`, which **defaults to `gemini-2.5-flash`** — so `tagvision` with no model flag runs Gemini. **Gemini** is the cloud option: it ingests the video and audio directly, reads Japanese on-screen text well, and is inexpensive for a one-time pass — about **$0.0037 per reel** on Gemini 2.5 Flash (≈ $3.70 per 1,000 reels, so the ~5.7k-reel corpus is roughly **$20**; the free tier is free but rate-capped, see NAMI102 for the breakdown). The self-hosted alternatives are **Qwen3-VL** (`--model qwen3-vl-8b`, video and text) and **Qwen3-Omni** (`--model qwen3-omni`, video, text and audio), for when the corpus must stay on local machines. Each category's `vision_description:` in `schema.yaml` is what helps the model separate look-alike categories (a food clip from a food *review*, incidental dancing from a dance *challenge*), so it is worth writing those well.

Tagging prints a per-reel progress line with a running ETA (`[ 12/5645 | ETA 14h22m] <pk> -> context:cityscape_street(0.80), …`) and a final wall-clock total. Transient server errors (HTTP 503/429, "high demand", timeouts) do **not** burn a reel: it is left `pending` so simply re-running `tagvision` retries it. Only genuine errors (bad output, 4xx) mark a reel `failed`, while reels the model's safety / prohibited-content filter refuses are given the terminal `blocked` state so they are never retried (list them with `visionblocked`). Because the queue is just the `pending` reels, tagging is naturally **incremental** — run `tagvision --limit N` repeatedly to build the corpus up in batches, then a final unlimited `tagvision` to finish and mop up any transient stragglers. Run `visionstatus` at any point to see how many reels are tagged (`done`) versus still open.

Almost all of the per-reel time is network and server-side waiting, not local computation, so tagging runs reels in parallel: `--workers` (default 8 for Gemini) fans the model calls out across a thread pool while all database writes stay on one thread, and Gemini sends reels under 18 MB inline so they skip the slower file-upload-and-wait path. Together these cut a full-corpus pass from roughly a day to a couple of hours. The progress index then counts reels in *completion* order rather than queue order, and the ETA reflects parallel throughput. Raising `--workers` further is faster but provokes more transient 503s (harmless — they just leave reels `pending`); local GPU backends stay serial unless you pass `--workers` explicitly.

A typical vision run:

```
NAMI> annotations                                          # create the tagging tables if needed
NAMI> fetchmedia                                           # backfill any reel videos missed during the crawl
NAMI> tagvision --stub --limit 20                          # dry-run the wiring without a real model
NAMI> tagvision --limit 15                                 # small real batch (defaults to gemini-2.5-flash)
NAMI> validatevisual                                       # eyeball-check the result (plays each clip)
NAMI> report --sources keyword,vision --only-vision-tagged # evaluate vision on just the tagged reels
NAMI> tagvision                                            # full run over the remaining pending reels
NAMI> validatetags sample                                  # build a CSV for manual scoring
NAMI> validatetags score                                   # after you fill in the CSV, compute precision per category
NAMI> report --min-conf 0.2                                 # final report — keyword+vision by default once tagged
```

The flag `--sources keyword,vision` in `report` (or `--sources vision` for vision-only) tells the classifier to union the two sources per axis. `--min-conf` filters weak vision rows. With no `--sources` flag the report includes **every source available** for the DB — `keyword`, plus `vision` once the corpus has been vision-tagged — so newly added vision tags show up automatically; it prints the sources it used. Pass `--sources keyword` for the text-only view, and check the model's precision on your schema with `validatetags` before leaning on the combined output. While only part of the corpus is tagged, add `--only-vision-tagged` to restrict the report to the reels the tagger has actually processed (`vision_state='done'`) so the vision distributions are not diluted by thousands of untagged reels; the report stamps a banner noting the subset is not corpus-representative, and the flag is ignored unless `vision` is a source. The Gemini backend needs `pip install -e ".[vision-gemini]"` and a `GEMINI_API_KEY` in `.env`; the self-hosted backends need `pip install -e ".[vision-local]"` and a GPU.

### 1.7 Building the report

```
NAMI> report
NAMI> open report
```

`report` builds `outputs/report_out/report.html` with embedded base64 PNG charts plus all underlying CSVs under `outputs/report_out/tables/`. The full default section set is listed in `domain.yaml / report.enabled_sections` and can be reduced by editing that list. Sections include scope, classifiability per dimension, music discourse vs visual world (the audio filter index), category distributions, song profiles, dimension co-occurrence, distinctiveness, distinctive hashtags, asset profiles vs song, impact by theme, creator structure, caption style, hashtag networks, close reading samples, robustness checks, and snapshot/churn.

If you want only the underlying CSVs without rebuilding the HTML, run `robustness` (writes only the robustness tables) or use the scope/talk commands.

### 1.8 Exploring the corpus interactively

The Explorer is an in-memory pandas-like query layer over the database.

```
NAMI> load                       # loads reels + hashtags + vision annotations
NAMI> xstatus                    # show what's loaded
NAMI> filter tokyo cafe          # text filter, AND mode by default
NAMI> compare hashtags 20        # what's over-represented in this filter vs the corpus
NAMI> where likes > 5000         # structured filter, narrows further
NAMI> top creators 10            # frequency table of one field
NAMI> review 20                  # show 20 records in compact review form
NAMI> inspect 3                  # full dump of the third record
NAMI> hits 10                    # see the snippets that matched my filter
NAMI> unfilter                   # back to the full loaded set
```

Filters compose: `filter` and `where` both restrict whatever is currently active, so `filter tokyo cafe` followed by `where likes > 5000` gives "Tokyo or cafe" reels with above five thousand likes. `unfilter` clears all filters at once.

`compare FIELD` is the key analytical move: it shows the lift of each value's share in the current filter compared to the corpus-wide share. A high lift means that a hashtag is over-represented in the current slice.

### 1.9 Manual annotation, close reading, and persistent views

After isolating an interesting subset, two things are worth doing:

1. **Save the subset as a view.** Views are persistent named lists of reel IDs, stored in `outputs/explorer/views.json`. In a new session, you can load the corpus, type `useview my_view`, and the same set is restored, even with complex multi-step filters built inside it.

```
NAMI> saveview tokyo_cafe_hits
NAMI> views                       # list all saved views
NAMI> useview tokyo_cafe_hits     # restore later
NAMI> dropview tokyo_cafe_hits    # delete
```

2. **Annotate records by hand.** The review/tag/note system writes to `outputs/explorer/manual_annotations.json`. You can:

+ Tag records by analytical category: `tag 3 context:dance_challenge`.
+ Add free-text notes: `note 3 "tight choreography, no music discourse, very strong fashion framing"`.
+ Mark records reviewed without making a keep/spam/exclude decision: `reviewed 3`.
+ Make a decision: `keep 3`, `markspam 4`, `exclude 5`. The decision implies `reviewed=true`.

Run `annotationsave` to save to SSD; the previous JSON is backed up. Run `annotationload` to reload (also done automatically on `load`).

The close-reading sampler is the curated counterpart. `sample` generates two samples: a stratified random sample across songs (controlled by `sampling.random_state` in `domain.yaml`) and a curated sample driven by `sampling.curated_slots`. Each slot defines a song, optional contexts, optional keywords, a sampling mode (`top` by impact or `random_visual_no_music` for counterexamples), and a count. Edit the slots to match the cases you want to read closely, then `open curated`.

### 1.10 Export subsets for collaborators

```
NAMI> filter tokyo hotel
NAMI> exportview md outputs/explorer/tokyo_cafe.md
NAMI> exportview csv outputs/explorer/tokyo_cafe.csv
NAMI> exportview json outputs/explorer/tokyo_cafe.json
```

`exportview` writes the active set with any manual annotations attached. Markdown is better for close reading and qualitative comments; CSV is better for spreadsheet workflows; JSON preserves the full nested structure (hashtag lists, vision label arrays).

`filtersave` does roughly the same as `exportview json` but without the manual annotations.

### 1.11 Network graphs and Gephi

NAMI builds four graph types. All exports produce `<prefix>_edges.csv`, `<prefix>_nodes.csv`, and, if `networkx` is installed, `<prefix>.gexf`. GEXF opens directly in Gephi.

| Graph                 | Command                       | Nodes                       | Edges                                                                  |
|-----------------------|-------------------------------|-----------------------------|------------------------------------------------------------------------|
| Hashtag co-occurrence | `taggraph`                    | Hashtags                    | Two hashtags appearing on the same reel; weight = co-occurrence count. |
| Creator–song          | `creatorgraph --kind song`    | Creators (pseudo) and songs | A creator published this many reels for this song.                     |
| Creator–asset         | `creatorgraph --kind asset`   | Creators and audio assets   | Same idea at the asset granularity (a song's multiple variants split). |
| Song–hashtag          | `songtaggraph`                | Songs and hashtags          | A song carried this hashtag on this many reels.                        |

Use `--min-weight N` to drop weak edges. Default output directory is `outputs/graphs/`. `graphstatus` reports which graphs are buildable for the current DB.

CSVs are usable on their own, and `vizgraph TYPE` produces a top-N bar plot of nodes and edges per graph type.

### 1.12 Scope and talk

The `scope` and `talk` command families are the fastest way to get specific quantitative answers without building the full report.

**Time and metrics:**

```
NAMI> timeline songs --freq M             # monthly counts by song
NAMI> timeline assets --freq W            # weekly counts by asset
NAMI> dist plays                          # play count quartiles, std, etc.
NAMI> topreels impact 50                  # top 50 reels by impact_metric
NAMI> correlate likes plays               # Pearson/Spearman
NAMI> weekdays taken_at                   # day-of-week to hour-of-day grid
NAMI> impact --by song                    # impact aggregated per song
```

**Text:**

```
NAMI> captionterms --top 100              # most frequent caption words
NAMI> hashtagterms --top 100              # most frequent hashtags
NAMI> distinctiveterms --by song --top 30 # hashtags over-represented per song
NAMI> captionmarkers                      # length, hashtag count, emoji presence
```

Outputs go to `outputs/analysis/`. Pair any of them with the matching `viz*` command to get a PNG.

### 1.13 Visualizations

`namiviz` is CSV-first: each individual `viz` command reads a CSV produced by a scope/talk/graph command and writes a PNG — no DB connection, no recomputation. The exception is `vizall`, which *does* recompute everything from the DB first (see below) so the bundled report is always current.

```
NAMI> viztimeline songs --freq M
NAMI> vizdist plays
NAMI> viztopreels plays
NAMI> vizimpact --by song
NAMI> vizterms hashtags --top 30
NAMI> vizgraph hashtags --top 40
NAMI> vizall                              # recompute ALL inputs, render all 30 charts, bundle visual_report.html
```

`vizstatus` tells you what CSVs are currently available.

### 1.14 Robustness, validation, and how to tell when results are bad

NAMI has some built-in tools to find out whether the results can be considered trustworthy.

1. **Keyword robustness.** `robustness` (or the same section in the full `report`) writes four kinds of CSVs:

- `keyword_audit.csv` -- every keyword in the schema, flagged if it is short (up to 3 characters) or in the project-defined broad-keywords list. These are candidates for false positives. Inspect, then either drop them from the schema or add them to `domain.yaml / robustness.broad_keywords`.
- `unknown_<dim>_hashtags.csv` -- the most frequent hashtags on reels classified only as the unknown category for that dimension. If the same recognizable theme is at the top of this list, this may be a category gap.
- `multicategory_<dim>_reels.csv` -- reels matched by three or more categories on the same axis, signaling that two categories' keywords overlap too much.
- `validation_sample_<dim>.csv` -- five random reels per category for manual precision checking.

2. **Classifiability rates.** Every distribution in the report is reported as "X of Y classifiable" with the denominator shown. The `analyse` command prints the same rate to stdout. If the classifiable rate is low, the per-category shares are computed only over classifiable reels.

3. **Vision validation.** Run `validatetags sample` to write a CSV of vision-tagged reels with their Instagram links and assigned tags, watch the clips, fill in your own true labels, then run `validatetags score` to get per-category precision. A category whose precision falls below 0.75 should be either re-described (edit its `vision_description:`) or dropped.

---

## 2. Command reference

Every command is a method on the interactive shell (`scripts/NAMI.py`). All commands are reachable non-interactively via `python scripts/NAMI.py -c "<command> [args]"`. Listed alphabetically.

### 2.1 `addsongs`

```
Syntax: addsongs
```
Interactive Instagram music search via HikerAPI. Found audio assets can be selected and appended to `config/songs.yaml`. Wraps `nami_code.crawl.add_songs_to_yaml.search_and_add`.

### 2.2 `analyse`

```
Syntax: analyse
```
Runs `nami_code.analysis.analyse` as a script. Gives classifiability rates per dimension, category distributions over the classifiable subset, the song-by-context profile matrix, the most distinctive categories across songs, and the top hashtag co-occurrence pairs.

### 2.3 `annotationload`

```
Syntax: annotationload
```
Loads manual tags, notes, and review flags from `outputs/explorer/manual_annotations.json`. Reports how many records, tags, notes, and review flags were loaded.

### 2.4 `annotations`

```
Syntax: annotations [--db data/corpus.db]
```
Creates the `annotations`, `vision_state`, and `media_state` tables (used by vision tagging and video download) on the given database. Optional in normal use: `tagvision` already calls this upgrade itself before tagging, and it is pure `CREATE TABLE IF NOT EXISTS`, so it never touches existing rows. Run it standalone only if you want the tables created without starting a tagging pass.

### 2.5 `annotationsave`

```
Syntax: annotationsave
```
Writes the in-memory annotation state to `outputs/explorer/manual_annotations.json`. The previous file is backed up before being replaced.

### 2.6 `annotationstatus`

```
Syntax: annotationstatus
```
Prints counts: records with annotations, tags total, notes total, reviewed / kept / spam / excluded.

### 2.7 `captionmarkers`

```
Syntax: captionmarkers [--db data/corpus.db] [--out PATH]
```
Writes a CSV of simple per-caption markers (length, hashtag count, emoji presence, mention presence, etc.).

### 2.8 `captionterms`

```
Syntax: captionterms [--top N] [--db data/corpus.db] [--out PATH]
```
Writes a CSV of the most frequent caption terms across the corpus. Default `--top 50`. Output default: `outputs/analysis/caption_terms.csv`.

### 2.9 `checkspam`

```
Syntax: checkspam [--db data/corpus.db] [--include-blocked true|false]
```
Loads `moderation.spam_terms` from `config/domain.yaml` and runs them as case-insensitive substrings against every caption. Reports counts and distribution, then sets `is_spam=1` for matches and `is_spam=0` for everything else in the `reels` table. By default it also unions in reels with `vision_state='blocked'` (vision content-policy refusals — adult/prohibited content that can never be tagged); their `blocked` state is preserved, so `visionblocked` still lists them. Pass `--include-blocked false` to mark only caption-term matches. This function changes the database! `analyse` and `load_reels` exclude `is_spam=1` rows from analysis by default.

### 2.10 `compare`

```
Syntax: compare FIELD [N]
Examples: compare hashtags 20 | compare songs | compare vision
```
For each value of `FIELD`, prints the active-subset count, the total-corpus count, the share in each, the lift (active% / total%), and the delta. Useful for asking what is over-represented in a filter. Aliases `songs` -> `song_title`, `creators` -> `creator_pseudo`, `hashtags` -> `hashtags`, `vision`/`labels` -> `vision_labels`.

### 2.11 `concordance`

```
Syntax: concordance [--db data/corpus.db] [--schema config/schema.yaml] [--out outputs/report_out/tables] [--min-conf 0.2]
```
Read-only check of whether the two independent classification signals — keyword and vision — agree. For every vision-tagged reel (`vision_state='done'`), it compares the keyword category set against the vision category set per dimension using a confidence-weighted (Ruzicka) Jaccard, with optional partial credit for near-synonym categories (an `concordance.adjacent` map in `schema.yaml`). Prints a per-dimension summary (mean/median concordance, exact- and zero-agreement shares, and an unknown breakdown: both-unknown, keyword-only-unknown, vision-only-unknown) and writes `concordance_by_dimension.csv` plus per-dimension `concordance_confusion_<dim>.csv` (keyword-category × vision-category co-occurrence) and `concordance_disagreements_<dim>.csv` (per category: agreement vs. keyword-only / vision-only divergence, ranked — the candidates for keyword or `vision_description` tuning). High mean concordance is converging evidence; systematic divergence flags a weak keyword vocabulary, a mis-described vision category, or a genuinely ambiguous slice.

### 2.12 `correlate`

```
Syntax: correlate FIELD1 FIELD2 [--db data/corpus.db] [--out PATH]
FIELD: likes | plays | views | comments | duration | impact
```
Pearson/Spearman correlation between two numeric reel fields, written to CSV. Reports n, the two coefficients, and prints them.

### 2.13 `crawl`

```
Syntax: crawl
crawl --refresh
crawl --refresh --pages N
```
The full crawling pipeline: `setupdb` -> `crawlindex` (with any passed flags) -> `crawldetails` -> either `snapshot` (when no `--refresh`) or nothing (when `--refresh`) -> `report`. The normal weekly update is `crawl --refresh`.

### 2.14 `crawldetails`

```
Syntax: crawldetails [--limit N] [--sleep 0.25]
```
Stage B of crawling. Iterates `reel_index` rows with `details_done=0`, calls HikerAPI `media_by_id_v1` for each, downloads the thumbnail to `data/thumbnails/<reel_pk>.jpg` and the reel video to `data/reels/<reel_pk>.mp4` (while the CDN links are fresh), writes the row to `reels`, parses hashtags out of the caption into `reel_hashtags`, records the download in `media_state`, and sets `details_done=1`. Resumable.

### 2.15 `crawlindex`

```
Syntax: crawlindex
crawlindex --refresh [--pages N] [--sleep 0.3] [--empty-stop N]
```
Stage A of crawling. Default mode: a resumable backfill across every `track_variants` row, continuing from `index_state.next_page_id`. Refresh mode (`--refresh`): starts at page 1 for every asset, opens a `crawl_runs` row with `mode='refresh'`, writes a `reel_seen` row for every observed reel, and inserts only previously unknown reel IDs into `reel_index`. The refresh run is what `churn_summary` reads. `--pages N` caps depth per asset. `--empty-stop N` stops after N consecutive pages with zero new IDs.

### 2.16 `creatorgraph`

```
Syntax: creatorgraph [--kind song|asset] [--db data/corpus.db] [--min-weight N] [--out outputs/graphs/creator_song]
```
Exports a graph linking pseudonymized creators to songs (default) or to audio assets. Writes `<out>_edges.csv`, `<out>_nodes.csv`, and `<out>.gexf` (GEXF only if `networkx` is installed). Edge weight is the number of reels the creator published in that relation.

### 2.17 `dist`

```
Syntax: dist FIELD [--db data/corpus.db] [--out PATH]
FIELD: likes | plays | views | comments | duration
```
Writes a CSV of summary statistics (count, mean, std, min, quartiles, max) for one numeric reel field. Output default: `outputs/analysis/dist_<field>.csv`.

### 2.18 `distinctiveterms`

```
Syntax: distinctiveterms [--by song|asset] [--source hashtags|captions] [--top N] [--db data/corpus.db] [--out PATH]
```
Writes a CSV of lightweight distinctiveness scores: which terms are over-represented in one song/asset relative to the rest of the corpus.

### 2.19 `dropview`

```
Syntax: dropview NAME
```
Deletes a saved Explorer view from `outputs/explorer/views.json`. The previous file is backed up first.

### 2.20 `exclude` / `unexclude`

```
Syntax: exclude TARGET
unexclude TARGET
```
Mark or unmark one record as manually excluded. `exclude` also sets `reviewed=true`. State lives in memory until `annotationsave`. TARGET may be a 1-based index, `reel_pk`, or shortcode/`code`.

### 2.21 `exit` / `quit` / `q`

```
Syntax: exit | quit | q
```
Quit the program. Does not auto-save Explorer state.

### 2.22 `exportgraph`

```
Syntax: exportgraph TYPE [PATH] [--db data/corpus.db] [--min-weight N]
TYPE: hashtags | creator_song | creator_asset | song_hashtag
```
General-purpose graph export, dispatching to the same builders as `taggraph`, `creatorgraph`, and `songtaggraph`. Writes `<PATH>_edges.csv`, `<PATH>_nodes.csv`, and `<PATH>.gexf`.

### 2.23 `exportview`

```
Syntax: exportview [json|csv|md] [PATH]
Examples: exportview csv outputs/explorer/current.csv | exportview markdown close_reading.md
```
Writes the active Explorer set, augmented with any manual annotations, to a file. Format is inferred from the first argument or from the file suffix.

### 2.24 `fetchmedia`

```
Syntax: fetchmedia [--db data/corpus.db] [--refresh true|false] [--vid-timeout 60] [--api-timeout 20]
```
Best-effort recovery of reel videos for reels missing a local `data/reels/<reel_pk>.mp4`. The main capture happens inline during `crawldetails`; this backfills any that were missed. It tries the stored `video_url` first and, with `--refresh true` (default), refetches a fresh URL from HikerAPI when the stored one has expired. Updates `media_state`.

### 2.25 `fetchthumbs`

```
Syntax: fetchthumbs [--db data/corpus.db] [--refresh true|false] [--img-timeout 12] [--api-timeout 20]
```
Downloads missing thumbnails for downloaded reels. With `--refresh true` (default), if the stored CDN URL has already expired, refetches the reel from HikerAPI to obtain a fresh URL. With `--refresh false`, it only attempts the stored URLs.

### 2.26 `fieldfilter`

```
Syntax: fieldfilter FIELD TERM... [--and|--or]
Examples: fieldfilter hashtag dance | fieldfilter caption "official audio" | fieldfilter vision performance
```
Like `filter`, but only searches inside one specific field. Field aliases: `caption`/`text` -> `caption_text`, `hashtag`/`hashtags` -> `hashtags`, `vision`/`tags` -> `vision_labels`, `creator`/`user` -> `creator_pseudo`, `shortcode`/`urlcode` -> `code`.

### 2.27 `filter`

```
Syntax: filter [--and|--or] TERM...
Examples: filter remix retro | filter --and dance challenge
```
Restricts the active Explorer set to records whose combined text fields (caption, hashtags, song title/artist, asset id, variant label, creator pseudo, vision labels) contain the given terms. Default mode is `--and`.

### 2.28 `filtersave`

```
Syntax: filtersave [PATH]
```
Writes the active set as JSON or CSV. Default path: `outputs/explorer/filter.json`. Unlike `exportview` it does not attach the manual annotations.

### 2.29 `graphstatus`

```
Syntax: graphstatus [--db data/corpus.db]
```
Reports DB readiness for graph export: networkx availability, counts of reels/creators/songs/assets/hashtags/annotations, and which graph types are currently buildable.

### 2.30 `hashtagterms`

```
Syntax: hashtagterms [--top N] [--db data/corpus.db] [--out PATH]
```
Top-N most frequent hashtags. Output default: `outputs/analysis/hashtag_terms.csv`.

### 2.31 `hits`

```
Syntax: hits [N]
```
For the last `filter` or `fieldfilter`, prints up to N matching records with highlighted snippet windows around the hit terms. Useful for verifying why a filter matched.

### 2.32 `howto`

```
Syntax: howto
```
Prints the recommended workflows for crawling, analysis, and vision.

### 2.33 `impact`

```
Syntax: impact [--by song|asset|hashtag|creator] [--db data/corpus.db] [--out PATH]
```
Aggregates an `impact_metric` per group (default: per song). Impact is `play_count` when present, else `view_count`, else `like_count`. Output: median, mean, sum, n.

### 2.34 `info`

```
Syntax: info
```
Shows general info on NAMI.

### 2.35 `inspect`

```
Syntax: inspect INDEX | inspect REEL_PK | inspect SHORTCODE
```
Prints a full info dump for one reel. INDEX is 1-based and refers to the current active Explorer set.

### 2.36 `keep` / `unkeep`

```
Syntax: keep TARGET
unkeep TARGET
```
Manual-review flags. `keep` marks the record as `keep=true` and `reviewed=true`.

### 2.37 `load`

```
Syntax: load [reels|PATH] [--db data/corpus.db]
Examples: load | load reels --db data/corpus.db | load outputs/view.json
```
Loads reel data into the Explorer state. Without arguments, loads from the configured DB. With a path argument ending in `.json` or `.csv`, loads from that file instead. Automatically loads any existing `manual_annotations.json` so prior annotations are visible.

### 2.38 `markspam` / `unmarkspam`

```
Syntax: markspam TARGET
unmarkspam TARGET
```
Manual spam flag in the Explorer JSON sidecar. Distinct from the `is_spam` column written by `checkspam`: Manual spam is an additional labeling that persists over spam-term changes.

### 2.39 `note`

```
Syntax: note TARGET TEXT
Example: note 1 "strong visual framing"
```
Appends a timestamped free-text note to one record.

### 2.40 `notes`

```
Syntax: notes [TARGET]
```
Without TARGET, lists every record that has at least one note, with the most recent note text. With TARGET, prints all notes for one record in chronological order.

### 2.41 `open`

```
Syntax: open [report|sample|curated|vision|visual|path]
```
Opens a HTML file in the default browser. All bundled reports live in `outputs/report_out/`. Built-in shortcuts: `report` -> `report.html`; `spam` -> `spam_report.html`; `charts` -> `visual_report.html` (the `vizall` bundle); `sample` -> close-reading sample; `curated` -> curated close-reading sample; `visual` -> `validation_visual.html`.

### 2.42 `paths`

```
Syntax: paths
```
Prints the existence status of the standard NAMI paths: DB, songs, schema, thumbnails, report HTML, tables dir, charts dir.

### 2.43 `report`

```
Syntax: report [--db data/corpus.db] [--schema config/schema.yaml] [--out outputs/report_out] [--sources keyword,vision] [--min-conf 0.2] [--only-vision-tagged] [--silent]
```
Builds the combined HTML report and writes all CSVs and PNG charts under `--out`. **With no `--sources` flag it defaults to every source available for the DB** — `keyword`, plus `vision` whenever the `annotations` table holds vision rows (a never-tagged corpus stays keyword-only) — and prints the sources it used. Pass `--sources keyword` for text classification only, or `--sources keyword,vision` to force both explicitly. `--min-conf` filters weak vision annotations. `--only-vision-tagged` restricts the report population to reels the vision tagger has processed (`vision_state='done'`, including reels that got zero tags) — useful while only part of the corpus is tagged, so vision distributions are not diluted by untagged reels; it is ignored unless `vision` is a source, and the report header carries a banner noting the subset is not corpus-representative. Unless `--silent`, the report opens in the browser when finished. The set of report sections, their labels, and which dimensions are primary/secondary all come from `domain.yaml / report`.

### 2.44 `review`

```
Syntax: review [N]
```
Shows the first N (default 10, max 50) Explorer records in review form, with manual tags and review flags. Designed for sweeping through a filter and using `keep` / `markspam` / `exclude` / `tag` / `note` by index.

### 2.45 `reviewed` / `unreviewed`

```
Syntax: reviewed TARGET
unreviewed TARGET
```
Toggle the `reviewed` flag on one record. Useful for keeping track of which records you have already looked at without making any keep/spam/exclude decision.

### 2.46 `robustness`

```
Syntax: robustness [--db data/corpus.db] [--schema config/schema.yaml] [--out outputs/report_out/tables] [--sources keyword,vision] [--min-conf 0.2]
```
Writes robustness CSVs without building the full report. Produces a keyword audit (which keywords are short or in the broad-keywords list), a per-dimension unknown-hashtag breakdown (what is the top text in reels NAMI couldn't classify?), a multi-category reels list (reels matched by many categories -- possibly over-broad keywords), and per-category validation samples.

### 2.47 `runmodule`

```
Syntax: runmodule nami_code.some.module
```
Runs a `nami_code.*` module as `__main__`. This makes modules without a dedicated shell command accessible.

### 2.48 `runscript`

```
Syntax: runscript scripts/analyse.py
```
Same as `runmodule` but for all script paths.

### 2.49 `sample`

```
Syntax: sample
```
Generates random and curated close-reading samples by running `scripts/manual_sampler.py`. Writes CSV and HTML under `outputs/report_out/`. Curated slot definitions come from `domain.yaml / sampling.curated_slots`. Random state is fixed (`42` by default in `domain.yaml`) so re-runs produce the same sample.

### 2.50 `saveview`

```
Syntax: saveview NAME
Example: saveview high_impact_reels
```
Saves the IDs of the currently active Explorer set as a named view in `outputs/explorer/views.json`. Names must match `[A-Za-z0-9_-]+`. Overwriting an existing view first creates a backup of the file.

### 2.51 `setupdb`

```
Syntax: setupdb [--db data/corpus.db]
```
Creates the DB if it does not exist, runs all `CREATE TABLE IF NOT EXISTS` statements, and syncs the contents of `songs.yaml` into the `songs` and `track_variants` tables.

### 2.52 `shell`

```
Syntax: shell COMMAND
```
Runs an OS command from inside the NAMI shell.

### 2.53 `snapshot`

```
Syntax: snapshot [--db data/corpus.db] [--note "manual snapshot"]
```
Writes the current `reels` table contents to `reel_seen` under a new `crawl_runs` row with `mode='snapshot'`. This is a corpus snapshot, not a real visibility refresh. `churn_summary` will ignore it. Use `crawlindex --refresh` instead for churn measurement.

### 2.54 `songtaggraph`

```
Syntax: songtaggraph [--db data/corpus.db] [--min-weight N] [--out outputs/graphs/song_hashtag]
```
Exports a graph linking songs to hashtags. Edge weight is the number of reels of that song carrying that hashtag.

### 2.55 `spamreport`

```
Syntax: spamreport [--db data/corpus.db] [--out outputs/report_out/spam_report.html] [--limit 150] [--include-blocked true|false] [--silent]
```
Builds a read-only HTML spam report and opens it (unless `--silent`). The spam set is recomputed the same way `checkspam` marks it — caption spam-term matches unioned with vision `blocked` reels (content-policy refusals), the latter omitted by `--include-blocked false` — so it works even before `checkspam` has been run and changes nothing in the DB. The page has a gallery of the flagged reels (ordered by uploader then date so same-channel clusters group together, each badged with the terms that fired and/or `BLOCKED`) followed by statistics: which spam terms fired, the vision/Gemini outcome counts (`blocked`/`failed`/…), which song and track variant attract spam (count and rate), whether uploads come in temporal spikes (mean+2σ test on daily counts), uploader concentration (top-5 share, channels with ≥3 spam reels), repeated captions (bot signatures), and engagement vs. the rest of the corpus. `--limit` caps the gallery size. Each reel's **thumbnail still is base64-embedded**, so the HTML is shareable as-is and a recipient sees the flagged frames; the playable MP4 is only a local reference (videos are too large to embed), so clips play only on the machine that built the report.

### 2.56 `status`

```
Syntax: status [--db data/corpus.db]
```
Prints repository root, DB path and existence, the four config-file paths and existence, the report output dir, the table list of the DB, and row counts for each known table, plus the count of pending Stage-B reels.

### 2.57 `tag` / `untag`

```
Syntax: tag TARGET TAG
untag TARGET TAG
Example: tag 1 context:dance_challenge
```
Add or remove a manual tag on one Explorer record. Tags must match `[a-z0-9_:-]+`; spaces are converted to underscores; uppercase is lowercased.

### 2.58 `taggraph`

```
Syntax: taggraph [--db data/corpus.db] [--min-weight N] [--out outputs/graphs/hashtags]
```
Exports the hashtag co-occurrence graph. Two hashtags share an edge if they appear together on at least one reel. Edge weight is the number of such co-occurrences. `--min-weight` can be used to suppress noise.

### 2.59 `tags`

```
Syntax: tags
```
Prints frequencies of all manual tags across the Explorer state.

### 2.60 `tagvision`

```
Syntax: tagvision [--db data/corpus.db] [--stub true|false] [--limit N] [--reset true|false] [--model MODEL] [--resolution default|low] [--fps N] [--workers N]
```
Classifies every reel with `vision_state.status='pending'` by sending its local video to a video-language model and writing the categories it returns as `(reel_pk, dimension, category, source='vision', confidence, model)` rows in `annotations`. The model is chosen with `--model`, which **defaults to `gemini-2.5-flash`** when omitted; other options are `qwen3-vl-8b` (self-hosted, video) and `qwen3-omni` (self-hosted, video+audio). Reels without a local video are marked `no_media`; a reel that fails for a genuine reason is marked `failed`, while a reel that hits a transient server error (HTTP 503/429, "high demand", timeout) is left `pending` so a later run retries it automatically. Progress is printed per reel with a running ETA (`[ 12/5645 | ETA 14h22m] <pk> -> …`) and a wall-clock total at the end. `--workers` sets how many reels are tagged in parallel (default 8 for Gemini, 1 for the local GPU backends and `--stub`); the model calls fan out across a thread pool while all database writes stay single-threaded. Combined with Gemini sending sub-18 MB reels inline (skipping the slower file-upload path), this takes a full-corpus pass from roughly a day down to a couple of hours; higher worker counts go faster but provoke more transient 503s, which simply leave reels `pending` for a follow-up run. `--stub` uses an offline fake model (`--stub false` forces the real model). `--reset` deletes all prior vision annotations and re-queues every reel (omit it to keep building incrementally). `--resolution` (`default`/`low`) and `--fps` tune how much of each clip the model sees (lower is cheaper; `default` resolution keeps on-screen text legible). For Gemini, `--fps` is sent as video metadata so it actually controls the server-side frame sampling rate.

### 2.61 `timeline`

```
Syntax: timeline [songs|assets|hashtags|creators] [--freq D|W|M] [--db data/corpus.db] [--out PATH]
```
Writes a CSV of counts per period (day, week, or month) per entity. Output default: `outputs/analysis/timeline_<entity>_<freq>.csv`.

### 2.62 `top`

```
Syntax: top FIELD [N]
Examples: top hashtags 20 | top songs | top creators
```
For the active Explorer set, prints the N most frequent values of FIELD. Aliases: `songs` -> `song_title`, `creators` -> `creator_pseudo`, `hashtags` -> `hashtags`.

### 2.63 `topreels`

```
Syntax: topreels FIELD [N] [--db data/corpus.db] [--out PATH]
FIELD: likes | plays | views | comments | duration | impact
```
Writes the top-N reels by the chosen metric to CSV. Output default: `outputs/analysis/topreels_<field>.csv`. Default N=20.

### 2.64 `unfilter`

```
Syntax: unfilter
```
Drops the current Explorer filter; the active set becomes the full loaded set again.

### 2.65 `useview`

```
Syntax: useview NAME
```
Restores a previously saved view: the active Explorer set becomes the records whose IDs are listed in the view. IDs that no longer exist in the loaded data are reported as missing.

### 2.66 `validatetags`

```
Syntax: validatetags [sample|score]
```
With `sample` (default), builds a CSV of vision-tagged reels for manual review. With `score`, reads back the user-completed CSV and computes per-category precision against the manual labels.

### 2.67 `validatevisual`

```
Syntax: validatevisual
```
Builds a flat HTML gallery (`outputs/report_out/validation_visual.html`) grouping tagged reels by category, with a playable `<video>` for each clip (thumbnail fallback) and a link to the Instagram reel, so a person can check the tags against the actual content.

### 2.68 `views`

```
Syntax: views
```
Lists every saved view: name, creation time, restored/stored counts, source DB, last filter that produced it.

### 2.69 `visionblocked`

```
Syntax: visionblocked [--db data/corpus.db] [--limit N] [--csv PATH]
```
Read-only listing of every reel in the terminal `blocked` state — reels that Gemini's safety / prohibited-content filter refused during `tagvision`, and which are therefore never retried. For each it prints the `reel_pk`, the shortcode as an `instagram.com/reel/…` URL, the `[song_id/variant_label]`, the creator pseudonym, the block timestamp, any keyword tags (vision tags never exist for a blocked reel) and a caption snippet — enough to eyeball what tripped the filter. `--limit N` truncates the console list; `--csv PATH` exports the full rows (captions untruncated) to a file instead. Pairs with `visionstatus`, which reports the `blocked` count.

### 2.70 `visionreport`

```
Syntax: visionreport
```
Builds the standard report with default config (`ReportConfig()`). Equivalent to `report` with all defaults.

### 2.71 `visionstatus`

```
Syntax: visionstatus [--db data/corpus.db]
```
Read-only summary of vision-tagging progress: total reels, how many are `done` (tagged) with a percentage, and how many are still open, broken down into `pending`, `no_media`, `blocked` (terminal content-policy refusals — see `visionblocked`), `failed`, and reels with no `vision_state` record yet. Also lists the model(s) present in the `source='vision'` annotations. Handy before deciding whether to run another `tagvision` batch, `fetchmedia`, or a sweep.

### 2.72 `vizall`

```
Syntax: vizall [--top N] [--no-recompute] [--link-images] [--out PATH] [--silent]
```
The one-shot "all visualizations" command. It (1) **recomputes every analysis and graph input fresh from the database** — running the `timeline` (songs/assets/hashtags/creators), `dist` and `topreels` (every numeric field), `impact` (every dimension), `captionterms`/`hashtagterms`/`distinctiveterms`, and `exportgraph` (all four network graphs) commands — so the charts are never stale or missing; (2) renders all 30 PNGs into `outputs/visuals/`; and (3) bundles them into a single grouped `outputs/report_out/visual_report.html` — **the same folder as `report.html` and `spam_report.html`**, so all the HTML reports live together (Timelines · Distributions · Top reels · Impact · Terms · Networks), which it opens unless `--silent`. By default the charts are **base64-embedded**, so the one HTML file is self-contained and can be passed on to someone else as-is; pass `--link-images` for a lighter file that references the PNGs in `outputs/visuals/` via a relative path instead. Pass `--no-recompute` to plot only the CSVs that already exist (the previous behaviour), `--out PATH` to write the report elsewhere, and `--top N` to cap bars/rows per chart. A producer or plot that fails is reported and shown as "(chart unavailable)" rather than aborting the run.

### 2.73 `vizdist`

```
Syntax: vizdist FIELD [--in PATH] [--out PATH]
FIELD: likes | plays | views | comments | duration
```
Bar plot of the summary stats produced by `dist`.

### 2.74 `vizgraph`

```
Syntax: vizgraph [hashtags|creator_song|creator_asset|song_hashtag] [--top N] [--out-dir PATH]
```
Plots the top-N nodes and edges from the chosen exported graph. Inputs are read from `outputs/graphs/`. Outputs go to `outputs/visuals/` by default.

### 2.75 `vizimpact`

```
Syntax: vizimpact [--by song|asset|hashtag|creator] [--top N] [--in PATH] [--out PATH]
```
Bar plot of the impact summary produced by `impact`.

### 2.76 `vizstatus`

```
Syntax: vizstatus
```
Reports matplotlib availability and lists the CSVs currently available under `outputs/analysis/` and `outputs/graphs/`.

### 2.77 `vizterms`

```
Syntax: vizterms [captions|hashtags|distinctive] [--top N] [--in PATH] [--out PATH]
```
Bar plot of the most frequent caption terms, hashtags, or distinctive terms.

### 2.78 `viztimeline`

```
Syntax: viztimeline [songs|assets|hashtags|creators] [--freq D|W|M] [--top N] [--in PATH] [--out PATH]
```
Multi-series line plot of the CSV produced by `timeline`. Top-N entities are shown.

### 2.79 `viztopreels`

```
Syntax: viztopreels FIELD [--top N] [--in PATH] [--out PATH]
FIELD: likes | plays | views | comments | duration | impact
```
Bar plot of the top reels CSV.

### 2.80 `weekdays`

```
Syntax: weekdays [taken_at|ingested_at] [--db data/corpus.db] [--out PATH]
```
Writes a CSV of counts by weekday and hour. Default target is `outputs/analysis/weekdays_<field>.csv`.

### 2.81 `where`

```
Syntax: where FIELD OP VALUE
Operators: = != > >= < <= contains between
Examples: where likes > 1000 | where hashtag contains dance | where taken_at between 2024-01-01 2024-12-31
```
Structured comparison filter on the active Explorer set. Numeric fields auto-coerce to numbers; everything else compares as text.

### 2.82 `xsample`

```
Syntax: xsample [N]
```
Prints N random records from the active Explorer set in brief form. Default N=5.

### 2.83 `xstatus`

```
Syntax: xstatus
```
Explorer-specific status (named `xstatus` to avoid colliding with `status`). Prints loaded source, total vs active record counts, last filter, saved-view count, and manual-annotation counters.

## 3. Acoustic / audio-visual sidecar (`nami_av`)

NAMI has an optional **sidecar** that adds an acoustic layer and near-identical edit
grouping, living in `src/nami_av/`. It has its own `nami-av` command and is also reachable from the
NAMI shell as **`av <subcommand>`** (e.g. `av all`, `av status`, `av validate`). It reads
NAMI's tables and the reel MP4s and writes its results back into the same `data/corpus.db` —
`corpus.db` stays the single source of truth. It is fully optional: with it absent, NAMI
behaves exactly as before.

Each song-asset's acoustics are measured on its **complete canonical audio**, fetched once
from Instagram (the same audio object every reel of that asset uses), rather than on the
short, mismatched clips individual reels happen to use — so tempo/key/brightness are clean
per-asset facts and reel alignment is to absolute positions in the real track.

What it answers: (1) the **variant question** — how a song's renderings differ acoustically
and in reach, compared **symmetrically** (no "original" is assumed: variants are measured
against *each other*, not against a baseline), and which "variants" are actually the same
recording re-uploaded; (2) **near-identical edits** — which of an asset's reels are edited
the same way (the same cuts at the same points of the song; reels using a *different* segment
of the track don't count even if their cut cadence happens to match). It also writes coarse
`sonic` labels into NAMI's `annotations` table as `source='acoustic'`, so they flow through
the normal source machinery.

`av report` (run within `av all`) builds four self-contained HTML reports under `outputs/av/`:

- **`acoustic_report.html`** — baseline-free variant comparison: per-song acoustic *spread*,
  per-variant *reach* (within-song rank), one arrowless tempo × brightness scatter per song,
  and a duplicate-vs-genuine-variant grouping; plus acoustic families.
- **`asset_report.html`** — one card per asset: Instagram's real title/artist/Spotify/lyrics
  paired with our measured acoustics and reach (audits the `songs.yaml` grouping).
- **`usage_heatmaps.html`** — per asset, five graphs on one shared time axis (segment-usage
  heat strip, waveform, spectrogram, loudness, tonnetz) with markers for the hook, beats,
  onsets, structural segments and (experimental) lyric-derived refrain starts.
- **`video_editing.html`** — for each asset with a group of near-identically edited reels,
  one strip per group on the song's timeline: the segment's **waveform** (grey), the shared
  **cuts** (full-height red) and the **beats** (short orange ticks) so you can see whether the
  cuts fall on- or off-beat, plus a collapsible list of the member videos linked to disk. The
  waveform/beats are decoded live from the asset's local audio (beats are librosa estimates).

Reports are grouped by song; `usage_heatmaps.html` orders assets by popularity and
`video_editing.html` orders them ascending. All link to the **downloaded reel files on disk**. See `src/nami_av/README.md` for the command order and the NAMI102
Technical Reference for module-level detail.
