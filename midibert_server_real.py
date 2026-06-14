from flask import Flask, request, jsonify
import torch
import torch.nn as nn
from transformers import BertConfig
import os
import sys
import pickle
import collections
import time
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Hardware constraints
GLOCKENSPIEL_VALID_PITCHES = {79, 81, 83, 84, 86, 88, 89, 91, 93, 95, 96, 98, 100, 101, 103}
BLACK_KEYS = {1, 3, 6, 8, 10}
GLOCK_MIN_PITCH = 79
GLOCK_MAX_PITCH = 103

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "checkpoints", "melody_best.ckpt")
DICT_PATH = os.path.join(BASE_DIR, "dict", "CP.pkl")
MIDIBERT_LIB_PATH = os.path.join(BASE_DIR, "MidiBERT")


class CastellaMelodyModel(nn.Module):
    """
    Neural network architecture for Castella Control Center.
    Wraps the core MidiBert with a classification head to distinguish melody vs accompaniment.
    """
    def __init__(self, midibert_core):
        super().__init__()
        self.midibert = midibert_core
        self.classifier = nn.Sequential(
            nn.Dropout(0.1),
            nn.Linear(768, 256),
            nn.ReLU(),
            nn.Linear(256, 4)
        )

    def forward(self, x):
        outputs = self.midibert(x)
        hidden_states = outputs.last_hidden_state if hasattr(outputs, 'last_hidden_state') else outputs[0]
        logits = self.classifier(hidden_states)
        return logits


class ModelLoader:
    """
    Responsible for initializing the environment, loading dictionaries,
    and reconstructing the neural network model.
    """
    def __init__(self):
        self.ai_model = None
        self.cp_dict = None
        self.is_loaded = False

    def load_environment(self):
        if os.path.exists(MIDIBERT_LIB_PATH):
            sys.path.insert(0, MIDIBERT_LIB_PATH)
            logging.info("MidiBERT library appended to system path.")
        else:
            logging.warning("MidiBERT library folder not found.")

        if os.path.exists(DICT_PATH):
            with open(DICT_PATH, 'rb') as f:
                self.cp_dict = pickle.load(f)
            logging.info("Music translation dictionary loaded.")
        else:
            logging.error(f"Dictionary not found at {DICT_PATH}.")

    def load_model(self):
        try:
            from model import MidiBert
            sys.path.pop(0)

            bert_config = BertConfig(
                hidden_size=768,
                num_attention_heads=12,
                num_hidden_layers=12,
                max_position_embeddings=512,
                position_embedding_type='relative_key'
            )

            midibert_core = MidiBert(bertConfig=bert_config, e2w=self.cp_dict[0], w2e=self.cp_dict[1])
            self.ai_model = CastellaMelodyModel(midibert_core)

            if os.path.exists(MODEL_PATH):
                logging.info("Loading pre-trained weights into the model.")
                checkpoint = torch.load(MODEL_PATH, map_location=torch.device('cpu'))
                self.ai_model.load_state_dict(checkpoint['state_dict'], strict=False)
                self.ai_model.eval()
                self.is_loaded = True
                logging.info("Model loaded and set to evaluation mode.")
            else:
                logging.error(f"Model checkpoint not found: {MODEL_PATH}")

        except ImportError as e:
            logging.error(f"Failed to import required MidiBERT modules: {e}")
        except Exception as e:
            logging.error(f"Failed to reconstruct or load the model: {e}", exc_info=True)


