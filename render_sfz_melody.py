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

def parse_midi_file(mid_path):
    """
    Parses a MIDI file and returns a list of notes with absolute timing:
    {note, velocity, start_time, duration}
    """
    mid = mido.MidiFile(mid_path)
    notes = []
    active_notes = {}
    
    for track in mid.tracks:
        current_time_sec = 0.0
        tempo = 500000 # Default 120 bpm
        
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

def render_note_vectorized(sample_data, ratio, velocity, duration_samples, loop_start=None, loop_end=None, release_samples=44100):
    """
    Vectorized linear-interpolation resampler with continuous looping and release envelope.
    """
    num_src_samples, num_channels = sample_data.shape
    total_samples = duration_samples + release_samples
    
    t = np.arange(total_samples, dtype=np.float32)
    src_ptrs = t * ratio
    
    if loop_start is not None and loop_end is not None:
        loop_len = loop_end - loop_start
        on_mask = t < duration_samples
        ptrs_on = src_ptrs[on_mask]
        
        wrap_mask = ptrs_on >= loop_end
        if np.any(wrap_mask):
            ptrs_on[wrap_mask] = loop_start + (ptrs_on[wrap_mask] - loop_start) % loop_len
            
        src_ptrs[on_mask] = ptrs_on
        
        if duration_samples > 0:
            last_ptr = src_ptrs[duration_samples - 1]
        else:
            last_ptr = 0.0
            
        off_mask = t >= duration_samples
        src_ptrs[off_mask] = last_ptr + (t[off_mask] - duration_samples) * ratio
        
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
    print(f"Loaded {len(regions)} regions. default_path: {default_path}")
    
    # We will generate a MIDI file of Bach's Prelude if it doesn't exist
    mid_path = "melody.mid"
    if not os.path.exists(mid_path):
        # Create Bach MIDI
        print("Generating MIDI file...")
        mid = mido.MidiFile()
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.Message('program_change', program=0, time=0))
        
        def add_bar(track, n1, n2, n3, n4, n5):
            for half in range(2):
                track.append(mido.Message('note_on', note=n1, velocity=90, time=0))
                track.append(mido.Message('note_on', note=n2, velocity=90, time=240))
                track.append(mido.Message('note_on', note=n3, velocity=90, time=240))
                track.append(mido.Message('note_on', note=n4, velocity=90, time=240))
                track.append(mido.Message('note_on', note=n5, velocity=90, time=240))
                
                track.append(mido.Message('note_off', note=n3, velocity=0, time=240))
                track.append(mido.Message('note_off', note=n4, velocity=0, time=0))
                track.append(mido.Message('note_off', note=n5, velocity=0, time=0))
                
                # Bass notes hold longer, let's release them at the end of the bar half
                track.append(mido.Message('note_on', note=n3, velocity=90, time=240))
                track.append(mido.Message('note_on', note=n4, velocity=90, time=240))
                track.append(mido.Message('note_on', note=n5, velocity=90, time=240))
                
                track.append(mido.Message('note_off', note=n1, velocity=0, time=240))
                track.append(mido.Message('note_off', note=n2, velocity=0, time=0))
                track.append(mido.Message('note_off', note=n3, velocity=0, time=0))
                track.append(mido.Message('note_off', note=n4, velocity=0, time=0))
                track.append(mido.Message('note_off', note=n5, velocity=0, time=0))
        
        # Bach Prelude notes (Bar 1-4)
        add_bar(track, 48, 52, 55, 60, 64)
        add_bar(track, 50, 53, 57, 62, 65)
        add_bar(track, 47, 50, 55, 62, 65)
        add_bar(track, 48, 52, 55, 60, 64)
        
        # Final chord
        track.append(mido.Message('note_on', note=36, velocity=85, time=0))
        track.append(mido.Message('note_on', note=48, velocity=85, time=0))
        track.append(mido.Message('note_on', note=52, velocity=85, time=0))
        track.append(mido.Message('note_on', note=55, velocity=85, time=0))
        track.append(mido.Message('note_on', note=60, velocity=85, time=0))
        
        track.append(mido.Message('note_off', note=36, velocity=0, time=1920))
        track.append(mido.Message('note_off', note=48, velocity=0, time=0))
        track.append(mido.Message('note_off', note=52, velocity=0, time=0))
        track.append(mido.Message('note_off', note=55, velocity=0, time=0))
        track.append(mido.Message('note_off', note=60, velocity=0, time=0))
        mid.save(mid_path)
        
    print(f"Parsing MIDI file: {mid_path}")
    midi_notes = parse_midi_file(mid_path)
    print(f"Parsed {len(midi_notes)} notes from MIDI.")
    
    # Calculate output audio length
    sr = 44100
    release_time_sec = 1.5
    release_samples = int(release_time_sec * sr)
    
    max_time = 0.0
    for n in midi_notes:
        max_time = max(max_time, n["start_time"] + n["duration"])
    
    total_duration_sec = max_time + release_time_sec
    total_samples = int(math.ceil(total_duration_sec * sr))
    print(f"Total audio duration: {total_duration_sec:.2f}s ({total_samples} samples)")
    
    # Initialize output buffer (stereo)
    output_audio = np.zeros((total_samples, 2), dtype=np.float32)
    
    # Cache for loaded WAV files
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
            print(f"Warning: No matching SFZ region for note {note}, velocity {velocity}")
            continue
            
        sample_name = region["sample"]
        sample_file_path = os.path.join(default_path, sample_name)
        
        # Load sample from cache or disk
        if sample_file_path not in sample_cache:
            if not os.path.exists(sample_file_path):
                print(f"Error: Sample file not found: {sample_file_path}")
                continue
            data, sample_sr = sf.read(sample_file_path)
            # Ensure it is stereo
            if data.ndim == 1:
                data = np.column_stack((data, data))
            sample_cache[sample_file_path] = (data, sample_sr)
            
        sample_data, sample_sr = sample_cache[sample_file_path]
        
        # Resampling ratio
        keycenter = int(region.get("pitch_keycenter", 60))
        ratio = 2.0 ** ((note - keycenter) / 12.0)
        # Adjust ratio if sample rate differs
        if sample_sr != sr:
            ratio *= (sample_sr / sr)
            
        # Parse loop points
        loop_start = None
        loop_end = None
        if region.get("loop_mode") == "loop_continuous":
            if "loop_start" in region and "loop_end" in region:
                loop_start = int(region["loop_start"])
                loop_end = int(region["loop_end"])
                
        # Render this note's audio
        duration_samples = int(duration * sr)
        note_audio = render_note_vectorized(
            sample_data, 
            ratio, 
            velocity, 
            duration_samples, 
            loop_start, 
            loop_end, 
            release_samples
        )
        
        # Mix into main buffer
        start_sample = int(start_time * sr)
        end_sample = min(total_samples, start_sample + note_audio.shape[0])
        mix_len = end_sample - start_sample
        if mix_len > 0:
            output_audio[start_sample:end_sample] += note_audio[:mix_len]
            
    # Normalize final audio if it exceeds clipping levels (optional, but good for mixing multiple notes)
    max_val = np.max(np.abs(output_audio))
    print(f"Max mixed amplitude: {max_val:.4f}")
    if max_val > 0.95:
        print(f"Normalizing audio to 0.90 to prevent clipping.")
        output_audio = output_audio * (0.90 / max_val)
        
    # Apply reverb and delay post-processing via Pedalboard for identical aesthetics
    print("Applying reverb and delay effects...")
    import pedalboard
    from pedalboard import Pedalboard, Reverb, Delay
    
    board = Pedalboard([
        Reverb(room_size=0.6, wet_level=0.25, dry_level=0.75),
        Delay(delay_seconds=0.375, feedback=0.2, mix=0.1)
    ])
    
    # Pedalboard expects (channels, samples)
    processed = board(output_audio.T, sr)
    
    output_path = "Surge_DX_Piano_SFZ_Melody.wav"
    sf.write(output_path, processed.T, sr)
    print(f"Melody successfully rendered using SFZ samples and saved to {output_path}!")

if __name__ == "__main__":
    main()
