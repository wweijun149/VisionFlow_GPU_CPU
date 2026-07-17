---
name: aoi-verify-push
description: Run the VisionFlow AOI validation matrix, update Todo.md, then safely stage, commit and push a completed change. Use after finishing any code change in this repo — pipeline, detector, recipe, GPU/CUDA, GUI, packaging, or CI — and before reporting the work as done. Enforces CPU-first correctness, old-DLL fallback, and the rule that CUDA source is never claimed built/validated unless nvcc actually ran.
---

# aoi-verify-push

完成 VisionFlow AOI 的程式修改後，依模組類型執行對應的驗證矩陣、正確更新 `Todo.md`，再以安全方式 staging、commit 並 push。這是 `AGENT.md` / `CLAUDE.md` 「完成前必跑驗證」與「Git 與產物」規範的可執行版本。

所有 Python 命令一律用工作區虛擬環境：`.\env\Scripts\python.exe`（無此環境時改用當前 `python`，並在回報中說明）。

## 核心原則

- CPU 路徑是正確性基準，也是缺 GPU/DLL 或 CUDA 失敗時的 fallback。
- 不改變 recipe 語意、PASS/NG、座標、defect metadata、輸出格式與排序。
- **開發機通常沒有 `nvcc`/CMake/NVIDIA GPU。未實際執行就不得聲稱 CUDA 原始碼已編譯或通過 runtime 驗證。** RTX 3090 待驗收項目保留在 `Todo.md` 未勾。
- 只勾選真正完成的項目；任何無法執行的驗證都要在回報中明說。

## 步驟

### 1. 開工前

```
git status --short --branch
```

- 讀 `Todo.md` 相關段落與鄰近實作/測試。
- 辨識並保留使用者自有、與本次任務無關的 working-tree 變更，不得 reset/覆寫/reformat。

### 2. 一律要跑的驗證

```powershell
.\env\Scripts\python.exe -m unittest discover -s tests -v
.\env\Scripts\python.exe -m compileall main.py gui_launcher.py core detectors gui gpu
.\env\Scripts\python.exe gpu\preflight_cuda_build.py
git diff --check
```

### 3. 依變更類型加跑

- **pipeline / detector / recipe / tiling / GPU bridge / reporter**：以固定 seed 合成影像跑 CLI smoke，輸出只寫 `outputs_validation/`。
- **GUI**：

  ```powershell
  $env:QT_QPA_PLATFORM='offscreen'
  .\env\Scripts\python.exe -c "from pathlib import Path; from PySide6.QtWidgets import QApplication; from gui.main_window import MainWindow; app=QApplication([]); w=MainWindow(); w.recipe_panel.load_recipe(Path('recipes/PRODUCT_A_AOI_01.yaml')); print(w.windowTitle(), w.recipe_panel.detector_list.count())"
  ```

- **打包 / `gui_launcher.py` / `.spec`**：以 `build_exe.ps1` 建置並跑打包版 `--smoke-test`，涵蓋 bundled recipe/MainWindow 啟動、CPU-only、缺 DLL fallback 等價（GPU call count = 0）與 strict-CUDA 明確失敗。
- **CUDA header / source / API**：跑所有可用的 Python/fake-DLL/static 檢查；檢視 public 宣告、native smoke、validator 與 brace/argument 一致性；若 `nvcc` 不可用，**明確回報 DLL 未重建**，並讓 RTX 3090 編譯、primitive matrix、production 等價、benchmark、壓測項目保持未勾。

任何必跑驗證失敗，先修正並重跑相關完整集合，再進入下一步。

### 4. 更新 Todo.md

- 只把真正完成的項目改成 `[x]`；硬體相依項目未在目標機測試前保持 `[ ]`。
- 在 `## 完成紀錄` 追加一筆 `- [x] YYYY-MM-DD：<完成的結果>`，簡潔描述行為與已跑/未跑的驗證。
- 不建立分散的 CPU/GPU/GUI/release Todo 檔。

### 5. 安全 staging 與 commit/push

只加屬於本次任務的檔案，dirty workspace 不用 `git add .`：

```powershell
git status --short --branch
git add -- <explicit files>
git diff --cached --check
git commit -m "<concise outcome>"
git push -u origin <current-branch>
git status -sb
```

- 絕不 commit：release ZIP、`outputs/logs/`、`outputs_validation/`、暫存影像、產生的報告、打包驗證檔、DLL build 輸出或無關變更。
- push 失敗若為網路錯誤，最多重試 4 次（2s、4s、8s、16s backoff）。
- 除非使用者明確要求，否則完成且驗證過的變更都要 push。

### 6. 回報

- 改了什麼、勾了哪些 roadmap 項目。
- CPU、fallback、GUI、CUDA、相容性影響。
- 實際執行的驗證命令與結果。
- 無法執行的驗證，特別是 `nvcc`／RTX 3090 相關。
- commit hash 與 push 結果。
