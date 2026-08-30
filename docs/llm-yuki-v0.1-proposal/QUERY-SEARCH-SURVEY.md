# Query/Search 方法論調查:Wiki 建立好之後怎麼查詢

**狀態:調查文件(survey),不是決議文件。** 這份文件補的是 `README.md` 討論串裡發現的一個缺口——D1–D23 全部是 Ingest(攝入)/Compile(編譯)/Lint(品質守門)三個循環的決議,呼應 Karpathy 原始模式的三循環之二,但**「Query(查詢)」這第三個循環從沒被正式調查過**,`ARCHITECTURE.md` 裡也沒有對應的模組。這件事不能無限期擱置——D8 的成功判準需要拿 `M3SciQA`/`MMDocRAG` 的 QA pairs 實際問問題、算正確率/F1,這技術上需要一套查詢機制才能執行。

這份文件先把「主流做法怎麼查詢」調查清楚,附上必要的參考程式碼,**還沒有做出任何決議**——要不要採用、採用到什麼程度,留給 `README.md` 之後開一條新決議(暫定 D25——D24 已用於 Document→Source 型別更名)時討論。

**查證深度標註**(沿用 `README.md`「相關參考」的慣例,誠實分級,避免誤讀成每個來源都查證到同樣深度):

| 來源 | 查證深度 |
|---|---|
| Karpathy 原始 gist | 直接查證 gist 原文 |
| LLM-Wiki 論文(arXiv 2605.25480) | 直接查證論文 HTML 全文(摘要 + 正文查詢機制段落),論文本身**沒有公開查詢時的原始碼**,只有敘述性描述 |
| `nashsu/llm_wiki` | **完整原始碼分析**——這次額外深讀了先前只列在 Key-file map、沒細看的 `src-tauri/src/commands/search.rs`(2263 行)與 `src-tauri/src/agent/tools.rs` 的工具定義段落,以下程式碼是實際檔案摘錄 |
| `atomicstrata/llm-wiki-compiler` | 官方 README 查閱,**未 vendor 原始碼**——以下只有 CLI 使用範例,不是內部實作程式碼 |
| `langchain-ai/openwiki` | 官方 README 查閱——**查詢機制完全沒有被記載**,這節沒有真正的參考程式碼可以附 |

---

## 1. Karpathy 原始 gist:最初的種子想法

原文(直接查證,逐字):「You ask questions against the wiki. The LLM searches for relevant pages, reads them, and synthesizes an answer with citations.」以及「good answers can be filed back into the wiki as new pages. A comparison you asked for, an analysis, a connection you discovered — these are valuable and shouldn't disappear into chat history.」

跟 Ingest(單向吸收)、Lint(健檢維護)不同,Query 是**雙向、探索性的**:不修改來源、不做例行維護,而是取出既有知識、彈性綜合答案,並且可以選擇性地把有價值的發現轉存回 wiki——查詢本身也是一種持續累積知識的方式,不是問完就丟。

gist 本身沒有程式碼,只有這段敘述。下面是把這個概念寫成最小可讀的參考虛擬碼(**這是我們自己根據 gist 描述重建的示意,不是 Karpathy 發布的程式碼**),用來對照後面幾節的具體實作差在哪:

```python
# 示意虛擬碼,依 Karpathy gist 的敘述重建,非原始碼
def query_wiki(question: str, wiki) -> str:
    candidate_pages = wiki.search(question)          # "searches for relevant pages"
    contents = [wiki.read(p) for p in candidate_pages]  # "reads them"
    answer = llm_synthesize(question, contents, cite=True)  # "synthesizes an answer with citations"

    if answer.is_worth_keeping():                     # 使用者判斷是否值得保留
        wiki.write_page(title=answer.title, body=answer.text, source_refs=candidate_pages)
        # "filed back into the wiki as new pages"

    return answer.text
```

---

## 2. LLM-Wiki 論文(arXiv 2605.25480):正式化的 agentic 查詢演算法

