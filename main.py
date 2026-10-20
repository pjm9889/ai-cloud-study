import csv
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from gpt_module import GPTModule
from naver_blog_routes import router as naver_blog_router

BASE = Path(__file__).resolve().parent; DB_PATH = BASE / 'data' / 'sessions.db'; CATEGORY_PATH = BASE / 'data' / 'category_rules.json'; DB_PATH.parent.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='BSSBU Vision Ops'); gpt = GPTModule()
app.include_router(naver_blog_router)
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')

class SessionPayload(BaseModel):
    session_id: Optional[str] = None
    detections: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    messages: list[dict] = Field(default_factory=list)
    finalized: bool = False
class ChatPayload(SessionPayload):
    message: str
    kind: str = 'chat'
class CategoryPayload(BaseModel):
    rules: dict[str, list[str]]
class TxtSqlPayload(BaseModel):
    table_name: str
    text: str
    delimiter: Optional[str] = None
class TextSqlPayload(BaseModel):
    prompt: Optional[str] = None
    sql: Optional[str] = None
def now(): return datetime.now(timezone.utc).isoformat()
def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        finalized INTEGER NOT NULL DEFAULT 0, detections_json TEXT NOT NULL,
        events_json TEXT NOT NULL, messages_json TEXT NOT NULL)'''); con.commit()
init_db()
def admin_guard(request: Request):
    if not ADMIN_PASSWORD or not secrets.compare_digest(request.headers.get('x-admin-password', ''), ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail='관리자 인증이 필요합니다.')
def safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[^0-9A-Za-z가-힣_]+', '_', value.strip()).strip('_')
    if not cleaned: cleaned = fallback
    if cleaned[0].isdigit(): cleaned = '_' + cleaned
    return cleaned[:48]
def load_category_rules():
    if CATEGORY_PATH.exists():
        try: return json.loads(CATEGORY_PATH.read_text(encoding='utf-8'))
        except json.JSONDecodeError: pass
    return {}
def db_schema():
    with sqlite3.connect(DB_PATH) as con:
        tables = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        return {name: [{'name': row[1], 'type': row[2]} for row in con.execute(f'PRAGMA table_info("{name.replace(chr(34), chr(34)*2)}")').fetchall()] for (name,) in tables}
def validate_admin_sql(sql: str):
    statement = sql.strip().rstrip(';').strip()
    if not statement: raise HTTPException(status_code=400, detail='실행할 SQL이 없습니다.')
    if ';' in statement: raise HTTPException(status_code=400, detail='한 번에 하나의 SQL만 실행할 수 있습니다.')
    if re.match(r'(?is)^(drop|alter|attach|detach|vacuum|reindex)\b', statement):
        raise HTTPException(status_code=400, detail='안전을 위해 DROP/ALTER/ATTACH/DETACH/VACUUM/REINDEX는 실행할 수 없습니다.')
    return statement
@app.get('/')
async def home(): return FileResponse(BASE / 'index.html')
@app.get('/admin')
async def admin_page(): return FileResponse(BASE / 'admin.html')
@app.get('/mcp')
async def mcp_page(): return FileResponse(BASE / 'mcp.html')
@app.get('/guide')
@app.get('/guide/')
async def guide_page(): return FileResponse(BASE / 'guide.html')
@app.get('/guide.html')
async def guide_html_page(): return FileResponse(BASE / 'guide.html')
@app.get('/health')
async def health(): return {'status':'ok','gpt_configured':gpt.available}
@app.get('/api/admin/categories')
async def get_categories(request: Request):
    admin_guard(request); return {'ok': True, 'rules': load_category_rules()}
@app.post('/api/admin/categories')
async def save_categories(payload: CategoryPayload, request: Request):
    admin_guard(request)
    clean = {safe_name(k, '기타'): [str(x).strip().lower() for x in v if str(x).strip()][:100] for k, v in payload.rules.items() if str(k).strip()}
    CATEGORY_PATH.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'ok': True, 'rules': clean}
@app.post('/api/admin/txt-to-sql')
async def txt_to_sql(payload: TxtSqlPayload, request: Request):
    admin_guard(request)
    lines = [line for line in payload.text.replace('\r\n', '\n').split('\n') if line.strip()]
    if len(lines) < 2: raise HTTPException(status_code=400, detail='헤더와 데이터가 포함된 TXT가 필요합니다.')
    delimiter = payload.delimiter or ('\t' if '\t' in lines[0] else ('|' if '|' in lines[0] else ','))
    rows = list(csv.reader(io.StringIO('\n'.join(lines)), delimiter=delimiter))
    headers = [safe_name(h, f'column_{i+1}') for i, h in enumerate(rows[0])]
    unique = []; seen = set()
    for h in headers:
        base, n = h, 2
        while h in seen: h = f'{base}_{n}'; n += 1
        seen.add(h); unique.append(h)
    table = safe_name(payload.table_name, 'imported_text')
    q = lambda name: '"' + name.replace('"', '""') + '"'
    with sqlite3.connect(DB_PATH) as con:
        con.execute(f'CREATE TABLE IF NOT EXISTS {q(table)} ({", ".join(q(h) + " TEXT" for h in unique)})')
        values = [tuple((row + [''] * len(unique))[:len(unique)]) for row in rows[1:]]
        con.executemany(f'INSERT INTO {q(table)} ({", ".join(q(h) for h in unique)}) VALUES ({", ".join("?" for _ in unique)})', values)
        con.commit()
    return {'ok': True, 'table': table, 'columns': unique, 'rows_inserted': len(values)}
@app.post('/api/admin/text-to-sql')
async def text_to_sql(payload: TextSqlPayload, request: Request):
    admin_guard(request)
    if not payload.prompt or not payload.prompt.strip(): raise HTTPException(status_code=400, detail='자연어 요청을 입력하세요.')
    try:
        sql = await gpt.sql_from_text(payload.prompt, db_schema())
        return {'ok': True, 'sql': validate_admin_sql(sql)}
    except RuntimeError as exc: raise HTTPException(status_code=503, detail=str(exc))
@app.post('/api/admin/execute-sql')
async def execute_admin_sql(payload: TextSqlPayload, request: Request):
    admin_guard(request)
    statement = validate_admin_sql(payload.sql or '')
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute(statement)
        if statement.lstrip().lower().startswith('select'):
            rows = [dict(row) for row in cur.fetchall()]
            columns = [d[0] for d in cur.description or []]
            return {'ok': True, 'columns': columns, 'rows': rows, 'row_count': len(rows)}
        con.commit()
        return {'ok': True, 'row_count': cur.rowcount if cur.rowcount >= 0 else 0, 'message': 'SQL을 실행했습니다.'}
@app.get('/api/admin/database')
async def inspect_database(request: Request, table: Optional[str] = None, limit: int = 50):
    admin_guard(request)
    limit = max(1, min(limit, 200))
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        names = [row['name'] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if not names: return {'ok': True, 'tables': [], 'table': None, 'columns': [], 'rows': []}
        selected = table if table in names else names[0]
        qname = '"' + selected.replace('"', '""') + '"'
        columns = [dict(row) for row in con.execute(f'PRAGMA table_info({qname})')]
        rows = [dict(row) for row in con.execute(f'SELECT * FROM {qname} LIMIT ?', (limit,))]
    return {'ok': True, 'tables': names, 'table': selected, 'columns': columns, 'rows': rows}
@app.post('/api/sessions')
async def save_session(payload: SessionPayload):
    sid = payload.session_id or uuid.uuid4().hex[:12]; stamp = now()
    with sqlite3.connect(DB_PATH) as con:
        con.execute('''INSERT INTO sessions VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(session_id) DO UPDATE SET updated_at=excluded.updated_at,
        finalized=excluded.finalized,detections_json=excluded.detections_json,
        events_json=excluded.events_json,messages_json=excluded.messages_json''',
        (sid,stamp,stamp,int(payload.finalized),json.dumps(payload.detections,ensure_ascii=False),
         json.dumps(payload.events,ensure_ascii=False),json.dumps(payload.messages,ensure_ascii=False))); con.commit()
    return {'ok':True,'session_id':sid}
@app.post('/api/chat')
async def chat(payload: ChatPayload):
    try: return {'ok':True,'reply':await gpt.reply(payload.message,payload.detections,payload.events,payload.messages,payload.kind)}
    except RuntimeError as exc: raise HTTPException(status_code=503, detail=str(exc))
