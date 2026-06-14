import mido
from model import CastellaModel

model = CastellaModel()
mid = mido.MidiFile()
track = mido.MidiTrack()
mid.tracks.append(track)
track.append(mido.Message('note_on', note=60, velocity=64, time=0))
track.append(mido.Message('note_on', note=64, velocity=64, time=0))
track.append(mido.Message('note_on', note=67, velocity=64, time=0))
track.append(mido.Message('note_off', note=60, velocity=64, time=480))
track.append(mido.Message('note_off', note=64, velocity=64, time=0))
track.append(mido.Message('note_off', note=67, velocity=64, time=0))
mid.save('test.mid')

success, err = model.import_midi_advanced('test.mid', 'unified_ai')
with open('output.txt', 'w', encoding='utf-8') as f:
    f.write(f'Success: {success}\n')
    if success:
        f.write(f'Glock notes: {len([n for n in model.all_notes if not getattr(n, "is_motor", False)])}\n')
        f.write(f'Motor notes: {len([n for n in model.all_notes if getattr(n, "is_motor", False)])}\n')
    else:
        f.write(f'Error: {err}\n')
