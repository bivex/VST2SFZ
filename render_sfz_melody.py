import os
import sys
import re
import math
import mido
import numpy as np
import soundfile as sf

def parse_sfz(sfz_path):
    """
    Parses an SFZ file and returns the default_path and a list of regions.
    """
    regions = []
    default_path = ""
    
    if not os.path.exists(sfz_path):
        raise FileNotFoundError(f"SFZ file not found: {sfz_path}")
        
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

def create_bach_midi_in_memory():
    """
    Generates the exact same beautiful, overlapping MIDI sequence of Bach's Prelude.
    """
    abs_events = []
    
    def add_bar(start_time, n1, n2, n3, n4, n5):
        for half in [0, 2.0]:
            t_offset = start_time + half
            notes = [
                (0.0, n1, 2.0),
                (0.25, n2, 1.75),
                (0.5, n3, 1.5),
                (0.75, n4, 1.25),
                (1.0, n5, 1.0),
                (1.25, n3, 0.75),
                (1.5, n4, 0.5),
                (1.75, n5, 0.25),
            ]
            for t_rel, note_num, dur in notes:
                on_t = t_offset + t_rel
                off_t = t_offset + t_rel + dur
                abs_events.append((on_t, 'note_on', {'note': note_num, 'velocity': 90}))
                abs_events.append((off_t, 'note_off', {'note': note_num, 'velocity': 0}))

    # Bar 1: C3, E3, G3, C4, E4
    add_bar(0.0, 48, 52, 55, 60, 64)
    # Bar 2: D3, F3, A3, D4, F4
    add_bar(4.0, 50, 53, 57, 62, 65)
    # Bar 3: B2, D3, G3, D4, F4
    add_bar(8.0, 47, 50, 55, 62, 65)
    # Bar 4: C3, E3, G3, C4, E4
    add_bar(12.0, 48, 52, 55, 60, 64)
    
    # Final chord
    final_time = 16.0
    for note_num in [36, 48, 52, 55, 60, 64]:
        abs_events.append((final_time, 'note_on', {'note': note_num, 'velocity': 85}))
        abs_events.append((final_time + 4.0, 'note_off', {'note': note_num, 'velocity': 0}))

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
        tempo = 500000 # 120 bpm
        
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
    """
    Vectorized linear-interpolation resampler. Plays the sample naturally (no looping)
    to keep the organic acoustic decay of the piano, and fades out smoothly at note-off.
    """
    num_src_samples, num_channels = sample_data.shape
    total_samples = duration_samples + release_samples
    
    # 1. Output time pointers
    t = np.arange(total_samples, dtype=np.float32)
    src_ptrs = t * ratio
    
    # 2. Linear interpolation
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
        
        # Apply amplitude release envelope (fade out starting at note-off)
        if release_samples > 0:
            release_ramp = np.ones(total_samples, dtype=np.float32)
            off_indices = np.arange(release_samples, dtype=np.float32)
            # Fade out from 1.0 to 0.0 starting at duration_samples
            release_ramp[duration_samples:] = np.maximum(0.0, 1.0 - off_indices / release_samples)
            val = val * release_ramp[valid_mask][:, np.newaxis]
            
        # Scale by velocity
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
    print(f"Loaded {len(regions)} regions. default_path: {default_path}")
    
    # Generate the MIDI in memory
    mid = create_bach_midi_in_memory()
    midi_notes = parse_midi_object(mid)
    print(f"Parsed {len(midi_notes)} notes from Bach MIDI performance.")
    
    sr = 44100
    # Use a musical release time (1.0 second decay on release)
    release_time_sec = 1.0
    release_samples = int(release_time_sec * sr)
    
    # Calculate output audio length
    max_time = 0.0
    for n in midi_notes:
        max_time = max(max_time, n["start_time"] + n["duration"])
    
    total_duration_sec = max_time + release_time_sec
    total_samples = int(math.ceil(total_duration_sec * sr))
    print(f"Total audio duration: {total_duration_sec:.2f}s ({total_samples} samples)")
    
    # Initialize stereo output buffer
    output_audio = np.zeros((total_samples, 2), dtype=np.float32)
    sample_cache = {}
    
    # Render loop
    print("Synthesizing notes from SFZ samples...")
    for idx, n in enumerate(midi_notes):
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
        
        # Render the note without artificial looping (natural piano decay)
        note_audio = render_note_vectorized(
            sample_data, 
            ratio, 
            velocity, 
            duration_samples, 
            release_samples
        )
        
        # Mix note into main buffer
        start_sample = int(start_time * sr)
        end_sample = min(total_samples, start_sample + note_audio.shape[0])
        mix_len = end_sample - start_sample
        if mix_len > 0:
            output_audio[start_sample:end_sample] += note_audio[:mix_len]
            
    # Normalize
    max_val = np.max(np.abs(output_audio))
    print(f"Max mixed amplitude: {max_val:.4f}")
    if max_val > 0.95:
        output_audio = output_audio * (0.90 / max_val)
        
    # Apply reverb and delay post-processing
    print("Applying reverb and delay effects...")
    import pedalboard
    from pedalboard import Pedalboard, Reverb, Delay
    
    board = Pedalboard([
        Reverb(room_size=0.6, wet_level=0.25, dry_level=0.75),
        Delay(delay_seconds=0.375, feedback=0.2, mix=0.1)
    ])
    
    processed = board(output_audio.T, sr)
    
    output_path = "Surge_DX_Piano_SFZ_Melody.wav"
    sf.write(output_path, processed.T, sr)
    print(f"Melody successfully rendered using SFZ samples and saved to {output_path}!")

if __name__ == "__main__":
    main()
