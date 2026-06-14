# Castella Control Center
**實體自動化樂器之網宇實體展演系統架構與 AI 降維改編模型深度技術規格書**

---

## 一、 摘要 (Abstract)

「Castella Control Center」為一針對自動化實體樂器（包含 15 音階實體鐵琴與 4 軌共振步進馬達陣列）所設計之專業網宇實體（Cyber-Physical Systems, CPS）數位音訊工作站（DAW）。在當代音樂資訊檢索（MIR）與機電整合領域中，將虛擬、無發聲限制的數位音樂數據（如 MIDI）映射至受限的物理硬體，存在極大的「維度縮減（Dimensionality Reduction）」與「物理干涉（Physical Interference）」挑戰。本系統不僅提供完整的非同步圖形化編輯介面與時間軸排程器，更內建了基於 `music21` 的樂理降維演算、Dijkstra 動態聲部靠攏演算法，以及基於 MidiBERT 的神經網路微服務。搭配自主研發的環形緩衝（Ring Buffer）與藍牙 BLE 序列化通訊協定，系統能以極低延遲（<20ms）的精度，將龐大且複雜的交響樂譜重組並完美驅動實體樂器進行即時物理展演。

---

## 二、 系統架構總覽 (System Architecture Overview)

本系統奠基於 **MVP (Model-View-Presenter)** 軟體工程設計模式，採用 PyQt6 構建高反應性之圖形介面，實現視圖與業務邏輯之深度解耦。

### 1. 架構分層設計
- **Model 層 (`model.py`, `core_logic.py`)**：負責數據狀態管理（State Management）、AI 樂理降維演算、硬體物理限制模擬（如落珠重力延遲與頻寬防護），以及 BLE 通訊封包的二進位 CRC-16 序列化。
- **View 層 (`view.py`, `ui_widgets.py`, `motor_widget.py`)**：專注於 UI 渲染。具備自定義鋼琴卷簾（Piano Roll）之客製化繪圖引擎（支援中鍵平移與滾輪縮放），以及 60FPS 渲染之科技感馬達儀表板，完全不涉及底層資料計算。
- **Presenter 層 (`presenter.py`)**：作為事件通訊之中樞（Event Hub）。處理 UI 觸發之所有互動訊號（PyQt Signals）、執行資料綁定（Data Binding）、管理撤銷/重做（Undo/Redo）堆疊，並調度背景執行緒以維持 UI 執行緒的絕對流暢。
- **Workers 層 (`workers.py`)**：獨立之 QThread 背景執行緒，專責處理 I/O 密集與容易阻塞主執行緒的任務，如 BLE 無線雙向通訊與高精度時間軸串流預讀（Pre-buffering）。

---

## 三、 核心演算法與實體映射物理引擎 (Core Algorithms & Physical Mapping)

本系統之核心技術在於解決「無限數位音符」至「有限物理硬體」轉換時造成的和聲崩塌與硬體過載難題：

### 3.1 AI 降維最佳化 (AI Dimensionality Reduction Optimization)

1. **決定性全域基底移調 (Global Base Transposition via Music21)**：
   演算法將遍歷 $[-6, +5]$ 共 12 個半音階的移調空間。針對目標 MIDI 之所有音符，映射至實體鐵琴之 25 個白鍵音域，並採用加權計分法（位於鐵琴有效音域內的白鍵得 2 分，範圍外白鍵得 1 分）。取得全域最大命中率之位移量後，執行無損之全曲移調，最大化硬體打擊效能並維持相對音階關係。
2. **低音語義分離 (Bass Semantic Separation)**：
   在 Unified AI 模式中，系統計算全曲平均音高 $\bar{P}$。當音符音高 $P < \bar{P} - 10$ 時，該音符將被視為低音伴奏，強制轉移至步進馬達陣列發聲，避免鐵琴因極低音被強制折疊至高音域而產生之和聲混亂（Scale Soup）。
3. **Dijkstra 動態聲部靠攏演算法 (Dijkstra Voice Leading)**：
   將殘餘之黑鍵視為網格空間中待映射的節點，利用 Dijkstra 動態規劃演算法尋找最佳的白鍵替代序列。其成本函數 $C_{total}$ 定義為：
   $$ C_{total} = C_{voice\_leading} + C_{fidelity} + C_{contour} $$
   - $C_{voice\_leading}$：相鄰音符映射後之計程車幾何距離。
   - $C_{fidelity}$：映射白鍵與原始黑鍵間的絕對音高偏差。
   - $C_{contour}$：旋律輪廓方向懲罰（確保原本上升之旋律映射後不變為下降）。
