# -*- coding: utf-8 -*-
"""
live-api — TSUKUYOMI 直播独立后端 (live.rrrosmontis.icu)
=========================================================
职责：
  1. SRS on_publish/on_unpublish HTTP hooks：推流码校验、主/副站来源区分、权限检查
  2. 主播申请/审批（房号 1-100、15 位推流码、三个月不使用吊销）
  3. 直播间标题等信息查询、直播记录、观看时长统计
  4. 向 napcat(live_monitor.py :1986) best-effort 报告开播信息 + outbox 补发兜底
  5. 观众 SSO 门禁（登录即可观看）、观看进入/心跳/离开记录

部署（bj, nssm `live-api`）：
  python -m uvicorn live_api:app --host 127.0.0.1 --port 4560 --log-level info
"""
import hashlib
import hmac
import json
import logging
import os
import re
import secrets as _secrets
import sqlite3
import threading
import time
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("live-api")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==================== 配置 ====================
DEFAULT_CONFIG = {
    "db": os.path.join(BASE_DIR, "live.db"),
    "sso_verify_url": "https://api.rrrosmontis.icu/v1/sso/service/verify",
    "service": "live",
    "napcat_notify_url": "http://127.0.0.1:1986/internal/notify",
    "revoke_days": 90,
    "watch_timeout_s": 120,
    "sites": {
        "1": {
            "name": "主站", "enabled": True,
            "push_server": "rtmps://api.rrrosmontis.icu:19350/live",
            "play_base": "https://api.rrrosmontis.icu/live/"
        },
        "2": {
            "name": "副站", "enabled": True,
            "push_server": "rtmps://tsk.rrrosmontis.icu:1935/live",
            "play_base_cn": "https://tsk.rrrosmontis.icu/live/",
            "play_base_oversea": "https://tsk.aeolianchi.me/live/"
        }
    }
}


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


CONFIG = _load_json(os.path.join(BASE_DIR, "config.json"), DEFAULT_CONFIG)
SECRETS = _load_json(os.path.join(BASE_DIR, "secrets.json"), {})
if not SECRETS.get("session_secret"):
    SECRETS["session_secret"] = _secrets.token_hex(32)
    try:
        with open(os.path.join(BASE_DIR, "secrets.json"), "w", encoding="utf-8") as f:
            json.dump(SECRETS, f, indent=2)
    except Exception as e:
        logger.warning(f"secrets.json 写入失败（用临时密钥）: {e}")

_db_cfg = CONFIG.get("db") or "live.db"
if not os.path.isabs(_db_cfg):
    _db_cfg = os.path.join(BASE_DIR, _db_cfg)
DB_PATH = os.environ.get("LIVE_API_DB") or _db_cfg
SERVICE = CONFIG.get("service", "live")
SERVICE_TOKEN = SECRETS.get("service_token", "")
SESSION_SECRET = SECRETS.get("session_secret", "").encode()
SITES = CONFIG["sites"]
REVOKE_DAYS = int(CONFIG.get("revoke_days", 90))
WATCH_TIMEOUT_S = int(CONFIG.get("watch_timeout_s", 120))

