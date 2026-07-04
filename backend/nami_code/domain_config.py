"""
Small YAML config loader for NAMI v4.

This module intentionally does not change any runtime behavior by itself.  It
provides a shared way to read the project, schema, domain, and songs YAML files
while keeping legacy default paths as fallbacks when the newer config files
are not present yet.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


DEFAULT_PATHS: dict[str, str] = {
    "database": "data/corpus.db",
    "songs": "config/songs.yaml",
    "schema": "config/schema.yaml",
    "domain": "config/domain.yaml",
    "report_output": "outputs/report_out",
    "reels": "data/reels",
    "thumbnails": "data/thumbnails",
}

DEFAULT_PROJECT_CONFIG: dict[str, Any] = {
    "project": {
        "id": "nami_project",
        "name": "NAMI project",
        "platform": "instagram",
        "media_type": "reels",
    },
    "paths": deepcopy(DEFAULT_PATHS),
}


def _copy_default(default: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Return a defensive copy of a default mapping.
    """

    if default is None:
        return {}
    return deepcopy(default)


def load_yaml(path: str | Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Load a YAML mapping from *path*.

    Missing files return a defensive copy of *default* instead of raising. YAML
    syntax errors and unreadable non-mapping documents raise a clear exception so
    callers do not silently continue with a broken configuration file.
    """

    yaml_path = Path(path)
    if not yaml_path.exists():
        return _copy_default(default)

    try:
        with yaml_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse YAML config {yaml_path}: {exc}") from exc
    except OSError as exc:
        raise OSError(f"Could not read YAML config {yaml_path}: {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML config {yaml_path} must contain a mapping at the top level.")
    return data


def _merge_project_defaults(config: dict[str, Any]) -> dict[str, Any]:
    """
    Merge project config with legacy defaults without mutating input.
    """

    merged = deepcopy(DEFAULT_PROJECT_CONFIG)

    for key, value in config.items():
        if key == "paths" and isinstance(value, dict):
            merged["paths"].update(value)
        elif key == "project" and isinstance(value, dict):
            merged["project"].update(value)
        else:
            merged[key] = value

    if not isinstance(merged.get("paths"), dict):
        merged["paths"] = deepcopy(DEFAULT_PATHS)
    else:
        for key, value in DEFAULT_PATHS.items():
            merged["paths"].setdefault(key, value)

    return merged


def load_project_config(path: str | Path = "config/project.yaml") -> dict[str, Any]:
    """
    Load project metadata and paths, falling back to legacy defaults.
    """

    return _merge_project_defaults(load_yaml(path, default=DEFAULT_PROJECT_CONFIG))


def load_domain_config(path: str | Path = "config/domain.yaml") -> dict[str, Any]:
    """
    Load domain-specific lists and settings.

    A missing domain config is valid during the v4 migration and returns an empty
    mapping.
    """

    return load_yaml(path, default={})


def load_schema_config(path: str | Path = "config/schema.yaml") -> dict[str, Any]:
    """
    Load the classification schema config.
    """

    return load_yaml(path, default={})


def load_songs_config(path: str | Path = "config/songs.yaml") -> dict[str, Any]:
    """
    Load the song and track-variant config.
    """

    return load_yaml(path, default={})


DEFAULT_VISION_CONFIG: dict[str, Any] = {
    "model": "gemini-2.5-flash",
    "media_resolution": "default",
    "fps": 1,
    "max_categories_per_dim": 2,
    "instruction_template": (
        "You are classifying a short Instagram Reel (video with audio) for a research "
        "corpus. Use the frames, any on-screen text (including Japanese), and the audio. "
        "For each dimension, pick the categories whose description best matches the "
        "reel's content; a reel may match several, one, or none. Return STRICT JSON: "
        '{"<dimension_id>": [{"category": "<category_id>", "confidence": <float 0..1>}]}. '
        "Use only the listed category ids and pick at most {max_categories_per_dim} per "
        "dimension."
    ),
}


def load_vision_config(schema: dict[str, Any] | None) -> dict[str, Any]:
    """
    Return the vision backend config: schema's ``vision:`` block merged over
    DEFAULT_VISION_CONFIG. Missing or malformed blocks fall back to defaults so
    callers always get every expected key.
    """

    cfg = deepcopy(DEFAULT_VISION_CONFIG)
    block = schema.get("vision") if isinstance(schema, dict) else None
    if isinstance(block, dict):
        for key, value in block.items():
            if value is not None:
                cfg[key] = value
    return cfg


def load_category_descriptions(schema: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    """
    Return, per dimension, a {category_id: description} map for a reasoning VLM.

    A category's description is its ``vision_description`` when present and non-empty,
    otherwise it falls back to its ``vision_prompt``. Categories without a
    ``vision_prompt`` are skipped — matching ``tag_vision.load_vision_prompts`` — so
    partial schema coverage stays safe.
    """

    out: dict[str, dict[str, str]] = {}
    dimensions = schema.get("dimensions", {}) if isinstance(schema, dict) else {}
    if not isinstance(dimensions, dict):
        return out

    for dim_id, dim in dimensions.items():
        if not isinstance(dim, dict):
            continue
        categories = dim.get("categories", {})
        if not isinstance(categories, dict):
            continue

        dim_desc: dict[str, str] = {}
        for cat_id, cat in categories.items():
            if not isinstance(cat, dict):
                continue
            prompt = cat.get("vision_prompt")
            if not (isinstance(prompt, str) and prompt.strip()):
                continue
            desc = cat.get("vision_description")
            if isinstance(desc, str) and desc.strip():
                dim_desc[str(cat_id)] = desc.strip()
            else:
                dim_desc[str(cat_id)] = prompt.strip()

        if dim_desc:
            out[str(dim_id)] = dim_desc

    return out


def get_project_path(project_config: dict[str, Any], key: str, fallback: str) -> str:
    """
    Return a path value from project config with a caller-provided fallback.
    """

    paths = project_config.get("paths", {})
    if isinstance(paths, dict):
        value = paths.get(key)
        if value:
            return str(value)
    return fallback


def load_nami_config(
    project_path: str | Path = "config/project.yaml",
    schema_path: str | Path | None = None,
    domain_path: str | Path | None = None,
    songs_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Load the combined NAMI v4 configuration.

    Explicit schema/domain/songs paths override paths declared in project.yaml.
    Missing project.yaml and domain.yaml are handled gracefully for backward
    compatibility.
    """

    project_config = load_project_config(project_path)

    resolved_schema_path = schema_path or get_project_path(
        project_config, "schema", DEFAULT_PATHS["schema"]
    )
    resolved_domain_path = domain_path or get_project_path(
        project_config, "domain", DEFAULT_PATHS["domain"]
    )
    resolved_songs_path = songs_path or get_project_path(
        project_config, "songs", DEFAULT_PATHS["songs"]
    )

    schema_config = load_schema_config(resolved_schema_path)
    domain_config = load_domain_config(resolved_domain_path)
    songs_config = load_songs_config(resolved_songs_path)

    return {
        "project": project_config.get("project", {}),
        "paths": project_config.get("paths", deepcopy(DEFAULT_PATHS)),
        "schema": schema_config,
        "domain": domain_config,
        "songs": songs_config,
    }


def validate_schema_config(schema: dict[str, Any]) -> list[str]:
    """
    Return validation warnings for a schema config without raising.
    """

    warnings: list[str] = []
    if not isinstance(schema, dict) or not schema:
        return ["schema config is empty or not a mapping"]

    dimensions = schema.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        warnings.append("schema config is missing a non-empty 'dimensions' mapping")
        return warnings

    for dim_id, dim in dimensions.items():
        if not isinstance(dim, dict):
            warnings.append(f"dimension '{dim_id}' must be a mapping")
            continue
        if not dim.get("unknown_id"):
            warnings.append(f"dimension '{dim_id}' is missing 'unknown_id'")
        if not dim.get("unknown_label"):
            warnings.append(f"dimension '{dim_id}' is missing 'unknown_label'")
        categories = dim.get("categories")
        if not isinstance(categories, dict) or not categories:
            warnings.append(f"dimension '{dim_id}' is missing a non-empty 'categories' mapping")
            continue
        for cat_id, cat in categories.items():
            if not isinstance(cat, dict):
                warnings.append(f"category '{dim_id}.{cat_id}' must be a mapping")
                continue
            if not cat.get("label"):
                warnings.append(f"category '{dim_id}.{cat_id}' is missing 'label'")
            keywords = cat.get("keywords", [])
            if keywords is not None and not isinstance(keywords, list):
                warnings.append(f"category '{dim_id}.{cat_id}' has non-list 'keywords'")
            vision_prompt = cat.get("vision_prompt")
            if vision_prompt is not None and not isinstance(vision_prompt, str):
                warnings.append(f"category '{dim_id}.{cat_id}' has non-string 'vision_prompt'")

    return warnings


def validate_domain_config(config: dict[str, Any]) -> list[str]:
    """
    Return validation warnings for a domain config without raising.
    """

    warnings: list[str] = []
    if config is None:
        return ["domain config is None"]
    if not isinstance(config, dict):
        return ["domain config is not a mapping"]
    if not config:
        return []

    shared_terms = config.get("shared_terms", {})
    if shared_terms is not None and not isinstance(shared_terms, dict):
        warnings.append("domain 'shared_terms' must be a mapping when present")
    elif isinstance(shared_terms, dict):
        for group_id, group in shared_terms.items():
            if isinstance(group, dict):
                terms = group.get("terms", [])
            else:
                terms = group
            if not isinstance(terms, list):
                warnings.append(f"shared_terms group '{group_id}' must define a list of terms")

    hashtag_semantics = config.get("hashtag_semantics", {})
    if hashtag_semantics is not None and not isinstance(hashtag_semantics, dict):
        warnings.append("domain 'hashtag_semantics' must be a mapping when present")
    elif isinstance(hashtag_semantics, dict):
        clusters = hashtag_semantics.get("clusters", [])
        if clusters is not None and not isinstance(clusters, list):
            warnings.append("hashtag_semantics.clusters must be a list")
        elif isinstance(clusters, list):
            for idx, cluster in enumerate(clusters):
                if not isinstance(cluster, dict):
                    warnings.append(f"hashtag semantic cluster #{idx} must be a mapping")
                    continue
                if not cluster.get("id"):
                    warnings.append(f"hashtag semantic cluster #{idx} is missing 'id'")
                if not cluster.get("label"):
                    warnings.append(f"hashtag semantic cluster #{idx} is missing 'label'")
                exact = cluster.get("exact", cluster.get("terms", []))
                contains = cluster.get("contains", cluster.get("substring_terms", []))
                if exact is not None and not isinstance(exact, list):
                    warnings.append(
                        f"hashtag semantic cluster '{cluster.get('id', idx)}' has non-list 'exact'"
                    )
                if contains is not None and not isinstance(contains, list):
                    warnings.append(
                        f"hashtag semantic cluster '{cluster.get('id', idx)}' has non-list 'contains'"
                    )
        priority_rules = hashtag_semantics.get("priority_substring_rules", [])
        if priority_rules is not None and not isinstance(priority_rules, list):
            warnings.append("hashtag_semantics.priority_substring_rules must be a list")

    sampling = config.get("sampling", {})
    if sampling is not None and not isinstance(sampling, dict):
        warnings.append("domain 'sampling' must be a mapping when present")
    elif isinstance(sampling, dict):
        slots = sampling.get("curated_slots", [])
        if slots is not None and not isinstance(slots, list):
            warnings.append("sampling.curated_slots must be a list")
        elif isinstance(slots, list):
            for idx, slot in enumerate(slots):
                if not isinstance(slot, dict):
                    warnings.append(f"sampling slot #{idx} must be a mapping")
                    continue
                if not slot.get("slot"):
                    warnings.append(f"sampling slot #{idx} is missing 'slot'")
                if "n" in slot and not isinstance(slot["n"], int):
                    warnings.append(f"sampling slot '{slot.get('slot', idx)}' has non-integer 'n'")



    hashtag_stoplist = config.get("hashtag_stoplist", {})
    if hashtag_stoplist is not None and not isinstance(hashtag_stoplist, (dict, list)):
        warnings.append("domain 'hashtag_stoplist' must be a mapping or list when present")
    elif isinstance(hashtag_stoplist, dict):
        for list_id, terms in hashtag_stoplist.items():
            if terms is not None and not isinstance(terms, list):
                warnings.append(f"hashtag_stoplist.{list_id} must be a list")

    robustness = config.get("robustness", {})
    if robustness is not None and not isinstance(robustness, dict):
        warnings.append("domain 'robustness' must be a mapping when present")
    elif isinstance(robustness, dict):
        broad = robustness.get("broad_keywords", robustness.get("broad_keyword_audit_terms", []))
        if broad is not None and not isinstance(broad, list):
            warnings.append("robustness.broad_keywords must be a list")
        max_len = robustness.get("broad_keyword_max_length")
        if max_len is not None and not isinstance(max_len, int):
            warnings.append("robustness.broad_keyword_max_length must be an integer")

    moderation = config.get("moderation", {})
    if moderation is not None and not isinstance(moderation, dict):
        warnings.append("domain 'moderation' must be a mapping when present")
    elif isinstance(moderation, dict):
        spam_terms = moderation.get("spam_terms", [])
        if spam_terms is not None and not isinstance(spam_terms, list):
            warnings.append("moderation.spam_terms must be a list")

    report = config.get("report", {})
    if report is not None and not isinstance(report, dict):
        warnings.append("domain 'report' must be a mapping when present")
    elif isinstance(report, dict):
        enabled = report.get("enabled_sections")
        if enabled is not None and not isinstance(enabled, list):
            warnings.append("report.enabled_sections must be a list")
        labels = report.get("labels")
        if labels is not None and not isinstance(labels, dict):
            warnings.append("report.labels must be a mapping")
        sections = report.get("sections")
        if sections is not None and not isinstance(sections, dict):
            warnings.append("report.sections must be a mapping")
        for key in ("title", "html_title", "subtitle", "primary_dimension", "secondary_dimension"):
            if key in report and report[key] is not None and not isinstance(report[key], str):
                warnings.append(f"report.{key} must be a string")

    return warnings
