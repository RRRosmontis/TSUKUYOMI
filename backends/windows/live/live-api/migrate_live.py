# -*- coding: utf-8 -*-
"""SSO/live 一次性迁移：live 服务行 + 存量用户权限回填 + secrets 加 service token + 预置站主播"""
import json
import secrets as _secrets
import sqlite3
import sys
from datetime import datetime

SVC_TOKEN = open('live_svc_token.txt').read().strip()
SSO_DB = r'C:/call/backends/sso/data/sso.db'
SSO_SECRETS = r'C:/call/backends/sso/secrets.json'
LIVE_DB = r'C:/call/backends/live/live-api/live.db'
now = lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# 1. SSO services + perms
c = sqlite3.connect(SSO_DB)
c.row_factory = sqlite3.Row
c.execute("INSERT INTO services (key,name,url,enabled,auto_provision) VALUES ('live','SLM Streaming · TSUKUYOMI 直播','https://live.rrrosmontis.icu',1,1) ON CONFLICT(key) DO NOTHING")
users = c.execute("SELECT id,email,nickname FROM users WHERE status='active'").fetchall()
n = 0
for u in users:
    cur = c.execute("INSERT OR IGNORE INTO user_service_perm (user_id,service_key,allowed,tier) VALUES (?,'live',1,0)", (u['id'],))
    n += cur.rowcount
c.commit()
print(f"[sso] services.live ok, perm backfill rows={n} (users={len(users)})")
c.close()

# 2. SSO secrets.json 加 service_tokens.live
doc = json.load(open(SSO_SECRETS, encoding='utf-8'))
doc.setdefault('service_tokens', {})['live'] = SVC_TOKEN
json.dump(doc, open(SSO_SECRETS, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print("[sso] secrets.json service_tokens.live written (hot-reload by mtime)")

# 3. live.db 预置站主播 royirin（uid=8, room=10, approved）
KEY_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
lc = sqlite3.connect(LIVE_DB)
lc.row_factory = sqlite3.Row
lc.execute("""CREATE TABLE IF NOT EXISTS anchors (
    uid TEXT PRIMARY KEY, email TEXT NOT NULL DEFAULT '', nickname TEXT NOT NULL DEFAULT '',
    room_no INTEGER UNIQUE, stream_key TEXT UNIQUE,
    main_enabled INTEGER NOT NULL DEFAULT 1, sub_enabled INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL, approved_at TEXT, last_live_at TEXT, revoked_at TEXT,
    reject_reason TEXT NOT NULL DEFAULT '', admin_note TEXT NOT NULL DEFAULT '')""")
if not lc.execute("SELECT 1 FROM anchors WHERE uid='rs_royirin'").fetchone():
    while True:
        raw = ''.join(_secrets.choice(KEY_ALPHABET) for _ in range(15))
        key = f"{raw[:5]}-{raw[5:10]}-{raw[10:]}"
        if not lc.execute("SELECT 1 FROM anchors WHERE stream_key=?", (key,)).fetchone():
            break
    lc.execute("INSERT INTO anchors (uid,email,nickname,room_no,stream_key,status,created_at,approved_at) VALUES ('rs_royirin',?,?,10,?,'approved',?,?)",
               (users[7]['email'], users[7]['nickname'], key, now(), now()))
    print(f"[live] owner anchor seeded: royirin room=10 key={key}")
else:
    row = lc.execute("SELECT room_no, stream_key FROM anchors WHERE uid='rs_royirin'").fetchone()
    print(f"[live] owner anchor exists: room={row['room_no']} key={row['stream_key']}")
lc.commit()
lc.close()
print("MIGRATION DONE")