# ==================== 数据库 ====================
DB_LOCK = threading.Lock()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def q(sql, args=(), one=False):
    with DB_LOCK:
        c = db()
        try:
            cur = c.execute(sql, args)
            rows = cur.fetchall()
            c.commit()
            return (rows[0] if rows else None) if one else rows
        finally:
            c.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS anchors (
    uid TEXT PRIMARY KEY,
    email TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    room_no INTEGER UNIQUE,
    stream_key TEXT UNIQUE,
    main_enabled INTEGER NOT NULL DEFAULT 1,
    sub_enabled INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    approved_at TEXT,
    last_live_at TEXT,
    revoked_at TEXT,
    reject_reason TEXT NOT NULL DEFAULT '',
    admin_note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    room_no INTEGER NOT NULL,
    site INTEGER NOT NULL,
    key TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_s INTEGER,
    end_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_streams_uid ON streams(uid);
CREATE INDEX IF NOT EXISTS idx_streams_key_site ON streams(key, site, ended_at);
CREATE TABLE IF NOT EXISTS watch_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    room_no INTEGER NOT NULL,
    site INTEGER NOT NULL,
    entered_at TEXT NOT NULL,
    last_beat_at TEXT NOT NULL,
    left_at TEXT,
    duration_s INTEGER,
    ip TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_watch_uid ON watch_sessions(uid);
CREATE INDEX IF NOT EXISTS idx_watch_room ON watch_sessions(room_no, site, left_at);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def init_db():
    with DB_LOCK:
        c = db()
        try:
            c.executescript(SCHEMA)
            c.commit()
        finally:
            c.close()
    logger.info("数据库初始化完成")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_ts() -> float:
    return time.time()


def _to_ts(s: str) -> float:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return 0.0


def audit(uid, action, detail="", ip=""):
    q("INSERT INTO audit_log (uid, action, detail, ip, created_at) VALUES (?,?,?,?,?)",
      (uid, action, detail, ip or "", now()))


# ==================== 会话令牌（HMAC 无状态） ====================
def _b64e(b: bytes) -> str:
    return __import__("base64").urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return __import__("base64").urlsafe_b64decode(s + pad)


def make_session_token(user: dict, ttl_s: int = 7 * 86400) -> str:
    payload = {"uid": user["uid"], "email": user["email"], "nickname": user["nickname"],
               "level": user.get("level", 9), "exp": int(now_ts()) + ttl_s}
    body = _b64e(json.dumps(payload, ensure_ascii=False).encode())
    sig = _b64e(hmac.new(SESSION_SECRET, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session_token(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".", 1)
        expect = _b64e(hmac.new(SESSION_SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(_b64d(body))
        if payload.get("exp", 0) < now_ts():
            return None
        return payload
    except Exception:
        return None


def bearer_user(request: Request) -> Optional[dict]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        tok = request.query_params.get("token", "")
    else:
        tok = auth[7:].strip()
    return verify_session_token(tok) if tok else None


# ==================== SSO 校验 ====================
def sso_verify(sso_token: str) -> Optional[dict]:
    """POST SSO /service/verify → {user:{...}, service:{usable,tier}} 或 None。"""
    if not sso_token:
        return None
    try:
        with httpx.Client(timeout=8.0, verify=True) as cli:
            r = cli.post(CONFIG["sso_verify_url"],
                         headers={"X-SSO-Service-Token": SERVICE_TOKEN},
                         json={"service": SERVICE, "token": sso_token})
        if r.status_code != 200:
            return None
        data = r.json()
        if not data.get("ok"):
            return None
        return data
    except Exception as e:
        logger.error(f"SSO verify 失败: {e}")
        return None


async def _sso_activate(uid: str):
    """触发首次使用激活并返回最新 {key,tier,usable}；失败返回 None（不阻塞 /me）。"""
    try:
        with httpx.Client(timeout=6.0, verify=True) as cli:
            r = cli.post(CONFIG["sso_activate_url"],
                         headers={"X-SSO-Service-Token": SERVICE_TOKEN},
                         json={"service": SERVICE, "uid": uid})
        if r.status_code == 200:
            d = r.json()
            if d.get("ok"):
                return {"key": SERVICE, "tier": d.get("tier", 0), "usable": d.get("usable", False)}
    except Exception as e:
        logger.warning(f"sso activate 失败: {e}")
    return None


# ==================== 推流码 ====================
KEY_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # 去掉易混淆 0O1IL
KEY_RE = re.compile(r"^[2-9A-HJ-NP-Z]{5}-[2-9A-HJ-NP-Z]{5}-[2-9A-HJ-NP-Z]{5}$")


def gen_stream_key() -> str:
    while True:
        raw = "".join(_secrets.choice(KEY_ALPHABET) for _ in range(15))
        key = f"{raw[:5]}-{raw[5:10]}-{raw[10:]}"
        if not q("SELECT 1 FROM anchors WHERE stream_key=?", (key,), one=True):
            return key


def norm_key(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", s or "").upper()


def find_anchor_by_stream(stream: str):
    """SRS 流名 = <房间号>（推拉统一，如 93）。兼容 room_93 旧写法。
    房号 1-100，获批主播独占。"""
    m = re.fullmatch(r"(?:room_)?(\d{1,3})", (stream or "").lower())
    if not m:
        return None
    return q("SELECT * FROM anchors WHERE room_no=? AND status='approved'",
             (int(m.group(1)),), one=True)


def parse_param_tk(param: str) -> str:
    """从 SRS on_publish 的 param（如 '?token=XXXX'）提取推流码。
    标准参数名 token；兼容早期写法 tk。"""
    if not param:
        return ""
    for pair in param.lstrip("?").split("&"):
        k, _, v = pair.partition("=")
        if k in ("token", "tk"):
            return v.strip()
    return ""


# ==================== napcat 通知 ====================
def _napcat_post(payload: dict) -> bool:
    try:
        with httpx.Client(timeout=3.0) as cli:
            r = cli.post(CONFIG["napcat_notify_url"], json=payload)
            return r.status_code == 200
    except Exception as e:
        logger.warning(f"napcat 通知失败: {e}")
        return False


def notify_unpublish_async(room_no: int, site: int):
    """Tell the bot that this live session ended, so a later stream is not deduplicated."""
    def _work():
        payload = {"room_id": str(room_no), "site": str(site), "action": "unpublish"}
        ok = _napcat_post(payload)
        if ok:
            logger.info(f"napcat end notification ok room={room_no} site={site}")
        else:
            logger.warning(f"napcat end notification failed room={room_no} site={site}")
    threading.Thread(target=_work, daemon=True).start()


def notify_publish_async(room_no: int, site: int, title: str = "", nickname: str = "",
                         reset_session: bool = False):
    """后台线程：best-effort POST napcat + 写 outbox 兜底。"""
    def _work():
        # A rejected reconnect can leave the previous bot session active.
        if reset_session:
            _napcat_post({"room_id": str(room_no), "site": str(site), "action": "unpublish"})
        payload = {"room_id": str(room_no), "site": str(site), "title": title, "nickname": nickname}
        ok = _napcat_post(payload)
        q("INSERT INTO outbox (type, payload, created_at, delivered_at, attempts) VALUES (?,?,?,?,?)",
          ("publish", json.dumps(payload, ensure_ascii=False), now(), now() if ok else None, 1))
        if ok:
            logger.info(f"napcat 通知成功 room={room_no} site={site}")
    threading.Thread(target=_work, daemon=True).start()


def sso_activate_async(uid: str):
    """后台线程：推流 = 实际使用直播服务，best-effort 触发 SSO 首次使用激活（tier 0→1）。
    失败仅记日志，绝不影响推流放行。"""
    def _work():
        try:
            with httpx.Client(timeout=6.0, verify=True) as cli:
                r = cli.post(CONFIG["sso_activate_url"],
                             headers={"X-SSO-Service-Token": SERVICE_TOKEN},
                             json={"service": SERVICE, "uid": uid})
            if r.status_code == 200 and r.json().get("ok"):
                logger.info(f"sso activate ok uid={uid}")
            else:
                logger.warning(f"sso activate 拒绝 uid={uid} status={r.status_code}")
        except Exception as e:
            logger.warning(f"sso activate 失败 uid={uid}: {e}")
    threading.Thread(target=_work, daemon=True).start()


def outbox_retry_worker():
    """每 60s 补发未送达的开播通知（24h 后放弃）。"""
    while True:
        try:
            rows = q("SELECT * FROM outbox WHERE delivered_at IS NULL AND attempts < 200", ())
            for row in rows:
                created = _to_ts(row["created_at"])
                if now_ts() - created > 86400:
                    q("UPDATE outbox SET delivered_at=? WHERE id=? AND delivered_at IS NULL",
                      (now() + " (expired)", row["id"]))
                    continue
                try:
                    ok = _napcat_post(json.loads(row["payload"]))
                except Exception:
                    ok = False
                if ok:
                    q("UPDATE outbox SET delivered_at=?, attempts=attempts+1 WHERE id=?", (now(), row["id"]))
                else:
                    q("UPDATE outbox SET attempts=attempts+1 WHERE id=?", (row["id"],))
        except Exception as e:
            logger.error(f"outbox worker 异常: {e}")
        time.sleep(60)


def revoke_worker():
    """每 6h 检查：approved 且 last_live_at 距今超过 revoke_days → 吊销。"""
    while True:
        try:
            rows = q("SELECT * FROM anchors WHERE status='approved'", ())
            cut = now_ts() - REVOKE_DAYS * 86400
            for a in rows:
                last = _to_ts(a["last_live_at"] or "") or _to_ts(a["approved_at"] or "")
                if last and last < cut:
                    q("UPDATE anchors SET status='revoked', revoked_at=?, stream_key=NULL, room_no=NULL,"
                      " admin_note=? WHERE uid=?", (now(), f"超过 {REVOKE_DAYS} 天未直播，自动吊销", a["uid"]))
                    audit(a["uid"], "anchor.autorevoke", f"room freed, last_live={a['last_live_at']}")
                    logger.info(f"自动吊销 uid={a['uid']}")
        except Exception as e:
            logger.error(f"revoke worker 异常: {e}")
        time.sleep(6 * 3600)


STREAM_SWEEP_TIMEOUT_S = 43200  # 12h：超时的未结束流记录判定为断流丢失，收编

def watch_sweep_worker():
    """每 60s 收编僵尸数据：
    1) 观看会话：心跳断掉超过 10 分钟仍未 leave 的自动关闭
    2) 流记录：副站网络断流时 on_unpublish 钩子丢失（Frp 不干净断开），
       超过 6h 仍未结束的流判定为已死，自动关闭，防止直播间长期假「正在直播」"""
    while True:
        try:
            rows = q("""SELECT id, uid, room_no, site, entered_at FROM watch_sessions
                        WHERE left_at IS NULL
                          AND (strftime('%s','now') - strftime('%s', last_beat_at)) > 600""", ())
            for r in rows:
                dur = max(0, int(now_ts() - _to_ts(r["entered_at"])))
                q("UPDATE watch_sessions SET left_at=?, duration_s=? WHERE id=?",
                  (now(), dur, r["id"]))
                logger.info(f"watch 会话超时关闭 id={r['id']} uid={r['uid']} room={r['room_no']} site={r['site']}")
        except Exception as e:
            logger.error(f"watch sweep worker 异常: {e}")
        try:
            # 有活跃观众（心跳<=2min）的流是真实在播，豁免不清扫；
            # 僵尸流（网络断流、unpublish 钩子丢失）无观众，到点收编
            srows = q("""SELECT s.id, s.uid, s.room_no, s.site, s.started_at FROM streams s
                         WHERE s.ended_at IS NULL
                           AND (strftime('%s','now') - strftime('%s', s.started_at)) > ?
                           AND NOT EXISTS (SELECT 1 FROM watch_sessions w
                                           WHERE w.room_no = s.room_no AND w.site = s.site
                                             AND w.left_at IS NULL
                                             AND (strftime('%s','now') - strftime('%s', w.last_beat_at)) <= 120)""",
                      (STREAM_SWEEP_TIMEOUT_S,))
            for r in srows:
                dur = max(0, int(now_ts() - _to_ts(r["started_at"])))
                q("UPDATE streams SET ended_at=?, duration_s=?, end_reason='sweep_timeout' WHERE id=?",
                  (now(), dur, r["id"]))
                audit(r["uid"], "stream.sweep_timeout", f"room={r['room_no']} site={r['site']} dur={dur}s")
                notify_unpublish_async(r["room_no"], r["site"])
                logger.info(f"流记录超时收编 id={r['id']} room={r['room_no']} site={r['site']} dur={dur}s")
        except Exception as e:
            logger.error(f"stream sweep worker 异常: {e}")
        time.sleep(60)


# ==================== FastAPI ====================
app = FastAPI(title="live-api", docs_url=None, redoc_url=None, openapi_url=None)

# CORS：直播前端在 live 域，API 在 api 域（与 SSO 后端同款白名单机制）
CORS_ORIGINS = [
    "https://live.rrrosmontis.icu",
    "https://lfr.aeolianchi.me",
    "https://sso.rrrosmontis.icu",
    "https://api.rrrosmontis.icu",
    "https://rosmanka.rrrosmontis.icu",
    "https://mail.rrrosmontis.icu",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"ok": False, "code": 500, "msg": "服务器内部错误"}, status_code=500)


@app.on_event("startup")
def _startup():
    init_db()
    threading.Thread(target=outbox_retry_worker, daemon=True).start()
    threading.Thread(target=revoke_worker, daemon=True).start()
    threading.Thread(target=watch_sweep_worker, daemon=True).start()
    logger.info("live-api 启动完成")


def jerr(msg, code=400, status=200):
    return JSONResponse({"ok": False, "code": code, "msg": msg}, status_code=status)


async def _json(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ---------- SRS HTTP hooks ----------
async def _hook_publish(site: int, request: Request):
    """SRS on_publish：流名=room_<房号>，param.tk=推流码 → 放行或拒绝。"""
    data = await _json(request)
    stream = str(data.get("stream", ""))
    ip = str(data.get("ip", ""))
    param = str(data.get("param", ""))
    logger.info(f"on_publish site={site} stream={stream!r} ip={ip} param={param!r}")

    a = find_anchor_by_stream(stream)
    if not a:
        audit(None, "publish.reject", f"unknown stream site={site} stream={stream} ip={ip}", ip)
        return JSONResponse({"code": 404, "msg": "invalid stream key"})
    # 推流码校验：param.tk 必须等于该主播的 stream_key（防 room_xx 被冒推）
    tk = parse_param_tk(param)
    if not tk or not _secrets.compare_digest(tk, a["stream_key"] or ""):
        audit(a["uid"], "publish.reject", f"bad tk site={site} stream={stream} ip={ip}", ip)
        return JSONResponse({"code": 401, "msg": "invalid push token"})
    enabled_col = "main_enabled" if site == 1 else "sub_enabled"
    if not a[enabled_col]:
        audit(a["uid"], "publish.reject", f"site {site} disabled", ip)
        return JSONResponse({"code": 403, "msg": f"site {site} not enabled"})
    site_cfg = SITES.get(str(site), {})
    if not site_cfg.get("enabled", True):
        return JSONResponse({"code": 403, "msg": f"site {site} globally disabled"})

    # 关闭同 key+site 的旧未结束记录（SRS 断线重推等），再开新记录
    open_row = q("SELECT * FROM streams WHERE key=? AND site=? AND ended_at IS NULL",
                 (stream, site), one=True)
    if open_row:
        dur = int(now_ts() - _to_ts(open_row["started_at"]))
        q("UPDATE streams SET ended_at=?, duration_s=?, end_reason='restart' WHERE id=?",
          (now(), dur, open_row["id"]))
    q("INSERT INTO streams (uid, room_no, site, key, title, started_at) VALUES (?,?,?,?,?,?)",
      (a["uid"], a["room_no"], site, stream, a["title"], now()))
    q("UPDATE anchors SET last_live_at=? WHERE uid=?", (now(), a["uid"]))
    audit(a["uid"], "publish.allow", f"room={a['room_no']} site={site} ip={ip}", ip)
    # Only a long-lived stale row means the prior unpublish was lost. Immediate
    # duplicate SRS hooks must not replay a notification.
    stale_old_session = bool(open_row and now_ts() - _to_ts(open_row["started_at"]) > 300)
    notify_publish_async(a["room_no"], site, a["title"], a["nickname"],
                         reset_session=stale_old_session)
    sso_activate_async(a["uid"])
    logger.info(f"ALLOW publish room={a['room_no']} site={site} uid={a['uid']}")
    return JSONResponse({"code": 0})


async def _hook_unpublish(site: int, request: Request):
    data = await _json(request)
    stream = str(data.get("stream", ""))
    a = find_anchor_by_stream(stream)
    if a:
        row = q("SELECT * FROM streams WHERE key=? AND site=? AND ended_at IS NULL",
                (stream, site), one=True)
        if row:
            dur = int(now_ts() - _to_ts(row["started_at"]))
            q("UPDATE streams SET ended_at=?, duration_s=?, end_reason='unpublish' WHERE id=?",
              (now(), dur, row["id"]))
            audit(a["uid"], "unpublish", f"room={a['room_no']} site={site} dur={dur}s")
            notify_unpublish_async(a["room_no"], site)
            logger.info(f"UNPUBLISH room={a['room_no']} site={site} dur={dur}s")
    return JSONResponse({"code": 0})


@app.post("/hooks/on_publish")
async def hook_publish_main(request: Request):
    return await _hook_publish(1, request)


@app.post("/hooks/local/on_publish")
async def hook_publish_local(request: Request):
    return await _hook_publish(2, request)


@app.post("/hooks/on_unpublish")
async def hook_unpublish_main(request: Request):
    return await _hook_unpublish(1, request)


@app.post("/hooks/local/on_unpublish")
async def hook_unpublish_local(request: Request):
    return await _hook_unpublish(2, request)


# ---------- 兼容旧路径（若 nginx 未改写直接打到 4560） ----------
@app.post("/remote_srs/on_publish")
async def compat_publish_main(request: Request):
    return await _hook_publish(1, request)


@app.post("/remote_srs/local/on_publish")
async def compat_publish_local(request: Request):
    return await _hook_publish(2, request)


@app.post("/remote_srs/on_unpublish")
async def compat_unpublish_main(request: Request):
    return await _hook_unpublish(1, request)


@app.post("/remote_srs/local/on_unpublish")
async def compat_unpublish_local(request: Request):
    return await _hook_unpublish(2, request)


# ---------- 观看/主播 Web API ----------
def _anchor_payload(a) -> dict:
    return {
        "uid": a["uid"], "room_no": a["room_no"], "status": a["status"],
        "main_enabled": bool(a["main_enabled"]), "sub_enabled": bool(a["sub_enabled"]),
        "title": a["title"], "created_at": a["created_at"], "approved_at": a["approved_at"],
        "last_live_at": a["last_live_at"], "reject_reason": a["reject_reason"],
    }


def _play_urls(key: str, site: int) -> dict:
    base = SITES.get(str(site), {})
    if site == 1:
        b = base.get("play_base", "")
        return {"flv": f"{b}{key}.flv", "m3u8": f"{b}{key}.m3u8"}
    return {"cn": {"flv": f"{base.get('play_base_cn','')}{key}.flv",
                   "m3u8": f"{base.get('play_base_cn','')}{key}.m3u8"},
            "oversea": {"flv": f"{base.get('play_base_oversea','')}{key}.flv",
                        "m3u8": f"{base.get('play_base_oversea','')}{key}.m3u8"}}


@app.post("/api/auth/verify")
async def auth_verify(request: Request):
    """danmaku 等附属服务校验会话：token → 用户（uid/nickname）。仅供服务内部鉴权调用。"""
    data = await _json(request)
    token = str(data.get("token") or data.get("sso_token") or "")
    user = verify_session_token(token)
    if not user:
        return {"ok": False, "msg": "token 无效或已过期"}
    return {"ok": True, "user": {"uid": user.get("uid", ""), "nickname": user.get("nickname", "")}}


@app.get("/api/config")
async def get_config():
    """公开：站点展示配置（推流地址等，主播页 OBS 配置用）。"""
    return {"ok": True, "sites": SITES, "revoke_days": REVOKE_DAYS}


@app.post("/api/auth/exchange")
async def auth_exchange(request: Request):
    """sso_token → live 会话 token。"""
    data = await _json(request)
    res = sso_verify(str(data.get("sso_token", "")))
    if not res:
        return jerr("SSO 校验失败", 401, 401)
    u = res["user"]
    tok = make_session_token(u)
    return {"ok": True, "token": tok, "user": {
        "uid": u["uid"], "email": u["email"], "nickname": u["nickname"],
        "level": u.get("level", 9), "avatar": u.get("avatar", ""),
        "live": res.get("service", {})}}


@app.get("/api/me")
async def me(request: Request):
    user = bearer_user(request)
    if not user:
        return jerr("未登录", 401, 401)
    live_svc = await _sso_activate(user['uid'])
    a = q("SELECT * FROM anchors WHERE uid=?", (user["uid"],), one=True)
    total_s = 0
    count = 0
    if a:
        r = q("SELECT COUNT(*) c, COALESCE(SUM(duration_s),0) s FROM streams WHERE uid=? AND ended_at IS NOT NULL",
              (user["uid"],), one=True)
        total_s, count = r["s"], r["c"]
    return {"ok": True, "user": {"uid": user["uid"], "email": user["email"],
                                 "nickname": user["nickname"], "level": user.get("level", 9),
                                 "live": live_svc},
            "anchor": _anchor_payload(a) if a else None,
            "stream_key": a["stream_key"] if a and a["status"] == "approved" else None,
            "stats": {"total_seconds": total_s, "stream_count": count}}


@app.post("/api/apply")
async def apply_anchor(request: Request):
    user = bearer_user(request)
    if not user:
        return jerr("未登录", 401, 401)
    if q("SELECT 1 FROM anchors WHERE uid=?", (user["uid"],), one=True):
        return jerr("已存在申请或已开通", 409)
    data = await _json(request)
    try:
        room = int(data.get("room"))
    except (TypeError, ValueError):
        return jerr("房间号必须是 1-100 的整数")
    if not (1 <= room <= 100):
        return jerr("房间号必须在 1-100 之间")
    if q("SELECT 1 FROM anchors WHERE room_no=?", (room,), one=True):
        return jerr("该房间号已被申请或占用", 409)
    q("INSERT INTO anchors (uid, email, nickname, room_no, status, created_at) VALUES (?,?,?,?,?,?)",
      (user["uid"], user["email"], user["nickname"], room, "pending", now()))
    audit(user["uid"], "anchor.apply", f"room={room}")
    return {"ok": True, "msg": "申请已提交，等待管理员审批"}


@app.post("/api/apply/retry")
async def apply_retry(request: Request):
    """被拒/被吊销后重新申请（更换房间号）。"""
    user = bearer_user(request)
    if not user:
        return jerr("未登录", 401, 401)
    a = q("SELECT * FROM anchors WHERE uid=?", (user["uid"],), one=True)
    if not a:
        return jerr("没有历史申请", 404, 404)
    if a["status"] in ("pending", "approved"):
        return jerr("当前状态不可重新申请", 409)
    data = await _json(request)
    try:
        room = int(data.get("room"))
    except (TypeError, ValueError):
        return jerr("房间号必须是 1-100 的整数")
    if not (1 <= room <= 100):
        return jerr("房间号必须在 1-100 之间")
    if q("SELECT 1 FROM anchors WHERE room_no=? AND uid<>?", (room, user["uid"]), one=True):
        return jerr("该房间号已被占用", 409)
    q("UPDATE anchors SET room_no=?, status='pending', reject_reason='', revoked_at=NULL, admin_note='', created_at=? WHERE uid=?",
      (room, now(), user["uid"]))
    audit(user["uid"], "anchor.retry", f"room={room}")
    return {"ok": True, "msg": "申请已重新提交"}


@app.post("/api/me/title")
async def set_title(request: Request):
    user = bearer_user(request)
    if not user:
        return jerr("未登录", 401, 401)
    a = q("SELECT * FROM anchors WHERE uid=?", (user["uid"],), one=True)
    if not a or a["status"] != "approved":
        return jerr("主播状态不可用", 403)
    data = await _json(request)
    title = str(data.get("title", ""))[:100]
    q("UPDATE anchors SET title=? WHERE uid=?", (title, user["uid"]))
    return {"ok": True}


@app.get("/api/me/records")
async def my_records(request: Request):
    user = bearer_user(request)
    if not user:
        return jerr("未登录", 401, 401)
    rows = q("SELECT * FROM streams WHERE uid=? ORDER BY id DESC LIMIT 100", (user["uid"],))
    r = q("SELECT COUNT(*) c, COALESCE(SUM(duration_s),0) s FROM streams WHERE uid=? AND ended_at IS NOT NULL",
          (user["uid"],), one=True)
    return {"ok": True, "total_seconds": r["s"], "count": r["c"],
            "records": [dict(x) for x in rows]}


@app.get("/api/rooms/map")
async def rooms_map():
    """房间 1-100 占用图（不含身份信息）：free/pending/taken/live。"""
    rows = q("SELECT room_no, status, uid FROM anchors WHERE room_no IS NOT NULL", ())
    live_rows = q("SELECT DISTINCT uid, site FROM streams WHERE ended_at IS NULL", ())
    live_uids = {r["uid"] for r in live_rows}
    m = {}
    for r in rows:
        if r["status"] == "approved":
            m[r["room_no"]] = "live" if r["uid"] in live_uids else "taken"
        else:
            m[r["room_no"]] = "pending"
    return {"ok": True, "rooms": {str(i): m.get(i, "free") for i in range(1, 101)}}


@app.get("/api/rooms/{room}")
async def room_info(room: int, site: int = 1):
    """观众：房间信息 + 解析播放地址。"""
    if not (1 <= room <= 100):
        return jerr("房间号无效", 404, 404)
    a = q("SELECT * FROM anchors WHERE room_no=?", (room,), one=True)
    if not a or a["status"] != "approved":
        return {"ok": True, "exists": False, "live": False}
    enabled_col = "main_enabled" if site == 1 else "sub_enabled"
    stream = str(room)  # SRS 流名统一 = 房间号（如 93）
    open_row = q("SELECT * FROM streams WHERE key=? AND site=? AND ended_at IS NULL",
                 (stream, site), one=True)
    return {
        "ok": True, "exists": True, "live": bool(open_row),
        "site_enabled": bool(a[enabled_col]),
        "title": a["title"], "nickname": a["nickname"],
        "room_no": a["room_no"],
        "play": _play_urls(stream, site) if open_row else None,
    }


# ---------- 观看统计 ----------
def _watch_session(user, room, site):
    return q("SELECT * FROM watch_sessions WHERE uid=? AND room_no=? AND site=? AND left_at IS NULL",
             (user["uid"], room, site), one=True)


@app.post("/api/watch/enter")
async def watch_enter(request: Request):
    user = bearer_user(request)
    if not user:
        return jerr("未登录", 401, 401)
    data = await _json(request)
    try:
        room, site = int(data.get("room")), int(data.get("site", 1))
    except (TypeError, ValueError):
        return jerr("参数错误")
    if not (1 <= room <= 100 and site in (1, 2)):
        return jerr("参数错误")
    a = q("SELECT * FROM anchors WHERE room_no=?", (room,), one=True)
    if not a or a["status"] != "approved":
        return {"ok": False, "code": 404, "msg": "房间不存在或未开放"}
    ip = request.client.host if request.client else ""
    old = _watch_session(user, room, site)
    if old:
        q("UPDATE watch_sessions SET last_beat_at=? WHERE id=?", (now(), old["id"]))
        return {"ok": True, "resumed": True}
    q("INSERT INTO watch_sessions (uid, room_no, site, entered_at, last_beat_at, ip) VALUES (?,?,?,?,?,?)",
      (user["uid"], room, site, now(), now(), ip))
    return {"ok": True}


@app.post("/api/watch/beat")
async def watch_beat(request: Request):
    user = bearer_user(request)
    if not user:
        return jerr("未登录", 401, 401)
    data = await _json(request)
    try:
        room, site = int(data.get("room")), int(data.get("site", 1))
    except (TypeError, ValueError):
        return jerr("参数错误")
    s = _watch_session(user, room, site)
    if s:
        q("UPDATE watch_sessions SET last_beat_at=? WHERE id=?", (now(), s["id"]))
    return {"ok": True}


@app.post("/api/watch/leave")
async def watch_leave(request: Request):
    user = bearer_user(request)
    if not user:
        return jerr("未登录", 401, 401)
    data = await _json(request)
    try:
        room, site = int(data.get("room")), int(data.get("site", 1))
    except (TypeError, ValueError):
        return jerr("参数错误")
    s = _watch_session(user, room, site)
    if s:
        dur = max(0, int(now_ts() - _to_ts(s["entered_at"])))
        q("UPDATE watch_sessions SET left_at=?, duration_s=? WHERE id=?", (now(), dur, s["id"]))
    return {"ok": True}


# ---------- 管理员（SSO level<=1） ----------
def require_admin(request: Request):
    user = bearer_user(request)
    if not user:
        return None, jerr("未登录", 401, 401)
    if int(user.get("level", 9)) > 1:
        return None, jerr("需要管理员权限", 403, 403)
    return user, None


@app.get("/api/admin/anchors")
async def admin_anchors(request: Request, status: str = ""):
    user, err = require_admin(request)
    if err:
        return err
    if status:
        rows = q("SELECT * FROM anchors WHERE status=? ORDER BY rowid DESC", (status,))
    else:
        rows = q("SELECT * FROM anchors ORDER BY rowid DESC", ())
    return {"ok": True, "anchors": [{**_anchor_payload(a), "email": a["email"]} for a in rows]}


@app.post("/api/admin/anchors/{uid}/approve")
async def admin_approve(uid: str, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    a = q("SELECT * FROM anchors WHERE uid=?", (uid,), one=True)
    if not a:
        return jerr("未找到该申请", 404, 404)
    if a["status"] != "pending":
        return jerr(f"当前状态 {a['status']} 不可审批", 409)
    key = a["stream_key"] or gen_stream_key()
    q("UPDATE anchors SET status='approved', approved_at=?, stream_key=?, reject_reason='' WHERE uid=?",
      (now(), key, uid))
    audit(user["uid"], "anchor.approve", f"target_uid={uid} room={a['room_no']}")
    return {"ok": True, "room_no": a["room_no"], "stream_key": key}


@app.post("/api/admin/anchors/{uid}/reject")
async def admin_reject(uid: str, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    a = q("SELECT * FROM anchors WHERE uid=?", (uid,), one=True)
    if not a or a["status"] != "pending":
        return jerr("仅待审申请可拒绝", 409)
    data = await _json(request)
    reason = str(data.get("reason", ""))[:200]
    q("UPDATE anchors SET status='rejected', reject_reason=?, room_no=NULL WHERE uid=?", (reason, uid))
    audit(user["uid"], "anchor.reject", f"target_uid={uid} reason={reason}")
    return {"ok": True}


@app.post("/api/admin/anchors/{uid}/revoke")
async def admin_revoke(uid: str, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    a = q("SELECT * FROM anchors WHERE uid=?", (uid,), one=True)
    if not a or a["status"] != "approved":
        return jerr("仅已开通主播可吊销", 409)
    data = await _json(request)
    reason = str(data.get("reason", ""))[:200]
    q("UPDATE anchors SET status='revoked', revoked_at=?, stream_key=NULL, room_no=NULL, admin_note=? WHERE uid=?",
      (now(), reason, uid))
    audit(user["uid"], "anchor.revoke", f"target_uid={uid} reason={reason}")
    return {"ok": True}


@app.post("/api/admin/anchors/{uid}/perms")
async def admin_perms(uid: str, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    a = q("SELECT * FROM anchors WHERE uid=?", (uid,), one=True)
    if not a:
        return jerr("未找到", 404, 404)
    data = await _json(request)
    main = 1 if data.get("main_enabled", bool(a["main_enabled"])) else 0
    sub = 1 if data.get("sub_enabled", bool(a["sub_enabled"])) else 0
    q("UPDATE anchors SET main_enabled=?, sub_enabled=? WHERE uid=?", (main, sub, uid))
    audit(user["uid"], "anchor.perms", f"target_uid={uid} main={main} sub={sub}")
    return {"ok": True, "main_enabled": bool(main), "sub_enabled": bool(sub)}


@app.post("/api/admin/anchors/{uid}/regen_key")
async def admin_regen(uid: int, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    a = q("SELECT * FROM anchors WHERE uid=?", (uid,), one=True)
    if not a or a["status"] != "approved":
        return jerr("仅已开通主播可重置推流码", 409)
    open_rows = q("SELECT * FROM streams WHERE key=? AND ended_at IS NULL",
                  (str(a['room_no']),), ())
    if open_rows:
        return jerr("该主播正在直播，请先停止推流", 409)
    key = gen_stream_key()
    q("UPDATE anchors SET stream_key=? WHERE uid=?", (key, uid))
    audit(user["uid"], "anchor.regen_key", f"target_uid={uid}")
    return {"ok": True, "stream_key": key}


@app.get("/api/admin/overview")
async def admin_overview(request: Request):
    user, err = require_admin(request)
    if err:
        return err
    s = q("SELECT COUNT(*) c FROM anchors WHERE status='pending'", (), one=True)["c"]
    a = q("SELECT COUNT(*) c FROM anchors WHERE status='approved'", (), one=True)["c"]
    live = q("SELECT COUNT(*) c FROM streams WHERE ended_at IS NULL", (), one=True)["c"]
    # “正在观看”：会话未关闭 且 心跳新鲜（≤watch_timeout_s） 且 对应房间当前确实在直播
    ws = q("""SELECT COUNT(*) c FROM watch_sessions s
              WHERE s.left_at IS NULL
                AND (strftime('%s','now') - strftime('%s', s.last_beat_at)) <= ?
                AND EXISTS (SELECT 1 FROM streams t
                            WHERE t.room_no = s.room_no AND t.site = s.site AND t.ended_at IS NULL)""",
           (WATCH_TIMEOUT_S,), one=True)["c"]
    return {"ok": True, "pending": s, "approved": a, "live_streams": live, "watching": ws}


# ---------- 健康检查 ----------
@app.get("/api/health")
@app.get("/")
async def health():
    return {"ok": True, "service": "live-api", "time": now()}
