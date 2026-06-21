#!/usr/bin/env python3
"""
Studio post-processing for the General MIDI sample pack.

Reads the raw WAV samples produced by sample_gm_pack.py and applies a
studio processing chain in place, after backing the raw files up. Run this
after sample_gm_pack.py, whenever you want to (re)shape the timbre/levels
without re-rendering from Surge XT.

Chain (per sample, in order):
  1. DC offset removal
  2. High-pass filter (35 Hz)  - remove sub-rumble
  3. EQ: low-shelf (-2 @ 250Hz), peak (+1.5 @ 3kHz), high-shelf (+2 @ 10kHz)
  4. Compressor (-20dB thr, 2.5:1) - density without pumping
  5. Subtle reverb (only for sustained/ambient GM groups)
  6. RMS normalization per-instrument (one gain for all 4 notes)
  7. Limiter (-1dB) - brick-wall safety after normalization

Usage:
  python process_samples.py [--input General_MIDI_samples]
                            [--backup-dir General_MIDI_samples_raw]
                            [--target-rms 0.08] [--dry-run]
"""
import os
import re
import sys
import shutil
import argparse
import glob

import numpy as np
import soundfile as sf


# GM group = program_index // 8. Groups that benefit from a subtle reverb tail
# (sustained/ambient/spacey timbres). Transient instruments (pianos, guitars,
# bass, plucked leads, percussion) stay dry to preserve attacks.
REVERB_GROUPS = {
    2,   # Organs
    5,   # Strings (violin..timpani)
    6,   # Ensemble (strings/choir/orchestra hit)
    7,   # Brass
    8,   # Reed
    9,   # Pipe
    11,  # Synth pads
    12,  # Synth FX
    15,  # Sound effects
}


def program_from_name(filename):
    """Extract the GM program index from a sample filename like gm_040_C4.wav."""
    m = re.match(r"gm_(\d{3})_", filename)
    return int(m.group(1)) if m else None


def build_chain(program_index, target_rms, instrument_rms):
    """Build the pedalboard chain for one instrument.

    The reverb stage is conditional on the GM group. Everything else is shared.
    Returns a tuple (pedalboard, rms_gain) where rms_gain is a scalar applied
    after the board (numpy multiply) so all 4 notes of one instrument share it.
    """
    from pedalboard import (Pedalboard, HighpassFilter, LowShelfFilter,
                            HighShelfFilter, PeakFilter, Compressor, Limiter, Reverb)

    pedals = [
        HighpassFilter(cutoff_frequency_hz=35.0),
        # EQ: de-mud, presence, air
        LowShelfFilter(cutoff_frequency_hz=250.0, gain_db=-2.0),
        PeakFilter(cutoff_frequency_hz=3000.0, gain_db=1.5, q=0.7),
        HighShelfFilter(cutoff_frequency_hz=10000.0, gain_db=2.0),
        # Gentle compression for density
        Compressor(threshold_db=-20.0, ratio=2.5, attack_ms=5.0, release_ms=50.0),
    ]

    group = program_index // 8
    if group in REVERB_GROUPS:
        # Very subtle, short tail. Reverb without release_ms param (uses damping).
        pedals.append(Reverb(room_size=0.3, damping=0.7, wet_level=0.10, dry_level=0.90))

    # Final limiter (brick-wall) to catch peaks after normalization gain
    pedals.append(Limiter(threshold_db=-1.0, release_ms=100.0))

    # RMS normalization gain: applied as numpy multiply AFTER the board so the
    # limiter sees the final level. Computed once per instrument from its mean RMS.
    if instrument_rms > 1e-6:
        rms_gain = target_rms / instrument_rms
    else:
        rms_gain = 1.0

    return Pedalboard(pedals), rms_gain


def compute_instrument_rms(files_by_program):
    """For each program, read all its samples and return the mean RMS."""
    rms_by_program = {}
    for prog, paths in files_by_program.items():
        rmss = []
        for p in paths:
            audio, _ = sf.read(p)
            if audio.ndim == 1:
                audio = audio[:, None]
            rmss.append(float(np.sqrt(np.mean(audio ** 2))))
        # Use the mean of non-silent samples (avoid a near-zero sample
        # dragging the target down for instruments that are quiet on some notes).
        nonzero = [r for r in rmss if r > 1e-5]
        rms_by_program[prog] = np.mean(nonzero) if nonzero else 0.0
    return rms_by_program


