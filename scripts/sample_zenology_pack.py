#!/usr/bin/env python3
"""
Zenology GM Pack generator.

Renders all (or a curated subset of) Roland Zenology presets through
Zenology Pro (VST3) via DawDreamer and writes:
  - WAV sample files into zenology_samples_raw/
  - Individual SFZ instrument files into zenology_instruments/
  - A master bank SFZ: zenology_gm.sfz

Preset loading strategy
-----------------------
ZENOLOGY presets arrive as .fzi collection-pointers (Roland Cloud) and
actual preset payloads as .exz (Roland VEXP format).  Neither format is
directly understood by DawDreamer, so headless loading happens via a
pre-dumped JSON parameter snapshot:

  1. Open Zenology in any DAW / standalone.
  2. Load the preset you care about.
  3. Run:  zengen dump_this_preset.py  (or paste the one-liner below).
  4. Save the resulting JSON into zen_patches/<preset_name>.json.

  One-liner for step 3:
    import json, dawdreamer as daw
    e = daw.RenderEngine(44100, 512)
    s = e.make_plugin_processor("z", "/Library/Audio/Plug-Ins/VST3/Roland/ZENOLOGY.vst3")
    e.load_graph([(s, [])])
    json.dump(s.get_patch(), open("out.json","w"))

The renderer looks for zen_patches/<safe_name>.json and feeds the values
back via synth.set_patch().  If a patch file is absent the synth is left
in its default (init) state and a warning is printed.

Usage:
    python sample_zenology_pack.py                        # all presets
    python sample_zenology_pack.py --presets "JUPITER-8"  # single preset
    python sample_zenology_pack.py --skip-missing         # render only found patches
"""

import argparse
import glob
import json
import os
import shutil
import sys
import time

import dawdreamer as daw
import mido
import numpy as np
import soundfile as sf

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
VST_PATH = "/Library/Audio/Plug-Ins/VST3/Roland/ZENOLOGY.vst3"
ZENOLOGY_PRESETS_DIR = os.path.expanduser(
    "~/Library/Application Support/Roland Cloud/ZENOLOGY"
)
PATCH_DIR = "zen_patches"  # <--- put your JSON dumps here
SAMPLES_DIR = "zenology_samples_raw"
INSTRUMENTS_DIR = "zenology_instruments"
SR = 96000
BUFFER_SIZE = 512
DURATION = 1.0  # seconds per note
RELEASE = 0.5  # release tail
NOTES = [24, 36, 48, 60, 72, 84, 96, 108]  # C1..C8
VELOCITIES = [64, 127]

