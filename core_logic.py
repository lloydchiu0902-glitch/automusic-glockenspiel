import struct
import math
from typing import List

try:
    import music21
    HAS_MUSIC21 = True
except ImportError:
    HAS_MUSIC21 = False

class NoteData:
    def __init__(self, note_id, pitch, t_note_us, t_trigger_us, is_ai=False, track_id=0):
        self.id = note_id
        self.pitch = pitch
        self.t_note_us = t_note_us
        self.t_trigger_us = t_trigger_us
        self.is_ai = is_ai
        self.track_id = track_id
        self.velocity = 100
        self.triggered = False
        self.audio_played = False
        self.is_motor = False

    def clone(self):
        n = NoteData(self.id, self.pitch, self.t_note_us, self.t_trigger_us, self.is_ai, self.track_id)
        n.velocity = self.velocity
        n.triggered = self.triggered
        n.audio_played = self.audio_played
        n.is_motor = self.is_motor
        n.channel = getattr(self, 'channel', 0)
        n.base_duration_us = getattr(self, 'base_duration_us', 200_000)
        return n

    def to_dict(self):
        return {
            "id": self.id, "pitch": self.pitch, "t_note_us": self.t_note_us,
            "t_trigger_us": self.t_trigger_us, "is_ai": self.is_ai, "track_id": self.track_id,
            "velocity": self.velocity, "is_motor": self.is_motor,
            "motor_id": getattr(self, 'motor_id', 0), "accel_val": getattr(self, 'accel_val', 2000),
            "base_duration_us": getattr(self, 'base_duration_us', 200_000)
        }

    @classmethod
    def from_dict(cls, d):
        n = cls(d["id"], d["pitch"], d["t_note_us"], d["t_trigger_us"], d.get("is_ai", False), d.get("track_id", 0))
        n.velocity = d.get("velocity", 100)
        n.is_motor = d.get("is_motor", False)
        n.base_duration_us = d.get("base_duration_us", 200_000)
        if "motor_id" in d: n.motor_id = d["motor_id"]
        if "accel_val" in d: n.accel_val = d["accel_val"]
        return n