def main():
    parser = argparse.ArgumentParser(description="Studio-process GM samples in place.")
    parser.add_argument("--input", default="General_MIDI_samples", help="Sample directory to process")
    parser.add_argument("--backup-dir", default="General_MIDI_samples_raw", help="Backup directory for raw samples")
    parser.add_argument("--target-rms", type=float, default=0.08, help="Target per-instrument RMS (0-1)")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and report without writing")
    args = parser.parse_args()

    samples_dir = args.input
    backup_dir = args.backup_dir
    if not os.path.isdir(samples_dir):
        print(f"Error: sample directory not found: {samples_dir}")
        sys.exit(1)

    wav_files = sorted(glob.glob(os.path.join(samples_dir, "*.wav")))
    if not wav_files:
        print(f"Error: no WAV files found in {samples_dir}")
        sys.exit(1)
    print(f"Found {len(wav_files)} WAV files in {samples_dir}.")

    # Group by program index for per-instrument RMS normalization
    files_by_program = {}
    for path in wav_files:
        prog = program_from_name(os.path.basename(path))
        if prog is None:
            continue
        files_by_program.setdefault(prog, []).append(path)

    # --- Backup (only once) ---------------------------------------------------
    if not args.dry_run:
        if os.path.isdir(backup_dir) and glob.glob(os.path.join(backup_dir, "*.wav")):
            print(f"Backup already exists at {backup_dir}, skipping backup (processing the current files).")
        else:
            print(f"Backing up raw samples to {backup_dir} ...")
            os.makedirs(backup_dir, exist_ok=True)
            for path in wav_files:
                shutil.copy2(path, os.path.join(backup_dir, os.path.basename(path)))
            print("Backup complete.")

    # --- Analyze RMS per instrument (from CURRENT files, not backup) ----------
    print("Computing per-instrument RMS from current samples...")
    # For dry-run we measure on the input; for real run we also measure on input
    # and apply gain after the chain.
    rms_by_program = compute_instrument_rms(files_by_program)
    rmss = np.array([v for v in rms_by_program.values() if v > 0])
    if len(rmss):
        print(f"  Instrument RMS: min={rmss.min():.4f} max={rmss.max():.4f} "
              f"mean={rmss.mean():.4f} (target={args.target_rms:.4f})")

    if args.dry_run:
        print("\n[DRY RUN] Would process with chain. Sample gains:")
        for prog in sorted(files_by_program)[:8]:
            r = rms_by_program[prog]
            gain = (args.target_rms / r) if r > 1e-6 else 1.0
            print(f"  prog {prog:03d}: rms={r:.4f} -> gain={gain:.2f}x ({20*np.log10(gain+1e-9):+.1f} dB)")
        print("  ...")
        return

    # --- Process --------------------------------------------------------------
    print(f"\nProcessing {len(wav_files)} samples...")
    for idx, path in enumerate(wav_files):
        prog = program_from_name(os.path.basename(path))
        if prog is None:
            continue
        if idx % 50 == 0 or idx == len(wav_files) - 1:
            print(f"  [{idx+1}/{len(wav_files)}] {os.path.basename(path)}")

        audio, sr = sf.read(path)
        if audio.ndim == 1:
            audio = np.column_stack((audio, audio))
        # Preserve original dtype/subtype (PCM_24). Work in float32.
        audio = audio.astype(np.float32, copy=False)

        # 1. DC removal
        audio = audio - np.mean(audio, axis=0)

        board, rms_gain = build_chain(prog, args.target_rms, rms_by_program[prog])

        # pedalboard expects (channels, samples)
        processed = board(audio.T, sr)
        audio_out = processed.T

        # 6. Per-instrument RMS normalization (applied after the board, before limiter
        # is already in the chain; we re-limit by clamping to avoid clipping).
        audio_out = audio_out * rms_gain
        # Safety clamp (the chain's limiter already runs at the fixed threshold,
        # but normalization gain can push above it; clamp to [-1,1] for PCM safety).
        audio_out = np.clip(audio_out, -1.0, 1.0)

        sf.write(path, audio_out, sr, subtype="PCM_24")

    # --- Report ---------------------------------------------------------------
    print("\nRe-analyzing processed samples...")
    new_rms = compute_instrument_rms(files_by_program)
    new_rmss = np.array([v for v in new_rms.values() if v > 0])
    if len(new_rmss):
        print(f"  Instrument RMS: min={new_rmss.min():.4f} max={new_rmss.max():.4f} "
              f"mean={new_rmss.mean():.4f}")
        print(f"  Spread (max/min ratio): {new_rmss.max()/(new_rmss.min()+1e-9):.1f}x  "
              f"(was {rmss.max()/(rmss.min()+1e-9):.1f}x)")
    print("\nProcessing complete.")


if __name__ == "__main__":
    main()
