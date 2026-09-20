import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH = os.getenv("AUTOSTREAM_DB_PATH", os.path.join(os.path.dirname(__file__), "autostream.db"))

if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row

def _connect():
    if DATABASE_URL:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row, sslmode="require")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _sql(query: str) -> str:
    return query.replace("%s", "?") if not DATABASE_URL else query

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def init_db():
    conn = _connect()
    if DATABASE_URL:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS leads (
            id SERIAL PRIMARY KEY,
            session_id TEXT, name TEXT NOT NULL, email TEXT NOT NULL, platform TEXT NOT NULL,
            intent TEXT DEFAULT 'high_intent', status TEXT DEFAULT 'new', plan_interest TEXT DEFAULT 'Pro',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY,
            session_id TEXT, name TEXT NOT NULL, platform TEXT NOT NULL, style TEXT NOT NULL,
            source_filename TEXT, source_path TEXT, source_size BIGINT DEFAULT 0,
            prompt TEXT, duration INTEGER DEFAULT 5, aspect_ratio TEXT DEFAULT '16:9',
            provider_job_id TEXT,
            status TEXT DEFAULT 'draft', progress INTEGER DEFAULT 0,
            current_step TEXT DEFAULT 'Ready to create', output_filename TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """)
    else:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, name TEXT NOT NULL, email TEXT NOT NULL, platform TEXT NOT NULL,
            intent TEXT DEFAULT 'high_intent', status TEXT DEFAULT 'new', plan_interest TEXT DEFAULT 'Pro',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, name TEXT NOT NULL, platform TEXT NOT NULL, style TEXT NOT NULL,
            source_filename TEXT, source_path TEXT, source_size INTEGER DEFAULT 0,
            prompt TEXT, duration INTEGER DEFAULT 5, aspect_ratio TEXT DEFAULT '16:9',
            provider_job_id TEXT,
            status TEXT DEFAULT 'draft', progress INTEGER DEFAULT 0,
            current_step TEXT DEFAULT 'Ready to create', output_filename TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "source_path" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN source_path TEXT")
        if "prompt" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN prompt TEXT")
        if "duration" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN duration INTEGER DEFAULT 5")
        if "aspect_ratio" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN aspect_ratio TEXT DEFAULT '16:9'")
        if "provider_job_id" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN provider_job_id TEXT")
    conn.commit()
    conn.close()

def get_session(session_id: str) -> Optional[dict]:
    conn = _connect()
    row = conn.execute(_sql("SELECT state_json FROM sessions WHERE session_id = %s"), (session_id,)).fetchone()
    conn.close()
    return json.loads(row["state_json"]) if row else None

def save_session(session_id: str, state: dict):
    now = utc_now()
    conn = _connect()
    if DATABASE_URL:
        conn.execute(
            "INSERT INTO sessions(session_id,state_json,created_at,updated_at) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT(session_id) DO UPDATE SET state_json=EXCLUDED.state_json,updated_at=EXCLUDED.updated_at",
            (session_id, json.dumps(state), now, now),
        )
    else:
        conn.execute(
            _sql("INSERT INTO sessions(session_id,state_json,created_at,updated_at) VALUES (%s,%s,%s,%s) "
                 "ON CONFLICT(session_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at"),
            (session_id, json.dumps(state), now, now),
        )
    conn.commit(); conn.close()

def create_lead(session_id: str, name: str, email: str, platform: str, intent: str = "high_intent"):
    now = utc_now(); conn = _connect()
    cursor = conn.execute(
        _sql("INSERT INTO leads(session_id,name,email,platform,intent,status,plan_interest,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,'new','Pro',%s,%s)"),
        (session_id, name, email, platform, intent, now, now),
    )
    conn.commit(); lead_id = cursor.lastrowid; conn.close(); return lead_id

def list_leads(status: Optional[str] = None):
    conn = _connect()
    rows = conn.execute(
        _sql("SELECT * FROM leads WHERE status = %s ORDER BY created_at DESC"), (status,)
    ).fetchall() if status else conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
    conn.close(); return [dict(row) for row in rows]

def update_lead_status(lead_id: int, status: str):
    allowed = {"new","contacted","qualified","demo","converted","lost"}
    if status not in allowed:
        raise ValueError(f"Invalid status. Use one of: {', '.join(sorted(allowed))}")
    conn = _connect()
    cursor = conn.execute(_sql("UPDATE leads SET status=%s,updated_at=%s WHERE id=%s"), (status, utc_now(), lead_id))
    conn.commit(); conn.close(); return cursor.rowcount > 0

def create_project(session_id: str, name: str, platform: str, style: str, prompt: str = "", duration: int = 5, aspect_ratio: str = "16:9"):
    now = utc_now(); conn = _connect()
    cursor = conn.execute(
        _sql("INSERT INTO projects(session_id,name,platform,style,prompt,duration,aspect_ratio,status,progress,current_step,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',0,'Ready to create',%s,%s)"),
        (session_id, name, platform, style, prompt, duration, aspect_ratio, now, now),
    )
    conn.commit(); project_id = cursor.lastrowid; conn.close(); return get_project(project_id)

def get_project(project_id: int):
    conn = _connect(); row = conn.execute(_sql("SELECT * FROM projects WHERE id=%s"), (project_id,)).fetchone(); conn.close()
    return dict(row) if row else None

def list_projects(session_id: Optional[str] = None):
    conn = _connect()
    rows = conn.execute(_sql("SELECT * FROM projects WHERE session_id=%s ORDER BY created_at DESC"), (session_id,)).fetchall() if session_id else conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    conn.close(); return [dict(row) for row in rows]

def update_project(project_id: int, **fields):
    allowed = {"source_filename","source_path","source_size","prompt","duration","aspect_ratio","provider_job_id","status","progress","current_step","output_filename","platform","style","name"}
    updates = {k:v for k,v in fields.items() if k in allowed}
    if not updates: return get_project(project_id)
    updates["updated_at"] = utc_now()
    sql = ", ".join(f"{k}={'%s' if DATABASE_URL else '?'}" for k in updates)
    values = list(updates.values()) + [project_id]
    conn = _connect(); conn.execute(f"UPDATE projects SET {sql} WHERE id={'%s' if DATABASE_URL else '?'}", values); conn.commit(); conn.close()
    return get_project(project_id)

def analytics():
    conn = _connect()
    total=conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
    qualified=conn.execute("SELECT COUNT(*) AS n FROM leads WHERE status IN ('qualified','demo','converted')").fetchone()["n"]
    converted=conn.execute("SELECT COUNT(*) AS n FROM leads WHERE status='converted'").fetchone()["n"]
    sessions=conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    projects=conn.execute("SELECT COUNT(*) AS n FROM projects").fetchone()["n"]
    completed=conn.execute("SELECT COUNT(*) AS n FROM projects WHERE status='completed'").fetchone()["n"]
    statuses=conn.execute("SELECT status,COUNT(*) AS count FROM leads GROUP BY status ORDER BY count DESC").fetchall()
    platforms=conn.execute("SELECT platform,COUNT(*) AS count FROM leads GROUP BY platform ORDER BY count DESC").fetchall()
    conn.close()
    return {"total_leads":total,"qualified_leads":qualified,"converted_leads":converted,"active_sessions":sessions,"projects":projects,"completed_projects":completed,"conversion_rate":round(converted/total*100,1) if total else 0,"pipeline":[dict(r) for r in statuses],"platforms":[dict(r) for r in platforms]}
