---
type: paper
title_en: "Agentic AI: How to Save on Tokens"
title_zh: "Agentic AI：如何節省 Token 成本"
authors: ["Ida Silfverskiöld"]
year: 2026
venue: "Medium (Data Science Collective)"
tags: [agents, efficiency, infrastructure, llm, current]
source_count: 1
updated: 2026-05-10
---

# Agentic AI: How to Save on Tokens (Silfverskiöld, 2026)

**Authors:** Ida Silfverskiöld | **Year:** 2026-05-05 | **Venue:** Medium

**Raw source:** `raw/Agentic AI How to Save on Tokens.md`

---

## TL;DR

本文提出四種降低 agentic AI token 成本的設計原則：prompt caching（重用 token）、lazy-loading tools（不預載休眠 token）、model routing / cascading（便宜模型做便宜工作）、以及 context 清理（移除 context 中的垃圾）。作者坦承每種方法都有取捨，並對廠商數字保持審慎，附有互動計算器輔助估算成本。

---

## Problem & Motivation | 問題與動機

Agent 成本迅速膨脹。文章以一個未優化 agent 為例：每天 100 則對話、每則 166K input tokens，在 Claude Opus 4.6 上每月費用約 **$2,490**；優化後可降至約 **$100**。

> ⚠️ **這些成本估算為作者試算，基於特定假設（166K tokens/msg × 100 msg/day）。實際成本取決於你的 token 分佈、模型版本及 provider 定價，應視為數量級參考而非精確預測。**

---

## Method | 四大設計原則

### 1. 重用 Token — Prompt Caching & Semantic Caching

**Prompt Caching（KV Cache / Prefix Caching）**
- 原理：快取 K/V tensors，下次相同 prefix 不重算
- 規則：**靜態內容必須放在 prompt 最前面**，任何微小變動（空格、重排序、時間戳）都會 invalidate cache
- OpenAI：1024+ tokens 自動快取，cached input 最高 **90% 折扣**；需 >256 靜態 tokens 才能生效
- Anthropic：需手動加 `cache-control` 參數；快取費用 + 可延長至 1 小時（但需 2x 費用）；若使用不當，Anthropic 比 OpenAI 更貴
- 自架（vLLM）：`--enable-prefix-caching` flag

**Semantic Caching**
- 原理：相似語意的問題返回快取答案（用 embedding cosine similarity）
- 適合：Q&A bot、重複性問題多的場景
- 不適合：coding agent（每次請求都是 unique）
- 需解決：similarity threshold、TTL、multi-turn、user scoping、錯誤快取的影響

> ⚠️ **Redis 聲稱 semantic caching 可減少 68.8% API 呼叫、40–50% latency 改善**，但這是廠商 marketing 數據，且使用的是 clear Q&A use case，不代表一般 agent 工作負載。需依自身場景測試。

### 2. 不預載休眠 Token — Lazy-Loading Tools

- 問題：大量工具定義（Anthropic 測量：優化前 55K–134K tokens 的工具定義）填滿 context，導致選錯工具
- 解法：Anthropic Advanced Tool Search — 模型用 `tool_search`（BM25 或 Regex）動態查詢工具，再按需載入
- 效果：更小的初始 context，但增加一個 search 步驟

> ⚠️ **有外部測試以 4,000 個工具測試 Anthropic Tool Search，結果「somewhat lackluster」**（來源：arcade.dev blog，原文引用）。此工具在大量工具場景的效果待更多中立測試驗證。

> ⚠️ **Anthropic 聲稱的 55K–134K token tool definition 數字**為 Anthropic 內部量測，來自官方工程部落格，可信度較高，但沒有方法論細節。

### 3. 便宜模型做便宜工作 — Model Routing & Cascading

**Predictive Routing（事前路由）**
- 概念：預測請求難度，路由到對應大小的模型
- RouteLLM（LMSYS）：從 Chatbot Arena 偏好資料學習路由

> ⚠️ **LLMRouterBench 論文（Jia et al., 2026-01）發現：許多 learned router 的效果只比簡單 baseline（keyword heuristic、embedding kNN）略好**。這是重要的反直覺發現，但需注意此論文本身的 benchmark 設計是否全面。

**Speculative Cascades（事後路由）**
- 概念：先用便宜模型，按信心度（logprobs、entropy）決定是否 escalate 到大模型
- 吸引力：不需事前預測難度；品質易於事後評判

> ⚠️ **CascadeFlow 聲稱 69% 成本節省、96% quality retention vs GPT-5**。作者本人指出：這些測試使用「可驗證 ground truth 的 prompt（數學、選擇題）」，不代表開放式 agent 任務的表現。應視為上界估計。

**Subagents**
- 效果相對有限：orchestrator 仍需處理規劃與合成
- 文章估算：約節省 11%（vs 無路由基準）

### 4. 保持 Context 乾淨 — Context Compaction

- 問題：agent 不斷累積垃圾（tool output、重複觀察、舊計劃、失敗嘗試）
- 好的 active context 應只保留：system rules、project rules、task、current working state（關鍵發現 + 待辦檔案）；其餘存入 archive
- Jia et al. (2026) 研究：6x 壓縮 → 51.8–71.3% token budget 減少，且 SWE-bench Verified 的 issue resolution rate 提升 5.0–9.2%

> ⚠️ **Jia et al. 2026 的數字很強，但原始論文未在文章中完整引用（僅連結 arXiv）**。5–9% 性能提升 + 大幅 token 節省的組合值得後續深入閱讀原文驗證。

---

## Results | 結果

無統一實驗，各策略估算如下（均為作者試算，非中立實驗）：

| 策略 | 估算節省 | 條件 |
|------|---------|------|
| Prompt caching | 最高 90% input cost | 90% 靜態 prompt |
| Semantic caching | 取決於重複率 | Q&A bot 效果最好 |
| Routing | 潛在大幅節省 | 若路由品質夠好 |
| Subagents | ~11% | vs 無路由 |
| Context cleanup | 30–70% context | 取決於垃圾比例 |

---

## Strengths & Weaknesses | 優缺點

- **Strengths:** 涵蓋面廣；作者對廠商數字保持明確的懷疑態度（罕見）；實用取向
- **Weaknesses / Limitations:** 工程部落格，缺乏嚴格對照實驗；互動計算器假設不透明；Gemini 3.1 Pro / OpenClaw 等 cost 基準若定價改變則數字過時

---

## Connections | 關聯

- Core concepts: [[wiki/concepts/prompt-caching|Prompt Caching]], [[wiki/concepts/lazy-loading-tools|Lazy-Loading Tools]], [[wiki/concepts/model-routing|Model Routing]], [[wiki/concepts/context-compaction|Context Compaction]]
- Entities: [[wiki/entities/anthropic|Anthropic]], [[wiki/entities/claude-code|Claude Code]]
- Complements: [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]] (harness 架構設計角度)
- Referenced papers: Jia et al. 2026 (context compaction benchmark); LLMRouterBench (Jia et al., 2026-01)
