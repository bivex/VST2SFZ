#!/usr/bin/env python3
"""
GM Drum Kit — KSHMR Vol.5 Complete Edition mapping.

Каждая GM-нота получает ДВА разных семпла:
  v064 (soft) → более лёгкий вариант (light, clean, small)
  v127 (loud) → более сильный вариант (heavy, punchy, big)

Это даёт реальную velocity-чувствительность вместо простого
дублирования одного файла.

Запустить: python kshmr_drum_mapping.py
"""

import os
import re
import shutil
import glob

KSHMR    = "/Volumes/External/Samples/Dharma Studio - Sounds of KSHMR Vol.5 Complete Edition"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRUM_DIR = os.path.join(_ROOT, "General_MIDI_samples_drums")
SFZ_PATH = os.path.join(_ROOT, "sfz", "General_MIDI_sfizz_drums.sfz")

D = KSHMR + "/Drums"   # shorthand

# GM note → (soft_v064_rel, loud_v127_rel)
# Relative paths under KSHMR root.
GM_TO_KSHMR = {
    # ── Kicks ──────────────────────────────────────────────────────────────
    35: (  # Acoustic Bass Drum — большой, объёмный
        "Drums/Kicks/Acoustic Kicks/KSHMR Acoustic Kick - Big - Roomy.wav",
        "Drums/Kicks/Acoustic Kicks/KSHMR Acoustic Kick - Big - Heavy.wav",
    ),
    36: (  # Bass Drum 1 — натуральный, сухой
        "Drums/Kicks/Acoustic Kicks/KSHMR Acoustic Kick - Natural - Beauty.wav",
        "Drums/Kicks/Acoustic Kicks/KSHMR Acoustic Kick - Natural - Stadium.wav",
    ),

    # ── Snare / Rim ────────────────────────────────────────────────────────
    37: (  # Side Stick — рим
        "Drums/Snares/Rims/KSHMR Rim - Organic - Maple.wav",
        "Drums/Snares/Rims/KSHMR Rim - Organic - Primal.wav",
    ),
    38: (  # Acoustic Snare
        "Drums/Snares/Acoustic Snares/KSHMR Acoustic Snare - Light - Snap.wav",
        "Drums/Snares/Acoustic Snares/KSHMR Acoustic Snare - Heavy - Maple.wav",
    ),
    39: (  # Hand Clap
        "Drums/Claps/Hand Claps/KSHMR Hand Clap - Small - Dry.wav",
        "Drums/Claps/Hand Claps/KSHMR Hand Clap - Big Group - Thick.wav",
    ),
    40: (  # Electric Snare — жёсткий
        "Drums/Snares/Tight Snares/KSHMR Tight Snare - Bright - Conditioned.wav",
        "Drums/Snares/Hard Snares/KSHMR Hard Snare - Force.wav",
    ),

    # ── Toms ───────────────────────────────────────────────────────────────
    41: (  # Low Floor Tom
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - Low - Pitcher.wav",
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - Low - Arena.wav",
    ),
    42: (  # Closed Hi-Hat
        "Drums/Hi-Hats/Closed Hi-Hats/KSHMR Closed Hat - Acoustic - Light.wav",
        "Drums/Hi-Hats/Closed Hi-Hats/KSHMR Closed Hat - Acoustic - Clean.wav",
    ),
    43: (  # High Floor Tom
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - Mid - Modest.wav",
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - Mid - Solid Punch.wav",
    ),
    44: (  # Pedal Hi-Hat
        "Drums/Hi-Hats/Closed Hi-Hats/KSHMR Closed Hat - Acoustic - Kiss.wav",
        "Drums/Hi-Hats/Closed Hi-Hats/KSHMR Closed Hat - Acoustic - Press.wav",
    ),
    45: (  # Low Tom
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - Low - Effective.wav",
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - Low - Thuddy.wav",
    ),
    46: (  # Open Hi-Hat
        "Drums/Hi-Hats/Open Hi-Hats/KSHMR Open Hat - Acoustic - Light.wav",
        "Drums/Hi-Hats/Open Hi-Hats/KSHMR Open Hat - Acoustic - Sizzle.wav",
    ),
    47: (  # Low-Mid Tom
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - Mid - Boomshift.wav",
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - Mid - Smacker.wav",
    ),
    48: (  # Hi-Mid Tom
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - High - Whimper.wav",
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - High - Power Boost.wav",
    ),
    49: (  # Crash Cymbal 1
        "Drums/Cymbals/Crashes/KSHMR Crash - Acoustic - Clean Bright.wav",
        "Drums/Cymbals/Crashes/KSHMR Crash - Acoustic - Classic Kit.wav",
    ),
    50: (  # High Tom
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - High - Snapper.wav",
        "Drums/Toms/Acoustic Toms/KSHMR Acoustic Tom - High - Breaker.wav",
    ),

    # ── Cymbals ────────────────────────────────────────────────────────────
    51: (  # Ride Cymbal 1
        "Drums/Cymbals/Rides/KSHMR Ride - Acoustic - Natural.wav",
        "Drums/Cymbals/Rides/KSHMR Ride - Acoustic - Bright.wav",
    ),
    52: (  # Chinese Cymbal
        "Drums/Cymbals/Crashes/KSHMR Crash - Clean Short - Simple.wav",
        "Drums/Cymbals/Crashes/KSHMR Crash - Clean Short - Big.wav",
    ),
    53: (  # Ride Bell
        "Drums/Cymbals/Rides/KSHMR Ride - Acoustic - Bell.wav",
        "Drums/Cymbals/Rides/KSHMR Ride - Classic - Punchy.wav",
    ),
    54: (  # Tambourine
        "Drums/Percussion/Tops - Tambourine/KSHMR Tambourine - Hit - Glisten.wav",
        "Drums/Percussion/Tops - Tambourine/KSHMR Tambourine - Hit - Flash.wav",
    ),
    55: (  # Splash Cymbal
        "Drums/Cymbals/Crashes/KSHMR Crash - Clean Short - Simple.wav",
        "Drums/Cymbals/Crashes/KSHMR Crash - Clean Short - Big.wav",
    ),
    56: (  # Cowbell
        "Drums/Percussion/Hand Drums/Bells/KSHMR Bell - Cowbell (E).wav",
        "Drums/Percussion/Hand Drums/Bells/KSHMR Bell - Cowbell (B).wav",
    ),
    57: (  # Crash Cymbal 2
        "Drums/Cymbals/Crashes/KSHMR Crash - Clean Long - Shimmer.wav",
        "Drums/Cymbals/Crashes/KSHMR Crash - Clean Long - Blazing.wav",
    ),
    58: (  # Vibraslap — ближайший аналог: rattling perc
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Rattle (C).wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Rattle (C).wav",
    ),
    59: (  # Ride Cymbal 2
        "Drums/Cymbals/Rides/KSHMR Ride - Classic - Quick.wav",
        "Drums/Cymbals/Rides/KSHMR Ride - Classic - Classic.wav",
    ),

    # ── Hand Drums ─────────────────────────────────────────────────────────
    60: (  # High Bongo
        "Drums/Percussion/Hand Drums/Bongos/KSHMR Bongo - Closed - Pop.wav",
        "Drums/Percussion/Hand Drums/Bongos/KSHMR Bongo - Closed - Bright.wav",
    ),
    61: (  # Low Bongo
        "Drums/Percussion/Hand Drums/Bongos/KSHMR Bongo - Open - Flow.wav",
        "Drums/Percussion/Hand Drums/Bongos/KSHMR Bongo - Closed - Low.wav",
    ),
    62: (  # Mute Hi Conga
        "Drums/Percussion/Hand Drums/Congas/KSHMR Conga - Closed High - Gold.wav",
        "Drums/Percussion/Hand Drums/Congas/KSHMR Conga - Closed High - Flick.wav",
    ),
    63: (  # Open Hi Conga
        "Drums/Percussion/Hand Drums/Congas/KSHMR Conga - Open High - Wide (A#).wav",
        "Drums/Percussion/Hand Drums/Congas/KSHMR Conga - Open High - Base (A#).wav",
    ),
    64: (  # Low Conga
        "Drums/Percussion/Hand Drums/Congas/KSHMR Conga - Closed Low - Facts (G).wav",
        "Drums/Percussion/Hand Drums/Congas/KSHMR Conga - Open Low - Big (C).wav",
    ),
    65: (  # High Timbale
        "Drums/Percussion/Hand Drums/Timbale/KSHMR Timbale - Hit - Light.wav",
        "Drums/Percussion/Hand Drums/Timbale/KSHMR Timbale - Hit - Hype.wav",
    ),
    66: (  # Low Timbale
        "Drums/Percussion/Hand Drums/Timbale/KSHMR Timbale - Hit - Clean.wav",
        "Drums/Percussion/Hand Drums/Timbale/KSHMR Timbale - Hit - Double.wav",
    ),
    67: (  # High Agogo
        "Drums/Percussion/Hand Drums/Bells/KSHMR Bell - Agogo (C#).wav",
        "Drums/Percussion/Hand Drums/Bells/KSHMR Bell - Agogo (C#).wav",
    ),
    68: (  # Low Agogo
        "Drums/Percussion/Hand Drums/Bells/KSHMR Bell - Baila (C#).wav",
        "Drums/Percussion/Hand Drums/Bells/KSHMR Bell - Baila (C#).wav",
    ),

    # ── Misc Percussion ────────────────────────────────────────────────────
    69: (  # Cabasa — loose shaker
        "Drums/Percussion/Tops - Shaker/KSHMR Shaker - Loose - Grain.wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Softie.wav",
    ),
    70: (  # Maracas
        "Drums/Percussion/Tops - Shaker/KSHMR Shaker - Mini - Chirp.wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Rattle (C).wav",
    ),
    71: (  # Short Whistle
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Kartal Space.wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Kartal Space.wav",
    ),
    72: (  # Long Whistle
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Kartal Spring.wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Kartal Spring.wav",
    ),
    73: (  # Short Guiro
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Guiro Hit.wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Guiro Hit.wav",
    ),
    74: (  # Long Guiro
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Guiro Scrape.wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Guiro Scrape.wav",
    ),
    75: (  # Claves
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Clave (A).wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Clave (A).wav",
    ),
    76: (  # Hi Wood Block
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Jam Block (A).wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Jam Block (A).wav",
    ),
    77: (  # Low Wood Block
        "Drums/Percussion/Mixed Percussion - Low/KSHMR Percussion Low - Organic - Duff (D#).wav",
        "Drums/Percussion/Mixed Percussion - Low/KSHMR Percussion Low - Digital - Knock.wav",
    ),
    78: (  # Mute Cuica
        "Drums/Percussion/Mixed Percussion - Low/KSHMR Percussion Low - Digital - Knock.wav",
        "Drums/Percussion/Mixed Percussion - Low/KSHMR Percussion Low - Digital - Knock.wav",
    ),
    79: (  # Open Cuica
        "Drums/Percussion/Mixed Percussion - Low/KSHMR Percussion Low - Digital - Echo Chamber.wav",
        "Drums/Percussion/Mixed Percussion - Low/KSHMR Percussion Low - Digital - Echo Chamber.wav",
    ),
    80: (  # Mute Triangle
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Galaxy.wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Galaxy.wav",
    ),
    81: (  # Open Triangle
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Flop.wav",
        "Drums/Percussion/Mixed Percussion - High/KSHMR Percussion High - Organic - Flop.wav",
    ),
}

