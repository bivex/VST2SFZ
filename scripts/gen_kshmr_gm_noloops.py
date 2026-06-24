#!/usr/bin/env python3
"""
Generate a 128 General MIDI SFZ from the KSHMR Vol.5 sample library.
ONLY ONE-SHOTS, no loops.
"""

import os, glob, re

BASE = (
    "/Volumes/External/Samples/Dharma Studio - Sounds of KSHMR Vol.5 Complete Edition"
)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sfz", "KSHMR_Vol5_128GM_NoLoops.sfz")


def rel(path):
    return os.path.relpath(path, os.path.dirname(OUT)).replace("\\", "/")


def parse_key(filename):
    name = os.path.basename(filename)
    m = re.search(
        r"\((\d+,\s*)?([A-G][#b]?(?:\s*(?:m|Maj|Phrygian|min|major))?)\)", name
    )
    if not m:
        return None
    token = m.group(2).strip()
    note_str = token.split()[0] if " " in token else token
    quality = token[len(note_str) :].strip() if len(token) > len(note_str) else ""
    note_map = {
        "C": 60,
        "C#": 61,
        "D": 62,
        "D#": 63,
        "E": 64,
        "F": 65,
        "F#": 66,
        "G": 67,
        "G#": 68,
        "A": 69,
        "A#": 70,
        "B": 71,
    }
    flat_to_sharp = {
        "Db": "C#",
        "Eb": "D#",
        "Gb": "F#",
        "Ab": "G#",
        "Bb": "A#",
        "Cb": "B",
        "Fb": "E",
    }
    if note_str in flat_to_sharp:
        note_str = flat_to_sharp[note_str]
    midi = note_map.get(note_str)
    return (midi, quality) if midi else None


def is_loop(path):
    p = path.lower()
    name = os.path.basename(p)
    # Exclude files with "loop" in name or in Drum Loops / Synth Loops folders
    if "loop" in name:
        return True
    if "/drum loops/" in p or "\\drum loops\\" in p:
        return True
    if "/synth loops/" in p or "\\synth loops\\" in p:
        return True
    if "/bass loops/" in p or "\\bass loops\\" in p:
        return True
    if "/guitar loops/" in p or "\\guitar loops\\" in p:
        return True
    if "/strings loops/" in p or "\\strings loops\\" in p:
        return True
    if "/action loops/" in p or "\\action loops\\" in p:
        return True
    if "/songstarters/" in p or "\\songstarters\\" in p:
        return True
    return False


def map_drum_key(path):
    p = path.lower()
    if "kick" in p or "808" in p or "stomp" in p or "sub" in p:
        return 36
    if "acoustic kick" in p:
        return 35
    if "snare" in p or "rim" in p or "snap" in p:
        if "rim" in p or "side" in p:
            return 37
        return 38
    if "clap" in p:
        return 39
    if "hat" in p or "hihat" in p or "hi-hat" in p:
        if "open" in p:
            return 46
        if "pedal" in p or "foot" in p:
            return 44
        return 42
    if "crash" in p:
        return 49
    if "ride" in p:
        if "bell" in p:
            return 53
        return 51
    if "tom" in p:
        if "high" in p:
            return 50
        if "floor" in p:
            return 41
        if "low" in p:
            return 41 if "low-mid" not in p else 47
        if "mid" in p:
            return 47
        return 45
    if "conga" in p:
        if "open high" in p:
            return 63
        if "closed high" in p or "mute" in p:
            return 62
        if "low" in p:
            return 64
        return 63
    if "bongo" in p:
        if "open" in p:
            return 60
        if "closed" in p or "flam" in p:
            return 61
        return 60
    if "timbale" in p:
        if "roll" in p or "double" in p:
            return 66
        return 65
    if "tambourine" in p:
        return 54
    if "cowbell" in p:
        return 56
    if "agogo" in p:
        return 67
    if "shaker" in p or "cabasa" in p or "seed" in p or "gourd" in p:
        return 69
    if "maraca" in p:
        return 70
    if "guiro" in p:
        return 74 if "scrape" in p or "long" in p else 73
    if "clave" in p:
        return 75
    if "jam block" in p or "block" in p:
        return 76
    if "orchestral drum" in p:
        return 50 if "high" in p else 41 if "low" in p else 45
    if "cymbal" in p or "china" in p:
        return 57
    return 36


