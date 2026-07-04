from __future__ import annotations
import sqlite3, random
from pathlib import Path
from typing import Protocol

from nami_code.domain_config import (
    load_schema_config,
    load_category_descriptions,
    load_vision_config,
)

IMG_DIR = Path("data/thumbnails")
MEDIA_DIR = Path("data/reels")
SCHEMA_PATH = "config/schema.yaml"
MODEL_NAME = "openai/clip-vit-large-patch14"

ABS_FLOOR = 0.15
REL_FRAC  = 0.40
TOP_K     = 2


def load_vision_prompts(schema: dict) -> dict:
    """
    Return configured vision prompts by dimension and category.

    Categories without ``vision_prompt`` are skipped. This keeps vision tagging
    safe for schemas that only define keyword-based categories. Retained for the
    contrastive CLIP/InternVideo2 backend (VisionModel); reasoning VLM backends use
    domain_config.load_category_descriptions instead.
    """

    prompts: dict[str, dict[str, str]] = {}
    dimensions = schema.get("dimensions", {}) if isinstance(schema, dict) else {}
    if not isinstance(dimensions, dict):
        return prompts

    for dim_id, dim in dimensions.items():
        if not isinstance(dim, dict):
            continue
        categories = dim.get("categories", {})
        if not isinstance(categories, dict):
            continue

        dim_prompts: dict[str, str] = {}
        for cat_id, cat in categories.items():
            if not isinstance(cat, dict):
                continue
            prompt = cat.get("vision_prompt")
            if isinstance(prompt, str) and prompt.strip():
                dim_prompts[str(cat_id)] = prompt.strip()

        if dim_prompts:
            prompts[str(dim_id)] = dim_prompts

    return prompts


def load_schema():
    """
    Load the classification scheme from the project's schema file.
    """
    return load_schema_config(SCHEMA_PATH)


def schema_categories(schema: dict, dim: str) -> set[str]:
    """Valid category ids for a dimension (used to reject hallucinated ids)."""
    dims = schema.get("dimensions", {}) if isinstance(schema, dict) else {}
    return set(dims.get(dim, {}).get("categories", {}))


def local_media(pk):
    """
    Return the best local media reference for a reel, or None.

    Prefers the downloaded MP4 (data/reels/{pk}.mp4) — what a VLM backend wants —
    and falls back to the thumbnail JPG (data/thumbnails/{pk}.jpg) for a
    frame-scoring backend. None means "no media": the reel is flagged ``no_media``.
    """
    mp4 = MEDIA_DIR / f"{pk}.mp4"
    if mp4.exists() and mp4.stat().st_size > 0:
        return str(mp4)
    jpg = IMG_DIR / f"{pk}.jpg"
    if jpg.exists() and jpg.stat().st_size > 0:
        return str(jpg)
    return None


class Backend(Protocol):
    """
    A vision backend maps one reel's media to per-dimension category picks.

    classify(media_ref, schema) -> {dimension_id: [(category_id, confidence), ...]}
    Confidence is a float in [0, 1]; run() clamps it and rejects category ids that
    are not in the schema before writing annotation rows.
    """

    def classify(self, media_ref, schema) -> dict[str, list[tuple[str, float]]]:
        """
        Look at one reel's media and return, for each dimension, the categories it seems to fit with a confidence score.
        """
        ...


class StubModel:
    """
    Offline backend: random but VALID (category, confidence) per dimension.

    Ignores ``media_ref`` (so smoke tests need no real media or model) but is seeded
    by it for deterministic output. Guarantees at least one pick per dimension so
    annotation rows always exist.
    """

    def classify(self, media_ref, schema) -> dict[str, list[tuple[str, float]]]:
        """
        Return random but valid category picks for each dimension. For offline testing; ignores the actual media.
        """
        rng = random.Random(hash(("stub", media_ref)) & 0xFFFFFFFF)
        out: dict[str, list[tuple[str, float]]] = {}
        for dim, cats in load_category_descriptions(schema).items():
            cat_ids = list(cats)
            picks = [
                (c, round(rng.uniform(0.3, 0.95), 3))
                for c in cat_ids
                if rng.random() < 0.5
            ]
            if not picks and cat_ids:
                c = rng.choice(cat_ids)
                picks = [(c, round(rng.uniform(0.3, 0.95), 3))]
            out[dim] = picks
        return out


