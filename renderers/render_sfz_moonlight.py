import os
import sys
import re
import math
import mido
import numpy as np
import soundfile as sf

def parse_sfz(sfz_path):
    regions = []
    default_path = ""
    sfz_dir = os.path.dirname(os.path.abspath(sfz_path))
    with open(sfz_path, "r") as f:
        content = f.read()
    content_clean = re.sub(r"//.*", "", content)
    blocks = re.split(r"<", content_clean)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        match = re.match(r"^(\w+)\s*>\s*(.*)$", block, re.DOTALL)
        if not match:
            continue
        header_name = match.group(1).lower()
        body = match.group(2)
        opcodes = {}
        pattern = r"(\w+)\s*=\s*([^\s=]+|\"[^\"]*\")"
        for key, val in re.findall(pattern, body):
            val = val.strip('"')
            opcodes[key.lower()] = val
        if header_name == "control":
            if "default_path" in opcodes:
                default_path = os.path.join(sfz_dir, opcodes["default_path"])
        elif header_name == "region":
            regions.append(opcodes)
    return default_path, regions

def create_moonlight_midi_in_memory():
    """
    Generates Beethoven's Moonlight Sonata (1st mvt) MIDI events in memory.
    Tempo: 54 BPM. 4/4 Time.
    1 beat = 60 / 54 = 1.111 seconds.
    1 triplet note = 1/3 beat = 0.370 seconds.
    1 bar = 4 beats = 12 triplets = 4.444 seconds.
    """
    abs_events = []
    beat_dur = 60.0 / 54.0     # ~1.111s
    triplet_dur = beat_dur / 3.0 # ~0.370s
    bar_dur = beat_dur * 4.0   # ~4.444s
    
    # Helper to add a bass octave (held for whole bar)
    def add_bass_octave(bar_idx, note_num):
        t_on = bar_idx * bar_dur
        t_off = (bar_idx + 1) * bar_dur - 0.05
        # Low octave notes
        abs_events.append((t_on, 'note_on', {'note': note_num, 'velocity': 70}))
        abs_events.append((t_off, 'note_off', {'note': note_num, 'velocity': 0}))
        abs_events.append((t_on, 'note_on', {'note': note_num + 12, 'velocity': 65}))
        abs_events.append((t_off, 'note_off', {'note': note_num + 12, 'velocity': 0}))

    # Helper to add a triplet group (3 notes)
    # n1, n2, n3: notes. Each note is held for 1.2s to create overlapping pedal wash.
    def add_triplet(abs_start_time, n1, n2, n3):
        notes = [n1, n2, n3]
        for idx, note_num in enumerate(notes):
            t_on = abs_start_time + idx * triplet_dur
            t_off = t_on + 1.2 # Overlapping decay (pedal)
            abs_events.append((t_on, 'note_on', {'note': note_num, 'velocity': 52}))
            abs_events.append((t_off, 'note_off', {'note': note_num, 'velocity': 0}))

    # Helper to add a melody note
    def add_melody(abs_on_time, note_num, duration_in_beats):
        t_on = abs_on_time
        t_off = abs_on_time + duration_in_beats * beat_dur - 0.05
        abs_events.append((t_on, 'note_on', {'note': note_num, 'velocity': 94}))
        abs_events.append((t_off, 'note_off', {'note': note_num, 'velocity': 0}))

    # 1. Bass accompaniment
    add_bass_octave(0, 37) # C#2 (37) & C#3 (49)
    add_bass_octave(1, 35) # B1 (35) & B2 (47)
    # Bar 3 has two bass chords: A2 (33) for 2 beats, F#2 (30) for 2 beats
    abs_events.append((2.0 * bar_dur, 'note_on', {'note': 33, 'velocity': 70}))
    abs_events.append((2.0 * bar_dur, 'note_on', {'note': 45, 'velocity': 65}))
    abs_events.append((2.0 * bar_dur + 2 * beat_dur - 0.05, 'note_off', {'note': 33, 'velocity': 0}))
    abs_events.append((2.0 * bar_dur + 2 * beat_dur - 0.05, 'note_off', {'note': 45, 'velocity': 0}))
    
    abs_events.append((2.0 * bar_dur + 2 * beat_dur, 'note_on', {'note': 30, 'velocity': 70}))
    abs_events.append((2.0 * bar_dur + 2 * beat_dur, 'note_on', {'note': 42, 'velocity': 65}))
    abs_events.append((3.0 * bar_dur - 0.05, 'note_off', {'note': 30, 'velocity': 0}))
    abs_events.append((3.0 * bar_dur - 0.05, 'note_off', {'note': 42, 'velocity': 0}))
    
    add_bass_octave(3, 32) # G#1 (32) & G#2 (44)
    add_bass_octave(4, 37) # C#2 (37) & C#3 (49)

    # 2. Right-hand triplets (4 groups per bar)
    # Bar 0
    for g in range(4):
        add_triplet(0.0 * bar_dur + g * beat_dur, 56, 61, 64) # G#3, C#4, E4
    # Bar 1
    add_triplet(1.0 * bar_dur + 0 * beat_dur, 56, 61, 64)
    add_triplet(1.0 * bar_dur + 1 * beat_dur, 56, 61, 64)
    add_triplet(1.0 * bar_dur + 2 * beat_dur, 57, 61, 64) # A3, C#4, E4
    add_triplet(1.0 * bar_dur + 3 * beat_dur, 57, 61, 64)
    # Bar 2
    add_triplet(2.0 * bar_dur + 0 * beat_dur, 57, 62, 66) # A3, D4, F#4
    add_triplet(2.0 * bar_dur + 1 * beat_dur, 57, 62, 66)
    add_triplet(2.0 * bar_dur + 2 * beat_dur, 56, 61, 64) # G#3, C#4, E4
    add_triplet(2.0 * bar_dur + 3 * beat_dur, 56, 61, 63) # G#3, C#4, D#4
    # Bar 3
    add_triplet(3.0 * bar_dur + 0 * beat_dur, 56, 60, 63) # G#3, C4, D#4 (G#7)
    add_triplet(3.0 * bar_dur + 1 * beat_dur, 54, 60, 63) # F#3, C4, D#4
    add_triplet(3.0 * bar_dur + 2 * beat_dur, 56, 61, 63) # G#3, C#4, D#4
    add_triplet(3.0 * bar_dur + 3 * beat_dur, 56, 61, 64) # G#3, C#4, E4
    # Bar 4
    for g in range(4):
        add_triplet(4.0 * bar_dur + g * beat_dur, 56, 61, 64) # G#3, C#4, E4

    # 3. Melody line
    # Bar 1 (enters on the last beat of Bar 1)
    add_melody(1.0 * bar_dur + 3 * beat_dur, 68, 1.0) # G#4 (68)
    
    # Bar 2
    add_melody(2.0 * bar_dur, 68, 1.5)
    add_melody(2.0 * bar_dur + 1.5 * beat_dur, 68, 0.5)
    add_melody(2.0 * bar_dur + 2.0 * beat_dur, 68, 1.5)
    add_melody(2.0 * bar_dur + 3.5 * beat_dur, 68, 0.5)
    
    # Bar 3
    add_melody(3.0 * bar_dur, 68, 1.5)
    add_melody(3.0 * bar_dur + 1.5 * beat_dur, 69, 0.5) # A4 (69)
    add_melody(3.0 * bar_dur + 2.0 * beat_dur, 66, 1.5) # F#4 (66)
    add_melody(3.0 * bar_dur + 3.5 * beat_dur, 68, 0.5) # G#4
    
    # Bar 4 (resolves)
    add_melody(4.0 * bar_dur, 68, 3.0)

    # Sort events
    abs_events.sort(key=lambda x: (x[0], 0 if x[1] == 'note_off' else 1))
    
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.Message('program_change', program=0, time=0))
    
    ticks_per_second = 960
    prev_tick = 0
    for time_sec, msg_type, args in abs_events:
        abs_tick = int(round(time_sec * ticks_per_second))
        delta_tick = max(0, abs_tick - prev_tick)
        prev_tick = abs_tick
        msg = mido.Message(msg_type, time=delta_tick, **args)
        track.append(msg)
        
    return mid