# ============================================================
# File collection - ONE SHOTS ONLY
# ============================================================


def collect_files():
    files = {}
    # Only one-shot folders, no loops
    patterns = [
        # Drums one-shots
        "Drums/Kicks/*.wav",
        "Drums/Claps/*.wav",
        "Drums/Cymbals/*.wav",
        "Drums/Hi-Hats/*.wav",
        "Drums/Snares/*/*.wav",
        "Drums/Toms/*/*.wav",
        "Drums/Snaps/*.wav",
        "Drums/Orchestral Drums/*.wav",
        "Drums/Percussion/Hand Drums/Bells/*.wav",
        "Drums/Percussion/Hand Drums/Bongos/*.wav",
        "Drums/Percussion/Hand Drums/Congas/*.wav",
        "Drums/Percussion/Hand Drums/Timbale/*.wav",
        "Drums/Percussion/Mixed Percussion - High/*.wav",
        "Drums/Percussion/Tops - Tambourine/*.wav",
        "Drums/Percussion/Tops - Shaker/*.wav",
        # Melodic one-shots
        "Instruments/Bass/Bass One Shots/*.wav",
        "Instruments/Brass/Orchestral Brass/Orchestral Brass One Shots/*.wav",
        "Instruments/Brass/Trumpets/Trumpet One Shots/*.wav",
        "Instruments/Guitar/Guitar One Shots/*.wav",
        "Instruments/Strings/One Shots/*.wav",
        "Instruments/Winds/Didgeridoo/Didgeridoo One Shots/*.wav",
        "Instruments/Winds/Duduk/Duduk One Shots/*.wav",
        "Instruments/Winds/Flute/Flute One Shots/*.wav",
        "Instruments/Winds/Human Whistles/One Shots/*.wav",
        "Instruments/Winds/Sax/Sax One Shots/*.wav",
        "Instruments/Winds/Shehnai/Shehnai One Shots/*.wav",
        "Instruments/Long Improvs/*.wav",
        # Synth one-shots
        "Synths/BASS - One Shots/Bass Shots - Hits/*.wav",
        "Synths/BASS - One Shots/Bass Shots - Plucks/*.wav",
        "Synths/BASS - One Shots/Bass Shots - Scream/*.wav",
        "Synths/BASS - One Shots/Bass Shots - Whomp/*.wav",
        "Synths/SYNTH - One Shots/SYNTH - Plucks/*.wav",
        "Synths/SYNTH - One Shots/SYNTH - Screeches/*.wav",
        "Synths/SYNTH - One Shots/SYNTH - Stabs/*.wav",
        "Synths/SYNTH - One Shots/SYNTH - Energizers/*.wav",
        # FX one-shots
        "FX/Hits/*.wav",
        "FX/Impacts/*.wav",
        "FX/War Horns/*.wav",
        "FX/Falls/**/*.wav",
        "FX/Rises/**/*.wav",
        "FX/Reverses/**/*.wav",
        "FX/Transitions/**/*.wav",
        "FX/Ambiance/**/*.wav",
        # VIP one-shots
        "VIP Friends of KSHMR/Instruments/*.wav",
        "VIP Friends of KSHMR/Synth One Shots/*.wav",
        # Fills (one-shot drum fills)
        "Fills/**/*.wav",
    ]
    for pat in patterns:
        matched = glob.glob(os.path.join(BASE, pat), recursive=True)
        for f in matched:
            if is_loop(f):
                continue
            k = parse_key(f)
            info = {"type": "melodic" if k else "other", "path": f}
            if k:
                info["key"] = k[0]
                info["quality"] = k[1]
            else:
                info["key"] = None
                info["quality"] = ""
            files[f] = info
    return files


# ============================================================
# Classification
# ============================================================


