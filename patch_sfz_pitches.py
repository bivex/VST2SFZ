#!/usr/bin/env python3
"""
Multiprocessed pitch correction tool for General MIDI SFZ packs.

Analyzes raw WAV samples in parallel using the loudest-peak method
(detect_pitch_midi_loudest from pitch_utils), and patches pitch_keycenter
opcodes in all target SFZ files in-place.

Why loudest-peak here (not validated lowest-peak)?
  Raw samples were stored BEFORE transpose compensation.  The dominant
  spectral energy is the perceived pitch of the preset — possibly many
  octaves from the filename note.  The loudest peak captures that correctly
  (88.7% agreement with keycenters sample_gm_pack.py computed at render
  time, vs 56% for lowest-peak on the same raw files).
"""

import os
import re
import glob
import argparse
import numpy as np
import soundfile as sf
from concurrent.futures import ProcessPoolExecutor
from pitch_utils import detect_pitch_midi_loudest as detect_pitch_midi

# Default paths
DEFAULT_RAW_DIR = "/Volumes/External/Code/VST2SFZ/General_MIDI_samples_raw"
DEFAULT_SFZ_FILES = [
    "/Volumes/External/Code/VST2SFZ/General_MIDI.sfz",
    "/Volumes/External/Code/VST2SFZ/General_MIDI_sfizz.sfz",
    "/Volumes/External/Code/VST2SFZ/General_MIDI_sfizz_processed.sfz",
]


# detect_pitch_midi is imported from pitch_utils (validated lowest-peak algorithm)


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
    # Melodic format: gm_000_C4_v64.wav -> C4
    # Drum format:    gm_drum_N57_v127.wav -> MIDI note 57
    default_note = 60
    m = re.search(r"gm_\d{3}_([A-Ga-g]#?\d+)_v", filename)
    if m:
        note_str = m.group(1)
        notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        letter_match = re.match(r"^([A-G]#?)(-?\d+)$", note_str)
        if letter_match:
            letter = letter_match.group(1)
            octave = int(letter_match.group(2))
            if letter in notes:
                val = notes.index(letter)
                default_note = val + (octave + 1) * 12
    else:
        m_drum = re.search(r"gm_drum_N(\d+)_v", filename)
        if m_drum:
            default_note = int(m_drum.group(1))

    return filename, default_note


def main():
    parser = argparse.ArgumentParser(
        description="Fast, parallelized pitch correction for SFZs."
    )
    parser.add_argument(
        "--raw-dir", default=DEFAULT_RAW_DIR, help="Directory containing raw WAV files"
    )
    parser.add_argument(
        "--sfz", nargs="*", default=DEFAULT_SFZ_FILES, help="SFZ files to patch"
    )
    parser.add_argument(
        "--workers", type=int, default=None, help="Number of parallel worker processes"
    )
    args = parser.parse_args()

    if not os.path.isdir(args.raw_dir):
        print(f"Error: Raw samples directory not found: {args.raw_dir}")
        return

    wav_files = sorted(glob.glob(os.path.join(args.raw_dir, "*.wav")))
    if not wav_files:
        print(f"Error: No WAV files found in {args.raw_dir}")
        return

    print(f"Found {len(wav_files)} raw samples in {args.raw_dir}")
    print(
        f"Analyzing pitches in parallel using {args.workers or 'all available'} CPU cores..."
    )

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
                print(
                    f"  Processed [{completed}/{total}] samples... Last: {filename} -> pitch={pitch}"
                )

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
        with open(sfz_path, "r") as f:
            lines = f.readlines()

        updated_lines = []
        replaced_count = 0
        for line in lines:
            if "<region>" in line:
                m_sample = re.search(r"sample=([^ ]+\.wav)", line)
                if m_sample:
                    sample_path = m_sample.group(1)
                    sample_name = os.path.basename(sample_path)

                    if sample_name in pitch_map:
                        new_pitch = pitch_map[sample_name]
                        if re.search(r"pitch_keycenter=\d+", line):
                            line_new, count = re.subn(
                                r"pitch_keycenter=\d+",
                                f"pitch_keycenter={new_pitch}",
                                line,
                            )
                            if count > 0:
                                line = line_new
                                replaced_count += 1
                        else:
                            line = line.rstrip() + f" pitch_keycenter={new_pitch}\n"
                            replaced_count += 1
            updated_lines.append(line)

        with open(sfz_path, "w") as f:
            f.writelines(updated_lines)
        print(
            f"  → Successfully patched {replaced_count} regions in {os.path.basename(sfz_path)}"
        )

    print("\n✓ Parallel pitch patching complete!")


if __name__ == "__main__":
    main()