4. **全域八度平移與例外折疊 (Global Octave Shift)**：
   在完成聲部靠攏後，計算鐵琴軌道之平均音高，將整段旋律平移至鐵琴物理中央區間（MIDI Pitch 91），完美保留原始旋律的八度跳躍與相對音階形狀。僅對極少數仍超出實體 $[79, 103]$ 範圍的離群值進行單獨的 $\pm12$ 八度折疊。

### 3.2 硬體物理限制防禦 (Hardware Physics & Constraints Guard)

1. **鐵琴重力落珠與頻寬防護 (Gravity Drop & Bandwidth Limiter)**：
   - 延遲補償：依據自由落體公式 $t = \sqrt{\frac{2h}{g}}$ 計算每個音高對應的機械物理延遲，並在軟體時間軸中進行「提前觸發 (AOT Pre-triggering)」。
   - 頻寬極限（60ms 極限頻寬防護）：為防止微控制器（MCU）當機與電磁鐵線圈燒毀，系統將檢測單一打擊槌連續兩次指令的時間差 $\Delta t$。若 $\Delta t < 60ms$，系統將觸發退避機制（Back-off），主動捨棄過密的冗餘音符。
2. **步進馬達共振折疊 (Stepper Motor Resonance Folding)**：
   馬達在特定轉速（如 150-180 RPM）時會產生破壞性的強烈物理共振與失步現象。系統將預判給定音高對應之頻率 $f$，若 $f$ 落入危險頻段，將自動觸發「共振八度折疊（Resonance Octave Folding）」，將該音符平移 12 個半音以瞬間跳脫危險頻段。

---

## 四、 軟體模組詳述 (Software Module Specifications)

### 4.1 系統啟動與底層組態
- **`main.py`**：應用程式進入點。配置了 Python 虛擬機的底層運作邏輯，包含調低 `sys.setswitchinterval` 以增加執行緒切換頻率，並實施 `gc.disable()` 與 `gc.freeze()`，將啟動時創建之大量 PyQt UI 物件移出垃圾回收掃描區，徹底消弭串流期間之卡頓（Micro-stutters）。
- **`requirements.txt`**：羅列全系統依賴套件，包含 `PySide6` (GUI)、`mido` (MIDI 解析)、`music21` (樂理計算)、`bleak` (藍牙協定)、`numpy` 與 `scipy`。

### 4.2 演算法大腦 (`core_logic.py`)
- **`NoteData` 類別**：最小資料結構單元。儲存 `t_note_us` (邏輯發聲時間)、`t_trigger_us` (補償後之實體發送時間)、`pitch`、`duration` 及硬體指向屬性 (`is_motor`, `track_id`)。
- **`AdvancedMidiProcessor` 類別**：封裝所有 AI 與樂理處理之靜態方法。包含 `_music21_global_shift`、`_dijkstra_voice_leading`，與負責合併相同音符與修剪和弦之 `_reduce_polyphony`。
- **`GlockenspielPhysics` 類別**：計算實體延遲常數並提供 `filter_dense_notes` 方法來保障硬體線圈壽命。
- **`StepperMotorProfiler` 類別**：管理馬達物理參數，提供 `check_and_fold_pitch` 來動態閃避危險共振。

### 4.3 數據層與通訊層 (`model.py`)
- **`UnifiedBLESerializer` 類別**：客製化 BLE 二進位封包建構器。採用 16-byte 定長封包設計，第一位元組做為 Command Type，結尾附帶 `calc_crc16` 產生之 2-byte 校驗碼。內建 `_get_buffer` 環形緩衝池以避免記憶體碎裂。
- **`MidiBERTMicroserviceClient` 類別**：微服務網路客戶端，以 HTTP POST 發送 JSON 至 MidiBERT 後端進行深度神經網路推理。
- **`CastellaModel` 類別**：系統唯一之資料真實來源 (Single Source of Truth)。管理系統配置檔 (Config)、`all_notes` 清單、Undo/Redo Stack，並透過 `re_route_all` 負責執行音符至硬體的最終派發與合法性檢核。

