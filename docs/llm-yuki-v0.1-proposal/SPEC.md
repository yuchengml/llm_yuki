# POC Spec: LLM Wiki 知識編譯與推理

Date: 2026-08-26

## Hypothesis

以 OKF(Open Knowledge Format)規格與 Karpathy 原始 LLM Wiki 三層架構(Raw Sources / Wiki / Schema)為基礎,補上「lint 診斷矛盾 → 根因歸因 → 針對性修正」的差異化機制,建立一套「編譯一次、持續維護」的領域無關 LLM Wiki 知識庫編譯方法論——這套方法論在(a)跨文件多跳推理準確率、(b)矛盾偵測的 precision/recall、(c)token 與時間成本效率三個面向,是否優於傳統向量 RAG 與現成的 `openwiki` 工具,且能否在特質差異大的兩個領域(`M3SciQA` 科學論文 / `MMDocRAG` 十領域長文件)上驗證其領域可移植性?

## Minimal Scope

- 測試領域限定 `M3SciQA` + `MMDocRAG` 兩個;`MuSiQue` 只當多跳問答 baseline,不算第三個領域
- 只處理純文字,圖片連結保留但內容不理解(無 OCR/vision)
- Raw Sources 假設已是「資料夾 = 文件,txt + `images/` + 連結」格式,不含 PDF → 此格式的轉換
- `Concept` 頁面長度不設上限或拆分規則
- 抽取粒度採自然段落/概念單位,不驗證與固定長度 chunk 切割的量化對照
- 執行策略採「Phase 1 平行抽取 + Phase 2 序列合併寫入」,不驗證與完全序列做法的吞吐量對照
- 不測試兩領域合併成單一跨領域 bundle 的情境
- 不逐頁人工審閱生成頁面內容品質、不做 wikilink 語意人工評估、不做大規模使用者研究
- `Writer` 只驗證檔案系統 markdown 一種實作;`index.md` 採 OKF 分層索引,依 `Claim`/`Concept`/`Source` 分子目錄各自建立、每筆條目附一句話描述,由 `Writer` 決定性生成(D23)
- 型別系統為 `Claim`/`Concept`/`Source` 三個核心型別(D21);`Source` 的 `summary` 用遞迴 batch-reduce 生成,不設收斂輪數上限保護
- `Merger` 的合併機制含三層保護(陣列聯集/LLM合併+70%長度比例拒絕/鎖定欄位,D22),但軟碰撞去重(命名不同的同一實體偵測)只做架構設計,這次不實作
- deepagents 的 skill 抽換機制(見 `ASSUMPTIONS.md` B-1)列為未查證假設,`analysis.md` 延後,這次 POC 的 `Connector`/`Extractor`/`Writer` 具體實作一律用內建程式碼,不驗證 skill 抽換本身是否可行
- 成本統計(`cost_ledger.jsonl`,見 `ARCHITECTURE.md` 第 7 節)只做被動記錄與事後分析,不做主動的成本上限/預算警報 governance

完整範疇侷限與未查證假設清單見 `ASSUMPTIONS.md`。實作架構細節見 `ARCHITECTURE.md`。

## Success Criteria

**Confirmed**(以下皆需成立):
- 編譯/維護正確性:`index.md` 完整性檢查通過(無孤兒頁面、無遺漏);`log.md` 稽核軌跡對人工注入的已知矛盾,偵測 precision/recall 達到 scaffolding 階段依實測基準線訂出的門檻
- 檢索/推理正確性:`M3SciQA`/`MMDocRAG` 的 QA 正確率/F1,優於簡單向量 RAG 對照組(純文字可答子集,呼應 Minimal Scope 的多模態限制)
- 跨領域可移植性:`Claim`/`Concept` 核心型別與矛盾偵測管線,在兩個領域上都能跑通,不需修改核心 pipeline(僅透過領域客製化邏輯調整)
- 相對 `openwiki` 的差異化:矛盾偵測(diagnose → 根因歸因 → 針對性修正)產出可具體展示的偵測與修正紀錄,`openwiki` 沒有對應能力
- 成本效率:依 `cost_ledger.jsonl`(D19)算出的 token 與時間成本,跟簡單向量 RAG(embedding + 查詢成本)、`openwiki`(每日 CI 整批重新生成成本)相比,「編譯一次、持續維護」的總成本不明顯劣於兩者(具體門檻留給 scaffolding 階段依實測數字訂)

**Not confirmed**(任一項即視為未確認):
- 核心型別/矛盾偵測管線需要為特定領域另寫核心邏輯才能運作(違反領域無關的設計前提)
- 矛盾偵測 precision/recall 明顯低於可接受門檻,判定差異化機制未達預期效果
- QA 正確率/F1 明顯劣於向量 RAG 對照組,未能證明編譯式 wiki 相對檢索式 RAG 的優勢
- 成本效率明顯劣於向量 RAG 與 `openwiki`,判定「編譯一次、持續維護」的效率主張不成立

**待決定**:量化門檻的具體數字留給 Phase 2 scaffolding 依實測基準線調整,不在 SPEC 定案時鎖定。
