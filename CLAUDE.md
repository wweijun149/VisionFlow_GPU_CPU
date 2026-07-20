# CLAUDE.md

本檔提供給 Claude Code（claude.ai/code 與 CLI）在此 repo 工作時參考。與 `AGENT.md` 為同一套規範，`AGENT.md` 為完整版契約，本檔為快速索引與最常用命令。

## 專案概觀

VisionFlow AOI 是配方驅動的 OpenCV 自動光學檢測系統，具備 PySide6 GUI 與可選的 CUDA DLL 加速後端。同一條 `AOIPipeline` 供 CLI、GUI、批次與資料夾監控共用；YAML 配方控制切圖、Detector、判定與輸出。**CPU-only 是完整受支援模式，也是正確性基準。**

## 進入點

- CLI：`python main.py --image <image> --recipe <recipe.yaml> --output <directory>`
- GUI：`python main.py --gui`
- 打包啟動／smoke：`gui_launcher.py`、`VisionFlow AOI.exe --smoke-test`
- Windows 打包：`build_exe.ps1`（使用受版控的 `VisionFlow AOI.spec`）
- CUDA 建置：`gpu/build_cuda_dll.ps1`；驗證 `gpu/validate_cuda_dll.py`；ABI preflight `gpu/preflight_cuda_build.py`

Python 命令一律使用工作區虛擬環境：`.\env\Scripts\python.exe`。

## 模組地圖

- `core/`：pipeline、recipe 載入/建置、tiling、aggregation、reporting、profiling、batch/monitor、result compaction、GPU session/bridge、preprocess plan 與 executor。
- `detectors/`：各 detector 的特徵、幾何、過濾與結果 metadata。
- `gpu/`：CUDA C ABI、kernels、persistent context、build script、native smoke 與 CPU/GPU 驗證。
- `gui/`：PySide6 screens、widgets、workers、status、preview。
- `recipes/`：YAML 配方與 production 預設。
- `tests/`：正確性、fallback、routing 與回歸測試。
- `cuda_practice/`、`design_handoff_aoi_gui/`：僅供學習/設計參考，production runtime 不得依賴。

行為放在最窄的適當模組。不要在個別 detector 內重複 pipeline 或 fallback 策略。

## 必守不變量

- 保留 `gpu.mode` 語意：`cpu` 絕不載入 CUDA、`auto` 可安全 fallback、`cuda` 要求成功且禁止隱藏 CPU fallback。
- GPU step 失敗必須整個 detector 從 CPU 重跑，不得混用部分 GPU 中間結果。
- 不改變 recipe 語意、PASS/NG、座標、defect metadata、輸出格式與排序；允許的數值容差必須先定義並加測試。
- Detector 只宣告 backend-neutral `PreprocessPlan`，由 CPU/CUDA executor 執行共用 typed operators。不得為個別 detector 建立各自的 CUDA workflow/export。
- `CpuPreprocessExecutor` 是正確性基準。新運算先加共用 typed operator 與 CPU reference，detector-named native adapter 只是相容碼。
- 不得以語意不同的較快運算靜默替換（如以 nearest-neighbor 取代 OpenCV `INTER_AREA`）。
- 保留 ABI v1 primitive API；新能力透過 optional export probing 加入以維持舊 DLL 相容。
- 開發機通常沒有 `nvcc`/CMake/NVIDIA GPU。**未實際執行就不得聲稱 CUDA 原始碼已編譯或通過 runtime 驗證**；RTX 3090 待驗收項目保留在 `Todo.md`。

## 唯一 Roadmap

`Todo.md` 是專案唯一工作清單，實作前先讀。不要建立分散的 CPU/GPU/GUI/release Todo 檔。只勾選真正完成的項目；硬體相依項目未在目標機測試前保持未勾。完成變更後更新對應 checkbox，並在 `完成紀錄` 追加一筆日期紀錄。

## Skills

- `aoi-verify-push`：完成程式修改後，依模組類型執行對應驗證矩陣、更新 `Todo.md`、安全 staging 並 commit/push，再對 `main` 開 PR 並合併。詳見 `.claude/skills/aoi-verify-push/SKILL.md`。

## 完成前必跑驗證

```powershell
.\env\Scripts\python.exe -m unittest discover -s tests -v
.\env\Scripts\python.exe -m compileall main.py gui_launcher.py core detectors gui gpu
.\env\Scripts\python.exe gpu\preflight_cuda_build.py
git diff --check
```

依變更類型另加：pipeline/detector/recipe/GPU 改動跑 CLI synthetic smoke（只寫 `outputs_validation/`）；GUI 改動跑 offscreen MainWindow 載入 recipe；打包/spec 改動用 `build_exe.ps1` 建置並跑 `--smoke-test`。CUDA header/source 改動若無 `nvcc` 必須明確回報 DLL 未重建，RTX 項目保持未勾。詳細命令見 `AGENT.md`。

## Git 與產物

- Stage 只加屬於當前任務的檔案，dirty workspace 不用 `git add .`。
- 不 commit release ZIP、`outputs/logs/`、`outputs_validation/`、暫存影像、產生的報告、DLL build 輸出或無關變更。
- 不 reset/覆寫/reformat 無關的使用者變更。
- Commit message 精簡描述完成的結果。完成且驗證過的變更除非使用者要求否則都要 push。
