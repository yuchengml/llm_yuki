# LLM Wiki 編譯方法論——架構參考

Implementation-ready 文件:把 `README.md` 裡已經拍板的「怎麼做」細節,抽出來整理成一份不含討論過程、只留結論的實作參考。寫 code 時查這份,不用回頭翻整份討論稿。每節結尾標註來源決議編號,細節理由回 `README.md` 查。

---

## 1. 資料模型(Data Model)

### 1.1 Raw Sources 格式

一個資料夾 = 一份文件,內含:
- 一個 txt 正文檔
- 一個 `images/` 子資料夾
- 正文檔內用 markdown image 連結指向對應圖片,例如 `![alt](images/fig1.png)`

Connector 攝入時原樣保留這個連結(對應 OKF 的 `resource`/`sources[]` 欄位),圖片**內容**不解讀(無 OCR、無 vision model)。假設語料已經是這個格式,不負責 PDF/原始論文 → 這個結構的轉換。

來源:D10、D10 二次更正。

### 1.2 `Claim` schema

| 欄位 | 型別 | 說明 |
|---|---|---|
| `claim_text` | string | 結構化後的主張文字(不是 passage 原文照抄) |
| `source_ref` | string/object | 出處指標,對應 Raw Sources 的文件/段落位置;涉及圖片連結時原樣保留該連結 |
| `confidence` | float(0.0–1.0) | 事實確定性分數 |
| `provenance_state` | enum | `extracted`(直接從原文抽出)/ `merged`(合併多來源)/ `inferred`(LLM 推論)/ `ambiguous`(不確定) |
| `related_concepts` | string[](slug) | 連到哪些 `Concept` 頁面 |
| `contradicted_by` | {slug, reason}[] | 跟哪些既有 Claim 衝突、理由。**候選線索,非權威判定**——lint(第 4 節)仍須完整偵測 |

來源:D9 補充決議。

### 1.3 `Concept` schema

| 欄位 | 型別 | 說明 |
|---|---|---|
| `concept_title` | string | 人類可讀標題 |
| `aliases` | string[] | 別名 |
| `tags` | string[] | 標籤 |
| `summary` | string | 一段話摘要(LLM 生成) |
| `key_facts` | slug[] | 關聯到的 `Claim` 清單——**backlink,由 `Writer` 增量維護,不是 LLM 生成**(見第 5.3 節) |
| `related_pages` | string[](slug) | 相關頁面 wikilink |
| `related_sources` | string[] | 出處/來源 digest 連結 |

**⚠️ 已知風險(D15,未處理)**:`summary`/`key_facts` 等欄位不設長度或筆數上限,`Concept` 頁面可能隨合併次數增加持續變大,`Extractor`/`Merger` 把既有頁面內容餵進 LLM context 時理論上可能撞到 context window 限制。這次 POC 不主動處理(不設拆分規則),細節與範疇侷限見 `ASSUMPTIONS.md` A-4。

來源:D9 補充決議、D18。

### 1.4 型別系統

- 共享核心型別:所有領域都用 `Claim`/`Concept` 這兩個核心型別,核心 pipeline 只寫一套處理這兩型別的邏輯就能跨領域通用
- 領域延伸型別:各領域 skill 自訂,不強制 namespace 前綴,**建議**(非強制)用 `<領域>:<Type>` 命名慣例(例如 `sci-paper:Paper`、`doc:Chart`)
- **⚠️ 型別系統擴充為三型別**(D21 推翻 D20):`Claim`/`Concept`/`Source`——每份 Raw Source 現在有自己專屬的 `Source` 導覽頁,欄位見 1.5 節。`Claim.source_ref`(1.2 節)仍然是連出 wiki 之外、指到 1.1 節 Raw Sources 位置的出處指標,語意不變(D17),`Source` 是額外新增的導覽入口,不是取代它。
- 這次 POC 只驗證兩個領域各自的核心型別行為一致,不測試合併成單一跨領域 bundle 的情境

來源:D9、D20(已由 D21 推翻部分結論)、D21。

### 1.5 `Source` schema

每份 D10 Raw Source 文件一頁,對應 `nashsu/llm_wiki` 的 `source` 型別。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `source_title` | string | 人類可讀標題(來源文件標題或檔名) |
| `source_path` | string | 對應 D10 Raw Source 資料夾位置 |
| `ingested_at` | string(date) | 首次編譯進 wiki 的日期 |
| `summary` | string | 一段話摘要,生成機制見下 |
| `produced_claims` | slug[] | 這份文件產生的 `Claim` 清單——backlink,`Writer` 增量維護(同 D18 機制) |
| `produced_concepts` | slug[] | 這份文件觸及/更新過的 `Concept` 清單——同上 |
| `related_pages` | string[](slug) | 相關頁面 wikilink |

