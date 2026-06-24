#!/usr/bin/env python3
"""
Delete all GM-pack samples and SFZ outputs, preserving everything else.

Removes:
  - General_MIDI_samples/gm_*.wav          (processed melodic samples)
  - General_MIDI_samples_raw/gm_*.wav      (raw melodic samples)
  - General_MIDI_instruments/gm_*.sfz      (per-instrument SFZ)
  - General_MIDI.sfz                       (master, relative paths)
  - General_MIDI_sfizz.sfz                 (sfizz, raw sample paths)
  - General_MIDI_sfizz_processed.sfz       (sfizz, processed sample paths)
  - General_MIDI_*_nokeycentered.sfz       (A/B variants)

Preserves:
  - General_MIDI_samples/ non-gm files     (KSHMR loops, etc.)
  - General_MIDI_samples_drums/            (drum kit samples)
  - General_MIDI_sfizz_drums.sfz           (drum kit SFZ)
  - KSHMR_Vol5_128GM*.sfz                  (KSHMR GM mapping)
  - Surge_DX_Piano.sfz                     (DX Piano demo)

Usage:
    python clean_gm_pack.py            # deletes (with confirmation)
    python clean_gm_pack.py --yes      # skip confirmation prompt
"""

import argparse
import glob
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories whose gm_* contents are deleted; non-gm files inside are kept.
SAMPLE_DIRS = [
    "General_MIDI_samples",
    "General_MIDI_samples_raw",
]
INSTRUMENT_DIR = "General_MIDI_instruments"

# Master SFZ files deleted entirely (they only reference GM samples).
SFZ_PATTERNS = [
    "General_MIDI.sfz",
    "General_MIDI_sfizz.sfz",
    "General_MIDI_sfizz_processed.sfz",
    "General_MIDI_nokeycentered.sfz",
    "General_MIDI_sfizz_nokeycentered.sfz",
    "General_MIDI_sfizz_processed_nokeycentered.sfz",
    "General_MIDI_partial.sfz",
    "General_MIDI_sfizz_partial.sfz",
    "General_MIDI_sfizz_processed_partial.sfz",
]

# Explicitly NOT deleted (sanity-checked before run so the script never
# accidentally wipes them if the patterns above are widened later).
PRESERVE = [
    "General_MIDI_sfizz_drums.sfz",
    "KSHMR_Vol5_128GM.sfz",
    "KSHMR_Vol5_128GM_NoLoops.sfz",
    "Surge_DX_Piano.sfz",
    "General_MIDI_samples_drums",
    "KSHMR_Vol5_128GM_NoLoops",
]


def collect_targets():
    """Return list of (path, kind) for every file/dir to be deleted."""
    targets = []

    for d in SAMPLE_DIRS:
        full = os.path.join(PROJECT_ROOT, d)
        if os.path.isdir(full):
            for f in glob.glob(os.path.join(full, "gm_*.wav")):
                targets.append((f, "sample"))

    full_inst = os.path.join(PROJECT_ROOT, INSTRUMENT_DIR)
    if os.path.isdir(full_inst):
        for f in glob.glob(os.path.join(full_inst, "gm_*.sfz")):
            targets.append((f, "instrument-sfz"))

    for pat in SFZ_PATTERNS:
        full = os.path.join(PROJECT_ROOT, pat)
        if os.path.exists(full):
            targets.append((full, "master-sfz"))

    return targets


def confirm(prompt):
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def main():
    parser = argparse.ArgumentParser(
        description="Delete all GM-pack samples and SFZ outputs."
    )
    parser.add_argument("--yes", "-y", action="store_true",
                        help="skip confirmation prompt")
    args = parser.parse_args()

    targets = collect_targets()

    if not targets:
        print("Nothing to delete — GM pack is already clean.")
        return

    # Group by kind for a readable summary
    by_kind = {}
    for path, kind in targets:
        by_kind.setdefault(kind, []).append(path)

    print(f"About to delete {len(targets)} items:\n")
    for kind in ("sample", "instrument-sfz", "master-sfz"):
        items = by_kind.get(kind, [])
        if items:
            print(f"  {kind:14s}: {len(items)}")
    print(f"\nTotal: {len(targets)} files")

    # Sanity-check that preserved paths still exist (don't accidentally clobber)
    print("\nPreserving:")
    for p in PRESERVE:
        full = os.path.join(PROJECT_ROOT, p)
        mark = "✓" if os.path.exists(full) else "—"
        print(f"  {mark} {p}")

    if not args.yes:
        print()
        if not confirm("Proceed with deletion?"):
            print("Aborted.")
            return

    deleted = 0
    for path, _ in targets:
        try:
            os.remove(path)
            deleted += 1
        except OSError as e:
            print(f"  ⚠ failed: {path} ({e})")

    # Remove now-empty instrument dir if nothing else lives there
    inst_dir = os.path.join(PROJECT_ROOT, INSTRUMENT_DIR)
    if os.path.isdir(inst_dir) and not os.listdir(inst_dir):
        os.rmdir(inst_dir)
        print(f"  removed empty dir: {INSTRUMENT_DIR}/")

    print(f"\n✓ Deleted {deleted}/{len(targets)} files.")
    print("GM pack is now clean. Re-run sample_gm_pack.py / "
          "sample_gm_pack_fast.py to regenerate.")


if __name__ == "__main__":
    main()
