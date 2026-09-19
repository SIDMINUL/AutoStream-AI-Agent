import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.getenv("AUTOSTREAM_DB_PATH", os.path.join(os.path.dirname(__file__), "autostream.db"))

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def init_db():
    conn = _connect()
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
        status TEXT DEFAULT 'draft', progress INTEGER DEFAULT 0,
        current_step TEXT DEFAULT 'Ready to upload', output_filename TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
    if "source_path" not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN source_path TEXT")
    conn.commit()
    conn.close()

def get_session(session_id: str) -> Optional[dict]:
    conn = _connect(); row = conn.execute("SELECT state_json FROM sessions WHERE session_id = ?", (session_id,)).fetchone(); conn.close()
    return json.loads(row["state_json"]) if row else None

def save_session(session_id: str, state: dict):
    now = utc_now(); conn = _connect()
    conn.execute("INSERT INTO sessions(session_id,state_json,created_at,updated_at) VALUES (?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at", (session_id,json.dumps(state),now,now))
    conn.commit(); conn.close()

def create_lead(session_id: str, name: str, email: str, platform: str, intent: str = "high_intent"):
    now = utc_now(); conn = _connect()
    cursor = conn.execute("INSERT INTO leads(session_id,name,email,platform,intent,status,plan_interest,created_at,updated_at) VALUES (?,?,?, ?,?,'new','Pro',?,?)", (session_id,name,email,platform,intent,now,now))
    conn.commit(); lead_id = cursor.lastrowid; conn.close(); return lead_id

def list_leads(status: Optional[str] = None):
    conn = _connect()
    rows = conn.execute("SELECT * FROM leads WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall() if status else conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
    conn.close(); return [dict(row) for row in rows]

def update_lead_status(lead_id: int, status: str):
    allowed = {"new","contacted","qualified","demo","converted","lost"}
    if status not in allowed: raise ValueError(f"Invalid status. Use one of: {', '.join(sorted(allowed))}")
    conn = _connect(); cursor = conn.execute("UPDATE leads SET status=?,updated_at=? WHERE id=?", (status,utc_now(),lead_id)); conn.commit(); conn.close(); return cursor.rowcount > 0

def create_project(session_id: str, name: str, platform: str, style: str):
    now = utc_now(); conn = _connect()
    cursor = conn.execute("INSERT INTO projects(session_id,name,platform,style,status,progress,current_step,created_at,updated_at) VALUES (?,?,?,?,'draft',0,'Ready to upload',?,?)", (session_id,name,platform,style,now,now))
    conn.commit(); project_id = cursor.lastrowid; conn.close(); return get_project(project_id)

def get_project(project_id: int):
    conn = _connect(); row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); conn.close(); return dict(row) if row else None

def list_projects(session_id: Optional[str] = None):
    conn = _connect()
    rows = conn.execute("SELECT * FROM projects WHERE session_id=? ORDER BY created_at DESC", (session_id,)).fetchall() if session_id else conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    conn.close(); return [dict(row) for row in rows]

def update_project(project_id: int, **fields):
    allowed = {"source_filename","source_path","source_size","status","progress","current_step","output_filename","platform","style","name"}
    updates = {k:v for k,v in fields.items() if k in allowed}
    if not updates: return get_project(project_id)
    updates["updated_at"] = utc_now()
    sql = ", ".join(f"{k}=?" for k in updates); values = list(updates.values()) + [project_id]
    conn = _connect(); conn.execute(f"UPDATE projects SET {sql} WHERE id=?", values); conn.commit(); conn.close(); return get_project(project_id)

def analytics():
    conn = _connect()
    total=conn.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"]; qualified=conn.execute("SELECT COUNT(*) n FROM leads WHERE status IN ('qualified','demo','converted')").fetchone()["n"]; converted=conn.execute("SELECT COUNT(*) n FROM leads WHERE status='converted'").fetchone()["n"]; sessions=conn.execute("SELECT COUNT(*) n FROM sessions").fetchone()["n"]; projects=conn.execute("SELECT COUNT(*) n FROM projects").fetchone()["n"]; completed=conn.execute("SELECT COUNT(*) n FROM projects WHERE status='completed'").fetchone()["n"]
    statuses=conn.execute("SELECT status,COUNT(*) count FROM leads GROUP BY status ORDER BY count DESC").fetchall(); platforms=conn.execute("SELECT platform,COUNT(*) count FROM leads GROUP BY platform ORDER BY count DESC").fetchall(); conn.close()
    return {"total_leads":total,"qualified_leads":qualified,"converted_leads":converted,"active_sessions":sessions,"projects":projects,"completed_projects":completed,"conversion_rate":round(converted/total*100,1) if total else 0,"pipeline":[dict(r) for r in statuses],"platforms":[dict(r) for r in platforms]}
