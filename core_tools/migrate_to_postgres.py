"""Migrate existing SQLite memories + JSON tasks/cron to PostgreSQL.

Usage:
    DATABASE_URL=postgresql://... python3 migrate_to_postgres.py --workspace /opt/aide/workspace

Safety:
    - Read-only on source files (SQLite, JSON)
    - Uses INSERT ON CONFLICT DO NOTHING (safe to run multiple times)
    - Prints summary with counts before and after
"""
import argparse
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

import psycopg2
import psycopg2.extras


def _get_conn():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn


def migrate_memories(workspace: Path, conn) -> int:
    """Migrate memories from SQLite to PostgreSQL."""
    db_path = workspace / "data" / "memory.db"
    if not db_path.exists():
        print("  No memory.db found, skipping")
        return 0

    sqlite_conn = sqlite3.connect(str(db_path))
    sqlite_conn.row_factory = sqlite3.Row
    rows = sqlite_conn.execute("SELECT * FROM memories ORDER BY created").fetchall()
    sqlite_conn.close()

    if not rows:
        print("  No memories to migrate")
        return 0

    migrated = 0
    with conn.cursor() as cur:
        for row in rows:
            mem_id = row["id"]
            text = row["text"]
            mem_type = row["type"] or "note"
            tags = json.loads(row["tags"]) if row["tags"] else []
            entities = json.loads(row["entities"]) if row["entities"] else []
            project = row["project"]
            created = row["created"]

            try:
                cur.execute(
                    """INSERT INTO memories (id, user_id, text, type, tags, entities, project, created_at, updated_at)
                       VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (mem_id, text, mem_type, tags, entities, project, created, created),
                )
                if cur.rowcount > 0:
                    migrated += 1
            except Exception as exc:
                print(f"  WARN: Failed to migrate memory {mem_id}: {exc}")
                conn.rollback()
                continue

    conn.commit()
    return migrated


def migrate_tasks(workspace: Path, conn) -> int:
    """Migrate tasks from JSON to PostgreSQL."""
    tasks_path = workspace / "data" / "tasks.json"
    if not tasks_path.exists():
        print("  No tasks.json found, skipping")
        return 0

    with tasks_path.open("r", encoding="utf-8") as f:
        tasks = json.load(f)

    if not tasks:
        print("  No tasks to migrate")
        return 0

    migrated = 0
    with conn.cursor() as cur:
        for task in tasks:
            task_id = task.get("id", str(uuid.uuid4()))
            title = task.get("title", "(untitled)")
            status = task.get("status", "open")
            # Map old "done" status to "completed"
            if status == "done":
                status = "completed"
            priority = task.get("priority")
            project = task.get("project")
            context = task.get("context")
            due = task.get("due")
            remind = task.get("remind")
            remind_sent_at = task.get("remind_sent_at")
            recurrence = task.get("recurrence")
            created = task.get("created")
            completed = task.get("completed")

            try:
                cur.execute(
                    """INSERT INTO tasks (id, user_id, title, status, priority, project, context,
                       due_date, remind_at, remind_sent_at, recurrence, created_at, updated_at, completed_at)
                       VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (task_id, title, status, priority, project, context,
                     due, remind, remind_sent_at, recurrence, created, created, completed),
                )
                if cur.rowcount > 0:
                    migrated += 1
            except Exception as exc:
                print(f"  WARN: Failed to migrate task {task_id} ({title}): {exc}")
                conn.rollback()
                continue

    conn.commit()
    return migrated


def migrate_cron(workspace: Path, conn) -> int:
    """Migrate cron jobs from JSON to PostgreSQL."""
    cron_path = workspace / "data" / "cron.json"
    if not cron_path.exists():
        print("  No cron.json found, skipping")
        return 0

    with cron_path.open("r", encoding="utf-8") as f:
        jobs = json.load(f)

    if not jobs:
        print("  No cron jobs to migrate")
        return 0

    migrated = 0
    with conn.cursor() as cur:
        for job in jobs:
            job_id = job.get("id", str(uuid.uuid4()))
            schedule = job.get("schedule", "")
            prompt = job.get("prompt", "")
            enabled = job.get("enabled", True)
            last_run = job.get("last_run")

            # Determine type: heartbeat or cron
            job_type = "heartbeat" if job_id == "heartbeat" else "cron"

            try:
                cur.execute(
                    """INSERT INTO cron_jobs (id, user_id, type, schedule, command, task, enabled, last_run)
                       VALUES (%s, NULL, %s, %s, NULL, %s, %s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (job_id, job_type, schedule, prompt, enabled, last_run),
                )
                if cur.rowcount > 0:
                    migrated += 1
            except Exception as exc:
                print(f"  WARN: Failed to migrate cron job {job_id}: {exc}")
                conn.rollback()
                continue

    conn.commit()
    return migrated


def verify_counts(workspace: Path, conn) -> None:
    """Compare source and target counts."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM memories")
        pg_memories = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tasks")
        pg_tasks = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM cron_jobs")
        pg_cron = cur.fetchone()[0]

    # Source counts
    src_memories = 0
    db_path = workspace / "data" / "memory.db"
    if db_path.exists():
        sqlite_conn = sqlite3.connect(str(db_path))
        src_memories = sqlite_conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        sqlite_conn.close()

    src_tasks = 0
    tasks_path = workspace / "data" / "tasks.json"
    if tasks_path.exists():
        src_tasks = len(json.load(tasks_path.open()))

    src_cron = 0
    cron_path = workspace / "data" / "cron.json"
    if cron_path.exists():
        src_cron = len(json.load(cron_path.open()))

    print(f"\nVerification:")
    print(f"  Memories: {src_memories} source → {pg_memories} in Postgres {'OK' if pg_memories >= src_memories else 'MISMATCH'}")
    print(f"  Tasks:    {src_tasks} source → {pg_tasks} in Postgres {'OK' if pg_tasks >= src_tasks else 'MISMATCH'}")
    print(f"  Cron:     {src_cron} source → {pg_cron} in Postgres {'OK' if pg_cron >= src_cron else 'MISMATCH'}")


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite/JSON data to PostgreSQL")
    parser.add_argument("--workspace", required=True, help="Path to workspace")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.exists():
        print(f"Workspace not found: {workspace}")
        sys.exit(1)

    print(f"Migrating from: {workspace}")
    conn = _get_conn()

    try:
        print("\n1. Migrating memories (SQLite → Postgres)...")
        mem_count = migrate_memories(workspace, conn)
        print(f"   Migrated: {mem_count}")

        print("\n2. Migrating tasks (JSON → Postgres)...")
        task_count = migrate_tasks(workspace, conn)
        print(f"   Migrated: {task_count}")

        print("\n3. Migrating cron jobs (JSON → Postgres)...")
        cron_count = migrate_cron(workspace, conn)
        print(f"   Migrated: {cron_count}")

        verify_counts(workspace, conn)
        print("\nMigration complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
