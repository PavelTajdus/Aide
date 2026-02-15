import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import resolve_workspace

# --- Database connection ---

_DB_URL = None


def _get_db_url() -> str:
    global _DB_URL
    if _DB_URL is None:
        _DB_URL = os.environ.get("DATABASE_URL", "")
    if not _DB_URL:
        raise RuntimeError("DATABASE_URL not set")
    return _DB_URL


def _get_conn():
    import psycopg2
    conn = psycopg2.connect(_get_db_url())
    conn.autocommit = False
    return conn


def _get_user_id() -> Optional[str]:
    """Get current user_id from env. None = legacy/single-user mode."""
    return os.environ.get("AIDE_USER_ID")


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


# --- Row formatting ---


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(row)
    d.pop("tsv", None)
    d.pop("embedding", None)
    d["id"] = str(d["id"])
    if d.get("user_id"):
        d["user_id"] = str(d["user_id"])
    for key in ("created_at", "updated_at"):
        if d.get(key):
            d[key] = d[key].isoformat()
    # Backward compat
    d["created"] = d.get("created_at", "")
    return d


def _row_to_compact(row: Dict[str, Any]) -> Dict[str, Any]:
    text = row["text"]
    first_sentence = text.split(". ")[0] if ". " in text else text[:80]
    return {
        "id": str(row["id"]),
        "type": row["type"],
        "created": row["created_at"].isoformat() if row.get("created_at") else "",
        "summary": first_sentence,
        "project": row["project"],
    }


# --- User filter helper ---


def _user_filter(user_id: Optional[str]) -> tuple:
    """SQL fragment for user_id filtering: own + shared (NULL)."""
    if user_id:
        return "(user_id = %s OR user_id IS NULL)", [user_id]
    return "TRUE", []


# --- Commands ---


def add_mem(workspace: Path, text: str, mem_type: Optional[str] = None,
            tags: Optional[List[str]] = None, project: Optional[str] = None) -> None:
    if not text or not text.strip():
        print(json.dumps({"success": False, "error": "Text cannot be empty"}, ensure_ascii=False))
        sys.exit(1)

    import psycopg2.extras

    mem_id = str(uuid.uuid4())
    detected_type = mem_type or _detect_type(text)
    detected_tags = _auto_tags(text) if tags is None else tags
    detected_entities = _extract_entities(text)
    detected_project = project or _detect_project(text)
    user_id = _get_user_id()

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO memories (id, user_id, text, type, tags, entities, project)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (mem_id, user_id, text, detected_type, detected_tags,
                 detected_entities, detected_project),
            )
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({
        "success": True,
        "data": {"id": str(mem_id), "type": detected_type, "tags": detected_tags,
                 "entities": detected_entities, "project": detected_project}
    }, ensure_ascii=False))


def search_mem(workspace: Path, query: str, compact: bool = False,
               mem_type: Optional[str] = None, project: Optional[str] = None,
               limit: int = 15) -> None:
    import psycopg2.extras

    user_id = _get_user_id()
    user_sql, user_params = _user_filter(user_id)

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            raw_words = query.strip().split()
            sanitized = [re.sub(r'[^\w]', '', w) for w in raw_words]
            sanitized = [w for w in sanitized if w]
            if sanitized:
                tsquery_parts = [f"{w}:*" for w in sanitized]
                tsquery = " & ".join(tsquery_parts)
                sql = f"""
                    SELECT *, ts_rank(tsv, to_tsquery('simple', %s)) AS rank
                    FROM memories
                    WHERE tsv @@ to_tsquery('simple', %s) AND {user_sql}
                """
                params = [tsquery, tsquery] + user_params
                order = " ORDER BY rank DESC LIMIT %s"
            else:
                sql = f"SELECT *, 0 AS rank FROM memories WHERE {user_sql}"
                params = list(user_params)
                order = " ORDER BY created_at DESC LIMIT %s"

            if mem_type:
                sql += " AND type = %s"
                params.append(mem_type)
            if project:
                sql += " AND project = %s"
                params.append(project)

            sql += order
            params.append(limit)

            cur.execute(sql, params)
            rows = cur.fetchall()
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

    import psycopg2.extras

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(f"SELECT * FROM memories WHERE id IN ({placeholders})", ids)
            rows = cur.fetchall()
    finally:
        conn.close()

    results = [_row_to_dict(r) for r in rows]
    print(json.dumps({"success": True, "data": results}, ensure_ascii=False))


def list_mem(workspace: Path, compact: bool = False, mem_type: Optional[str] = None,
             project: Optional[str] = None) -> None:
    import psycopg2.extras

    user_id = _get_user_id()
    user_sql, user_params = _user_filter(user_id)

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = f"SELECT * FROM memories WHERE {user_sql}"
            params = list(user_params)
            if mem_type:
                sql += " AND type = %s"
                params.append(mem_type)
            if project:
                sql += " AND project = %s"
                params.append(project)
            sql += " ORDER BY created_at DESC"
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    if compact:
        results = [_row_to_compact(r) for r in rows]
    else:
        results = [_row_to_dict(r) for r in rows]

    print(json.dumps({"success": True, "data": results, "count": len(results)}, ensure_ascii=False))


def forget_mem(workspace: Path, mem_id: str) -> None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM memories WHERE id = %s", (mem_id,))
            if cur.rowcount == 0:
                print(json.dumps({"success": False, "error": "Memory item not found"}, ensure_ascii=False))
                sys.exit(1)
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"success": True, "data": {"id": mem_id}}, ensure_ascii=False))


def stats_mem(workspace: Path) -> None:
    import psycopg2.extras

    user_id = _get_user_id()
    user_sql, user_params = _user_filter(user_id)

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM memories WHERE {user_sql}", user_params)
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT type, COUNT(*) AS cnt FROM memories WHERE {user_sql} GROUP BY type ORDER BY cnt DESC",
                user_params,
            )
            by_type = {r["type"]: r["cnt"] for r in cur.fetchall()}

            cur.execute(
                f"""SELECT project, COUNT(*) AS cnt FROM memories
                    WHERE project IS NOT NULL AND {user_sql}
                    GROUP BY project ORDER BY cnt DESC""",
                user_params,
            )
            by_project = {r["project"]: r["cnt"] for r in cur.fetchall()}
    finally:
        conn.close()

    print(json.dumps({
        "success": True,
        "data": {"total": total, "by_type": by_type, "by_project": by_project}
    }, ensure_ascii=False))


# --- CLI ---


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage memory items (PostgreSQL)")
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
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