# ─────────────────────────────────────────────────────────────────────────────
# Preset → GM program mapping (based on .fzi filename keywords)
# ─────────────────────────────────────────────────────────────────────────────
GM_NAMES = [
    "acoustic_grand_piano",
    "bright_acoustic_piano",
    "electric_grand_piano",
    "honky_tonk_piano",
    "electric_piano_1",
    "electric_piano_2",
    "harpsichord",
    "clavinet",
    "celesta",
    "glockenspiel",
    "music_box",
    "vibraphone",
    "marimba",
    "xylophone",
    "tubular_bells",
    "dulcimer",
    "drawbar_organ",
    "percussive_organ",
    "rock_organ",
    "church_organ",
    "reed_organ",
    "accordion",
    "harmonica",
    "tango_accordion",
    "acoustic_guitar_nylon",
    "acoustic_guitar_steel",
    "electric_guitar_jazz",
    "electric_guitar_clean",
    "electric_guitar_muted",
    "overdriven_guitar",
    "distorted_guitar",
    "guitar_harmonics",
    "acoustic_bass",
    "electric_bass_finger",
    "electric_bass_pick",
    "fretless_bass",
    "slap_bass_1",
    "slap_bass_2",
    "synth_bass_1",
    "synth_bass_2",
    "violin",
    "viola",
    "cello",
    "contrabass",
    "tremolo_strings",
    "pizzicato_strings",
    "orchestral_harp",
    "timpani",
    "string_ensemble_1",
    "string_ensemble_2",
    "synth_strings_1",
    "synth_strings_2",
    "choir_aahs",
    "voice_oohs",
    "synth_voice",
    "orchestra_hit",
    "trumpet",
    "trombone",
    "tuba",
    "muted_trumpet",
    "french_horn",
    "brass_section",
    "synth_brass_1",
    "synth_brass_2",
    "soprano_sax",
    "alto_sax",
    "tenor_sax",
    "baritone_sax",
    "oboe",
    "english_horn",
    "bassoon",
    "clarinet",
    "piccolo",
    "flute",
    "recorder",
    "pan_flute",
    "blown_bottle",
    "shakuhachi",
    "whistle",
    "ocarina",
    "lead_1_square",
    "lead_2_sawtooth",
    "lead_3_calliope",
    "lead_4_chiff",
    "lead_5_charang",
    "lead_6_voice",
    "lead_7_fifths",
    "lead_8_bass_lead",
    "pad_1_new_age",
    "pad_2_warm",
    "pad_3_polysynth",
    "pad_4_choir",
    "pad_5_bowed",
    "pad_6_metallic",
    "pad_7_halo",
    "pad_8_sweep",
    "fx_1_rain",
    "fx_2_soundtrack",
    "fx_3_crystal",
    "fx_4_atmosphere",
    "fx_5_brightness",
    "fx_6_goblins",
    "fx_7_echoes",
    "fx_8_sci_fi",
    "sitar",
    "banjo",
    "shamisen",
    "koto",
    "kalimba",
    "bagpipe",
    "fiddle",
    "shanai",
    "tinkle_bell",
    "agogo",
    "steel_drums",
    "woodblock",
    "taiko_drum",
    "melodic_tom",
    "synth_drum",
    "reverse_cymbal",
    "guitar_fret_noise",
    "breath_noise",
    "seashore",
    "bird_tweet",
    "telephone_ring",
    "helicopter",
    "applause",
    "gunshot",
]

