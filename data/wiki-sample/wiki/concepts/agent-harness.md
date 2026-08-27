---
type: concept
name_en: "Agent Harness"
name_zh: "Agent Harness（基礎設施層）"
aliases: ["harness", "agent infrastructure", "agent framework"]
tags: [agents, infrastructure, system, foundational]
source_count: 1
updated: 2026-05-10
---

# Agent Harness（Agent 基礎設施層）

> 包覆 LLM 模型、使其能可靠執行工作的所有基礎設施程式碼與配置。

---

## What It Is | 定義

**核心公式：`Agent = Model + Harness`**

- **Model**：負責推理、語言理解、決策
- **Harness**：負責讓模型能夠安全、重複、可規模地行動的一切其他東西

Harness 包含控制循環、狀態管理、記憶體、工具執行環境、上下文管理、規劃機制、錯誤處理。

> 「A model without a harness is a brain without a nervous system. The thinking happens. Nothing else does.」— Yadav 2026

---

## Why It Matters | 重要性

大多數 agent 生產環境失敗根源在 harness 品質不足，而非模型能力不足。工具呼叫返回空結果、上下文在長時間運行後填滿、子 agent 互相矛盾、模型無限重試——這些都是 harness 問題。

Harness 也決定了成本：未優化的 harness 會造成 context 膨脹、重複計算，直接轉換成帳單。

---

## How It Works | 7 個核心元件

| 元件 | 職責 |
|------|------|
| **[[wiki/concepts/agent-control-loop\|Control Loop]]** | 驅動 model→tools→context 循環；`MAX_STEPS` 防無限循環 |
| **[[wiki/concepts/agent-state-management\|State Management]]** | Session state + Persistent state（JSON 檔案最簡實作） |
| **Memory** | Short-term（對話歷史）+ Long-term（vector DB 或結構化檔案） |
| **Tools** | 將語言轉為行動；bash escape hatch 讓 agent 動態產生工具 |
| **[[wiki/concepts/context-compaction\|Context Management]]** | Compaction + tool output truncation + [[wiki/concepts/lazy-loading-tools\|lazy-loading]] |
| **Planning** | Plan file 注入 context；self-verification；Ralph Loop |
| **Error Handling** | 每個工具明確定義失敗行為；escalation path |

**推薦建構順序**（由最關鍵到最後加）：
1. Control loop + `MAX_STEPS`
2. State file
3. 3–5 個工具（描述精確）
4. Error handling
5. Context compaction
6. Memory
7. Planning

---

## Model-Harness Coupling | 模型與 Harness 的耦合

這是本概念最非直覺的重要面向：

現代 coding agent（如 Claude Code）的模型是在與特定 harness 一起運行時進行後訓練（post-training）的。模型學會了使用特定 harness 設計的檔案系統操作、bash 執行、規劃行為。

**結果：改變 harness 邏輯往往會降低模型性能，即使新邏輯在邏輯上等價。** 例如，改變工具的 patching 格式，用了不同於訓練時的格式，模型表現會變差。

> ⚠️ **實證依據**：Terminal Bench 2.0 上，Opus 4.6 在 Claude Code 內的得分顯著低於在 custom-tuned harness 內（來源：[[wiki/papers/2026-yadav-agent-harness|Yadav 2026]]，未揭露具體數字）。此數字無法獨立驗證，但論點值得關注。

**實踐含義**：out-of-the-box harness 未必是你任務的最優解；harness 優化是個尚未被廣泛探索的性能槓桿。

---

## When NOT to Use Agents | 何時不應用 Agent

- 同樣的輸入總是通過同樣的步驟產生同樣的輸出 → 用確定性 pipeline
- 錯誤代價是刪除生產資料或發送錯誤郵件 → 加入人工審核 gate
- 輸入是結構化的、處理是規則型的 → agent 是過度設計

> 「An agent is not an upgrade from a workflow. It is a different tool for a different class of problem.」

---

## Debates & Open Questions | 爭議與未解問題

- 隨著模型能力提升，多少 harness 功能會被模型原生吸收（如更好的 self-planning）？
- 最佳 harness 設計是否高度任務特定，還是存在通用最佳實踐？
- Model-harness coupling 程度有多深？是否可以量化？

---

## Sources | 來源

- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]] — 核心框架定義與 7 元件詳解
- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] — token 成本角度的 harness 優化