class VisionModel:
    """
    Legacy contrastive backend (CLIP / InternVideo2 frame scoring).

    Kept for the optional drop-in path. It scores a single frame against the
    per-category ``vision_prompt`` strings and applies choose_tags() (softmax +
    floor/rel/top-k). Reasoning VLM backends do NOT use this.
    """

    def __init__(self, model_name=MODEL_NAME):
        """
        Load the local image model and pick the best available hardware to run it on.
        """
        from transformers import AutoProcessor, AutoModel
        import torch
        self.torch = torch
        self.is_clip = "clip" in model_name.lower()
        self.proc = AutoProcessor.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.model.eval()
        self.device = "cuda" if torch.cuda.is_available() else \
                      ("mps" if torch.backends.mps.is_available() else "cpu")
        self.model.to(self.device)
        print(f"  [Device: {self.device}]")

    def score(self, img_path, prompts):
        """
        Compare one image against the given text prompts and return a similarity score for each.
        """
        from PIL import Image
        cats = list(prompts.keys())
        texts = list(prompts.values())
        img = Image.open(img_path).convert("RGB")
        if self.is_clip:
            inputs = self.proc(text=texts, images=img, return_tensors="pt",
                               padding=True, truncation=True).to(self.device)
        else:
            inputs = self.proc(text=texts, images=img, return_tensors="pt",
                               padding="max_length", max_length=64,
                               truncation=True).to(self.device)
        with self.torch.no_grad():
            logits = self.model(**inputs).logits_per_image[0]
            if self.is_clip:
                probs = self.torch.softmax(logits, dim=-1).cpu().tolist()
            else:
                probs = self.torch.sigmoid(logits).cpu().tolist()
        return {cat: round(float(p), 4) for cat, p in zip(cats, probs)}

    @staticmethod
    def _image_for(media_ref):
        """Resolve a frame image: a jpg/png ref directly, or an mp4's sibling jpg."""
        if not media_ref:
            return None
        p = Path(media_ref)
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            return str(p) if p.exists() else None
        thumb = IMG_DIR / f"{p.stem}.jpg"
        return str(thumb) if thumb.exists() else None

    def classify(self, media_ref, schema) -> dict[str, list[tuple[str, float]]]:
        """
        Score the reel's frame against every category's prompt and keep the strongest matches per dimension.
        """
        img_path = self._image_for(media_ref)
        if not img_path:
            return {}
        prompts_by_dim = load_vision_prompts(schema)
        out: dict[str, list[tuple[str, float]]] = {}
        for dim, prompts in prompts_by_dim.items():
            valid = {c: p for c, p in prompts.items() if c in schema_categories(schema, dim)}
            if not valid:
                continue
            out[dim] = choose_tags(self.score(img_path, valid))
        return out


def _gemini_client():
    """Create a google-genai client from GEMINI_API_KEY (lazy, dotenv-loaded)."""
    import os
    from dotenv import load_dotenv
    from google import genai
    load_dotenv()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Missing GEMINI_API_KEY in environment or .env")
    return genai.Client(api_key=key)


def _build_vlm_prompt(schema: dict, vcfg: dict) -> str:
    """Compose the instruction template with the schema's dimensions + categories.

    Shared by every reasoning-VLM backend (Gemini, Qwen) — the prompt is purely
    schema-derived, not backend-specific.
    """
    try:
        instr = vcfg.get("instruction_template", "").format(
            max_categories_per_dim=vcfg.get("max_categories_per_dim", 2)
        )
    except Exception:
        instr = vcfg.get("instruction_template", "")

    lines = []
    descs = load_category_descriptions(schema)
    dimensions = schema.get("dimensions", {})
    for dim, cats in descs.items():
        label = dimensions.get(dim, {}).get("unknown_label", dim)
        lines.append(f'Dimension "{dim}" ({label}) — choose from:')
        for cat, desc in cats.items():
            lines.append(f"  - {cat}: {desc}")
    return instr.rstrip() + "\n\nCATEGORIES:\n" + "\n".join(lines)


def _describe_empty_response(resp) -> str:
    """Best-effort one-line reason for an empty Gemini response.

    Reads ``finish_reason`` off the first candidate and ``block_reason`` off
    ``prompt_feedback`` (the prompt-level safety verdict). Both accessors are
    defensive: SDK response shapes vary and either may be absent, in which case
    we fall back to "unknown". Purely diagnostic — does not affect stored data.
    """
    parts = []
    try:
        cand = (getattr(resp, "candidates", None) or [None])[0]
        fr = getattr(cand, "finish_reason", None)
        if fr is not None:
            parts.append(f"finish_reason={getattr(fr, 'name', fr)}")
    except Exception:
        pass
    try:
        pf = getattr(resp, "prompt_feedback", None)
        br = getattr(pf, "block_reason", None)
        if br is not None:
            parts.append(f"block_reason={getattr(br, 'name', br)}")
    except Exception:
        pass
    return ", ".join(parts) or "no finish_reason/block_reason"


def _parse_vlm_json(raw: str):
    """Parse a JSON object from a model response, tolerating ``` code fences."""
    import json, re
    if not raw or not str(raw).strip():
        raise ValueError("empty VLM response")
    s = str(raw).strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return json.loads(s)


