"""User management tool for Aide multi-user system.

Commands:
  list          List all users (optionally --active-only)
  invite        Invite/create user (--slack-id, --name, --role)
  update-role   Change user role (--id, --role)
  deactivate    Deactivate user (--id)
  activate      Re-activate user (--id)
  overview      Admin overview: user stats, claims, memory/task counts
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import resolve_workspace


# --- Database ---


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
    return os.environ.get("AIDE_USER_ID")


def _require_admin() -> str:
    """Return current user_id or raise if not admin."""
    user_id = _get_user_id()
    if not user_id:
        raise RuntimeError("AIDE_USER_ID not set — cannot verify admin role")
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row or row[0] != "admin":
                raise RuntimeError("Permission denied: admin role required")
    finally:
        conn.close()
    return user_id


# --- Commands ---


def list_users(active_only: bool = False) -> None:
    _require_admin()
    import psycopg2.extras

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = "SELECT id, slack_id, name, role, active, created_at FROM users"
            if active_only:
                sql += " WHERE active = true"
            sql += " ORDER BY created_at"
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()

    users = []
    for r in rows:
        users.append({
            "id": str(r["id"]),
            "slack_id": r["slack_id"],
            "name": r["name"],
            "role": r["role"],
            "active": r["active"],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })

    print(json.dumps({"success": True, "data": users}, ensure_ascii=False))


def invite_user(slack_id: str, name: str, role: str = "user") -> None:
    _require_admin()

    if role not in ("admin", "user"):
        print(json.dumps({"success": False, "error": f"Invalid role: {role}. Use 'admin' or 'user'."}, ensure_ascii=False))
        sys.exit(1)

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # Check if user already exists
            cur.execute("SELECT id, active FROM users WHERE slack_id = %s", (slack_id,))
            existing = cur.fetchone()
            if existing:
                if not existing[1]:
                    # Re-activate
                    cur.execute(
                        "UPDATE users SET active = true, name = %s, role = %s WHERE id = %s",
                        (name, role, existing[0]),
                    )
                    conn.commit()
                    print(json.dumps({"success": True, "data": {"id": str(existing[0]), "action": "reactivated"}}, ensure_ascii=False))
                    return
                print(json.dumps({"success": False, "error": f"User with Slack ID {slack_id} already exists"}, ensure_ascii=False))
                sys.exit(1)

            user_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO users (id, slack_id, name, role) VALUES (%s, %s, %s, %s)",
                (user_id, slack_id, name, role),
            )
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"success": True, "data": {"id": user_id, "slack_id": slack_id, "name": name, "role": role}}, ensure_ascii=False))


def update_role(user_id_or_name: str, role: str) -> None:
    _require_admin()

    if role not in ("admin", "user"):
        print(json.dumps({"success": False, "error": f"Invalid role: {role}. Use 'admin' or 'user'."}, ensure_ascii=False))
        sys.exit(1)

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # Try UUID first, then name
            try:
                uuid.UUID(user_id_or_name)
                cur.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id_or_name))
            except ValueError:
                # Check for ambiguous name match
                cur.execute(
                    "SELECT id FROM users WHERE LOWER(name) = LOWER(%s)",
                    (user_id_or_name,),
                )
                matches = cur.fetchall()
                if len(matches) > 1:
                    print(json.dumps({"success": False, "error": f"Multiple users match '{user_id_or_name}'. Use UUID."}, ensure_ascii=False))
                    sys.exit(1)
                if not matches:
                    print(json.dumps({"success": False, "error": "User not found"}, ensure_ascii=False))
                    sys.exit(1)
                cur.execute("UPDATE users SET role = %s WHERE id = %s", (role, matches[0][0]))
            if cur.rowcount == 0:
                print(json.dumps({"success": False, "error": "User not found"}, ensure_ascii=False))
                sys.exit(1)
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"success": True, "data": {"user": user_id_or_name, "role": role}}, ensure_ascii=False))


def deactivate_user(user_id_or_name: str) -> None:
    admin_id = _require_admin()

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            try:
                uuid.UUID(user_id_or_name)
                target_id = user_id_or_name
            except ValueError:
                cur.execute("SELECT id FROM users WHERE LOWER(name) = LOWER(%s)", (user_id_or_name,))
                matches = cur.fetchall()
                if len(matches) > 1:
                    print(json.dumps({"success": False, "error": f"Multiple users match '{user_id_or_name}'. Use UUID."}, ensure_ascii=False))
                    sys.exit(1)
                if not matches:
                    print(json.dumps({"success": False, "error": "User not found"}, ensure_ascii=False))
                    sys.exit(1)
                target_id = str(matches[0][0])

            if target_id == admin_id:
                print(json.dumps({"success": False, "error": "Cannot deactivate yourself"}, ensure_ascii=False))
                sys.exit(1)

            cur.execute("UPDATE users SET active = false WHERE id = %s", (target_id,))
            if cur.rowcount == 0:
                print(json.dumps({"success": False, "error": "User not found"}, ensure_ascii=False))
                sys.exit(1)
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"success": True, "data": {"id": target_id, "active": False}}, ensure_ascii=False))


def activate_user(user_id_or_name: str) -> None:
    _require_admin()

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            try:
                uuid.UUID(user_id_or_name)
                cur.execute("UPDATE users SET active = true WHERE id = %s", (user_id_or_name,))
            except ValueError:
                cur.execute("SELECT id FROM users WHERE LOWER(name) = LOWER(%s)", (user_id_or_name,))
                matches = cur.fetchall()
                if len(matches) > 1:
                    print(json.dumps({"success": False, "error": f"Multiple users match '{user_id_or_name}'. Use UUID."}, ensure_ascii=False))
                    sys.exit(1)
                if not matches:
                    print(json.dumps({"success": False, "error": "User not found"}, ensure_ascii=False))
                    sys.exit(1)
                cur.execute("UPDATE users SET active = true WHERE id = %s", (matches[0][0],))
            if cur.rowcount == 0:
                print(json.dumps({"success": False, "error": "User not found"}, ensure_ascii=False))
                sys.exit(1)
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"success": True, "data": {"user": user_id_or_name, "active": True}}, ensure_ascii=False))


def overview() -> None:
    _require_admin()
    import psycopg2.extras

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # User counts
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE active = true) AS active_users,
                    COUNT(*) FILTER (WHERE active = false) AS inactive_users,
                    COUNT(*) FILTER (WHERE role = 'admin') AS admins
                FROM users
            """)
            user_stats = dict(cur.fetchone())

            # Per-user stats
            cur.execute("""
                SELECT
                    u.id, u.name, u.role, u.active,
                    COALESCE(m.cnt, 0) AS memory_count,
                    COALESCE(t.cnt, 0) AS task_count,
                    COALESCE(c.cnt, 0) AS claim_count
                FROM users u
                LEFT JOIN (SELECT user_id, COUNT(*) AS cnt FROM memories GROUP BY user_id) m ON m.user_id = u.id
                LEFT JOIN (SELECT user_id, COUNT(*) AS cnt FROM tasks WHERE status != 'completed' GROUP BY user_id) t ON t.user_id = u.id
                LEFT JOIN (SELECT owner_id, COUNT(*) AS cnt FROM channel_claims GROUP BY owner_id) c ON c.owner_id = u.id
                WHERE u.active = true
                ORDER BY u.name
            """)
            per_user = []
            for r in cur.fetchall():
                per_user.append({
                    "id": str(r["id"]),
                    "name": r["name"],
                    "role": r["role"],
                    "memory_count": r["memory_count"],
                    "task_count": r["task_count"],
                    "claim_count": r["claim_count"],
                })

            # Shared stats
            cur.execute("SELECT COUNT(*) AS cnt FROM memories WHERE user_id IS NULL")
            shared_memories = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM tasks WHERE user_id IS NULL AND status != 'completed'")
            shared_tasks = cur.fetchone()["cnt"]

            # Channel claims
            cur.execute("""
                SELECT cc.channel_id, cc.scope, u.name AS owner
                FROM channel_claims cc
                JOIN users u ON u.id = cc.owner_id
                ORDER BY cc.scope, u.name
            """)
            claims = [{"channel_id": r["channel_id"], "scope": r["scope"], "owner": r["owner"]} for r in cur.fetchall()]
    finally:
        conn.close()

    print(json.dumps({
        "success": True,
        "data": {
            "users": user_stats,
            "per_user": per_user,
            "shared": {"memories": shared_memories, "tasks": shared_tasks},
            "channel_claims": claims,
        }
    }, ensure_ascii=False))


