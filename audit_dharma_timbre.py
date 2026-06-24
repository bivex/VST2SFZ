#!/usr/bin/env python3
"""
Timbre/pitch audit for Dharma.sfz one-shots.

For every pitched one-shot the builder kept, detect the real fundamental with
three independent detectors (ACF / HPS / FFT-lowest, reused from audit_pitch.py)
and compare against the root parsed from the filename. The KSHMR roots carry no
octave, so we compare PITCH CLASS (mod 12) and take the detector consensus.

A sample "matches its instrument" when its detected pitch class agrees with the
filename root (within tolerance). Per-program match rate tells us whether a
program is genuinely tonal (safe to stretch chromatically) or noisy/atonal
(better key-locked).

Run:  python audit_dharma_timbre.py
      python audit_dharma_timbre.py --csv dharma_pitch.csv
"""

import os
import re
import sys
import csv
import argparse
import numpy as np
import soundfile as sf
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_pitch import detect_acf, detect_hps, detect_fft_lowest  # noqa: E402
from build_dharma_sfz import (  # noqa: E402
    scan, parse_root, folder_label, articulation, is_gesture,
)

PC = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def pc_distance(a, b):
    """Circular distance between two pitch classes (0..6 semitones)."""
    d = abs((a - b) % 12)
    return min(d, 12 - d)


def analyse(path, root_midi):
    try:
        audio, sr = sf.read(path, dtype="float32")
    except Exception:
        return None
    root_pc = root_midi % 12
    ests = []
    for fn in (detect_acf, detect_hps, detect_fft_lowest):
        try:
            m = fn(audio, sr)
        except Exception:
            m = None
        if m is not None:
            ests.append(round(m) % 12)
    if not ests:
        return (path, root_pc, None, None, None)
    # consensus = pitch class minimising total circular distance to estimates
    best_pc, best_cost = None, 1e9
    for cand in range(12):
        cost = sum(pc_distance(cand, e) for e in ests)
        if cost < best_cost:
            best_cost, best_pc = cost, cand
    dist = pc_distance(best_pc, root_pc)
    # agreement among detectors (how tight the cluster is)
    spread = max(pc_distance(e, best_pc) for e in ests) if len(ests) > 1 else 0
    return (path, root_pc, best_pc, dist, spread)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    patches, _ = scan()
    jobs = []  # (prog_name, root_midi, path, gesture)
    for name, samples in patches.items():
        for root, path, gesture in samples:
            jobs.append((name, root, path, gesture))

    print(f"Auditing {len(jobs)} samples across {len(patches)} programs...\n")

    results = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(analyse, p, r): (n, p, g)
                for (n, r, p, g) in jobs}
        for fut in as_completed(futs):
            n, p, g = futs[fut]
            res = fut.result()
            if res:
                results[p] = (n, g, res)

    # aggregate per program
    per_prog = defaultdict(lambda: {"n": 0, "match": 0, "off": 0, "nopitch": 0,
                                    "gesture": False, "offsets": []})
    rows = []
    TOL = 1  # semitone tolerance (pitch-class)
    for path, (name, gesture, res) in results.items():
        _, root_pc, det_pc, dist, spread = res
        d = per_prog[name]
        d["n"] += 1
        d["gesture"] = d["gesture"] or gesture
        if det_pc is None:
            d["nopitch"] += 1
        elif dist <= TOL:
            d["match"] += 1
        else:
            d["off"] += 1
            d["offsets"].append(dist)
        rows.append([name, os.path.basename(path), PC[root_pc],
                     PC[det_pc] if det_pc is not None else "?",
                     "" if dist is None else dist,
                     "" if spread is None else spread,
                     "gesture" if gesture else ""])

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["program", "file", "root", "detected", "dist_st",
                        "detector_spread", "kind"])
            w.writerows(sorted(rows))
        print(f"Wrote {args.csv}\n")

    # report
    print(f"{'program':<24} {'n':>3} {'match%':>6} {'off':>4} "
          f"{'noP':>4}  verdict")
    print("-" * 64)
    tot_n = tot_m = 0
    flags = []
    for name in sorted(per_prog):
        d = per_prog[name]
        n = d["n"]
        tonal_n = n - d["nopitch"]
        rate = (100.0 * d["match"] / tonal_n) if tonal_n else 0.0
        if not d["gesture"]:
            tot_n += tonal_n
            tot_m += d["match"]
        if d["gesture"]:
            verdict = "gesture (key-locked, pitch N/A)"
        elif tonal_n == 0:
            verdict = "ATONAL — no pitch detected"
            flags.append((name, "atonal"))
        elif rate >= 70:
            verdict = "OK tonal"
        elif rate >= 40:
            verdict = "MIXED — check"
            flags.append((name, "mixed"))
        else:
            verdict = "POOR — likely atonal/mislabelled"
            flags.append((name, "poor"))
        print(f"{name:<24} {n:>3} {rate:>5.0f}% {d['off']:>4} "
              f"{d['nopitch']:>4}  {verdict}")

    overall = (100.0 * tot_m / tot_n) if tot_n else 0
    print("-" * 64)
    print(f"Overall tonal match (non-gesture): {tot_m}/{tot_n} = {overall:.0f}%")

    if flags:
        print(f"\n{len(flags)} programs flagged:")
        for name, why in flags:
            print(f"  [{why}] {name}")


if __name__ == "__main__":
    main()