def _map_vlm_result(data, schema, max_per: int) -> dict[str, list[tuple[str, float]]]:
    """Validate model JSON into {dim: [(cat, conf)]}: reject unknown ids, clamp conf."""
    out: dict[str, list[tuple[str, float]]] = {}
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    for dim, items in data.items():
        valid_cats = schema_categories(schema, dim)
        if not valid_cats or not isinstance(items, list):
            continue
        picks: list[tuple[str, float]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            cat = item.get("category")
            if cat not in valid_cats or cat in seen:
                continue
            try:
                conf = max(0.0, min(1.0, float(item.get("confidence", 1.0))))
            except (TypeError, ValueError):
                conf = 0.0
            picks.append((cat, conf))
            seen.add(cat)
            if len(picks) >= max_per:
                break
        if picks:
            out[dim] = picks
    return out


class GeminiModel:
    """
    Reasoning-VLM backend: send the reel MP4 (with audio) to Gemini and parse a
    strict-JSON multi-label classification back into annotation picks.

    The single network seam is ``_raw_response`` (upload + generate); tests
    monkeypatch it to return a canned JSON string so no network/key is needed.
    """

    def __init__(self, model_name: str, client=None):
        """
        Set up the Gemini backend. The network connection is opened only on first use.
        """
        import threading
        self.model_name = model_name or "gemini-2.5-flash"
        self._client = client
        self._usage_lock = threading.Lock()
        self._usage = {"calls": 0, "prompt": 0, "audio": 0, "output": 0, "thoughts": 0, "total": 0}

    def _client_or_create(self):
        """
        Return the Gemini connection, opening it the first time it is needed.
        """
        if self._client is None:
            self._client = _gemini_client()
        return self._client

    def _record_usage(self, resp):
        """Accumulate token counts from a response's usage_metadata (best-effort)."""
        um = getattr(resp, "usage_metadata", None)
        if um is None:
            return
        prompt = getattr(um, "prompt_token_count", 0) or 0
        output = getattr(um, "candidates_token_count", 0) or 0
        thoughts = getattr(um, "thoughts_token_count", 0) or 0
        total = getattr(um, "total_token_count", 0) or 0
        audio = 0
        for d in (getattr(um, "prompt_tokens_details", None) or []):
            if str(getattr(d, "modality", "")).upper().endswith("AUDIO"):
                audio += getattr(d, "token_count", 0) or 0
        with self._usage_lock:
            self._usage["calls"] += 1
            self._usage["prompt"] += prompt
            self._usage["audio"] += audio
            self._usage["output"] += output
            self._usage["thoughts"] += thoughts
            self._usage["total"] += total

    def usage_summary(self) -> dict:
        """Return a copy of the accumulated token tally."""
        with self._usage_lock:
            return dict(self._usage)

    _INLINE_MAX_BYTES = 18 * 1024 * 1024

    @staticmethod
    def _mime_for(path) -> str:
        p = str(path).lower()
        if p.endswith((".mov", ".m4v")):
            return "video/quicktime"
        if p.endswith(".webm"):
            return "video/webm"
        if p.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if p.endswith(".png"):
            return "image/png"
        return "video/mp4"

    def _raw_response(self, media_path, prompt, media_resolution, fps=None) -> str:
        """Build a media Part (inline if small, else Files API) and request strict JSON. (network)"""
        import os, time
        from google.genai import types
        client = self._client_or_create()

        mime = self._mime_for(media_path)
        is_video = mime.startswith("video")
        vmeta = None
        if fps and float(fps) > 0 and is_video:
            try:
                vmeta = types.VideoMetadata(fps=float(fps))
            except Exception:
                vmeta = None

        try:
            size = os.path.getsize(media_path)
        except OSError:
            size = self._INLINE_MAX_BYTES + 1

        if size <= self._INLINE_MAX_BYTES:
            with open(media_path, "rb") as fh:
                data = fh.read()
            if vmeta is not None:
                media_part = types.Part(inline_data=types.Blob(data=data, mime_type=mime),
                                        video_metadata=vmeta)
            else:
                media_part = types.Part.from_bytes(data=data, mime_type=mime)
        else:
            uploaded = client.files.upload(file=media_path)
            wait_budget = min(600, 120 + (size / (1024 * 1024)) * 3)
            deadline = time.monotonic() + wait_budget
            while str(getattr(uploaded.state, "name", uploaded.state)) == "PROCESSING":
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"Gemini file {uploaded.name} stuck in processing after "
                        f"{int(wait_budget)}s")
                time.sleep(1)
                uploaded = client.files.get(name=uploaded.name)
            if str(getattr(uploaded.state, "name", uploaded.state)) != "ACTIVE":
                raise RuntimeError(f"Gemini file {uploaded.name} failed to process: state={uploaded.state}")
            if vmeta is not None:
                media_part = types.Part(
                    file_data=types.FileData(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
                    video_metadata=vmeta)
            else:
                media_part = uploaded

        cfg_kwargs = {"response_mime_type": "application/json"}
        if str(media_resolution).lower() == "low":
            try:
                cfg_kwargs["media_resolution"] = types.MediaResolution.MEDIA_RESOLUTION_LOW
            except Exception:
                pass
        resp = client.models.generate_content(
            model=self.model_name,
            contents=[media_part, prompt],
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
        self._record_usage(resp)
        try:
            text = resp.text
        except Exception:
            text = None
        if not text or not str(text).strip():
            raise ValueError(f"empty VLM response ({_describe_empty_response(resp)})")
        return text

    def classify(self, media_ref, schema) -> dict[str, list[tuple[str, float]]]:
        """
        Send the reel to Gemini, read back its category choices, and keep only the valid, sensible ones.
        """
        import random, time
        vcfg = load_vision_config(schema)
        prompt = _build_vlm_prompt(schema, vcfg)
        max_per = int(vcfg.get("max_categories_per_dim", 2) or 2)
        attempts = 4
        last_exc = None
        for attempt in range(attempts):
            try:
                raw = self._raw_response(media_ref, prompt, vcfg.get("media_resolution"),
                                         fps=vcfg.get("fps"))
                return _map_vlm_result(_parse_vlm_json(raw), schema, max_per)
            except Exception as exc:
                last_exc = exc
                if attempt == attempts - 1:
                    break
                if _is_dependency_error(exc):
                    break  # missing package — no retry will ever fix it
                transient = _is_transient_error(exc)
                quota = _is_quota_error(exc)
                if not transient and attempt >= 1:
                    break
                if quota and attempt >= 1:
                    break
                if transient:
                    cap = 5.0 if quota else 30.0
                    delay = min(cap, 2.0 * (2 ** attempt)) * (0.5 + random.random())
                    time.sleep(delay)
        raise RuntimeError(f"Gemini classify failed after {attempts} attempts: {last_exc}")


def _sample_frames(media_path, n_frames: int = 8):
    """
    Decode a video and return up to *n_frames* PIL Images sampled evenly.

    Uses PyAV. A jpg/png path is treated as a single frame. Returns [] if nothing
    decodes. The model call is separate, so tests can exercise this in isolation.
    """
    p = Path(media_path)
    if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
        from PIL import Image
        return [Image.open(p).convert("RGB")] if p.exists() else []

    import av
    container = av.open(str(media_path))
    try:
        decoded = [frame.to_image() for frame in container.decode(video=0)]
    finally:
        container.close()
    if not decoded:
        return []
    if len(decoded) <= n_frames:
        return decoded
    step = len(decoded) / n_frames
    return [decoded[int(i * step)] for i in range(n_frames)]


class _QwenBase:
    """
    Shared scaffolding for self-hosted Qwen VLM backends.

    classify() samples frames (and, for the Omni variant, audio), builds the same
    schema-derived prompt as Gemini, calls the model (the _raw_response seam, which
    tests monkeypatch), and validates the JSON identically. The heavy model load is
    deferred to first use so importing this module never pulls in torch.
    """

    WITH_AUDIO = False

    def __init__(self, model_name: str, n_frames: int | None = None):
        """
        Remember which model to use. The heavy model files are loaded only on first use.

        n_frames=None (the default) lets classify() derive the frame budget from the
        configured fps, so --fps actually controls how many frames Qwen sees. Pass an
        explicit int only to override that and pin a fixed budget.
        """
        self.model_name = model_name
        self.n_frames = n_frames
        self._model = None
        self._processor = None

    def _load(self):
        """Load weights + processor on first real use (heavy: torch/transformers)."""
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
        self._processor = AutoProcessor.from_pretrained(self.model_name)
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_name, torch_dtype="auto", device_map="auto")
        self._model.eval()

    def _raw_response(self, frames, prompt, audio_path=None) -> str:
        """Run the model on frames(+audio) and return its raw text. (heavy)"""
        self._load()
        import torch
        content = [{"type": "image", "image": img} for img in frames]
        if self.WITH_AUDIO and audio_path:
            content.append({"type": "audio", "audio": audio_path})
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content}]
        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        inputs = self._processor(text=[text], images=frames, return_tensors="pt")
        inputs = inputs.to(self._model.device)
        with torch.no_grad():
            out = self._model.generate(**inputs, max_new_tokens=512)
        trimmed = out[:, inputs["input_ids"].shape[1]:]
        return self._processor.batch_decode(trimmed, skip_special_tokens=True)[0]

    def _extract_audio(self, media_path):
        """Best-effort: extract the audio track to a temp wav (Omni only)."""
        return None

    def classify(self, media_ref, schema) -> dict[str, list[tuple[str, float]]]:
        """
        Take a few frames (and audio, for the Omni variant) from the reel, ask the model to classify them, and return the cleaned-up answer.
        """
        vcfg = load_vision_config(schema)
        prompt = _build_vlm_prompt(schema, vcfg)
        max_per = int(vcfg.get("max_categories_per_dim", 2) or 2)
        fps_frames = int(vcfg.get("fps", 1) or 1) * 8
        frames = _sample_frames(media_ref, self.n_frames or fps_frames)
        if not frames:
            raise RuntimeError(f"no frames extracted from {media_ref}")
        audio = self._extract_audio(media_ref) if self.WITH_AUDIO else None
        last_exc = None
        for attempt in range(2):
            try:
                raw = self._raw_response(frames, prompt, audio)
                return _map_vlm_result(_parse_vlm_json(raw), schema, max_per)
            except Exception as exc:
                last_exc = exc
        raise RuntimeError(f"{type(self).__name__} classify failed after retry: {last_exc}")


