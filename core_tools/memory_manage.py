import argparse
import json
import re
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import atomic_write_json, iso_now, load_json, resolve_workspace

# --- FTS5 sanitization ---

_FTS_SPECIAL = re.compile(r'["\*\(\)\-\+\^:]')


def _sanitize_fts_token(word: str) -> str:
    """Remove characters that have special meaning in FTS5."""
    return _FTS_SPECIAL.sub('', word).strip()


# --- Type detection heuristics ---

_TYPE_PATTERNS = {
    "decision": re.compile(
        r"(rozhodnut|decision|rozhodl|strategi|plán:|neadoptovat|nezavírat|přejmenovat|migrac)", re.I
    ),
    "contact": re.compile(
        r"(kontakt|email.*@|partner|dodavatel|odběratel|klient|zákazník|firma:)", re.I
    ),
    "preference": re.compile(
        r"(prefer|vždy|nikdy|always|never|poučení|pravidlo|používat)", re.I
    ),
    "event": re.compile(
        r"(meeting|schůzk|deadline|termín|podáno|zaplacen|objednán|odesláno|schválil|vyřeš)", re.I
    ),
    "project": re.compile(
        r"(vytvořen.*tool|vytvořen.*skill|implementac|integrac|hotov[áý]|launch|stav:)", re.I
    ),
}

_ENTITY_PATTERN = re.compile(
    r"(?:[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+)+)"
)

_PROJECT_KEYWORDS = {
    "printerhive": "printerhive",
    "hotend": "acg-stores",
    "acg": "acg-stores",
    "silicagel": "silicagel-store",
    "sicca": "silicagel-store",
    "filamentlab": "filament-lab",
    "aide": "aide",
    "ortopedie": "ortopedie-havirov",
    "schwannom": "schwannom-web",
    "youtube": "youtube",
}


def _detect_type(text: str) -> str:
    for typ, pat in _TYPE_PATTERNS.items():
        if pat.search(text):
            return typ
    return "note"


def _extract_entities(text: str) -> List[str]:
    _skip = {"Plán", "Příklad", "Stav", "Čekáme", "Pavel", "Příště", "Nabídka", "Projekt", "Materiál"}
    found = _ENTITY_PATTERN.findall(text)
    return [e for e in dict.fromkeys(found) if e not in _skip][:5]


def _detect_project(text: str) -> Optional[str]:
    text_lower = text.lower()
    for keyword, project in _PROJECT_KEYWORDS.items():
        if keyword in text_lower:
            return project
    return None


def _auto_tags(text: str) -> List[str]:
    tags = []
    text_lower = text.lower()
    tag_keywords = {
        "finance": ["faktur", "platb", "úhrad", "ceník", "nabídk", "czk", "eur", "kč"],
        "seo": ["seo", "článk", "blog", "obsah"],
        "product": ["produkt", "filament", "silikagel", "laser", "tiskárn"],
        "partnership": ["partner", "dodavatel", "odběratel", "spolupráce"],
        "tool": ["tool", "skill", "workflow", "script", "api"],
    }
    for tag, keywords in tag_keywords.items():
        if any(kw in text_lower for kw in keywords):
            tags.append(tag)
    return tags[:5]


# --- SQLite + FTS5 backend ---


def _db_path(workspace: Path) -> Path:
    return workspace / "data" / "memory.db"


def _json_path(workspace: Path) -> Path:
    return workspace / "data" / "memory.json"


