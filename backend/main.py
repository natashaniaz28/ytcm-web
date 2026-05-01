"""
YTCM Web API — FastAPI backend
Cloud-ready version: works on Render (ephemeral filesystem) and locally.

Key differences from local-only version:
- API key comes from environment variable YOUTUBE_API_KEY (not a file)
- File-based routes also accept file upload or an in-memory session store
- CORS is env-driven so Vercel frontend URL can be set at deploy time
- /tmp is used for any transient file writes on cloud
"""

import asyncio, base64, io, json, logging, os, sys, uuid, tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

# Suppress noisy Google API discovery cache warning
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BACKEND_DIR))

# On Render the filesystem is ephemeral — use /tmp for any writes
# Locally BACKEND_DIR is fine and persistent
IS_CLOUD = os.environ.get("RENDER", "") != ""
WORK_DIR = Path(tempfile.gettempdir()) if IS_CLOUD else BACKEND_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
jobs: Dict[str, Dict[str, Any]] = {}

# Session data store: maps session_id → parsed JSON data dict
# Used on cloud where there is no persistent Comments.json
session_data: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# WebSocket manager
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, WebSocket] = {}

    async def connect(self, job_id: str, ws: WebSocket):
        await ws.accept()
        self.active[job_id] = ws

    def disconnect(self, job_id: str):
        self.active.pop(job_id, None)

    async def send(self, job_id: str, data: dict):
        ws = self.active.get(job_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(job_id)

manager = ConnectionManager()


# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"YTCM API starting — cloud={IS_CLOUD}, work_dir={WORK_DIR}")
    yield

app = FastAPI(title="YTCM Web API", version="1.0.0", lifespan=lifespan)

# CORS: allow the Vercel frontend URL (set via env) plus localhost for dev
_frontend_url = os.environ.get("FRONTEND_URL", "")
_origins = ["http://localhost:5173", "http://localhost:3000"]
if _frontend_url:
    _origins.append(_frontend_url)
    _origins.append(_frontend_url.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins + ["*"],   # "*" ensures it works while you set things up
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class APIKeyConfig(BaseModel):
    api_key: str

class SearchConfig(BaseModel):
    primary_terms: List[List[str]]
    secondary_terms: List[str] = []
    excluded_terms: List[str] = []
    search_year: int

class DownloadConfig(BaseModel):
    video_ids: List[str]
    session_id: str = "default"

class EnrichConfig(BaseModel):
    force_rebuild: bool = False
    session_id: str = "default"

class FilterConfig(BaseModel):
    terms: List[str]
    mode: str = "and"
    session_id: str = "default"

class ExportConfig(BaseModel):
    format: str = "all"
    session_id: str = "default"

class WordcloudConfig(BaseModel):
    session_id: str = "default"
    ngram_min: int = 1
    ngram_max: int = 2
    extra_stopwords: List[str] = []
    min_df: int = 2
    max_df: float = 0.95

class TopicsConfig(BaseModel):
    session_id: str = "default"
    n_topics: int = 6
    n_words: int = 10
    min_df: int = 5
    max_df: float = 0.6
    ngram_min: int = 1
    ngram_max: int = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """
    API key priority:
    1. Environment variable YOUTUBE_API_KEY  (Render / cloud)
    2. File YOUTUBE.API in BACKEND_DIR       (local dev)
    """
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if key:
        return key
    key_file = BACKEND_DIR / "YOUTUBE.API"
    if key_file.exists():
        return key_file.read_text().strip()
    return ""


def get_session_data(session_id: str) -> dict:
    """Return data for a session, or raise 404."""
    # Try in-memory session store first
    if session_id in session_data:
        return session_data[session_id]
    # Fall back to Comments.json on disk (local dev convenience)
    local = BACKEND_DIR / "Comments.json"
    if local.exists():
        with open(local, "r", encoding="utf-8") as f:
            data = json.load(f)
        session_data[session_id] = data
        return data
    raise HTTPException(status_code=404, detail="No data found. Upload a Comments.json file first.")


def save_session_data(session_id: str, data: dict):
    session_data[session_id] = data
    # Also write to disk locally so it persists across restarts in dev
    if not IS_CLOUD:
        out = BACKEND_DIR / "Comments.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def fig_to_base64(fig=None) -> str:
    if fig is None:
        fig = plt.gcf()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close("all")
    return f"data:image/png;base64,{encoded}"


def capture_plots(func, *args, **kwargs):
    captured = []
    original_show = plt.show

    def mock_show(*a, **kw):
        for fig_num in plt.get_fignums():
            fig = plt.figure(fig_num)
            captured.append(fig_to_base64(fig))
        plt.close("all")

    plt.show = mock_show
    try:
        # ✅ CALL THE FUNCTION
        func(*args, **kwargs)

        # ✅ also capture if function didn't call plt.show()
        for fig_num in plt.get_fignums():
            fig = plt.figure(fig_num)
            captured.append(fig_to_base64(fig))

        plt.close("all")
    finally:
        plt.show = original_show

    return captured


def check_modules() -> bool:
    try:
        import YTCM_config
        import YTCM_tubescope
        import YTCM_tubetalk
        import YTCM_tubegraph
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "cloud": IS_CLOUD,
        "ytcm_modules": check_modules(),
        "api_key_set": bool(get_api_key()),
        "sessions": len(session_data),
        "jobs": len(jobs),
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@app.get("/api/config")
def get_config():
    try:
        import YTCM_config as cfg
        return {
            "primary_terms": cfg.PRIMARY_SEARCH_TERMS,
            "secondary_terms": cfg.SECONDARY_SEARCH_TERMS,
            "excluded_terms": cfg.EXCLUDED_TERMS,
            "search_year": cfg.SEARCH_YEAR,
            "version_date": cfg.VERSION_DATE,
            "cloud_mode": IS_CLOUD,
        }
    except ImportError:
        return {"cloud_mode": IS_CLOUD}


@app.get("/api/config/apikey")
def check_api_key():
    return {"exists": bool(get_api_key())}


@app.post("/api/config/apikey")
def save_api_key(config: APIKeyConfig):
    """
    On cloud: just store in env-like memory (lasts for this process only).
    On local: write to YOUTUBE.API file.
    """
    if IS_CLOUD:
        os.environ["YOUTUBE_API_KEY"] = config.api_key.strip()
        return {"status": "saved_in_memory", "note": "On Render, set YOUTUBE_API_KEY as an environment variable in the dashboard for persistence."}
    key_path = BACKEND_DIR / "YOUTUBE.API"
    key_path.write_text(config.api_key.strip())
    return {"status": "saved", "file": str(key_path)}


# ---------------------------------------------------------------------------
# Data / Upload
# ---------------------------------------------------------------------------
@app.post("/api/data/upload")
async def upload_data(file: UploadFile = File(...)):
    """
    Upload a Comments.json file. Returns a session_id to use in all subsequent calls.
    This is the primary way to load data on cloud deployments.
    """
    try:
        content = await file.read()
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("File must be a JSON object (dict of video IDs)")
        session_id = str(uuid.uuid4())[:8]
        session_data[session_id] = data
        total_comments = sum(len(v.get("comments", [])) for v in data.values())
        return {
            "session_id": session_id,
            "total_videos": len(data),
            "total_comments": total_comments,
            "message": f"Loaded {len(data)} videos with {total_comments} comments.",
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/data/sessions")
def list_sessions():
    result = []
    for sid, data in session_data.items():
        total_comments = sum(len(v.get("comments", [])) for v in data.values())
        result.append({"session_id": sid, "videos": len(data), "comments": total_comments})
    # Also check for local Comments.json
    local = BACKEND_DIR / "Comments.json"
    if local.exists() and "default" not in session_data:
        result.append({"session_id": "default", "source": "Comments.json (local disk)"})
    return {"sessions": result}


@app.get("/api/data/stats")
def get_stats(session_id: str = "default"):
    data = get_session_data(session_id)
    try:
        from YTCM_tubetalk import count_comments, count_languages, load_existing_comments
        counts = count_comments(data)
        langs = count_languages(data)
        return {
            "counts": counts,
            "languages": {
                "video":   dict(langs["video"].most_common(10)),
                "comment": dict(langs["comment"].most_common(10)),
                "reply":   dict(langs["reply"].most_common(10)),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/preview")
def preview_data(session_id: str = "default", limit: int = 5):
    data = get_session_data(session_id)
    preview = []
    for i, (vid_id, vid_data) in enumerate(data.items()):
        if i >= limit:
            break
        info = vid_data.get("video_info", {})
        preview.append({
            "video_id":      vid_id,
            "title":         info.get("title", ""),
            "channel":       info.get("channel_name", ""),
            "published_at":  info.get("published_at", ""),
            "views":         info.get("views", 0),
            "comment_count": len(vid_data.get("comments", [])),
        })
    return {"videos": preview, "total": len(data)}


@app.get("/api/data/download")
def download_session_json(session_id: str = "default"):
    """Let the user download their (enriched) data as a JSON file."""
    data = get_session_data(session_id)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=Comments_{session_id}.json"},
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@app.post("/api/search")
async def search_videos(config: SearchConfig, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "result": None, "error": None}

    async def run():
        try:
            jobs[job_id]["status"] = "running"
            await manager.send(job_id, {"status": "running", "message": "Connecting to YouTube API..."})

            api_key = get_api_key()
            if not api_key:
                raise ValueError("No YouTube API key configured. Set YOUTUBE_API_KEY in Render environment variables.")

            from YTCM_api_utils import init_youtube_service, get_video_ids
            from YTCM_processing_utils import generate_search_list
            import YTCM_config as cfg

            youtube = init_youtube_service(api_key)
            search_terms = generate_search_list(config.primary_terms, config.secondary_terms)

            await manager.send(job_id, {"status": "running", "message": f"Searching {len(search_terms)} term combination(s)…"})

            video_ids = get_video_ids(
                search_terms, youtube,
                part="snippet",
                maxResults=cfg.MAX_RESULTS,
                year=config.search_year,
                excluded_terms=config.excluded_terms,
            ) or []

            jobs[job_id].update({"status": "done", "video_ids": video_ids, "count": len(video_ids),
                                  "result": {"video_ids": video_ids, "count": len(video_ids)}})
            await manager.send(job_id, {"status": "done", "video_ids": video_ids,
                                         "count": len(video_ids), "message": f"Found {len(video_ids)} video ID(s)"})
        except Exception as e:
            logger.error(f"Search job {job_id} failed: {e}")
            jobs[job_id].update({"status": "error", "error": str(e)})
            await manager.send(job_id, {"status": "error", "error": str(e)})

    background_tasks.add_task(run)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
@app.post("/api/download")
async def download_comments(config: DownloadConfig, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "progress": 0, "total": len(config.video_ids), "result": None, "error": None}

    async def run():
        try:
            jobs[job_id]["status"] = "running"
            await manager.send(job_id, {"status": "running", "progress": 0, "total": len(config.video_ids)})

            api_key = get_api_key()
            if not api_key:
                raise ValueError("No YouTube API key configured.")

            from YTCM_api_utils import init_youtube_service, get_video_information
            from YTCM_comments_utils import get_comments
            import YTCM_config as cfg

            youtube = init_youtube_service(api_key)
            # Load any existing data for this session so we can append
            try:
                all_comments = get_session_data(config.session_id)
            except HTTPException:
                all_comments = {}

            total = len(config.video_ids)
            for idx, video_id in enumerate(config.video_ids, 1):
                await manager.send(job_id, {
                    "status": "running", "progress": idx - 1, "total": total,
                    "current_video": video_id, "message": f"Processing {idx}/{total}: {video_id}"
                })
                try:
                    video_info = get_video_information(youtube, video_id)
                    if not video_info:
                        continue
                    comments, quota_exceeded = get_comments(
                        youtube, part="snippet", videoId=video_id,
                        maxResults=cfg.MAX_RESULTS, textFormat="plainText"
                    )
                    if quota_exceeded:
                        jobs[job_id].update({"status": "quota_exceeded",
                                              "error": "API quota exceeded. Resume tomorrow."})
                        await manager.send(job_id, {"status": "quota_exceeded",
                                                     "message": "API quota exceeded. Partial data saved."})
                        save_session_data(config.session_id, all_comments)
                        return
                    all_comments[video_id] = {"video_info": video_info, "comments": comments or []}
                    jobs[job_id]["progress"] = idx
                except Exception as e:
                    logger.error(f"Error processing {video_id}: {e}")
                    continue

            save_session_data(config.session_id, all_comments)
            jobs[job_id].update({
                "status": "done",
                "result": {"session_id": config.session_id, "processed": total, "total_videos": len(all_comments)},
            })
            await manager.send(job_id, {
                "status": "done", "progress": total, "total": total,
                "session_id": config.session_id,
                "message": f"Done. {total} videos downloaded into session '{config.session_id}'."
            })
        except Exception as e:
            jobs[job_id].update({"status": "error", "error": str(e)})
            await manager.send(job_id, {"status": "error", "error": str(e)})

    background_tasks.add_task(run)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Job status + WebSocket
# ---------------------------------------------------------------------------
@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.websocket("/ws/jobs/{job_id}")
async def job_websocket(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    TERMINAL = {"done", "error", "quota_exceeded"}
    try:
        current = jobs.get(job_id)
        if current:
            await websocket.send_json(current)
            if current.get("status") in TERMINAL:
                return
        while True:
            await asyncio.sleep(0.5)
            current = jobs.get(job_id)
            if current is None:
                break
            if current.get("status") in TERMINAL:
                try:
                    await websocket.send_json(current)
                except Exception:
                    pass
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket error for job {job_id}: {e}")
    finally:
        manager.disconnect(job_id)


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------
@app.post("/api/enrich/language")
async def run_language(config: EnrichConfig, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "result": None, "error": None}

    async def run():
        try:
            jobs[job_id]["status"] = "running"
            await manager.send(job_id, {"status": "running", "message": "Detecting languages…"})
            data = get_session_data(config.session_id)

            from YTCM_data_enrichment_utils import detect_language
            from tqdm import tqdm

            for vid_id, vid_data in data.items():
                info = vid_data.get("video_info", {})
                for field in ("title", "description"):
                    lk = f"{field}_language"
                    if config.force_rebuild or lk not in info:
                        info[lk] = detect_language(info.get(field, "") or "")
                for comment in vid_data.get("comments", []):
                    if config.force_rebuild or "language" not in comment:
                        comment["language"] = detect_language(comment.get("text", "") or "")
                    for reply in comment.get("replies", []):
                        if config.force_rebuild or "language" not in reply:
                            reply["language"] = detect_language(reply.get("text", "") or "")

            save_session_data(config.session_id, data)
            jobs[job_id].update({"status": "done", "result": {"message": "Language detection complete"}})
            await manager.send(job_id, {"status": "done", "message": "Language detection complete"})
        except Exception as e:
            jobs[job_id].update({"status": "error", "error": str(e)})
            await manager.send(job_id, {"status": "error", "error": str(e)})

    background_tasks.add_task(run)
    return {"job_id": job_id}


@app.post("/api/enrich/sentiment")
async def run_sentiment(config: EnrichConfig, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "result": None, "error": None}

    async def run():
        try:
            jobs[job_id]["status"] = "running"
            await manager.send(job_id, {"status": "running", "message": "Running sentiment analysis…"})
            data = get_session_data(config.session_id)

            from YTCM_data_enrichment_utils import blob_analysis, vader_analysis

            for vid_data in data.values():
                for comment in vid_data.get("comments", []):
                    if comment.get("language") == "en" and comment.get("text"):
                        if config.force_rebuild or "vader_sentiment" not in comment:
                            try:
                                comment["blob_sentiment"]  = blob_analysis(comment["text"])
                                comment["vader_sentiment"] = vader_analysis(comment["text"])
                            except Exception:
                                comment["blob_sentiment"] = comment["vader_sentiment"] = "N/A"
                    for reply in comment.get("replies", []):
                        if reply.get("language") == "en" and reply.get("text"):
                            if config.force_rebuild or "vader_sentiment" not in reply:
                                try:
                                    reply["blob_sentiment"]  = blob_analysis(reply["text"])
                                    reply["vader_sentiment"] = vader_analysis(reply["text"])
                                except Exception:
                                    reply["blob_sentiment"] = reply["vader_sentiment"] = "N/A"

            save_session_data(config.session_id, data)
            jobs[job_id].update({"status": "done", "result": {"message": "Sentiment analysis complete"}})
            await manager.send(job_id, {"status": "done", "message": "Sentiment analysis complete"})
        except Exception as e:
            jobs[job_id].update({"status": "error", "error": str(e)})
            await manager.send(job_id, {"status": "error", "error": str(e)})

    background_tasks.add_task(run)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@app.post("/api/export")
async def export_data(config: ExportConfig):
    data = get_session_data(config.session_id)
    try:
        from YTCM_export_utils import convert_json_to_csv, convert_json_to_gephi, convert_json_to_html
        fmt = config.format.lower()
        results = {}
        tmp = WORK_DIR

        # Write to tmp JSON first (some exporters need a file path)
        tmp_json = str(tmp / f"export_{config.session_id}.json")
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if fmt in ("csv", "all"):
            out = str(tmp / f"Comments_{config.session_id}.csv")
            convert_json_to_csv(tmp_json, out)
            results["csv"] = f"Comments_{config.session_id}.csv"

        if fmt in ("html", "all"):
            out = str(tmp / f"Comments_{config.session_id}.html")
            convert_json_to_html(tmp_json, out)
            results["html"] = f"Comments_{config.session_id}.html"

        if fmt in ("gephi", "all"):
            out_on  = str(tmp / f"Comments_{config.session_id}_replies.gexf")
            out_off = str(tmp / f"Comments_{config.session_id}.gexf")
            convert_json_to_gephi(tmp_json, out_on,  include_replies=True)
            convert_json_to_gephi(tmp_json, out_off, include_replies=False)
            results["gephi_with_replies"] = f"Comments_{config.session_id}_replies.gexf"
            results["gephi_no_replies"]   = f"Comments_{config.session_id}.gexf"

        return {"status": "done", "files": results, "session_id": config.session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export/download/{filename}")
def download_export_file(filename: str):
    # Security: no path traversal
    safe_name = Path(filename).name
    path = WORK_DIR / safe_name
    if not path.exists():
        # Also check BACKEND_DIR for local mode
        path = BACKEND_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(path), filename=safe_name)


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------
@app.post("/api/filter")
def filter_comments(config: FilterConfig):
    data = get_session_data(config.session_id)
    try:
        from YTCM_filter_utils import filter_data
        result = filter_data(data, config.terms, config.mode)
        summary = [
            {"video_id": vid, "title": vd.get("video_info", {}).get("title", ""),
             "comment_count": len(vd.get("comments", []))}
            for vid, vd in result.items()
        ]
        return {"matched_videos": len(result), "videos": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# TubeScope
# ---------------------------------------------------------------------------
def _scope_all_comments(session_id):
    from YTCM_tubescope import analyze_comments
    data = get_session_data(session_id)
    return analyze_comments([c for vd in data.values() for c in vd.get("comments", [])]), data


@app.get("/api/tubescope/summary")
def scope_summary(session_id: str = "default"):
    try:
        from YTCM_tubescope import calculate_average_sentiment, analyze_replies
        df, data = _scope_all_comments(session_id)
        return {
            "total_videos":       len(data),
            "total_comments":     len(df),
            "average_sentiment":  round(float(calculate_average_sentiment(df)), 3),
            "reply_percentage":   round(float(analyze_replies(df)), 2),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tubescope/activity")
def scope_activity(session_id: str = "default"):
    try:
        from YTCM_tubescope import group_comments_by_date, plot_comments_over_time
        df, _ = _scope_all_comments(session_id)
        return {"images": capture_plots(plot_comments_over_time, group_comments_by_date(df))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tubescope/sentiment")
def scope_sentiment(session_id: str = "default"):
    try:
        from YTCM_tubescope import (analyze_sentiment_over_time, plot_sentiment_over_time,
                                     plot_sentiment_distribution, calculate_average_sentiment)
        df, _ = _scope_all_comments(session_id)
        imgs  = capture_plots(plot_sentiment_over_time, analyze_sentiment_over_time(df))
        imgs += capture_plots(plot_sentiment_distribution, df)
        return {"images": imgs, "average_sentiment": round(float(calculate_average_sentiment(df)), 3)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tubescope/likes")
def scope_likes(session_id: str = "default"):
    try:
        from YTCM_tubescope import plot_comment_likes_distribution
        df, _ = _scope_all_comments(session_id)
        return {"images": capture_plots(plot_comment_likes_distribution, df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tubescope/weekdays")
def scope_weekdays(session_id: str = "default"):
    try:
        from YTCM_tubescope import plot_interactions_by_weekday
        _, data = _scope_all_comments(session_id)
        return {"images": capture_plots(plot_interactions_by_weekday, data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tubescope/views")
def scope_views(session_id: str = "default"):
    try:
        from YTCM_tubescope import plot_views_vs_comments, analyze_views_static
        _, data = _scope_all_comments(session_id)
        imgs  = capture_plots(plot_views_vs_comments, data)
        imgs += capture_plots(analyze_views_static, data)
        return {"images": imgs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tubescope/uploads")
def scope_uploads(session_id: str = "default"):
    try:
        from YTCM_tubescope import plot_uploads_over_time
        _, data = _scope_all_comments(session_id)
        return {"images": capture_plots(plot_uploads_over_time, data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tubescope/channels")
def scope_channels(session_id: str = "default"):
    try:
        from YTCM_tubescope import plot_participation_timeline
        _, data = _scope_all_comments(session_id)
        return {"images": capture_plots(plot_participation_timeline, data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# TubeTalk
# ---------------------------------------------------------------------------
@app.get("/api/tubetalk/languages")
def talk_languages(session_id: str = "default", level: str = "comment", top_n: int = 20):
    try:
        from YTCM_tubetalk import plot_language_distribution
        data = get_session_data(session_id)
        return {"images": capture_plots(plot_language_distribution, data, level=level, top_n=top_n, normalize=False)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tubetalk/langconflicts")
def talk_lang_conflicts(session_id: str = "default"):
    try:
        from YTCM_tubetalk import plot_language_conflicts
        data = get_session_data(session_id)
        return {"images": capture_plots(plot_language_conflicts, data, top_n=20, normalize=True)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tubetalk/wordcloud")
async def talk_wordcloud(config: WordcloudConfig, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "result": None, "error": None}

    async def run():
        try:
            jobs[job_id]["status"] = "running"
            await manager.send(job_id, {"status": "running", "message": "Building word cloud…"})
            from YTCM_tubetalk import run_wordcloud
            data = get_session_data(config.session_id)
            images = capture_plots(run_wordcloud, data,
                ngram_range=(config.ngram_min, config.ngram_max),
                extra_stopwords=config.extra_stopwords or None,
                min_df=config.min_df, max_df=config.max_df)
            jobs[job_id].update({"status": "done", "result": {"images": images}})
            await manager.send(job_id, {"status": "done", "images": images})
        except Exception as e:
            jobs[job_id].update({"status": "error", "error": str(e)})
            await manager.send(job_id, {"status": "error", "error": str(e)})

    background_tasks.add_task(run)
    return {"job_id": job_id}


@app.post("/api/tubetalk/topics")
async def talk_topics(config: TopicsConfig, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "result": None, "error": None}

    async def run():
        try:
            jobs[job_id]["status"] = "running"
            await manager.send(job_id, {"status": "running", "message": "Running LDA topic modeling…"})
            from YTCM_tubetalk import run_topics
            data = get_session_data(config.session_id)
            images = capture_plots(run_topics, data,
                n_topics=config.n_topics, n_words=config.n_words,
                min_df=config.min_df, max_df=config.max_df,
                ngram_range=(config.ngram_min, config.ngram_max))
            jobs[job_id].update({"status": "done", "result": {"images": images}})
            await manager.send(job_id, {"status": "done", "images": images})
        except Exception as e:
            jobs[job_id].update({"status": "error", "error": str(e)})
            await manager.send(job_id, {"status": "error", "error": str(e)})

    background_tasks.add_task(run)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# TubeGraph
# ---------------------------------------------------------------------------
@app.get("/api/tubegraph/channelstats")
def graph_channel_stats(session_id: str = "default", top_n: int = 15):
    try:
        from YTCM_tubegraph import channel_occurrence_stats, plot_top_channels
        data = get_session_data(session_id)
        df   = channel_occurrence_stats(data)
        imgs = []
        for role in ["uploader", "commenter", "replier", "total"]:
            imgs += capture_plots(plot_top_channels, df, role=role, top_n=top_n)
        return {"images": imgs, "top_channels": df.head(top_n).to_dict(orient="records")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tubegraph/network")
async def graph_network(background_tasks: BackgroundTasks, session_id: str = "default", top_n: int = 50):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "result": None, "error": None}

    async def run():
        try:
            jobs[job_id]["status"] = "running"
            await manager.send(job_id, {"status": "running", "message": "Building interaction graph…"})
            from YTCM_tubegraph import build_interaction_graph, plot_network_graph
            data = get_session_data(session_id)
            G    = build_interaction_graph(data)
            imgs = capture_plots(plot_network_graph, G, top_n=top_n)
            jobs[job_id].update({"status": "done",
                "result": {"images": imgs, "nodes": G.number_of_nodes(), "edges": G.number_of_edges()}})
            await manager.send(job_id, {"status": "done", "images": imgs,
                "nodes": G.number_of_nodes(), "edges": G.number_of_edges()})
        except Exception as e:
            jobs[job_id].update({"status": "error", "error": str(e)})
            await manager.send(job_id, {"status": "error", "error": str(e)})

    background_tasks.add_task(run)
    return {"job_id": job_id}


@app.post("/api/tubegraph/replygraph")
async def graph_replies(background_tasks: BackgroundTasks, session_id: str = "default"):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "result": None, "error": None}

    async def run():
        try:
            jobs[job_id]["status"] = "running"
            await manager.send(job_id, {"status": "running", "message": "Building reply graph…"})
            from YTCM_tubegraph import build_reply_network, plot_reply_network
            data = get_session_data(session_id)
            G    = build_reply_network(data, include_self=False, min_weight=1)
            imgs = capture_plots(plot_reply_network, G, top_n=50)
            jobs[job_id].update({"status": "done", "result": {"images": imgs}})
            await manager.send(job_id, {"status": "done", "images": imgs})
        except Exception as e:
            jobs[job_id].update({"status": "error", "error": str(e)})
            await manager.send(job_id, {"status": "error", "error": str(e)})

    background_tasks.add_task(run)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
@app.get("/api/validate")
def validate(session_id: str = "default"):
    try:
        data = get_session_data(session_id)
        return {
            "valid":          True,
            "total_videos":   len(data),
            "total_comments": sum(len(v.get("comments", [])) for v in data.values()),
            "total_replies":  sum(len(c.get("replies", []))
                                  for v in data.values() for c in v.get("comments", [])),
        }
    except HTTPException:
        return {"valid": False, "error": "No data loaded"}
    except Exception as e:
        return {"valid": False, "error": str(e)}

