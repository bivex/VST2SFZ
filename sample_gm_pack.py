#!/usr/bin/env python3
import os
import sys
import re
import glob
import math
import numpy as np
import soundfile as sf
import dawdreamer as daw

# 128 standard GM instrument names (cleaned for filenames)
GM_NAMES = [
    "acoustic_grand_piano", "bright_acoustic_piano", "electric_grand_piano", "honky_tonk_piano", "electric_piano_1", "electric_piano_2", "harpsichord", "clavinet",
    "celesta", "glockenspiel", "music_box", "vibraphone", "marimba", "xylophone", "tubular_bells", "dulcimer",
    "drawbar_organ", "percussive_organ", "rock_organ", "church_organ", "reed_organ", "accordion", "harmonica", "tango_accordion",
    "acoustic_guitar_nylon", "acoustic_guitar_steel", "electric_guitar_jazz", "electric_guitar_clean", "electric_guitar_muted", "overdriven_guitar", "distorted_guitar", "guitar_harmonics",
    "acoustic_bass", "electric_bass_finger", "electric_bass_pick", "fretless_bass", "slap_bass_1", "slap_bass_2", "synth_bass_1", "synth_bass_2",
    "violin", "viola", "cello", "contrabass", "tremolo_strings", "pizzicato_strings", "orchestral_harp", "timpani",
    "string_ensemble_1", "string_ensemble_2", "synth_strings_1", "synth_strings_2", "choir_aahs", "voice_oohs", "synth_voice", "orchestra_hit",
    "trumpet", "trombone", "tuba", "muted_trumpet", "french_horn", "brass_section", "synth_brass_1", "synth_brass_2",
    "soprano_sax", "alto_sax", "tenor_sax", "baritone_sax", "oboe", "english_horn", "bassoon", "clarinet",
    "piccolo", "flute", "recorder", "pan_flute", "blown_bottle", "shakuhachi", "whistle", "ocarina",
    "lead_1_square", "lead_2_sawtooth", "lead_3_calliope", "lead_4_chiff", "lead_5_charang", "lead_6_voice", "lead_7_fifths", "lead_8_bass_lead",
    "pad_1_new_age", "pad_2_warm", "pad_3_polysynth", "pad_4_choir", "pad_5_bowed", "pad_6_metallic", "pad_7_halo", "pad_8_sweep",
    "fx_1_rain", "fx_2_soundtrack", "fx_3_crystal", "fx_4_atmosphere", "fx_5_brightness", "fx_6_goblins", "fx_7_echoes", "fx_8_sci_fi",
    "sitar", "banjo", "shamisen", "koto", "kalimba", "bagpipe", "fiddle", "shanai",
    "tinkle_bell", "agogo", "steel_drums", "woodblock", "taiko_drum", "melodic_tom", "synth_drum", "reverse_cymbal",
    "guitar_fret_noise", "breath_noise", "seashore", "bird_tweet", "telephone_ring", "helicopter", "applause", "gunshot"
]

def build_preset_mapping(factory_dir):
    folders = ["Basses", "Brass", "Keys", "Leads", "Pads", "Percussion", "Plucks", "Polysynths", "Winds", "FX"]
    presets_by_folder = {}
    for fld in folders:
        path = os.path.join(factory_dir, fld)
        if os.path.exists(path):
            presets_by_folder[fld.lower()] = sorted(glob.glob(os.path.join(path, "*.fxp")))

    mapping = {}
    used_presets = set()

    def get_preset(folder_name, keywords=None):
        files = presets_by_folder.get(folder_name.lower(), [])
        if not files:
            return None
        # Try matching keywords
        if keywords:
            for kw in keywords:
                for f in files:
                    if kw.lower() in os.path.basename(f).lower() and f not in used_presets:
                        used_presets.add(f)
                        return f
        # Fallback to first unused file
        for f in files:
            if f not in used_presets:
                used_presets.add(f)
                return f
        # If all used, recycle one
        return files[0] if files else None

    # Map all 128 GM slots
    for i in range(128):
        grp = i // 8
        fld = "polysynths"
        kws = None
        
        if grp == 0:  # Piano
            fld = "keys"
            if i == 0: kws = ["grand", "remains", "organ"]
            elif i == 1: kws = ["bright"]
            elif i == 4: kws = ["ep 1", "suitcase"]
            elif i == 5: kws = ["dx ep", "ep 2"]
            elif i == 6: kws = ["harpsi"]
            elif i == 7: kws = ["clav"]
        elif grp == 1:  # Chromatic Percussion
            fld = "plucks"
            if i == 8: kws = ["celesta", "bell"]
            elif i == 9: kws = ["glock"]
            elif i == 10: kws = ["box"]
            elif i == 11: kws = ["vibe"]
            elif i == 12: kws = ["marimba"]
            elif i == 13: kws = ["xylo"]
            elif i == 14: kws = ["bell"]
        elif grp == 2:  # Organ
            fld = "keys"
            kws = ["organ", "church", "circus"]
        elif grp == 3:  # Guitar
            fld = "plucks"
            kws = ["guitar", "nylon", "steel", "clean"]
        elif grp == 4:  # Bass
            fld = "basses"
            if i == 32: kws = ["acoustic", "upright"]
            elif i == 33: kws = ["finger"]
            elif i == 34: kws = ["pick"]
            elif i == 35: kws = ["fretless"]
            elif i in (36, 37): kws = ["slap"]
            else: kws = ["synth", "acid", "saw"]
        elif grp in (5, 6):  # Strings / Ensemble
            fld = "pads" if grp == 6 else "polysynths"
            kws = ["string", "violin", "cello", "ensemble", "choir", "voice", "aah", "ooh"]
        elif grp == 7:  # Brass
            fld = "brass"
            kws = ["brass", "trumpet", "horn", "section"]
        elif grp in (8, 9):  # Reed / Pipe
            fld = "winds"
            kws = ["wind", "flute", "clarinet", "sax", "oboe"]
        elif grp == 10:  # Synth Lead
            fld = "leads"
            kws = ["square", "saw", "lead", "syn"]
        elif grp == 11:  # Synth Pad
            fld = "pads"
            kws = ["pad", "warm", "sweep", "space"]
        elif grp == 12:  # Synth Effects
            fld = "fx"
            kws = ["fx", "rain", "crystal", "soundtrack"]
        elif grp == 13:  # Ethnic
            fld = "plucks"
            kws = ["sitar", "banjo", "koto", "pipe", "fiddle"]
        elif grp == 14:  # Percussive
            fld = "percussion"
            kws = ["perc", "drum", "bell", "block"]
        elif grp == 15:  # Sound Effects
            fld = "fx"
            kws = ["fx", "noise", "helicopter", "phone"]
            
        mapping[i] = get_preset(fld, kws)

    return mapping

