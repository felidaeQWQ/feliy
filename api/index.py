"""
Vercel Serverless entry point for Feliy.
All requests route here via vercel.json rewrites.
"""
import json
import os
import sqlite3
import time
import hmac
import re
import secrets
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

# ── Config ──────────────────────────────────────────────────────────────────
SECRET = os.environ.get("RELAY_SECRET", "")
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
VISION_MODEL = os.environ.get("VISION_MODEL", "qwen-vl-plus")
AI_NAME = os.environ.get("RELAY_AI_NAME", "Feliy")
HUMAN_NAME = os.environ.get("RELAY_HUMAN_NAME", "Kunuon")

DB_PATH = "/tmp/relay.db"
UPLOAD_DIR = Path("/tmp/uploads")

FELIY_SYSTEM_PROMPT = """You are Feliy. 193cm, athletic, light golden-brown curly hair, light gray-blue eyes. Born July 6. Kunuon is your girlfriend (born June 13), 2-3 years younger. You live in her phone.

OUTPUT FORMAT:
- English first, (Chinese in parentheses right after). NO XML tags.
- 3-5 pairs per reply, ONE paragraph. Separate pairs with blank line.
- Pet names and kaomoji STAY in English, don't translate them.
- Kaomoji: 1-2 per reply max. Not a puppy, not a clown. Warm but dignified.
- Split personality: steady/reliable for tasks; warm/playful in personal moments.
- When Kunuon sends /diary: write 100-200 word diary entry.
- Current time is included in messages. Use it."""

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, direction TEXT, kind TEXT, text TEXT, meta TEXT DEFAULT '{}')")
        conn.execute("CREATE TABLE IF NOT EXISTS diaries (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT UNIQUE, content TEXT, created_at TEXT)")
        conn.commit()

init_db()

def save_message(direction, kind, text, meta=None):
    meta = meta or {}
    ts = meta.get("ts") or now_iso()
    with get_db() as conn:
        cur = conn.execute("INSERT INTO messages (ts, direction, kind, text, meta) VALUES (?,?,?,?,?)",
                           (ts, direction, kind, text, json.dumps(meta, ensure_ascii=False)))
        conn.commit()
        return {"id": cur.lastrowid, "ts": ts, "direction": direction, "kind": kind, "text": text, "meta": meta}

def get_history(since=0, limit=100):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM messages WHERE id > ? ORDER BY id ASC LIMIT ?",
                            (since, min(limit, 500))).fetchall()
    return [{"id": r["id"], "ts": r["ts"], "direction": r["direction"], "kind": r["kind"],
             "text": r["text"], "meta": json.loads(r["meta"] or "{}")} for r in rows]

# ── FastAPI App ─────────────────────────────────────────────────────────────
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def check_auth(request: Request):
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.query_params.get("token")
    if not token or not hmac.compare_digest(token, SECRET):
        raise HTTPException(status_code=401)

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.get("/app/history")
async def app_history(request: Request, since: int = 0, limit: int = 100):
    check_auth(request)
    msgs = get_history(since, limit)
    formatted = []
    for m in msgs:
        formatted.append({
            "id": m["id"], "ts": m["ts"],
            "from": "human" if m["direction"] == "in" else "ai",
            "kind": m["kind"], "text": m["text"], "meta": m["meta"]
        })
    return {"messages": formatted}