def classify(path):
    p = path.lower()

    if "/fx/" in p or "\\fx\\" in p:
        if "hit" in p or "impact" in p or "war horn" in p:
            return "fx", "hit"
        if "rise" in p:
            return "fx", "rise"
        if "fall" in p or "drop" in p or "tape stop" in p:
            return "fx", "fall"
        if "reverse" in p:
            return "fx", "reverse"
        if "sweep" in p or "transition" in p:
            return "fx", "sweep"
        if "ambiance" in p or "ambience" in p:
            return "fx", "ambiance"
        return "fx", "other"

    if "/drums/" in p or "\\drums\\" in p:
        return "drum", "any"

    if "fill" in p and "/fills/" in p:
        if (
            "drum" in p
            or "perc" in p
            or "tom" in p
            or "cym" in p
            or "snare" in p
            or "crash" in p
        ):
            return "drumfill", "drumfill"
        return "fill", "fill"

    if "bass" in p:
        return "bass", "any"

    if "guitar" in p:
        return "guitar", "any"

    if "string" in p or "violin" in p or "cello" in p or "viola" in p or "lyra" in p:
        return "strings", "any"

    if "trumpet" in p:
        return "brass", "trumpet"
    if "brass" in p or "orch brass" in p:
        return "brass", "section"
    if "horn" in p and "synth" not in p and "war" not in p:
        return "brass", "horn"

    if "sax" in p:
        return "winds", "sax"
    if "flute" in p:
        return "winds", "flute"
    if "duduk" in p:
        return "winds", "duduk"
    if "shehnai" in p:
        return "winds", "shehnai"
    if "whistle" in p:
        return "winds", "whistle"
    if "didgeridoo" in p:
        return "winds", "didgeridoo"
    if "clarinet" in p:
        return "winds", "clarinet"

    if "keys" in p or "piano" in p:
        return "keys", "keys"
    if "organ" in p:
        return "keys", "organ"
    if "harp" in p and "synth" not in p:
        return "keys", "harp"
    if "accordion" in p or "bandoneon" in p:
        return "keys", "accordion"

    if "bass" in p and "synth" in p:
        return "synthbass", "synthbass"

    if "synth" in p or "synths/" in p:
        if "pluck" in p:
            return "synth", "pluck"
        if "stab" in p:
            if "choir" in p:
                return "choir", "choir"
            if "brass" in p:
                return "synthbrass", "stab"
            return "synth", "stab"
        if "screech" in p:
            return "synth", "screech"
        if "energizer" in p:
            return "synth", "energizer"
        if "fill" in p:
            return "synth", "fill"
        if "lead" in p or "melody" in p:
            return "synth", "lead"
        if "chord" in p:
            return "synth", "chord"
        if "arp" in p:
            return "synth", "arp"
        if "atmosphere" in p or "ambient" in p:
            return "synth", "pad"
        if "acid" in p:
            return "synth", "acid"
        if "techno" in p:
            return "synth", "techno"
        if "distortion" in p or "distort" in p:
            return "synth", "distortion"
        return "synth", "misc"

    if (
        "sitar" in p
        or "saz" in p
        or "baglama" in p
        or "bouzouki" in p
        or "lo tar" in p
        or "tar " in p
        or "oud" in p
    ):
        return "ethnic", "world"
    if "banjo" in p:
        return "ethnic", "banjo"

    if "vocal" in p or "choir" in p or "adlib" in p or "shout" in p or "chant" in p:
        return "vocal", "vocal"

    if "vip" in p:
        return "vip", "vip"

    return "misc", "misc"


# ============================================================
# Program assignment
# ============================================================


