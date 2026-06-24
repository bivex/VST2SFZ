#!/usr/bin/env python3
"""
Build Dharma.sfz from the KSHMR Vol.5 Complete Edition sample library.

The library is NOT a chromatic multisample (like Dexed/DX7) — it is a one-shot
+ loop construction kit where every pitched one-shot carries its musical root
in the filename:

    one-shot : "KSHMR Trumpet - Staccato - Jab (B).wav"      -> root = B
    loop     : "KSHMR Bass Loop (125, C) - Clean Eighths.wav" -> tempo phrase

So there is nothing to *render*; the job is to scan, classify and write SFZ.

Architecture (chosen): instrument-per-program.
  * Each (instrument folder, articulation) becomes one playable program.
  * One-shots are stretched CHROMATICALLY around their parsed root note —
    key zones are built from the midpoints between neighbouring sampled roots,
    so the whole keyboard plays and each key picks its nearest-root sample.
  * Several samples sharing one root -> round-robin (seq_length/seq_position).
  * Loops (tempo number in the key token) are EXCLUDED — they are phrases,
    not instruments.
  * A GM drum kit (reused from kshmr_drum_mapping) is appended.

Outputs (matching the repo's Dexed/GM convention):
  Dharma.sfz              master bank, prg_num + relative paths, drums embedded
  Dharma_sfizz.sfz        loprog/hiprog + absolute paths, NO embedded drums
                          (the pysfizz consumer ignores lochan=10, so an
                          embedded drum block would leak onto melodic notes)
  Dharma_sfizz_drums.sfz  standalone GM kit for a separate sfizz drum synth

Run:  python build_dharma_sfz.py            (build everything)
      python build_dharma_sfz.py --report   (scan + print plan, write nothing)
"""

import os
import re
import sys
import glob
from collections import defaultdict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = "/Volumes/External/Samples/Dharma Studio - Sounds of KSHMR Vol.5 Complete Edition"
OUT_DIR = "/Volumes/External/Code/VST2SFZ"
MASTER = os.path.join(OUT_DIR, "Dharma.sfz")
SFIZZ = os.path.join(OUT_DIR, "Dharma_sfizz.sfz")
SFIZZ_DRUMS = os.path.join(OUT_DIR, "Dharma_sfizz_drums.sfz")

# Folders to harvest pitched one-shots from. Loops/fills/FX/vocals/drums are
# deliberately excluded — drums come from the GM kit, the rest are phrases.
ONESHOT_GLOBS = [
    "Instruments/**/*.wav",
    "Synths/SYNTH - One Shots/**/*.wav",
    "Synths/BASS - One Shots/**/*.wav",
]

NOTE_MAP = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}
FLAT_TO_SHARP = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "Cb": "B", "Fb": "E",
}
# Root octave for the parsed pitch class. KSHMR roots have no octave in the
# name; C4=60 is a sensible playable centre.
ROOT_OCTAVE_MIDI = 60  # C4


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------
_KEY_RE = re.compile(r"\(([^)]*)\)")


def parse_root(filename):
    """Return (midi_root, is_loop) or (None, is_loop).

    A loop has a tempo number in the key token: "(125, C#m)".
    A one-shot has just a pitch class: "(C)", "(Am)", "(F#)".
    """
    name = os.path.basename(filename)
    is_loop = False
    for token in _KEY_RE.findall(name):
        token = token.strip()
        has_bpm = bool(re.match(r"^\d", token))
        if has_bpm:
            is_loop = True
            # tempo,key form -> take part after comma
            parts = token.split(",")
            if len(parts) < 2:
                continue
            token = parts[1].strip()
        # token now like "C", "Am", "F#m", "D#"
        m = re.match(r"^([A-G][#b]?)\s*(m|maj|min|major|minor)?$", token)
        if not m:
            continue
        note = m.group(1)
        note = FLAT_TO_SHARP.get(note, note)
        pc = NOTE_MAP.get(note)
        if pc is None:
            continue
        return ROOT_OCTAVE_MIDI - (ROOT_OCTAVE_MIDI % 12) + pc, is_loop
    return None, is_loop


