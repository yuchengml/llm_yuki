---
type: overview
updated: 2026-05-10
source_count: 2
---

# AI/Tech Research — Field Overview | 領域全景

> 本頁是基於所有已 ingest 資料的綜合論述。隨每次 ingest 更新，不代表任何單一來源。

---

## Current State of the Field | 當前領域概覽

AI agent 工程在 2026 年已進入「生產環境爬坡期」：demo 容易，可靠的生產系統難。目前社群對「模型本身的能力」關注度高，但對「模型周圍的基礎設施」（harness）投資普遍不足。兩者之間的落差，正是大多數生產環境 agent 失敗的根源。

同時，agent 成本問題開始成為實際工程決策的約束。未優化的 agent 在高流量下每月成本可達數千美元；透過系統性的 harness 設計，可降低 80–90%。

---

## Major Themes | 主要研究主題

### 1. Harness = 生產化的關鍵差距

核心框架：`Agent = Model + Harness`（[[wiki/concepts/agent-harness|Agent Harness]]）。

Harness 包含控制循環、狀態管理、記憶體、工具、context 管理、規劃、錯誤處理。這不是「配件」，而是讓模型能夠可靠工作的神經系統。重要的反直覺洞察：**Harness 的設計甚至影響模型性能本身**——model-harness coupling 意味著 out-of-the-box harness 未必是特定任務的最優解。

### 2. Token 成本是工程約束，不是事後優化

四種主要降本策略（[[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]]）：

| 策略 | 本質 | 代表技術 |
|------|------|---------|
| 重用 token | 避免重複計算相同 prefix | [[wiki/concepts/prompt-caching|Prompt Caching]] |
| 不預載休眠 token | 按需載入工具定義 | [[wiki/concepts/lazy-loading-tools|Lazy-Loading Tools]] |
| 便宜模型做便宜工作 | 路由請求到對應大小模型 | [[wiki/concepts/model-routing|Model Routing]] |
| 保持 context 乾淨 | 移除累積的垃圾 | [[wiki/concepts/context-compaction|Context Compaction]] |

### 3. Context 管理是貫穿兩個主題的核心

Context 管理同時出現在「可靠性」（context rot 導致 agent 忽略自己的指令）和「成本」（冗餘 token）兩個問題中。這不是巧合——context 是模型與 harness 之間的唯一介面。

---

## Key Open Questions | 核心未解問題

- **Model-harness coupling 的程度**：這個耦合能被量化嗎？可以系統性地優化特定任務的 harness 嗎？
- **Routing 品質的下界**：當 learned router 與簡單 heuristic 效果相近時（LLMRouterBench），實際工程中應如何選擇？
- **Context compaction 的最佳觸發時機**：主動（LangChain 式）vs 被動（Anthropic 式），哪個更好？

---

## Emerging Trends | 新興趨勢

- **Harness 優化成為性能槓桿**：同樣的模型，不同 harness，可量測的性能差異（Terminal Bench 2.0 案例，具體數字待驗證）
- **工具數量爆炸**：大量 MCP tools 帶來的 context 管理壓力驅動 lazy-loading 工具的需求
- **Agent 成本估算工具化**：Silfverskiöld 2026 使用互動計算器評估不同策略，顯示「成本可計算性」成為設計對話的一部分

---

## Sources Reflected Here | 反映的來源

- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]] — Harness 框架、7 元件、model-harness coupling
- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] — Token 成本優化四策略