def assign_program(fam, sub, path):
    p = path.lower()
    if fam == "drum":
        return 0
    if fam == "drumfill":
        return 0  # drum fills go to drum program too
    if fam == "fx":
        if sub == "hit":
            return 120
        if sub == "sweep":
            return 121
        if sub == "fall":
            return 122
        if sub == "reverse":
            return 123
        if sub == "rise":
            return 124
        if sub == "ambiance":
            return 125
        return 126
    if fam == "bass":
        return 32 + (hash(path) % 8)
    if fam == "synthbass":
        return 38 + (hash(path) % 2)
    if fam == "guitar":
        if "acoustic" in p:
            return 24
        return 25 + (hash(path) % 7)
    if fam == "worldstrum":
        return 104 + (hash(path) % 8)
    if fam == "strings":
        return 40 + (hash(path) % 8)
    if fam == "choir":
        return 52 + (hash(path) % 3)
    if fam == "brass":
        return 56 + (hash(path) % 8)
    if fam == "synthbrass":
        return 62 + (hash(path) % 2)
    if fam == "winds":
        return 64 + (hash(path) % 16)
    if fam == "keys":
        if "organ" in p:
            return 16 + (hash(path) % 8)
        if "harp" in p:
            return 46
        if "accordion" in p or "bandoneon" in p:
            return 21 + (hash(path) % 3)
        return 0 + (hash(path) % 8)
    if fam == "ethnic":
        return 104 + (hash(path) % 8)
    if fam == "synth":
        if "pluck" in p:
            return 88 + (hash(path) % 7)
        if "stab" in p:
            if "brass" in p:
                return 61
            return 80 + (hash(path) % 14)
        if "screech" in p:
            return 102
        if "lead" in p or "melody" in p:
            return 80 + (hash(path) % 8)
        if "chord" in p:
            return 89 + (hash(path) % 7)
        if "arp" in p:
            return 89 + (hash(path) % 7)
        if "pad" in p or "atmosphere" in p:
            return 88 + (hash(path) % 7)
        if "techno" in p:
            return 80 + (hash(path) % 8)
        if "acid" in p:
            return 38
        if "distortion" in p:
            return 30
        if "fill" in p:
            return 80 + (hash(path) % 8)
        return 80 + (hash(path) % 8)
    if fam == "vocal":
        return 52 + (hash(path) % 4)
    if fam == "fill":
        return 80 + (hash(path) % 8)
    if fam == "vip":
        if "organ" in p:
            return 16 + (hash(path) % 8)
        if "harp" in p:
            return 46
        return 48 + (hash(path) % 4)

    # Fallback
    if "bell" in p or "tink" in p or "agogo" in p:
        return 112
    if "cowbell" in p or "wood" in p:
        return 115
    if "taiko" in p or "orchestral drum" in p:
        return 116
    if "steel" in p:
        return 114
    if "melodic tom" in p:
        return 117
    if "synth drum" in p:
        return 118
    if "reverse cymbal" in p or "reverse cym" in p:
        return 119
    if "impact" in p or "gun" in p or "shot" in p:
        return 127
    if "applause" in p or "crowd" in p:
        return 126
    if "helicopter" in p or "plane" in p:
        return 125
    if "phone" in p or "telephone" in p or "ring" in p:
        return 124
    if "bird" in p or "tweet" in p:
        return 123
    if "sea" in p or "ocean" in p or "wave" in p:
        return 122
    if "breath" in p:
        return 121
    if "fret" in p or "guitar noise" in p:
        return 120

    return 80


# ============================================================
# Build GM map
# ============================================================


def build_gm_map(all_files):
    gm = {i: [] for i in range(128)}
    seen = set()

    for path, info in all_files.items():
        fam, sub = classify(path)
        prog = assign_program(fam, sub, path)
        if (prog, path) in seen:
            continue
        seen.add((prog, path))
        gm[prog].append({"path": path, "info": info, "fam": fam})

    # Fill missing programs
    gm = fill_missing(gm)
    return gm


def fill_missing(gm_map):
    missing = [i for i in range(128) if not gm_map[i]]
    if not missing:
        return gm_map

    for prog in missing:
        candidates = []
        if prog in list(range(8, 16)):  # Chromatic Perc
            for p in [112, 113, 114, 115, 116, 117, 118, 119, 56, 57, 88, 89]:
                if gm_map[p]:
                    candidates.extend(gm_map[p][:5])
            if not candidates:
                candidates = gm_map[0][:5]
        elif prog in list(range(16, 24)):  # Organ family
            candidates = gm_map[21][:3]
            if not candidates:
                candidates = gm_map[16][:3]
            if not candidates:
                candidates = gm_map[46][:3]
        elif prog in list(range(96, 104)):  # FX
            candidates = gm_map[80][:3] + gm_map[88][:3] + gm_map[102][:5]
        elif prog in list(range(112, 120)):  # Percussion
            candidates = gm_map[0][-10:]
        elif prog == 127:  # Gunshot
            candidates = gm_map[120][:3] + gm_map[55][:3]
        elif prog == 48:  # String Ensemble
            candidates = gm_map[40][:10] + gm_map[41][:5]
        elif prog == 93 or prog == 94 or prog == 95:  # Pad 6-8
            candidates = gm_map[88][:10] + gm_map[89][:10]
        elif prog == 106:  # Shamisen
            candidates = gm_map[104][:5] + gm_map[25][:5]
        elif prog == 108:  # Kalimba
            candidates = gm_map[73][:5] + gm_map[88][:5]
        elif prog == 110:  # Fiddle
            candidates = gm_map[40][:5] + gm_map[25][:5]
        elif prog == 111:  # Shanai
            candidates = gm_map[73][:5] + gm_map[70][:5]
        else:
            nearby = [prog - 1, prog + 1, prog - 8, prog + 8, prog - 12, prog + 12]
            for p in nearby:
                if 0 <= p <= 127 and gm_map[p]:
                    candidates = gm_map[p][:5]
                    break

        if candidates:
            for c in candidates[:3]:
                gm_map[prog].append(
                    {
                        "path": c["path"],
                        "info": c["info"],
                        "fam": c.get("fam", "fallback"),
                    }
                )

    return gm_map