def parse_midi_object(mid):
    notes = []
    active_notes = {}
    for track in mid.tracks:
        current_time_sec = 0.0
        tempo = 500000
        for msg in track:
            delta_sec = mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
            current_time_sec += delta_sec
            if msg.type == 'set_tempo':
                tempo = msg.tempo
            elif msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = (current_time_sec, msg.velocity)
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active_notes:
                    start_time, velocity = active_notes.pop(msg.note)
                    duration = current_time_sec - start_time
                    notes.append({
                        "note": msg.note,
                        "velocity": velocity,
                        "start_time": start_time,
                        "duration": duration
                    })
    return notes

def render_note_vectorized(sample_data, ratio, velocity, duration_samples, release_samples=44100):
    num_src_samples, num_channels = sample_data.shape
    total_samples = duration_samples + release_samples
    t = np.arange(total_samples, dtype=np.float32)
    src_ptrs = t * ratio
    idx_low = np.floor(src_ptrs).astype(np.int32)
    idx_high = idx_low + 1
    valid_mask = idx_low < num_src_samples
    note_buffer = np.zeros((total_samples, num_channels), dtype=np.float32)
    if np.any(valid_mask):
        frac = src_ptrs[valid_mask] - idx_low[valid_mask]
        frac = frac[:, np.newaxis]
        low_idx = idx_low[valid_mask]
        high_idx = np.clip(idx_high[valid_mask], 0, num_src_samples - 1)
        val_low = sample_data[low_idx]
        val_high = sample_data[high_idx]
        val = (1.0 - frac) * val_low + frac * val_high
        if release_samples > 0:
            release_ramp = np.ones(total_samples, dtype=np.float32)
            off_indices = np.arange(release_samples, dtype=np.float32)
            release_ramp[duration_samples:] = np.maximum(0.0, 1.0 - off_indices / release_samples)
            val = val * release_ramp[valid_mask][:, np.newaxis]
        val = val * (velocity / 127.0)
        note_buffer[valid_mask] = val
    return note_buffer