class QwenVLModel(_QwenBase):
    """Qwen3-VL — frames + text, no audio (Apache-2.0, self-hosted)."""
    WITH_AUDIO = False


class QwenOmniModel(_QwenBase):
    """Qwen3.x-Omni — frames + audio + text (self-hosted)."""
    WITH_AUDIO = True

    def _extract_audio(self, media_path):
        """
        Return a path to the reel's audio track, or nothing. The plain video model has no audio.
        """
        p = Path(media_path)
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            return None
        try:
            import av, tempfile
            out = Path(tempfile.gettempdir()) / f"{p.stem}.wav"
            with av.open(str(media_path)) as inp:
                if not inp.streams.audio:
                    return None
                with av.open(str(out), mode="w") as outp:
                    ostream = outp.add_stream("pcm_s16le", rate=16000)
                    for frame in inp.decode(audio=0):
                        for packet in ostream.encode(frame):
                            outp.mux(packet)
                    for packet in ostream.encode():
                        outp.mux(packet)
            return str(out)
        except Exception:
            return None


def get_model(stub: bool, model_name: str | None = None) -> Backend:
    """
    Dispatch to a backend by name (the shell forwards --model into MODEL_NAME).

      stub=True            -> StubModel (offline, no model load)
      "gemini" in name     -> GeminiModel        (added in P6)
      "qwen"/"omni" in name-> Qwen* local VLM     (added in P10)
      otherwise            -> VisionModel (legacy CLIP / InternVideo2)

    The Gemini/Qwen classes live in this module once their prompt lands; we look
    them up in globals() so P5 stays import-safe before they exist.
    """
    if stub:
        print("  [Model: STUB, no real analysis]")
        return StubModel()

    name = (model_name or MODEL_NAME or "").lower()
    if "gemini" in name:
        import os
        cls = globals().get("GeminiModel")
        if cls is None:
            raise RuntimeError("Gemini backend not available yet (added in P6).")
        if not os.environ.get("GEMINI_API_KEY"):
            raise RuntimeError(
                f"Gemini backend selected (--model {model_name}) but GEMINI_API_KEY "
                "is not set. Export it before tagging, or pass a local --model.")
        print(f"  [Model: {model_name} (Gemini)]")
        return cls(model_name)
    if "omni" in name:
        cls = globals().get("QwenOmniModel")
        if cls is None:
            raise RuntimeError("Local Omni backend not available yet (added in P10).")
        print(f"  [Model: {model_name} (Qwen Omni, frames+audio)]")
        return cls(model_name)
    if "qwen" in name:
        cls = globals().get("QwenVLModel")
        if cls is None:
            raise RuntimeError("Local VLM backend not available yet (added in P10).")
        print(f"  [Model: {model_name} (Qwen-VL, frames)]")
        return cls(model_name)

    print(f"  [Model: {model_name or MODEL_NAME} -> local backend (VisionModel).")
    print("   If you meant a cloud model, the recognised patterns are: "
          "gemini*, qwen*, omni*. Loading locally...]")
    return VisionModel(model_name or MODEL_NAME)


