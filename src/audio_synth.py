# 請在這裡貼上 audio_synth.py 的程式碼
import os
import math
import struct
import wave
import tempfile
from typing import Dict
from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QSoundEffect

class GlockenspielSynthesizer:
    """純軟體動態波形合成器，產生帶有物理敲擊感的鐵琴聲音"""
    def __init__(self):
        self.sounds: Dict[int, QSoundEffect] = {}
        self.temp_dir = os.path.join(tempfile.gettempdir(), "automusic_sounds")
        os.makedirs(self.temp_dir, exist_ok=True)
        
    def _generate_wav(self, pitch: int, filepath: str):
        """合成模擬鐵琴物理特性的 WAV 檔案"""
        freq = 440.0 * (2.0 ** ((pitch - 69) / 12.0))
        sample_rate = 44100
        duration = 1.5
        n_samples = int(sample_rate * duration)
        
        with wave.open(filepath, 'w') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            
            for i in range(n_samples):
                t = float(i) / sample_rate
                # 使用指數衰減與泛音模擬敲擊感
                envelope = math.exp(-4.0 * t) 
                wave_val = (math.sin(2.0 * math.pi * freq * t) + 
                            0.5 * math.sin(2.0 * math.pi * freq * 2 * t) + 
                            0.2 * math.sin(2.0 * math.pi * freq * 3.5 * t)) / 1.7
                
                v = int(wave_val * 32767 * 0.4 * envelope)
                w.writeframesraw(struct.pack('<h', v))

    def play_note(self, pitch: int):
        """播放指定音高的音效，若無緩存則現場生成"""
        if pitch not in self.sounds:
            filepath = os.path.join(self.temp_dir, f"note_{pitch}.wav")
            if not os.path.exists(filepath):
                self._generate_wav(pitch, filepath)
            
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(filepath))
            effect.setVolume(0.8)
            self.sounds[pitch] = effect
            
        self.sounds[pitch].play()


class MotorSynthesizer:
    """純軟體動態波形合成器，產生類似步進馬達的方波 (Square Wave) 蜂鳴聲"""
    def __init__(self):
        self.sounds: Dict[int, QSoundEffect] = {}
        self.temp_dir = os.path.join(tempfile.gettempdir(), "automusic_motor_sounds")
        os.makedirs(self.temp_dir, exist_ok=True)
        
    def _generate_wav(self, pitch: int, filepath: str):
        """合成模擬步進馬達電磁脈衝的方波 WAV 檔案"""
        freq = 440.0 * (2.0 ** ((pitch - 69) / 12.0))
        sample_rate = 44100
        duration = 0.3 # 馬達聲音通常比較短促
        n_samples = int(sample_rate * duration)
        
        with wave.open(filepath, 'w') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            
            for i in range(n_samples):
                t = float(i) / sample_rate
                
                # 使用方波 (Square Wave) 來模擬馬達步進時的強烈電流切換聲
                wave_val = 1.0 if math.sin(2.0 * math.pi * freq * t) > 0 else -1.0
                
                # 加入極短的起音(Attack)與釋音(Release)包絡線，避免爆音(Clicking)
                envelope = 1.0
                if i < 500: 
                    envelope = i / 500.0
                elif i > n_samples - 500: 
                    envelope = (n_samples - i) / 500.0
                
                # 方波聽覺上非常大聲且刺耳，所以將基礎音量係數調低 (0.15)
                v = int(wave_val * 32767 * 0.15 * envelope)
                w.writeframesraw(struct.pack('<h', v))

    def play_note(self, pitch: int):
        """播放馬達模擬音效"""
        if pitch not in self.sounds:
            filepath = os.path.join(self.temp_dir, f"motor_note_{pitch}.wav")
            if not os.path.exists(filepath):
                self._generate_wav(pitch, filepath)
            
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(filepath))
            effect.setVolume(0.5) # 馬達音量可在此微調
            self.sounds[pitch] = effect
            
        self.sounds[pitch].play()