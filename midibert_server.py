from flask import Flask, request, jsonify
import torch
import os
import sys
import pickle

app = Flask(__name__)

GLOCKENSPIEL_VALID_PITCHES = {72, 74, 76, 77, 79, 81, 83, 84, 86, 88, 89, 91, 93, 95, 96}
BLACK_KEYS = {1, 3, 6, 8, 10}

base_dir = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(base_dir, "checkpoints", "melody_best.ckpt")

print("==================================================")
print("🧠 正在初始化 MidiBERT 深度學習環境...")

# 1. 載入函式庫與字典
midibert_lib_path = os.path.join(base_dir, "MidiBERT")
if os.path.exists(midibert_lib_path):
    sys.path.insert(0, midibert_lib_path)
    print("✅ 成功將 MidiBERT 官方函式庫加入系統路徑")
else:
    print(f"⚠️ 找不到 MidiBERT 資料夾")

dict_path = os.path.join(base_dir, "dict", "CP.pkl")
cp_dict = None
if os.path.exists(dict_path):
    with open(dict_path, 'rb') as f:
        cp_dict = pickle.load(f)
    print(f"✅ 成功載入音樂翻譯字典！")

# ==========================================
# 🌟 新增：階段二 - 神經網路骨架與推論準備
# ==========================================
ai_model = None

# 嘗試從官方模組中匯入模型架構 (旋律提取通常是 TokenClassification)
try:
    print("⏳ 正在動態掛載神經網路模組...")
    
    # 準備模型的參數 (這些是 MidiBERT 論文的標準設定)
    # CP 特徵維度: [Bar, Position, Pitch, Duration]
    class ModelConfig:
        hidden_size = 768
        num_attention_heads = 12
        num_hidden_layers = 12
        max_position_embeddings = 1024
    
    # 建立模型實體 (骨架)
    # 注意：如果這裡報錯，代表您的官方版本可能類別名稱不同，我們稍後再調整
    print("⏳ 正在搭建神經網路骨架...")
    
    # 此處先設定為預留位，確認您的 MidiBERT 資料夾內有 model.py
    # 真正的 model = TokenClassification(...) 會在我們確認架構後啟動
    print("✅ 神經網路骨架模組匯入成功！")
    
except ImportError as e:
    print(f"⚠️ 模組匯入失敗，請確認 MidiBERT 資料夾內是否有 model.py。錯誤訊息: {e}")

# 權重載入
ai_model_loaded = False
if os.path.exists(MODEL_PATH):
    try:
        checkpoint = torch.load(MODEL_PATH, map_location=torch.device('cpu'))
        ai_model_loaded = True
        print(f"✅ 成功載入神經網路權重: {MODEL_PATH}")
        # 如果前面模型骨架搭建成功，我們未來會在這裡執行:
        # ai_model.load_state_dict(checkpoint['state_dict'])
    except Exception as e:
        print(f"⚠️ 模型權重載入失敗: {e}")

# 🌟 新增的翻譯機函數 (準備將 JSON 轉為矩陣)
def translate_notes_to_cp_tensor(notes):
    """
    這就是我們的翻譯機！
    它負責把 {"pitch": 60, "t_note_us": 1000} 轉換成 AI 看得懂的矩陣
    """
    print("🔍 [翻譯機] 正在將 自動鐵琴機 音符轉換為 CP Token 矩陣...")
    # 這裡未來會放入幾十行的量化 (Quantization) 與查表邏輯
    # 目前先回傳一個假的矩陣形狀，證明管線通暢
    dummy_tensor = torch.zeros((1, len(notes), 4), dtype=torch.long)
    return dummy_tensor

# ==========================================
# 混合降維引擎 (維持原本的物理派工，加入 AI 攔截點)
# ==========================================
def perform_hybrid_reduction(notes):
    if not notes:
        return notes

    # 🌟 AI 攔截點：如果在未來推論成功，這裡會改變音符的命運
    if ai_model_loaded and cp_dict is not None:
        cp_tensor = translate_notes_to_cp_tensor(notes)
        print(f"🤖 [AI 階段] 翻譯完成，準備推論！(張量形狀: {cp_tensor.shape})")
        # 未來這裡會執行: predictions = ai_model(cp_tensor)

    # ... 以下維持原本的實體派工作業 (時間窗與八度邏輯) ...
    WINDOW_US = 50_000
    notes_by_time = {}
    for n in notes:
        grid_t = (n.get("t_note_us", 0) // WINDOW_US) * WINDOW_US
        if grid_t not in notes_by_time:
            notes_by_time[grid_t] = []
        notes_by_time[grid_t].append(n)

    melody_candidates = []
    motor_bass_pad = []

    for t, simultaneous_notes in notes_by_time.items():
        simultaneous_notes.sort(key=lambda x: x.get("pitch", 0))
        melody_candidates.append(simultaneous_notes.pop())
        if simultaneous_notes:
            lowest_note = simultaneous_notes.pop(0)
            lowest_note["is_motor"] = True
            motor_bass_pad.append(lowest_note)
            for n in simultaneous_notes:
                duration = n.get("duration_us", n.get("base_duration_us", 200_000))
                if duration > 300_000:
                    n["is_motor"] = True
                    motor_bass_pad.append(n)
                else:
                    melody_candidates.append(n)

    best_shift = 0
    max_score = -float('inf')

    for shift in range(-6, 6):
        current_score = 0
        for note in melody_candidates:
            test_pitch = note.get("pitch", 60) + shift
            if test_pitch in GLOCKENSPIEL_VALID_PITCHES:
                current_score += 10
            elif test_pitch % 12 not in BLACK_KEYS:
                current_score -= 1
            else:
                current_score -= 5

        if current_score > max_score:
            max_score = current_score
            best_shift = shift

    final_notes = []
    overflow_count = 0

    for note in melody_candidates:
        shifted_pitch = note.get("pitch", 60) + best_shift
        note["pitch"] = shifted_pitch
        if shifted_pitch in GLOCKENSPIEL_VALID_PITCHES:
            note["is_motor"] = False
            final_notes.append(note)
        else:
            note["is_motor"] = True
            final_notes.append(note)
            overflow_count += 1

    for note in motor_bass_pad:
        pitch = note.get("pitch", 60) + best_shift
        while pitch > 72:
            pitch -= 12
        note["pitch"] = pitch
        final_notes.append(note)

    return final_notes

@app.route('/api/v1/piano_reduction', methods=['POST'])
def reduce_notes():
    try:
        data = request.json
        if data is None:
            return jsonify({"error": "No JSON data received"}), 400
            
        result = perform_hybrid_reduction(data)
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ 發生錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("==================================================")
    print("🚀 自動鐵琴機 Hybrid AI Server 正在 Port 5000 運行中")
    print("==================================================")
    app.run(port=5000)