def choose_tags(scores):
    """Contrastive-only: softmax-scored categories -> floor/rel/top-k selection."""
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    best = ranked[0][1] if ranked else 0.0
    out = []
    for cat, sc in ranked:
        if sc < ABS_FLOOR:
            continue
        if best > 0 and sc < REL_FRAC * best:
            continue
        out.append((cat, sc))
        if len(out) >= TOP_K:
            break
    return out


_TRANSIENT_MARKERS = (
    "429", "503", "500", "502", "504",
    "RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED",
    "rate limit", "high demand", "timeout", "timed out", "overloaded",
    "stuck in processing",
)


def _is_transient_error(exc) -> bool:
    """True if *exc* looks like a temporary server/rate-limit error worth retrying."""
    text = str(exc).lower()
    return any(m.lower() in text for m in _TRANSIENT_MARKERS)


_QUOTA_MARKERS = ("429", "resource_exhausted", "quota")
_QUOTA_HALT_THRESHOLD = 8


def _is_quota_error(exc) -> bool:
    """True if *exc* is an API quota/rate-cap error (429 RESOURCE_EXHAUSTED)."""
    text = str(exc).lower()
    return any(m in text for m in _QUOTA_MARKERS)


_BLOCK_MARKERS = (
    "block_reason=",
    "finish_reason=safety",
    "finish_reason=prohibited_content",
    "finish_reason=recitation",
)


