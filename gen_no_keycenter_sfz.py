#!/usr/bin/env python3
"""
Generate a "no detected pitch_keycenter" variant of any GM SFZ.

For every region, replace the detected pitch_keycenter with the note that was
*requested* at sample time (parsed from the sample filename: gm_NNN_<NOTE>_v<VEL>.wav).

When sfizz loads the result, it treats each sample as if it actually plays the
requested note — i.e. no preset-transpose compensation. This is the A/B
baseline to compare against the detected-keycenter SFZ.

Usage:
    python gen_no_keycenter_sfz.py <input.sfz> <output.sfz>

Env override for restarter.sh:
    PITCH_CENTER_IGNORE=1   -> generates the no-keycenter variant on the fly
                               and points BIRKA_SFZ at it.

When PITCH_CENTER_IGNORE is set, calling this script with no arguments (or
via the wrapper) regenerates the *_nokeycentered.sfz next to the input.
"""

import os
import re
import sys

NOTE_LETTERS = ["c", "cs", "d", "ds", "e", "f", "fs", "g", "gs", "a", "as", "b"]


def name_to_midi(name):
    """'C4' -> 60, 'Cs5' -> 73, 'A0' -> 21."""
    m = re.match(r"([A-G])(s?)(-?\d+)$", name)
    if not m:
        return None
    key = (m.group(1) + m.group(2)).lower()
    if key not in NOTE_LETTERS:
        return None
    octave = int(m.group(3))
    return NOTE_LETTERS.index(key) + (octave + 1) * 12


def replace_keycenter(input_sfz, output_sfz):
    """Rewrite each region so pitch_keycenter equals the requested note."""
    fname_re = re.compile(r"gm_\d{3}_([A-G]s?\d+)_v\d+\.wav")
    region_re = re.compile(r"(<region>.*?)(pitch_keycenter=)(\d+)(.*?)(sample=[^ ]+)")

    changed = total = 0
    out_lines = []
    with open(input_sfz) as f:
        for line in f:
            if "<region>" in line:
                total += 1
                # Find sample filename first to know the requested note
                m_sample = fname_re.search(line)
                if m_sample:
                    requested = name_to_midi(m_sample.group(1))
                    if requested is not None:
                        line = re.sub(
                            r"pitch_keycenter=\d+",
                            f"pitch_keycenter={requested}",
                            line,
                        )
                        changed += 1
            out_lines.append(line)

    with open(output_sfz, "w") as f:
        f.writelines(out_lines)

    print(f"[gen_no_keycenter] {input_sfz}")
    print(f"  -> {output_sfz}")
    print(f"  regions: {total}, pitch_keycenter reset to requested note: {changed}")
    return changed


def main():
    if len(sys.argv) == 3:
        replace_keycenter(sys.argv[1], sys.argv[2])
        return

    # Default behaviour: regenerate the *_nokeycentered.sfz variants
    targets = [
        ("General_MIDI_sfizz_processed.sfz",
         "General_MIDI_sfizz_processed_nokeycentered.sfz"),
        ("General_MIDI_sfizz.sfz",
         "General_MIDI_sfizz_nokeycentered.sfz"),
        ("General_MIDI.sfz",
         "General_MIDI_nokeycentered.sfz"),
    ]
    for src, dst in targets:
        if os.path.exists(src):
            replace_keycenter(src, dst)


if __name__ == "__main__":
    main()
