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
                default_path = opcodes["default_path"]
        elif header_name == "region":
            regions.append(opcodes)
    return default_path, regions

def create_gymnopedie_midi_in_memory():
    """
    Generates Erik Satie's Gymnopédie No. 1 MIDI events in memory.
    Tempo: 75 BPM. 3/4 Time signature.
    1 beat = 0.8 seconds.
    1 bar = 3 beats = 2.4 seconds.
    """
    abs_events = []
    beat_dur = 0.8
    bar_dur = 2.4
    
    # Helper to add bass and accompaniment chord
    def add_accompaniment(bar_index, bass_note, chord_notes):
        t_bar = bar_index * bar_dur
        # Bass note on beat 1 (holds for whole bar)
        abs_events.append((t_bar, 'note_on', {'note': bass_note, 'velocity': 80}))
        abs_events.append((t_bar + bar_dur - 0.05, 'note_off', {'note': bass_note, 'velocity': 0}))
        
        # Chord on beat 2 (holds for 2 beats)
        t_chord = t_bar + beat_dur
        for note_num in chord_notes:
            abs_events.append((t_chord, 'note_on', {'note': note_num, 'velocity': 65}))
            abs_events.append((t_chord + 2 * beat_dur - 0.05, 'note_off', {'note': note_num, 'velocity': 0}))
            
    # Helper to add melody note
    def add_melody(time_in_beats, note_num, duration_in_beats, velocity=85):
        t_on = time_in_beats * beat_dur
        t_off = (time_in_beats + duration_in_beats) * beat_dur - 0.05
        abs_events.append((t_on, 'note_on', {'note': note_num, 'velocity': velocity}))
        abs_events.append((t_off, 'note_off', {'note': note_num, 'velocity': 0}))

    # Accompaniment (Bars 0 to 8)
    # Alternating G2 (43) and D2 (38) bass with B3-D4-F#4 (59-62-66) chords
    chord_g = [59, 62, 66] # B3, D4, F#4
    for bar in range(8):
        bass = 43 if bar % 2 == 0 else 38
        add_accompaniment(bar, bass, chord_g)
        
    # Melody
    # Bar 3: F#5 (78) held for 6 beats (2 bars)
    add_melody(9, 78, 6)
    # Bar 5: E5 (76) (1 beat), D5 (74) (1 beat), B4 (71) (1 beat)
    add_melody(15, 76, 1)
    add_melody(16, 74, 1)
    add_melody(17, 71, 1)
    # Bar 6: C#5 (73) (1 beat), D5 (74) (1 beat), B4 (71) (6 beats)
    add_melody(18, 73, 1)
    add_melody(19, 74, 1)
    add_melody(20, 71, 6)
    
    # Bar 8: Final resolving chord
    # G1 (31) bass, B3-D4-F#4-A4 (59-62-66-69) chord
    add_accompaniment(8, 31, [59, 62, 66, 69])
    
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
    sfz_path = "Surge_DX_Piano.sfz"
    print(f"Parsing SFZ file: {sfz_path}")
    default_path, regions = parse_sfz(sfz_path)
    
    mid = create_gymnopedie_midi_in_memory()
    midi_notes = parse_midi_object(mid)
    print(f"Parsed {len(midi_notes)} notes from Gymnopédie MIDI performance.")
    
    sr = 44100
    release_time_sec = 1.5 # Slow, beautiful release decay
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
        Reverb(room_size=0.7, wet_level=0.3, dry_level=0.7),
        Delay(delay_seconds=0.4, feedback=0.25, mix=0.12)
    ])
    
    processed = board(output_audio.T, sr)
    
    output_path = "Surge_DX_Piano_SFZ_Gymnopedie.wav"
    sf.write(output_path, processed.T, sr)
    print(f"Gymnopédie successfully rendered and saved to {output_path}!")

if __name__ == "__main__":
    main()