class SemanticLabeler:
    """
    Handles translation of notes to tensor representations
    and applies model inference to label notes based on semantics.
    """
    def __init__(self, model_loader: ModelLoader):
        self.loader = model_loader

    def translate_notes_to_tensor(self, notes):
        e2w_dict = self.loader.cp_dict[0]
        tensor = torch.zeros((1, len(notes), 4), dtype=torch.long)
        
        us_per_beat = 500_000
        us_per_bar = 2_000_000

        for i, n in enumerate(notes):
            t_us = n.get("t_note_us", 0)
            dur_us = n.get("duration_us", n.get("base_duration_us", 200_000))

            is_new_bar = True if i == 0 else (t_us // us_per_bar) > (notes[i-1].get("t_note_us", 0) // us_per_bar)
            bar_key = 'Bar New' if is_new_bar else 'Bar Continue'
            tensor[0, i, 0] = e2w_dict['Bar'].get(bar_key, 2)
            
            pos_index = int((t_us % us_per_bar) / (us_per_bar / 16)) + 1
            pos_index = min(max(pos_index, 1), 16)
            tensor[0, i, 1] = e2w_dict['Position'].get(f'Position {pos_index}/16', 0)
            
            pitch_val = n.get("pitch", 60)
            tensor[0, i, 2] = e2w_dict['Pitch'].get(f'Pitch {pitch_val}', 0)
            
            beats = dur_us / us_per_beat
            dur_class = max(1, min(63, int(beats * 4))) 
            tensor[0, i, 3] = e2w_dict['Duration'].get(f'Duration {dur_class}', 0)
            
        return tensor

    def label_semantic_notes(self, notes):
        if not notes:
            return notes

        ai_predictions = []
        
        if self.loader.is_loaded and self.loader.cp_dict is not None:
            cp_tensor = self.translate_notes_to_tensor(notes)
            seq_len = cp_tensor.size(1)
            
            with torch.no_grad():
                total_chunks = (seq_len + 511) // 512
                logging.info(f"Sequence length: {seq_len}, processing in {total_chunks} chunk(s).")
                
                start_time = time.time()  
                for start_idx in range(0, seq_len, 512):
                    end_idx = min(start_idx + 512, seq_len)
                    chunk = cp_tensor[:, start_idx:end_idx, :]
                    outputs = self.loader.ai_model(chunk)
                    chunk_preds = torch.argmax(outputs, dim=-1)[0]
                    ai_predictions.extend(chunk_preds.cpu().tolist())
                    
            elapsed_time = time.time() - start_time  
            counter = collections.Counter(ai_predictions)
            logging.info(f"Inference complete. Time: {elapsed_time:.2f}s | Classes: {dict(counter)}")

        melody_candidates = []
        motor_bass_pad = []

        for i, note in enumerate(notes):
            pred_class = ai_predictions[i] if i < len(ai_predictions) else 3
            
            # ⭐️【關鍵調音台】：如果主旋律聽起來反了，把這裡的 2 改成 3
            if pred_class == 2:  
                melody_candidates.append(note)
            else:
                note["is_motor"] = True
                motor_bass_pad.append(note)

        # 找出最佳白鍵平移
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

        # 🌟 關鍵修改：手動升降 KEY (移調)
        # 數值 1 = 升半音, 2 = 升全音 (一個 Key), 12 = 升八度
        MANUAL_KEY_SHIFT = 12  
        best_shift += MANUAL_KEY_SHIFT
        logging.info(f"🛠️ [移調資訊] AI 最佳平移: {best_shift - MANUAL_KEY_SHIFT} | 手動抬升: +{MANUAL_KEY_SHIFT} | 總移調: {best_shift}")

        final_notes = []
        
        # 🌟 1. 鐵琴軌道：強迫升降八度與溢位防護 (G5~G7)
        for note in melody_candidates:
            shifted_pitch = note.get("pitch", 60) + best_shift
            
            # 低於 G5 (79)，升八度
            while shifted_pitch < GLOCK_MIN_PITCH:
                shifted_pitch += 12
            # 高於 G7 (103)，降八度
            while shifted_pitch > GLOCK_MAX_PITCH:
                shifted_pitch -= 12
                
            note["pitch"] = shifted_pitch
            note["is_ai"] = True  
            
            if shifted_pitch in GLOCKENSPIEL_VALID_PITCHES:
                note["is_motor"] = False
                final_notes.append(note)
            else:
                # 手動移調若產生黑鍵，會被丟來這裡給馬達代打
                note["is_motor"] = True
                final_notes.append(note)

        # 🌟 2. 馬達軌道：將伴奏降至鐵琴音域之下，營造低頻鋪底
        for note in motor_bass_pad:
            pitch = note.get("pitch", 60) + best_shift
            
            # 確保馬達的聲音永遠低於鐵琴的最低音 G5 (79)
            # 💡 如果您覺得馬達聲音太低沉怪異，可以嘗試把 GLOCK_MIN_PITCH 改為 90 或更高
            while pitch >= GLOCK_MIN_PITCH:
                pitch -= 12
            note["pitch"] = pitch
            final_notes.append(note)

        logging.info(f"🎵 [硬體階段] AI 鐵琴旋律: {len(melody_candidates)} 音 | AI 馬達伴奏: {len(motor_bass_pad)} 音 (總移調: {best_shift})")
        return final_notes


# Initialize components
model_loader = ModelLoader()
model_loader.load_environment()
model_loader.load_model()
labeler = SemanticLabeler(model_loader)


@app.route('/api/v1/piano_reduction', methods=['POST'])
def reduce_notes():
    try:
        data = request.json
        if data is None:
            return jsonify({"error": "No JSON data received"}), 400
            
        result = labeler.label_semantic_notes(data)
        return jsonify(result)
        
    except Exception as e:
        logging.error(f"Error processing piano reduction request: {e}", exc_info=True)
        return jsonify({"error": "Internal server error during processing"}), 500


if __name__ == '__main__':
    logging.info("Castella Hybrid AI Server initializing on port 5000.")
    app.run(port=5000)