# Instrument label per source folder. Longest match wins.
FOLDER_LABELS = [
    ("Instruments/Brass/Trumpets", "Trumpet"),
    ("Instruments/Brass/Orchestral Brass", "Orch Brass"),
    ("Instruments/Brass", "Brass"),
    ("Instruments/Winds/Flute", "Flute"),
    ("Instruments/Winds/Sax", "Sax"),
    ("Instruments/Winds/Duduk", "Duduk"),
    ("Instruments/Winds/Shehnai", "Shehnai"),
    ("Instruments/Winds/Didgeridoo", "Didgeridoo"),
    ("Instruments/Winds", "Winds"),
    ("Instruments/Strings", "Strings"),
    ("Instruments/Guitar", "Guitar"),
    ("Instruments/Bass", "Bass"),
    ("Instruments/Keys", "Keys"),
    ("Synths/SYNTH - One Shots/SYNTH - Plucks", "Synth Pluck"),
    ("Synths/SYNTH - One Shots/SYNTH - Stabs", "Synth Stab"),
    ("Synths/SYNTH - One Shots/SYNTH - Energizers", "Synth Energizer"),
    ("Synths/SYNTH - One Shots/SYNTH - Screeches", "Synth Screech"),
    ("Synths/BASS - One Shots/Bass Shots - Hits", "Synth Bass Hit"),
    ("Synths/BASS - One Shots/Bass Shots - Plucks", "Synth Bass Pluck"),
    ("Synths/BASS - One Shots/Bass Shots - Whomp", "Synth Bass Whomp"),
    ("Synths/BASS - One Shots/Bass Shots - Scream", "Synth Bass Scream"),
]


def folder_label(path):
    rel = os.path.relpath(path, BASE)
    best = None
    for prefix, label in FOLDER_LABELS:
        if rel.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), label)
    return best[1] if best else None