**`summary` 生成演算法(遞迴 batch-reduce)**:

1. 觸發時機:某份文件的所有 passage 都完成 Phase 1 抽取後(該文件所有 `Claim` 已產生),在 Phase 2 `Merger` 階段執行——不摺疊進任何 passage 的抽取呼叫。
2. 收集該文件所有 `Claim.claim_text`,依 context window 預算(借用 `context-budget.ts` 的固定比例配額精神計算,見下方換算)估算是否一次放得下。
3. 放得下:一次 LLM 呼叫直接總結成 `Source.summary`。
4. 放不下:先將 `Claim` 依預算切成多個 batch,各自一次呼叫產生 batch summary;收集所有 batch summary,重複步驟 2 的預算檢查——放得下就一次總結成最終 `summary`,放不下就再切 batch、再總結一輪,遞迴直到收斂。
5. **已知風險,未設安全上限**:`Claim` 數量極端多時,理論上遞迴輪數可能很多輪,這次不設收斂輪數上限保護,見 `ASSUMPTIONS.md`。

來源:D21。

---

## 2. 模組架構(Module Architecture)

採 Ports & Adapters(hexagonal architecture)分層思路(借用軟體工程既有的通用架構命名,不是 LLM-Wiki 生態系文獻裡查到的做法)。

```mermaid
flowchart LR
    RS["Raw Sources<br/>(1.1)"] --> C["Connector<br/>(輸入 Port)"]
    C --> EX

    subgraph O["Orchestrator(核心領域邏輯,不含領域邏輯)"]
        direction TB
        EX["Extractor<br/>Phase 1"] --> ME["Merger<br/>Phase 2<br/>三層保護 + Source.summary<br/>(recursive batch-reduce)"]
        ME -. "軟碰撞去重<br/>(僅設計,不實作)" .-> DEDUP["dedup 偵測"]
        ME --> VA["Validator<br/>Discover"]
        VA --> EBM["ErrorBook 管理"]
        EBM --> FX["Fixer"]
        FX -. "約束注入下一輪" .-> EX
    end

    ME --> W["Writer<br/>(輸出 Port)"]
    EBM -. "log.md 事件" .-> W
    W --> FS[("檔案系統:md 檔案<br/>bundle/(含 Claim/Concept/Source)")]
    W -. "未來可替換" .-> DB[("DB 或其他後端")]
    EBM --> EBS[("error_book.yaml<br/>pipeline-state/")]

    SK["Skill<br/>(deepagents,未查證)"] -. "可替換實作" .-> C
    SK -. "可替換實作" .-> EX
    SK -. "可替換實作" .-> W
```

### 2.1 `Connector`(輸入 Port)

- **職責**:把 Raw Sources 轉成 `Orchestrator` 能處理的統一表示(passage/document 序列)
- **最少介面**:`list_sources()` 列出這次 batch 有哪些來源;`read_source(ref)` 讀出正文 + 保留的圖片連結
- **目前實作**:txt file connector(唯一/預設實作)
- 來源:D2、D10、D16

### 2.2 `Orchestrator`(核心領域邏輯)

不得包含任何領域特定規則(呼應設計準則 MUST 5)。只依 Algorithm 1(第 3 節)的迴圈結構依序呼叫底下五個子模組。

#### 2.2.1 `Extractor`

- **輸入**:passage + 既有頁面 snapshot
- **輸出**:候選 `Claim`/`Concept`(欄位見 1.2/1.3)
- 領域特有的段落切法/型別擴充委派給領域 skill(未查證,見 `ASSUMPTIONS.md` B-1),`Extractor` 本身介面領域無關
- 抽取粒度:文件的自然段落/概念單位,不做固定長度 chunk 切割
- 來源:D9、D11、D12 Phase 1

#### 2.2.2 `Merger`

- **輸入**:`Extractor` 產出的候選
- **職責**:去重(`is_new` 判定)、決定最終內容、生成 `Source.summary`(見下)——**不負責實際持久化**,決定完交給 `Writer`
- **三層合併保護**(D22,套用到既有 `Concept` 頁面的更新,`is_new = false` 時觸發):
  1. **第一層(deterministic,零成本)**:陣列型欄位(`aliases`/`tags`/`key_facts`/`related_pages`/`related_sources`)一律集合聯集,不叫 LLM——是 D18 `key_facts` 增量維護的通用化。
  2. **第二層(LLM 合併 + 長度比例拒絕)**:只有 `summary` 有實質衝突時才叫 LLM 合併;合併後長度 `< 70%` × max(舊/新長度)視為疑似內容流失,拒絕採用,退回第一層結果。70% 門檻借用 `llm_wiki` 的 `BODY_SHRINK_THRESHOLD`。跟 D13 Error Book 的 LLM 語意驗證互補,不重疊。
  3. **第三層(鎖定欄位)**:`concept_title`/`type`/`created` 不管第二層輸出什麼,一律強制回填既有值——D17/D18「決定性優先於 LLM」原則第三次套用。