D14 已經採納這篇論文的 Algorithm 1 當我們自己 Ingest/Lint 執行迴圈的範本,但 Algorithm 1 只涵蓋編譯,論文的查詢機制是另一段獨立的敘述,**論文沒有公開對應的 pseudocode 或原始碼**,以下是直接查證論文 HTML 全文後的逐字/精確轉述。

**核心敘述(查證,逐字)**:「the agent composes wiki_search and wiki_read calls based on intermediate observations, iteratively searching, reading, following links, and checking sufficiency until it gathers sufficient evidence.」

**終止條件(查證,逐字)**:「It terminates when all reasoning chains have been traced, the tool-call budget T_max is reached, or consecutive empty searches exceed patience threshold P.」——三個終止條件是「或」的關係,任一滿足就停。

**兩個工具的定義(查證,逐字)**:
- `wiki_search(query)`:「Searches the Wiki index by prioritizing structured signals such as page names, aliases, tags, and descriptions before falling back to page content.」——**先比對結構化 metadata,比不到才退到全文比對**,不是一開始就做語意相似度。回傳候選頁面 + metadata。
- `wiki_read(paths)`:「Batch-reads directory indices (`_index.md`) or full pages. For knowledge pages, the returned content includes inter-page links that serve as traversal affordances for subsequent hops.」——可以批次讀多個路徑,讀到的內容本身帶連結,是下一跳的線索。

跟傳統 RAG 的核心差異(查證,逐字):「Instead of receiving a fixed top-k context」,LLM-Wiki 把外部知識當成「a compilable, composable, and self-evolving structure」,不是「flat chunks retrieved by embedding similarity」。

**把論文敘述重建成 pseudocode**(**這是我們自己依論文文字重建的示意,論文原文沒有這段程式碼**,重建時特別保留三個終止條件跟「結構化優先」這兩個關鍵約束):

```python
# 示意虛擬碼,依論文敘述重建,非論文原始碼
def llm_wiki_query(question: str, wiki, T_max: int, P: int) -> str:
    evidence = []
    consecutive_empty = 0
    tool_calls = 0

    while tool_calls < T_max and consecutive_empty < P:
        next_action = llm_decide_next_tool_call(question, evidence)  # agent 自己決定下一步
        tool_calls += 1

        if next_action.tool == "wiki_search":
            # 結構化訊號(頁名/別名/tag/描述)優先,查無結果才退到全文比對
            results = wiki.search(next_action.query, prefer_structured_fields=True)
            if not results:
                consecutive_empty += 1
            else:
                consecutive_empty = 0
                evidence.append(("search", results))

        elif next_action.tool == "wiki_read":
            # 可批次讀多頁;讀回的內容含 inter-page link,可以當下一跳線索
            pages = wiki.read_batch(next_action.paths)
            evidence.append(("read", pages))

        if llm_judges_sufficient(question, evidence):
            break

    return llm_synthesize(question, evidence, cite=True)
```

**實測結果(查證,逐字數字)**,對照的三個 baseline(HippoRAG 2 / LightRAG / GraphRAG)都是 D5/D8 已經提過的 GraphRAG-Bench 系文獻常用對照組,`MuSiQue` 正是我們自己 D5 選的 baseline 資料集:

| Benchmark | LLM-Wiki | HippoRAG 2 | LightRAG | GraphRAG |
|---|---|---|---|---|
| HotpotQA (F1) | 0.839 | 0.805 | 0.819 | 0.771 |
| MuSiQue (F1) | 0.739 | 0.624 | 0.659(+8.1) | 0.582 |
| 2WikiMultiHopQA (F1) | 0.911 | 0.831 | 0.847(+6.4) | 0.720 |

三個 benchmark 都是 LLM-Wiki 最高分。

---

## 3. `nashsu/llm_wiki`:一個真實上線實作的完整程式碼

這節的程式碼是**實際檔案摘錄**(標了確切檔案路徑與行號區間),不是重建的示意——這是先前 framework analysis 沒有深入讀的部分,這次特地補讀。

