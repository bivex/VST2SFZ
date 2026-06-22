#!/usr/bin/env python3
"""
Multiprocessed pitch correction tool for General MIDI SFZ packs.

Analyzes raw WAV samples in parallel using the "lowest-peak" method,
and patches pitch_keycenter opcodes in all target SFZ files in-place.
"""
import os
import re
import glob
import argparse
import numpy as np
import soundfile as sf
from concurrent.futures import ProcessPoolExecutor

# Default paths
DEFAULT_RAW_DIR = "/Volumes/External/Code/VST2SFZ/General_MIDI_samples_raw"
DEFAULT_SFZ_FILES = [
    "/Volumes/External/Code/VST2SFZ/General_MIDI.sfz",
    "/Volumes/External/Code/VST2SFZ/General_MIDI_sfizz.sfz",
    "/Volumes/External/Code/VST2SFZ/General_MIDI_sfizz_processed.sfz"
]

def detect_pitch_midi(audio, sr):
    """Detects fundamental pitch using the lowest-peak method."""
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    # Sustain window: skip attack (first 0.1s), take next 0.6s
    start = int(sr * 0.1)
    seg = mono[start:start + int(sr * 0.6)]
    if seg.size == 0 or float(np.max(np.abs(seg))) < 1e-5:
        return None
    seg = seg - float(np.mean(seg))  # remove DC
    seg = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
    
    valid_indices = np.where((freqs >= 16) & (freqs <= 8400))[0]
    if len(valid_indices) == 0:
        return None
        
    max_mag = float(np.max(spec[valid_indices]))
    if max_mag < 1e-5:
        return None
        
    threshold = 0.10 * max_mag
    
    # Scan from low to high frequency for the first local peak exceeding threshold
    best_idx = None
    for idx in valid_indices:
        if idx > 0 and idx < len(spec) - 1:
            if spec[idx] >= spec[idx - 1] and spec[idx] >= spec[idx + 1]:
                if spec[idx] >= threshold:
                    best_idx = idx
                    break
                    
    if best_idx is None:
        best_idx = int(valid_indices[np.argmax(spec[valid_indices])])
        
    freq = freqs[best_idx]
    if freq <= 0:
        return None
        
    if 0 < best_idx < len(freqs) - 1:
        a0, a1, a2 = spec[best_idx - 1], spec[best_idx], spec[best_idx + 1]
        denom = (a0 - 2 * a1 + a2)
        if denom != 0:
            offset = 0.5 * (a0 - a2) / denom
            freq = freqs[best_idx] + offset * (freqs[1] - freqs[0])
            
    midi = 69 + 12 * np.log2(freq / 440.0)
    return int(round(midi))

def process_single_file(path):
    """Worker task: reads a WAV file and returns its detected pitch."""
    filename = os.path.basename(path)
    try:
        audio, sr = sf.read(path)
        detected = detect_pitch_midi(audio, sr)
        if detected is not None:
            return filename, detected
    except Exception as e:
        # Silently fail or log to stderr; main process handles fallback
        pass
        
    # Extract fallback pitch from note name in filename
    # Format: gm_000_C4_v64.wav -> C4
    default_note = 60
    m = re.search(r'gm_\d{3}_([A-Ga-g]#?\d+)_v', filename)
    if m:
        note_str = m.group(1)
        notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        letter_match = re.match(r'^([A-G]#?)(-?\d+)$', note_str)
        if letter_match:
            letter = letter_match.group(1)
            octave = int(letter_match.group(2))
            val = notes.index(letter)
            default_note = val + (octave + 1) * 12
            
    return filename, default_note

def main():
    parser = argparse.ArgumentParser(description="Fast, parallelized pitch correction for SFZs.")
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR, help="Directory containing raw WAV files")
    parser.add_argument("--sfz", nargs="*", default=DEFAULT_SFZ_FILES, help="SFZ files to patch")
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel worker processes")
    args = parser.parse_args()

    if not os.path.isdir(args.raw_dir):
        print(f"Error: Raw samples directory not found: {args.raw_dir}")
        return

    wav_files = sorted(glob.glob(os.path.join(args.raw_dir, "*.wav")))
    if not wav_files:
        print(f"Error: No WAV files found in {args.raw_dir}")
        return

    print(f"Found {len(wav_files)} raw samples in {args.raw_dir}")
    print(f"Analyzing pitches in parallel using {args.workers or 'all available'} CPU cores...")

    pitch_map = {}
    completed = 0
    total = len(wav_files)

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        # Submit all jobs and read results as they complete
        futures = executor.map(process_single_file, wav_files)
        for filename, pitch in futures:
            pitch_map[filename] = pitch
            completed += 1
            if completed % 250 == 0 or completed == total:
                print(f"  Processed [{completed}/{total}] samples... Last: {filename} -> pitch={pitch}")

    # Align soft velocity pitches to the loudest velocity (v127) pitch for each note
    print("\nAligning soft velocity layers to loudest velocity (v127) pitches...")
    aligned_count = 0
    for filename in list(pitch_map.keys()):
        if "_v64.wav" in filename:
            v127_name = filename.replace("_v64.wav", "_v127.wav")
            if v127_name in pitch_map:
                v64_pitch = pitch_map[filename]
                v127_pitch = pitch_map[v127_name]
                if v64_pitch != v127_pitch:
                    pitch_map[filename] = v127_pitch
                    aligned_count += 1
    if aligned_count > 0:
        print(f"  → Aligned {aligned_count} soft velocity layers' pitches.")

    print("\nPatching SFZ files...")
    for sfz_path in args.sfz:
        if not os.path.exists(sfz_path):
            print(f"Warning: SFZ file not found, skipping: {sfz_path}")
            continue

        print(f"Updating {os.path.basename(sfz_path)}...")
        with open(sfz_path, 'r') as f:
            lines = f.readlines()

        updated_lines = []
        replaced_count = 0
        for line in lines:
            if "<region>" in line:
                m_sample = re.search(r'sample=([^ ]+\.wav)', line)
                if m_sample:
                    sample_path = m_sample.group(1)
                    sample_name = os.path.basename(sample_path)
                    
                    if sample_name in pitch_map:
                        new_pitch = pitch_map[sample_name]
                        # In-place regex substitution of the pitch_keycenter parameter
                        line_new, count = re.subn(r'pitch_keycenter=\d+', f'pitch_keycenter={new_pitch}', line)
                        if count > 0:
                            line = line_new
                            replaced_count += 1
            updated_lines.append(line)

        with open(sfz_path, 'w') as f:
            f.writelines(updated_lines)
        print(f"  → Successfully patched {replaced_count} regions in {os.path.basename(sfz_path)}")

    print("\n✓ Parallel pitch patching complete!")

if __name__ == "__main__":
    main()
