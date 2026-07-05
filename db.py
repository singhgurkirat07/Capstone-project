import sqlite3
import os
import uuid
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phoenix.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # Projects table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL
    );
    """)
    
    # Tasks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        project_id TEXT,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'todo',
        priority TEXT DEFAULT 'medium',
        created_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    );
    """)
    
    # Notes table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id TEXT PRIMARY KEY,
        project_id TEXT,
        title TEXT,
        content TEXT NOT NULL,
        type TEXT DEFAULT 'note',
        created_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE SET NULL
    );
    """)
    
    # Knowledge Documents table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_docs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_type TEXT NOT NULL,
        size_bytes INTEGER,
        chunk_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """)
    
    # Knowledge Chunks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        text TEXT NOT NULL,
        FOREIGN KEY (doc_id) REFERENCES knowledge_docs (id) ON DELETE CASCADE
    );
    """)
    
    # Usage tracking table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usage_log (
        id TEXT PRIMARY KEY,
        date TEXT NOT NULL,
        request_count INTEGER DEFAULT 0,
        max_requests INTEGER DEFAULT 50
    );
    """)
    
    # Check if a default project exists, if not, create one
    cursor.execute("SELECT COUNT(*) as count FROM projects")
    if cursor.fetchone()["count"] == 0:
        cursor.execute(
            "INSERT INTO projects (id, name, description, status, created_at) VALUES (?, ?, ?, ?, ?)",
            ("default", "Inbox / General Project", "Default workspace for notes and tasks.", "active", datetime.now().isoformat())
        )
        
    conn.commit()
    conn.close()

# ── Projects ──
def list_projects():
    conn = get_db_connection()
    projects = [dict(row) for row in conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()]
    conn.close()
    return projects

def create_project(name, description=""):
    pid = str(uuid.uuid4())
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO projects (id, name, description, created_at) VALUES (?, ?, ?, ?)",
        (pid, name, description, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return pid

def delete_project(pid):
    if pid == "default":
        return False
    conn = get_db_connection()
    conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return True

# ── Tasks ──
def list_tasks(project_id=None):
    conn = get_db_connection()
    if project_id:
        rows = conn.execute("SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
    else:
        rows = conn.execute("SELECT t.*, p.name as project_name FROM tasks t LEFT JOIN projects p ON t.project_id = p.id ORDER BY t.created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def create_task(title, description="", project_id="default", priority="medium", status="todo"):
    tid = str(uuid.uuid4())
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO tasks (id, project_id, title, description, priority, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tid, project_id or "default", title, description, priority, status, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return tid

def update_task_status(tid, status):
    conn = get_db_connection()
    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, tid))
    conn.commit()
    conn.close()

def delete_task(tid):
    conn = get_db_connection()
    conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
    conn.commit()
    conn.close()

# ── Notes ──
def list_notes(project_id=None):
    conn = get_db_connection()
    if project_id:
        rows = conn.execute("SELECT * FROM notes WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
    else:
        rows = conn.execute("SELECT n.*, p.name as project_name FROM notes n LEFT JOIN projects p ON n.project_id = p.id ORDER BY n.created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def create_note(title, content, project_id="default", note_type="note"):
    nid = str(uuid.uuid4())
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO notes (id, project_id, title, content, type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (nid, project_id or "default", title, content, note_type, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return nid

def delete_note(nid):
    conn = get_db_connection()
    conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
    conn.commit()
    conn.close()

# ── Knowledge / RAG ──
def add_knowledge_doc(name, file_path, file_type, size_bytes, chunks):
    doc_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO knowledge_docs (id, name, file_path, file_type, size_bytes, chunk_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (doc_id, name, file_path, file_type, size_bytes, len(chunks), datetime.now().isoformat())
    )
    for chunk in chunks:
        chunk_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO knowledge_chunks (id, doc_id, text) VALUES (?, ?, ?)",
            (chunk_id, doc_id, chunk)
        )
    conn.commit()
    conn.close()
    return doc_id

def list_knowledge_docs():
    conn = get_db_connection()
    docs = [dict(row) for row in conn.execute("SELECT * FROM knowledge_docs ORDER BY created_at DESC").fetchall()]
    conn.close()
    return docs

def delete_knowledge_doc(doc_id):
    conn = get_db_connection()
    # Chunk table has CASCADE delete linked to doc_id
    conn.execute("DELETE FROM knowledge_docs WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()

def query_knowledge_chunks(query_text, limit=5):
    conn = get_db_connection()
    # Simple token-matching / keyword search fallback for RAG
    # We split the query into keywords and find rows matching any of the words,
    # ranked by the count of matches.
    keywords = [kw.strip() for kw in query_text.lower().split() if len(kw.strip()) > 2]
    if not keywords:
        # Fallback to general substring search
        rows = conn.execute(
            "SELECT c.text, d.name as doc_name FROM knowledge_chunks c JOIN knowledge_docs d ON c.doc_id = d.id WHERE c.text LIKE ? LIMIT ?",
            (f"%{query_text}%", limit)
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
        
    # Match keywords using sqlite functions
    # Construct query: SUM(c.text LIKE '%word%')
    select_match = " + ".join([f"(case when lower(c.text) like ? then 1 else 0 end)" for _ in keywords])
    params = [f"%{kw}%" for kw in keywords]
    
    sql = f"""
    SELECT c.text, d.name as doc_name, ({select_match}) as match_count 
    FROM knowledge_chunks c 
    JOIN knowledge_docs d ON c.doc_id = d.id 
    WHERE match_count > 0 
    ORDER BY match_count DESC 
    LIMIT ?
    """
    rows = conn.execute(sql, params + [limit]).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ── Usage Tracking ──
def get_today_usage():
    """Returns today's usage stats: {date, used, limit, remaining, percentage}."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM usage_log WHERE date = ?", (today,)).fetchone()
    if not row:
        row_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO usage_log (id, date, request_count, max_requests) VALUES (?, ?, 0, 50)",
            (row_id, today)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM usage_log WHERE date = ?", (today,)).fetchone()
    conn.close()
    row = dict(row)
    used = row["request_count"]
    limit = row["max_requests"]
    remaining = max(0, limit - used)
    percentage = round((used / limit) * 100, 1) if limit > 0 else 100.0
    return {
        "date": today,
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "percentage": percentage
    }

def increment_usage():
    """Increments today's request_count by 1. Returns True if under limit, False if over."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM usage_log WHERE date = ?", (today,)).fetchone()
    if not row:
        row_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO usage_log (id, date, request_count, max_requests) VALUES (?, ?, 0, 50)",
            (row_id, today)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM usage_log WHERE date = ?", (today,)).fetchone()
    row = dict(row)
    new_count = row["request_count"] + 1
    conn.execute("UPDATE usage_log SET request_count = ? WHERE date = ?", (new_count, today))
    conn.commit()
    conn.close()
    return new_count <= row["max_requests"]

def set_usage_limit(new_limit):
    """Updates max_requests for today's row."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM usage_log WHERE date = ?", (today,)).fetchone()
    if not row:
        row_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO usage_log (id, date, request_count, max_requests) VALUES (?, ?, 0, ?)",
            (row_id, today, new_limit)
        )
    else:
        conn.execute("UPDATE usage_log SET max_requests = ? WHERE date = ?", (new_limit, today))
    conn.commit()
    conn.close()

# Initialize on import
init_db()
