#!/usr/bin/env python3
"""
Dexed GM Pack — renders GM melodic instruments (slots 0-95) from DX7/Dexed
FM synthesis, using hand-picked DX7 voices from the DX7_AllTheWeb SYX
collection (13 193 banks, 30 000+ unique voice names scanned).

Voice selection: curated by scanning actual voice names — every slot maps to
a voice whose name closely matches the GM instrument (e.g. "TRUMPET",
"CELLO", "PICK BASS"), not just a vague bank/slot guess.

Post-processing: light hall reverb + high-shelf brightness boost applied to
every sample, making the dry FM signal warmer and more present in a mix.

Output goes to Dexed_MIDI_* directories (separate from the Surge pack).
Slot 128 (MIDI ch10, GM drum kit) is appended from KSHMR Vol.5 samples.
"""

import os
import sys
import glob
import numpy as np
import soundfile as sf
import mido
import dawdreamer as daw
from pitch_utils import detect_pitch_midi

DEXED_PATH = "/Library/Audio/Plug-Ins/VST3/Dexed.vst3"
SYX_ROOT   = "/Users/password9090/Downloads/DX7_AllTheWeb"

SAMPLE_RATE    = 44100
BUFFER_SIZE    = 512
NOTES_TO_SAMPLE = [24, 36, 48, 60, 72, 84, 96, 108]   # C1–C8
VELOCITIES     = [64, 127]
VEL_RANGES     = [(0, 95), (96, 127)]
VEL_XFADE      = [(0, 0, 85, 95), (85, 95, 127, 127)]
DURATION       = 2.0    # longer → FM envelopes fully develop
RELEASE        = 1.0    # tail for decay-type instruments
TOTAL_DURATION = DURATION + RELEASE


# ── GM Drum Kit ──────────────────────────────────────────────────────────────
DRUM_NOTES = [
    (35, "Acoustic Bass Drum"), (36, "Bass Drum 1"),    (37, "Side Stick"),
    (38, "Acoustic Snare"),     (39, "Hand Clap"),       (40, "Electric Snare"),
    (41, "Low Floor Tom"),      (42, "Closed Hi-Hat"),   (43, "High Floor Tom"),
    (44, "Pedal Hi-Hat"),       (45, "Low Tom"),         (46, "Open Hi-Hat"),
    (47, "Low-Mid Tom"),        (48, "Hi-Mid Tom"),      (49, "Crash Cymbal 1"),
    (50, "High Tom"),           (51, "Ride Cymbal 1"),   (52, "Chinese Cymbal"),
    (53, "Ride Bell"),          (54, "Tambourine"),      (55, "Splash Cymbal"),
    (56, "Cowbell"),            (57, "Crash Cymbal 2"),  (58, "Vibraslap"),
    (59, "Ride Cymbal 2"),      (60, "Hi Bongo"),        (61, "Low Bongo"),
    (62, "Mute Hi Conga"),      (63, "Open Hi Conga"),   (64, "Low Conga"),
    (65, "High Timbale"),       (66, "Low Timbale"),     (67, "High Agogo"),
    (68, "Low Agogo"),          (69, "Cabasa"),          (70, "Maracas"),
    (71, "Short Whistle"),      (72, "Long Whistle"),    (73, "Short Guiro"),
    (74, "Long Guiro"),         (75, "Claves"),          (76, "Hi Wood Block"),
    (77, "Low Wood Block"),     (78, "Mute Cuica"),      (79, "Open Cuica"),
    (80, "Mute Triangle"),      (81, "Open Triangle"),
]


