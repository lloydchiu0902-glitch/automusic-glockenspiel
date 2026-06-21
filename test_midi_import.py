import traceback
import sys
import mido
import os
from model import AutoMusicModel

old_import = AutoMusicModel.import_midi_advanced
def new_import(self, file_path, mode="glock_only"):
    try:
        return old_import(self, file_path, mode)
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
        return False, f"進階匯入 MIDI 失敗: {str(e)}", 0
AutoMusicModel.import_midi_advanced = new_import

# Create a dummy midi file
mid = mido.MidiFile()
track = mido.MidiTrack()
mid.tracks.append(track)
track.append(mido.Message('note_on', note=60, velocity=64, time=0))
track.append(mido.Message('note_off', note=60, velocity=64, time=480))
mid.save('test_dummy.mid')

m = AutoMusicModel()
for mode in ["glock_only", "motor_only", "unified_ai", "unified_inst", "ai_midibert"]:
    print(f"\n--- Testing mode {mode} ---")
    try:
        m.import_midi_advanced('test_dummy.mid', mode)
        print(f"{mode} finished successfully without top-level crash.")
    except Exception as e:
        print(f"{mode} crashed: {e}")
