# 微博私信归档 · 容器服务

接收归档插件上报的消息，存进 SQLite，并自动抽取**个股提及**。
跑在 192.168.0.168，对外端口 `8848`。下一步的 MCP server 会读同一个数据库文件。

## 部署（在 192.168.0.168 上）

把本文件夹拷到那台机器，然后：

```bash
cd weibo-archive-server
docker compose up -d --build
```

确认起来了：

```bash
curl http://localhost:8848/health
# {"ok":true,"messages":0}
```

数据库和词典持久化在 `./data/`：
- `data/weibo.db` —— SQLite 数据库（容器重建不丢）
- `data/stock_alias.json` —— 个股别名词典（**改完即时生效，无需重启**）

## 个股别名词典

`data/stock_alias.json` 格式：`{"正名": ["别名", "代码", ...]}`

```json
{
  "拓荆科技": ["拓荆", "688072"],
  "臻镭科技": ["臻镭", "688270"]
}
```

抽取逻辑：词典命中 + 6位股票代码正则 + `$xxx$` cashtag。
词典里没有的票，靠代码/cashtag 也能抓；纯简称（如"雷子"）必须进词典才认得。

> ⚠️ 我预置的词典里的**股票代码是示例/猜测**（如"雷子""臻镭"对应的代码），
> 你按实际情况核对修改。改 JSON 文件即可，立即生效。

## 让插件连上

归档插件弹窗里「容器接收地址」填：`http://192.168.0.168:8848/ingest`，
点「测试上报」，这边 `curl http://localhost:8848/health` 的 messages 计数会 +1。

## API（MCP server 会复用）

| 接口 | 说明 |
|---|---|
| `POST /ingest` | 插件上报消息（去重靠消息 id） |
| `GET /health` | 健康检查 + 消息总数 |
| `GET /search?keyword=&sender=&conversation=&limit=` | 子串搜索消息 |
| `GET /who_mentioned?symbol=` | 谁提过某票、原话、时间 |
| `GET /recent_stocks?days=7` | 最近 N 天热门标的排行 |
| `GET /sender_stocks?sender=` | 某人聊过哪些票 |

搜索用 SQL `LIKE` 子串匹配（对 2 字中文票名也准；个人量级速度无压力）。

## 数据表

- **messages**：id(微博mid,主键去重)、conversation、sender、text、media_json、sent_time、captured_at
- **stock_mentions**：message_id、symbol(正名)、raw(命中词)、sender、context(原句)、captured_at

## 安全/网络

- 仅监听内网，建议**别把 8848 暴露到公网**。
- 插件 manifest 已授权 `http://192.168.0.168:8848/*`。若换 IP/端口，两边都要改。
