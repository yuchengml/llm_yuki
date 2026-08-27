# Wiki Log | 操作紀錄

Append-only chronological record of all wiki operations.
Each entry starts with `## [YYYY-MM-DD] <type> | <title>` — grep-parseable.

Types: `ingest` | `query` | `lint` | `update`

---

## [2026-05-10] ingest | Yadav 2026 — 7 Agent Harness Components
- Pages created: [[wiki/papers/2026-yadav-agent-harness]]
- Pages updated: [[wiki/entities/anthropic]], [[wiki/entities/claude-code]], [[wiki/concepts/agent-harness]], [[wiki/concepts/agent-state-management]], [[wiki/concepts/context-compaction]], [[wiki/concepts/lazy-loading-tools]]
- Key insight: `Agent = Model + Harness`；model-harness coupling 意味著 harness 設計影響模型性能本身（Terminal Bench 2.0，數字未揭露）
- Open questions: coupling 程度能量化嗎？harness 優化的系統性方法？

## [2026-05-10] ingest | Silfverskiöld 2026 — Agentic AI: How to Save on Tokens
- Pages created: [[wiki/papers/2026-silfverskiold-token-savings]]
- Pages updated: [[wiki/concepts/prompt-caching]], [[wiki/concepts/lazy-loading-tools]], [[wiki/concepts/model-routing]], [[wiki/concepts/context-compaction]], [[wiki/entities/anthropic]], [[wiki/entities/claude-code]]
- Key insight: 四種降本策略；LLMRouterBench 發現 learned router 效果接近簡單 baseline（反直覺）；Jia et al. 6x 壓縮同時節省成本並提升性能（需驗證原文）
- ⚠️ Flagged vendor data: Redis semantic caching numbers、CascadeFlow savings numbers
- Open questions: routing 品質下界的工程決策；主動 vs 被動 compaction；Jia et al. 原文方法論

## [2026-05-10] update | Wiki Initialized
- Created directory structure: `raw/`, `raw/assets/`, `wiki/entities/`, `wiki/concepts/`, `wiki/papers/`, `wiki/analyses/`
- Created schema: `CLAUDE.md`
- Created special files: `wiki/index.md`, `wiki/log.md`, `wiki/overview.md`
- Domain: AI / Technology Research
- Language: Bilingual (Traditional Chinese / English)
- Ready for first ingest.
