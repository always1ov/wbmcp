# app/main.py
# 接收插件上报的消息，写入 SQLite，并抽取个股提及。

import json
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .db import init_db, get_conn
from .stocks import extract_mentions

app = FastAPI(title="微博私信归档接收服务")

# 允许浏览器扩展跨域 POST（扩展的 origin 是 chrome-extension://...，这里放开）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Media(BaseModel):
    images: List[str] = []
    videos: List[str] = []
    links: List[dict] = []


class Message(BaseModel):
    id: str
    conversation: Optional[str] = ""
    sender: Optional[str] = ""
    text: Optional[str] = ""
    media: Optional[Media] = None
    sent_time: Optional[str] = ""
    captured_at: Optional[str] = ""


class IngestBody(BaseModel):
    messages: List[Message]


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
    return {"ok": True, "messages": n}


@app.post("/ingest")
def ingest(body: IngestBody):
    inserted = 0
    mentions_added = 0

    with get_conn() as conn:
        cur = conn.cursor()
        for m in body.messages:
            media_json = json.dumps(
                m.media.dict() if m.media else {"images": [], "videos": [], "links": []},
                ensure_ascii=False,
            )
            # INSERT OR IGNORE：靠主键 id 去重，重复上报不会重复插入
            cur.execute(
                """
                INSERT OR IGNORE INTO messages
                    (id, conversation, sender, text, media_json, sent_time, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (m.id, m.conversation, m.sender, m.text, media_json, m.sent_time, m.captured_at),
            )
            if cur.rowcount > 0:
                inserted += 1
                # 只对新消息抽取个股提及
                for men in extract_mentions(m.text or ""):
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO stock_mentions
                            (message_id, symbol, raw, sender, context, captured_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (m.id, men["symbol"], men["raw"], m.sender, men["context"], m.captured_at),
                    )
                    if cur.rowcount > 0:
                        mentions_added += 1
        conn.commit()

    return {"ok": True, "received": len(body.messages),
            "inserted": inserted, "mentions_added": mentions_added}


# ---------- 查询接口（MCP server 也会复用这些逻辑）----------

@app.get("/search")
def search(keyword: str, sender: str = "", conversation: str = "", limit: int = 50):
    """全文（子串）搜索消息。LIKE 对中文短词友好，个人量级速度无压力。"""
    sql = "SELECT id, conversation, sender, text, sent_time, captured_at FROM messages WHERE text LIKE ?"
    args = [f"%{keyword}%"]
    if sender:
        sql += " AND sender LIKE ?"
        args.append(f"%{sender}%")
    if conversation:
        sql += " AND conversation LIKE ?"
        args.append(f"%{conversation}%")
    sql += " ORDER BY captured_at DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {"count": len(rows), "results": [dict(r) for r in rows]}


@app.get("/who_mentioned")
def who_mentioned(symbol: str, limit: int = 100):
    """谁提过某只票、什么时候、原话。symbol 支持正名或别名子串。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT symbol, sender, raw, context, captured_at, message_id
            FROM stock_mentions
            WHERE symbol LIKE ? OR raw LIKE ?
            ORDER BY captured_at DESC LIMIT ?
            """,
            (f"%{symbol}%", f"%{symbol}%", limit),
        ).fetchall()
    return {"count": len(rows), "results": [dict(r) for r in rows]}


@app.get("/recent_stocks")
def recent_stocks(days: int = 7, limit: int = 20):
    """最近 N 天被聊得最多的标的排行。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT symbol,
                   COUNT(*) AS mentions,
                   COUNT(DISTINCT sender) AS people,
                   MAX(captured_at) AS last_seen
            FROM stock_mentions
            WHERE captured_at >= datetime('now', ?)
            GROUP BY symbol
            ORDER BY mentions DESC
            LIMIT ?
            """,
            (f"-{int(days)} days", limit),
        ).fetchall()
    return {"days": days, "results": [dict(r) for r in rows]}


@app.get("/sender_stocks")
def sender_stocks(sender: str, limit: int = 50):
    """某人聊过哪些票，各多少次。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT symbol, COUNT(*) AS mentions, MAX(captured_at) AS last_seen
            FROM stock_mentions
            WHERE sender LIKE ?
            GROUP BY symbol
            ORDER BY mentions DESC LIMIT ?
            """,
            (f"%{sender}%", limit),
        ).fetchall()
    return {"sender": sender, "results": [dict(r) for r in rows]}


# ---------- 群聊查看接口 ----------

@app.get("/conversations")
def list_conversations():
    """返回所有会话，按最新消息倒序。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT conversation,
                   COUNT(*) AS msg_count,
                   MAX(captured_at) AS last_at
            FROM messages
            GROUP BY conversation
            ORDER BY last_at DESC
            """
        ).fetchall()
    return {"results": [dict(r) for r in rows]}


@app.get("/messages")
def list_messages(conversation: str, offset: int = 0, limit: int = 50):
    """按会话分页拉取消息（时间正序）。"""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE conversation = ?",
            (conversation,),
        ).fetchone()["c"]
        rows = conn.execute(
            """
            SELECT id, sender, text, media_json, sent_time, captured_at
            FROM messages
            WHERE conversation = ?
            ORDER BY captured_at ASC
            LIMIT ? OFFSET ?
            """,
            (conversation, limit, offset),
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["media"] = json.loads(d.pop("media_json") or "{}")
        except Exception:
            d["media"] = {}
        results.append(d)
    return {"total": total, "offset": offset, "limit": limit, "results": results}


# ---------- 前端页面 ----------

_HTML = (Path(__file__).parent / "chat_ui.html").read_text(encoding="utf-8")


@app.get("/view", response_class=HTMLResponse)
def view_ui():
    return _HTML
