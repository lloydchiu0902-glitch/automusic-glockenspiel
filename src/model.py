import time
import random
import math
import re
import struct
import json
import os
import urllib.request
import urllib.error
from typing import List

try:
    import mido
    HAS_MIDO = True
except ImportError:
    HAS_MIDO = False

from core_logic import NoteData, GlockenspielPhysics, AdvancedMidiProcessor, StepperMotorProfiler

GLOCKENSPIEL_MAP = {
    79: 0, 81: 1, 83: 2, 84: 3, 86: 4, 88: 5, 89: 6,
    91: 7, 93: 8, 95: 9, 96: 10, 98: 11, 100: 12, 101: 13, 103: 14
}

original_clone = NoteData.clone
def new_clone(self):
    n = original_clone(self)
    n.velocity = getattr(self, 'velocity', 100) 
    n.is_motor = getattr(self, 'is_motor', False)
    n.track_id = getattr(self, 'track_id', 0)
    n.motor_id = getattr(self, 'motor_id', 0)
    n.is_ignored = getattr(self, 'is_ignored', False)
    n.duration_us = getattr(self, 'duration_us', 200_000)
    n.base_duration_us = getattr(self, 'base_duration_us', 200_000)
    n.glide_to_next = getattr(self, 'glide_to_next', False)
    n.accel_val = getattr(self, 'accel_val', 2000)
    n.effective_pitch = getattr(self, 'effective_pitch', self.pitch)
    n.chorus_motor_id = getattr(self, 'chorus_motor_id', None)
    n.chorus_pitch = getattr(self, 'chorus_pitch', None)
    n.is_generated = getattr(self, 'is_generated', False) 
    n.midi_portamento = getattr(self, 'midi_portamento', False) 
    return n
NoteData.clone = new_clone

def calc_crc16(data) -> int:
    crc = 0x0000
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000: crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else: crc = (crc << 1) & 0xFFFF
    return crc

class UnifiedBLESerializer:
    def __init__(self):
        self.pool_size = 1024
        self.pool = [bytearray(16) for _ in range(self.pool_size)]
        self.pool_idx = 0
        self.seq_num = 0
        self.history = {}
        for b in self.pool: b[0], b[1] = 0xFE, 0xFE

    def _get_buffer(self):
        b = self.pool[self.pool_idx]
        self.pool_idx = (self.pool_idx + 1) % self.pool_size
        return b
        
    def _build(self, cmd_type, motor_id, timestamp_us, payload_bytes):
        buf = self._get_buffer()
        struct.pack_into('<BBH', buf, 2, cmd_type, motor_id, self.seq_num)
        struct.pack_into('<I', buf, 6, int(timestamp_us))
        struct.pack_into('4s', buf, 10, payload_bytes)
        crc = calc_crc16(memoryview(buf)[:14])
        struct.pack_into('<H', buf, 14, crc)
        
        self.history[self.seq_num] = bytes(buf)
        old_seq = (self.seq_num - 3000) % 65536
        if old_seq in self.history: del self.history[old_seq]
            
        self.seq_num = (self.seq_num + 1) % 65536
        return buf

    def create_sync_command(self, current_time_us=0):
        self.seq_num = 0
        self.history.clear()
        return self._build(3, 0, current_time_us, b'\x00\x00\x00\x00')
        
    def create_note_command(self, note):
        track_mask = 1 << getattr(note, 'track_id', 0)
        return self._build(1, 0, note.t_trigger_us, struct.pack('<I', track_mask))
        
    def create_motor_command(self, rpm, accel, motor_id, timestamp):
        return self._build(2, int(motor_id), timestamp, struct.pack('<HH', int(rpm), int(accel)))

    def create_inquiry_command(self):
        buf = bytearray(16)
        buf[0:2] = b'\xFE\xFE'
        struct.pack_into('<BBH', buf, 2, 4, 0, 0)
        struct.pack_into('<I', buf, 6, 0)
        struct.pack_into('4s', buf, 10, b'\x00\x00\x00\x00')
        crc = calc_crc16(memoryview(buf)[:14])
        struct.pack_into('<H', buf, 14, crc)
        return buf

