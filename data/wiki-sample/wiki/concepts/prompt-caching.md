---
type: concept
name_en: "Prompt Caching"
name_zh: "提示詞快取"
aliases: ["KV cache", "prefix caching", "K/V caching", "prompt cache"]
tags: [efficiency, llm, infrastructure]
source_count: 1
updated: 2026-05-10
---

# Prompt Caching（提示詞快取）

> 儲存並重用已計算的 K/V tensors，避免每次 API 呼叫重新處理相同的 prompt prefix。

---

## What It Is | 定義

LLM 在生成回應前必須先「處理」整個 prompt——token 化 → 向量化 → 在每個 attention 層計算 K/V tensors。這個計算有成本（時間與金錢）。

**Prompt caching** 的做法是：將這些 K/V tensors 快取起來，下次有相同 prefix 的請求時，直接讀取快取，跳過重新計算。

---

## Why It Matters | 重要性

對於有長系統提示（工具定義、上下文背景、指令）的 agent，每次 API 呼叫都重新計算相同的靜態部分是純粹的浪費。

**成本影響**：cached input tokens 在主要 provider 上可享受最高 **90% 折扣**。對於 90% 靜態的長系統提示，這是最容易實現的成本節省之一。

---

## How It Works | 機制

**KV Cache 的底層原理**

1. Prompt 被 tokenize → 轉成向量
2. 每個 attention 層計算 K/V tensors
3. 推理引擎快取這些 tensors
4. 下次請求，先確認 prefix 是否有對應快取 → 若有，載入 tensors 跳過計算

**關鍵約束：必須是完全相同的 prefix（exact token match）**。任何改變（加一個空格、重排工具順序、在靜態部分插入時間戳）都會 invalidate 快取。

**因此，prompt 結構規則：靜態內容放最前，動態內容放最後。**

---

## Provider 實作差異

| Provider | 啟用方式 | 最低長度 | 折扣 | TTL | 備注 |
|---------|---------|---------|------|-----|------|
| **OpenAI** | 自動（1024+ tokens） | 1024 tokens | 最高 90% off | ~5–10 min | 靜態 prefix 需 >256 tokens；可加 `prompt-cache-key` 提升 hit rate |
| **Anthropic** | 手動加 `cache-control` | — | 同等折扣，但**需付儲存費** | ~5–10 min（可延長至 1 小時，2x 費用） | 若使用不當，Anthropic 比 OpenAI 更貴 |
| **vLLM（自架）** | `--enable-prefix-caching` flag | — | 節省計算時間（自架無 per-token 費用） | 受 GPU 記憶體限制 | `--block-size` 控制 block 大小；`--kv-cache-memory-bytes` 設定快取大小 |

---

## Semantic Caching | 語意快取（相關但不同的概念）

Semantic caching 是另一種策略：若新請求與過去請求**語意相似**（而非完全相同），直接返回快取答案。

- 優點：可處理同義問法（"What's the capital of France?" ≈ "France's capital city?"）
- 缺點：需要 embedding、similarity threshold、TTL 策略、user scoping、錯誤快取的 rollback 機制

> ⚠️ **Redis 聲稱 semantic caching 可減少 68.8% API 呼叫、40–50% latency 改善**，但這是廠商 marketing 數字，基於 clear Q&A use case。一般 agent 工作負載效果可能顯著低於此。建議在看到日誌中的重複模式後再考慮引入，而非一開始就實作。

**適合場景**：Q&A bot、問題重複率高
**不適合場景**：coding agent、每次請求 unique 的工作負載

---

## Debates & Open Questions | 爭議與未解問題

- 快取 TTL 延長（Anthropic 1 小時 2x 費用）在哪些場景下划算？
- Semantic caching 的 threshold 設定沒有標準答案，各自取捨
- 若系統提示需要頻繁更新（如含版本號），如何平衡 cache hit rate 與資訊新鮮度？

---

## Key Papers | 代表論文

- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]] — Provider 比較、機制詳解、成本估算

---

## Sources | 來源

- [[wiki/papers/2026-silfverskiold-token-savings|Silfverskiöld 2026]]