# --- CLI ---


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Aide users")
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list")
    list_p.add_argument("--active-only", action="store_true")

    inv_p = sub.add_parser("invite")
    inv_p.add_argument("--slack-id", required=True, help="Slack user ID (e.g. U12345)")
    inv_p.add_argument("--name", required=True, help="Display name")
    inv_p.add_argument("--role", default="user", help="Role: admin or user")

    role_p = sub.add_parser("update-role")
    role_p.add_argument("--id", required=True, help="User ID or name")
    role_p.add_argument("--role", required=True, help="New role: admin or user")

    deact_p = sub.add_parser("deactivate")
    deact_p.add_argument("--id", required=True, help="User ID or name")

    act_p = sub.add_parser("activate")
    act_p.add_argument("--id", required=True, help="User ID or name")

    sub.add_parser("overview")

    args = parser.parse_args()

    try:
        if args.cmd == "list":
            list_users(active_only=args.active_only)
        elif args.cmd == "invite":
            invite_user(args.slack_id, args.name, args.role)
        elif args.cmd == "update-role":
            update_role(args.id, args.role)
        elif args.cmd == "deactivate":
            deactivate_user(args.id)
        elif args.cmd == "activate":
            activate_user(args.id)
        elif args.cmd == "overview":
            overview()
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