### 3.1 客戶端:查詢前處理(`src/lib/search.ts`,完整 83 行)

CJK 查詢會先做 bigram 切詞(兩字一組)再逐字比對,處理中文沒有天然分詞邊界的問題:

```typescript
// src/lib/search.ts (逐字摘錄,原檔 83 行)
const STOP_WORDS = new Set([
  "的", "是", "了", "什么", "在", "有", "和", "与", "对", "从",
  "the", "is", "a", "an", "what", "how", "are", "was", "were",
  // ...(其餘停用詞略)
])

export function tokenizeQuery(query: string): string[] {
  const rawTokens = query
    .toLowerCase()
    .split(/[\s,，。！？、；：""''（）()\-_/\\·~～…]+/)
    .filter((t) => t.length > 1)
    .filter((t) => !STOP_WORDS.has(t))

  const tokens: string[] = []
  for (const token of rawTokens) {
    const hasCJK = /[一-鿿㐀-䶿]/.test(token)
    if (hasCJK && token.length > 2) {
      const chars = [...token]
      for (let i = 0; i < chars.length - 1; i++) tokens.push(chars[i] + chars[i + 1])  // bigram
      for (const ch of chars) {
        if (!STOP_WORDS.has(ch)) tokens.push(ch)  // 單字也保留
      }
      tokens.push(token)  // 整詞也保留
    } else {
      tokens.push(token)
    }
  }
  return [...new Set(tokens)]
}

export async function searchWiki(projectPath: string, query: string): Promise<SearchResult[]> {
  if (!query.trim()) return []
  const response = await invoke<BackendSearchResponse>("search_project", {
    projectPath: normalizePath(projectPath),
    query,
    topK: 20,
    includeContent: false,
    queryEmbedding: null,          // 有設定 embedding provider 時才會帶值,見 3.2
    embeddingConfig: useWikiStore.getState().embeddingConfig,
  })
  return response.results
}
```

### 3.2 伺服端:三訊號混合檢索核心(`src-tauri/src/commands/search.rs`)

這是整個檔案(2263 行)裡真正的檢索邏輯所在,拆成三段摘錄。

**(a) 主流程 `search_project_inner`——關鍵字掃描 + 向量檢索都跑,再融合**(節錄自 327–484 行,省略部分邊界處理):

```rust
// src-tauri/src/commands/search.rs:327-484(節錄)
pub async fn search_project_inner(
    project_path: String, query: String, top_k: usize,
    include_content: bool, query_embedding: Option<Vec<f32>>,
) -> Result<ProjectSearchResponse, String> {
    let tokens = tokenize_query(&query);
    let mut results = Vec::new();

    // 1) 關鍵字:掃 wiki/ 底下所有 .md 檔,逐檔計分(見 3.3 score_file)
    for entry in WalkDir::new(&wiki_root) /* ...filter .md files... */ {
        let content = fs::read_to_string(entry.path())?;
        if let Some(hit) = score_file(&project_path, entry.path(), &content, &tokens, /*...*/) {
            results.push(hit);
        }
        // 同時把這個頁面的 wikilink 記進 graph_pages,供第 3 步圖擴展用
    }

    // 關鍵字結果先照分數排出名次(token_rank),供後面 RRF 融合用
    let token_rank = /* 依 results 分數排序後,記錄每個 path 的名次 */;

    // 2) 向量:如果呼叫端有帶 query_embedding,才做語意檢索(見 search_by_embedding)
    let mut vector_rank = BTreeMap::new();
    let mut vector_hits = 0;
    if let Some(embedding) = query_embedding {
        let vector_results = search_by_embedding(&project_path, embedding, top_k.max(10)).await?;
        vector_hits = vector_results.len();
        // 記錄每個結果的向量名次(vector_rank)跟原始分數(vector_score)
    }

    // 3) 融合:關鍵字名次 + 向量名次 → RRF(Reciprocal Rank Fusion)分數
    if vector_hits > 0 {
        apply_rrf_scores(&mut results, &token_rank, &vector_rank, &vector_score);
    }
    results.sort_by(/* 依融合後分數排序 */);

    // 4) 圖擴展:從排名最前面的結果當種子,沿 wikilink 擴展一跳(見 blend_graph_results)
    let graph_hits = blend_graph_results(&mut results, &graph_pages, top_k, vector_hits, include_content);

    Ok(ProjectSearchResponse { mode: search_mode(/*...*/), results, /* ... */ })
}
```