GM_DRUM_NAMES = {
    35: "Acoustic Bass Drum", 36: "Bass Drum 1",     37: "Side Stick",
    38: "Acoustic Snare",     39: "Hand Clap",        40: "Electric Snare",
    41: "Low Floor Tom",      42: "Closed Hi-Hat",    43: "High Floor Tom",
    44: "Pedal Hi-Hat",       45: "Low Tom",          46: "Open Hi-Hat",
    47: "Low-Mid Tom",        48: "Hi-Mid Tom",       49: "Crash Cymbal 1",
    50: "High Tom",           51: "Ride Cymbal 1",    52: "Chinese Cymbal",
    53: "Ride Bell",          54: "Tambourine",       55: "Splash Cymbal",
    56: "Cowbell",            57: "Crash Cymbal 2",   58: "Vibraslap",
    59: "Ride Cymbal 2",      60: "Hi Bongo",         61: "Low Bongo",
    62: "Mute Hi Conga",      63: "Open Hi Conga",    64: "Low Conga",
    65: "High Timbale",       66: "Low Timbale",      67: "High Agogo",
    68: "Low Agogo",          69: "Cabasa",           70: "Maracas",
    71: "Short Whistle",      72: "Long Whistle",     73: "Short Guiro",
    74: "Long Guiro",         75: "Claves",           76: "Hi Wood Block",
    77: "Low Wood Block",     78: "Mute Cuica",       79: "Open Cuica",
    80: "Mute Triangle",      81: "Open Triangle",
}


