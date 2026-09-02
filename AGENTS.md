# AGENTS.md — AI Agent 驱动指南

本应用提供面向 AI agent 的一步式 HTTP API（本地/局域网单用户，无鉴权）。
首次发现请调 `GET /api/agent/help`（约 300 tokens，含参数表与示例）。

## 快速示例

```bash
# 目录（递归）→ 合并为一个有声书 → 输出到指定目录
curl -s http://HOST:8000/api/agent/convert \
  -H 'Content-Type: application/json' \
  -d '{"inputs":["/mnt/user/audiobooks/书A"],
       "preset":"audiobook_aac_lc_64k","merge":true,
       "book_title":"书A","book_artist":"演播者",
       "output_dir":"/mnt/user/audiobooks-out"}'
# → {"jobs":[{"id":"..","status":"done","output":"<最终文件路径>","error":null}]}

# 逐文件转码（每个文件一个任务，wait=false 先拿 ids 再轮询）
curl -s http://HOST:8000/api/agent/convert \
  -H 'Content-Type: application/json' \
  -d '{"inputs":["/mnt/user/audiobooks/书A"],"preset":"audiobook_opus_32k",
       "wait":false}'
curl -s "http://HOST:8000/api/agent/status?ids=ID1,ID2"
```

## 要点

| 项 | 说明 |
|---|---|
| 输入路径 | 目录或文件，须在 `HAC_LIBRARY_ROOTS` 白名单内（环境变量，冒号分隔） |
| 输出目录 | 须在 `HAC_OUTPUT_ROOTS` 白名单内（默认仅 `data/outputs`）；给出即隐含等待完成 |
| preset | `GET /api/presets` 查询；opus/aac 系有声书预设开箱即用 |
| merge | true 合并为单个 .m4b（需 AAC 系编码器，Opus 会 400 并提示原因） |
| 错误自纠 | 400/403 响应的 `detail` 含明确原因与修正方向，直接读它重试 |
| 已有文件零上传 | `lib:<绝对路径>` 形式的 source_ids 亦被 `/api/jobs` 原生接受 |