# Heuristic keyword → GM program(s) mapping for Zenology preset names.
# A single preset may cover multiple GM programs; we flatten by picking the
# first match.  Extend this when you add more presets or remap them.
KEYWORD_MAP = [
    # pianos
    (r"concert.?grand|grand.?piano|stage.?piano|complete.?piano|piano", 0),
    (r"bright.*piano|soft.*suitcase|piano", 1),
    (r"electric.?grand|polysynth.*old", 2),
    (r"honky.?tonk|convex", 3),
    (r"electric.?piano.?1|ep.?1|classic.?ep|vintage.?keys", 4),
    (r"electric.?piano.?2|ep.?2|sinus|ep.?clean", 5),
    # keys / chrom perc
    (r"harpsichord|digi.?harpsi", 6),
    (r"clavinet|dirt", 7),
    (r"celesta|bell", 8),
    (r"glockenspiel|music.?box|vibraphone|fantasy.?bell", [9, 10, 11]),
    (r"marimba|woody|tinker", [12, 13]),
    (r"tubular.?bells|belle", 14),
    (r"dulcimer|metallic", 15),
    # organs
    (r"organ.?1|drawbar|house.?organ|circus.?1", 16),
    (r"organ.?2|percussive.?organ|church", [17, 19]),
    (r"rock.?organ|organ.?3", 18),
    (r"reed.?organ", 20),
    (r"accordion|circus", 21),
    (r"harmonica", 22),
    (r"tango|butter", 23),
    # guitars
    (r"acoustic.*nylon|guitar.*nylon", 24),
    (r"acoustic.*steel|magical.?guitar", 25),
    (r"guitar.*jazz|clean.*guitar|e-guitar.*clean", 26),
    (r"electric.*guitar.*clean|clean.*e-guitar", 27),
    (r"muted.*guitar|ambient.?guitar", 28),
    (r"overdriven|synth.?guitar.?1|distorted", [29, 30]),
    (r"guitar.*harmonics|harmonics", 31),
    # bass
    (r"bass.*wide|wide.?bassline|acoustic.?bass", 32),
    (r"electric.*bass.*finger|sub.*2|bass.*finger", 33),
    (r"electric.*bass.*pick|bass.*pick|bass.*1", 34),
    (r"fretless|bass.*2", 35),
    (r"slap.*1|fm.?slap", 36),
    (r"slap.*2|bass.*3", 37),
    (r"synth.*bass.*1|square.?bass|lord.?saw", 38),
    (r"synth.*bass.*2|sub.*1|pure.?sub|saw.?lo.?fi", 39),
    # strings
    (r"violin|violini", 40),
    (r"viola|subtle.?comb", 41),
    (r"cello|anthemish", 42),
    (r"contrabass|deep.?end", 43),
    (r"tremolo|anthemish.*2", 44),
    (r"pizzicato|comb.?pluck", 45),
    (r"harp|simple.?waveguide", 46),
    (r"timpani|synth.?tom", 47),
    # ensemble
    (r"string.*ensemble.*1|juno.*60|juno-?60", 48),
    (r"ensemble.*2|sawteeth", 49),
    (r"synth.*string.*1|notched", 50),
    (r"synth.*string.*2|harsh.?saw", 51),
    (r"choir|retro.?choir", 52),
    (r"voice.*ooh|ooh", 53),
    (r"synth.*voice|synth.?choir", 54),
    (r"orchestra.*hit|tek.?stab", 55),
    # brass
    (r"trumpet|reso.?brassy|brassy", 56),
    (r"trombone|buggy", 57),
    (r"tuba|crisp.*noise", 58),
    (r"muted.*trumpet|jx.*10|jx-10", 59),
    (r"french.*horn|plastic", 60),
    (r"brass.*section|toto", 61),
    (r"synth.*brass.*1", 62),
    (r"synth.*brass.*2", 63),
    # reed
    (r"soprano|sax|tragic|baritonosaurus", [64, 66]),
    (r"alto.*sax|fake.*ethno", 65),
    (r"tenor|baritone|low.*sax", [66, 67]),
    (r"oboe|violini.*solo", 68),
    (r"english.*horn|flute.*1", 69),
    (r"bassoon|flute.*2", 70),
    (r"clarinet|soft.*space", [71, 74]),
    # pipe
    (r"piccolo|dreamy.*flute", 72),
    (r"flute|cyber.*flute", 73),
    (r"recorder|soft.*space.*oboe", 74),
    (r"pan.*flute|talky", 75),
    (r"blown.*bottle|formants", 76),
    (r"shakuhachi|smoothness", 77),
    (r"whistle|vocal.?lead", 78),
    (r"ocarina|formant.?pulse", 79),
    # synth lead
    (r"lead.*square|square", 80),
    (r"lead.*saw|moogy|sawtooth", 81),
    (r"sync.*lead|calliope", 82),
    (r"chiff|crisp.*pwm", 83),
    (r"charang|resofest", 84),
    (r"lead.*voice|classic.*lead", 85),
    (r"fifths|saw.*oct", 86),
    (r"bass.?lead|tight", 87),
    # synth pad
    (r"pad.*fm|fm.*pad|new.?age", 88),
    (r"pad.*warm|mks.?70|warm", 89),
    (r"jupiter|polysynth|pad.*jupiter", 90),
    (r"pad.*choir|choir.*pad", 91),
    (r"pad.*bell|bell.*pad", 92),
    (r"chowning|pad.*metallic", 93),
    (r"sparkly|halo", 94),
    (r"sweep|harmonic.*sweep", 95),
    # fx
    (r"rain|radio.*noise", 96),
    (r"space.*adventure|soundtrack", [97, 98]),
    (r"space.*cadet|crystal", 98),
    (r"fireworks|brightness", 100),
    (r"alien|goblin", 101),
    (r"vinyl|echoes", 102),
    (r"geiger|sci.?fi", 103),
    # ethnic
    (r"sitar|mystic", 104),
    (r"banjo|banjo.*remains", 105),
    (r"shamisen|saw.*pluck", 106),
    (r"koto|wire", 107),
    (r"kalimba|nice.*pluck", 108),
    (r"bagpipe|rundfunk", 109),
    (r"fiddle|classical", 110),
    (r"shanai|scream", 111),
    # perc
    (r"tinkle|nice.*pluck.*2", 112),
    (r"agogo|nice.*pluck.*3", 113),
    (r"steel.*drum|nice.*pluck.*4", 114),
    (r"woodblock|square.*pop", 115),
    (r"taiko|synth.*tom.*2", 116),
    (r"melodic.*tom|synth.*tom.*3", 117),
    (r"synth.*drum|verber", 118),
    (r"reverse.*cymbal|drum.*one", 119),
    # sfx
    (r"guitar.*fret|crackling", 120),
    (r"breath|harm", 121),
    (r"seashore|rather.*low", 122),
    (r"bird|bork", 123),
    (r"telephone|dtmf", 124),
    (r"helicopter|alarm", 125),
    (r"applause|busy", 126),
    (r"gunshot|damage.*dealer", 127),
    # drums
    (r"drums|drum", 128),  # fallback drum slot
]


