#!/usr/bin/env python3
"""
Dexed GM Pack — renders GM melodic instruments (slots 0-95) from DX7/Dexed
FM synthesis, using hand-picked DX7 voices from the DX7_AllTheWeb SYX
collection.

This is the Dexed counterpart to sample_gm_pack.py (which uses Surge XT).
Dexed is a DX7 emulator; its strength is classic 1980s FM pianos, electric
pianos, bells, brass, and synth leads — NOT acoustic instruments. Slots
0-95 are covered; drums and FX (96-127) are not (Dexed has no drum kit).

Each GM slot maps to a specific DX7 voice: a (syx_file, voice_slot) pair.
The SYX file is loaded via dexed.load_state(); for 32-voice banks the
voice_slot is selected via MIDI program_change.

Output goes to Dexed_MIDI_* directories, completely separate from the
Surge pack (General_MIDI_*).
"""

import os
import sys
import glob
import numpy as np
import soundfile as sf
import mido
import dawdreamer as daw
from pitch_utils import detect_pitch_midi, detect_pitch_midi_loudest

DEXED_PATH = "/Library/Audio/Plug-Ins/VST3/Dexed.vst3"
SYX_ROOT = "/Users/password9090/Downloads/DX7_AllTheWeb"

SAMPLE_RATE = 44100
BUFFER_SIZE = 512
NOTES_TO_SAMPLE = [24, 36, 48, 60, 72, 84, 96, 108]  # C1-C8
VELOCITIES = [64, 127]
VEL_RANGES = [(0, 95), (96, 127)]
VEL_XFADE = [(0, 0, 85, 95), (85, 95, 127, 127)]
DURATION = 1.0
RELEASE = 0.5
TOTAL_DURATION = DURATION + RELEASE

# 96 GM melodic instrument names (slots 0-95)
GM_NAMES = [
    "acoustic_grand_piano","bright_acoustic_piano","electric_grand_piano","honky_tonk_piano",
    "electric_piano_1","electric_piano_2","harpsichord","clavinet",
    "celesta","glockenspiel","music_box","vibraphone","marimba","xylophone","tubular_bells","dulcimer",
    "drawbar_organ","percussive_organ","rock_organ","church_organ","reed_organ","accordion","harmonica","tango_accordion",
    "acoustic_guitar_nylon","acoustic_guitar_steel","electric_guitar_jazz","electric_guitar_clean",
    "electric_guitar_muted","overdriven_guitar","distorted_guitar","guitar_harmonics",
    "acoustic_bass","electric_bass_finger","electric_bass_pick","fretless_bass","slap_bass_1","slap_bass_2","synth_bass_1","synth_bass_2",
    "violin","viola","cello","contrabass","tremolo_strings","pizzicato_strings","orchestral_harp","timpani",
    "string_ensemble_1","string_ensemble_2","synth_strings_1","synth_strings_2","choir_aahs","voice_oohs","synth_voice","orchestra_hit",
    "trumpet","trombone","tuba","muted_trumpet","french_horn","brass_section","synth_brass_1","synth_brass_2",
    "soprano_sax","alto_sax","tenor_sax","baritone_sax","oboe","english_horn","bassoon","clarinet",
    "piccolo","flute","recorder","pan_flute","blown_bottle","shakuhachi","whistle","ocarina",
    "lead_1_square","lead_2_sawtooth","lead_3_calliope","lead_4_chiff","lead_5_charang","lead_6_voice","lead_7_fifths","lead_8_bass_lead",
    "pad_1_new_age","pad_2_warm","pad_3_polysynth","pad_4_choir","pad_5_bowed","pad_6_metallic","pad_7_halo","pad_8_sweep",
]