def find_matching_region(regions, note, velocity):
    for r in regions:
        lokey = int(r.get("lokey", 0))
        hikey = int(r.get("hikey", 127))
        lovel = int(r.get("lovel", 1))
        hivel = int(r.get("hivel", 127))
        if lokey <= note <= hikey and lovel <= velocity <= hivel:
            return r
    return None

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    sfz_path = os.path.join(project_root, "Surge_DX_Piano.sfz")
    print(f"Parsing SFZ file: {sfz_path}")
    default_path, regions = parse_sfz(sfz_path)
    
    mid = create_moonlight_midi_in_memory()
    midi_notes = parse_midi_object(mid)
    print(f"Parsed {len(midi_notes)} notes from Moonlight Sonata MIDI.")
    
    sr = 96000 # HD quality render
    release_time_sec = 2.0 # Extra long decay tail for the sonata
    release_samples = int(release_time_sec * sr)
    
    max_time = 0.0
    for n in midi_notes:
        max_time = max(max_time, n["start_time"] + n["duration"])
    total_duration_sec = max_time + release_time_sec
    total_samples = int(math.ceil(total_duration_sec * sr))
    print(f"Total audio duration: {total_duration_sec:.2f}s ({total_samples} samples)")
    
    output_audio = np.zeros((total_samples, 2), dtype=np.float32)
    sample_cache = {}
    
    print("Synthesizing notes from SFZ samples...")
    for n in midi_notes:
        note = n["note"]
        velocity = n["velocity"]
        start_time = n["start_time"]
        duration = n["duration"]
        
        region = find_matching_region(regions, note, velocity)
        if not region:
            continue
            
        sample_name = region["sample"]
        sample_file_path = os.path.join(default_path, sample_name)
        
        if sample_file_path not in sample_cache:
            if not os.path.exists(sample_file_path):
                print(f"Error: Sample file not found: {sample_file_path}")
                continue
            data, sample_sr = sf.read(sample_file_path)
            if data.ndim == 1:
                data = np.column_stack((data, data))
            sample_cache[sample_file_path] = (data, sample_sr)
            
        sample_data, sample_sr = sample_cache[sample_file_path]
        
        keycenter = int(region.get("pitch_keycenter", 60))
        ratio = 2.0 ** ((note - keycenter) / 12.0)
        if sample_sr != sr:
            ratio *= (sample_sr / sr)
            
        duration_samples = int(duration * sr)
        note_audio = render_note_vectorized(
            sample_data, 
            ratio, 
            velocity, 
            duration_samples, 
            release_samples
        )
        
        start_sample = int(start_time * sr)
        end_sample = min(total_samples, start_sample + note_audio.shape[0])
        mix_len = end_sample - start_sample
        if mix_len > 0:
            output_audio[start_sample:end_sample] += note_audio[:mix_len]
            
    max_val = np.max(np.abs(output_audio))
    print(f"Max mixed amplitude: {max_val:.4f}")
    if max_val > 0.95:
        output_audio = output_audio * (0.90 / max_val)
        
    print("Applying reverb and delay effects...")
    import pedalboard
    from pedalboard import Pedalboard, Reverb, Delay
    
    board = Pedalboard([
        Reverb(room_size=0.78, wet_level=0.35, dry_level=0.65),
        Delay(delay_seconds=0.555, feedback=0.25, mix=0.15) # Triplets matching delay
    ])
    
    processed = board(output_audio.T, sr)
    
    output_path = os.path.join(project_root, "Surge_DX_Piano_SFZ_Moonlight.wav")
    sf.write(output_path, processed.T, sr, subtype='PCM_24')
    print(f"Moonlight Sonata successfully rendered and saved to {output_path}!")

if __name__ == "__main__":
    main()