def _resolve_gm_programs(name: str):
    """Return a non-empty list of GM program indices for a preset name."""
    import re

    n = name.lower()
    for pattern, target in KEYWORD_MAP:
        if re.search(pattern, n):
            if isinstance(target, int):
                return [target]
            return list(target)
    return [0]  # fallback: acoustic grand piano


def build_preset_list():
    """Scan ZENOLOGY_PRESETS_DIR for .fzi presets and return sorted list."""
    patterns = [
        os.path.join(ZENOLOGY_PRESETS_DIR, "*.fzi"),
        os.path.join(ZENOLOGY_PRESETS_DIR, "*", "*.exz"),
    ]
    found = {}
    for pat in patterns:
        for p in glob.glob(pat):
            base = os.path.splitext(os.path.basename(p))[0]
            if base not in found:
                found[base] = p
    items = sorted(found.items())
    return items


def load_preset(synth, preset_name: str):
    """Try to load a Zenology preset headlessly.

    Order of attempts:
      1. zen_patches/<safe>.json   — pre-dumped get_patch() output (recommended)
      2. synth.load_vst3_preset()  — only if file ends with .vstpreset
      3. None (leave init state)

    Returns True on success.
    """
    safe = preset_name.replace("/", "_").replace(" ", "_")
    patch_path = os.path.join(PATCH_DIR, f"{safe}.json")

    # 1. JSON parameter dump (the reliable headless path)
    if os.path.exists(patch_path):
        try:
            with open(patch_path) as f:
                patch = json.load(f)
            if isinstance(patch, list) and patch:
                synth.set_patch(patch)
                return True
        except Exception as e:
            print(f"  ! patch load error {patch_path}: {e}")

    # 2. .vstpreset (rare for Zenology, but try anyway)
    fzi = os.path.join(ZENOLOGY_PRESETS_DIR, f"{preset_name}.fzi")
    if os.path.exists(fzi) and fzi.endswith(".vstpreset"):
        try:
            if synth.load_vst3_preset(fzi):
                return True
        except Exception:
            pass

    # 3. No patch available — leave synth in init state
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Worker
# ─────────────────────────────────────────────────────────────────────────────
_WORKER = {}


def _init_worker():
    devnull = open(os.devnull, "w")
    old_stderr = os.dup(2)
    os.dup2(devnull.fileno(), 2)
    try:
        engine = daw.RenderEngine(SR, BUFFER_SIZE)
        synth = engine.make_plugin_processor("zen", VST_PATH)
        engine.load_graph([(synth, [])])
        _WORKER["engine"] = engine
        _WORKER["synth"] = synth
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()