### 4.4 視圖層 (`view.py`)
- **`ImportMidiDialog` 類別**：負責擷取使用者所選擇之 AI 降維模式（如 `unified_ai`、`ai_midibert` 等）。
- **`CastellaView` 類別**：繼承自 `QMainWindow` 之主視窗。負責排版所有 UI 模組，將所有的按鍵點擊、滑鼠事件封裝為語義化的 PyQt Signals（如 `sig_req_play`, `sig_notes_changed`），並暴露 `render_notes`、`update_playhead` 等 API 供 Presenter 呼叫。

### 4.5 介面邏輯控制器 (`presenter.py`)
- **`CastellaPresenter` 類別**：軟體的心臟。在 `_connect_signals` 中將所有的 Model 變更與 View 事件綁定。管理 `BLEWorker` 與 `PlaybackWorker` 的生命週期。具備完善的狀態機邏輯以處理連線狀態（Connecting, Connected, Disconnected）與播放狀態的切換。

### 4.6 客製化圖形元件 (`ui_widgets.py` & `motor_widget.py`)
- **`PianoRollView` 類別** (`ui_widgets.py`)：繼承自 `QGraphicsView` 的高效能 2D 繪圖引擎。精確繪製黑白鍵背景網格、節拍線與鐵琴專屬安全音域（綠色框線）。覆寫了滑鼠中鍵與滾輪事件以實現如商業 DAW 般的無縫平移與縮放體驗。
- **`NoteGraphicItem` 類別** (`ui_widgets.py`)：代表實體音符之 `QGraphicsItem`。支援滑鼠拖曳（即時修改時間與音高），並利用 QLinearGradient 繪製帶有柔和光暈與微動畫之 UI 質感。
- **`SciFiMotorWidget` 類別** (`motor_widget.py`)：極具科技感的馬達狀態監控儀表板。利用 PyQt 動畫框架，不僅即時繪製旋轉的幾何轉子，更在馬達觸發危險共振時引入了 `trigger_shake` 實體震動特效（Screen Shake），提供強烈的物理反饋。

### 4.7 背景工作執行緒 (`workers.py`)
- **`BLEWorker` 類別**：利用 `asyncio` 與 `bleak` 庫建立跨平台之藍牙序列埠 (Nordic UART) 連線。維持與 Arduino 端的常駐心跳檢測（Heartbeat）。
- **`PlaybackWorker` 類別**：精確的時間軸排程器。以微秒（Microseconds, $\mu s$）為單位掃描 `all_notes`。它不僅會在 `PREBUFFER_TIME` 內提早將指令注入 BLE 佇列以抵銷藍牙傳輸延遲，更實現了 `trigger_backfill` 演算法，以應對 Arduino 環形緩衝區溢位時的主動補發請求機制，確保音樂展演絕不掉幀。

### 4.8 其他微型模組
- **`audio_synth.py`**：軟體音訊合成器（Soft Synth）。在無硬體連線狀態下，利用 `numpy` 與 `scipy` 生成包絡線（Envelope）與合成波形，以 `QtMultimedia` 即時發聲，模擬硬體表現。
- **`settings_ui.py`**：`HardwareSettingsDialog` 負責儲存 Arduino 的實體參數（如延遲補償毫秒數、馬達安全轉速上限），並提供手動觸發單顆電磁鐵的射擊測試介面。
- **`midibert_server_real.py`**：可於獨立伺服器運行的 Flask API，負責載入預訓練之神經網路模型以進行多聲部語義分割。

---

## 五、 結論與未來展望 (Conclusion and Future Work)

Castella Control Center 透過嚴謹之軟體工程架構（MVP）、無鎖環形佇列（Lock-free Ring Buffer）與高容錯藍牙協定，成功消弭了虛擬軟體與實體硬體間之非同步通訊壁壘。而其引入之基於 Music21 與 Dijkstra 最佳化之網宇實體降維模型，更使得任意結構的數位鋼琴曲譜，皆能以極低的資訊熵損失轉化為受限硬體上的優雅物理展演。

本系統高度模組化的架構與完善的物理避險機制，已為自動化樂器控制樹立了技術標竿。未來的研究與開發將著重於橫向擴展，計畫整合更高維度與不同發聲原理的樂器矩陣（如自動鼓機、機械弦樂器或管風琴陣列），進一步拓展網宇實體音樂藝術的展演邊界。