- **`Source.summary` 生成**:遞迴 batch-reduce,見 1.5 節,歸屬 `Merger` 職責延伸,不是新模組。
- **軟碰撞去重(⚠️ 僅架構設計,這次 POC 不實作)**:比照 `dedup.ts` 的 LLM 分組偵測(命名不同的同一實體,如同義詞/縮寫/跨語言),確認後合併並改寫所有引用。不實作理由見 D22——持續性 LLM 成本 + 必要性未驗證,比照 D16 對 skill 抽換的處理方式。
- 來源:D12 Phase 2、D18、D21、D22

#### 2.2.3 `Validator`

- `StructuralValidate`:deterministic,涵蓋 D6 的 OKF conformance + 擴大範圍的結構性檢查(見第 4.1 節)
- `ContentValidate`:LLM-based(見第 4.1 節)
- 來源:D13 Discover

#### 2.2.4 `ErrorBook` 管理

- 四個函式:`UpdateErrorBook(ℬ, E)` / `ActiveConstraints(ℬ)` / `PeriodicFixDue(ℬ)` / `VerifyAndClose(ℬ, W)`
- 來源:D14

#### 2.2.5 `Fixer`

- `CodeAutoFix`(deterministic,結構性錯誤)/ `LLMPeriodicFix`(LLM,內容性錯誤)
- 來源:D13

### 2.3 `Writer`(輸出 Port)

- **職責**:把 `Merger` 決定的內容、`ErrorBook` 產生的事件實際持久化,並支援讀回(`Extractor` 的 `SelectPages`/`ContentValidate` 需要讀既有頁面內容)
- **目前唯一實作**:檔案系統,寫成 markdown 檔案,對應 `bundle/` 目錄(D6 要求通過 OKF conformance)
- **額外職責**(2.3.1、2.3.2 見下):body 連結渲染、backlink 增量維護
- **硬性約束**:不管未來換哪種實作(如 DB),都必須能匯出/渲染出符合 OKF conformance 的 markdown 檔案集合供驗證
- 來源:D6、D16

#### 2.3.1 body 連結渲染(方向A)

`Writer` 從 `related_concepts`/`contradicted_by`/`source_ref` 決定性渲染出 body 裡的 `## Related Pages`/`## Related Sources` 區塊,**不由 LLM 獨立生成這段文字**——避免 body 與 frontmatter 不一致,不需要新增額外的一致性檢查。`summary` 等敘述文字仍是 LLM 生成,不受影響。

來源:D17。

#### 2.3.2 backlink 增量維護

`Writer` 在 Phase 2 `ApplyUpdates` 時,每次有新 `Claim` 帶 `related_concepts` 寫入,同步把它加進目標 `Concept` 的 `key_facts` 清單;`contradicted_by` 指向的 Claim 也同步維護反向指標(對稱),不需要 LLM 自己想到要雙向都寫。

**目的**:讓「查詢某概念的所有相關 Claim」不需要全庫掃描,直接讀 `key_facts` 即可——這是 D8 要驗證的效率優勢的必要前提。

**責任邊界**:這個增量維護邏輯本身的正確性,是一般軟體測試(unit test)範圍,不屬於 D13 Error Book 處理的「LLM 編譯品質」錯誤分類。

來源:D18。

### 2.4 Skill 抽換原則(⚠️ 未查證假設,見 `ASSUMPTIONS.md` B-1)

`Connector`/`Extractor`/`Writer` 的具體實作都可能是內建程式碼,也可能是一個 deepagents skill——`Orchestrator` 面對的永遠是抽象介面,不需要知道底下是哪一種。**這次 POC 的具體實作(txt connector、markdown writer)都用內建程式碼**,不用 skill 包;介面設計上要讓「換成 skill」是之後可以無痛替換的選項。

來源:D3、D16。

---

## 3. 執行流程(Execution Flow)

直接採納 LLM-Wiki 論文 Algorithm 1 當執行迴圈範本:

```
Input: Source batch X, current Wiki W, directory indices I,
       source archives A, active Error Book constraints C
Output: Updated Wiki W and Error Book ℬ

1: for each source passage x ∈ X do
2:   S ← SelectPages(x, I)
3:   U ← CompileWikiPages(x, S, C)
4:   E_s ← StructuralValidate(U, W)
5:   E_c ← ContentValidate(U, W, A)
6:   E ← E_s ∪ E_c
7:   if E ≠ ∅ then
8:     ℬ ← UpdateErrorBook(ℬ, E)
9:     C ← ActiveConstraints(ℬ)
10:    U ← CodeAutoFix(U, E_s)
11:  end if
12:  W ← ApplyUpdates(W, U)
13: end for
14: if PeriodicFixDue(ℬ) then
15:   W ← LLMPeriodicFix(W, ℬ)
16:   ℬ ← VerifyAndClose(ℬ, W)
17: end if
18: return W, ℬ
```

