#!/usr/bin/env python3
"""
Map the 28 missing standard GM drum notes (35-81) to KSHMR Vol.5 one-shots,
copy the chosen samples into General_MIDI_samples_drums/, and REBUILD
General_MIDI_sfizz_drums.sfz directly from the files on disk (so every
gm_drum_N<note>_v<vel>.wav present becomes a region — robust against any
prior SFZ state).
"""

import os
import re
import shutil
import glob

ORIG = "/Volumes/External/Samples/Dharma Studio - Sounds of KSHMR Vol.5 Complete Edition"
DRUM_DIR = "/Volumes/External/Code/VST2SFZ/General_MIDI_samples_drums"
SFZ_PATH = "/Volumes/External/Code/VST2SFZ/General_MIDI_sfizz_drums.sfz"

# GM drum note -> KSHMR sample relative path under ORIG.
GM_TO_KSHMR = {
    39: "Drums/Claps/Main/KSHMR Main Clap - Mid - Snap.wav",            # Hand Clap
    52: "Drums/Cymbals/Crashes/KSHMR Crash - Acoustic - Classic Kit.wav", # Chinese Cymbal
    54: "Drums/Percussion/Tops - Tambourine/KSHMR Tambourine - Hit - Twinkle.wav",  # Tambourine
    56: "Drums/Percussion/Hand Drums/Bells/KSHMR Bell - Cowbell (E).wav", # Cowbell
    58: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Rattle (C).wav",  # Vibraslap
    59: "Drums/Cymbals/Rides/KSHMR Ride - Classic - Classic.wav",         # Ride Cymbal 2
    60: "Drums/Percussion/Hand Drums/Bongos/KSHMR Bongo - Closed - Bright.wav",  # High Bongo
    61: "Drums/Percussion/Hand Drums/Bongos/KSHMR Bongo - Closed - Low.wav",     # Low Bongo
    62: "Drums/Percussion/Hand Drums/Congas/KSHMR Conga - Closed High - Flick.wav",  # Mute High Conga
    63: "Drums/Percussion/Hand Drums/Congas/KSHMR Conga - Open High - Base (A#).wav",  # Open High Conga
    64: "Drums/Percussion/Hand Drums/Congas/KSHMR Conga - Closed Low - Facts (G).wav",  # Low Conga
    65: "Drums/Percussion/Hand Drums/Timbale/KSHMR Timbale - Hit - Light.wav",  # High Timbale
    66: "Drums/Percussion/Hand Drums/Timbale/KSHMR Timbale - Hit - Clean.wav", # Low Timbale
    67: "Drums/Percussion/Hand Drums/Bells/KSHMR Bell - Agogo (C#).wav",      # High Agogo
    68: "Drums/Percussion/Hand Drums/Bells/KSHMR Bell - Baila (C#).wav",      # Low Agogo
    69: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Softie.wav",  # Cabasa
    70: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Rattle (C).wav",  # Maracas
    71: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Kartal Space.wav",  # Short Whistle
    72: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Kartal Spring.wav", # Long Whistle
    73: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Guiro Hit.wav",   # Short Guiro
    74: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Guiro Scrape.wav", # Long Guiro
    75: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Clave (A).wav",   # Claves
    76: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Jam Block (A).wav",  # High Woodblock
    77: "Drums/Percussion/Mixed Percussion - Low/KSHMR Percussion Low - Organic - Duff (D#).wav",       # Low Woodblock
    78: "Drums/Percussion/Mixed Percussion - Low/KSHMR Percussion Low - Digital - Knock.wav",            # Mute Cuica
    79: "Drums/Percussion/Mixed Percussion - Low/KSHMR Percussion Low - Digital - Echo Chamber.wav",     # Open Cuica
    80: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Galaxy.wav",         # Mute Triangle
    81: "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Flop.wav",           # Open Triangle
}


def main():
    # 1. Validate candidates
    print("=== Validating KSHMR candidates ===")
    missing = []
    for note, rel in sorted(GM_TO_KSHMR.items()):
        full = os.path.join(ORIG, rel)
        if not os.path.exists(full):
            missing.append((note, rel))
            print(f"  ✗ N{note}: NOT FOUND -> {rel}")
    if missing:
        print(f"\n{len(missing)} candidates missing, aborting.")
        return
    print(f"  ✓ All {len(GM_TO_KSHMR)} candidates exist.")

    # 2. Copy samples
    print("\n=== Copying samples ===")
    copied = 0
    for note, rel in sorted(GM_TO_KSHMR.items()):
        src = os.path.join(ORIG, rel)
        for vel_tag in ("v064", "v127"):
            dst = os.path.join(DRUM_DIR, f"gm_drum_N{note}_{vel_tag}.wav")
            shutil.copy2(src, dst)
            copied += 1
    print(f"  Copied {copied} files ({len(GM_TO_KSHMR)} notes × 2 vel layers).")

    # 3. Rebuild SFZ entirely from files on disk
    print("\n=== Rebuilding SFZ from disk ===")
    # Collect all gm_drum_N<note>_v<vel>.wav
    region_map = {}  # note -> {"v064": basename, "v127": basename}
    for path in glob.glob(os.path.join(DRUM_DIR, "gm_drum_N*_v*.wav")):
        fname = os.path.basename(path)
        m = re.match(r"gm_drum_N(\d+)_(v\d+)\.wav", fname)
        if not m:
            continue
        note = int(m.group(1))
        vel = m.group(2)
        region_map.setdefault(note, {})[vel] = fname

    out = [
        "// GM Drum Kit — sfizz (KSHMR Vol.5)\n",
        "<group>\n",
        "ampeg_attack=0.001 ampeg_release=0.05\n",
        "\n",
    ]
    region_count = 0
    for note in sorted(region_map):
        layers = region_map[note]
        if "v064" in layers:
            out.append(f"<region> sample={DRUM_DIR}/{layers['v064']} lokey={note} hikey={note} lovel=0 hivel=80\n")
            region_count += 1
        if "v127" in layers:
            out.append(f"<region> sample={DRUM_DIR}/{layers['v127']} lokey={note} hikey={note} lovel=81 hivel=127\n")
            region_count += 1

    with open(SFZ_PATH, "w") as f:
        f.writelines(out)
    print(f"  Wrote {len(region_map)} drum notes ({region_count} regions) to {os.path.basename(SFZ_PATH)}.")


if __name__ == "__main__":
    main()
