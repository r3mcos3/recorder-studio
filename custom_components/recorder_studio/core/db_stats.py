"""Read-only SQLite analysis of the recorder database."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

DEFAULT_DB = "home-assistant_v2.db"


def resolve_db_path(config_dir: str, db_url: str | None) -> Path:
    """Map a SQLAlchemy sqlite URL to a file path (relative URLs resolve against config_dir)."""
    base = Path(config_dir)
    if db_url and db_url.lower().startswith("sqlite://"):
        raw = db_url.partition("://")[2].partition("?")[0]
        if raw.strip("/"):
            if db_url.startswith("sqlite:////"):
                return Path("/" + raw.lstrip("/"))
            return base / raw.lstrip("/")
    return base / DEFAULT_DB


def total_size_bytes(db_path: Path) -> int:
    """Sum of the .db file and its -wal / -shm sidecars."""
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += (db_path.with_name(db_path.name + suffix)).stat().st_size
        except OSError:
            pass
    return total


def file_sizes(db_path: Path) -> dict[str, int]:
    """Sizes of the database file and its WAL/SHM sidecars (cheap: stat only, no SQL)."""
    out = {}
    for key, suffix in (("db", ""), ("wal", "-wal"), ("shm", "-shm")):
        try:
            out[key] = db_path.with_name(db_path.name + suffix).stat().st_size
        except OSError:
            out[key] = 0
    out["total"] = out["db"] + out["wal"] + out["shm"]
    return out


def table_sizes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Bytes per table (indexes included) using the dbstat virtual table; [] when unavailable."""
    try:
        owner = {n: t for n, t in conn.execute("SELECT name, tbl_name FROM sqlite_master")}
        sizes: dict[str, int] = {}
        for name, size in conn.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name"):
            table = owner.get(name, name)
            sizes[table] = sizes.get(table, 0) + int(size or 0)
    except sqlite3.Error:
        return []
    return [{"name": n, "bytes": b} for n, b in sorted(sizes.items(), key=lambda kv: -kv[1]) if b]


def free_bytes(conn: sqlite3.Connection) -> int:
    """Space inside the file that is unused and would be returned to the OS by a repack."""
    try:
        pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
        size = conn.execute("PRAGMA page_size").fetchone()[0]
        return int(pages) * int(size)
    except sqlite3.Error:
        return 0


def analyze(db_path: Path) -> dict[str, Any]:
    """Per-entity state counts. Opens the database strictly read-only."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "states_meta" in tables:
            sql = (
                "SELECT m.entity_id, COUNT(*) FROM states s "
                "JOIN states_meta m ON m.metadata_id = s.metadata_id "
                "GROUP BY m.entity_id ORDER BY 2 DESC"
            )
        else:
            sql = "SELECT entity_id, COUNT(*) FROM states GROUP BY entity_id ORDER BY 2 DESC"
        counts = {e: c for e, c in conn.execute(sql) if e}
        tables = table_sizes(conn)
        free = free_bytes(conn)
    finally:
        conn.close()
    return {
        "entity_counts": counts,
        "total_records": sum(counts.values()),
        "db_path": str(db_path),
        "db_size_bytes": total_size_bytes(db_path),
        "files": file_sizes(db_path),
        "tables": tables,
        "free_bytes": free,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }


def summarize(stats: dict[str, Any], excluded: list[str], known_entities: set[str]) -> dict[str, Any]:
    """Derive the dashboard numbers from raw counts.

    obsolete = records that still sit in the database for entities that are now excluded
    orphans  = excluded entity ids that no longer exist anywhere in Home Assistant
    """
    counts: dict[str, int] = stats.get("entity_counts", {})
    total = int(stats.get("total_records", 0))
    obsolete = sum(counts.get(e, 0) for e in excluded)
    matched = [e for e in excluded if e in counts]
    orphans = sorted(e for e in excluded if e not in known_entities and e not in counts)
    return {
        "total_records": total,
        "current_records": total - obsolete,
        "obsolete_records": obsolete,
        "excluded_with_records": len(matched),
        "orphan_exclusions": orphans,
        "entity_count": len(counts),
        "db_size_bytes": stats.get("db_size_bytes", 0),
        "tables": stats.get("tables", []),
        "free_bytes": stats.get("free_bytes", 0),
        "db_path": stats.get("db_path"),
        "generated_at": stats.get("generated_at"),
        "error": stats.get("error"),
        "top_entities": [[e, c, round(c * 100 / total, 2) if total else 0.0] for e, c in list(counts.items())[:15]],
    }


def estimate_impact(stats: dict[str, Any], entity_ids: list[str]) -> dict[str, Any]:
    """Rough impact of purging the given entities, for confirmation dialogs."""
    counts = stats.get("entity_counts", {})
    records = sum(counts.get(e, 0) for e in entity_ids)
    total = max(int(stats.get("total_records", 0)), 1)
    return {
        "entities": len(entity_ids),
        "records": records,
        "approx_bytes": int(stats.get("db_size_bytes", 0) * records / total),
    }