**對應關係**:

| Algorithm 1 行號 | 對應模組 |
|---|---|
| 1–3(`SelectPages`/`CompileWikiPages`) | `Extractor`(2.2.1),Phase 1,可平行 |
| 4–6(`StructuralValidate`/`ContentValidate`) | `Validator`(2.2.3),**每個 batch 都跑**,含結構性與內容性偵測 |
| 7–10(`UpdateErrorBook`/`ActiveConstraints`/`CodeAutoFix`) | `ErrorBook` 管理 + `Fixer` 的即時部分(2.2.4/2.2.5) |
| 12(`ApplyUpdates`) | `Writer`(2.3),Phase 2,序列化——同時觸發 body 渲染(2.3.1)與 backlink 維護(2.3.2) |
| 14–17(`LLMPeriodicFix`/`VerifyAndClose`) | `Fixer` 的批次部分 + `ErrorBook` 管理,**降頻到每 N batch** |

**執行策略要點**:
- Phase 1(第 1–6 行的抽取與偵測部分)可以對 passage/文章層級平行處理
- Phase 2(第 12 行的 `ApplyUpdates`)必須序列化,避免同一 `Concept` 頁面被並發寫入衝突
- 只有「修正」動作(第 10 行 `CodeAutoFix` 除外,它本來就是即時的;主要是第 15 行 `LLMPeriodicFix`)延後到 periodic,**偵測**(第 4–6 行)不延後,每 batch 都做,好讓約束能盡早生效

來源:D11、D12、D14。

---

## 4. Lint / Error Book

### 4.1 七類錯誤

| # | 錯誤類型 | 分類 | 偵測方法 |
|---|---|---|---|
| 1 | Dangling Links | 結構性 | 連結指向不存在的頁面,跟檔案系統交叉驗證 |
| 2 | Incomplete Pages | 結構性 | 必要區塊缺失(facts/sources),模板完整性檢查 |
| 3 | Malformed Refs | 結構性 | 出處引用格式不對,regex 驗證 |
| 4 | Unseen Overwrite | 結構性 | LLM 改了 Phase 1 沒選中的頁面,集合比對 |
| 5 | Index Inconsistency | 結構性 | `index.md` 跟檔案系統對不上,雙向 diff |
| 6 | Unsupported Facts | 內容性 | `Claim` 沒有 `source_ref` 支撐,source-grounded LLM verification;對 `provenance_state=extracted` 尤其重要 |
| 7 | Cross-Page Contradictions | 內容性 | 相關頁面屬性/日期/關係互相矛盾,sampling-based consistency check,以 `contradicted_by` 候選為起點但不限於此 |

結構性錯誤含 D6 的 OKF conformance 驗證,但範圍更廣(多了 index 一致性、unseen overwrite 這類 pipeline 正確性檢查)。

來源:D13。

### 4.2 五階段生命週期

1. **Discover**——依 4.1 分類偵測錯誤(deterministic validator 或 LLM verification)
2. **Attribute**——追溯根因
3. **Constrain**——根因 formalize 成自然語言約束規則
4. **Inject**——開放中的約束規則加進下一輪編譯 prompt
5. **Verify & Close**——定期重新驗證曾出錯的頁面,錯誤不再出現才標記 closed

來源:D13。

### 4.3 執行時機

| 頻率 | 動作 |
|---|---|
| 每個 batch(Phase 2 寫入完立刻) | 結構性 + 內容性錯誤的 **Discover**;結構性的 **Code Auto-fix**;Attribute→Constrain→Inject |
| 每 N 個 batch | 內容性錯誤的 **LLM Periodic Fix**(只有修正動作延後,偵測不延後) |
| 更低頻率(每 M 個 periodic 週期,或整個 run 結束) | **Verify & Close** |

N/M 具體數值不在架構層級決定,留給 scaffolding 階段依實測效能調整。

**⚠️ 這是 D14 對 D13 原始說法的修正**:D13 原本把內容性錯誤的偵測也歸類成「每 N batch」,對照 Algorithm 1 後修正為「偵測每 batch、只有修正才降頻」。

來源:D13、D14。

### 4.4 Error Book(ℬ)資料結構

**儲存位置**:獨立於 OKF bundle 之外的 pipeline 內部狀態檔案,不放進 D6 要驗證 conformance 的 `bundle/` 目錄。

