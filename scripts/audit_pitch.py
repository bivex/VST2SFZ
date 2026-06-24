#!/usr/bin/env python3
"""
Pitch & timbre audit for the GM SFZ pack.

Three independent pitch detectors are run on every raw (dry) sample so
results can be cross-checked instead of trusting a single algorithm:

  * ACF   — biased autocorrelation (classic, robust for tonal instruments)
  * HPS   — harmonic product spectrum (robust to weak fundamentals)
  * FFT   — lowest spectral peak above 10% of max (current sample_gm_pack method)
  * FFT-L — loudest spectral peak   (current patch_sfz_pitches method)

For each sample we compute the offset, in semitones, between the requested
note (encoded in the filename) and each detector's estimate. Offsets near
multiples of 12 indicate an *octave-shifted preset* (Surge presets that
transpose the played note); offsets that don't match a multiple of 12
indicate an actual detection problem.

A CSV is written to audit_pitch.csv and a human-readable summary to stdout.
"""

import os
import re
import sys
import glob
import csv
import argparse
import numpy as np
import soundfile as sf
from concurrent.futures import ProcessPoolExecutor, as_completed

NOTE_RE = re.compile(r"gm_(\d{3})_([A-G]s?\d+)_v(\d+)\.wav$")
NOTE_LETTERS = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"]


def note_name_to_midi(name):
    m = re.match(r"^([A-G]s?)(-?\d+)$", name)
    if not m:
        return None
    letter, octave = m.group(1), int(m.group(2))
    if letter not in NOTE_LETTERS:
        return None
    return NOTE_LETTERS.index(letter) + (octave + 1) * 12


def midi_to_name(m):
    return f"{NOTE_LETTERS[m % 12]}{(m // 12) - 1}"


def freq_to_midi(f):
    if f <= 0:
        return None
    return 69 + 12 * np.log2(f / 440.0)


def _sustain_segment(audio, sr):
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    start = int(sr * 0.12)
    end = start + int(sr * 0.6)
    seg = mono[start:end]
    if seg.size == 0 or float(np.max(np.abs(seg))) < 1e-5:
        return None
    seg = seg - float(np.mean(seg))
    return seg


def detect_acf(audio, sr):
    """Biased autocorrelation with parabolic peak interpolation."""
    seg = _sustain_segment(audio, sr)
    if seg is None:
        return None
    seg = seg * np.hanning(len(seg))
    n = len(seg)
    corr = np.correlate(seg, seg, mode="full")[n - 1:]
    corr = corr / corr[0]
    # Only consider lags corresponding to MIDI 24..108 (C1..C8)
    min_lag = max(1, int(sr / 1300.0))   # ~MIDI 108
    max_lag = min(n - 1, int(sr / 32.0))  # ~MIDI 24
    if max_lag <= min_lag:
        return None
    region = corr[min_lag:max_lag]
    if region.size == 0:
        return None
    # First major peak after the initial descent
    best = None
    for i in range(1, len(region) - 1):
        if region[i] > region[i - 1] and region[i] >= region[i + 1] and region[i] > 0.1:
            best = i
            break
    if best is None:
        best = int(np.argmax(region))
    lag = best + min_lag
    # Parabolic interpolation
    if 0 < best < len(region) - 1:
        a0, a1, a2 = region[best - 1], region[best], region[best + 1]
        denom = a0 - 2 * a1 + a2
        if denom != 0:
            offset = 0.5 * (a0 - a2) / denom
            lag = lag + offset
    if lag <= 0:
        return None
    f = sr / lag
    m = freq_to_midi(f)
    return float(m) if m is not None else None


