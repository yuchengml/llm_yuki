---
type: concept
name_en: "Lazy-Loading Tools"
name_zh: "工具延遲載入"
aliases: ["progressive disclosure", "tool lazy-loading", "deferred tools", "tool search", "skills"]
tags: [agents, efficiency, infrastructure, llm]
source_count: 2
updated: 2026-05-10
---

# Lazy-Loading Tools（工具延遲載入）

> 不在 session 開始時預載所有工具定義，而是讓 agent 按需動態查詢並載入所需工具。

---

## What It Is | 定義

傳統做法是把所有工具的完整定義（名稱、描述、input schema）一次性塞入 system prompt。當工具數量多時，這個做法有兩個問題：
1. **Token 浪費**：大多數工具在這次任務中用不到，卻佔用了珍貴的 context
2. **性能下降**：工具太多，模型選錯工具的機率上升

Lazy-loading tools 的做法是：只在 context 中保留一個輕量的「工具查詢工具」，讓模型先搜尋找到需要的工具，然後才把那個工具的定義載入 context。

---

## Why It Matters | 重要性

Anthropic 量測：在某些設定下，工具定義可高達 **55K–134K tokens**。這個體積：
- 消耗大量 prompt cache（每次 agent 呼叫的主要成本）
- 模型在超大工具列表中選錯工具是常見的失敗模式

> ⚠️ **55K–134K tokens 數字來自 Anthropic 官方工程部落格**，是內部量測，方法論未公開，但來源可信度較高。

---

## How It Works | 實作

**Anthropic Advanced Tool Search API**

```python
tools=[
    {
        "type": "tool_search_tool_bm25_20251119",  # 或 Regex，或自訂
        "name": "tool_search"
    },
    {
        "name": "send_email",
        "description": "Send an email to one or more recipients.",
        "input_schema": { ... },
        "defer_loading": True  # 僅在 10+ 工具時有意義
    }
]
```

- 模型用 `tool_search` 搜尋工具（BM25 或 Regex）
- 找到匹配後，工具定義以 `tool_reference` block 形式追加到對話中
- 初始 context 更小；但每次需要工具時多一個 search 步驟

**Claude Code 的 Skills 系統**
Claude Code 有 50+ skills（工具包），但不會在 session 開始時全部載入。Skills 只載入 front-matter（摘要），模型決定需要某 skill 時才載入完整定義。這是相同原則的另一個實作。

---

## Variants & Related Work | 變體與延伸

**靜態 slim context + on-demand fetch（一般模式）**
不依賴 API 提供的工具搜尋功能，手動設計：保持一個小的「導航層」（什麼工具在哪裡），agent 確認需要後才展開完整定義。這是「好的 AI engineering」的一般原則，不限於特定 API。

**與 [[wiki/concepts/prompt-caching|Prompt Caching]] 的關係**
頻繁變動的工具定義層是 prompt cache 的最大殺手。Lazy-loading 解決了「工具定義層不穩定」這個問題，兩者結合效果更好。

---

## Debates & Open Questions | 爭議與未解問題

> ⚠️ **外部測試（arcade.dev）以 4,000 個工具測試 Anthropic Tool Search，結果「somewhat lackluster」**（引自 [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]]）。在大量工具場景下，工具搜尋本身的準確率是瓶頸。此測試為單一外部報告，尚需更多中立評測。

- 工具搜尋增加的一個 LLM 呼叫是否值得節省的 context？
- 搜尋品質取決於工具描述的寫法，難以系統性保證
- 在工具數量 10–50 的中型場景，lazy-loading 的 ROI 是否足夠？

---

## Key Papers | 代表論文

- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] — Anthropic Tool Search API 介紹與成本計算
- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]] — Skills progressive disclosure 作為 context management 策略

---

## Sources | 來源

- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]]
- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]]