def _get_db(workspace: Path) -> sqlite3.Connection:
    db_file = _db_path(workspace)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'note',
            text TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            entities TEXT NOT NULL DEFAULT '[]',
            project TEXT,
            created TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            text, tags, entities, project,
            content='memories',
            content_rowid='rowid',
            tokenize='unicode61'
        )
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, text, tags, entities, project)
            VALUES (new.rowid, new.text, new.tags, new.entities, new.project);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, text, tags, entities, project)
            VALUES ('delete', old.rowid, old.text, old.tags, old.entities, old.project);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, text, tags, entities, project)
            VALUES ('delete', old.rowid, old.text, old.tags, old.entities, old.project);
            INSERT INTO memories_fts(rowid, text, tags, entities, project)
            VALUES (new.rowid, new.text, new.tags, new.entities, new.project);
        END
    """)
    conn.commit()
    return conn


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d.pop("rank", None)
    d["tags"] = json.loads(d["tags"])
    d["entities"] = json.loads(d["entities"])
    return d


def _row_to_compact(row: sqlite3.Row) -> Dict[str, Any]:
    text = row["text"]
    first_sentence = text.split(". ")[0] if ". " in text else text[:80]
    return {
        "id": row["id"],
        "type": row["type"],
        "created": row["created"],
        "summary": first_sentence,
        "project": row["project"],
    }


def _sync_json_backup(workspace: Path, conn: sqlite3.Connection) -> None:
    """Export all memories to JSON as backup."""
    rows = conn.execute("SELECT * FROM memories ORDER BY created").fetchall()
    items = [_row_to_dict(r) for r in rows]
    atomic_write_json(_json_path(workspace), items)


# --- Commands ---


def add_mem(workspace: Path, text: str, mem_type: Optional[str] = None,
            tags: Optional[List[str]] = None, project: Optional[str] = None) -> None:
    if not text or not text.strip():
        print(json.dumps({"success": False, "error": "Text cannot be empty"}, ensure_ascii=False))
        sys.exit(1)

    conn = _get_db(workspace)
    try:
        mem_id = str(uuid.uuid4())
        detected_type = mem_type or _detect_type(text)
        detected_tags = _auto_tags(text) if tags is None else tags
        detected_entities = _extract_entities(text)
        detected_project = project or _detect_project(text)

        conn.execute(
            "INSERT INTO memories (id, type, text, tags, entities, project, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mem_id, detected_type, text, json.dumps(detected_tags, ensure_ascii=False),
             json.dumps(detected_entities, ensure_ascii=False), detected_project, iso_now()),
        )
        conn.commit()
        _sync_json_backup(workspace, conn)
    finally:
        conn.close()
    print(json.dumps({
        "success": True,
        "data": {"id": mem_id, "type": detected_type, "tags": detected_tags,
                 "entities": detected_entities, "project": detected_project}
    }, ensure_ascii=False))


def search_mem(workspace: Path, query: str, compact: bool = False,
               mem_type: Optional[str] = None, project: Optional[str] = None,
               limit: int = 15) -> None:
    conn = _get_db(workspace)
    try:
        words = [_sanitize_fts_token(w) for w in query.strip().split() if _sanitize_fts_token(w)]
        if words:
            fts_query = " AND ".join(f'"{w}"*' for w in words)
            sql = """
                SELECT m.*, rank
                FROM memories_fts fts
                JOIN memories m ON m.rowid = fts.rowid
                WHERE memories_fts MATCH ?
            """
            params: list = [fts_query]
            order = " ORDER BY rank LIMIT ?"
        else:
            sql = "SELECT *, 0 as rank FROM memories m WHERE 1=1"
            params = []
            order = " ORDER BY m.created DESC LIMIT ?"

        if mem_type:
            sql += " AND m.type = ?"
            params.append(mem_type)
        if project:
            sql += " AND m.project = ?"
            params.append(project)

        sql += order
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    if compact:
        results = [_row_to_compact(r) for r in rows]
    else:
        results = [_row_to_dict(r) for r in rows]

    print(json.dumps({"success": True, "data": results, "count": len(results)}, ensure_ascii=False))


def get_mem(workspace: Path, ids: List[str]) -> None:
    if not ids:
        print(json.dumps({"success": True, "data": []}, ensure_ascii=False))
        return
    conn = _get_db(workspace)
    try:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT * FROM memories WHERE id IN ({placeholders})", ids).fetchall()
    finally:
        conn.close()
    results = [_row_to_dict(r) for r in rows]
    print(json.dumps({"success": True, "data": results}, ensure_ascii=False))


def list_mem(workspace: Path, compact: bool = False, mem_type: Optional[str] = None,
             project: Optional[str] = None) -> None:
    conn = _get_db(workspace)
    try:
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list = []
        if mem_type:
            sql += " AND type = ?"
            params.append(mem_type)
        if project:
            sql += " AND project = ?"
            params.append(project)
        sql += " ORDER BY created DESC"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    if compact:
        results = [_row_to_compact(r) for r in rows]
    else:
        results = [_row_to_dict(r) for r in rows]

    print(json.dumps({"success": True, "data": results, "count": len(results)}, ensure_ascii=False))


def forget_mem(workspace: Path, mem_id: str) -> None:
    conn = _get_db(workspace)
    try:
        cursor = conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        if cursor.rowcount == 0:
            print(json.dumps({"success": False, "error": "Memory item not found"}, ensure_ascii=False))
            sys.exit(1)
        conn.commit()
        _sync_json_backup(workspace, conn)
    finally:
        conn.close()
    print(json.dumps({"success": True, "data": {"id": mem_id}}, ensure_ascii=False))


def stats_mem(workspace: Path) -> None:
    conn = _get_db(workspace)
    try:
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        by_type = conn.execute("SELECT type, COUNT(*) as cnt FROM memories GROUP BY type ORDER BY cnt DESC").fetchall()
        by_project = conn.execute(
            "SELECT project, COUNT(*) as cnt FROM memories WHERE project IS NOT NULL GROUP BY project ORDER BY cnt DESC"
        ).fetchall()
    finally:
        conn.close()
    print(json.dumps({
        "success": True,
        "data": {
            "total": total,
            "by_type": {r[0]: r[1] for r in by_type},
            "by_project": {r[0]: r[1] for r in by_project},
        }
    }, ensure_ascii=False))


def migrate_json(workspace: Path) -> None:
    """Migrate existing JSON memory to SQLite."""
    json_path = _json_path(workspace)
    items = load_json(json_path, [])
    if not items:
        print(json.dumps({"success": True, "data": {"migrated": 0, "message": "No items to migrate"}}))
        return

    conn = _get_db(workspace)
    try:
        existing = {r[0] for r in conn.execute("SELECT id FROM memories").fetchall()}
        migrated = 0

        for item in items:
            mem_id = item.get("id", str(uuid.uuid4()))
            if mem_id in existing:
                continue

            text = item.get("text", "")
            created = item.get("created", iso_now())

            mem_type = item.get("type") or _detect_type(text)
            raw_tags = item.get("tags")
            tags = raw_tags if isinstance(raw_tags, list) else _auto_tags(text)
            raw_entities = item.get("entities")
            entities = raw_entities if isinstance(raw_entities, list) else _extract_entities(text)
            project = item.get("project") or _detect_project(text)

            conn.execute(
                "INSERT INTO memories (id, type, text, tags, entities, project, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (mem_id, mem_type, text, json.dumps(tags, ensure_ascii=False),
                 json.dumps(entities, ensure_ascii=False), project, created),
            )
            migrated += 1

        conn.commit()
        conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
        conn.commit()
        _sync_json_backup(workspace, conn)
    finally:
        conn.close()
    print(json.dumps({"success": True, "data": {"migrated": migrated, "total": len(items)}}))


def archive_mem(workspace: Path, days: int = 30) -> None:
    """Move memories older than N days to archive."""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    conn = _get_db(workspace)
    try:
        old_rows = conn.execute(
            "SELECT * FROM memories WHERE created < ? ORDER BY created", (cutoff,)
        ).fetchall()

        if not old_rows:
            print(json.dumps({"success": True, "data": {"archived": 0}}))
            return

        archive_path = workspace / "data" / "memory_archive.json"
        existing_archive = load_json(archive_path, [])
        existing_ids = {a["id"] for a in existing_archive}

        archived = 0
        for row in old_rows:
            d = _row_to_dict(row)
            if d["id"] not in existing_ids:
                existing_archive.append(d)
                archived += 1

        atomic_write_json(archive_path, existing_archive)

        conn.execute("DELETE FROM memories WHERE created < ?", (cutoff,))
        conn.commit()
        _sync_json_backup(workspace, conn)
    finally:
        conn.close()

    print(json.dumps({"success": True, "data": {"archived": archived}}))


# --- CLI ---


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage memory items (SQLite + FTS5)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list")
    list_p.add_argument("--compact", action="store_true", help="Return compact index only")
    list_p.add_argument("--type", dest="mem_type", help="Filter by type")
    list_p.add_argument("--project", help="Filter by project")

    add_p = sub.add_parser("add")
    add_p.add_argument("--text", required=True)
    add_p.add_argument("--type", dest="mem_type", help="Override auto-detected type")
    add_p.add_argument("--tags", help="Comma-separated tags")
    add_p.add_argument("--project", help="Override auto-detected project")

    search_p = sub.add_parser("search")
    search_p.add_argument("--query", required=True)
    search_p.add_argument("--compact", action="store_true", help="Return compact index only")
    search_p.add_argument("--type", dest="mem_type", help="Filter by type")
    search_p.add_argument("--project", help="Filter by project")
    search_p.add_argument("--limit", type=int, default=15)

    get_p = sub.add_parser("get")
    get_p.add_argument("--ids", required=True, help="Comma-separated memory IDs")

    forget_p = sub.add_parser("forget")
    forget_p.add_argument("--id", required=True)

    sub.add_parser("stats")
    sub.add_parser("migrate", help="Migrate JSON memory to SQLite")

    archive_p = sub.add_parser("archive")
    archive_p.add_argument("--days", type=int, default=30, help="Archive items older than N days")

    args = parser.parse_args()
    workspace = resolve_workspace()

    try:
        if args.cmd == "list":
            list_mem(workspace, compact=args.compact, mem_type=args.mem_type, project=args.project)
        elif args.cmd == "add":
            tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
            add_mem(workspace, args.text, mem_type=args.mem_type, tags=tags, project=args.project)
        elif args.cmd == "search":
            search_mem(workspace, args.query, compact=args.compact,
                       mem_type=args.mem_type, project=args.project, limit=args.limit)
        elif args.cmd == "get":
            ids = [i.strip() for i in args.ids.split(",")]
            get_mem(workspace, ids)
        elif args.cmd == "forget":
            forget_mem(workspace, args.id)
        elif args.cmd == "stats":
            stats_mem(workspace)
        elif args.cmd == "migrate":
            migrate_json(workspace)
        elif args.cmd == "archive":
            archive_mem(workspace, days=args.days)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
