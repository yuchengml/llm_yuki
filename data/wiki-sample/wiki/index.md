---
updated: 2026-05-10
total_pages: 11
total_sources: 2
---

# Wiki Index | 知識庫索引

_Last updated: 2026-05-10 — 11 pages, 2 sources_

> Entry point for all queries. Read this first to find relevant pages, then drill into them.

---

## Papers | 論文 (2)

| Page | Summary | Year | Tags |
|------|---------|------|------|
| [[wiki/papers/2026-yadav-agent-harness\|Yadav — 7 Agent Harness Components]] | `Agent = Model + Harness`；7 個 harness 元件框架；model-harness coupling 的非直覺洞察 | 2026 | agents, infrastructure, system |
| [[wiki/papers/2026-silfverskiold-token-savings\|Silfverskiöld — Agentic AI: How to Save on Tokens]] | 4 種降低 token 成本策略：prompt caching、lazy-loading、model routing、context 清理 | 2026 | agents, efficiency, infrastructure |

---

## Entities | 實體 (2)

_Organizations, models, systems._

| Page | Type | Summary |
|------|------|---------|
| [[wiki/entities/anthropic\|Anthropic]] | org | Claude 系列模型開發者；MCP、Tool Search API、Claude Code 的設計方 |
| [[wiki/entities/claude-code\|Claude Code]] | system | Anthropic 的 coding agent CLI；agent harness 設計的重要參考案例 |

---

## Concepts | 概念 (5)

_Techniques, frameworks, design patterns._

| Page | Summary |
|------|---------|
| [[wiki/concepts/agent-harness\|Agent Harness]] | 包覆 LLM 的基礎設施層；7 元件框架；model-harness coupling |
| [[wiki/concepts/agent-state-management\|Agent State Management]] | Session state + Persistent state；JSON 檔案最簡實作；Ralph Loop |
| [[wiki/concepts/context-compaction\|Context Compaction]] | 壓縮 context 歷史；三種技術；Jia et al. 6x 壓縮研究（需驗證） |
| [[wiki/concepts/prompt-caching\|Prompt Caching]] | K/V tensor 快取；OpenAI vs Anthropic vs vLLM 實作差異；semantic caching 比較 |
| [[wiki/concepts/lazy-loading-tools\|Lazy-Loading Tools]] | 按需載入工具定義；Anthropic Tool Search API；Claude Code Skills 系統 |
| [[wiki/concepts/model-routing\|Model Routing]] | 路由請求到不同大小模型；predictive routing vs speculative cascade |

---

## Analyses | 分析 (0)

| Page | Kind | Summary |
|------|------|---------|
| _(none yet)_ | | |

---

## Overview

→ [[wiki/overview|Field Overview]] — evolving synthesis of the research landscape