def midi_to_note_name(midi_num):
    notes = ['C', 'Cs', 'D', 'Ds', 'E', 'F', 'Fs', 'G', 'Gs', 'A', 'As', 'B']
    octave = (midi_num // 12) - 1
    note_index = midi_num % 12
    return f"{notes[note_index]}{octave}"

def main():
    vst_path = "/Library/Audio/Plug-Ins/VST3/Surge XT.vst3"
    factory_dir = "/Library/Application Support/Surge XT/patches_factory"
    
    if not os.path.exists(vst_path):
        print(f"Error: Surge XT VST3 not found at {vst_path}")
        sys.exit(1)
        
    print("Mapping 128 GM slots to Surge XT presets...")
    preset_mapping = build_preset_mapping(factory_dir)
    
    # Directories
    samples_dir = "General_MIDI_samples"
    instruments_dir = "General_MIDI_instruments"
    os.makedirs(samples_dir, exist_ok=True)
    os.makedirs(instruments_dir, exist_ok=True)
    
    # Configure DawDreamer engine
    # Using 44100 Hz, 16-bit for lighter and standard General MIDI sizing
    sr = 44100
    engine = daw.RenderEngine(sr, 512)
    synth = engine.make_plugin_processor("synth", vst_path)
    engine.load_graph([(synth, [])])
    
    # 4 standard pitch levels across the keyboard (2 octaves apart)
    notes_to_sample = [36, 60, 84, 108]  # C2, C4, C6, C8
    duration = 1.0
    release = 0.5
    total_duration = duration + release
    
    master_sfz_path = "General_MIDI.sfz"
    print(f"Writing master SFZ: {master_sfz_path}...")
    
    with open(master_sfz_path, "w") as master_f:
        master_f.write("// General MIDI 128 Instrument Pack\n")
        master_f.write("// Generated from Surge XT factory presets\n\n")
        master_f.write("<control>\n")
        master_f.write(f"default_path={samples_dir}/\n\n")
        
        for i in range(128):
            inst_name = GM_NAMES[i]
            preset_path = preset_mapping[i]
            
            print(f"Sampling [{i:03d}/127] {inst_name} (Preset: {os.path.basename(preset_path)})...")
            
            # Load the preset state
            synth.load_state(preset_path)
            
            # Individual instrument SFZ
            indiv_sfz_path = os.path.join(instruments_dir, f"gm_{i:03d}_{inst_name}.sfz")
            with open(indiv_sfz_path, "w") as indiv_f:
                indiv_f.write(f"// GM Program {i}: {inst_name}\n")
                indiv_f.write(f"default_path=../{samples_dir}/\n\n")
                indiv_f.write("<group>\n")
                
                master_f.write(f"// GM Program {i}: {inst_name}\n")
                master_f.write("<group>\n")
                master_f.write(f"prg_num={i}\n")
                
                # Sample the 4 notes
                for idx, note in enumerate(notes_to_sample):
                    note_name = midi_to_note_name(note)
                    sample_name = f"gm_{i:03d}_{note_name}.wav"
                    sample_path = os.path.join(samples_dir, sample_name)
                    
                    # Render note
                    synth.clear_midi()
                    synth.add_midi_note(note, 100, 0.0, duration)
                    engine.render(total_duration)
                    audio = engine.get_audio()
                    
                    # Save WAV as 16-bit PCM
                    sf.write(sample_path, audio.T, sr, subtype='PCM_16')
                    
                    # Calculate key boundaries
                    if idx == 0:
                        lokey = 0
                    else:
                        lokey = (notes_to_sample[idx-1] + note) // 2 + 1
                        
                    if idx == len(notes_to_sample) - 1:
                        hikey = 127
                    else:
                        hikey = (note + notes_to_sample[idx+1]) // 2
                        
                    # Write region to individual SFZ
                    line = f"<region> sample={sample_name} pitch_keycenter={note} lokey={lokey} hikey={hikey}\n"
                    indiv_f.write(line)
                    
                    # Write region to master SFZ
                    master_f.write(line)
                    
                master_f.write("\n")
                
    print("\nGeneral MIDI 128 pack rendering complete!")
    print(f"Master file: {master_sfz_path}")
    print(f"Individual SFZ files: {instruments_dir}/")
    print(f"Sample WAV files: {samples_dir}/")

if __name__ == "__main__":
    main()
