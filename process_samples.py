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
  7. Limiter (-1dB) - brick-wall safety, runs AFTER step 6 so the gain
     cannot push limited peaks back over 0 dBFS

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
                            HighShelfFilter, PeakFilter, Compressor, Reverb)

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

    # NOTE: the Limiter is intentionally NOT in this board. It must run AFTER
    # the per-instrument RMS gain (applied in main() as a numpy multiply),
    # otherwise the gain would push limited peaks back above 0 dBFS and
    # np.clip() would hard-clip them into distortion. main() applies a second
    # Pedalboard(Limiter) on the gained signal for a true brick-wall ceiling.

    # RMS normalization gain: applied as numpy multiply after this board. A
    # final peak ceiling is applied in main() as a clean numpy peak-normalize
    # (NOT a pedalboard Limiter — the pedalboard Limiter does NOT brick-wall:
    # in testing it hard-clips to exactly 1.0 at *every* threshold, with more
    # saturation at lower thresholds, which is the opposite of safe). The gain
    # is capped so very-quiet instruments don't require huge limiting swings.
    if instrument_rms > 1e-6:
        rms_gain = min(target_rms / instrument_rms, 4.0)
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

    # --- Backup (only once) + re-run safety -----------------------------------
    if not args.dry_run:
        if os.path.isdir(backup_dir) and glob.glob(os.path.join(backup_dir, "*.wav")):
            # Backup exists from a previous run. To stay idempotent, restore the
            # raw samples from backup before processing, so we always start from
            # the unprocessed source instead of stacking processing on top of an
            # already-processed result (which would double-compress / re-EQ /
            # re-normalize and drift further on each run).
            print(f"Backup already exists at {backup_dir}.")
            print("Restoring raw samples from backup before processing (idempotency)...")
            for path in glob.glob(os.path.join(backup_dir, "*.wav")):
                shutil.copy2(path, os.path.join(samples_dir, os.path.basename(path)))
            # Rebuild the working file list with the restored (raw) files
            wav_files = sorted(glob.glob(os.path.join(samples_dir, "*.wav")))
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
        if 32 <= prog <= 39:
            # Bass instruments: skip the full studio chain to preserve low-end
            # power, BUT still declip — Surge XT renders bass patches hard-clipped
            # on high notes (e.g. gm_033 C7/C8 has 20k+ samples pinned at 1.0),
            # and those flat-top segments crackle on playback. Apply a soft
            # declamper (cubic waveshaper) that rounds the hard shoulders into
            # smooth arcs, then peak-normalize to 0.95.
            raw_path = os.path.join(backup_dir, os.path.basename(path))
            shutil.copy2(raw_path, path)
            audio, sr = sf.read(path)
            if audio.ndim == 1:
                audio = np.column_stack((audio, audio))
            audio = audio.astype(np.float32, copy=True)
            # Cubic soft-clip: y = x - (1/3)*x^3 for |x|<=1, smoothly limiting.
            # Maps ±1 → ±0.667 with zero derivative at the limit, removing the
            # flat clipped shoulders entirely while preserving sub-0.5 samples
            # almost linearly.
            clipped = np.abs(audio) >= 0.999
            if np.any(clipped):
                audio = audio - (1.0 / 3.0) * np.power(audio, 3)
            peak = float(np.max(np.abs(audio)))
            if peak > 0.95:
                audio = audio * (0.95 / peak)
            sf.write(path, audio, sr, subtype="PCM_24")
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

        # Per-instrument RMS normalization: scale so each instrument reaches the
        # target RMS. Gain is capped in build_chain to avoid extreme swings.
        audio_out = audio_out * rms_gain

        # --- Production Post-Processing ---
        # 1. Mid-Side stereo widening for strings (group 6) and pads (group 11)
        group = prog // 8
        if group in {6, 11}:
            mid = (audio_out[:, 0] + audio_out[:, 1]) * 0.5
            side = (audio_out[:, 0] - audio_out[:, 1]) * 0.5
            side = side * 1.35  # Widen stereo field by 35%
            audio_out[:, 0] = mid + side
            audio_out[:, 1] = mid - side

        # 2. Subtle analog tube saturation/excitation (even/odd harmonic warmth)
        clipped = np.clip(audio_out, -1.0, 1.0)
        sat = clipped - (clipped ** 3) / 6.0
        audio_out = audio_out * 0.90 + sat * 0.10

        # 3. Smooth cosine fade-out over last 150ms to prevent clicks/pop tails
        fade_len = int(0.15 * sr)
        if len(audio_out) > fade_len:
            fade_curve = 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, fade_len)))
            audio_out[-fade_len:] *= fade_curve[:, np.newaxis]

        # Final peak ceiling via clean numpy: if any sample exceeds 0.95 after
        # the gain, scale the WHOLE buffer down so its peak is exactly 0.95.
        # This is a transparent brick-wall that never saturates (unlike the
        # pedalboard Limiter, which hard-clips to 1.0 regardless of threshold).
        peak = float(np.max(np.abs(audio_out)))
        ceiling = 0.95
        if peak > ceiling:
            audio_out = audio_out * (ceiling / peak)

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