def write_drum_section(f, drum_samples_dir):
    """Append a GM Drum Kit section (ch10, N35-N81) to an open SFZ file."""
    f.write("\n")
    f.write("// ─── GM Drum Kit (channel 10 / MIDI ch 9) ─────────────────────────────────\n")
    f.write("// KSHMR Vol.5 samples, N35-N81, 2 velocity layers\n")
    f.write("<group>\n")
    f.write("lokey=0 hikey=127 lochan=10 hichan=10\n")
    f.write("ampeg_attack=0.001 ampeg_release=0.05\n")
    f.write("\n")
    written = 0
    for note, name in DRUM_NOTES:
        p64  = os.path.join(drum_samples_dir, f"gm_drum_N{note}_v064.wav")
        p127 = os.path.join(drum_samples_dir, f"gm_drum_N{note}_v127.wav")
        if not (os.path.exists(p64) and os.path.exists(p127)):
            continue
        f.write(f"// {note} — {name}\n")
        f.write(f"<region> sample={p64}  lokey={note} hikey={note} lovel=0   hivel=80\n")
        f.write(f"<region> sample={p127} lokey={note} hikey={note} lovel=81  hivel=127\n")
        written += 1
    print(f"  drum section: {written} notes written ({written*2} regions)")
    return written


# ── 96 GM melodic instrument names ───────────────────────────────────────────
GM_NAMES = [
    "acoustic_grand_piano", "bright_acoustic_piano", "electric_grand_piano", "honky_tonk_piano",
    "electric_piano_1", "electric_piano_2", "harpsichord", "clavinet",
    "celesta", "glockenspiel", "music_box", "vibraphone", "marimba", "xylophone", "tubular_bells", "dulcimer",
    "drawbar_organ", "percussive_organ", "rock_organ", "church_organ", "reed_organ", "accordion", "harmonica", "tango_accordion",
    "acoustic_guitar_nylon", "acoustic_guitar_steel", "electric_guitar_jazz", "electric_guitar_clean",
    "electric_guitar_muted", "overdriven_guitar", "distorted_guitar", "guitar_harmonics",
    "acoustic_bass", "electric_bass_finger", "electric_bass_pick", "fretless_bass",
    "slap_bass_1", "slap_bass_2", "synth_bass_1", "synth_bass_2",
    "violin", "viola", "cello", "contrabass", "tremolo_strings", "pizzicato_strings", "orchestral_harp", "timpani",
    "string_ensemble_1", "string_ensemble_2", "synth_strings_1", "synth_strings_2",
    "choir_aahs", "voice_oohs", "synth_voice", "orchestra_hit",
    "trumpet", "trombone", "tuba", "muted_trumpet", "french_horn", "brass_section", "synth_brass_1", "synth_brass_2",
    "soprano_sax", "alto_sax", "tenor_sax", "baritone_sax", "oboe", "english_horn", "bassoon", "clarinet",
    "piccolo", "flute", "recorder", "pan_flute", "blown_bottle", "shakuhachi", "whistle", "ocarina",
    "lead_1_square", "lead_2_sawtooth", "lead_3_calliope", "lead_4_chiff", "lead_5_charang",
    "lead_6_voice", "lead_7_fifths", "lead_8_bass_lead",
    "pad_1_new_age", "pad_2_warm", "pad_3_polysynth", "pad_4_choir",
    "pad_5_bowed", "pad_6_metallic", "pad_7_halo", "pad_8_sweep",
]


