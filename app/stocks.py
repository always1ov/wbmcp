# app/stocks.py
# 从消息正文里抽取"个股提及"。
# 两路并用：
#   1) 正则：6位A股代码、$代码$、(代码) 这类规整写法
#   2) 别名词典：他们常用简称/外号 -> 正名（外挂 JSON，随时加，不用改代码）

import re
import os
import json

# 别名词典路径（挂载进容器，可热加载）
ALIAS_PATH = os.environ.get("STOCK_ALIAS_PATH", "/data/stock_alias.json")

# 6位数字股票代码（沪深）：60xxxx / 00xxxx / 30xxxx / 68xxxx 等
RE_CODE = re.compile(r"(?<!\d)(6\d{5}|0\d{5}|3\d{5})(?!\d)")
# $茅台$ / $600519$ 这种 cashtag
RE_CASHTAG = re.compile(r"\$([^\$\s]{1,12})\$")

_alias_cache = {"mtime": 0, "map": {}}


def load_aliases():
    """加载别名词典：{ "正名": ["别名1","别名2"], ... }
    返回 反向映射 { "别名": "正名" }，并把正名本身也映射到自己。
    带 mtime 缓存，文件改了自动重载。"""
    try:
        mtime = os.path.getmtime(ALIAS_PATH)
    except OSError:
        return {}
    if mtime == _alias_cache["mtime"] and _alias_cache["map"]:
        return _alias_cache["map"]

    rev = {}
    try:
        with open(ALIAS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for canonical, aliases in data.items():
            rev[canonical] = canonical
            for a in aliases or []:
                rev[a] = canonical
    except Exception as e:
        print("[stocks] 词典加载失败：", e)
        rev = {}

    _alias_cache["mtime"] = mtime
    _alias_cache["map"] = rev
    return rev


def split_sentences(text):
    """粗略按标点切句，用于给每个提及找上下文。"""
    parts = re.split(r"[。！？!?\n；;]+", text or "")
    return [p.strip() for p in parts if p.strip()]


def extract_mentions(text):
    """返回 [{symbol, raw, context}, ...]，已按 symbol 去重。"""
    if not text:
        return []

    rev = load_aliases()
    found = {}  # symbol -> {raw, context}
    sentences = split_sentences(text)

    def add(symbol, raw):
        ctx = ""
        for s in sentences:
            if raw in s:
                ctx = s
                break
        if symbol not in found:
            found[symbol] = {"symbol": symbol, "raw": raw, "context": ctx or text[:60]}

    # 1) 别名/正名词典命中（最可靠，优先）
    for term, canonical in rev.items():
        if term and term in text:
            add(canonical, term)

    # 2) 6位代码
    for m in RE_CODE.finditer(text):
        code = m.group(1)
        canonical = rev.get(code, code)
        add(canonical, code)

    # 3) cashtag $xxx$
    for m in RE_CASHTAG.finditer(text):
        tok = m.group(1)
        canonical = rev.get(tok, tok)
        add(canonical, tok)

    return list(found.values())
