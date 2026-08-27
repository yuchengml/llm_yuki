---
type: concept
name_en: "Context Compaction"
name_zh: "上下文壓縮"
aliases: ["context compression", "compaction", "context management", "context cleanup"]
tags: [agents, efficiency, infrastructure, llm]
source_count: 2
updated: 2026-05-10
---

# Context Compaction（上下文壓縮）

> 在 agent context window 填滿前，主動壓縮或清理歷史內容，同時保留關鍵資訊。

---

## What It Is | 定義

Context compaction 是 agent harness 的一個功能，解決「context rot」問題：agent 長時間運行後，context window 中累積大量過時或不相關的內容（tool output、重複觀察、舊計劃、失敗嘗試），導致：
1. 重要的系統提示和任務定義被「埋」在中間，模型逐漸停止關注
2. Token 成本直線上升
3. 性能下降（注意力分散）

---

## Why It Matters | 重要性

Context rot 是最隱蔽的生產失敗之一——沒有 crash、沒有 error，agent 只是悄悄開始忽略自己的系統提示。

**研究數據**：Jia et al. (2026) 在 SWE-bench Verified 上實驗，6x 壓縮比例達到：
- 51.8–71.3% token budget 減少
- issue resolution rate 提升 5.0–9.2%

> ⚠️ **Jia et al. 2026 的原始論文僅有 arXiv 連結**（[[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] 引用），完整方法論尚未直接閱讀。數字看起來很強（同時節省成本又提升性能），值得找原文確認。

---

## How It Works | 三種技術

**1. Compaction（摘要歷史）**
當 context 填滿時，對較舊的對話歷史進行摘要，而非直接截斷。
- **鐵則：永遠不壓縮原始任務定義和系統提示**
- 系統提示和任務定義應在 context 的開頭和結尾都保持可見

**2. Tool Output Truncation（工具輸出截斷）**
大型工具返回值（如 50 頁文件）直接倒入 context 會耗盡整個 budget。
- Harness 只保留前後 N 個 token
- 完整輸出存到檔案系統
- 給模型一個 file pointer，讓它在需要時讀取更多

**3. Progressive Disclosure / Lazy-Loading（漸進式載入）**
詳見 [[wiki/concepts/lazy-loading-tools|Lazy-Loading Tools]]。

---

## Context 清理的正確做法 | Active State Pipeline

**要保留（active context）：**
```
[system rules]
[project rules]
[user task]
[current working state]
  - 關鍵發現
  - 在 scope 中的檔案
  - 失敗測試的具體錯誤
```

**要丟棄（存入 archive）：**
- raw grep 結果
- 完整 test log
- 重複的 file dump
- 已放棄的嘗試

某些 context 片段可以有「生命週期」——超過一定步驟數後自動過期。

---

## Variants & Related Work | 觸發時機的爭議

**Anthropic 的做法**：在 context 已經接近填滿時才觸發壓縮（被動）。

**LangChain 的做法**：讓 agent 自己決定何時壓縮（主動），而不是等到 context 已經 bloated 才處理。

這個設計選擇尚無明確的最優解。主動壓縮可能增加不必要的 overhead；被動壓縮可能已經太遲。

---

## Key Papers | 代表論文

- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] — 實用角度的 context compaction 設計
- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]] — Context management 作為 harness 的第 5 個元件

---

## Sources | 來源

- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]]
- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]]