# ============================================================
# SFZ generation
# ============================================================

GM_NAMES = {
    0: "Acoustic Grand Piano / Drum Kit",
    1: "Bright Piano",
    2: "Electric Grand Piano",
    3: "Honky-tonk Piano",
    4: "Electric Piano 1",
    5: "Electric Piano 2",
    6: "Harpsichord",
    7: "Clavinet",
    8: "Celesta",
    9: "Glockenspiel",
    10: "Music Box",
    11: "Vibraphone",
    12: "Marimba",
    13: "Xylophone",
    14: "Tubular Bells",
    15: "Dulcimer",
    16: "Drawbar Organ",
    17: "Percussive Organ",
    18: "Rock Organ",
    19: "Church Organ",
    20: "Reed Organ",
    21: "Accordion",
    22: "Harmonica",
    23: "Tango Accordion",
    24: "Acoustic Guitar (nylon)",
    25: "Acoustic Guitar (steel)",
    26: "Electric Guitar (jazz)",
    27: "Electric Guitar (clean)",
    28: "Electric Guitar (muted)",
    29: "Overdriven Guitar",
    30: "Distortion Guitar",
    31: "Guitar Harmonics",
    32: "Acoustic Bass",
    33: "Electric Bass (finger)",
    34: "Electric Bass (pick)",
    35: "Fretless Bass",
    36: "Slap Bass 1",
    37: "Slap Bass 2",
    38: "Synth Bass 1",
    39: "Synth Bass 2",
    40: "Violin",
    41: "Viola",
    42: "Cello",
    43: "Contrabass",
    44: "Tremolo Strings",
    45: "Pizzicato Strings",
    46: "Harp",
    47: "Timpani",
    48: "String Ensemble 1",
    49: "String Ensemble 2",
    50: "SynthStrings 1",
    51: "SynthStrings 2",
    52: "Choir Aahs",
    53: "Voice Oohs",
    54: "Synth Voice",
    55: "Orchestra Hit",
    56: "Trumpet",
    57: "Trombone",
    58: "Tuba",
    59: "Muted Trumpet",
    60: "French Horn",
    61: "Brass Section",
    62: "SynthBrass 1",
    63: "SynthBrass 2",
    64: "Soprano Sax",
    65: "Alto Sax",
    66: "Tenor Sax",
    67: "Baritone Sax",
    68: "Oboe",
    69: "English Horn",
    70: "Bassoon",
    71: "Clarinet",
    72: "Piccolo",
    73: "Flute",
    74: "Recorder",
    75: "Pan Flute",
    76: "Blown Bottle",
    77: "Shakuhachi",
    78: "Whistle",
    79: "Ocarina",
    80: "Lead 1 (square)",
    81: "Lead 2 (sawtooth)",
    82: "Lead 3 (calliope)",
    83: "Lead 4 (chiff)",
    84: "Lead 5 (charang)",
    85: "Lead 6 (voice)",
    86: "Lead 7 (fifths)",
    87: "Lead 8 (bass+lead)",
    88: "Pad 1 (new age)",
    89: "Pad 2 (warm)",
    90: "Pad 3 (polysynth)",
    91: "Pad 4 (choir)",
    92: "Pad 5 (bowed)",
    93: "Pad 6 (metallic)",
    94: "Pad 7 (halo)",
    95: "Pad 8 (sweep)",
    96: "FX 1 (rain)",
    97: "FX 2 (soundtrack)",
    98: "FX 3 (crystal)",
    99: "FX 4 (atmosphere)",
    100: "FX 5 (brightness)",
    101: "FX 6 (goblins)",
    102: "FX 7 (echoes)",
    103: "FX 8 (sci-fi)",
    104: "Sitar",
    105: "Banjo",
    106: "Shamisen",
    107: "Koto",
    108: "Kalimba",
    109: "Bagpipe",
    110: "Fiddle",
    111: "Shanai",
    112: "Tinkle Bell",
    113: "Agogo",
    114: "Steel Drums",
    115: "Woodblock",
    116: "Taiko Drum",
    117: "Melodic Tom",
    118: "Synth Drum",
    119: "Reverse Cymbal",
    120: "Guitar Fret Noise",
    121: "Breath Noise",
    122: "Seashore",
    123: "Bird Tweet",
    124: "Telephone Ring",
    125: "Helicopter",
    126: "Applause",
    127: "Gunshot",
}