**(b) RRF 融合公式**(逐字摘錄,484–503 行):

```rust
// src-tauri/src/commands/search.rs:484-503
fn apply_rrf_scores(
    results: &mut [ProjectSearchResult],
    token_rank: &BTreeMap<String, usize>,
    vector_rank: &BTreeMap<String, usize>,
    vector_score: &BTreeMap<String, f32>,
) {
    for result in results {
        let mut rrf = 0.0;
        if let Some(rank) = token_rank.get(&normalize_path(&result.path)) {
            rrf += 1.0 / (RRF_K + *rank as f64);   // 標準 RRF 公式:1/(k+rank)
        }
        if let Some(rank) = vector_rank.get(&file_stem(&result.path)) {
            rrf += 1.0 / (RRF_K + *rank as f64);
        }
        result.score = rrf;   // 兩路名次各自算一次 RRF 分數,加總
    }
}
```

**(c) 圖擴展配額——向量檢索覆蓋率越低,圖擴展佔比越高(15%–30% 動態調整)**(逐字摘錄,511–519 行):

```rust
// src-tauri/src/commands/search.rs:511-519
/// Reserve 15-30% of the final window for one-hop graph expansion. A full
/// vector window leaves the minimum graph share; sparse vector retrieval moves
/// progressively toward the maximum.
fn graph_result_quota(limit: usize, vector_hits: usize) -> usize {
    if limit < 2 { return 0; }
    let vector_coverage = vector_hits.min(limit) as f64 / limit as f64;
    let ratio = MAX_GRAPH_RESULT_RATIO - (MAX_GRAPH_RESULT_RATIO - MIN_GRAPH_RESULT_RATIO) * vector_coverage;
    ((limit as f64 * ratio).ceil() as usize).clamp(1, limit - 1)
}
```

擴展邏輯本身(`blend_graph_results`,521–660 行)是把目前排名最前面的結果當「種子」,沿頁面內文的 `[[wikilink]]` 找一跳鄰居,鄰居分數用 `1/(rank+1)` 依種子的名次加權——名次越前面的種子,它擴展出來的鄰居分數越高。

**(d) 關鍵字計分是加權啟發式,不是 BM25**(節錄自 `score_file`,818–864 行):沒有 IDF、沒有文件長度正規化,而是檔名完全比對(高權重)+ 標題含完整詞組 + 內容詞組出現次數 + 標題/內容 token 比對分數,各自乘不同權重加總——比 BM25 簡單,但夠用。

### 3.3 查詢是包成一組 agent tool,不是單次呼叫(`src-tauri/src/agent/tools.rs:420-527`)

這對應論文說的「agent 自己組合 search/read 呼叫」——`nashsu/llm_wiki` 把它做成一組具名工具讓 LLM chat agent 自己決定怎麼用:

```rust
// src-tauri/src/agent/tools.rs:420-527(節錄,逐字保留工具描述文字)
ToolSpec {
    name: "wiki.search".to_string(),
    description: "Search generated LLM Wiki pages using backend keyword/vector retrieval.".to_string(),
    parameters: /* { query: string, topK: 1-10 } */
},
ToolSpec {
    name: "wiki.read_page".to_string(),
    description: "Read a project wiki markdown page by project-relative path.".to_string(),
    parameters: /* { path: string } */
},
ToolSpec {
    name: "graph.search".to_string(),
    description: "Retrieve graph relationships, neighbors, backlinks, dependencies, and \
                   connections between project entities. Use concise entity or concept names \
                   rather than a full question.".to_string(),
    parameters: /* { query: string, topK: 1-10 } */
},
ToolSpec {
    name: "source.search".to_string(),
    description: "Search raw source files stored under raw/sources for exact keyword snippets.".to_string(),
    parameters: /* { query: string, topK: 1-10 } */
},
ToolSpec {
    name: "wiki.write_page".to_string(),
    description: "Create a Markdown wiki page under wiki/ with project-bound path checks. \
                   Existing files require allowOverwrite=true.".to_string(),
    parameters: /* { path: string, content: string, allowOverwrite?: bool } */
},
// 另有 web.search / anytxt.search / deep_research.run,略
```

`wiki.search` 走 3.2 的三訊號混合;`graph.search` 是獨立工具,專門查關係/鄰居/backlink,輸入用詞條而非完整問句;`wiki.write_page` 對應 Karpathy「好答案歸檔回 wiki」的具體實作出口。整組工具還透過 `mcp-server/src/index.ts` 暴露成 MCP server,外部 agent(Claude Code、Codex)可以直接呼叫。

---

## 4. `atomicstrata/llm-wiki-compiler`:獨立收斂到同一個模式(僅 CLI 範例,未讀原始碼)

**這節沒有內部實作程式碼**——這個專案沒有被 vendor 進本 repo,以下只是直接查證 README 後轉錄的**文件記載的 CLI 使用方式**,不是我們讀過的原始碼:

```bash
# 以下命令語法轉錄自官方 README,未驗證實際執行結果,未讀內部實作
llmwiki query "這個系統的認證流程是什麼?"          # 對編譯好的 wiki 問「有根據的問題」
llmwiki query "..." --save                        # 把答案存回 wiki(呼應 Karpathy 的歸檔概念)
llmwiki context "實作 OAuth callback" --json       # 產生給下游 agent 用的結構化證據包
llmwiki view --open                                # 唯讀瀏覽 UI:搜尋、圖探索、來源新鮮度標記、引用 chip
```

README 原文對檢索策略的描述(查證,逐字):「Semantic chunk search, BM25 reranking, and wikilink graph expansion build compact evidence packs for queries and agents.」——**語意 chunk 搜尋 + BM25 重排 + wikilink 圖擴展**。這跟第 3 節 `nashsu/llm_wiki` 的「向量 + 關鍵字 + 圖擴展」三訊號融合幾乎同構,差別只在重排演算法用 BM25(有 IDF/文件長度正規化)而不是 RRF。**兩個完全獨立開發的專案收斂到同一個三訊號模式,這點本身是值得注意的證據,不是巧合**。另外還有 MCP server(暴露 query/lint/read/status/eval/context-pack/OKF 交換工具)跟 TypeScript SDK,同樣是「查詢能力對外暴露給 agent」這個共同模式的一部分。

---

## 5. `langchain-ai/openwiki`:誠實記錄一個空白

直接查證 README,**完全沒有記載查詢機制**。文件只講攝入(`--init`/`--update`)跟驅動編譯器本身的 CLI 互動,產出就是純 markdown 檔案。**這節沒有真正的參考程式碼可以附**——下面只是我們自己寫的、對應「文件沒講、只能自己猜」這個情境的最樸素示意,明確標註不是 openwiki 提供的:

```python
# 示意:openwiki 沒有記載查詢機制時,最樸素的下游做法(非 openwiki 提供,自行推測)
import glob
def naive_query(question: str, wiki_dir: str) -> list[str]:
    # 沒有搜尋索引,直接掃全部 markdown 檔案關鍵字比對
    return [f for f in glob.glob(f"{wiki_dir}/**/*.md", recursive=True) if question in open(f).read()]
```

---

## 6. 綜合對照