class AdvancedMidiProcessor:
    """進階 AI 樂理與硬體適配管線 (結合 KS 滑動視窗與 Dijkstra 動態靠攏)"""
    
    @staticmethod
    def _music21_global_shift(notes: List[NoteData], valid_pitches: List[int]):
        """步驟 1：基於 Music21 的決定性全域基底移調 (Stage 1)"""
        if not notes: return []
        
        try:
            import music21
            HAS_M21 = True
        except ImportError:
            HAS_M21 = False

        shifted_notes = [n.clone() for n in notes]
        
        if not HAS_M21:
            # Fallback if music21 is not available
            best_shift = 0
            max_score = -1
            black_keys = {1, 3, 6, 8, 10}
            for shift in range(-6, 6):
                current_score = sum(10 if (n.pitch + shift) in valid_pitches else (2 if (n.pitch + shift) % 12 not in black_keys else -5) for n in shifted_notes)
                if current_score > max_score:
                    max_score, best_shift = current_score, shift
            for n in shifted_notes: n.pitch += best_shift
            return shifted_notes

        # 使用 music21 進行調性分析
        stream = music21.stream.Stream()
        for n in shifted_notes:
            try:
                m21_note = music21.note.Note(n.pitch)
                stream.append(m21_note)
            except: pass
            
        try:
            detected_key = stream.analyze('key')
        except:
            detected_key = music21.key.Key('C')

        best_shift = 0
        max_white_ratio = -1
        black_keys = {1, 3, 6, 8, 10}

        # 窮舉 12 個半音階，利用 Interval 計算平移
        for shift_val in range(-6, 6):
            white_count = 0
            for n in shifted_notes:
                p = n.pitch + shift_val
                if p % 12 not in black_keys:
                    white_count += (2 if p in valid_pitches else 1)
                    
            if white_count > max_white_ratio:
                max_white_ratio = white_count
                best_shift = shift_val

        # 應用最佳移調
        for n in shifted_notes:
            n.pitch += best_shift
            
        return shifted_notes

    @staticmethod
    def _dijkstra_voice_leading(notes: List[NoteData], valid_pitches: List[int]):
        """步驟 2：實作 TPS 與 Dijkstra 動態聲部靠攏 (利用 Viterbi 動態規劃解法)"""
        if not notes: return []
        
        black_keys = {1, 3, 6, 8, 10}
        white_keys = [p for p in range(21, 109) if p % 12 not in black_keys]
        
        # 依時間排序建立序列
        notes.sort(key=lambda x: x.t_note_us)
        
        # 建立候選節點矩陣 (Trellis)
        candidates_lattice = []
        for n in notes:
            if n.pitch % 12 not in black_keys and n.pitch in valid_pitches:
                candidates_lattice.append([n.pitch]) # 已是白鍵，無需映射
            else:
                # 尋找最近的 2~3 個白鍵作為候選節點
                cands = sorted(white_keys, key=lambda x: abs(x - n.pitch))[:3]
                candidates_lattice.append(cands)

        # 動態規劃 (Viterbi) 尋找最低成本路徑
        # dp[i][cand] = (min_cost, prev_cand)
        dp = [{c: (abs(c - notes[0].pitch) * 2, None) for c in candidates_lattice[0]}]
        
        for i in range(1, len(notes)):
            current_cands = candidates_lattice[i]
            prev_cands = candidates_lattice[i-1]
            current_dp = {}
            
            for c in current_cands:
                best_cost = float('inf')
                best_prev = None
                
                # 成本 3: 忠誠度成本 (Fidelity) - 距離原始音高的誤差
                fidelity_cost = abs(c - notes[i].pitch) * 2
                
                for p_c in prev_cands:
                    prev_cost, _ = dp[i-1][p_c]
                    
                    # 成本 1: 聲部移動距離 (Voice Leading) - 計程車幾何
                    voice_leading_cost = abs(c - p_c)
                    
                    # 成本 2: 簡化版 TPS (Tonal Pitch Space) 和聲成本
                    # Include C Major (C,E,G) and G Major (G,B,D) chord tones for Glockenspiel
                    is_chord_tone = (c % 12) in {0, 2, 4, 7, 11}
                    tps_cost = 0 if is_chord_tone else 2 
                    
                    # 成本 4: 旋律輪廓成本 (Contour) - 保持旋律的上下起伏方向
                    orig_delta = notes[i].pitch - notes[i-1].pitch
                    cand_delta = c - p_c
                    contour_cost = 0
                    if orig_delta > 0 and cand_delta <= 0:
                        contour_cost = 10
                    elif orig_delta < 0 and cand_delta >= 0:
                        contour_cost = 10
                    elif orig_delta == 0 and cand_delta != 0:
                        contour_cost = 10
                    
                    total_cost = prev_cost + voice_leading_cost + tps_cost + fidelity_cost + contour_cost
                    if total_cost < best_cost:
                        best_cost = total_cost
                        best_prev = p_c
                        
                current_dp[c] = (best_cost, best_prev)
            dp.append(current_dp)
            
        # 回溯找出最佳路徑 (Backtracking)
        best_final_cand = min(dp[-1].keys(), key=lambda k: dp[-1][k][0])
        optimal_path = [best_final_cand]
        
        for i in range(len(notes)-1, 0, -1):
            prev_cand = dp[i][optimal_path[-1]][1]
            optimal_path.append(prev_cand)
            
        optimal_path.reverse()
        
        # 套用最佳路徑
        for i, n in enumerate(notes):
            n.pitch = optimal_path[i]
            
        return notes

    @staticmethod
    def process_midi_notes(file_path, raw_notes: List[NoteData], valid_pitches: List[int], skip_motor_split=False):
        """整合第一階段之改良演算法"""
        if not HAS_MUSIC21:
            raise ImportError("請安裝 music21 進行進階樂理分析: pip install music21")

        # 1. 決定性全域基底移調 (Stage 1)
        shifted_notes = AdvancedMidiProcessor._music21_global_shift(raw_notes, valid_pitches)
        
        # 簡易的高低音軌分離 (防止低音被硬折疊到鐵琴產生雜音)
        melody_notes, motor_notes = [], []
        if shifted_notes:
            if skip_motor_split:
                for n in shifted_notes:
                    if getattr(n, 'is_motor', False): motor_notes.append(n)
                    else: melody_notes.append(n)
            else:
                avg_p = sum(n.pitch for n in shifted_notes) / len(shifted_notes)
                for n in shifted_notes:
                    if n.pitch < avg_p - 10:  # 顯著低於平均音高的當作伴奏馬達
                        n.is_motor = True
                        motor_notes.append(n)
                    else:
                        n.is_motor = False
                        melody_notes.append(n)
        
        # 2. Dijkstra 動態聲部靠攏 (只處理鐵琴軌道)
        mapped_melody = AdvancedMidiProcessor._dijkstra_voice_leading(melody_notes, valid_pitches)

        # 3. 鐵琴全域八度平移 (Global Octave Shift) 與例外折疊
        if mapped_melody:
            avg_melody = sum(n.pitch for n in mapped_melody) / len(mapped_melody)
            glock_center = 91
            octave_shifts = round((glock_center - avg_melody) / 12)
            
            target_max = max(valid_pitches)
            target_min = min(valid_pitches)
            
            for n in mapped_melody:
                n.pitch += int(octave_shifts * 12)
                while n.pitch > target_max: n.pitch -= 12
                while n.pitch < target_min: n.pitch += 12
                
        # 4. 馬達低頻處理
        if motor_notes:
            avg_motor = sum(n.pitch for n in motor_notes) / len(motor_notes)
            m_shift = round((45 - avg_motor) / 12)
            for n in motor_notes:
                n.pitch += int(m_shift * 12)
                while n.pitch >= min(valid_pitches): n.pitch -= 12

        # 合併與複音處理
        final_mapped = mapped_melody + motor_notes
        final_mapped.sort(key=lambda x: x.t_note_us)
        
        final_notes, group = [], []
        time_threshold = 30_000 
        
        for n in final_mapped:
            if getattr(n, 'is_motor', False):
                final_notes.append(n)
                continue
                
            if not group: group.append(n)
            else:
                if abs(n.t_note_us - group[0].t_note_us) <= time_threshold: group.append(n)
                else:
                    final_notes.extend(AdvancedMidiProcessor._reduce_polyphony(group))
                    group = [n]
        if group: final_notes.extend(AdvancedMidiProcessor._reduce_polyphony(group))

        return final_notes, "Dynamic KS & Dijkstra"

    @staticmethod
    def _reduce_polyphony(group):
        if len(group) == 1: return group
        unique_pitches = {}
        for n in group:
            if n.pitch not in unique_pitches or n.velocity > unique_pitches[n.pitch].velocity:
                unique_pitches[n.pitch] = n
        result = list(unique_pitches.values())
        if len(result) > 1:
            lowest_note = min(result, key=lambda x: x.pitch)
            lowest_note.is_motor = True
        return result