class MidiBERTMicroserviceClient:
    API_ENDPOINT = "http://127.0.0.1:5000//api/v1/piano_reduction"
    
    @staticmethod
    def request_piano_reduction(notes: List[NoteData]) -> List[NoteData]:
        payload = json.dumps([n.to_dict() for n in notes]).encode('utf-8')
        req = urllib.request.Request(
            MidiBERTMicroserviceClient.API_ENDPOINT, 
            data=payload, 
            headers={'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(req, timeout=120.0) as response:
                if response.status == 200:
                    resp_data = json.loads(response.read().decode('utf-8'))
                    if isinstance(resp_data, dict):
                        notes_data = resp_data.get('notes', [])
                    else:
                        notes_data = resp_data
                    return [NoteData.from_dict(d) for d in notes_data]
                else:
                    raise Exception(f"微服務回應異常: HTTP {response.status}")
        except urllib.error.URLError as e:
            raise ConnectionError(f"無法連線至 MidiBERT 服務...\n詳細錯誤: {str(e)}")

class AutoMusicModel:
    def __init__(self):
        self.physics = GlockenspielPhysics()
        self.motor_profiler = StepperMotorProfiler()
        self.serializer = UnifiedBLESerializer()
        self.all_notes = []
        self.undo_stack = []
        self.clipboard = []
        
        self.sustain_multiplier = 1.0
        self.motor_temp = 35.0
        self.hit_rate = 100.0  
        
        self.detected_is_minor = False 
        
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.library_dir = os.path.join(base_dir, "Songs")
        os.makedirs(self.library_dir, exist_ok=True)
        
        # 自動轉移舊版 song_library.json
        old_library = os.path.join(base_dir, "song_library.json")
        if os.path.exists(old_library):
            try:
                with open(old_library, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
                for name, data in old_data.items():
                    # 清理不合法的檔名字元
                    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).rstrip()
                    if not safe_name: safe_name = "未命名歌曲"
                    new_path = os.path.join(self.library_dir, f"{safe_name}.json")
                    if not os.path.exists(new_path):
                        with open(new_path, 'w', encoding='utf-8') as nf:
                            json.dump(data, nf, ensure_ascii=False, indent=2)
                os.rename(old_library, old_library + ".bak")
            except Exception as e:
                print(f"歌曲轉移失敗: {e}")

        self.current_song_name = "未命名歌曲"
        
        self.config = {
            'mode_idx': 0,
            'active_motors': [0, 1, 2, 3],
            'transpose': 0,
            'arp_speed_ms': 10,
            'gate_time': 100
        }

    def calculate_best_transpose(self, notes):
        if not notes: return 0
        
        # 排除馬達音符
        glock_notes = [n for n in notes if not getattr(n, 'is_motor', False)]
        if not glock_notes: return 0
        
        best_offset = 0
        max_hits = -1
        # Check from -24 to +24
        for k in range(-24, 25):
            hits = sum(1 for n in glock_notes if (n.pitch + k) in GLOCKENSPIEL_MAP)
            # Prefer smaller offsets in case of tie
            if hits > max_hits or (hits == max_hits and abs(k) < abs(best_offset)):
                max_hits = hits
                best_offset = k
        return best_offset

    def save_state(self):
        state = [n.clone() for n in self.all_notes if not getattr(n, 'is_generated', False)]
        self.undo_stack.append(state)
        if len(self.undo_stack) > 50: self.undo_stack.pop(0)

    def save_song(self, song_name):
        safe_name = "".join([c for c in song_name if c.isalnum() or c in (' ', '-', '_')]).rstrip()
        if not safe_name: safe_name = "未命名歌曲"
        file_path = os.path.join(self.library_dir, f"{safe_name}.json")
        pure_notes = [n for n in self.all_notes if not getattr(n, 'is_generated', False)]
        song_data = {
            "config": self.config,
            "sustain_multiplier": self.sustain_multiplier,
            "notes": [n.to_dict() for n in pure_notes]
        }
        with open(file_path, 'w', encoding='utf-8') as f: json.dump(song_data, f, ensure_ascii=False, indent=2)
        self.current_song_name = song_name

    def load_song(self, song_name):
        safe_name = "".join([c for c in song_name if c.isalnum() or c in (' ', '-', '_')]).rstrip()
        if not safe_name: safe_name = "未命名歌曲"
        file_path = os.path.join(self.library_dir, f"{safe_name}.json")
        if not os.path.exists(file_path): return False
        with open(file_path, 'r', encoding='utf-8') as f: song = json.load(f)
        self.config = song.get("config", self.config)
        self.sustain_multiplier = song.get("sustain_multiplier", 1.0)
        self.all_notes = [NoteData.from_dict(nd) for nd in song.get("notes", [])]
        self.current_song_name = song_name
        self.re_route_all()
        return True

    def get_song_list(self):
        if not os.path.exists(self.library_dir): return []
        songs = []
        for f in os.listdir(self.library_dir):
            if f.endswith('.json'):
                songs.append(f[:-5])
        return sorted(songs)

    def update_config(self, new_config):
        self.config.update(new_config)
        self.re_route_all()

    def save_state(self):
        state = [n.clone() for n in self.all_notes if not getattr(n, 'is_generated', False)]
        self.undo_stack.append(state)
        if len(self.undo_stack) > 50: self.undo_stack.pop(0)

    def undo(self):
        if self.undo_stack:
            self.all_notes = self.undo_stack.pop()
            self.re_route_all()

    def re_route_all(self):
        self.all_notes = [n for n in self.all_notes if not getattr(n, 'is_generated', False)]

        if not self.all_notes:
            self.hit_rate = 100.0
            return
            
        c = self.config
        active_motors = c['active_motors'] if c['active_motors'] else [0]
        total_offset = c.get('transpose', 0)

        for note in self.all_notes:
            note.is_ignored = False
            note.accel_val = 2000
            note.effective_pitch = note.pitch + total_offset

        for note in self.all_notes:
            if getattr(note, 'is_motor', False): continue
            if c.get('mode_idx', 0) == 1: 
                note.is_motor, note.track_id = True, -1
            else:
                if note.effective_pitch in GLOCKENSPIEL_MAP:
                    note.is_motor, note.track_id = False, GLOCKENSPIEL_MAP[note.effective_pitch]
                else:
                    note.is_motor = True
                    note.track_id = -1

        for note in self.all_notes:
            if getattr(note, 'is_motor', False):
                note.effective_pitch = self.motor_profiler.check_and_fold_pitch(note.effective_pitch)
                note.duration_us = max(20_000, getattr(note, 'base_duration_us', 200_000))
            else:
                note.duration_us = 200_000
                
        self.all_notes = self.physics.filter_dense_notes(self.all_notes)

        white_key_hits = sum(1 for n in self.all_notes if n.effective_pitch in GLOCKENSPIEL_MAP)
        self.hit_rate = (white_key_hits / len(self.all_notes)) * 100.0 if self.all_notes else 100.0

        # 時間軸處理
        events = []
        for note in self.all_notes:
            if getattr(note, 'is_ignored', False): continue
            if getattr(note, 'is_motor', False):
                events.append({'time': note.t_trigger_us, 'type': 'ON', 'note': note})
                events.append({'time': note.t_trigger_us + note.duration_us, 'type': 'OFF', 'note': note})
                
        events.sort(key=lambda x: (x['time'], 0 if x['type'] == 'OFF' else 1))

        motor_state = {m: None for m in active_motors}
        ranges = c.get('motor_ranges', {0: (36, 59), 1: (60, 71), 2: (72, 83), 3: (84, 108)}) 
        motor_last_note = {m: None for m in active_motors} 

        for ev in events:
            n = ev['note']
            
            if ev['type'] == 'OFF':
                for m in active_motors:
                    if motor_state[m] == n:  
                        motor_state[m] = None 
            
            elif ev['type'] == 'ON':
                idle_motors = [m for m in active_motors if motor_state[m] is None]
                if not idle_motors:
                    n.is_ignored = True 
                    continue
                
                perfect_matches = [m for m in idle_motors if ranges.get(m, (0, 127))[0] <= n.effective_pitch <= ranges.get(m, (0, 127))[1]]
                
                if perfect_matches: chosen_m = perfect_matches[0]
                else:
                    def dist(m_idx):
                        rmin, rmax = ranges.get(m_idx, (0, 127))
                        if n.effective_pitch < rmin: return rmin - n.effective_pitch
                        if n.effective_pitch > rmax: return n.effective_pitch - rmax
                        return 0
                    chosen_m = min(idle_motors, key=dist) 
                
                n.motor_id = chosen_m
                motor_state[chosen_m] = n
                
                prev_note = motor_last_note[chosen_m]
                if prev_note and not getattr(prev_note, 'is_ignored', False):
                    overlap = (prev_note.t_trigger_us + prev_note.duration_us) - n.t_trigger_us
                    if overlap >= 0:
                        prev_note.duration_us = n.t_trigger_us - prev_note.t_trigger_us
                        if prev_note.duration_us <= 0: prev_note.is_ignored = True 
                        
                motor_last_note[chosen_m] = n



        # Force sort by timeline
        self.all_notes.sort(key=lambda x: getattr(x, 't_trigger_us', 0))

    def import_midi_advanced(self, file_path, mode):
        if not HAS_MIDO: return False, "缺少 mido 套件", 0
        if hasattr(self, 'save_state'): self.save_state()
            
        try:
            self.current_song_name = file_path.split('/')[-1].replace('.mid', '').replace('.midi', '')
            mid = mido.MidiFile(file_path)
            parsed_notes = []
            current_time_us = 0
            active_notes = {}
            note_id = 0
            
            channel_programs = {} 
            delay_us = self.physics.get_total_delay_us()
            current_cc5_val = 0
            
            for msg in mid:
                current_time_us += int(msg.time * 1_000_000)
                
                if msg.type == 'program_change': channel_programs[msg.channel] = msg.program
                elif msg.type == 'control_change' and msg.control == 5: current_cc5_val = msg.value
                elif msg.type == 'note_on' and msg.velocity > 0:
                    key = (msg.note, msg.channel)
                    active_notes[key] = {'start_time': current_time_us, 'cc5': current_cc5_val}
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    key = (msg.note, msg.channel)
                    if key in active_notes:
                        start_time = active_notes[key]['start_time']
                        cc5_val = active_notes[key]['cc5']
                        del active_notes[key]
                        
                        duration = current_time_us - start_time
                        prog = channel_programs.get(msg.channel, 0)
                        
                        # Reserve t=0 for testing to avoid sequence desynchronization
                        t_trigger = max(1, start_time - delay_us) 
                        n = NoteData(f"M_{note_id}", msg.note, start_time, t_trigger)
                        n.base_duration_us = duration
                        n.duration_us = duration
                        n.channel = msg.channel
                        n.program = prog
                        n.velocity = msg.velocity
                        
                        if cc5_val > 0:
                            n.accel_val = max(100, 2000 - int((cc5_val / 127.0) * 1900))
                            n.midi_portamento = True
                        else:
                            n.accel_val = 2000
                            n.midi_portamento = False
                            
                        parsed_notes.append(n)
                        note_id += 1
            
            final_notes = []
            self.detected_is_minor = False
            
            if mode == "glock_only":
                existing_motor = [n for n in getattr(self, 'all_notes', []) if getattr(n, 'is_motor', False)]
                for n in parsed_notes:
                    n.is_motor = False
                    n.track_id = GLOCKENSPIEL_MAP[n.pitch] if n.pitch in GLOCKENSPIEL_MAP else n.pitch % 15
                final_notes = existing_motor + parsed_notes
                
            elif mode == "motor_only":
                existing_glock = [n for n in getattr(self, 'all_notes', []) if not getattr(n, 'is_motor', False)]
                for n in parsed_notes:
                    n.is_motor = True
                    n.motor_id = n.pitch % 4
                final_notes = existing_glock + parsed_notes
                
            elif mode == "unified_ai":
                valid_pitches = list(GLOCKENSPIEL_MAP.keys())
                ai_notes, key_name = AdvancedMidiProcessor.process_midi_notes(file_path, parsed_notes, valid_pitches)
                for n in ai_notes:
                    if getattr(n, 'is_motor', False): n.motor_id = n.pitch % 4
                    else: n.track_id = GLOCKENSPIEL_MAP[n.pitch] if n.pitch in GLOCKENSPIEL_MAP else n.pitch % 15
                final_notes = ai_notes
                self.detected_is_minor = "minor" in str(key_name).lower()
                
            elif mode == "unified_inst":
                for n in parsed_notes:
                    is_bass_or_synth = (32 <= n.program <= 39) or (80 <= n.program <= 95)
                    if n.channel == 9 or is_bass_or_synth:
                        n.is_motor = True
                        n.motor_id = n.pitch % 4
                    else:
                        n.is_motor = False
                        n.track_id = GLOCKENSPIEL_MAP[n.pitch] if n.pitch in GLOCKENSPIEL_MAP else n.pitch % 15
                final_notes = parsed_notes

            elif mode == "ai_midibert":
                # 調用 MidiBERT
                # 保留神經網路還原的原始旋律輪廓
                final_notes = MidiBERTMicroserviceClient.request_piano_reduction(parsed_notes)
                
            self.all_notes = final_notes
            best_offset = self.calculate_best_transpose(self.all_notes)
            self.re_route_all()
                
            return True, f"成功載入 {len(parsed_notes)} 個音符", best_offset
            
        except ConnectionError as ce:
            return False, str(ce), 0
        except Exception as e:
            return False, f"進階匯入 MIDI 失敗: {str(e)}", 0

    def import_arduino_h(self, file_name):
        pass
        
    def export_arduino(self, file_name):
        pass

    def export_web_json(self, path):
        try:
            import json
            events = []
            
            def calc_crc16(data):
                crc = 0x0000
                for byte in data:
                    crc ^= (byte << 8)
                    for _ in range(8):
                        if crc & 0x8000: crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                        else: crc = (crc << 1) & 0xFFFF
                return crc

            seq_counter = 0 # Sequential tracking counter

            def build_packet(cmd_type, motor_id, ts, payload_bytes):
                nonlocal seq_counter
                packet = bytearray(16)
                packet[0], packet[1] = 0xFE, 0xFE
                packet[2] = cmd_type
                packet[3] = motor_id
                
                # Write dynamic sequence number
                packet[4] = seq_counter & 0xFF
                packet[5] = (seq_counter >> 8) & 0xFF
                seq_counter = (seq_counter + 1) % 65536 
                
                packet[6] = ts & 0xFF
                packet[7] = (ts >> 8) & 0xFF
                packet[8] = (ts >> 16) & 0xFF
                packet[9] = (ts >> 24) & 0xFF
                
                for i in range(4):
                    packet[10 + i] = payload_bytes[i]
                    
                crc = calc_crc16(packet[:14])
                packet[14] = crc & 0xFF
                packet[15] = (crc >> 8) & 0xFF
                return list(packet)

            events.append({"t_us": 0, "payload": build_packet(0x03, 0, 0, [0,0,0,0])})
            all_notes = getattr(self, 'all_notes', [])

            # Combine simultaneous Glockenspiel notes into bitmask
            glock_groups = {}
            for note in all_notes:
                if getattr(note, 'is_ignored', False) or getattr(note, 'is_generated', False): continue
                if not getattr(note, 'is_motor', False):
                    t_us = getattr(note, 't_trigger_us', 1)
                    if t_us not in glock_groups: glock_groups[t_us] = 0
                    glock_groups[t_us] |= (1 << getattr(note, 'track_id', 0))

            for t_us, mask in glock_groups.items():
                payload = [mask & 0xFF, (mask >> 8) & 0xFF, (mask >> 16) & 0xFF, (mask >> 24) & 0xFF]
                events.append({"t_us": t_us, "payload": build_packet(0x01, 0, t_us, payload)})

            for note in all_notes:
                if getattr(note, 'is_ignored', False) or getattr(note, 'is_generated', False): continue
                if getattr(note, 'is_motor', False):
                    t_trigger = getattr(note, 't_trigger_us', 1)
                    pitch = getattr(note, 'effective_pitch', getattr(note, 'pitch', 60))
                    rpm = int((440.0 * (2.0 ** ((pitch - 69) / 12.0))) * 0.3)
                    accel = getattr(note, 'accel_val', 2000)
                    motor_id = getattr(note, 'motor_id', 0)
                    
                    payload = [rpm & 0xFF, (rpm >> 8) & 0xFF, accel & 0xFF, (accel >> 8) & 0xFF]
                    events.append({"t_us": t_trigger, "payload": build_packet(0x02, motor_id, t_trigger, payload)})
                    
                    stop_t = t_trigger + getattr(note, 'duration_us', 200_000)
                    stop_payload = [0, 0, accel & 0xFF, (accel >> 8) & 0xFF]
                    events.append({"t_us": stop_t, "payload": build_packet(0x02, motor_id, stop_t, stop_payload)})

            events.sort(key=lambda x: x["t_us"])
            
            export_data = {
                "version": "1.0",
                "song_name": getattr(self, 'current_song_name', 'Untitled'),
                "total_commands": len(events),
                "commands": events
            }
            
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False)
                
            return True, ""
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, str(e)