def main():
    os.makedirs(DRUM_DIR, exist_ok=True)

    # 1. Validate all source files
    print("=== Validating KSHMR candidates ===")
    missing = []
    for note, (soft, loud) in sorted(GM_TO_KSHMR.items()):
        for rel in set([soft, loud]):
            full = os.path.join(KSHMR, rel)
            if not os.path.exists(full):
                missing.append((note, rel))
                print(f"  ✗ N{note}: NOT FOUND → {rel}")
    if missing:
        print(f"\n{len(missing)} files missing, aborting.")
        return
    print(f"  ✓ All candidates exist.")

    # 2. Copy samples with velocity-tagged names
    print("\n=== Copying samples (2 real velocity layers) ===")
    copied = 0
    for note, (soft_rel, loud_rel) in sorted(GM_TO_KSHMR.items()):
        name = GM_DRUM_NAMES.get(note, f"N{note}")
        soft_src = os.path.join(KSHMR, soft_rel)
        loud_src = os.path.join(KSHMR, loud_rel)
        dst_soft = os.path.join(DRUM_DIR, f"gm_drum_N{note}_v064.wav")
        dst_loud = os.path.join(DRUM_DIR, f"gm_drum_N{note}_v127.wav")
        shutil.copy2(soft_src, dst_soft)
        shutil.copy2(loud_src, dst_loud)
        same = "=" if soft_rel == loud_rel else "≠"
        print(f"  N{note:>2} {name:<22} {same}  soft={os.path.basename(soft_rel)[:35]}")
        copied += 2

    print(f"\n  Copied {copied} files ({len(GM_TO_KSHMR)} notes × 2 vel).")

    # 3. Rebuild standalone drum SFZ from disk
    print("\n=== Rebuilding General_MIDI_sfizz_drums.sfz ===")
    region_map = {}
    for path in glob.glob(os.path.join(DRUM_DIR, "gm_drum_N*_v*.wav")):
        m = re.match(r"gm_drum_N(\d+)_(v\d+)\.wav", os.path.basename(path))
        if not m:
            continue
        note, vel = int(m.group(1)), m.group(2)
        region_map.setdefault(note, {})[vel] = path

    out = [
        "// GM Drum Kit — sfizz (KSHMR Vol.5 Complete Edition)\n",
        "// 2 real velocity layers per note (soft ≠ loud samples)\n",
        "<group>\n",
        "ampeg_attack=0.001 ampeg_release=0.05\n",
        "\n",
    ]
    rc = 0
    for note in sorted(region_map):
        layers = region_map[note]
        gm_name = GM_DRUM_NAMES.get(note, f"N{note}")
        out.append(f"// {note} — {gm_name}\n")
        if "v064" in layers:
            out.append(f"<region> sample={layers['v064']}  lokey={note} hikey={note} lovel=0   hivel=80\n")
            rc += 1
        if "v127" in layers:
            out.append(f"<region> sample={layers['v127']} lokey={note} hikey={note} lovel=81  hivel=127\n")
            rc += 1

    with open(SFZ_PATH, "w") as f:
        f.writelines(out)
    print(f"  ✓ {len(region_map)} notes, {rc} regions → {os.path.basename(SFZ_PATH)}")

    # 4. Strip any embedded drum section from the sfizz banks.
    #
    # The sfizz consumer (pysfizz) plays every note on channel 1 and IGNORES
    # the lochan=10 gate, so an embedded drum section leaks a percussion hit
    # onto every melodic note in the N35-N81 key range (verified: melodic
    # note 60 correlated 0.80 with the bongo sample). sfizz consumers must get
    # drums from the standalone General_MIDI_sfizz_drums.sfz (loaded into a
    # SEPARATE drum synth), never from an embedded section. So here we only
    # REMOVE any previously-embedded block; we do not re-append one.
    print("\n=== Stripping embedded drum sections from sfizz banks ===")
    _sfz = os.path.join(_ROOT, "sfz")
    SFZ_FILES = [
        os.path.join(_sfz, "General_MIDI_sfizz.sfz"),
        os.path.join(_sfz, "General_MIDI_sfizz_processed.sfz"),
        os.path.join(_sfz, "Dexed_MIDI_sfizz.sfz"),
        os.path.join(_sfz, "Dexed_MIDI_sfizz_processed.sfz"),
    ]
    MARKER = "\n// ─── GM Drum Kit"

    for sfz_path in SFZ_FILES:
        if not os.path.exists(sfz_path):
            print(f"  SKIP (not found): {os.path.basename(sfz_path)}")
            continue
        content = open(sfz_path).read()
        had = MARKER in content
        if had:
            content = content[:content.index(MARKER)].rstrip() + "\n"
            open(sfz_path, "w").write(content)
        state = "stripped embedded drums" if had else "no embedded drums (ok)"
        print(f"  ✓ {os.path.basename(sfz_path)}: {state}; "
              f"{content.count('<region>')} melodic regions")


if __name__ == "__main__":
    main()
