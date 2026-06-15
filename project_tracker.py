import sqlite3
import json
import os
from datetime import datetime, date
from flask import Flask, request, jsonify, g, send_from_directory
import anthropic

# Bulletproof path - works on Windows, Mac, Linux regardless of where you run from
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
DB_PATH = os.path.join(BASE_DIR, 'projects.db')

app = Flask(__name__, static_folder=STATIC_DIR)

# ── Database ───────────────────────────────────────────────────────────

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS columns_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            config TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT NOT NULL,
            period_label TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS project_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL UNIQUE,
            sections TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
    """)
    cur = db.execute("SELECT COUNT(*) FROM columns_config")
    if cur.fetchone()[0] == 0:
        default_cols = [
            {"id":"date",     "label":"Date",        "type":"date",    "visible":True},
            {"id":"project",  "label":"Project",     "type":"text",    "visible":True},
            {"id":"purpose",  "label":"Purpose",     "type":"text",    "visible":True},
            {"id":"agent",    "label":"Agent type",  "type":"text",    "visible":True},
            {"id":"tools",    "label":"Tools used",  "type":"text",    "visible":True},
            {"id":"learning", "label":"Learning",    "type":"text",    "visible":True},
            {"id":"target",   "label":"Target date", "type":"date",    "visible":True},
            {"id":"status",   "label":"Status",      "type":"status",  "visible":True},
            {"id":"pct",      "label":"% done",      "type":"percent", "visible":True},
            {"id":"comments", "label":"Comments",    "type":"text",    "visible":True},
        ]
        db.execute("INSERT INTO columns_config (id, config) VALUES (1, ?)", [json.dumps(default_cols)])
    cur = db.execute("SELECT COUNT(*) FROM projects")
    if cur.fetchone()[0] == 0:
        samples = [
            {"date":"2024-06-01","project":"AI Chatbot","purpose":"Customer support automation","agent":"LLM Agent","tools":"Claude API, LangChain","learning":"Prompt engineering basics","target":"2024-07-15","status":"in-progress","pct":60,"comments":"Going well"},
            {"date":"2024-06-05","project":"Data Pipeline","purpose":"ETL automation","agent":"Code agent","tools":"Python, Pandas, Airflow","learning":"DAG design patterns","target":"2024-06-30","status":"testing","pct":90,"comments":"Needs QA sign-off"},
            {"date":"2024-06-10","project":"RAG System","purpose":"Document Q&A","agent":"RAG Agent","tools":"Embeddings, Pinecone","learning":"Vector search tuning","target":"2024-08-01","status":"not-started","pct":0,"comments":"Waiting for data"},
        ]
        for s in samples:
            db.execute("INSERT INTO projects (data, created_at, updated_at) VALUES (?, datetime('now'), datetime('now'))", [json.dumps(s)])
    db.commit()
    db.close()

# ── Projects API ───────────────────────────────────────────────────────

@app.route('/api/projects', methods=['GET'])
def get_projects():
    db = get_db()
    rows = db.execute("SELECT id, data, created_at, updated_at FROM projects ORDER BY id").fetchall()
    result = []
    for r in rows:
        d = json.loads(r['data'])
        d['_id'] = r['id']
        d['_created'] = r['created_at']
        d['_updated'] = r['updated_at']
        # flag whether notes exist
        n = db.execute("SELECT id FROM project_notes WHERE project_id=?", [r['id']]).fetchone()
        d['_has_notes'] = n is not None
        result.append(d)
    return jsonify(result)

@app.route('/api/projects/<int:pid>', methods=['GET'])
def get_project(pid):
    db = get_db()
    r = db.execute("SELECT id, data, created_at, updated_at FROM projects WHERE id=?", [pid]).fetchone()
    if not r: return jsonify({"error": "Not found"}), 404
    d = json.loads(r['data'])
    d['_id'] = r['id']
    d['_created'] = r['created_at']
    d['_updated'] = r['updated_at']
    return jsonify(d)

@app.route('/api/projects', methods=['POST'])
def create_project():
    db = get_db()
    data = request.json or {}
    data.setdefault('date', date.today().isoformat())
    data.setdefault('status', 'not-started')
    data.setdefault('pct', 0)
    cur = db.execute("INSERT INTO projects (data, created_at, updated_at) VALUES (?, datetime('now'), datetime('now'))", [json.dumps(data)])
    db.commit()
    data['_id'] = cur.lastrowid
    return jsonify(data), 201

@app.route('/api/projects/<int:pid>', methods=['PUT'])
def update_project(pid):
    db = get_db()
    data = request.json or {}
    data.pop('_id', None); data.pop('_created', None); data.pop('_updated', None); data.pop('_has_notes', None)
    db.execute("UPDATE projects SET data=?, updated_at=datetime('now') WHERE id=?", [json.dumps(data), pid])
    db.commit()
    return jsonify({"ok": True})

@app.route('/api/projects/<int:pid>', methods=['DELETE'])
def delete_project(pid):
    db = get_db()
    db.execute("DELETE FROM project_notes WHERE project_id=?", [pid])
    db.execute("DELETE FROM projects WHERE id=?", [pid])
    db.commit()
    return jsonify({"ok": True})

# ── Project Notes API ──────────────────────────────────────────────────

@app.route('/api/notes/<int:pid>', methods=['GET'])
def get_notes(pid):
    db = get_db()
    row = db.execute("SELECT sections, updated_at FROM project_notes WHERE project_id=?", [pid]).fetchone()
    if not row:
        return jsonify({"sections": [], "updated_at": None})
    return jsonify({"sections": json.loads(row['sections']), "updated_at": row['updated_at']})

@app.route('/api/notes/<int:pid>', methods=['PUT'])
def save_notes(pid):
    db = get_db()
    sections = request.json.get('sections', [])
    db.execute("""
        INSERT INTO project_notes (project_id, sections, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(project_id) DO UPDATE SET sections=excluded.sections, updated_at=excluded.updated_at
    """, [pid, json.dumps(sections)])
    db.commit()
    return jsonify({"ok": True})

# ── Columns API ────────────────────────────────────────────────────────

@app.route('/api/columns', methods=['GET'])
def get_columns():
    db = get_db()
    row = db.execute("SELECT config FROM columns_config WHERE id=1").fetchone()
    return jsonify(json.loads(row['config']) if row else [])

@app.route('/api/columns', methods=['PUT'])
def save_columns():
    db = get_db()
    db.execute("INSERT OR REPLACE INTO columns_config (id, config) VALUES (1, ?)", [json.dumps(request.json)])
    db.commit()
    return jsonify({"ok": True})

# ── AI Summary API ─────────────────────────────────────────────────────

@app.route('/api/summary', methods=['POST'])
def generate_summary():
    body = request.json or {}
    period = body.get('period', 'month')
    period_label = body.get('label', 'This period')
    api_key = body.get('api_key', '').strip()
    if not api_key:
        return jsonify({"error": "Anthropic API key required"}), 400

    db = get_db()
    rows = db.execute("SELECT id, data, created_at FROM projects ORDER BY id").fetchall()
    projects = []
    for r in rows:
        d = json.loads(r['data']); d['_id'] = r['id']; d['_created'] = r['created_at']
        projects.append(d)

    now = datetime.now()
    if period == 'month':
        filtered = [p for p in projects if _in_current_month(p.get('date','') or p.get('_created',''), now)] or projects
    elif period == 'quarter':
        filtered = [p for p in projects if _in_current_quarter(p.get('date','') or p.get('_created',''), now)] or projects
    else:
        filtered = projects

    cols = json.loads(db.execute("SELECT config FROM columns_config WHERE id=1").fetchone()['config'])
    rows_text = []
    for p in filtered:
        parts = [f"{c['label']}: {p.get(c['id'],'')}" for c in cols if str(p.get(c['id'],'') or '').strip()]
        rows_text.append("• " + " | ".join(parts))

    prompt = f"""You are an AI assistant helping a developer review their project tracking data.

Period: {period_label}
Total projects: {len(filtered)}

Project data:
{chr(10).join(rows_text)}

Write a concise, insightful summary report with these sections:

## Executive Summary
## Highlights
## In Progress
## Concerns & Blockers
## Key Learnings
## Tools & Technologies
## Recommendations

Be specific, reference actual project names. Professional but conversational tone."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(model="claude-sonnet-4-6", max_tokens=1500,
            messages=[{"role": "user", "content": prompt}])
        content = message.content[0].text
        db.execute("INSERT INTO summaries (period, period_label, content, created_at) VALUES (?, ?, ?, datetime('now'))",
            [period, period_label, content])
        db.commit()
        return jsonify({"summary": content, "project_count": len(filtered)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/summaries', methods=['GET'])
def get_summaries():
    db = get_db()
    rows = db.execute("SELECT id, period_label, created_at FROM summaries ORDER BY id DESC LIMIT 20").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/summaries/<int:sid>', methods=['GET'])
def get_summary(sid):
    db = get_db()
    row = db.execute("SELECT * FROM summaries WHERE id=?", [sid]).fetchone()
    if not row: return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))

# ── Helpers ────────────────────────────────────────────────────────────

def _parse_date(s):
    try: return datetime.strptime(s[:10], '%Y-%m-%d')
    except: return None

def _in_current_month(s, now):
    d = _parse_date(s)
    return d and d.year == now.year and d.month == now.month

def _in_current_quarter(s, now):
    d = _parse_date(s)
    if not d: return False
    return d.year == now.year and (d.month-1)//3 == (now.month-1)//3

# ── Static files ───────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/project/<int:pid>')
def project_detail(pid):
    return send_from_directory(STATIC_DIR, 'project.html')

@app.route('/debug')
def debug_info():
    files = os.listdir(STATIC_DIR) if os.path.isdir(STATIC_DIR) else []
    return jsonify({
        'base_dir': BASE_DIR,
        'static_dir': STATIC_DIR,
        'static_dir_exists': os.path.isdir(STATIC_DIR),
        'static_files': files,
    })

if __name__ == '__main__':
    init_db()
    print("\n✅ Project Tracker running at http://localhost:5000")
    print("📁 Base folder : " + BASE_DIR)
    print("📂 Static folder: " + STATIC_DIR + "\n")
    app.run(debug=True, port=5000)