def _is_blocked_error(exc) -> bool:
    """True if an empty VLM response was a terminal content-policy block."""
    text = str(exc).lower()
    return any(m in text for m in _BLOCK_MARKERS)


_DEPENDENCY_MARKERS = (
    "no module named",
    "modulenotfounderror",
    "importerror",
)


def _is_dependency_error(exc) -> bool:
    """True if *exc* is a missing-dependency / import failure.

    This is an *environment* problem (a package isn't installed), not a per-reel
    fault: it hits every reel identically. Detected so the run can halt fast
    instead of marking the whole corpus 'failed' one reel at a time."""
    text = str(exc).lower()
    return any(m in text for m in _DEPENDENCY_MARKERS)


_HALTED = object()


def _fmt_eta(seconds: float) -> str:
    """Format a seconds estimate as a compact h/m/s string for progress lines."""
    seconds = int(max(0, round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m:02d}:{s:02d}"


def _worker_label() -> str:
    """Compact id of the worker thread doing the work (e.g. 'W03'); 'main' off-pool.

    ThreadPoolExecutor names its threads '<prefix>_<slot>', so the trailing number is
    the stable worker slot — exactly "which worker ran this reel".
    """
    import threading
    tail = threading.current_thread().name.rsplit("_", 1)[-1]
    return f"W{int(tail):02d}" if tail.isdigit() else "main"


_BREAKER_THRESHOLD = 4
_BREAKER_COOLDOWN = 60.0


class _CircuitBreaker:
    """Thread-safe pause-on-burst gate shared by all tagging workers."""

    def __init__(self, threshold=_BREAKER_THRESHOLD, cooldown=_BREAKER_COOLDOWN):
        import threading
        self._lock = threading.Lock()
        self._fails = 0
        self._open_until = 0.0
        self._resume_pending = False
        self.threshold = threshold
        self.cooldown = cooldown

    def record_success(self):
        with self._lock:
            self._fails = 0

    def record_transient(self):
        import time
        with self._lock:
            self._fails += 1
            if self._fails >= self.threshold and time.monotonic() >= self._open_until:
                self._open_until = time.monotonic() + self.cooldown
                self._fails = 0
                self._resume_pending = True
                print(f"  ⏸ circuit breaker tripped ({self.threshold} consecutive transient "
                      f"errors) — pausing workers {int(self.cooldown)}s for demand to subside",
                      flush=True)

    def wait(self):
        """Block until the circuit is closed (returns immediately if it already is)."""
        import time
        while True:
            with self._lock:
                remaining = self._open_until - time.monotonic()
                announce = remaining <= 0 and self._resume_pending
                if announce:
                    self._resume_pending = False
            if remaining <= 0:
                if announce:
                    print("  ▶ circuit breaker reset — resuming tagging", flush=True)
                return
            time.sleep(min(remaining, 1.0))


_REQUEST_MIN_INTERVAL = 0.2


class _RateLimiter:
    """Thread-safe gate that hands out request slots at least `min_interval` apart."""

    def __init__(self, min_interval: float = 0.0):
        import threading
        self._lock = threading.Lock()
        self._min = max(0.0, float(min_interval))
        self._next = 0.0

    def acquire(self):
        """Block until this caller's spacing slot is due (no-op if interval is 0)."""
        if self._min <= 0:
            return
        import time
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self._next:
                    self._next = now + self._min
                    return
                wait = self._next - now
            time.sleep(wait)


def run(db_path, stub=False, limit=None, resolution=None, fps=None, workers=1, min_interval=0.0):
    """
    Tag every reel that still needs it: read its media, ask the chosen model for categories, and save the results. Can be stopped and resumed.

    With workers>1 the per-reel model calls run concurrently in a thread pool while
    all SQLite writes and progress prints stay on the calling thread (so the DB is
    only ever touched single-threaded). Intended for network backends (Gemini);
    keep workers=1 for local GPU models.
    """
    conn = sqlite3.connect(db_path)
    schema = load_schema()
    if (resolution is not None or fps is not None) and isinstance(schema, dict):
        vblock = schema.setdefault("vision", {})
        if isinstance(vblock, dict):
            if resolution is not None:
                vblock["media_resolution"] = resolution
            if fps is not None:
                vblock["fps"] = fps
    model = get_model(stub, MODEL_NAME)
    model_name = "stub" if stub else (MODEL_NAME or "vision")

    rows = conn.execute("""
        SELECT r.reel_pk FROM reels r
        LEFT JOIN vision_state v ON v.reel_pk = r.reel_pk
        WHERE (v.status IS NULL OR v.status='pending')
    """).fetchall()
    if limit:
        rows = rows[:limit]
    print(f"To tag: {len(rows)} reels\n")

    import time, threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if hasattr(model, "_client_or_create"):
        try:
            model._client_or_create()
        except Exception:
            pass

    breaker = _CircuitBreaker()
    rate = _RateLimiter(min_interval)
    halt = threading.Event()
    quota_state = {"streak": 0}

    def _classify_job(pk, media):
        worker = _worker_label()
        if halt.is_set():
            return (pk, media, None, _HALTED, worker)
        try:
            breaker.wait()
            rate.acquire()
            res = model.classify(media, schema)
        except Exception as exc:
            if _is_transient_error(exc):
                breaker.record_transient()
            return (pk, media, None, exc, worker)
        breaker.record_success()
        return (pk, media, res, None, worker)

    t_start = time.monotonic()
    done = no_media = failed = transient = blocked = 0
    total = len(rows)
    width = len(str(total))
    state = {"n": 0}
    worker_counts: dict[str, int] = {}

    def _prefix(pk, worker) -> str:
        completed = state["n"]
        if completed > 0:
            avg = (time.monotonic() - t_start) / completed
            eta = _fmt_eta(avg * (total - completed))
        else:
            eta = "--:--"
        state["n"] += 1
        return f"[{state['n']:>{width}}/{total} | ETA {eta} | {worker:>4}] {pk}"

    def _finalize(pk, media, results, exc, worker):
        nonlocal done, failed, transient, blocked
        if exc is _HALTED:
            return
        worker_counts[worker] = worker_counts.get(worker, 0) + 1
        if exc is not None:
            if _is_dependency_error(exc):
                conn.execute("INSERT OR REPLACE INTO vision_state (reel_pk,status,media_path,updated_at) "
                             "VALUES (?,'pending',?,datetime('now'))", (pk, media))
                conn.commit(); transient += 1
                if not halt.is_set():
                    halt.set()
                    print(f"\n✋ HALTING: missing dependency / import error — this breaks every reel "
                          f"identically, not just this one, so the run stops instead of marking the "
                          f"whole corpus 'failed'. Install the missing package (e.g. for Gemini: "
                          f"pip install google-genai) and re-run tagvision to resume. Un-tagged reels "
                          f"stay 'pending' — nothing is lost.\n  cause: {exc}\n", flush=True)
                return
            if _is_transient_error(exc):
                conn.execute("INSERT OR REPLACE INTO vision_state (reel_pk,status,media_path,updated_at) "
                             "VALUES (?,'pending',?,datetime('now'))", (pk, media))
                conn.commit(); transient += 1
                print(f"{_prefix(pk, worker)} ~ transient error (left pending, will retry): {exc}", flush=True)
                if _is_quota_error(exc):
                    quota_state["streak"] += 1
                    if quota_state["streak"] >= _QUOTA_HALT_THRESHOLD and not halt.is_set():
                        halt.set()
                        print(f"\n✋ HALTING: {_QUOTA_HALT_THRESHOLD} consecutive 429 quota errors. "
                              f"This is your API quota cap, not a demand spike — pausing won't clear "
                              f"it. Stopping so the run doesn't churn. Un-tagged reels stay 'pending'; "
                              f"restore quota (check limits / enable billing at aistudio.google.com) "
                              f"and re-run tagvision to resume — nothing is lost.\n", flush=True)
                else:
                    quota_state["streak"] = 0
            elif _is_blocked_error(exc):
                conn.execute("INSERT OR REPLACE INTO vision_state (reel_pk,status,media_path,updated_at) "
                             "VALUES (?,'blocked',?,datetime('now'))", (pk, media))
                conn.commit(); blocked += 1
                print(f"{_prefix(pk, worker)} ⊘ blocked (content policy — terminal, won't retry): {exc}", flush=True)
                quota_state["streak"] = 0
            else:
                conn.execute("INSERT OR REPLACE INTO vision_state (reel_pk,status,media_path,updated_at) "
                             "VALUES (?,'failed',?,datetime('now'))", (pk, media))
                conn.commit(); failed += 1
                print(f"{_prefix(pk, worker)} ! failed: {exc}", flush=True)
                quota_state["streak"] = 0
            return
        quota_state["streak"] = 0
        conn.execute("DELETE FROM annotations WHERE reel_pk=? AND source='vision'", (pk,))
        kept: list[str] = []
        for dim, picks in (results or {}).items():
            valid_cats = schema_categories(schema, dim)
            for cat, conf in picks:
                if cat not in valid_cats:
                    continue
                conf = max(0.0, min(1.0, float(conf)))
                conn.execute("""INSERT OR REPLACE INTO annotations
                    (reel_pk,dimension,category,source,confidence,model)
                    VALUES (?,?,?,?,?,?)""",
                    (pk, dim, cat, "vision", conf, model_name))
                kept.append(f"{dim}:{cat}({conf:.2f})")
        conn.execute("INSERT OR REPLACE INTO vision_state (reel_pk,status,media_path,updated_at) "
                     "VALUES (?,'done',?,datetime('now'))", (pk, media))
        conn.commit()
        done += 1
        print(f"{_prefix(pk, worker)} -> {', '.join(kept) if kept else '(no tags)'}", flush=True)

    jobs: list[tuple] = []
    for (pk,) in rows:
        media = local_media(pk)
        if not media:
            conn.execute("INSERT OR REPLACE INTO vision_state (reel_pk,status,updated_at) "
                         "VALUES (?,'no_media',datetime('now'))", (pk,))
            conn.commit(); no_media += 1
            lbl = _worker_label()
            worker_counts[lbl] = worker_counts.get(lbl, 0) + 1
            print(f"{_prefix(pk, lbl)} -> no local media (skipped)", flush=True)
        else:
            jobs.append((pk, media))

    workers = max(1, int(workers or 1))
    if workers == 1 or len(jobs) <= 1:
        for pk, media in jobs:
            _finalize(*_classify_job(pk, media))
            if halt.is_set():
                break
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="w") as ex:
            futs = [ex.submit(_classify_job, pk, media) for pk, media in jobs]
            try:
                for fut in as_completed(futs):
                    _finalize(*fut.result())
                    if halt.is_set():
                        break
            finally:
                for f in futs:
                    f.cancel()

    elapsed_total = time.monotonic() - t_start
    verb = "Halted after" if halt.is_set() else "Done in"
    print(f"\n{verb} {_fmt_eta(elapsed_total)}: {done} reels tagged, "
          f"{no_media} skipped (no local media), {blocked} blocked (content policy), "
          f"{failed} failed, "
          f"{transient} left pending (transient errors, will retry).")
    if halt.is_set():
        print("  ⚠ Run halted early on sustained quota exhaustion — many reels are still "
              "untagged/pending. Restore quota and re-run `tagvision` to resume; nothing is lost.")
    if no_media:
        print("  -> Running fetch_media.py might help acquiring missing videos.")
    pool_counts = {w: n for w, n in worker_counts.items() if w != "main"}
    if len(pool_counts) > 1:
        tally = "  ".join(f"{w}:{n}" for w, n in sorted(pool_counts.items()))
        lo, hi = min(pool_counts.values()), max(pool_counts.values())
        print(f"Per-worker reels:  {tally}   (spread {lo}-{hi})")

    if hasattr(model, "usage_summary"):
        u = model.usage_summary()
        if u.get("calls"):
            P_IN, P_AUD, P_OUT = 0.30, 1.00, 2.50
            non_audio_in = max(0, u["prompt"] - u["audio"])
            cost = (non_audio_in / 1e6 * P_IN + u["audio"] / 1e6 * P_AUD
                    + (u["output"] + u["thoughts"]) / 1e6 * P_OUT)
            print(f"\nToken usage ({u['calls']} billed calls):")
            print(f"  input   : {u['prompt']:>12,}  (of which audio {u['audio']:,})")
            print(f"  output  : {u['output']:>12,}  + thinking {u['thoughts']:,}")
            print(f"  total   : {u['total']:>12,}")
            print(f"  est. cost @ Flash Standard: ${cost:.2f}  "
                  f"(~${cost / u['calls'] * 1000:.2f}/1k reels) — check Cloud Billing for the exact charge")

    try:
        import pandas as pd
        summ = pd.read_sql("""SELECT dimension, category, COUNT(*) n, ROUND(AVG(confidence),3) avg_conf
                              FROM annotations WHERE source='vision'
                              GROUP BY dimension, category ORDER BY n DESC LIMIT 20""", conn)
        print("\n=== Vision tags (top 20) ===")
        print(summ.to_string(index=False) if not summ.empty else "  (none)")
    except Exception:
        pass
    conn.close()


if __name__ == "__main__":
    DB_PATH = "data/corpus.db"
    STUB    = False
    LIMIT   = None
    RESET   = True
    MODEL   = "gemini-2.5-flash"

    globals()["MODEL_NAME"] = MODEL

    if RESET:
        _c = sqlite3.connect(DB_PATH)
        _c.execute("DELETE FROM annotations WHERE source='vision'")
        _c.execute("UPDATE vision_state SET status='pending'")
        _c.commit(); _c.close()
        print("RESET: old vision tags discarded, all reels flagged 'pending'.\n")

    run(DB_PATH, stub=STUB, limit=LIMIT)
