---
type: paper
title_en: "7 Agent Harness Components Every AI Developer Needs to Build Reliable AI Agent Systems"
title_zh: "建構可靠 AI Agent 系統的 7 個 Harness 元件"
authors: ["Divy Yadav"]
year: 2026
venue: "Medium (AI Engineering Simplified)"
tags: [agents, infrastructure, llm, system, current]
source_count: 1
updated: 2026-05-10
---

# 7 Agent Harness Components (Yadav, 2026)

**Authors:** Divy Yadav | **Year:** 2026-04-14 | **Venue:** Medium

**Raw source:** `raw/7 Agent Harness Components Every AI Developer Needs to Build Reliable AI Agent Systems.md`

---

## TL;DR

本文提出 `Agent = Model + Harness` 的核心框架：模型負責推理與決策，harness 是包覆模型的所有基礎設施——控制循環、狀態管理、記憶體、工具、上下文管理、規劃、錯誤處理。作者主張大多數生產環境的 agent 失敗根源在 harness 品質不足，而非模型能力不足，並提出按優先序逐步建構 harness 的實踐建議。

---

## Problem & Motivation | 問題與動機

示範環境中完美運作的 agent 上線後頻繁失敗：無限循環（文章開頭的 $38 billing 事故）、上下文填滿後忽略系統提示、子 agent 互相矛盾、工具呼叫不停重試。作者指出這些失敗幾乎不是模型問題，而是 harness 缺失的問題。

---

## Method | 方法（核心框架）

**核心公式：**
```
Agent = Model + Harness
Model   → reasoning, language, decisions
Harness → everything the model needs to act reliably
```

**7 個 Harness 元件：**

| # | 元件 | 核心功能 |
|---|------|---------|
| 1 | **Control Loop** | 驅動 model→tools→context 循環；`MAX_STEPS` 硬限制防止無限循環 |
| 2 | **State Management** | Session state（對話歷史）+ Persistent state（跨 session 進度）；最簡實作：JSON 檔案 |
| 3 | **Memory** | Short-term（對話歷史）+ Long-term（跨 session 知識，vector DB 或結構化檔案） |
| 4 | **Tools & Bash Escape Hatch** | 將語言轉為行動；bash 存取讓 agent 動態生成工具，但需 sandbox 隔離 |
| 5 | **Context Management** | Compaction（摘要舊歷史）+ Tool output truncation + Skills progressive disclosure |
| 6 | **Planning** | Plan file 注入 context；每步驟後 self-verification；Ralph Loop 跨 context window 持續任務 |
| 7 | **Error Handling** | 每個工具明確定義失敗行為；設 escalation path（判斷何時交給人類） |

**推薦建構順序：**
1. Control loop + step limit
2. State file
3. Tool set（3–5 個，描述精確）
4. Error handling
5. Context compaction
6. Memory
7. Planning

---

## Results | 結果

文章為工程實踐文章，無實驗數據。提供一個「生產 agent trace」示例：搜尋 EU AI regulation 新聞，共 9 步驟完成，harness 負責 state tracking、context 管理、驗證循環、step limit、memory 寫入。

---

## Strengths & Weaknesses | 優缺點

- **Strengths:** 框架清晰，建構順序有實踐依據；「model-harness coupling」洞察非常罕見且有價值；「何時不用 agent」的部分少見且實用
- **Weaknesses / Limitations:** 工程部落格文章，無實驗驗證；部分建議（如 `MAX_STEPS = 10`）為作者個人經驗，未必適用所有情境

---

## My Take | 個人評估

`Agent = Model + Harness` 這個框架是本文最有價值的貢獻，不是因為技術上多新穎，而是因為它改變了工程師的投資決策：大多數人把 90% 時間放在模型（更好的 prompt、更新的模型），卻跳過了 harness。這個框架逼你正視那 10%。

**Model-harness coupling 的洞察** 尤其值得關注：Terminal Bench 2.0 上，Opus 4.6 在 Claude Code 內的得分顯著低於在 custom-tuned harness 內，同樣的模型因為 harness 不同而有可量測的排名差異。這意味著 harness 優化是個未被充分探索的性能槓桿。

> ⚠️ **Terminal Bench 2.0 的具體數字未在文章中揭露**，作者僅稱「significantly lower」，無法獨立驗證。

---

## Connections | 關聯

- Core concept: [[wiki/concepts/agent-harness|Agent Harness]]
- Sub-concepts: [[wiki/concepts/agent-state-management|State Management]], [[wiki/concepts/context-compaction|Context Compaction]], [[wiki/concepts/lazy-loading-tools|Lazy-Loading Tools]]
- Entities: [[wiki/entities/anthropic|Anthropic]], [[wiki/entities/claude-code|Claude Code]]
- Complements: [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] (token 節省角度切入相同問題)