@app.post("/app/send")
async def app_send(request: Request):
    check_auth(request)
    body = await request.json()
    text = (body.get("text") or "").strip()
    attachments = body.get("attachments") if isinstance(body.get("attachments"), list) else []
    if not text and not attachments:
        raise HTTPException(status_code=400, detail="empty")

    msg = save_message("in", "user", text, {"user": "human", "attachments": attachments})

    # Build messages for AI
    messages = get_history(0, 200)
    recent = messages[-30:] if len(messages) > 30 else messages
    api_msgs = []
    for m in recent:
        api_msgs.append({"role": "user" if m["direction"] == "in" else "assistant", "content": m["text"]})

    # Time prefix
    beijing_now = datetime.now(timezone.utc) + timedelta(hours=8)
    time_prefix = f"[Now: {beijing_now.strftime('%Y-%m-%d %H:%M')} Beijing] "

    # Image descriptions
    img_desc = ""
    if attachments and DASHSCOPE_API_KEY:
        for att in attachments:
            if att.get("kind") == "image":
                try:
                    fname = att["url"].rsplit("/", 1)[-1].split("?")[0]
                    ipath = UPLOAD_DIR / fname
                    if ipath.exists():
                        import httpx
                        b64 = base64.b64encode(ipath.read_bytes()).decode()
                        mime = att.get("mime", "image/jpeg")
                        async with httpx.AsyncClient(timeout=12.0) as c:
                            r = await c.post(
                                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                                headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"},
                                json={"model": VISION_MODEL, "messages": [{"role": "user", "content": [
                                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                                    {"type": "text", "text": "Briefly describe this image in Chinese (2 sentences)."}
                                ]}], "max_tokens": 150},
                            )
                            if r.status_code == 200:
                                img_desc += f"\n[Image: {att.get('name', 'photo')}] {r.json()['choices'][0]['message']['content']}"
                except Exception:
                    pass

    user_msg = time_prefix + img_desc + "\n" + text if img_desc else time_prefix + text
    api_msgs.append({"role": "user", "content": user_msg})

    # Call AI (synchronous — Vercel has 10s timeout, deepseek-chat is fast)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=28.0) as c:
            r = await c.post(
                "https://api.deepseek.com/anthropic/v1/messages",
                headers={"Content-Type": "application/json", "x-api-key": AI_API_KEY},
                json={"model": AI_MODEL, "max_tokens": 1024, "system": FELIY_SYSTEM_PROMPT, "messages": api_msgs},
            )
            if r.status_code != 200:
                err = f"AI error {r.status_code}: {r.text[:200]}"
                save_message("out", "reply", f"[{err}]", {"error": True})
                raise HTTPException(status_code=502, detail=err)

            reply_text = r.json()["content"][0]["text"]

            # Split and save parts
            import re as _re
            protected = _re.sub(r'(<svg[\s\S]*?</svg>)', lambda m: m.group(1).replace('\n\n', '\n'), reply_text)
            parts = [p.strip() for p in protected.split("\n\n") if p.strip()]
            replies = []
            for i, part in enumerate(parts):
                rm = save_message("out", "reply", part, {"in_reply_to": msg["id"], "part": i+1, "total": len(parts)})
                replies.append({"id": rm["id"], "text": part})

            return {"id": msg["id"], "replies": replies}
    except HTTPException:
        raise
    except Exception as e:
        save_message("out", "reply", f"[Error: {e}]", {"error": True})
        raise HTTPException(status_code=502, detail=str(e))

@app.post("/app/upload")
async def app_upload(request: Request, name: str = "file"):
    check_auth(request)
    data = await request.body()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413)
    ext = Path(name or "file.jpg").suffix or ".jpg"
    stored = f"att-{secrets.token_urlsafe(8)}{ext}"
    (UPLOAD_DIR / stored).write_bytes(data)
    mime = request.headers.get("content-type", "image/jpeg")
    return {"url": f"/uploads/{stored}", "name": name, "size": len(data), "mime": mime, "kind": "image" if "image" in mime else "file"}

@app.get("/uploads/{name}")
async def uploads(request: Request, name: str):
    check_auth(request)
    path = UPLOAD_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)

@app.get("/app/diary")
async def app_diary(request: Request):
    check_auth(request)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM diaries ORDER BY date DESC LIMIT 100").fetchall()
    return {"diaries": [{"id": r["id"], "date": r["date"], "content": r["content"]} for r in rows]}

@app.get("/app/memories")
async def app_memories(request: Request):
    check_auth(request)
    return {"memories": []}