def articulation(filename, label):
    """Second ' - ' token of the descriptive name, or '' for synths.

    "KSHMR Trumpet - Staccato - Jab (B)"  -> "Staccato"
    "KSHMR Pluck - Pinch (C)"             -> ""  (folder label is enough)
    """
    name = os.path.basename(filename)
    name = re.sub(r"\.wav$", "", name, flags=re.I)
    name = re.sub(r"\s*\([^)]*\)", "", name)  # drop ALL key tokens (can be mid-name)
    name = re.sub(r"^KSHMR\s+", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    parts = [p.strip() for p in name.split(" - ")]
    if len(parts) >= 3:
        return parts[1]
    return ""


# Articulations that are not chromatically playable (gestures / fx). They get
# their own program but are key-locked (no stretch) so they don't smear.
GESTURE_ARTICS = {
    "fall", "rise", "run up", "run", "slide", "fx", "ambient fx",
    "crescendo growl", "reverse", "screech", "drift",
    # multi-note phrases: the parsed key is the phrase's TONALITY, not a single
    # playable pitch — stretching them chromatically smears the phrase, so they
    # are key-locked just like loops. (Confirmed by pitch audit: ~46% root match
    # vs ~82% for true single-note one-shots.)
    "lick", "strum",
}

# Phrase keywords (whole-word match anywhere in the filename, not just the
# articulation slot), e.g. "String Run", "Violin Cascade", "Pentatonic Flow".
# Whole-word matching avoids substring false positives ("Flicker" != "lick").
PHRASE_KEYWORDS = (
    "lick", "run", "cascade", "flow", "rush", "dash", "swift",
    "pentatonic", "arpeggio", "glissando", "riff",
)
_PHRASE_RE = re.compile(
    r"\b(" + "|".join(PHRASE_KEYWORDS) + r")\b", re.IGNORECASE
)

# Pitch-glide gestures: the parsed key is a start/end point of a glide, not a
# steady pitch, so they must be key-locked. These appear mid-filename with an
# empty articulation slot (e.g. "KSHMR Bass Slide (C) - Fall").
GLIDE_KEYWORDS = (
    "slide", "glide", "fall", "dive", "swoop", "plunge", "scoop", "bend",
)
_GLIDE_RE = re.compile(
    r"\b(" + "|".join(GLIDE_KEYWORDS) + r")\b", re.IGNORECASE
)

# Inherently atonal instruments — no stable fundamental, so chromatic stretch
# is meaningless; play each sample on its own key.
ATONAL_KEYWORDS = ("whistle",)
_ATONAL_RE = re.compile(
    r"\b(" + "|".join(ATONAL_KEYWORDS) + r")\b", re.IGNORECASE
)


def is_gesture(artic, label, filename=""):
    a = artic.lower()
    if a in GESTURE_ARTICS:
        return True
    if "screech" in label.lower():
        return True
    fn = os.path.basename(filename).lower()
    if _PHRASE_RE.search(fn) or _GLIDE_RE.search(fn) or _ATONAL_RE.search(fn):
        return True
    return False


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------
def scan():
    """Return {program_name: [(root_midi, abspath, gesture_bool), ...]}."""
    patches = defaultdict(list)
    seen = set()
    stats = {"loops": 0, "no_key": 0, "kept": 0, "no_label": 0}
    for pat in ONESHOT_GLOBS:
        for f in glob.glob(os.path.join(BASE, pat), recursive=True):
            if f in seen:
                continue
            seen.add(f)
            root, is_loop = parse_root(f)
            if is_loop:
                stats["loops"] += 1
                continue
            if root is None:
                stats["no_key"] += 1
                continue
            label = folder_label(f)
            if not label:
                stats["no_label"] += 1
                continue
            artic = articulation(f, label)
            gesture = is_gesture(artic, label, f)
            prog_name = f"{label} {artic}".strip() if artic else label
            patches[prog_name].append((root, f, gesture))
            stats["kept"] += 1
    return patches, stats


# ---------------------------------------------------------------------------
# Zone building
# ---------------------------------------------------------------------------
def build_zones(samples):
    """samples: [(root, path, gesture)] -> list of zone dicts.

    Chromatic stretch: sort unique roots, key boundaries = midpoints between
    neighbouring roots. Samples sharing a root become a round-robin group.
    Gesture patches are key-locked (lokey=hikey=root).
    """
    gesture = any(g for _, _, g in samples)
    by_root = defaultdict(list)
    for root, path, _ in samples:
        by_root[root].append(path)
    roots = sorted(by_root)

    zones = []
    if gesture:
        # key-locked: each root on its own key, round-robin variants
        for root in roots:
            paths = by_root[root]
            zones.append({
                "lokey": root, "hikey": root, "keycenter": root, "paths": paths,
            })
        return zones

    for i, root in enumerate(roots):
        lo = 0 if i == 0 else (roots[i - 1] + root) // 2 + 1
        hi = 127 if i == len(roots) - 1 else (root + roots[i + 1]) // 2
        zones.append({
            "lokey": lo, "hikey": hi, "keycenter": root, "paths": by_root[root],
        })
    return zones


def zone_regions(zone, sample_ref):
    """Emit <region> lines for one zone (round-robin if >1 sample)."""
    paths = zone["paths"]
    n = len(paths)
    lines = []
    for i, p in enumerate(paths, 1):
        rr = "" if n == 1 else f" seq_length={n} seq_position={i}"
        lines.append(
            f"<region> sample={sample_ref(p)} pitch_keycenter={zone['keycenter']} "
            f"lokey={zone['lokey']} hikey={zone['hikey']} lovel=0 hivel=127{rr}"
        )
    return lines


# ---------------------------------------------------------------------------
# Drum kit (reused from kshmr_drum_mapping)
# ---------------------------------------------------------------------------
def load_drum_map():
    sys.path.insert(0, OUT_DIR)
    from kshmr_drum_mapping import GM_TO_KSHMR, GM_DRUM_NAMES, KSHMR
    kit = {}
    for note, (soft, loud) in GM_TO_KSHMR.items():
        s = os.path.join(KSHMR, soft)
        l = os.path.join(KSHMR, loud)
        if os.path.exists(s) and os.path.exists(l):
            kit[note] = (s, l, GM_DRUM_NAMES.get(note, f"N{note}"))
    return kit


def drum_lines(kit, sample_ref, lochan=None):
    lines = []
    chan = f" lochan=10 hichan=10" if lochan else ""
    for note in sorted(kit):
        s, l, name = kit[note]
        lines.append(f"// {note} — {name}")
        lines.append(
            f"<region> sample={sample_ref(s)} lokey={note} hikey={note} "
            f"lovel=0 hivel=80{chan}"
        )
        lines.append(
            f"<region> sample={sample_ref(l)} lokey={note} hikey={note} "
            f"lovel=81 hivel=127{chan}"
        )
    return lines


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def assign_programs(patches):
    """Sort patches into a stable, musical order and assign program numbers."""
    names = sorted(patches.keys())
    return {name: i for i, name in enumerate(names)}


def write_master(patches, progmap, kit):
    rel = lambda p: os.path.relpath(p, OUT_DIR).replace("\\", "/")
    out = [
        "// Dharma.sfz — KSHMR Vol.5 Complete Edition",
        "// Instrument-per-program one-shot construction kit.",
        f"// {len(progmap)} melodic programs + GM drum kit (prog as channel 10).",
        "",
    ]
    for name in sorted(progmap, key=lambda n: progmap[n]):
        prog = progmap[name]
        out.append(f"<group>")
        out.append(f"prg_num={prog} // {name}")
        for zone in build_zones(patches[name]):
            out += zone_regions(zone, rel)
        out.append("")
    if kit:
        out.append("// ─── GM Drum Kit (channel 10) ───")
        out.append("<group>")
        out.append("ampeg_attack=0.001 ampeg_release=0.05")
        out += drum_lines(kit, rel, lochan=True)
        out.append("")
    with open(MASTER, "w") as f:
        f.write("\n".join(out))
    return MASTER


def write_sfizz(patches, progmap):
    absref = lambda p: p
    out = [
        "// Dharma_sfizz.sfz — KSHMR Vol.5 (sfizz consumer, absolute paths)",
        "// loprog/hiprog program switching. NO embedded drums "
        "(use Dharma_sfizz_drums.sfz in a separate synth).",
        "",
    ]
    for name in sorted(progmap, key=lambda n: progmap[n]):
        prog = progmap[name]
        out.append("<group>")
        out.append(f"loprog={prog} hiprog={prog} // {name}")
        for zone in build_zones(patches[name]):
            out += zone_regions(zone, absref)
        out.append("")
    with open(SFIZZ, "w") as f:
        f.write("\n".join(out))
    return SFIZZ


def write_sfizz_drums(kit):
    absref = lambda p: p
    out = [
        "// Dharma_sfizz_drums.sfz — GM kit (KSHMR Vol.5), standalone for sfizz",
        "// 2 velocity layers per note (soft ≠ loud).",
        "<group>",
        "ampeg_attack=0.001 ampeg_release=0.05",
        "",
    ]
    out += drum_lines(kit, absref, lochan=None)
    with open(SFIZZ_DRUMS, "w") as f:
        f.write("\n".join(out))
    return SFIZZ_DRUMS


# ---------------------------------------------------------------------------
def main():
    report_only = "--report" in sys.argv
    patches, stats = scan()
    progmap = assign_programs(patches)

    print("=== Scan ===")
    print(f"  kept one-shots : {stats['kept']}")
    print(f"  loops skipped  : {stats['loops']}")
    print(f"  no key skipped : {stats['no_key']}")
    print(f"  no label       : {stats['no_label']}")
    print(f"  programs       : {len(progmap)}")
    print("\n=== Programs ===")
    for name in sorted(progmap, key=lambda n: progmap[n]):
        smp = patches[name]
        roots = sorted({r for r, _, _ in smp})
        gest = " [gesture/key-locked]" if any(g for _, _, g in smp) else ""
        print(f"  {progmap[name]:>3}  {name:<22} {len(smp):>3} smp, "
              f"{len(roots)} roots{gest}")

    if len(progmap) > 128:
        print(f"\n!! {len(progmap)} programs > 128 — needs bank select. Adjust grouping.")

    if report_only:
        print("\n(report only, no files written)")
        return

    kit = load_drum_map()
    m = write_master(patches, progmap, kit)
    s = write_sfizz(patches, progmap)
    d = write_sfizz_drums(kit)
    print(f"\n=== Written ===")
    for p in (m, s, d):
        n = open(p).read().count("<region>")
        print(f"  {p}  ({n} regions)")
    print(f"  drum notes: {len(kit)}")


if __name__ == "__main__":
    main()