```
<wiki-instance-root>/
  bundle/                <- 通過 OKF conformance 驗證,只放 Wiki 內容
    index.md              <- 根層索引(D23):三個型別分組,連到各子目錄 index.md
    log.md
    claims/
      index.md             <- 該型別完整清單,每筆條目附一句話描述(D23)
      <slug>.md ...
    concepts/
      index.md
      <slug>.md ...
    documents/
      index.md
      <slug>.md ...
  pipeline-state/        <- 不屬於 OKF bundle,pipeline 自己的內部狀態
    error_book.yaml
```

**欄位**(對照 Algorithm 1 的四個函式介面反推,論文本身沒給欄位清單,以下是本專案自訂設計):

| 欄位 | 說明 |
|---|---|
| `id` | entry 唯一識別碼 |
| `error_type` | 4.1 七類之一 |
| `phenomenon` | Discover 產出,錯誤現象描述 |
| `affected_refs` | 受影響的 `Claim`/`Concept` slug 清單 |
| `root_cause` | Attribute 產出的根因文字 |
| `constraint_rule` | Constrain 產出的約束規則,`ActiveConstraints(ℬ)` 撈出串進下一輪 prompt 的內容 |
| `verification_method` | Verify & Close 怎麼確認錯誤不再發生 |
| `status` | `open` / `closed` |
| `discovered_at_batch` | 發現時的 batch |
| `closed_at_batch` | 關閉時的 batch,`open` 時為 `null` |

**跟 `log.md` 的分工**:`error_book.yaml` 是當前狀態快照,`log.md` 是 append-only 歷史。每次 `UpdateErrorBook`/`VerifyAndClose` 都要同步寫一筆事件進 `log.md`。

來源:D14。

---

## 5. Link / Backlink

### 5.1 六種 link 形式

| # | 形式 | 儲存位置 | 方向 |
|---|---|---|---|
| 1 | body 內文 wikilink | body(人類可讀) | 頁面 ↔ 頁面,OKF 無型別邊標籤,只表示有關聯 |
| 2 | `related_concepts` | frontmatter | Claim → Concept,機器可讀權威來源 |
| 3 | `contradicted_by` | frontmatter | Claim → Claim,語意是衝突,`{slug, reason}` |
| 4 | `source_ref` | frontmatter | Claim/Concept → Raw Source(連出 wiki 之外) |
| 5 | 圖片連結 | Raw Source txt 正文 | 正文 → `images/` |
| 6 | `index.md` 目錄連結(D23:分層,依型別分子目錄各自一份) | `index.md`(根層 + `claims/`/`concepts/`/`sources/` 各一份) | Index → 該層/該型別底下所有頁面 |

另有 `error_book.yaml` 的 `affected_refs`(第 4.4 節),不算 wiki page 內部連結,是 pipeline meta-state 對 wiki content 的連結。

來源:D17、D23(第 6 項由 D23 修正——原本這裡誤標「D1 的 Single Index 規則」,查證 D1 原文後確認 D1 沒講過這件事,是先前寫作時的推論被誤標成引用)。

### 5.2 body/frontmatter 一致性

見 2.3.1。body 的連結區塊由 `Writer` 決定性渲染,不獨立由 LLM 生成,消除不一致的可能性,不需要新增 lint 檢查。

### 5.3 Backlink

見 2.3.2。`Concept.key_facts` 由 `Writer` 增量維護,不是 LLM 生成內容。

### 5.4 `index.md` 撰寫規則與 schema(D23)

**結構**:改採 OKF 的分層索引(progressive disclosure),不是單一攤平檔案:

- **根層 `bundle/index.md`**:依核心型別分三個區塊(`# Claims` / `# Concepts` / `# Sources`),每區塊底下一筆連結連到對應子目錄的 `index.md`,不在根層重複列出個別頁面。
- **子目錄 `claims/index.md` / `concepts/index.md` / `documents/index.md`**:各自完整列出該型別底下的所有頁面連結。

**條目格式**(呼應 OKF spec 的 `* [標題](連結) - 描述` 慣例):每一筆連結都附一句話描述,描述來源:
- `Concept`:取 `concept_title` + `summary`
- `Source`:取 `source_title` + `summary`
- `Claim`:沒有獨立摘要欄位,直接取 `claim_text` 本身當描述

**生成方式**:不論哪一層,`Writer` 在 Phase 2 從檔案系統實際內容 + 各頁面既有欄位決定性重新渲染,不由 LLM 生成——「決定性優先於 LLM」原則第四次套用(前三次:D17 body 連結、D18 backlink、D22 三層保護的陣列聯集/鎖定欄位)。

**明確排除**:不做比型別更深一層的巢狀分層;不採用 OKF 選配的 `okf_version` frontmatter 欄位(bundle 根目錄 index.md MAY 帶,這次沒有跨版本相容性驗證需求)。

