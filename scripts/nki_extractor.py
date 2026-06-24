#!/usr/bin/env python3
"""
nki_extractor.py — витягує embedded WAV семпли з Kontakt .nki файлів
і будує SFZ маппінг через librosa YIN pitch detection.

Usage:
    python nki_extractor.py <file.nki> [--out-dir DIR] [--sfz PATH] [--dry-run]

Examples:
    python nki_extractor.py "Amore Grand Piano v2.nki"
    python nki_extractor.py "Amore Grand Piano v2.nki" --out-dir samples/ --sfz amore.sfz
"""

import argparse
import os
import re
import struct
import sys
import numpy as np
import soundfile as sf

# ── pitch detection ────────────────────────────────────────────────────────────

def detect_pitch_yin(audio: np.ndarray, sr: int) -> int:
    """YIN pitch detection via librosa. Returns MIDI note (0 = undetected)."""
    try:
        import librosa
    except ImportError:
        print("[warn] librosa not installed — falling back to HPS")
        return detect_pitch_hps(audio, sr)

    seg = audio[:int(sr * 0.5)].astype(np.float32)
    f0s = librosa.yin(seg, fmin=27.5, fmax=4186, sr=sr)
    f0s = f0s[f0s > 30]
    if len(f0s) == 0:
        return 0
    f0 = float(np.median(f0s))
    return int(round(69 + 12 * np.log2(f0 / 440)))


def detect_pitch_hps(audio: np.ndarray, sr: int, harmonics: int = 5) -> int:
    """Harmonic Product Spectrum fallback."""
    seg = audio[:int(sr * 0.5)]
    N = 8192
    if len(seg) < N:
        seg = np.pad(seg, (0, N - len(seg)))
    w = np.fft.rfft(seg[:N] * np.hanning(N))
    mag = np.abs(w)
    hps = mag.copy()
    for h in range(2, harmonics + 1):
        dec = mag[::h]
        hps[:len(dec)] *= dec
    freqs = np.fft.rfftfreq(N, 1 / sr)
    idx = int(np.argmax(hps[20:2000])) + 20
    f0 = freqs[idx]
    if f0 < 20:
        return 0
    return int(round(69 + 12 * np.log2(f0 / 440)))


NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def midi_to_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


# ── NKI extraction ─────────────────────────────────────────────────────────────

def extract_wavs(nki_path: str, out_dir: str, dry_run: bool = False) -> list[dict]:
    """
    Scan .nki for embedded RIFF/WAVE blocks, extract each as a numbered WAV.
    Returns list of dicts: {path, index, sr, channels, frames, duration}
    """
    print(f"Reading {nki_path} ({os.path.getsize(nki_path) // 1024 // 1024} MB)...")
    with open(nki_path, 'rb') as f:
        data = f.read()

    offsets = [m.start() for m in re.finditer(b'RIFF', data)]
    print(f"Found {len(offsets)} RIFF blocks")

    if not dry_run:
        os.makedirs(out_dir, exist_ok=True)

    stem = os.path.splitext(os.path.basename(nki_path))[0]
    # sanitize for filename
    stem = re.sub(r'[^\w\-]', '_', stem)

    results = []
    skipped = 0
    for i, off in enumerate(offsets):
        if off + 12 > len(data):
            skipped += 1
            continue
        chunk_size = struct.unpack_from('<I', data, off + 4)[0]
        fmt = data[off + 8:off + 12]
        if fmt != b'WAVE':
            skipped += 1
            continue
        total = chunk_size + 8
        if off + total > len(data):
            # truncated — take what we have
            total = len(data) - off

        wav_bytes = data[off:off + total]
        out_name = f"{stem}_{i:03d}.wav"
        out_path = os.path.join(out_dir, out_name)

        if not dry_run:
            with open(out_path, 'wb') as wf:
                wf.write(wav_bytes)

        try:
            info = sf.info(out_path) if not dry_run else None
            results.append({
                'path': out_path,
                'name': out_name,
                'index': i,
                'sr': info.samplerate if info else None,
                'channels': info.channels if info else None,
                'frames': info.frames if info else None,
                'duration': info.duration if info else None,
            })
        except Exception as e:
            print(f"  [warn] {out_name}: {e}")
            if not dry_run:
                os.remove(out_path)
            skipped += 1

    print(f"Extracted {len(results)} WAV files (skipped {skipped})")
    return results