| 維度 | Karpathy gist | LLM-Wiki 論文 | `nashsu/llm_wiki` | `llm-wiki-compiler` | `openwiki` |
|---|---|---|---|---|---|
| 檢索訊號 | 未指定 | 未指定實作,只講「不是 flat chunk」 | 關鍵字 + 向量 + 圖擴展(RRF 融合) | 語意 chunk + BM25 + 圖擴展 | 無記載 |
| 查詢流程 | search→read→synthesize | agentic 迭代迴圈,有 `T_max`/耐心閾值 `P` 終止條件 | 一組 agent tool(`wiki.search`/`wiki.read_page`/`graph.search`/...),LLM 自主決定呼叫順序 | `llmwiki query`/`context` 指令,細節未讀原始碼 | 無記載 |
| 搜尋優先序 | 未指定 | 結構化 metadata 優先,查無才退到全文 | 檔名/標題精確比對權重高於全文 token | 未讀到細節 | 無記載 |
| 答案要求 | 帶引用 | 未直接提及(重點在證據收集) | 未強制,由 agent 自行決定 | 有「citation chips」UI 元素 | 無記載 |
| 查詢結果寫回 wiki | 明確支援(核心理念之一) | 未提及 | `query`/`synthesis` 頁面型別 + `wiki.write_page` 工具 | `--save` flag | 無記載 |
| 對外暴露 | 未指定 | 未指定 | MCP server + 本機 HTTP API | MCP server + TS SDK | 無 |
| 對照 benchmark | 無 | 贏 HotpotQA/MuSiQue/2WikiMultiHopQA 上的 HippoRAG 2/LightRAG/GraphRAG 2.0–8.1 F1 | 無公開 benchmark | 無公開 benchmark | 無 |

**收斂出的共識**:检索訊號上「關鍵字/BM25 + 向量語意 + wikilink 圖擴展」三者混合是目前兩個獨立實作都選的做法;查詢流程上「agentic 迭代(search→read→追連結→判斷夠不夠)」優於「一次性 top-k」是論文的核心論點,也被 `nashsu/llm_wiki` 的多工具 agent 設計實際印證;「查詢結果可以寫回 wiki」是從 Karpathy 最早的構想就存在、兩個現成實作都各自用不同機制(頁面型別 / `--save` flag)落地的想法。

---

## 7. 跟本 POC 的關係(留給後續決議,這裡不下結論)

目前 `ARCHITECTURE.md` 完全沒有 Query 模組,`SPEC.md` 的 D8 成功判準(拿 `M3SciQA`/`MMDocRAG` QA pairs 算正確率/F1、跟向量 RAG 比較)技術上需要一套查詢機制才能執行——這是這次調查意外浮現的一個實際缺口,不是原本要調查的問題。

如果之後要把這個補成正式決議(暫定 D25——D24 已用於 Document→Source 型別更名),至少要拍板:(a) 查詢要不要走「三訊號混合 + agentic 迭代」,還是這次 POC 先用最簡單的向量 top-k 當 baseline、把混合檢索列為未來優化方向(呼應 D4/D7 的 minimal-scope 精神);(b) 答案要不要強制帶引用;(c) 查詢結果要不要能寫回 wiki——這會牽動 D6 的 OKF conformance,因為新頁面也要合規,也可能需要在 D9 型別系統裡加一個對應型別(呼應 Karpathy 的 `query`/`synthesis`,或比照 `nashsu/llm_wiki` 的做法)。

---

## 參考來源

- Karpathy 原始 gist:https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- *Retrieval as Reasoning via LLM-Wiki*(arXiv 2605.25480):https://arxiv.org/abs/2605.25480
- `nashsu/llm_wiki`(已 vendor,`knowledge-base/frameworks/llm_wiki-0.6.11/`):https://github.com/nashsu/llm_wiki
- `atomicstrata/llm-wiki-compiler`:https://github.com/atomicstrata/llm-wiki-compiler
- `langchain-ai/openwiki`:https://github.com/langchain-ai/openwiki
