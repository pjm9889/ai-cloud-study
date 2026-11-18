"""
자가진단 체크리스트 (/checklist)

Day별 작업이 끝날 때마다 "GPT(LLM) 도움 없이 이 정도는 할 수 있다"를 개인별로 체크하고,
같은 항목을 날짜를 바꿔 다시 점검하며, 과정 전체(역량 영역별)로 쌓아 보는 기능입니다.

- 학생: 강사가 등록한 이름으로 로그인, 첫 로그인 때 자기 비밀번호를 정함
- 점검 기록: (학생, 항목, 점검 날짜)마다 한 줄. 가장 최근 날짜의 값이 '현재 상태'
- 다시 점검: 전체 / 🟡·⬜만 / ⬜만 / 미응답만 골라서 다시 체크
- 강사: ADMIN_PASSWORD 환경변수로 로그인 (main.py와 같은 값). 기준 날짜를 바꿔 그날까지의 상태를 볼 수 있음
- 데이터: data/checklist.db (SQLite), 항목: data/checklist_items.yaml

main.py에 두 줄만 추가하면 됩니다.
    from checklist_routes import router as checklist_router
    app.include_router(checklist_router)

환경변수 (선택)
    CHECKLIST_SECRET         로그인 쿠키 서명 키 (없으면 data/.checklist_secret 자동 생성)
    CHECKLIST_COOKIE_SECURE  HTTPS로 운영하면 1
    CHECKLIST_DB             DB 경로 (기본 data/checklist.db)
    CHECKLIST_ITEMS          항목 파일 경로 (기본 data/checklist_items.yaml)
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import os
import secrets
import sqlite3
import time
from collections import OrderedDict, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("CHECKLIST_DB", str(BASE / "data" / "checklist.db")))
ITEMS_PATH = Path(os.getenv("CHECKLIST_ITEMS", str(BASE / "data" / "checklist_items.yaml")))
SECRET_FILE = BASE / "data" / ".checklist_secret"
COOKIE_SECURE = os.getenv("CHECKLIST_COOKIE_SECURE", "0") == "1"
P = "/checklist"
SESSION_SEC = 60 * 60 * 24 * 30
ADMIN_SEC = 60 * 60 * 12
MIN_PW = 4
KST = timezone(timedelta(hours=9))

ROLES = {"rec": "🔍 기록 담당", "doc": "📘 문서 담당"}
ROLE_ALIASES = {"rec": "rec", "기록": "rec", "기록담당": "rec", "🔍": "rec",
                "doc": "doc", "문서": "doc", "문서담당": "doc", "📘": "doc"}
SCOPES = {"common": "👥 공통", "rec": "🔍 기록 담당", "doc": "📘 문서 담당", "peer": "🔁 상대 영역"}
STATUS = {2: "혼자 할 수 있다", 1: "자료를 보면 할 수 있다", 0: "아직 어렵다"}
ICON = {2: "✅", 1: "🟡", 0: "⬜", None: "·"}
MODES = OrderedDict([("all", "전체 다시 확인"), ("review", "🟡·⬜ 다시 보기"),
                     ("hard", "⬜ 아직만"), ("blank", "미응답만")])

router = APIRouter(prefix=P, include_in_schema=False)
templates = Jinja2Templates(directory=str(BASE / "templates"))

DAYS: "OrderedDict[int, str]" = OrderedDict()      # day -> 제목
DAY_DATES: "dict[int, str]" = {}                    # day -> 수업 날짜 (선택)
AREAS: "OrderedDict[str, dict]" = OrderedDict()     # 이름 -> {name, course, desc}


# ================================================================ DB

@contextmanager
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS ck_users (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  team       TEXT,
  role       TEXT,
  pw_hash    TEXT,
  created_at TEXT NOT NULL,
  last_login TEXT
);
CREATE TABLE IF NOT EXISTS ck_items (
  id            TEXT PRIMARY KEY,
  day           INTEGER NOT NULL,
  scope         TEXT NOT NULL,
  section       TEXT NOT NULL,
  section_title TEXT NOT NULL,
  area          TEXT NOT NULL,
  text          TEXT NOT NULL,
  ord           INTEGER NOT NULL,
  active        INTEGER NOT NULL DEFAULT 1
);
-- (학생, 항목, 점검 날짜)마다 한 줄. 같은 날 다시 누르면 그 날짜 값이 바뀐다.
CREATE TABLE IF NOT EXISTS ck_entries (
  user_id    INTEGER NOT NULL REFERENCES ck_users(id) ON DELETE CASCADE,
  item_id    TEXT NOT NULL REFERENCES ck_items(id),
  check_date TEXT NOT NULL,
  status     INTEGER,
  note       TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, item_id, check_date)
);
CREATE INDEX IF NOT EXISTS idx_ck_entries_date ON ck_entries(check_date);
-- 모든 변경 기록 (같은 날짜 안에서 바꾼 것까지)
CREATE TABLE IF NOT EXISTS ck_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES ck_users(id) ON DELETE CASCADE,
  item_id    TEXT NOT NULL,
  check_date TEXT,
  old_status INTEGER,
  new_status INTEGER,
  note       TEXT,
  at         TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return datetime.now(KST).date().isoformat()


def valid_date(s: Optional[str]) -> Optional[str]:
    try:
        d = date.fromisoformat((s or "").strip())
    except ValueError:
        return None
    if d.year < 2020 or d.isoformat() > today():
        return None
    return d.isoformat()


def load_items(c: sqlite3.Connection) -> int:
    """yaml의 항목을 DB와 맞춘다. yaml에서 빠진 항목은 숨김(active=0). 체크 기록은 남는다."""
    data = yaml.safe_load(ITEMS_PATH.read_text(encoding="utf-8"))
    days, ddates, areas = OrderedDict(), {}, OrderedDict()
    for a in data.get("areas") or []:
        areas[a["name"]] = {"name": a["name"], "course": a.get("course", ""), "desc": a.get("desc", "")}
    rows, seen, ord_ = [], set(), 0
    for d in data["days"]:
        day = int(d["day"])
        days[day] = d.get("title", f"Day {day}")
        if d.get("date"):
            ddates[day] = str(d["date"])
        for s in d.get("sections") or []:
            if s["scope"] not in SCOPES:
                raise ValueError(f"알 수 없는 scope: {s['scope']}")
            for it in s.get("items") or []:
                ord_ += 1
                iid = str(it["id"])
                if iid in seen:
                    raise ValueError(f"항목 id 중복: {iid}")
                seen.add(iid)
                area = it.get("area") or s.get("area") or "기타"
                areas.setdefault(area, {"name": area, "course": "", "desc": ""})
                rows.append((iid, day, s["scope"], s["key"], s["title"], area, str(it["text"]).strip(), ord_))
    for r in rows:
        c.execute("""INSERT INTO ck_items (id, day, scope, section, section_title, area, text, ord, active)
                     VALUES (?,?,?,?,?,?,?,?,1)
                     ON CONFLICT(id) DO UPDATE SET day=excluded.day, scope=excluded.scope,
                       section=excluded.section, section_title=excluded.section_title,
                       area=excluded.area, text=excluded.text, ord=excluded.ord, active=1""", r)
    if seen:
        c.execute(f"UPDATE ck_items SET active=0 WHERE id NOT IN ({','.join('?' * len(seen))})", tuple(seen))
    DAYS.clear(); DAYS.update(days)
    DAY_DATES.clear(); DAY_DATES.update(ddates)
    AREAS.clear(); AREAS.update(areas)
    return len(seen)


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)
        cols = [r[1] for r in c.execute("PRAGMA table_info(ck_log)")]
        if "check_date" not in cols:
            c.execute("ALTER TABLE ck_log ADD COLUMN check_date TEXT")
        # 이전 버전(날짜 없는 ck_checks) 기록 옮기기
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ck_checks'").fetchone():
            c.execute("""INSERT OR IGNORE INTO ck_entries (user_id, item_id, check_date, status, note, updated_at)
                         SELECT user_id, item_id, substr(updated_at, 1, 10), status, note, updated_at FROM ck_checks""")
            c.execute("ALTER TABLE ck_checks RENAME TO ck_checks_old")
        load_items(c)


# ================================================================ 보안 도우미

def _secret() -> bytes:
    v = os.getenv("CHECKLIST_SECRET")
    if v:
        return v.encode()
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text().strip().encode()
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    v = secrets.token_hex(32)
    SECRET_FILE.write_text(v)
    try:
        os.chmod(SECRET_FILE, 0o600)
    except OSError:
        pass
    return v.encode()


SECRET = _secret()


def _mac(v: str) -> str:
    return hmac.new(SECRET, v.encode(), hashlib.sha256).hexdigest()[:40]


def sign(payload: str) -> str:
    v = f"{payload}:{int(time.time())}"
    return f"{v}.{_mac(v)}"


def unsign(tok: Optional[str], max_age: int) -> Optional[str]:
    if not tok or "." not in tok:
        return None
    v, _, sig = tok.rpartition(".")
    if not hmac.compare_digest(sig, _mac(v)):
        return None
    payload, _, ts = v.rpartition(":")
    try:
        if time.time() - int(ts) > max_age:
            return None
    except ValueError:
        return None
    return payload


def hash_pw(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"pbkdf2${salt}${h}"


def check_pw(pw: str, stored: Optional[str]) -> bool:
    try:
        _, salt, h = (stored or "").split("$")
    except ValueError:
        return False
    return hmac.compare_digest(h, hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex())


def pw_tag(stored: Optional[str]) -> str:
    """비밀번호가 바뀌거나 초기화되면 기존 로그인 쿠키가 무효가 되도록 쿠키에 넣는 표식."""
    return (stored or "").split("$")[1][:8] if stored and "$" in stored else ""


def admin_password() -> str:
    return os.getenv("ADMIN_PASSWORD", "")


def admin_tag() -> str:
    return hashlib.sha256(("ck-admin" + admin_password()).encode()).hexdigest()[:8]


def csrf(request: Request, kind: str) -> str:
    base = request.cookies.get("ck_admin" if kind == "admin" else "ck_session") or ""
    return _mac("csrf|" + kind + "|" + base)[:32]


async def read_form(request: Request) -> dict:
    """python-multipart 없이 일반 폼(urlencoded)을 읽는다."""
    body = (await request.body()).decode("utf-8", "replace")
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


def csrf_ok(request: Request, kind: str, form: Optional[dict] = None) -> bool:
    sent = request.headers.get("x-csrf-token") or (form or {}).get("csrf", "")
    return bool(sent) and hmac.compare_digest(sent, csrf(request, kind))


FAILS: "defaultdict[tuple, list]" = defaultdict(list)
LOCK_N, LOCK_SEC = 5, 300


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0] if fwd else (request.client.host if request.client else "")).strip()


def locked(key: tuple) -> bool:
    t = time.time()
    FAILS[key] = [x for x in FAILS[key] if t - x < LOCK_SEC]
    return len(FAILS[key]) >= LOCK_N


def go(path: str, msg: str = "", err: str = "") -> RedirectResponse:
    q = urlencode({k: v for k, v in (("msg", msg), ("err", err)) if v})
    return RedirectResponse(f"{P}{path}" + (("&" if "?" in path else "?") + q if q else ""), status_code=303)


def set_cookie(resp: Response, name: str, value: str, max_age: int) -> None:
    resp.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax",
                    secure=COOKIE_SECURE, path=P)


def mmdd(d: Optional[str]) -> str:
    return f"{int(d[5:7])}/{int(d[8:10])}" if d and len(d) >= 10 else ""


def page(request: Request, name: str, kind: str = "user", **ctx):
    ctx.update(request=request, P=P, csrf=csrf(request, kind), roles=ROLES, scopes=SCOPES,
               status=STATUS, icon=ICON, days=DAYS, day_dates=DAY_DATES, modes=MODES, mmdd=mmdd,
               today=today(), msg=request.query_params.get("msg", ""),
               err=request.query_params.get("err", ""))
    return templates.TemplateResponse(request=request, name=f"checklist/{name}", context=ctx)


def current_user(request: Request, c: sqlite3.Connection):
    payload = unsign(request.cookies.get("ck_session"), SESSION_SEC)
    if not payload or not payload.startswith("u"):
        return None
    try:
        uid_s, tag = payload[1:].split("|", 1)
        u = c.execute("SELECT * FROM ck_users WHERE id=?", (int(uid_s),)).fetchone()
    except (ValueError, sqlite3.Error):
        return None
    if not u or not u["pw_hash"] or pw_tag(u["pw_hash"]) != tag:
        return None
    return u


def is_admin(request: Request) -> bool:
    if not admin_password():
        return False
    return unsign(request.cookies.get("ck_admin"), ADMIN_SEC) == "admin|" + admin_tag()


def visible_scopes(role: Optional[str]) -> tuple:
    return ("common", role, "peer") if role in ROLES else tuple(SCOPES)


def pick_day(request: Request, allow_all: bool = True) -> int:
    """0 = 전체 Day"""
    raw = request.query_params.get("day")
    try:
        d = int(raw) if raw is not None else -1
    except ValueError:
        d = -1
    if d == 0 and allow_all:
        return 0
    if d in DAYS:
        return d
    return next(iter(DAYS)) if DAYS else 1


# ================================================================ 상태 계산

def items_for(c, day: int, role) -> list:
    sc = visible_scopes(role)
    q = f"SELECT * FROM ck_items WHERE active=1 AND scope IN ({','.join('?' * len(sc))})"
    args: tuple = sc
    if day:
        q += " AND day=?"
        args = (*sc, day)
    return c.execute(q + " ORDER BY ord", args).fetchall()


def latest_map(c, uid: int, as_of: Optional[str] = None) -> dict:
    """항목별 가장 최근(as_of 이하) 점검 기록. 상태가 비어 있는 날(메모만)은 건너뛴다."""
    rows = c.execute("""SELECT * FROM ck_entries WHERE user_id=? AND status IS NOT NULL AND check_date<=?
                        ORDER BY check_date, updated_at""", (uid, as_of or "9999-12-31")).fetchall()
    out = {}
    for r in rows:
        out[r["item_id"]] = r
    return out


def latest_all(c, as_of: str) -> dict:
    """(user_id, item_id) -> 최근 기록 (강사 화면용)"""
    out = {}
    for r in c.execute("""SELECT * FROM ck_entries WHERE status IS NOT NULL AND check_date<=?
                          ORDER BY check_date, updated_at""", (as_of,)):
        out[(r["user_id"], r["item_id"])] = r
    return out


def history_map(c, uid: int) -> dict:
    out = defaultdict(list)
    for r in c.execute("SELECT * FROM ck_entries WHERE user_id=? ORDER BY check_date", (uid,)):
        out[r["item_id"]].append(r)
    return out


def hist_json(rows) -> list:
    return [{"d": r["check_date"], "md": mmdd(r["check_date"]), "s": r["status"], "n": r["note"] or ""} for r in rows]


def progress(items, lat: dict) -> dict:
    p = {"total": len(items), 2: 0, 1: 0, 0: 0}
    for it in items:
        r = lat.get(it["id"])
        if r is not None and r["status"] in (0, 1, 2):
            p[r["status"]] += 1
    return p


def mode_match(mode: str, r) -> bool:
    st = r["status"] if r is not None else None
    if mode == "review":
        return st in (0, 1)
    if mode == "hard":
        return st == 0
    if mode == "blank":
        return st is None
    return True


def area_summary(items, lat: dict, hist: Optional[dict] = None) -> list:
    """역량 영역별로 최신 상태를 모은다."""
    out = OrderedDict((n, {**a, 2: [], 1: [], 0: [], None: []}) for n, a in AREAS.items())
    for it in items:
        r = lat.get(it["id"])
        st = r["status"] if r is not None and r["status"] in (0, 1, 2) else None
        a = out.setdefault(it["area"], {"name": it["area"], "course": "", "desc": "", 2: [], 1: [], 0: [], None: []})
        row = dict(it)
        row["note"] = (r["note"] if r is not None else "") or ""
        row["last_date"] = r["check_date"] if r is not None else ""
        row["hist"] = [h for h in (hist or {}).get(it["id"], []) if h["status"] is not None]
        a[st].append(row)
    res = []
    for a in out.values():
        a["tot"] = sum(len(a[k]) for k in (2, 1, 0, None))
        if a["tot"]:
            a["pct"] = round(len(a[2]) * 100 / a["tot"])
            res.append(a)
    return res


# ================================================================ 학생: 로그인

@router.get("")
@router.get("/")
def login_page(request: Request):
    with db() as c:
        if current_user(request, c):
            return RedirectResponse(f"{P}/me", status_code=303)
    return page(request, "login.html")


@router.post("/login")
async def login(request: Request):
    f = await read_form(request)
    name, pw = (f.get("name") or "").strip(), f.get("password") or ""
    key = (name.lower(), client_ip(request))
    if locked(key):
        return go("/", err="로그인 시도가 너무 많습니다. 잠시 뒤 다시 시도하세요.")
    with db() as c:
        u = c.execute("SELECT * FROM ck_users WHERE name=?", (name,)).fetchone()
        if not u:
            FAILS[key].append(time.time())
            return go("/", err="등록되지 않은 이름입니다. 강사에게 등록을 요청하세요.")
        if not u["pw_hash"]:
            r = RedirectResponse(f"{P}/set-password", status_code=303)
            set_cookie(r, "ck_setpw", sign(f"s{u['id']}"), 600)
            return r
        if not check_pw(pw, u["pw_hash"]):
            FAILS[key].append(time.time())
            return go("/", err="비밀번호가 맞지 않습니다.")
        FAILS.pop(key, None)
        c.execute("UPDATE ck_users SET last_login=? WHERE id=?", (now(), u["id"]))
        r = RedirectResponse(f"{P}/me", status_code=303)
        set_cookie(r, "ck_session", sign(f"u{u['id']}|{pw_tag(u['pw_hash'])}"), SESSION_SEC)
        return r


def _setpw_user(request: Request, c):
    p = unsign(request.cookies.get("ck_setpw"), 600)
    if not p or not p.startswith("s"):
        return None
    u = c.execute("SELECT * FROM ck_users WHERE id=?", (int(p[1:]),)).fetchone()
    return u if u and not u["pw_hash"] else None


@router.get("/set-password")
def set_password_page(request: Request):
    with db() as c:
        u = _setpw_user(request, c)
    if not u:
        return go("/", err="처음부터 다시 로그인하세요.")
    return page(request, "set_password.html", u=u, min_pw=MIN_PW)


@router.post("/set-password")
async def set_password(request: Request):
    f = await read_form(request)
    with db() as c:
        u = _setpw_user(request, c)
        if not u:
            return go("/", err="처음부터 다시 로그인하세요.")
        p1, p2 = f.get("pw1") or "", f.get("pw2") or ""
        if len(p1) < MIN_PW:
            return go("/set-password", err=f"비밀번호는 {MIN_PW}자 이상으로 정하세요.")
        if p1 != p2:
            return go("/set-password", err="두 비밀번호가 다릅니다.")
        h = hash_pw(p1)
        c.execute("UPDATE ck_users SET pw_hash=?, last_login=? WHERE id=?", (h, now(), u["id"]))
    r = go("/me", msg="비밀번호를 정했습니다. 다음부터는 이름과 이 비밀번호로 들어옵니다.")
    set_cookie(r, "ck_session", sign(f"u{u['id']}|{pw_tag(h)}"), SESSION_SEC)
    r.delete_cookie("ck_setpw", path=P)
    return r


@router.get("/me/password")
def change_password_page(request: Request):
    with db() as c:
        u = current_user(request, c)
    if not u:
        return go("/")
    return page(request, "change_password.html", u=u, min_pw=MIN_PW)


@router.post("/me/password")
async def change_password(request: Request):
    f = await read_form(request)
    with db() as c:
        u = current_user(request, c)
        if not u:
            return go("/")
        if not csrf_ok(request, "user", f):
            return go("/me/password", err="요청이 만료되었습니다. 다시 시도하세요.")
        if not check_pw(f.get("cur") or "", u["pw_hash"]):
            return go("/me/password", err="지금 비밀번호가 맞지 않습니다.")
        p1, p2 = f.get("pw1") or "", f.get("pw2") or ""
        if len(p1) < MIN_PW:
            return go("/me/password", err=f"새 비밀번호는 {MIN_PW}자 이상으로 정하세요.")
        if p1 != p2:
            return go("/me/password", err="두 비밀번호가 다릅니다.")
        h = hash_pw(p1)
        c.execute("UPDATE ck_users SET pw_hash=? WHERE id=?", (h, u["id"]))
    r = go("/me", msg="비밀번호를 바꿨습니다.")
    set_cookie(r, "ck_session", sign(f"u{u['id']}|{pw_tag(h)}"), SESSION_SEC)
    return r


@router.post("/logout")
def logout():
    r = RedirectResponse(f"{P}/", status_code=303)
    r.delete_cookie("ck_session", path=P)
    return r


# ================================================================ 학생: 체크

@router.get("/me")
def me(request: Request):
    with db() as c:
        u = current_user(request, c)
        if not u:
            return go("/")
        day = pick_day(request)
        mode = request.query_params.get("mode", "all")
        mode = mode if mode in MODES else "all"
        cdate = valid_date(request.query_params.get("date")) or today()

        lat = latest_map(c, u["id"])
        hist = history_map(c, u["id"])
        all_items = items_for(c, day, u["role"])
        counts = {m: sum(1 for it in all_items if mode_match(m, lat.get(it["id"]))) for m in MODES}
        items = [it for it in all_items if mode_match(mode, lat.get(it["id"]))]

        on_date = {k: next((h for h in v if h["check_date"] == cdate), None) for k, v in hist.items()}
        sections = OrderedDict()
        for it in items:
            key = it["section"]
            sections.setdefault(key, {"title": it["section_title"], "day": it["day"], "scope": it["scope"], "items": []})
            sections[key]["items"].append(it)

        day_prog = {d: progress(items_for(c, d, u["role"]), lat) for d in DAYS}
        day_prog[0] = progress(items_for(c, 0, u["role"]), lat)
        prog = day_prog.get(day, {"total": 0, 2: 0, 1: 0, 0: 0})
        dates = [r["check_date"] for r in c.execute(
            "SELECT DISTINCT check_date FROM ck_entries WHERE user_id=? ORDER BY check_date DESC", (u["id"],))]
        done_on_date = sum(1 for it in all_items if (on_date.get(it["id"]) or {"status": None})["status"] is not None)
    return page(request, "me.html", u=u, day=day, mode=mode, cdate=cdate, sections=sections,
                lat=lat, hist=hist, on_date=on_date, prog=prog, day_prog=day_prog, counts=counts,
                dates=dates, done_on_date=done_on_date, total_view=len(all_items), areas=AREAS)


@router.get("/me/summary")
def summary(request: Request):
    with db() as c:
        u = current_user(request, c)
        if not u:
            return go("/")
        items = items_for(c, 0, u["role"])
        lat = latest_map(c, u["id"])
        hist = history_map(c, u["id"])
        areas = area_summary(items, lat, hist)
        dates = [r["check_date"] for r in c.execute(
            "SELECT DISTINCT check_date FROM ck_entries WHERE user_id=? ORDER BY check_date", (u["id"],))]
    tot = sum(a["tot"] for a in areas)
    can = sum(len(a[2]) for a in areas)
    mid = sum(len(a[1]) for a in areas)
    # 처음 체크보다 올라간 항목
    grew = []
    for it in items:
        hs = [h for h in hist.get(it["id"], []) if h["status"] is not None]
        if len(hs) >= 2 and hs[-1]["status"] > hs[0]["status"]:
            grew.append({"it": it, "first": hs[0], "last": hs[-1]})
    return page(request, "summary.html", u=u, areas=areas, tot=tot, can=can, mid=mid, grew=grew, dates=dates)


@router.post("/api/check")
async def api_check(request: Request):
    with db() as c:
        u = current_user(request, c)
        if not u:
            return JSONResponse({"ok": False, "error": "다시 로그인하세요."}, status_code=401)
        if not csrf_ok(request, "user"):
            return JSONResponse({"ok": False, "error": "페이지를 새로고침하세요."}, status_code=400)
        try:
            data = await request.json()
        except Exception:
            data = {}
        iid = str(data.get("item_id", ""))
        it = c.execute("SELECT * FROM ck_items WHERE id=? AND active=1", (iid,)).fetchone()
        if not it or it["scope"] not in visible_scopes(u["role"]):
            return JSONResponse({"ok": False, "error": "항목을 찾을 수 없습니다."}, status_code=404)
        cdate = valid_date(data.get("date"))
        if not cdate:
            return JSONResponse({"ok": False, "error": "점검 날짜가 올바르지 않습니다 (오늘 이후는 고를 수 없습니다)."}, status_code=400)

        cur = c.execute("SELECT * FROM ck_entries WHERE user_id=? AND item_id=? AND check_date=?",
                        (u["id"], iid, cdate)).fetchone()
        old_status = cur["status"] if cur else None
        old_note = (cur["note"] if cur else "") or ""
        status = old_status
        if "status" in data:
            status = data["status"]
            if status is not None:
                try:
                    status = int(status)
                except (TypeError, ValueError):
                    status = -1
                if status not in STATUS:
                    return JSONResponse({"ok": False, "error": "상태 값이 올바르지 않습니다."}, status_code=400)
        note = str(data.get("note", old_note) if "note" in data else old_note).strip()[:300]
        t = now()
        if status is None and not note:
            c.execute("DELETE FROM ck_entries WHERE user_id=? AND item_id=? AND check_date=?", (u["id"], iid, cdate))
        else:
            c.execute("""INSERT INTO ck_entries (user_id, item_id, check_date, status, note, updated_at)
                         VALUES (?,?,?,?,?,?)
                         ON CONFLICT(user_id, item_id, check_date) DO UPDATE SET status=excluded.status,
                           note=excluded.note, updated_at=excluded.updated_at""",
                      (u["id"], iid, cdate, status, note, t))
        if status != old_status or note != old_note:
            c.execute("""INSERT INTO ck_log (user_id, item_id, check_date, old_status, new_status, note, at)
                         VALUES (?,?,?,?,?,?,?)""", (u["id"], iid, cdate, old_status, status, note, t))

        try:
            view_day = int(data.get("view_day", it["day"]))
        except (TypeError, ValueError):
            view_day = it["day"]
        lat = latest_map(c, u["id"])
        p = progress(items_for(c, view_day if view_day in DAYS or view_day == 0 else it["day"], u["role"]), lat)
        hs = c.execute("SELECT * FROM ck_entries WHERE user_id=? AND item_id=? ORDER BY check_date",
                       (u["id"], iid)).fetchall()
        lr = lat.get(iid)
    return {"ok": True, "status": status, "note": note, "date": cdate,
            "latest": {"s": lr["status"], "d": lr["check_date"], "md": mmdd(lr["check_date"])} if lr else None,
            "history": hist_json(hs),
            "progress": {"total": p["total"], "s2": p[2], "s1": p[1], "s0": p[0]}}


# ================================================================ 강사

@router.get("/admin/login")
def admin_login_page(request: Request):
    if not admin_password():
        return page(request, "message.html", "admin", title="강사 화면 비활성",
                    text="서버에 ADMIN_PASSWORD 환경변수를 설정한 뒤 다시 시작하세요.")
    return page(request, "admin_login.html", "admin")


@router.post("/admin/login")
async def admin_login(request: Request):
    f = await read_form(request)
    key = ("__admin__", client_ip(request))
    if not admin_password():
        return go("/admin/login")
    if locked(key):
        return go("/admin/login", err="로그인 시도가 너무 많습니다. 잠시 뒤 다시 시도하세요.")
    if not hmac.compare_digest((f.get("password") or "").encode(), admin_password().encode()):
        FAILS[key].append(time.time())
        return go("/admin/login", err="비밀번호가 맞지 않습니다.")
    FAILS.pop(key, None)
    r = RedirectResponse(f"{P}/admin", status_code=303)
    set_cookie(r, "ck_admin", sign("admin|" + admin_tag()), ADMIN_SEC)
    return r


@router.post("/admin/logout")
def admin_logout():
    r = RedirectResponse(f"{P}/admin/login", status_code=303)
    r.delete_cookie("ck_admin", path=P)
    return r


def in_scope(item, user) -> bool:
    return item["scope"] in visible_scopes(user["role"])


@router.get("/admin")
def admin(request: Request):
    if not is_admin(request):
        return go("/admin/login")
    day = pick_day(request, allow_all=False)
    team = request.query_params.get("team", "")
    asof = valid_date(request.query_params.get("asof")) or today()
    with db() as c:
        teams = [r["team"] for r in c.execute(
            "SELECT DISTINCT team FROM ck_users WHERE team IS NOT NULL AND team<>'' ORDER BY team")]
        users = c.execute("SELECT * FROM ck_users" + (" WHERE team=?" if team else "") + " ORDER BY team, role, name",
                          (team,) if team else ()).fetchall()
        items = c.execute("SELECT * FROM ck_items WHERE active=1 AND day=? ORDER BY ord", (day,)).fetchall()
        all_items = c.execute("SELECT * FROM ck_items WHERE active=1 ORDER BY ord").fetchall()
        chk = latest_all(c, asof)
        on_day = {(r["user_id"], r["item_id"]) for r in c.execute(
            "SELECT user_id, item_id FROM ck_entries WHERE check_date=? AND status IS NOT NULL", (asof,))}
        dates = [r["check_date"] for r in c.execute(
            "SELECT check_date, COUNT(DISTINCT user_id) n FROM ck_entries GROUP BY check_date ORDER BY check_date DESC LIMIT 30")]

        stats = []
        for n, it in enumerate(items, 1):
            targets = [u for u in users if in_scope(it, u)]
            cnt = {2: 0, 1: 0, 0: 0, None: 0}
            for u in targets:
                r = chk.get((u["id"], it["id"]))
                cnt[r["status"] if r is not None and r["status"] in (0, 1, 2) else None] += 1
            stats.append({"n": n, "it": it, "tot": len(targets), "c": cnt,
                          "pct": round(cnt[2] * 100 / len(targets)) if targets else None})
        weak = sorted([s for s in stats if s["tot"]],
                      key=lambda s: (s["c"][None] == s["tot"], s["pct"], -s["c"][0], s["c"][None]))

        rows = []
        for u in users:
            cells, p = [], {2: 0, 1: 0, 0: 0, "tot": 0, "today": 0}
            for it in items:
                if not in_scope(it, u):
                    cells.append(None)
                    continue
                p["tot"] += 1
                r = chk.get((u["id"], it["id"]))
                st = r["status"] if r is not None else None
                if st in (0, 1, 2):
                    p[st] += 1
                fresh = (u["id"], it["id"]) in on_day
                p["today"] += 1 if fresh else 0
                cells.append({"st": st, "note": (r["note"] if r is not None else "") or "",
                              "d": r["check_date"] if r is not None else "", "fresh": fresh})
            rows.append({"u": u, "cells": cells, "p": p})

        by_team = defaultdict(list)
        for u in users:
            if u["team"]:
                by_team[u["team"]].append(u)
        gaps = []
        for t, members in sorted(by_team.items()):
            if len(members) < 2:
                continue
            miss = []
            for n, it in enumerate(items, 1):
                if it["scope"] not in ("common", "peer"):
                    continue
                sts = [(chk.get((m["id"], it["id"])) or {"status": None})["status"] for m in members]
                if all(s != 2 for s in sts) and any(s is not None for s in sts):
                    miss.append({"n": n, "it": it, "sts": sts})
            gaps.append({"team": t, "members": members, "miss": miss})

        area_rows = []
        for u in users:
            lat_u = {k[1]: v for k, v in chk.items() if k[0] == u["id"]}
            its = [it for it in all_items if in_scope(it, u)]
            area_rows.append({"u": u, "a": {a["name"]: a for a in area_summary(its, lat_u)}})

        log = c.execute("""SELECT l.*, u.name, u.team, i.text, i.day FROM ck_log l
                           JOIN ck_users u ON u.id=l.user_id JOIN ck_items i ON i.id=l.item_id
                           ORDER BY l.id DESC LIMIT 40""").fetchall()
        joined = len({k[0] for k in on_day})
    return page(request, "admin.html", "admin", day=day, team=team, teams=teams, users=users, asof=asof,
                items=items, stats=stats, weak=weak, rows=rows, gaps=gaps, log=log, dates=dates,
                joined=joined, area_rows=area_rows, areas=AREAS)


@router.get("/admin/users")
def admin_users(request: Request):
    if not is_admin(request):
        return go("/admin/login")
    with db() as c:
        users = c.execute("""SELECT u.*, (SELECT COUNT(DISTINCT check_date) FROM ck_entries e WHERE e.user_id=u.id) AS n_dates,
                                    (SELECT MAX(check_date) FROM ck_entries e WHERE e.user_id=u.id) AS last_date
                             FROM ck_users u ORDER BY team, role, name""").fetchall()
    return page(request, "admin_users.html", "admin", users=users)


@router.post("/admin/users/add")
async def admin_users_add(request: Request):
    f = await read_form(request)
    if not is_admin(request) or not csrf_ok(request, "admin", f):
        return go("/admin/login")
    added = updated = 0
    errors = []
    with db() as c:
        for ln, line in enumerate((f.get("roster") or "").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            parts = [x.strip() for x in line.replace("\t", ",").split(",")]
            name = parts[0]
            team = parts[1] if len(parts) > 1 else ""
            raw = parts[2].replace(" ", "") if len(parts) > 2 else ""
            role = ROLE_ALIASES.get(raw.lower(), ROLE_ALIASES.get(raw)) if raw else None
            if not name:
                continue
            if raw and not role:
                errors.append(f"{ln}번째 줄 역할 '{parts[2]}'을 알 수 없습니다 (기록 / 문서)")
                continue
            ex = c.execute("SELECT id FROM ck_users WHERE name=?", (name,)).fetchone()
            if ex:
                c.execute("UPDATE ck_users SET team=?, role=? WHERE id=?", (team, role, ex["id"]))
                updated += 1
            else:
                c.execute("INSERT INTO ck_users (name, team, role, created_at) VALUES (?,?,?,?)",
                          (name, team, role, now()))
                added += 1
    return go("/admin/users", msg=f"새로 등록 {added}명, 정보 수정 {updated}명", err=" · ".join(errors))


@router.post("/admin/users/{uid}/reset")
async def admin_users_reset(uid: int, request: Request):
    f = await read_form(request)
    if not is_admin(request) or not csrf_ok(request, "admin", f):
        return go("/admin/login")
    with db() as c:
        u = c.execute("SELECT name FROM ck_users WHERE id=?", (uid,)).fetchone()
        if u:
            c.execute("UPDATE ck_users SET pw_hash=NULL WHERE id=?", (uid,))
    return go("/admin/users", msg=f"{u['name']}님 비밀번호를 초기화했습니다. 다음 로그인 때 새로 정합니다." if u else "")


@router.post("/admin/users/{uid}/delete")
async def admin_users_delete(uid: int, request: Request):
    f = await read_form(request)
    if not is_admin(request) or not csrf_ok(request, "admin", f):
        return go("/admin/login")
    with db() as c:
        u = c.execute("SELECT name FROM ck_users WHERE id=?", (uid,)).fetchone()
        if u:
            c.execute("DELETE FROM ck_users WHERE id=?", (uid,))
    return go("/admin/users", msg=f"{u['name']}님과 체크 기록을 삭제했습니다." if u else "")


@router.post("/admin/reload-items")
async def admin_reload_items(request: Request):
    f = await read_form(request)
    if not is_admin(request) or not csrf_ok(request, "admin", f):
        return go("/admin/login")
    try:
        with db() as c:
            n = load_items(c)
        return go("/admin", msg=f"항목 파일을 다시 읽었습니다. 항목 {n}개")
    except Exception as e:  # yaml 오류를 화면에 보여 준다
        return go("/admin", err=f"항목 파일 읽기 실패: {e}")


@router.get("/admin/export.csv")
def admin_export(request: Request):
    """kind=history: 모든 점검 기록(날짜별) / kind=latest: 학생×항목 현재 상태"""
    if not is_admin(request):
        return go("/admin/login")
    day = request.query_params.get("day", "")
    kind = request.query_params.get("kind", "history")
    buf = io.StringIO()
    w = csv.writer(buf)
    with db() as c:
        if kind == "latest":
            asof = valid_date(request.query_params.get("asof")) or today()
            chk = latest_all(c, asof)
            w.writerow(["기준 날짜", "이름", "조", "역할", "Day", "역량 영역", "구분", "항목ID", "항목",
                        "현재 상태", "마지막 점검 날짜", "메모"])
            q = "SELECT * FROM ck_items WHERE active=1" + (" AND day=?" if day.isdigit() else "") + " ORDER BY ord"
            items = c.execute(q, (int(day),) if day.isdigit() else ()).fetchall()
            for u in c.execute("SELECT * FROM ck_users ORDER BY team, name"):
                for it in items:
                    if not in_scope(it, u):
                        continue
                    r = chk.get((u["id"], it["id"]))
                    w.writerow([asof, u["name"], u["team"] or "", ROLES.get(u["role"], ""), it["day"], it["area"],
                                it["section_title"], it["id"], it["text"],
                                STATUS.get(r["status"]) if r is not None else "미응답",
                                r["check_date"] if r is not None else "", (r["note"] if r is not None else "") or ""])
        else:
            w.writerow(["점검 날짜", "이름", "조", "역할", "Day", "역량 영역", "구분", "항목ID", "항목",
                        "상태", "메모", "저장 시각"])
            q = """SELECT e.*, u.name, u.team, u.role, i.day, i.area, i.section_title, i.text
                   FROM ck_entries e JOIN ck_users u ON u.id=e.user_id JOIN ck_items i ON i.id=e.item_id"""
            args: tuple = ()
            if day.isdigit():
                q += " WHERE i.day=?"
                args = (int(day),)
            for r in c.execute(q + " ORDER BY u.team, u.name, i.ord, e.check_date", args):
                w.writerow([r["check_date"], r["name"], r["team"] or "", ROLES.get(r["role"], ""), r["day"], r["area"],
                            r["section_title"], r["item_id"], r["text"], STATUS.get(r["status"], "-"),
                            r["note"] or "", r["updated_at"]])
    fn = f"checklist_{kind}" + (f"_day{day}" if day.isdigit() else "") + ".csv"
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={fn}"})


init()