def build_dexed_mapping():
    """Map each GM slot (0-95) to a (syx_basename, voice_slot) tuple.

    Every voice name was verified by scanning the DX7_AllTheWeb collection
    (11 647 banks, 30 101 unique names). The voice name is shown in the comment.
    """
    mapping = {
        # ── Pianos (0-7) ──────────────────────────────────────────────────────
        0:  ("PIANO-09.SYX",               13),  # E.PIANO 1       → Acoustic Grand
        1:  ("106.syx",                    14),  # E.PIANO 2       → Bright Piano
        2:  ("NEWFI104.SYX",               22),  # ELEC.PIANO      → Electric Grand
        3:  ("PIANO-10.SYX",                17),  # HONKY-TONK      → Honky-Tonk
        4:  ("ePian-22.syx",                2),  # E.PIANO 1       → EP 1 (DX7 classic)
        5:  ("ePian-23.syx",               22),  # E.PIANO 5       → EP 2 (bell EP)
        6:  ("SIMS98.SYX",                 18),  # HARPSICH98      → Harpsichord
        7:  ("CLAV08.SYX",               0),  # CLAVINET        → Clavinet
        # ── Chromatic Percussion (8-15) ───────────────────────────────────────
        8:  ("DEMO2_A.SYX",                30),  # CELESTA         → Celesta
        9:  ("PERCDANZ.SYX",                22),  # GLOCKEN         → Glockenspiel
       10:  ("NEWFI199.SYX",               15),  # Music Box       → Music Box
       11:  ("ePian-18.syx",               16),  # VibraPhone      → Vibraphone
       12:  ("CHROMA17.SYX",               13),  # MARIMBA         → Marimba
       13:  ("CHROMA10.SYX",               27),  # XYLOPHONE       → Xylophone
       14:  ("TX7-21.SYX",                 20),  # Tubular         → Tubular Bells
       15:  ("TIMFAV4.SYX",                15),  # DULCIMER        → Dulcimer
        # ── Organs (16-23) ────────────────────────────────────────────────────
       16:  ("ORGAN-42.SYX",               22),  # ORGAN 1         → Drawbar Organ
       17:  ("ORGAN-33.SYX",                6),  # PERC ORGN2      → Percussive Organ
       18:  ("ORGAN-44.SYX",               10),  # ROCK ORGAN      → Rock Organ
       19:  ("ORGAN_2.SYX",                15),  # CHURCH          → Church Organ
       20:  ("ORGAN-34.SYX",               18),  # REED ORGAN      → Reed Organ
       21:  ("WIND--01.SYX",               10),  # ACCORDION       → Accordion
       22:  ("DXTX_P01.SYX",               28),  # Harmonica       → Harmonica
       23:  ("BEST03.SYX",                 27),  # BANDONEON       → Tango Accordion
        # ── Guitar (24-31) ────────────────────────────────────────────────────
       24:  ("STANOS93.SYX",               29),  # NYLON GTR       → Nylon Guitar
       25:  ("NEWFI285.SYX",               19),  # Steel Gtr1      → Steel Guitar
       26:  ("NEWFIL53.SYX",               19),  # BRJAZZ GTR      → Jazz Guitar
       27:  ("GUITAR02.SYX",                1),  # E.GUITAR B      → Clean Guitar
       28:  ("DRUMS11.SYX",                13),  # Muted           → Muted Guitar
       29:  ("ShofukuExtra(1-32).syx",     17),  # OverdrivEB      → Overdriven Guitar
       30:  ("SYNTH013.SYX",               18),  # DISTORTION      → Distorted Guitar
       31:  ("TX7-68C.SYX",                15),  # Harm.Clang      → Guitar Harmonics
        # ── Bass (32-39) ──────────────────────────────────────────────────────
       32:  ("BASS--01.SYX",               20),  # Ac.Bass*5       → Acoustic Bass
       33:  ("BASS--09.SYX",                0),  # E.BASS 1        → Finger Bass
       34:  ("BASS--13.SYX",               13),  # PICK BASS       → Pick Bass
       35:  ("BASS--09.SYX",               29),  # FRETLESS        → Fretless Bass
       36:  ("BASS--15.SYX",               18),  # slap bass       → Slap Bass 1
       37:  ("BASS--19.SYX",               24),  # THUMB BASS      → Slap Bass 2
       38:  ("NEWFI305.SYX",                7),  # SYN BASS 2      → Synth Bass 1
       39:  ("DX66.SYX",                   11),  # SYN BASS 2      → Synth Bass 2
        # ── Strings (40-47) ───────────────────────────────────────────────────
       40:  ("VIOLIN01.SYX",                0),  # VIOLIN          → Violin
       41:  ("STRINGS.SYX",               16),  # VIOLA           → Viola
       42:  ("STRING15.SYX",               16),  # CELLO           → Cello
       43:  ("DX7_A6.SYX",               9),  # CONTRABASS      → Contrabass
       44:  ("FLNGRODE.SYX",               31),  # TREMOLO RH      → Tremolo Strings
       45:  ("STRING08.SYX",               24),  # PIZZICATO       → Pizzicato Strings
       46:  ("DXTX_P01.SYX",               29),  # Harp            → Orchestral Harp
       47:  ("INCONI98.SYX",               20),  # timpani         → Timpani
        # ── Ensemble (48-55) ──────────────────────────────────────────────────
       48:  ("STRING05.SYX",                5),  # STRINGS         → String Ensemble 1
       49:  ("STRING09.SYX",               20),  # SLOW STRNG      → String Ensemble 2
       50:  ("SYNTH-16.SYX",               12),  # SYNTH STRN      → Synth Strings 1
       51:  ("DX7_CPP.SYX",                 9),  # POLY STRGS      → Synth Strings 2
       52:  ("DXTX_P02.SYX",               28),  # Choir           → Choir Aahs
       53:  ("INCON104.SYX",                3),  # VOICES          → Voice Oohs
       54:  ("Cjsp1.syx",                  28),  # SYNVOXINE       → Synth Voice
       55:  ("ORCHES01.SYX",               13),  # ORCH.HIT13      → Orchestra Hit
        # ── Brass (56-63) ─────────────────────────────────────────────────────
       56:  ("BRASS-02.SYX",                23),  # TRUMPET         → Trumpet
       57:  ("DXTX_P07.SYX",               18),  # TROMBONE        → Trombone
       58:  ("BRASS-20.SYX",                3),  # TUBA            → Tuba
       59:  ("BRASS-19.SYX",               14),  # TRUMPET (cup)   → Muted Trumpet
       60:  ("BRASS-09.SYX",                9),  # FR.HORN R1      → French Horn
       61:  ("BRASS-03.SYX",               30),  # BRASS 1         → Brass Section
       62:  ("SYNTH-22.SYX",               4),  # SYN BRASS       → Synth Brass 1
       63:  ("BRASS-10.SYX",               15),  # Polybrass       → Synth Brass 2
        # ── Reed (64-71) ──────────────────────────────────────────────────────
       64:  ("DXTX_P01.SYX",               27),  # Sax             → Soprano Sax
       65:  ("BRASS-20.SYX",               27),  # ALTO SAXBC      → Alto Sax
       66:  ("NEWFI324.SYX",               28),  # TENOR SAX       → Tenor Sax
       67:  ("BRASS-20.SYX",               29),  # BARI SAX        → Baritone Sax
       68:  ("WIND--03.SYX",               30),  # OBOE            → Oboe
       69:  ("INCONI35.SYX",               18),  # ENGLISH 01      → English Horn
       70:  ("WIND--01.SYX",               27),  # BASSOON         → Bassoon
       71:  ("WIND--02.SYX",               12),  # Clarinet        → Clarinet
        # ── Pipe (72-79) ──────────────────────────────────────────────────────
       72:  ("WIND--04.SYX",               22),  # PICCOLO         → Piccolo
       73:  ("Flutes02.syx",                3),  # FLUTE           → Flute
       74:  ("WIND--05.SYX",               10),  # RECORDER        → Recorder
       75:  ("33.syx",                      8),  # PAN FLUTE       → Pan Flute
       76:  ("INCONI60.SYX",                21),  # BottleFlt3      → Blown Bottle
       77:  ("TX7-08C.SYX",                15),  # Shakuhachi      → Shakuhachi
       78:  ("INCON106.SYX",                1),  # WHISTLE         → Whistle
       79:  ("INCONI66.SYX",                3),  # OCARINA         → Ocarina
        # ── Lead (80-87) ──────────────────────────────────────────────────────
       80:  ("Ultimate DX7 - LEAD.syx",    28),  # SQUARE          → Lead 1 Square
       81:  ("INCONI79.SYX",               23),  # SAWTOOTH .      → Lead 2 Sawtooth
       82:  ("17.syx",               24),  # SYN-LEAD 3      → Lead 3 Calliope
       83:  ("PIANO-07.SYX",               23),  # ChiffPiano      → Lead 4 Chiff
       84:  ("TX3.SYX",                    21),  # CHARANGO        → Lead 5 Charang
       85:  ("Cjsp1.syx",                  28),  # SYNVOXINE       → Lead 6 Voice
       86:  ("INCONI38.SYX",                9),  # FIFTHS          → Lead 7 Fifths
       87:  ("BASS--19.SYX",               17),  # SYNTH BASS      → Lead 8 Bass+Lead
        # ── Pad (88-95) ───────────────────────────────────────────────────────
       88:  ("STANOS92.SYX",               10),  # New Age         → Pad 1 New Age
       89:  ("SYNTH-25.SYX",                5),  # WARM PAD 6      → Pad 2 Warm
       90:  ("Midway1.syx",                31),  # PolySynth       → Pad 3 Polysynth
       91:  ("PADS04.SYX",                  0),  # PAD             → Pad 4 Choir
       92:  ("BASS--06.SYX",               16),  # Bowed bass      → Pad 5 Bowed
       93:  ("DX7 - madFame DX DRUMS and FX.syx", 7),  # METAL    → Pad 6 Metallic
       94:  ("DeepDX-More Pads.syx",       28),  # CEPHALOPHO      → Pad 7 Halo
       95:  ("BRASS-15.SYX",               22),  # SWEEPBRASS      → Pad 8 Sweep
    }

    # Resolve each syx basename to a full path
    resolved = {}
    cache = {}
    for slot, (syx_name, voice_slot) in mapping.items():
        if syx_name not in cache:
            matches = glob.glob(f"{SYX_ROOT}/**/{syx_name}", recursive=True)
            cache[syx_name] = matches[0] if matches else None
        full = cache[syx_name]
        if not full:
            raise FileNotFoundError(f"SYX not found for slot {slot}: {syx_name}")
        resolved[slot] = (full, voice_slot)
    return resolved


