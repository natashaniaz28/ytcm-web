"""
NAMI Web API routes — read-only analysis over an uploaded NAMI corpus.db snapshot.

Scope: v1 is deliberately read-only. Crawling (HikerAPI) and vision-tagging
(Gemini/Qwen) need persistent storage, a GPU, and paid API budget this free-tier
deployment doesn't have, so those stay an offline step (run locally, producing a
corpus.db snapshot that gets uploaded here). This mirrors YTCM's own
Comments.json upload -> in-memory session -> analyze -> download flow.

Vendored NAMI analysis code lives in nami_code/ (copied from NAMI/NAMI/src/nami_code,
analysis-only modules — crawl/vision/diagnostics excluded). Default schema/domain/
project config lives in nami_config/ (copied from NAMI/NAMI/config).
"""
import asyncio
import base64
import logging
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

BACKEND_DIR = Path(__file__).parent.resolve()
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from nami_code.analysis import analyse as A
from nami_code.analysis import namiscope, namitalk, namigraph, namiviz
from nami_code.reports import report as nami_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nami", tags=["nami"])

# Same ephemeral-storage convention as main.py: Render's disk resets on restart,
# so uploaded corpora live in /tmp there and next to the code locally.
IS_CLOUD = os.environ.get("RENDER", "") != ""
WORK_DIR = Path(tempfile.gettempdir()) if IS_CLOUD else BACKEND_DIR

NAMI_CONFIG_DIR = BACKEND_DIR / "nami_config"
SCHEMA_PATH = str(NAMI_CONFIG_DIR / "schema.yaml")
DOMAIN_PATH = str(NAMI_CONFIG_DIR / "domain.yaml")
PROJECT_PATH = str(NAMI_CONFIG_DIR / "project.yaml")

# session_id -> uploaded corpus.db path
nami_sessions: Dict[str, Path] = {}
# job_id -> job state, for the (slow) full-report build
nami_jobs: Dict[str, Dict[str, Any]] = {}


class _NamiConnectionManager:
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


manager = _NamiConnectionManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_db_path(session_id: str) -> str:
    path = nami_sessions.get(session_id)
    if not path or not path.exists():
        raise HTTPException(
            status_code=404,
            detail="No NAMI corpus loaded for this session. Upload a corpus.db first.",
        )
    return str(path)


def _quote_ident(name: str) -> str:
    """Safely quote a SQLite identifier (table name) coming from sqlite_master."""
    return '"' + name.replace('"', '""') + '"'


def _records(df) -> list:
    """Pandas DataFrame -> plain JSON-serializable records, same pattern main.py already uses."""
    if df is None or df.empty:
        return []
    return df.to_dict(orient="records")


def _png_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _load_schema():
    return A.load_schema(SCHEMA_PATH)


# ---------------------------------------------------------------------------
# Upload / status
# ---------------------------------------------------------------------------
@router.post("/upload")
async def upload_corpus(file: UploadFile = File(...)):
    """Upload a NAMI corpus.db snapshot. Returns a session_id for all subsequent calls."""
    content = await file.read()
    session_id = str(uuid.uuid4())[:8]
    dest = WORK_DIR / f"nami_{session_id}.db"
    dest.write_bytes(content)

    try:
        conn = sqlite3.connect(str(dest))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "reels" not in tables:
            conn.close()
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Not a NAMI corpus: missing a 'reels' table.")
        n_songs = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] if "songs" in tables else 0
        n_reels = conn.execute("SELECT COUNT(*) FROM reels").fetchone()[0]
        n_tagged = 0
        if "vision_state" in tables:
            n_tagged = conn.execute(
                "SELECT COUNT(*) FROM vision_state WHERE status='done'"
            ).fetchone()[0]
        conn.close()
    except sqlite3.DatabaseError:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Not a valid SQLite database.")

    nami_sessions[session_id] = dest
    tagged_pct = round(100 * n_tagged / n_reels, 1) if n_reels else 0.0
    return {
        "session_id": session_id,
        "songs": n_songs,
        "reels": n_reels,
        "tagged_pct": tagged_pct,
        "message": f"Loaded {n_reels} reels across {n_songs} songs.",
    }


@router.get("/status")
def status(session_id: str):
    db_path = _get_db_path(session_id)
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    counts = {}
    for t in tables:
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {_quote_ident(t)}").fetchone()[0]
        except sqlite3.DatabaseError:
            continue
    vision_status = {}
    if "vision_state" in tables:
        for status_val, n in conn.execute("SELECT status, COUNT(*) FROM vision_state GROUP BY status"):
            vision_status[status_val] = n
    conn.close()
    return {"tables": counts, "vision_status": vision_status}


