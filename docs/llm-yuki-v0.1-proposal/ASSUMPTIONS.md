# 假設與已知風險清單

寫 `SPEC.md`/開始 Phase 2 scaffolding 前的 pre-flight checklist。每項只留一句話結論 + 一句話理由 + 來源決議,詳細討論過程在 `README.md` 對應決議裡,這裡不重複展開。呼應「設計準則」MUST 7:範疇之外的假設必須顯式記錄,不能沉默省略。

---

## A. 已知範疇侷限(這次 POC 刻意不處理,不是遺漏)

1. **三個驗證資料集都是靜態學術 benchmark,測不到「內容持續更新」這個維度**(D5)。`M3SciQA`/`MMDocRAG`/`MuSiQue` 都是固定語料,不像客服知識庫、新聞、財報那種會隨時間變動的活語料——如果之後要驗證「跨領域 + 隨時間更新」這個組合情境,得留給後續 POC。

2. **圖片內容不理解,只保留連結**(D10 二次更正)。Raw Sources 是「資料夾+txt+images/+連結」格式,connector 攝入時把文字檔裡指向圖片的連結原樣保留(對應 OKF 的 `resource`/`sources[]`),但不做 OCR、不接 vision model 解讀圖片內容。**直接影響**:`M3SciQA`/`MMDocRAG` 裡需要看懂圖表才能答對的題目,這次答不出來或準確率偏低,寫 `SPEC.md` 的 Success Criteria 時要處理這點(只評測純文字可答子集,或整體照跑但註明低分主因是範疇限制)。

3. **Raw Sources 假設已經是「資料夾+txt+images/+連結」格式,不負責從 PDF 轉換這個前處理**(D10)。把原始 `M3SciQA`/`MMDocRAG` 論文/長文件轉成這個資料夾結構的轉換動作,算前處理,不算這次 pipeline 要解決的問題。

4. **`Concept` 頁面長度不設上限或拆分規則**(D15)。查證 LLM-Wiki 論文、OKF spec、`llm-wiki-compiler` 三個來源都沒處理這題,這次 POC 也不主動處理。**已知風險**:D12 Phase 1 的 `SelectPages`/`CompileWikiPages` 可能因頁面持續增長撞到 context window;如果實測 `M3SciQA`/`MMDocRAG` 語料時真的撞到,留給後續 POC。

5. **不逐頁人工審閱生成頁面內容品質、不做 wikilink 語意人工評估、不做大規模使用者研究**(D7)。驗證聚焦在 `index.md` 完整性 + `log.md` 稽核軌跡,以及 D5 的 QA benchmark 正確率/F1,不做人工審閱。

6. **不驗證「chunk-based vs passage-based 抽取」的量化對照實驗**(D11)。決議採自然段落/概念單位抽取(不做固定長度 chunk 切割)是根據文獻研究(LLM-Wiki 論文、`llm-wiki-compiler` 都不走 chunk-based)做的架構選擇,不是這次要跑的實驗變因;要量化證明這個選擇比 chunk-based 好,得留給後續 POC。

7. **不驗證「Phase 1 平行 vs 完全序列」的實測吞吐量數字**(D12)。決議採「Phase 1 平行抽取 + Phase 2 序列合併寫入」是參考 `llm-wiki-compiler` 的兩階段形狀做的架構選擇,這次不對照量測兩種做法的實際吞吐量差異。

8. **不測試「兩領域合併成一個跨領域 bundle」的情境**(D9)。D9 的共享核心型別設計只驗證「兩個領域各自產出的 bundle,`Claim`/`Concept` 行為一致、矛盾偵測管線通用」,不測試合併查詢後的實際互通性(例如兩領域頁面互相連結)。

9. **`Writer` 只驗證檔案系統 markdown 一種實作,不驗證 DB 或其他後端**(D16)。介面設計上留了可替換的可能性,但這次 POC 只實作、只驗證檔案系統版本。

10. **`error_book.yaml` 用 YAML 格式是設計選擇,不驗證跟 JSON 等其他格式的效能/可維護性差異**(D14)。格式本身是實作細節,不是這次要驗證的核心假設。

---

## B. 未查證的假設(需要在 scaffolding 時特別留意,可能推翻既有決議)

1. **deepagents 的 skill 抽換機制**(D3/D16)。`Connector`/`Extractor`/`Writer` 都可能替換成 deepagents skill 這個假設,`knowledge-base/frameworks/deepagents-0.7.6/analysis.md` 已於 2026-08-26 決定延後,尚未查證 deepagents 是否原生支援「skill」這個概念、具體是什麼機制(sub-agent?工具註冊?外部檔案結構?)。**風險等級:高**——如果 scaffolding 時發現 deepagents 實際不支援設想的擴充方式,D3/D16 的架構需要回頭調整,不是小修小補。**這是目前所有未查證假設裡影響面最廣的一項。**

2. **`contradicted_by` 在平行抽取(D12 Phase 1)下的實際準確率**。理論上會漏掉同批次裡互相看不到彼此的 passage 之間的矛盾,實際漏掉的比例沒有實測過。依賴 D13 的獨立 lint 管線(每 batch 做 `ContentValidate`)補上,但這個「補上的完整度」本身也沒實測過。**風險等級:中**——如果 lint 管線的補漏率不夠高,D7 的 precision/recall 數字會偏低,需要在 scaffolding 早期就用小規模資料驗證這個補漏機制有沒有實際運作。

3. **`Writer` 增量維護 backlink 邏輯的正確性**(D18)。`Concept.key_facts` 由 `Writer` 在 `ApplyUpdates` 時同步更新、`contradicted_by` 對稱維護,這個機制本身沒有實作過,需要 unit test 驗證。**風險等級:低**——這是一般軟體正確性問題,不屬於 D13 Error Book 要抓的「LLM 編譯品質」錯誤範圍,用標準單元測試就能驗證,不需要額外設計驗證流程。

4. **body/frontmatter 一致性(D17 方向A)的渲染邏輯正確性**。假設「`Writer` 決定性渲染 body 連結」不會出錯,但渲染邏輯本身一樣需要 unit test,不是選了這個方向就自動保證正確。**風險等級:低**,理由同上一項。

---

## C. 待辦(如果之後要驗證上述假設)

- [ ] 補 `knowledge-base/frameworks/deepagents-0.7.6/analysis.md`(對應 B-1,目前優先順序最高但已決定延後,寫 `SPEC.md` 時仍要明確標成未驗證假設)
- [ ] Phase 2 scaffolding 早期,用小規模資料驗證 B-2(`contradicted_by` 補漏率)
- [ ] Phase 2 scaffolding 時為 B-3(`Writer` backlink 維護)、B-4(body 渲染邏輯)各自寫 unit test

---

## 使用方式

寫 `SPEC.md`/開始 scaffolding 前,把這份清單當作最後一次「有沒有漏掉什麼」的檢查表過一遍;有新發現的假設或風險,直接加進對應區塊,不用等到下一次 README 討論才記錄。`SPEC.md` 的 Minimal Scope 應該直接引用 A 區塊的項目(範疇侷限),Success Criteria 訂定時要考慮 B 區塊的風險等級(尤其 B-1 是高風險項,可能影響整個 POC 的可行性,B-2 直接影響 D7 的 precision/recall 判準能不能達標)。