def detect_hps(audio, sr, harmonics=5):
    """Harmonic Product Spectrum."""
    seg = _sustain_segment(audio, sr)
    if seg is None:
        return None
    seg = seg * np.hanning(len(seg))
    n = len(seg)
    spec = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    min_bin = max(1, int(np.searchsorted(freqs, 20)))
    max_bin = min(len(spec), int(np.searchsorted(freqs, 8400)))
    cropped = spec[: (max_bin // harmonics) + 1]
    for h in range(2, harmonics + 1):
        down = spec[::h][: len(cropped)]
        cropped = cropped * down
    if cropped.size == 0:
        return None
    valid = cropped[min_bin:]
    if valid.size == 0:
        return None
    peak = int(np.argmax(valid)) + min_bin
    f = freqs[peak]
    # Parabolic interpolation in original spectrum
    if 0 < peak < len(spec) - 1:
        a0, a1, a2 = spec[peak - 1], spec[peak], spec[peak + 1]
        denom = a0 - 2 * a1 + a2
        if denom != 0:
            offset = 0.5 * (a0 - a2) / denom
            f = freqs[peak] + offset * (freqs[1] - freqs[0])
    m = freq_to_midi(f)
    return float(m) if m is not None else None


def detect_fft_lowest(audio, sr):
    seg = _sustain_segment(audio, sr)
    if seg is None:
        return None
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
    best_idx = None
    for idx in valid_indices:
        if 0 < idx < len(spec) - 1:
            if spec[idx] >= spec[idx - 1] and spec[idx] >= spec[idx + 1] and spec[idx] >= threshold:
                best_idx = idx
                break
    if best_idx is None:
        best_idx = int(valid_indices[np.argmax(spec[valid_indices])])
    f = freqs[best_idx]
    if 0 < best_idx < len(freqs) - 1:
        a0, a1, a2 = spec[best_idx - 1], spec[best_idx], spec[best_idx + 1]
        denom = a0 - 2 * a1 + a2
        if denom != 0:
            offset = 0.5 * (a0 - a2) / denom
            f = freqs[best_idx] + offset * (freqs[1] - freqs[0])
    m = freq_to_midi(f)
    return float(m) if m is not None else None


def detect_fft_loudest(audio, sr):
    seg = _sustain_segment(audio, sr)
    if seg is None:
        return None
    seg = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
    valid = (freqs >= 20) & (freqs <= 8400)
    masked = spec.copy()
    masked[~valid] = 0
    best_idx = int(np.argmax(masked))
    if masked[best_idx] <= 0:
        return None
    f = freqs[best_idx]
    if 0 < best_idx < len(spec) - 1:
        a0, a1, a2 = spec[best_idx - 1], spec[best_idx], spec[best_idx + 1]
        denom = a0 - 2 * a1 + a2
        if denom != 0:
            offset = 0.5 * (a0 - a2) / denom
            f = freqs[best_idx] + offset * (freqs[1] - freqs[0])
    m = freq_to_midi(f)
    return float(m) if m is not None else None


def analyze_one(path):
    fname = os.path.basename(path)
    m = NOTE_RE.match(fname)
    if not m:
        return None
    prog = int(m.group(1))
    requested = note_name_to_midi(m.group(2))
    if requested is None:
        return None
    vel = int(m.group(3))
    try:
        audio, sr = sf.read(path)
    except Exception:
        return None
    if audio.ndim == 1:
        audio = np.column_stack((audio, audio))
    acf = detect_acf(audio, sr)
    hps = detect_hps(audio, sr)
    f_low = detect_fft_lowest(audio, sr)
    f_loud = detect_fft_loudest(audio, sr)

    def off(det):
        return None if det is None else det - requested

    return {
        "file": fname,
        "prog": prog,
        "vel": vel,
        "requested": requested,
        "acf": acf,
        "hps": hps,
        "fft_low": f_low,
        "fft_loud": f_loud,
        "off_acf": off(acf),
        "off_hps": off(hps),
        "off_fft_low": off(f_low),
        "off_fft_loud": off(f_loud),
    }


def consensus_offset(rec):
    """Return (consensus_offset_semitones, agreement_label).

    agreement_label ∈ {match, octave_shift, ambiguous, none}
    """
    offs = [v for v in (rec["off_acf"], rec["off_hps"], rec["off_fft_low"], rec["off_fft_loud"]) if v is not None]
    if not offs:
        return None, "none"
    rounded = [int(round(o)) for o in offs]
    # If all methods agree within 1 semitone
    if max(offs) - min(offs) <= 1.0:
        return np.median(offs), "match"
    # If all methods agree on an integer (octave) within 1 semitone
    if max(rounded) - min(rounded) <= 1:
        return float(np.median(rounded)), "octave_shift"
    return None, "ambiguous"


def main():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=os.path.join(_root, "General_MIDI_samples_raw"))
    parser.add_argument("--csv", default=os.path.join(_root, "data", "audit_pitch.csv"))
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--max-offset", type=float, default=0.5,
                        help="Threshold (semitones) above which an offset is flagged as wrong")
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(args.input, "gm_*_v*.wav")))
    if not files:
        print(f"No GM samples found in {args.input}", file=sys.stderr)
        sys.exit(1)
    print(f"Auditing {len(files)} samples with 4 detectors...")

    records = []
    completed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(analyze_one, p): p for p in files}
        for fut in as_completed(futures):
            rec = fut.result()
            if rec:
                records.append(rec)
            completed += 1
            if completed % 256 == 0 or completed == len(files):
                print(f"  [{completed}/{len(files)}]")

    records.sort(key=lambda r: (r["prog"], r["requested"], r["vel"]))

    with open(args.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "prog", "requested", "vel",
                    "acf", "hps", "fft_low", "fft_loud",
                    "off_acf", "off_hps", "off_fft_low", "off_fft_loud",
                    "consensus_offset", "agreement"])
        for r in records:
            co, ag = consensus_offset(r)
            w.writerow([r["file"], r["prog"], r["requested"], r["vel"],
                        r["acf"], r["hps"], r["fft_low"], r["fft_loud"],
                        r["off_acf"], r["off_hps"], r["off_fft_low"], r["off_fft_loud"],
                        co if co is not None else "", ag])

    # Summary statistics
    by_agree = {}
    flagged = []
    for r in records:
        co, ag = consensus_offset(r)
        by_agree[ag] = by_agree.get(ag, 0) + 1
        if co is not None and abs(co) > args.max_offset and abs(co - round(co / 12) * 12) > 0.5:
            flagged.append((r, co))

    total = len(records)
    print("\n=== AGGREGATE AGREEMENT ===")
    for ag in ("match", "octave_shift", "ambiguous", "none"):
        n = by_agree.get(ag, 0)
        print(f"  {ag:14s}: {n:5d} ({100*n/total:5.1f}%)")

    print(f"\n=== NON-OCTAVE OUTLIERS (offset > {args.max_offset} st, not near 12k) ===")
    print(f"  Total: {len(flagged)} / {total}")
    if flagged:
        print(f"  {'prog':>4} {'vel':>4} {'req':>4}  {'ACF':>6} {'HPS':>6} {'FFTL':>6} {'FFTU':>6}  consensus  file")
        for r, co in flagged[:80]:
            def fmt(x):
                return f"{x:+.1f}" if x is not None else "  -  "
            print(f"  {r['prog']:4d} {r['vel']:4d} {midi_to_name(r['requested']):>4}  "
                  f"{fmt(r['off_acf']):>6} {fmt(r['off_hps']):>6} "
                  f"{fmt(r['off_fft_low']):>6} {fmt(r['off_fft_loud']):>6}  {co:+.1f}  {r['file']}")

    print(f"\nCSV written to {args.csv}")


if __name__ == "__main__":
    main()