# ---------------------------------------------------------------------------
# Analyse (classifiability, distributions, song profile)
# ---------------------------------------------------------------------------
@router.get("/analyse")
def analyse(session_id: str):
    db_path = _get_db_path(session_id)
    try:
        schema = _load_schema()
        df = A.load_reels(db_path)
        df = A.classify(df, schema, sources=["keyword"], db_path=db_path)
        dims = A.schema_dimensions(schema)

        classifiability = [A.classifiable_rate(df, schema, dim) for dim in dims]
        distributions = {dim: _records(A.distribution_classifiable(df, dim, schema)) for dim in dims}
        song_profiles = {dim: _records(A.song_profile(df, dim, schema).reset_index()) for dim in dims}
        overview = _records(A.summary(df))

        return {
            "dimensions": dims,
            "n_reels": len(df),
            "n_songs": int(df["song_id"].nunique()) if "song_id" in df else 0,
            "classifiability": classifiability,
            "distributions": distributions,
            "song_profiles": song_profiles,
            "overview": overview,
        }
    except Exception as e:
        logger.error(f"nami analyse failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Scope (timeline / dist / topreels / impact)
# ---------------------------------------------------------------------------
@router.get("/scope/timeline")
def scope_timeline(session_id: str, entity: str = "songs", freq: str = "M"):
    db_path = _get_db_path(session_id)
    try:
        df = namiscope.load_scope_dataframe(db_path)
        out = namiscope.make_timeline(df, entity, freq)
        return {"rows": _records(out)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"nami scope timeline failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scope/dist")
def scope_dist(session_id: str, field: str = "plays"):
    db_path = _get_db_path(session_id)
    try:
        df = namiscope.load_scope_dataframe(db_path)
        out = namiscope.describe_distribution(df, field)
        return {"rows": _records(out)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"nami scope dist failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scope/topreels")
def scope_topreels(session_id: str, field: str = "plays", n: int = 20):
    db_path = _get_db_path(session_id)
    try:
        df = namiscope.load_scope_dataframe(db_path)
        out = namiscope.top_reels(df, field, n)
        return {"rows": _records(out)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"nami scope topreels failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scope/impact")
def scope_impact(session_id: str, by: str = "song"):
    db_path = _get_db_path(session_id)
    try:
        df = namiscope.load_scope_dataframe(db_path)
        out = namiscope.impact_summary(df, by)
        return {"rows": _records(out)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"nami scope impact failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Talk (caption / hashtag terms)
# ---------------------------------------------------------------------------
@router.get("/talk/captionterms")
def talk_captionterms(session_id: str, top: int = 50):
    db_path = _get_db_path(session_id)
    try:
        df = namitalk.load_caption_dataframe(db_path)
        out = namitalk.extract_caption_terms(df, top=top)
        return {"rows": _records(out)}
    except Exception as e:
        logger.error(f"nami talk captionterms failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/talk/hashtagterms")
def talk_hashtagterms(session_id: str, top: int = 50):
    db_path = _get_db_path(session_id)
    try:
        df = namitalk.load_caption_dataframe(db_path)
        out = namitalk.extract_hashtag_terms(df, top=top)
        return {"rows": _records(out)}
    except Exception as e:
        logger.error(f"nami talk hashtagterms failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/talk/distinctiveterms")
def talk_distinctiveterms(session_id: str, by: str = "song", source: str = "hashtags", top: int = 30):
    db_path = _get_db_path(session_id)
    try:
        df = namitalk.load_caption_dataframe(db_path)
        out = namitalk.distinctive_terms(df, by=by, source=source, top=top)
        return {"rows": _records(out)}
    except Exception as e:
        logger.error(f"nami talk distinctiveterms failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Graphs (hashtag / creator-song / creator-asset / song-hashtag)
# ---------------------------------------------------------------------------
_GRAPH_BUILDERS = {
    "hashtags": namigraph.build_hashtag_cooccurrence,
    "creator_song": namigraph.build_creator_song_graph,
    "creator_asset": namigraph.build_creator_asset_graph,
    "song_hashtag": namigraph.build_song_hashtag_graph,
}


@router.get("/graphs/{graph_type}")
def graph_export(graph_type: str, session_id: str, min_weight: int = 1, top: int = 40):
    if graph_type not in _GRAPH_BUILDERS:
        raise HTTPException(status_code=400, detail=f"Unknown graph type: {graph_type}")
    db_path = _get_db_path(session_id)
    try:
        records = namigraph.load_graph_records(db_path)
        nodes, edges = _GRAPH_BUILDERS[graph_type](records, min_weight=min_weight)

        out_dir = WORK_DIR / f"nami_graphs_{session_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = out_dir / graph_type
        namigraph.write_edges_csv(f"{prefix}_edges.csv", edges)
        namigraph.write_nodes_csv(f"{prefix}_nodes.csv", nodes)
        gexf_available = namigraph.networkx_available()
        if gexf_available:
            namigraph.write_gexf(f"{prefix}.gexf", nodes, edges)

        chart = None
        if namiviz.matplotlib_available() and edges:
            chart_path = out_dir / f"{graph_type}_chart.png"
            namiviz.plot_graph_edges(f"{prefix}_edges.csv", chart_path, top=top)
            chart = _png_data_uri(chart_path)

        return {
            "graph_type": graph_type,
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "nodes": nodes[:top],
            "edges": edges[:top],
            "chart": chart,
            "gexf_available": gexf_available,
        }
    except Exception as e:
        logger.error(f"nami graph export ({graph_type}) failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graphs/{graph_type}/download/{fmt}")
def graph_download(graph_type: str, fmt: str, session_id: str):
    if graph_type not in _GRAPH_BUILDERS:
        raise HTTPException(status_code=400, detail=f"Unknown graph type: {graph_type}")
    if fmt not in ("edges.csv", "nodes.csv", "gexf"):
        raise HTTPException(status_code=400, detail="fmt must be one of: edges.csv, nodes.csv, gexf")
    out_dir = WORK_DIR / f"nami_graphs_{session_id}"
    filename = f"{graph_type}.gexf" if fmt == "gexf" else f"{graph_type}_{fmt}"
    path = out_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Graph not built yet. Call /graphs/{graph_type} first.")
    return FileResponse(path=str(path), filename=path.name)


# ---------------------------------------------------------------------------
# Full report (slow — background job + WebSocket progress, like /api/quickreport)
# ---------------------------------------------------------------------------
@router.post("/report")
async def build_report(session_id: str, background_tasks: BackgroundTasks):
    db_path = _get_db_path(session_id)
    job_id = str(uuid.uuid4())
    nami_jobs[job_id] = {"status": "pending", "result": None, "error": None}

    async def run():
        try:
            nami_jobs[job_id]["status"] = "running"
            await manager.send(job_id, {"status": "running", "message": "Building NAMI report…"})

            out_dir = WORK_DIR / f"nami_report_{session_id}"
            cfg = nami_report.ReportConfig(
                db_path=db_path,
                schema_path=SCHEMA_PATH,
                domain_path=DOMAIN_PATH,
                project_path=PROJECT_PATH,
                out_dir=str(out_dir),
            )
            report_path = nami_report.build(cfg)

            nami_jobs[job_id].update({
                "status": "done",
                "result": {"session_id": session_id, "report_file": Path(report_path).name},
            })
            await manager.send(job_id, {
                "status": "done", "session_id": session_id,
                "report_file": Path(report_path).name,
                "message": "Report ready.",
            })
        except Exception as e:
            logger.error(f"nami report job {job_id} failed: {e}")
            nami_jobs[job_id].update({"status": "error", "error": str(e)})
            await manager.send(job_id, {"status": "error", "error": str(e)})

    background_tasks.add_task(run)
    return {"job_id": job_id}


@router.get("/report/jobs/{job_id}")
def report_job_status(job_id: str):
    if job_id not in nami_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return nami_jobs[job_id]


@router.websocket("/ws/report/{job_id}")
async def report_job_websocket(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    TERMINAL = {"done", "error"}
    try:
        current = nami_jobs.get(job_id)
        if current:
            await websocket.send_json(current)
            if current.get("status") in TERMINAL:
                return
        while True:
            await asyncio.sleep(0.5)
            current = nami_jobs.get(job_id)
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
        logger.warning(f"NAMI WebSocket error for job {job_id}: {e}")
    finally:
        manager.disconnect(job_id)


@router.get("/report/file")
def report_file(session_id: str):
    out_dir = WORK_DIR / f"nami_report_{session_id}"
    path = out_dir / "report.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not built yet.")
    return FileResponse(path=str(path), filename="nami_report.html", media_type="text/html")