來源:D23。

---

## 6. 驗證/評估方式

### 6.1 編譯/維護端正確性

- **`index.md` 完整性**:D23 之後是根層 index + `claims/`/`concepts/`/`sources/` 三個子目錄各自的 index 都要查——每個子目錄的 index 是否完整列出該型別底下所有頁面(無遺漏)、無孤兒頁面,根層 index 是否正確連到三個子目錄,階層跟磁碟實際結構一致
- **`log.md` 稽核軌跡**:人工/合成注入已知矛盾到語料裡,跑完 lint 管線後,比對 `log.md` 實際記錄的偵測/歸因/修正筆數與內容,算 precision/recall

明確排除:逐頁人工審閱內容品質、wikilink 語意人工評估、大規模使用者研究。

來源:D7。

### 6.2 檢索/推理端正確性與對照基準

| 項目 | 角色 |
|---|---|
| `M3SciQA` | 對照領域1(科學論文,窄深,多文件+部分多模態) |
| `MMDocRAG` | 對照領域2(十領域長文件,廣雜,重度多模態) |
| `MuSiQue` | 跨文件多跳問答 baseline(不算第三個領域) |
| 簡單向量 RAG | 對照基準1:回答品質(QA 正確率/F1) |
| `langchain-ai/openwiki` | 對照基準2:量化 + 質化(含矛盾偵測這塊它沒有的能力) |

明確不列入對照:「未優化的 OKF/Karpathy 原版」(`openwiki` 已某種程度扮演這個角色)、「整批塞 context」(`MMDocRAG` 平均 67 頁/文件會撞 context window)。

來源:D5、D8。

---

## 7. 成本統計(Cost Tracking)

### 7.1 記錄機制

每個 pipeline stage 呼叫都記錄一筆 cost event,存進 `pipeline-state/cost_ledger.jsonl`(append-only,一行一個 JSON 事件)——跟 4.4 節的 `error_book.yaml` 同一個道理:pipeline 自己的 meta-state,不需要通過 D6 的 OKF conformance 驗證,不混進 `bundle/log.md`。

```
<wiki-instance-root>/
  bundle/                <- OKF conformance 範圍(不含成本資料)
  pipeline-state/
    error_book.yaml       <- D14
    cost_ledger.jsonl      <- D19,append-only
```

### 7.2 欄位

| 欄位 | 說明 |
|---|---|
| `event_id` | 唯一識別碼 |
| `stage` | 呼叫的模組/函式(對應 2.2/2.3 節的模組劃分,例如 `Extractor.compile`、`Validator.ContentValidate`、`Fixer.LLMPeriodicFix`、`Merger.summarize_source`〔D21 的 `Source.summary` 遞迴 batch-reduce,可加 `round` 欄位標記批次輪數〕) |
| `batch_id` | 對應 3 節的 batch 概念 |
| `tokens_in` / `tokens_out` | LLM 呼叫的輸入/輸出 token 數;**非 LLM 步驟(`CodeAutoFix`、`StructuralValidate`)明確記 0**,不留空 |
| `wall_clock_ms` | 這次呼叫的實際耗時 |
| `timestamp` | 事件發生時間 |

### 7.3 彙總(Rollup)

每個 batch 結束或整個 run 結束時,產生彙總:按 `stage` 分組的 token 總數、按 Phase 1/Phase 2(第 3 節)分組的 wall-clock 總時間、按 4.1 節七類錯誤/兩層修正分組的成本。彙總可以是 `cost_ledger.jsonl` 的聚合查詢結果,不強制另開檔案。

### 7.4 用途

- **驗證 D12 的效能取捨**:D12 選「Phase 1 平行 + Phase 2 序列」時沒有實測數據佐證,`cost_ledger` 提供直接的數據來源,不需要另外設計對照實驗。
- **補上 6.2 節對照基準的第三軸**:除了回答品質、矛盾偵測能力,現在可以用 `cost_ledger` 的數字跟簡單向量 RAG(embedding + 查詢成本)、`openwiki`(每日 CI 整批重新生成成本)做量化的成本/效率對照。

**明確排除**:這次 POC 只做被動記錄與事後分析,不設定成本上限或預算警報這類主動 governance 機制。

來源:D19。

---

## 8. Query 模組(檢索/查詢管線)

來源:D25(`QUERY-SEARCH-SURVEY.md` 的調查為依據)。這是 Karpathy 原始模式三循環的第三個——Ingest/Compile(§2–3)、Lint(§4)之外的 Query 循環,不修改 bundle,只讀取既有頁面、綜合回答。

### 8.1 模組架構

