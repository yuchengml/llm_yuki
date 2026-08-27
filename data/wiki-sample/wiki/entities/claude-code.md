---
type: entity
category: system
name_en: "Claude Code"
name_zh: "Claude Code"
aliases: ["claude-code", "Claude Code CLI"]
tags: [agents, system, llm, current]
source_count: 2
updated: 2026-05-10
---

# Claude Code

> Anthropic 開發的 coding agent CLI，是目前最廣泛被討論的 agent harness 設計參考案例之一。

---

## Overview | 概覽

Claude Code 是一個在終端機中運行的 coding agent，模型與 harness 共同設計，並且模型是在這個特定 harness 環境中進行後訓練（post-training）的。這使它成為研究 model-harness coupling 的重要案例。

---

## Key Facts | 關鍵事實

- **Creator:** [[wiki/entities/anthropic|Anthropic]]
- **Type:** CLI coding agent
- **Architecture:** Model + custom harness（兩者共同設計）
- **Subagents:** 內建 Explore subagent（使用 Haiku 模型做 codebase 搜尋）

---

## Notable Design Choices | 設計特點

**Bash escape hatch**：Agent 可執行 bash，動態生成工具，而非受限於預設工具集。

**Skills（技能）系統**：50+ skills 使用 progressive disclosure 載入——只有 front-matter（摘要）在 session 開始時載入，完整定義按需展開。這是 [[wiki/concepts/lazy-loading-tools|Lazy-Loading Tools]] 的具體實作。

**Memory 系統**：有一個 always-loaded index file（不超過 200 行），詳細 topic files 存放在其他位置。這是 context slim 設計的具體體現。

**Model-harness coupling**：Claude Code 的模型在 harness 中 post-training，因此對特定 harness 行為（patching 格式、工具呼叫模式）有依賴。

> ⚠️ **Terminal Bench 2.0 上 Opus 4.6 在 Claude Code 內的得分低於 custom-tuned harness**（來源：[[wiki/papers/2026-yadav-agent-harness|Yadav 2026]]，具體數字未揭露）。這個發現支持「out-of-the-box harness 未必是你任務的最優解」的論點。

---

## Relationships | 關聯

- Creator: [[wiki/entities/anthropic|Anthropic]]
- Key concepts: [[wiki/concepts/agent-harness|Agent Harness]], [[wiki/concepts/lazy-loading-tools|Lazy-Loading Tools]], [[wiki/concepts/context-compaction|Context Compaction]]
- Model routing: 使用 [[wiki/concepts/model-routing|Model Routing]] 將 Explore subagent 路由到 Haiku

---

## Sources | 來源

- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]] — model-harness coupling 討論
- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] — skills 系統、memory index、Explore subagent 的成本角度分析