# ── pitch detection pass ───────────────────────────────────────────────────────

def detect_pitches(wavs: list[dict], workers: int = 4) -> list[dict]:
    """Add 'midi' and 'note' fields to each wav dict."""
    total = len(wavs)
    for i, w in enumerate(wavs):
        try:
            audio, sr = sf.read(w['path'])
            if audio.ndim > 1:
                audio = audio[:, 0]
            midi = detect_pitch_yin(audio, sr)
        except Exception:
            midi = 0
        w['midi'] = midi
        w['note'] = midi_to_name(midi) if midi else '?'
        if (i + 1) % 10 == 0 or (i + 1) == total:
            print(f"  pitch detection: {i+1}/{total}", end='\r')
    print()
    return wavs


# ── velocity layer grouping ────────────────────────────────────────────────────

def group_velocity_layers(wavs: list[dict]) -> dict[int, list[dict]]:
    """
    Group WAVs by detected MIDI pitch.
    Within each pitch group, sort by duration descending
    (longer = softer velocity layer for piano, typically).
    Returns {midi: [wav, ...]} sorted by pitch.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for w in wavs:
        midi = w.get('midi', 0)
        if midi:
            groups[midi].append(w)

    # sort within group by duration desc (longer = softer)
    for midi in groups:
        groups[midi].sort(key=lambda x: x.get('duration', 0), reverse=True)

    return dict(sorted(groups.items()))


# ── SFZ generation ─────────────────────────────────────────────────────────────

def build_sfz(groups: dict[int, list[dict]], sfz_path: str, samples_dir: str):
    """
    Build a 2-velocity-layer SFZ. Groups with 1 sample get full velocity range.
    lokey/hikey = midpoint between adjacent pitches.
    """
    pitches = sorted(groups.keys())

    def key_range(i: int):
        lo = (pitches[i] + pitches[i - 1]) // 2 + 1 if i > 0 else 0
        hi = (pitches[i] + pitches[i + 1]) // 2 if i < len(pitches) - 1 else 127
        return lo, hi

    lines = []
    lines.append("// Auto-generated by nki_extractor.py")
    lines.append(f"// Source samples: {samples_dir}")
    lines.append("")
    lines.append("<control>")
    lines.append(f"default_path={os.path.abspath(samples_dir)}/")
    lines.append("")

    for i, pitch in enumerate(pitches):
        wavs = groups[pitch]
        lokey, hikey = key_range(i)
        note_str = midi_to_name(pitch)
        lines.append(f"<group>  // {note_str} (midi {pitch})  lokey={lokey} hikey={hikey}")

        n = len(wavs)
        if n == 1:
            w = wavs[0]
            lines.append(
                f"<region> sample={w['name']} pitch_keycenter={pitch}"
                f" lokey={lokey} hikey={hikey} lovel=0 hivel=127"
            )
        elif n == 2:
            # longer dur = soft (v64), shorter = loud (v127)
            soft, loud = wavs[0], wavs[1]
            lines.append(
                f"<region> sample={soft['name']} pitch_keycenter={pitch}"
                f" lokey={lokey} hikey={hikey} lovel=0 hivel=95"
                f" xfin_lovel=0 xfin_hivel=0 xfout_lovel=85 xfout_hivel=95"
            )
            lines.append(
                f"<region> sample={loud['name']} pitch_keycenter={pitch}"
                f" lokey={lokey} hikey={hikey} lovel=96 hivel=127"
                f" xfin_lovel=85 xfin_hivel=95 xfout_lovel=127 xfout_hivel=127"
            )
        else:
            # 3+ layers: distribute evenly
            step = 127 // n
            for j, w in enumerate(wavs):
                lo_v = j * step
                hi_v = (j + 1) * step - 1 if j < n - 1 else 127
                lines.append(
                    f"<region> sample={w['name']} pitch_keycenter={pitch}"
                    f" lokey={lokey} hikey={hikey} lovel={lo_v} hivel={hi_v}"
                )
        lines.append("")

    os.makedirs(os.path.dirname(os.path.abspath(sfz_path)), exist_ok=True)
    with open(sfz_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    print(f"SFZ written: {sfz_path}  ({len(pitches)} key zones)")


# ── rename samples to note names ───────────────────────────────────────────────

def rename_to_notes(groups: dict[int, list[dict]]) -> dict[int, list[dict]]:
    """Rename files from amore_NNN.wav to NoteOctave_vXX.wav in-place."""
    updated = {}
    for pitch, wavs in groups.items():
        note_str = midi_to_name(pitch).replace('#', 's')  # C#3 → Cs3
        new_wavs = []
        for vi, w in enumerate(wavs):
            vel_tag = f"v{(vi + 1) * 64:03d}"  # v064, v127 for 2 layers
            new_name = f"{note_str}_{vel_tag}.wav"
            new_path = os.path.join(os.path.dirname(w['path']), new_name)
            if w['path'] != new_path and os.path.exists(w['path']):
                os.rename(w['path'], new_path)
            w = dict(w, path=new_path, name=new_name)
            new_wavs.append(w)
        updated[pitch] = new_wavs
    return updated


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract embedded WAV samples from Kontakt .nki and build SFZ."
    )
    parser.add_argument("nki", help="Path to .nki file")
    parser.add_argument(
        "--out-dir", default=None,
        help="Output directory for WAV files (default: <nki_stem>_samples/ next to .nki)"
    )
    parser.add_argument(
        "--sfz", default=None,
        help="Output SFZ path (default: <nki_stem>.sfz next to .nki)"
    )
    parser.add_argument(
        "--rename", action="store_true",
        help="Rename extracted WAVs to note names (e.g. C4_v064.wav)"
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Parallel workers for pitch detection (default: 4)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scan only, do not write files"
    )
    parser.add_argument(
        "--no-sfz", action="store_true",
        help="Extract WAVs only, skip SFZ generation"
    )
    args = parser.parse_args()

    nki_path = os.path.abspath(args.nki)
    if not os.path.exists(nki_path):
        print(f"Error: file not found: {nki_path}")
        sys.exit(1)

    stem = os.path.splitext(os.path.basename(nki_path))[0]
    base_dir = os.path.dirname(nki_path)

    out_dir = args.out_dir or os.path.join(base_dir, re.sub(r'[^\w\-]', '_', stem) + "_samples")
    sfz_path = args.sfz or os.path.join(base_dir, re.sub(r'[^\w\-]', '_', stem) + ".sfz")

    # 1. extract
    wavs = extract_wavs(nki_path, out_dir, dry_run=args.dry_run)
    if not wavs or args.dry_run:
        print(f"Dry run: {len(wavs)} WAVE blocks found.")
        return

    # 2. pitch detection
    print(f"Detecting pitch for {len(wavs)} samples ({args.workers} workers)...")
    wavs = detect_pitches(wavs, workers=args.workers)

    # print summary
    print(f"\n{'FILE':<30} {'MIDI':>4}  {'NOTE':<5}  {'DUR':>6}s")
    print("-" * 55)
    for w in wavs:
        print(f"{w['name']:<30} {w.get('midi', 0):>4}  {w.get('note','?'):<5}  {w.get('duration', 0):>6.2f}")

    # 3. group by pitch
    groups = group_velocity_layers(wavs)
    undetected = [w for w in wavs if not w.get('midi')]
    if undetected:
        print(f"\n[warn] {len(undetected)} files with undetected pitch — excluded from SFZ:")
        for w in undetected:
            print(f"  {w['name']}  dur={w.get('duration',0):.2f}s")

    # 4. rename
    if args.rename:
        print("\nRenaming files to note names...")
        groups = rename_to_notes(groups)

    # 5. SFZ
    if not args.no_sfz:
        print(f"\nBuilding SFZ: {sfz_path}")
        build_sfz(groups, sfz_path, out_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