def midi_to_note_name(midi_num):
    notes = ['C', 'Cs', 'D', 'Ds', 'E', 'F', 'Fs', 'G', 'Gs', 'A', 'As', 'B']
    octave = (midi_num // 12) - 1
    return f"{notes[midi_num % 12]}{octave}"


def postprocess(audio: np.ndarray, sr: int) -> np.ndarray:
    """Light post-processing for DX7 samples.

    1. High-shelf boost (+3 dB above 6 kHz) — FM often sounds thin in the
       high-mids; a gentle shelf adds presence without harshness.
    2. Hall reverb (room_size=0.45, wet=0.18) — removes the completely dry
       character without drowning the attack transient.
    3. Peak normalise to 0.90.
    """
    try:
        from pedalboard import Pedalboard, Reverb, HighShelfFilter
        board = Pedalboard([
            HighShelfFilter(cutoff_frequency_hz=6000, gain_db=3.0),
            Reverb(room_size=0.45, damping=0.6, wet_level=0.18, dry_level=0.82),
        ])
        # pedalboard expects (channels, samples)
        processed = board(audio.T, sr).T
    except Exception as e:
        print(f"  [postprocess skipped: {e}]")
        processed = audio

    peak = float(np.max(np.abs(processed)))
    if peak > 1e-6:
        processed = processed * (0.90 / peak)
    return processed


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(DEXED_PATH):
        print(f"Error: Dexed not found at {DEXED_PATH}")
        sys.exit(1)

    samples_dir     = os.path.join(project_root, "Dexed_MIDI_samples")
    instruments_dir = os.path.join(project_root, "Dexed_MIDI_instruments")
    os.makedirs(samples_dir, exist_ok=True)
    os.makedirs(instruments_dir, exist_ok=True)

    print("Building DX7 voice mapping...")
    mapping = build_dexed_mapping()
    print(f"  {len(mapping)} slots mapped")

    print("Initializing Dexed engine...")
    devnull = open(os.devnull, 'w')
    old_stderr = os.dup(2)
    os.dup2(devnull.fileno(), 2)
    try:
        engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)
        dexed  = engine.make_plugin_processor("dexed", DEXED_PATH)
        engine.load_graph([(dexed, [])])
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()

    # Use absolute paths everywhere — Dexed's load_state() changes the process
    # working directory to its own data folder, breaking relative writes.
    master_path    = os.path.join(project_root, "Dexed_MIDI.sfz")
    sfizz_path     = os.path.join(project_root, "Dexed_MIDI_sfizz.sfz")
    sfizz_proc_path = os.path.join(project_root, "Dexed_MIDI_sfizz_processed.sfz")

    master_f     = open(master_path, "w")
    sfizz_f      = open(sfizz_path, "w")
    sfizz_proc_f = open(sfizz_proc_path, "w")

    for f, is_sfizz in [(master_f, False), (sfizz_f, True), (sfizz_proc_f, True)]:
        f.write("// Dexed GM Pack — DX7 FM synthesis (slots 0-95)\n")
        f.write("// 2 Velocity Layers, 8 Key Zones\n\n")
        f.write("<control>\n")
        if not is_sfizz:
            f.write(f"default_path={samples_dir}/\n")
        f.write("\n")

    total = len(mapping)
    for idx, (slot, (syx_path, voice_slot)) in enumerate(sorted(mapping.items())):
        inst_name    = GM_NAMES[slot]
        syx_basename = os.path.basename(syx_path)

        print(f"[{idx+1}/{total}] slot {slot:02d}  {inst_name}  ({syx_basename} v{voice_slot})")

        # Load SYX bank and select voice
        dexed.clear_midi()
        dexed.load_state(syx_path)
        mid   = mido.MidiFile()
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.Message('program_change', program=voice_slot, time=0))
        tmp = f"/tmp/dexed_pc_{slot}.mid"
        mid.save(tmp)
        dexed.load_midi(tmp, all_events=True)
        engine.render(0.5)       # let the program_change settle
        dexed.clear_midi()
        os.remove(tmp)

        # Render 8 notes × 2 velocities
        rendered = {}
        for n_idx, note in enumerate(NOTES_TO_SAMPLE):
            for v_idx, vel in enumerate(VELOCITIES):
                dexed.clear_midi()
                dexed.add_midi_note(note, vel, 0.0, DURATION)
                engine.render(TOTAL_DURATION)
                audio = engine.get_audio()
                dexed.clear_midi()
                if audio.ndim == 1:
                    audio = np.column_stack((audio, audio))
                elif audio.shape[0] == 2:
                    audio = audio.T
                rendered[(n_idx, v_idx)] = audio

        # Silent fallback: borrow nearest audible note
        for v_idx in range(len(VELOCITIES)):
            silent  = [i for i in range(len(NOTES_TO_SAMPLE))
                       if float(np.max(np.abs(rendered[(i, v_idx)]))) < 0.001]
            audible = [i for i in range(len(NOTES_TO_SAMPLE)) if i not in silent]
            if silent and audible:
                for sidx in silent:
                    donor = min(audible, key=lambda j: abs(j - sidx))
                    rendered[(sidx, v_idx)] = rendered[(donor, v_idx)]

        # Post-process all rendered buffers
        for key in list(rendered.keys()):
            rendered[key] = postprocess(rendered[key], SAMPLE_RATE)

        # Pitch detection on v127 layer
        note_pitches = {}
        for n_idx, note in enumerate(NOTES_TO_SAMPLE):
            det = detect_pitch_midi(rendered[(n_idx, 1)], SAMPLE_RATE)
            note_pitches[n_idx] = det if det is not None else note

        # Clamp: collapse runs of identical detected pitches
        kept = []
        i = 0
        while i < len(NOTES_TO_SAMPLE):
            run_end = i
            while (run_end + 1 < len(NOTES_TO_SAMPLE)
                   and note_pitches[run_end + 1] == note_pitches[i]):
                run_end += 1
            if run_end > i:
                rep = (i + run_end) // 2
                kept.append(rep)
                print(f"  ~ clamp {midi_to_note_name(NOTES_TO_SAMPLE[i])}.."
                      f"{midi_to_note_name(NOTES_TO_SAMPLE[run_end])} → "
                      f"{midi_to_note_name(NOTES_TO_SAMPLE[rep])}")
            else:
                kept.append(i)
            i = run_end + 1

        # Write individual SFZ
        indiv_path = os.path.join(instruments_dir, f"gm_{slot:03d}_{inst_name}.sfz")
        indiv_f    = open(indiv_path, "w")
        indiv_f.write(f"// GM Program {slot}: {inst_name} (Dexed/DX7)\n")
        indiv_f.write("<control>\n")
        indiv_f.write(f"default_path={samples_dir}/\n\n")
        indiv_f.write(f"<group>\nprg_num={slot}\n")

        master_f.write(f"<group>\nprg_num={slot}\n")
        sfizz_f.write(f"<group>\nloprog={slot} hiprog={slot}\n")
        sfizz_proc_f.write(f"<group>\nloprog={slot} hiprog={slot}\n")

        for k, n_idx in enumerate(kept):
            note = NOTES_TO_SAMPLE[n_idx]
            if k == 0:
                lokey = 0
            else:
                lokey = (NOTES_TO_SAMPLE[kept[k-1]] + note) // 2 + 1
            if k == len(kept) - 1:
                hikey = 127
            else:
                hikey = (note + NOTES_TO_SAMPLE[kept[k+1]]) // 2
            actual_pitch = note_pitches[n_idx]

            for v_idx, vel in enumerate(VELOCITIES):
                lovel, hivel                     = VEL_RANGES[v_idx]
                xfin_lo, xfin_hi, xfout_lo, xfout_hi = VEL_XFADE[v_idx]
                note_name   = midi_to_note_name(note)
                sample_name = f"gm_{slot:03d}_{note_name}_v{vel}.wav"
                audio       = rendered[(n_idx, v_idx)]

                sf.write(os.path.join(samples_dir, sample_name),
                         audio, SAMPLE_RATE, subtype='PCM_24')

                xf   = (f" xfin_lovel={xfin_lo} xfin_hivel={xfin_hi}"
                        f" xfout_lovel={xfout_lo} xfout_hivel={xfout_hi}")
                base = (f"pitch_keycenter={actual_pitch}"
                        f" lokey={lokey} hikey={hikey}"
                        f" lovel={lovel} hivel={hivel}{xf}")

                indiv_f.write(f"<region> sample={sample_name} {base}\n")
                master_f.write(f"<region> sample={sample_name} {base}\n")
                sfizz_f.write(f"<region> sample={samples_dir}/{sample_name} {base}\n")
                sfizz_proc_f.write(f"<region> sample={samples_dir}/{sample_name} {base}\n")

        indiv_f.close()
        master_f.write("\n")
        sfizz_f.write("\n")
        sfizz_proc_f.write("\n")

    # ── Append GM Drum Kit ───────────────────────────────────────────────────
    drum_samples_dir = os.path.join(project_root, "General_MIDI_samples_drums")
    if os.path.isdir(drum_samples_dir):
        print("\nAppending GM drum kit section...")
        write_drum_section(master_f, drum_samples_dir)
        write_drum_section(sfizz_f, drum_samples_dir)
        write_drum_section(sfizz_proc_f, drum_samples_dir)
    else:
        print(f"Warning: drum samples dir not found: {drum_samples_dir}")
        print("  Run kshmr_drum_mapping.py first to generate drum samples.")

    master_f.close()
    sfizz_f.close()
    sfizz_proc_f.close()
    print(f"\n✓ Dexed GM pack complete! {total} melodic slots + drum kit → {samples_dir}/")


if __name__ == "__main__":
    main()
