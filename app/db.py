# app/db.py
# SQLite 连接 + 建表。三张表：messages（主表）、stock_mentions（个股提及）、messages_fts（全文索引）

import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/weibo.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,   -- 微博 mid，天然去重
    conversation TEXT,               -- 会话名
    sender       TEXT,               -- 发信人昵称
    text         TEXT,               -- 正文
    media_json   TEXT,               -- 图片/视频/链接 JSON
    sent_time    TEXT,               -- 页面上的时分（可能为空）
    captured_at  TEXT,               -- 采集时间 ISO
    ingested_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_msg_conv   ON messages(conversation);
CREATE INDEX IF NOT EXISTS idx_msg_sender ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_msg_time   ON messages(captured_at);

CREATE TABLE IF NOT EXISTS stock_mentions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT,
    symbol     TEXT,                 -- 归一化后的标的名
    raw        TEXT,                 -- 原文里命中的词
    sender     TEXT,
    context    TEXT,                 -- 提及所在的那句话
    captured_at TEXT,
    UNIQUE(message_id, symbol)       -- 同一条消息同一标的只记一次
);

CREATE INDEX IF NOT EXISTS idx_stk_symbol ON stock_mentions(symbol);
CREATE INDEX IF NOT EXISTS idx_stk_sender ON stock_mentions(sender);
CREATE INDEX IF NOT EXISTS idx_stk_time   ON stock_mentions(captured_at);
"""


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
