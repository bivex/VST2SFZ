#!/usr/bin/env python3
import os
import sys
import re
import math
import argparse
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

def parse_midi_file(midi_path):
    print(f"Parsing MIDI file: {midi_path}")
    mid = mido.MidiFile(midi_path)
    notes = []
    active_notes = {}
    current_time_sec = 0.0
    
    # Direct iteration over MidiFile object merges all tracks and processes delta times to seconds automatically
    for msg in mid:
        current_time_sec += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            if msg.note in active_notes:
                start_time, velocity = active_notes.pop(msg.note)
                duration = current_time_sec - start_time
                notes.append({
                    "note": msg.note,
                    "velocity": velocity,
                    "start_time": start_time,
                    "duration": duration
                })
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
                
    # Close any notes that are still active
    for note, (start_time, velocity) in active_notes.items():
        notes.append({
            "note": note,
            "velocity": velocity,
            "start_time": start_time,
            "duration": max(0.1, current_time_sec - start_time)
        })
        
    return notes

def render_note_vectorized(sample_data, ratio, velocity, duration_samples, release_samples=44100):
    num_src_samples, num_channels = sample_data.shape
    max_resampled_samples = int(math.ceil(num_src_samples / ratio))
    
    # Optimization: Cap buffer size at the maximum samples the source WAV can produce
    total_samples = min(duration_samples + release_samples, max_resampled_samples)
    if total_samples <= 0:
        return np.zeros((0, num_channels), dtype=np.float32)
        
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
        
        # Apply release envelope ramp if note-off occurs before sample naturally ends
        if release_samples > 0 and duration_samples < total_samples:
            release_ramp = np.ones(total_samples, dtype=np.float32)
            off_indices = np.arange(total_samples - duration_samples, dtype=np.float32)
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
    parser = argparse.ArgumentParser(description="Render a MIDI file to a WAV using an SFZ instrument.")
    parser.add_argument("--midi", type=str, default="6101-2d_moonlight_sonata_27-2_1_2_(nc)smythe.mid", help="Path to input MIDI file")
    parser.add_argument("--sfz", type=str, default="Surge_DX_Piano.sfz", help="Path to input SFZ mapping file")
    parser.add_argument("--output", type=str, default="Surge_DX_Piano_SFZ_Moonlight_Full.wav", help="Path to output WAV file")
    parser.add_argument("--sr", type=int, default=96000, help="Rendering sample rate (Hz)")
    parser.add_argument("--release", type=float, default=2.0, help="Envelope release time (seconds)")
    args = parser.parse_args()
    
    if not os.path.exists(args.midi):
        print(f"Error: MIDI file not found: {args.midi}")
        sys.exit(1)
        
    if not os.path.exists(args.sfz):
        print(f"Error: SFZ file not found: {args.sfz}")
        sys.exit(1)
        
    default_path, regions = parse_sfz(args.sfz)
    midi_notes = parse_midi_file(args.midi)
    print(f"Parsed {len(midi_notes)} notes from MIDI.")
    
    sr = args.sr
    release_samples = int(args.release * sr)
    
    max_time = 0.0
    for n in midi_notes:
        max_time = max(max_time, n["start_time"] + n["duration"])
    total_duration_sec = max_time + args.release
    total_samples = int(math.ceil(total_duration_sec * sr))
    print(f"Total audio duration: {total_duration_sec:.2f}s ({total_samples} samples)")
    
    output_audio = np.zeros((total_samples, 2), dtype=np.float32)
    sample_cache = {}
    
    print("Synthesizing notes...")
    percent_mark = len(midi_notes) // 10 if len(midi_notes) >= 10 else 1
    
    for idx, n in enumerate(midi_notes):
        if idx % percent_mark == 0 or idx == len(midi_notes) - 1:
            progress = (idx + 1) / len(midi_notes) * 100
            print(f"Synthesis progress: {progress:.0f}% ({idx + 1}/{len(midi_notes)} notes)")
            
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
                print(f"Warning: Sample file not found: {sample_file_path}")
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
            
    # Normalize output to prevent clipping
    max_val = np.max(np.abs(output_audio))
    print(f"Max raw mixed amplitude: {max_val:.4f}")
    if max_val > 0.95:
        output_audio = output_audio * (0.90 / max_val)
        print("Audio normalized to 0.90 peak level.")
        
    print("Applying reverb and delay effects...")
    try:
        import pedalboard
        from pedalboard import Pedalboard, Reverb, Delay
        
        board = Pedalboard([
            Reverb(room_size=0.75, wet_level=0.30, dry_level=0.70),
            Delay(delay_seconds=0.370, feedback=0.18, mix=0.10)
        ])
        processed = board(output_audio.T, sr)
        output_data = processed.T
    except Exception as e:
        print(f"Warning: pedalboard failed or not available, saving dry output. ({e})")
        output_data = output_audio
        
    print(f"Saving WAV output to: {args.output}")
    sf.write(args.output, output_data, sr, subtype='PCM_24')
    print("Render complete! Enjoy your audio.")

if __name__ == "__main__":
    main()