def _render_program(task):
    """Render one Zenology preset.

    Returns dict with: preset_name, prog, inst_name, log, samples, regions.
    """
    preset_name, preset_path, gm_programs, samples_dir = task
    w = _WORKER
    synth = w["synth"]
    engine = w["engine"]
    log = []

    loaded = load_preset(synth, preset_name)
    if not loaded:
        log.append(f"no patch → init state")
    else:
        log.append("patch loaded")

    # Pick first matching GM program for naming
    prog = gm_programs[0]
    inst_name = GM_NAMES[prog] if prog < len(GM_NAMES) else f"zen_{prog}"

    rendered = {}
    for idx, note in enumerate(NOTES):
        for v_idx, vel in enumerate(VELOCITIES):
            synth.clear_midi()
            synth.add_midi_note(note, vel, 0.0, DURATION)
            engine.render(DURATION + RELEASE)
            audio = engine.get_audio()
            synth.clear_midi()

            if audio.ndim == 1:
                audio = np.column_stack((audio, audio))
            elif audio.shape[0] == 2:
                audio = audio.T

            if float(np.max(np.abs(audio))) < 0.001:
                log.append(f"silent {note}v{vel}")

            rendered[(idx, v_idx)] = audio

    # Borrow fallback per-vel (same logic as sample_gm_pack_fast)
    for v_idx, vel in enumerate(VELOCITIES):
        silent = [
            i
            for i in range(len(NOTES))
            if float(np.max(np.abs(rendered[(i, v_idx)]))) < 0.001
        ]
        audible = [i for i in range(len(NOTES)) if i not in silent]
        for sidx in silent:
            if audible:
                donor = min(audible, key=lambda j: abs(j - sidx))
                rendered[(sidx, v_idx)] = rendered[(donor, v_idx)]
                log.append(f"borrow {NOTES[donor]}→{NOTES[sidx]} v{vel}")

    # Pitch detection on v127 layer
    from pitch_utils import detect_pitch_midi

    note_pitches = {}
    for idx, note in enumerate(NOTES):
        audio_v127 = rendered[(idx, 1)]
        detected = detect_pitch_midi(audio_v127, SR)
        note_pitches[idx] = detected if detected is not None else note

    # Clamp consecutive identical pitches
    kept = []
    i = 0
    while i < len(NOTES):
        run_end = i
        while run_end + 1 < len(NOTES) and note_pitches[run_end + 1] == note_pitches[i]:
            run_end += 1
        if run_end > i:
            rep = (i + run_end) // 2
            kept.append(rep)
            log.append(f"clamp {NOTES[i]}..{NOTES[run_end]} → {note_pitches[i]}")
        else:
            kept.append(i)
        i = run_end + 1

    # Build samples+regions + write WAVs
    vel_ranges = [(0, 95), (96, 127)]
    vel_xfade = [(0, 0, 85, 95), (85, 95, 127, 127)]
    samples = []
    regions = []

    for k, idx in enumerate(kept):
        note = NOTES[idx]
        lokey = 0 if k == 0 else (NOTES[kept[k - 1]] + note) // 2 + 1
        hikey = 127 if k == len(kept) - 1 else (note + NOTES[kept[k + 1]]) // 2
        actual_pitch = note_pitches[idx]

        for v_idx, vel in enumerate(VELOCITIES):
            lovel, hivel = vel_ranges[v_idx]
            xfin_lo, xfin_hi, xfout_lo, xfout_hi = vel_xfade[v_idx]
            note_name = _midi_to_note_name(note)
            sample_name = f"zen_{prog:03d}_{preset_name}_{note_name}_v{vel}.wav"
            sample_path = os.path.join(samples_dir, sample_name)
            audio = rendered[(idx, v_idx)]
            sf.write(sample_path, audio, SR, subtype="PCM_24")
            samples.append((sample_name, audio))
            regions.append(
                {
                    "sample_name": sample_name,
                    "pitch_keycenter": actual_pitch,
                    "lokey": lokey,
                    "hikey": hikey,
                    "lovel": lovel,
                    "hivel": hivel,
                    "xfin_lo": xfin_lo,
                    "xfin_hi": xfin_hi,
                    "xfout_lo": xfout_lo,
                    "xfout_hi": xfout_hi,
                }
            )

    return {
        "prog": prog,
        "inst_name": inst_name,
        "preset": preset_name,
        "log": log,
        "samples": samples,
        "regions": regions,
    }


def _midi_to_note_name(m):
    notes = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"]
    return f"{notes[m % 12]}{m // 12 - 1}"