```mermaid
flowchart LR
    Q["question: str"] --> QE

    subgraph QE["QueryEngine (domain, no I/O beyond Writer port)"]
        direction TB
        LC["load_corpus(writer)<br/>→ list[PageRecord]"] --> STRAT
        subgraph STRAT["SearchStrategy(ies)"]
            SS["StructuredSignalSearch<br/>(title/aliases/tags/description → body)"]
            ES["EmbeddingSearch<br/>(NotImplementedError, D25)"]
        end
        STRAT --> FUSE["reciprocal_rank_fusion"]
        FUSE --> GRAPH["expand_via_wikilinks<br/>(one-hop, rank-weighted)"]
        GRAPH --> READ["read top-k full pages<br/>(writer.read_claim/read_concept/read_source)"]
        READ --> SYN["AnswerSynthesizer"]
    end

    SYN --> A["QueryAnswer<br/>(answer text + cited slugs)"]
```

- `SearchStrategy`(domain ABC):`search(query: str, corpus: list[PageRecord], top_k: int) -> list[SearchHit]`. 純函式風格,不碰 `Writer`——語料快照(`PageRecord`)由 `load_corpus(writer)` 一次性建好,之後所有策略/融合/圖擴展都操作這份唯讀快照,不重複打 `Writer`。
  - `StructuredSignalSearch`(domain,具體實作,§8.2):唯一這次 POC 實作的檢索訊號。
  - `EmbeddingSearch`(adapters,具體實作,§8.2 末段):**未實作**,呼叫即拋 `NotImplementedError`——介面留著,實作留白(D25 決議1)。
- `AnswerSynthesizer`(domain ABC):`synthesize(question, hits, corpus_by_slug, batch_id) -> QueryAnswer`。LLM 綜合回答並附引用,具體實作 `LLMAnswerSynthesizer` 在 adapters(呼叫既有的 `OpenAICompatibleClient` + `JsonlCostLedger`,跟 `LLMExtractor` 同一套機制)。
- `NextActionDecider`(domain ABC,只給 `IterativeAgenticQueryEngine` 用):`decide(question, evidence) -> QueryAction`。決定下一步是 `wiki_search`、`wiki_read` 還是 `stop`,具體實作 `LLMActionDecider` 在 adapters。
- `QueryEngine`(domain ABC):`answer(question: str, writer: Writer, top_k: int) -> QueryAnswer`。兩個具體實作見 §8.4/§8.5。

### 8.2 `StructuredSignalSearch`——結構化訊號優先

比照 LLM-Wiki 論文對 `wiki_search` 的敘述(「先比對結構化 metadata,比不到才退到全文比對」):

1. 先比對 `title`(`Claim` 沒有獨立 title,用 `slug`)、`aliases`(僅 `Concept`)、`tags`(僅 `Concept`)、`description` 這幾個結構化欄位,命中給高權重。
2. 上述都沒命中,才退到 `content`(`claim_text`/`summary`)全文比對,權重較低。
3 個以上訊號同時命中的頁面分數疊加,不是取最高分。不是 BM25(沒有 IDF/文件長度正規化),是加權啟發式評分——跟 `nashsu/llm_wiki` 的 `score_file` 同一類取捨(比 BM25 簡單但夠用,§ 調查文件 3.2(d))。

`EmbeddingSearch`(adapters,`adapters/query/embedding_search.py`):實作 `SearchStrategy` 介面,但 `search()` 呼叫立即拋 `NotImplementedError`,訊息指向這條 D25 決議與未來要接的 embedding provider——讓呼叫端(`QueryEngine` 組裝時)可以清楚看到「這是故意留白的架構占位」,而不是缺一個實作類別。

### 8.3 融合與圖擴展

- `reciprocal_rank_fusion(rankings: list[list[SearchHit]], k: float = 60.0) -> list[SearchHit]`:標準 RRF 公式 `score += 1 / (k + rank)`,逐個 ranking 疊加——直接借用調查文件 3.2(b) `nashsu/llm_wiki` 的 `apply_rrf_scores` 公式。這次 POC 只有一個非 stub 策略(`StructuredSignalSearch`),融合步驟先留著(等 `EmbeddingSearch` 之後真的實作,不需要改 `QueryEngine` 的呼叫邏輯)。
- `expand_via_wikilinks(seed_hits, corpus, quota) -> list[SearchHit]`:以融合後排名最前面的 `seed_hits` 為種子,沿 `PageRecord.links`(`related_concepts`/`related_pages`/`key_facts`/`produced_claims`/`produced_concepts` 攤平後的集合)找一跳鄰居,鄰居分數 `1/(seed_rank+1)` 依種子名次加權——借用調查文件 3.2(c) 的 `blend_graph_results` 精神。
- `graph_result_quota(limit, primary_hits) -> int`:配額計算,借用 `nashsu/llm_wiki` 的 `graph_result_quota` 公式(`MIN_GRAPH_RESULT_RATIO`–`MAX_GRAPH_RESULT_RATIO`,依主要訊號覆蓋率動態調整)。這次 POC 沒有向量訊號,`primary_hits` 恆等於 `StructuredSignalSearch` 的命中數,覆蓋率通常偏低,配額多半落在上限附近。