class GlockenspielPhysics:
    def __init__(self):
        self.t_comm_us = 20_000
        self.t_solenoid_us = 15_000
        self.h_meters = 0.05
        self.g = 9.81
        self.SOLENOID_PULSE_MS = 60 # 60ms 極限頻寬
        self._update_drop_time()
        
    def _update_drop_time(self):
        t_drop_seconds = math.sqrt((2 * self.h_meters) / self.g)
        self.t_drop_us = int(t_drop_seconds * 1_000_000)
        
    def update_params(self, comm_ms=None, solenoid_ms=None, height_m=None):
        if comm_ms is not None: self.t_comm_us = int(comm_ms * 1000)
        if solenoid_ms is not None: self.t_solenoid_us = int(solenoid_ms * 1000)
        if height_m is not None: 
            self.h_meters = height_m
            self._update_drop_time()
            
    def get_total_delay_us(self): return self.t_comm_us + self.t_solenoid_us + self.t_drop_us
    def calculate_trigger_time(self, note_time_us): return max(0, note_time_us - self.get_total_delay_us())

    def filter_dense_notes(self, notes: List[NoteData]):
        """Stage 3: 實體硬體特徵感知 (過濾低於 60ms 之脈衝)"""
        filtered = []
        track_last_time = {}
        for n in notes:
            if getattr(n, 'is_motor', False) or getattr(n, 'is_ignored', False):
                filtered.append(n)
                continue
                
            t_us = getattr(n, 't_trigger_us', n.t_note_us)
            track = getattr(n, 'track_id', -1)
            last_t = track_last_time.get(track, -self.SOLENOID_PULSE_MS * 1000)
            
            if (t_us - last_t) >= self.SOLENOID_PULSE_MS * 1000:
                filtered.append(n)
                track_last_time[track] = t_us
            else:
                n.is_ignored = True # 標記為略過，觸發退避機制
                filtered.append(n)
        return filtered



class StepperMotorProfiler:
    def __init__(self):
        self.resonance_band = (150, 180)
        self.safe_accel = 10
        self.burst_accel = 50

    def update_params(self, res_min=None, res_max=None, safe_accel=None, burst_accel=None):
        if res_min is not None and res_max is not None: self.resonance_band = (res_min, res_max)
        if safe_accel is not None: self.safe_accel = safe_accel
        if burst_accel is not None: self.burst_accel = burst_accel
        
    def check_and_fold_pitch(self, pitch: int) -> int:
        """Stage 3: 步進馬達共振頻帶八度折疊防護"""
        rpm = int((440.0 * (2.0 ** ((pitch - 69) / 12.0))) * 0.3)
        min_f, max_f = self.resonance_band
        if min_f <= rpm <= max_f:
            # 觸碰共振區間，強制向下折疊一個八度
            return pitch - 12
        return pitch

    def calculate_safe_profile(self, current_rpm, target_rpm):
        min_f, max_f = self.resonance_band
        microstep = 16 if target_rpm < 100 else (8 if target_rpm < 200 else 4)

        if min_f <= target_rpm <= max_f:
            if abs(target_rpm - min_f) < abs(target_rpm - max_f): target_rpm = min_f - 1
            else: target_rpm = max_f + 1

        is_crossing_up = (current_rpm < min_f) and (target_rpm > max_f)
        is_crossing_down = (current_rpm > max_f) and (target_rpm < min_f)
        
        if is_crossing_up or is_crossing_down: return target_rpm, self.burst_accel, microstep
        return target_rpm, self.safe_accel, microstep