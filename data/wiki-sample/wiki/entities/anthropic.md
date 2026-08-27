---
type: entity
category: org
name_en: "Anthropic"
name_zh: "Anthropic"
aliases: []
tags: [llm, alignment, agents]
source_count: 2
updated: 2026-05-10
---

# Anthropic

> 美國 AI 安全公司，Claude 系列模型的開發者，以憲法 AI（Constitutional AI）和 RLHF 研究著稱。

---

## Overview | 概覽

Anthropic 由前 OpenAI 研究人員（包括 Dario Amodei、Daniela Amodei）於 2021 年創立，核心使命是 AI 安全研究。產品線以 Claude 模型為主（Opus、Sonnet、Haiku 系列），並積極開發 agent 基礎設施（Claude Code、MCP 協定、Tool Search API）。

---

## Key Facts | 關鍵事實

- **Founded:** 2021
- **Core product:** Claude 系列 LLM（Opus、Sonnet、Haiku）
- **Agent tools:** Claude Code CLI、MCP (Model Context Protocol)、Advanced Tool Search API

---

## Notable Work | 重要成果

- Constitutional AI（RLAIF）
- Claude 4.x 模型系列（截至 2026-05：Opus 4.7、Sonnet 4.6、Haiku 4.5）
- MCP（Model Context Protocol）— agent 工具協定標準
- Advanced Tool Search — BM25/Regex 工具延遲載入 API（見 [[wiki/concepts/lazy-loading-tools|Lazy-Loading Tools]]）
- Claude Code — coding agent CLI（見 [[wiki/entities/claude-code|Claude Code]]）

---

## Relationships | 關聯

- Key product: [[wiki/entities/claude-code|Claude Code]]
- Concepts: [[wiki/concepts/prompt-caching|Prompt Caching]]（`cache-control` API）、[[wiki/concepts/lazy-loading-tools|Lazy-Loading Tools]]（Tool Search API）

---

## Sources | 來源

- [[wiki/papers/2026-yadav-agent-harness|Yadav 2026]] — 作為 harness 設計的參考案例
- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] — prompt caching API 細節、Tool Search API