def gen_sfz(gm_map):
    lines = []
    lines.append(
        "// KSHMR Vol.5 Complete Edition - 128 General MIDI (ONE-SHOTS ONLY, no loops)"
    )
    lines.append("// Auto-generated mapping from Dharma Studio sample library")
    lines.append("")
    lines.append("<global>")
    lines.append("loop_mode=one_shot")
    lines.append("volume=-6")
    lines.append("ampeg_attack=0.005")
    lines.append("ampeg_release=0.3")
    lines.append("<control>")
    lines.append("default_path=./")
    lines.append("")

    used = [i for i in range(128) if gm_map[i]]
    missing = [i for i in range(128) if not gm_map[i]]
    lines.append(f"// Mapped programs: {len(used)}/128")
    if missing:
        lines.append(f"// Programs without samples: {missing}")
    lines.append("")

    for prog in range(128):
        samples = gm_map[prog]
        if not samples:
            continue

        name = GM_NAMES.get(prog, f"Program {prog}")
        lines.append(f"<group>")
        lines.append(f"loprog={prog} hiprog={prog}")
        lines.append(f"// GM {prog}: {name}")
        lines.append("")

        if prog == 0:
            lines.append("ampeg_attack=0.001 ampeg_release=0.1")
            lines.append("loop_mode=one_shot")
            lines.append("volume=-4")
            lines.append("")
            for s in samples:
                path = s["path"]
                gm_key = map_drum_key(path)
                rp = rel(path)
                lines.append(
                    f"<region> sample={rp} key={gm_key} pitch_keycenter={gm_key}"
                )
        else:
            lines.append("ampeg_attack=0.005 ampeg_release=0.3")
            lines.append("volume=-6")
            lines.append("")
            for s in samples:
                info = s["info"]
                path = s["path"]
                if info["type"] == "melodic" and info.get("key"):
                    key_midi = info["key"]
                    pitch = key_midi
                    lokey = max(0, key_midi - 12)
                    hikey = min(127, key_midi + 12)
                    rp = rel(path)
                    lines.append(
                        f"<region> sample={rp} pitch_keycenter={pitch} lokey={lokey} hikey={hikey} lovel=0 hivel=127"
                    )
                else:
                    pitch = 60
                    rp = rel(path)
                    lines.append(
                        f"<region> sample={rp} pitch_keycenter={pitch} lokey=0 hikey=127 lovel=0 hivel=127"
                    )

        lines.append("")

    return "\n".join(lines)


# ============================================================
# Main
# ============================================================


def main():
    print("Scanning library (one-shots only, no loops)...")
    all_files = collect_files()
    print(f"Found {len(all_files)} one-shot files")

    print("Building GM map...")
    gm_map = build_gm_map(all_files)

    used = [i for i in range(128) if gm_map[i]]
    missing = [i for i in range(128) if not gm_map[i]]
    print(f"Programs with samples: {len(used)}/128")
    print(f"Missing: {missing}")
    print()
    print("Sample counts by program:")
    for prog in sorted(used):
        name = GM_NAMES.get(prog, "???")
        print(f"  Prog {prog:3d}: {len(gm_map[prog]):4d} samples - {name}")

    print("\nGenerating SFZ...")
    sfz = gen_sfz(gm_map)

    with open(OUT, "w") as f:
        f.write(sfz)
    print(f"Written to: {OUT}")
    print(f"File size: {len(sfz):,} bytes")


if __name__ == "__main__":
    main()
