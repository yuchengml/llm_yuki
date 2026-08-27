---
type: concept
name_en: "Model Routing"
name_zh: "模型路由"
aliases: ["LLM routing", "model cascading", "speculative cascade", "routing", "cascading"]
tags: [efficiency, llm, agents]
source_count: 1
updated: 2026-05-10
---

# Model Routing（模型路由）

> 根據請求難度，動態決定用較便宜的小模型還是較貴的大模型來處理，以平衡成本與品質。

---

## What It Is | 定義

並非每個請求都需要最強的模型。Model routing 的前提假設是：大多數請求（業界估計 60%+）是相對簡單的任務，不需要最大的模型，也不需要 chain-of-thought。

有兩種主要策略：
1. **Predictive Routing（事前路由）**：在生成前預測難度，直接路由到對應模型
2. **Speculative Cascade（事後路由）**：讓便宜模型先試，再決定是否 escalate

---

## Why It Matters | 重要性

使用最強模型的成本 vs 使用較弱模型的成本差距可達 10–100x。若能正確路由 60% 的請求到便宜模型，整體成本可大幅下降。

---

## How It Works | 兩種機制

### Predictive Routing（事前路由）

在請求到達前估計難度：
- 輸入特徵：對話類型、複雜度信號、工具需求、明確意圖（「仔細思考」）
- 路由模型（如 RouteLLM）從偏好資料中學習

**RouteLLM（LMSYS）**：基於 Chatbot Arena 偏好資料訓練，使用標準 embedding + 小型 router head。

> ⚠️ **LLMRouterBench（Jia et al., 2026-01）發現：許多 learned router 的效果只比簡單 baseline（keyword heuristic、embedding kNN）略好。** 這是重要的反直覺發現，但需注意：此論文的 benchmark 設計是否涵蓋了多樣化的真實場景仍未清楚。引自 [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]]，值得找原文確認。

**OpenRouter Auto、Switchpoint**：商業解決方案，但路由內部機制和準確率數字未公開。

**主要風險**：路由錯誤發生在「第一步」，會毒化整個 session。

### Speculative Cascade（事後路由）

先讓便宜模型試做，再用信心指標決定是否升級：
- 信心指標：logprobs、token 機率、entropy、語意對齊
- 優點：不需事前預測難度；品質易於事後評判
- 限制：只有當你認為多數問題可以被小模型回答時才划算（每次升級都要付兩個模型的費用）

**Google「Speculative Cascades」研究**：確認此方法可行，驗證時延可低於 20ms。

> ⚠️ **CascadeFlow（開源實作）聲稱 69% 成本節省、96% quality retention vs GPT-5**。但測試任務是「有可驗證 ground truth 的問題（數學、選擇題）」，不代表開放式 agent 任務。作者本人也指出小模型「confidently wrong」的問題，建議用保守 threshold。應視為上界估計。

### Subagents（子 Agent 路由）

用較小、較便宜的模型作為 subagent 處理特定子任務（如 Claude Code 的 Explore subagent 使用 Haiku）。

- 節省效果相對有限（估算約節省 11% vs 無路由基準），因為 orchestrator 仍需規劃與合成
- 更大的價值是隔離 context、讓每個 agent 專注特定任務

---

## Variants & Related Work | 變體與延伸

- [[wiki/entities/claude-code|Claude Code]] 的 Explore subagent：明確使用 Haiku 做 codebase 搜尋
- ChatGPT：依對話類型、複雜度、工具需求、明確意圖自動路由
- 與 [[wiki/concepts/lazy-loading-tools|Lazy-Loading Tools]] 的關係：兩者都在減少「過度投入的資源」

---

## Debates & Open Questions | 爭議與未解問題

- Predictive routing 的品質下限是多少？路由錯誤的代價有多大？
- 「60%+ 的請求是簡單任務」這個假設對不同應用場景的適用性？
- 事前路由 vs 事後 cascade 的最優選擇如何決定？

---

## Key Papers | 代表論文

- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] — 詳細介紹兩種路由策略與成本估算

---

## Sources | 來源

- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]]
