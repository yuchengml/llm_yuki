---
type: concept
name_en: "Agent State Management"
name_zh: "Agent 狀態管理"
aliases: ["state management", "persistent state", "session state"]
tags: [agents, infrastructure, foundational]
source_count: 1
updated: 2026-05-10
---

# Agent State Management（Agent 狀態管理）

> Agent harness 追蹤「已做什麼、正在做什麼、接下來做什麼」的機制。

---

## What It Is | 定義

LLM 本身是無狀態的——每次 API 呼叫從頭開始。State management 是 harness 層負責的工作，讓 agent 跨步驟、跨 session 保持連貫性。

---

## How It Works | 兩種狀態

**Session State（Session 內狀態）**
- 當前對話歷史（所有 message、tool call、tool result）
- 當前步驟計數器
- 暫存的 tool 輸出

**Persistent State（跨 Session 持久狀態）**
- 長任務的進度（已完成的子任務、待處理項目）
- 已處理的檔案清單（防止 coding agent 重複編輯同一個檔案）
- 當前整體任務狀態

**最簡實作：JSON 檔案**

```json
{
  "task_id": "refactor-auth-module",
  "completed_files": ["auth.py", "middleware.py"],
  "pending_files": ["routes.py", "tests/test_auth.py"],
  "current_step": 3
}
```

優點：可讀、可 debug、可從 process restart 中恢復、不需要額外基礎設施。加上 git 後可追蹤變更、回滾錯誤、分支實驗。

---

## Variants & Related Work | 變體與延伸

**Ralph Loop**：當 agent 在長任務中跑完 context window 但未完成目標，Ralph Loop 透過 hook 攔截退出，將原始目標注入全新的 context window 並強制繼續。這是跨多個 context window 實現長視野自主性的機制。
- 依賴 persistent state：每個新的 context window 讀取前一個 iteration 留下的狀態檔案

**Plan File**：State management 與 planning 的交叉點。一個 YAML 格式的計劃檔案，harness 在每個循環開始時注入 context，agent 完成步驟後打勾。Session 結束後計劃持久保存；下次 session 繼續時知道從哪裡開始。

**Memory vs State**
- State = agent 在這個 session / 任務中做了什麼
- Memory = agent 跨 session 知道什麼（使用者偏好、項目背景）
- 兩者不同層次，需分開管理

---

## Key Papers | 代表論文

- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]] — 狀態管理作為 7 個 harness 元件之一，含 JSON 模式示例

---

## Sources | 來源

- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]]