def build_dexed_mapping():
    """Map each GM slot (0-95) to a (syx_basename, voice_slot, label) tuple.

    Curated from scanning 8526 DX7 SYX banks in DX7_AllTheWeb for voice names
    matching each GM instrument family. Prefers clean/canonical DX7 voices
    (E.PIANO, BRASS SEC, MARIMBA, etc.) over obscure user patches.
    """
    mapping = {
        # Pianos 0-7
        0: ("GERRY1.SYX", 10), 1: ("SYST_AA.SYX", 27), 2: ("TX7-07B.SYX", 13),
        3: ("DXOC01.SYX", 19), 4: ("PIANO-09.SYX", 13), 5: ("SYST_EE.SYX", 9),
        6: ("DXOC01.SYX", 29), 7: ("DUITSL.SYX", 4),
        # Chrom Perc 8-15
        8: ("DEMO2_A.SYX", 30), 9: ("DXOC02.SYX", 26), 10: ("NEWFI199.SYX", 16),
        11: ("GERRY1.SYX", 21), 12: ("SYST_CC.SYX", 11), 13: ("TX7-69.SYX", 10),
        14: ("NEWFI199.SYX", 16), 15: ("INCONI24.SYX", 21),
        # Organ 16-23
        16: ("YAMAHA21.SYX", 20), 17: ("ORGAN01.SYX", 17), 18: ("DX7_A3.SYX", 22),
        19: ("SYST_D.SYX", 20), 20: ("ORGAN-34.SYX", 18), 21: ("WIND--01.SYX", 9),
        22: ("WIND--01.SYX", 2), 23: ("NEWFI323.SYX", 6),
        # Guitar 24-31
        24: ("GUITAR01.SYX", 8), 25: ("STUDIO.SYX", 13), 26: ("NEWFIL53.SYX", 19),
        27: ("TX2.SYX", 24), 28: ("TX2.SYX", 25), 29: ("TX2.SYX", 26),
        30: ("INCONI05.SYX", 23), 31: ("INCONI45.SYX", 17),
        # Bass 32-39
        32: ("libra_1.SYX", 2), 33: ("BASS--01.SYX", 7), 34: ("BASS--13.SYX", 13),
        35: ("BASS--09.SYX", 29), 36: ("BASS--01.SYX", 7), 37: ("BASS--15.SYX", 25),
        38: ("NEWFI304.SYX", 29), 39: ("SYNTH-23.SYX", 0),
        # Strings 40-47
        40: ("Strings1.SYX", 2), 41: ("NEWFIL15.SYX", 24), 42: ("SYST_CC.SYX", 5),
        43: ("STRING17.SYX", 20), 44: ("FLNGRODE.SYX", 31), 45: ("STRING19.SYX", 19),
        46: ("YAMAHA10.SYX", 22), 47: ("BANGERS.SYX", 14),
        # Ensemble 48-55
        48: ("YAMAHA06.SYX", 5), 49: ("YAMAHA12.SYX", 27), 50: ("NEWFI320.SYX", 8),
        51: ("NEWFI320.SYX", 8), 52: ("VOICES01.SYX", 15), 53: ("VOICES09.SYX", 27),
        54: ("VOICES01.SYX", 18), 55: ("ORCHES01.SYX", 11),
        # Brass 56-63
        56: ("BRASS-01.SYX", 8), 57: ("BRASS-01.SYX", 7), 58: ("SYST_GG.SYX", 30),
        59: ("BRASS-01.SYX", 9), 60: ("BRASS-01.SYX", 3), 61: ("COMBOS2.SYX", 24),
        62: ("YAMAHA08.SYX", 27), 63: ("YAMAHA08.SYX", 27),
        # Reed 64-71
        64: ("SYST_GG.SYX", 4), 65: ("STUDIO.SYX", 10), 66: ("NEWFI324.SYX", 28),
        67: ("BRASS-20.SYX", 29), 68: ("WIND--01.SYX", 3), 69: ("INCONI35.SYX", 18),
        70: ("WIND--01.SYX", 0), 71: ("SYST_CC.SYX", 25),
        # Pipe 72-79
        72: ("SYST_GG.SYX", 12), 73: ("SYST_GG.SYX", 22), 74: ("WIND--05.SYX", 10),
        75: ("TIMFAV3.SYX", 25), 76: ("GARRETT7.SYX", 21), 77: ("TX7-08C.SYX", 15),
        78: ("TX7-37B.SYX", 4), 79: ("INCONI66.SYX", 3),
        # Lead 80-87
        80: ("DX7_A3.SYX", 13), 81: ("NEWFIL53.SYX", 16), 82: ("SYST_CC.SYX", 11),
        83: ("074.SYX", 16), 84: ("DXOC02.SYX", 11), 85: ("VOICES01.SYX", 18),
        86: ("INCONI08.SYX", 6), 87: ("BASS--21.SYX", 21),
        # Pad 88-95
        88: ("SYNTH-27.SYX", 12), 89: ("CJSP5.SYX", 22), 90: ("SYNTH-09.SYX", 22),
        91: ("VOICES01.SYX", 15), 92: ("INCONI18.SYX", 14), 93: ("SYST_CC.SYX", 25),
        94: ("TX13.SYX", 17), 95: ("INCONI09.SYX", 13),
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


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(DEXED_PATH):
        print(f"Error: Dexed not found at {DEXED_PATH}")
        sys.exit(1)

    samples_dir = os.path.join(project_root, "Dexed_MIDI_samples")
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
        dexed = engine.make_plugin_processor("dexed", DEXED_PATH)
        engine.load_graph([(dexed, [])])
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()

    # Use absolute paths everywhere — Dexed's load_state() changes the
    # process working directory to its own data folder, which would break
    # all relative file writes below.
    master_path = os.path.join(project_root, "Dexed_MIDI.sfz")
    sfizz_path = os.path.join(project_root, "Dexed_MIDI_sfizz.sfz")
    sfizz_proc_path = os.path.join(project_root, "Dexed_MIDI_sfizz_processed.sfz")

    master_f = open(master_path, "w")
    sfizz_f = open(sfizz_path, "w")
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
        inst_name = GM_NAMES[slot]
        syx_basename = os.path.basename(syx_path)

        print(f"[{idx+1}/{total}] slot {slot:02d} {inst_name} ({syx_basename} v{voice_slot})...")

        # Load SYX bank/voice
        dexed.clear_midi()
        dexed.load_state(syx_path)
        # Select voice slot via program_change
        mid = mido.MidiFile()
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.Message('program_change', program=voice_slot, time=0))
        tmp = f"/tmp/dexed_pc_{slot}.mid"
        mid.save(tmp)
        dexed.load_midi(tmp, all_events=True)
        engine.render(0.5)  # settle
        dexed.clear_midi()
        os.remove(tmp)

        # Render notes
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

        # Silent fallback: borrow nearest audible
        for v_idx, vel in enumerate(VELOCITIES):
            silent = [i for i in range(len(NOTES_TO_SAMPLE))
                      if float(np.max(np.abs(rendered[(i, v_idx)]))) < 0.001]
            audible = [i for i in range(len(NOTES_TO_SAMPLE)) if i not in silent]
            if silent and audible:
                for sidx in silent:
                    donor = min(audible, key=lambda j: abs(j - sidx))
                    rendered[(sidx, v_idx)] = rendered[(donor, v_idx)]

        # Pitch detection (v127)
        note_pitches = {}
        for n_idx, note in enumerate(NOTES_TO_SAMPLE):
            det = detect_pitch_midi(rendered[(n_idx, 1)], SAMPLE_RATE)
            note_pitches[n_idx] = det if det is not None else note

        # Clamp detection
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
                print(f"  ~ clamp: {midi_to_note_name(NOTES_TO_SAMPLE[i])}.."
                      f"{midi_to_note_name(NOTES_TO_SAMPLE[run_end])} -> "
                      f"{midi_to_note_name(NOTES_TO_SAMPLE[rep])}")
            else:
                kept.append(i)
            i = run_end + 1

        # Write individual SFZ
        indiv_path = os.path.join(instruments_dir, f"gm_{slot:03d}_{inst_name}.sfz")
        indiv_f = open(indiv_path, "w")
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
                lovel, hivel = VEL_RANGES[v_idx]
                xfin_lo, xfin_hi, xfout_lo, xfout_hi = VEL_XFADE[v_idx]
                note_name = midi_to_note_name(note)
                sample_name = f"gm_{slot:03d}_{note_name}_v{vel}.wav"
                audio = rendered[(n_idx, v_idx)]

                sf.write(os.path.join(samples_dir, sample_name), audio,
                         SAMPLE_RATE, subtype='PCM_24')

                xf = (f" xfin_lovel={xfin_lo} xfin_hivel={xfin_hi}"
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

    master_f.close()
    sfizz_f.close()
    sfizz_proc_f.close()
    print(f"\n✓ Dexed GM pack complete! {total} slots rendered → {samples_dir}/")


if __name__ == "__main__":
    main()
