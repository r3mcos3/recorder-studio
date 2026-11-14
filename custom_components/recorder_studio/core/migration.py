"""Import an existing recorder config and switch configuration.yaml over to our file."""
from __future__ import annotations

import difflib
import re
from typing import Any

import yaml

from .rules import rules_to_text

SIMPLE_OPTIONS = ("auto_purge", "auto_repack", "purge_keep_days", "commit_interval", "db_url", "db_max_retries", "db_retry_wait")
KNOWN_TOP = set(SIMPLE_OPTIONS) | {"exclude", "include"}
MARKER = "# [recorder_studio] previous recorder config, replaced by the include below:"


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates HA tags such as !include / !secret (kept as plain strings)."""


def _any_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> str:
    return f"!{suffix} {getattr(node, 'value', '')}"


_Loader.add_multi_constructor("!", _any_tag)


def find_block(lines: list[str], key: str = "recorder") -> tuple[int, int] | None:
    """Return [start, end) line range of a top-level `key:` block (comments after it excluded)."""
    start = next(
        (i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(key)}\s*:", ln)),
        None,
    )
    if start is None:
        return None
    end = start + 1
    last_content = start + 1
    while end < len(lines):
        ln = lines[end]
        if ln.strip() and not ln.startswith((" ", "\t", "#", "-")):
            break
        if ln.strip() and not ln.lstrip().startswith("#"):
            last_content = end + 1
        end += 1
    return start, last_content


def parse_recorder_config(data: dict[str, Any]) -> dict[str, Any]:
    """Map a recorder: mapping onto Recorder Studio's data model."""
    warnings: list[str] = []
    options = {k: data[k] for k in SIMPLE_OPTIONS if k in data}
    for key, value in list(options.items()):
        if isinstance(value, str) and value.startswith("!"):
            del options[key]
            warnings.append(f"'{key}' uses a YAML tag ({value}); set it manually, it was not imported.")
    for key in data:
        if key not in KNOWN_TOP:
            warnings.append(f"Option '{key}' is not supported and was left out.")

    exclude = data.get("exclude") or {}
    include = data.get("include") or {}
    excluded = [str(e) for e in exclude.get("entities", []) or []]
    rules: dict[str, dict[str, list[str]]] = {}
    for section, body, keys in (
        ("exclude", exclude, ("domains", "entity_globs", "event_types")),
        ("include", include, ("domains", "entity_globs")),
    ):
        picked = {k: [str(v) for v in body[k]] for k in keys if body.get(k)}
        if picked:
            rules[section] = picked

    rescued: list[str] = []
    inc_entities = [str(e) for e in include.get("entities", []) or []]
    if inc_entities:
        if exclude.get("domains") or exclude.get("entity_globs") or include.get("domains") or include.get("entity_globs"):
            rescued = inc_entities
        else:
            warnings.append(
                "include.entities without a domain/glob filter acts as an allowlist; "
                "this is not supported and was left out."
            )
    if include.get("event_types"):
        warnings.append("include.event_types is not supported and was left out.")

    return {
        "options": options,
        "excluded_entities": sorted(set(excluded)),
        "rescued_entities": sorted(set(rescued)),
        "rules_text": rules_to_text(rules),
        "warnings": warnings,
    }


def read_legacy_file(text: str) -> dict[str, Any]:
    """Parse a standalone recorder yaml (e.g. gui_recorder.yaml)."""
    data = yaml.load(text, Loader=_Loader) or {}
    if not isinstance(data, dict):
        raise ValueError("File does not contain a recorder mapping.")
    return parse_recorder_config(data)


def inspect_configuration(config_text: str, target_file: str) -> dict[str, Any]:
    """Describe how recorder is currently configured in configuration.yaml."""
    lines = config_text.splitlines()
    rng = find_block(lines)
    if rng is None:
        return {"state": "absent", "block": "", "imported": None}
    start, end = rng
    block = "\n".join(lines[start:end])
    first = lines[start].partition(":")[2].strip()
    if first.startswith("!include"):
        target = first.split(None, 1)[1].strip() if " " in first else ""
        state = "active" if target == target_file else "other_include"
        return {"state": state, "block": block, "include_target": target, "imported": None}
    body = "\n".join(lines[start:end])
    try:
        parsed = yaml.load(body, Loader=_Loader) or {}
        data = parsed.get("recorder") or {}
        if not isinstance(data, dict):
            data = {}
    except yaml.YAMLError as err:
        return {"state": "invalid", "block": block, "imported": None, "error": str(err)}
    return {"state": "inline", "block": block, "imported": parse_recorder_config(data)}


def activate(config_text: str, target_file: str) -> str:
    """Return configuration.yaml text with recorder replaced by an include of target_file."""
    lines = config_text.splitlines()
    include_line = f"recorder: !include {target_file}"
    rng = find_block(lines)
    if rng is None:
        sep = [] if not lines or not lines[-1].strip() else [""]
        return "\n".join(lines + sep + [include_line]) + "\n"
    start, end = rng
    old = lines[start:end]
    if len(old) == 1 and old[0].partition(":")[2].strip().startswith("!include"):
        new = [include_line]
    else:
        new = [MARKER] + [f"# {ln}" if ln.strip() else "#" for ln in old] + [include_line]
    return "\n".join(lines[:start] + new + lines[end:]) + "\n"


def diff_text(before: str, after: str, name: str = "configuration.yaml") -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True), f"{name} (now)", f"{name} (after)"
        )
    )