### 8.4 `SinglePassQueryEngine`——單次融合(Karpathy gist baseline)

```python
def answer(self, question: str, writer: Writer, top_k: int) -> QueryAnswer:
    corpus = load_corpus(writer)
    rankings = [strategy.search(question, corpus, top_k) for strategy in self._strategies]
    fused = reciprocal_rank_fusion(rankings)
    graph_hits = expand_via_wikilinks(fused[:_SEED_COUNT], corpus, quota=graph_result_quota(top_k, len(fused)))
    hits = _merge_and_rank(fused, graph_hits)[:top_k]
    return self._synthesizer.synthesize(question, hits, corpus, batch_id)
```

一次性:跑策略 → 融合 → 圖擴展 → 讀回 top-k → 綜合回答,不迭代。角色是這次 POC 最簡單的對照組——沒有 embedding,也沒有 agentic 多跳,純粹測「結構化訊號 + 圖擴展」這個組合本身的檢索品質。

### 8.5 `IterativeAgenticQueryEngine`——agentic 迭代(LLM-Wiki 論文核心論點)

直接依論文敘述重建的 pseudocode(`QUERY-SEARCH-SURVEY.md` §2)實作,只是把 `wiki_search`/`wiki_read` 換成這次 POC 的具體積木:

```python
def answer(self, question: str, writer: Writer, top_k: int) -> QueryAnswer:
    corpus = load_corpus(writer)
    evidence: list[EvidenceItem] = []
    consecutive_empty = 0
    tool_calls = 0

    while tool_calls < self._t_max and consecutive_empty < self._patience:
        action = self._decider.decide(question, evidence)
        tool_calls += 1
        if action.tool == "wiki_search":
            hits = self._strategy.search(action.query, corpus, top_k)
            consecutive_empty = consecutive_empty + 1 if not hits else 0
            evidence.append(EvidenceItem(kind="search", hits=hits))
        elif action.tool == "wiki_read":
            pages = [corpus_by_slug[slug] for slug in action.slugs if slug in corpus_by_slug]
            evidence.append(EvidenceItem(kind="read", pages=pages))
        else:  # action.tool == "stop"
            break

    return self._synthesizer.synthesize(question, evidence, corpus, batch_id)
```

- **終止條件三選一**(調查文件 §2「三個終止條件是『或』的關係」):`evidence` 被 `NextActionDecider` 自己判斷為 sufficient(回傳 `stop`)、`tool_calls` 達 `T_max`、或連續空搜尋達耐心閾值 `P`。
- `wiki_read` 讀到的頁面內容含 `PageRecord.links`,下一輪 `NextActionDecider` 可以看到這些連結決定要不要繼續追——這是論文說的「讀到的內容本身帶連結,是下一跳的線索」,不需要額外的圖走訪邏輯,`corpus`(唯讀快照)本身已經帶著全部連結資訊。
- `T_max`/`P` 的具體數字這次決議不鎖定(D25 決議「明確排除」),留給 scaffolding 依 `M3SciQA`/`MMDocRAG` 實測基準線調整,比照 D15/B-5 的既有精神。

### 8.6 答案與引用

`QueryAnswer`(domain dataclass):`question: str`、`answer: str`、`cited_slugs: list[str]`、`method: str`(`"single_pass"`/`"iterative_agentic"`,供 D8 對照基準的實驗記錄用)。`AnswerSynthesizer` 的 LLM prompt 強制要求回傳 `cited_slugs`(D25 決議3——不像 `nashsu/llm_wiki` 交給 agent 自行決定要不要引用);回傳的 `cited_slugs` 會過濾成只保留確實在這次讀回的頁面集合內的 slug,跟 `Extractor.SelectPages` 對 hallucinated slug 的過濾慣例(§2.2.1)一致,不是讓整次查詢直接失敗。

### 8.7 明確排除

- embedding 檢索的具體實作(D25 決議1)。
- 查詢結果寫回 wiki——不產生新的 `Concept`/其他型別頁面,不呼叫 `Writer.write_*`(D25 決議4)。查詢是唯讀操作,`QueryEngine.answer` 只接受 `Writer` 用來讀,不做任何寫入。
- 兩個 `QueryEngine` 之間的吞吐量/延遲量化對照(D25「明確排除」)——都做是為了都能被驗證用,不是為了互相比較。

---

## 待補齊

這份文件反映 2026-08-30 為止的決議(D1–D25)。如果之後 `README.md` 有新決議或修正既有決議,回頭同步更新對應章節,以最新版本為準。