def main():
    global ZENOLOGY_PRESETS_DIR
    parser = argparse.ArgumentParser(description="Roland Zenology → GM SFZ pack")
    parser.add_argument(
        "--presets", nargs="*", help="Subset of preset names to render (default: all)"
    )
    parser.add_argument("--preset-dir", default=ZENOLOGY_PRESETS_DIR)
    parser.add_argument("--samples-dir", default=SAMPLES_DIR)
    parser.add_argument("--instruments-dir", default=INSTRUMENTS_DIR)
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 1) - 1),
        help=f"Worker processes (default cpu-1={max(1, (os.cpu_count() or 1) - 1)})",
    )
    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="Skip presets with no patch dump instead of rendering init state",
    )
    args = parser.parse_args()

    ZENOLOGY_PRESETS_DIR = args.preset_dir

    os.makedirs(args.samples_dir, exist_ok=True)
    os.makedirs(args.instruments_dir, exist_ok=True)
    os.makedirs(PATCH_DIR, exist_ok=True)

    if not os.path.exists(VST_PATH):
        print(f"Error: Zenology VST3 not found at {VST_PATH}")
        sys.exit(1)

    all_presets = build_preset_list()
    if not all_presets:
        print(f"Error: no .fzi/.exz presets found in {ZENOLOGY_PRESETS_DIR}")
        sys.exit(1)

    if args.presets:
        name_map = {name: path for name, path in all_presets}
        selected = []
        for p in args.presets:
            if p in name_map:
                selected.append((p, name_map[p]))
            else:
                print(f"Warning: preset not found: {p}")
        all_presets = selected

    print(f"Found {len(all_presets)} Zenology presets")

    # Skip-missing filter
    tasks = []
    skipped = 0
    for name, path in all_presets:
        gm_progs = _resolve_gm_programs(name)
        patch_path = os.path.join(
            PATCH_DIR, f"{name.replace('/', '_').replace(' ', '_')}.json"
        )
        has_patch = os.path.exists(patch_path)
        if args.skip_missing and not has_patch:
            skipped += 1
            continue
        tasks.append((name, path, gm_progs, args.samples_dir))

    if skipped:
        print(f"Skipped {skipped} presets (no patch dump found)")

    from multiprocessing import Pool

    master_sfz = "zenology_gm.sfz"
    indiv_dir = args.instruments_dir

    # Pre-create master SFZ control header
    with open(master_sfz, "w") as mf:
        mf.write("// Zenology GM Pack\n")
        mf.write("// Generated from Roland Zenology Pro presets\n\n")
        mf.write("<control>\n")
        mf.write(f"default_path={args.samples_dir}/\n\n")

    t0 = time.perf_counter()
    completed = 0

    with Pool(processes=args.workers, initializer=_init_worker) as pool:
        for result in pool.imap(_render_program, tasks):
            completed += 1
            prog = result["prog"]
            inst = result["inst_name"]
            print(
                f"[{completed}/{len(tasks)}] prog {prog:03d} {inst} "
                f"({result['preset']})  {' | '.join(result['log'])}"
            )

            # Individual SFZ
            indiv_path = os.path.join(indiv_dir, f"zen_{prog:03d}_{inst}.sfz")
            with open(indiv_path, "w") as f:
                f.write(f"// Zenology preset: {result['preset']} → GM {prog} {inst}\n")
                f.write("<control>\n")
                f.write(f"default_path=../{args.samples_dir}/\n\n")
                f.write(f"<group>\nprg_num={prog}\n")
                for r in result["regions"]:
                    xf = (
                        f" xfin_lovel={r['xfin_lo']} xfin_hivel={r['xfin_hi']}"
                        f" xfout_lovel={r['xfout_lo']} xfout_hivel={r['xfout_hi']}"
                    )
                    base = (
                        f"pitch_keycenter={r['pitch_keycenter']}"
                        f" lokey={r['lokey']} hikey={r['hikey']}"
                        f" lovel={r['lovel']} hivel={r['hivel']}{xf}"
                    )
                    f.write(f"<region> sample={r['sample_name']} {base}\n")

            # Master SFZ append
            with open(master_sfz, "a") as mf:
                mf.write(f"<group>\nprg_num={prog}\n")
                for r in result["regions"]:
                    xf = (
                        f" xfin_lovel={r['xfin_lo']} xfin_hivel={r['xfin_hi']}"
                        f" xfout_lovel={r['xfout_lo']} xfout_hivel={r['xfout_hi']}"
                    )
                    base = (
                        f"pitch_keycenter={r['pitch_keycenter']}"
                        f" lokey={r['lokey']} hikey={r['hikey']}"
                        f" lovel={r['lovel']} hivel={r['hivel']}{xf}"
                    )
                    mf.write(f"<region> sample={r['sample_name']} {base}\n")

    elapsed = time.perf_counter() - t0
    print(f"\nDone! {completed} presets rendered in {elapsed:.1f}s → {master_sfz}")
    print(f"Master SFZ: {master_sfz}")
    print(f"Instruments: {indiv_dir}/")
    print(f"Samples:     {args.samples_dir}/")


if __name__ == "__main__":
    main()
