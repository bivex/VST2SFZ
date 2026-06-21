#!/usr/bin/env python3
import os
import sys
import re
import glob
import math
import shutil
import numpy as np
import soundfile as sf
import mido
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
    # Walk factory directory to collect all available .fxp presets
    all_presets = {}
    for root, dirs, files in os.walk(factory_dir):
        for file in files:
            if file.endswith('.fxp'):
                fld = os.path.basename(root)
                all_presets[os.path.join(fld, file)] = os.path.join(root, file)

    mapping = {}
    used = set()

    def find_unique_preset(keywords, preferred_folders):
        # Try keywords in preferred folders
        for kw in keywords:
            for f, path in all_presets.items():
                if path in used:
                    continue
                fld = os.path.basename(os.path.dirname(path)).lower()
                if fld in [pf.lower() for pf in preferred_folders] and kw.lower() in f.lower():
                    used.add(path)
                    return path

        # Try keywords globally
        for kw in keywords:
            for f, path in all_presets.items():
                if path in used:
                    continue
                if kw.lower() in f.lower():
                    used.add(path)
                    return path

        # Fallback to preferred folders (first unused)
        for f, path in all_presets.items():
            if path in used:
                continue
            fld = os.path.basename(os.path.dirname(path)).lower()
            if fld in [pf.lower() for pf in preferred_folders]:
                used.add(path)
                return path

        # Global fallback (first unused anywhere)
        for f, path in all_presets.items():
            if path not in used:
                used.add(path)
                return path

        return None

    # Explicit hand-picked presets for critical instruments
    explicit_presets = {
        0: 'Plucks/Piano Remains 1.fxp', # Acoustic Grand Piano
        1: 'Plucks/Piano Remains 2.fxp', # Bright Acoustic Piano
        2: 'Keys/Artificial 1.fxp',      # Electric Grand Piano
        3: 'Keys/Experiment.fxp',        # Honky-Tonk Piano
        4: 'Keys/EP 1.fxp',              # Electric Piano 1
        5: 'Keys/DX EP.fxp',             # Electric Piano 2
        6: 'Keys/Digi Harpsi.fxp',       # Harpsichord
        7: 'Keys/Dirt.fxp',              # Clavinet
        10: 'Plucks/Magic Music Box.fxp',# Music Box
        16: 'Keys/Organ 1.fxp',          # Drawbar Organ
        17: 'Keys/Organ 2.fxp',          # Percussive Organ
        18: 'Keys/Organ 3.fxp',          # Rock Organ
        19: 'Keys/Church.fxp',           # Church Organ
        32: 'Basses/Wide Bassline.fxp',  # Acoustic Bass
        33: 'Basses/Fingered.fxp',       # Electric Bass (finger)
        34: 'Basses/Bass 1.fxp',         # Electric Bass (pick)
        35: 'Basses/Bass 2.fxp',         # Fretless Bass
        36: 'Basses/FM Slap.fxp',        # Slap Bass 1
        37: 'Basses/Bass 3.fxp',         # Slap Bass 2
        38: 'Basses/Lord Sawtooth.fxp',  # Synth Bass 1
        39: 'Basses/Saw Lo-Fi.fxp',      # Synth Bass 2
        40: 'Polysynths/Violini Poly.fxp', # Violin
        41: 'Pads/Subtle Comb Strings.fxp', # Viola
        48: 'Polysynths/Juno-60 Strings.fxp', # String Ensemble 1
        49: 'Pads/Choir Pad Thing.fxp',   # String Ensemble 2
        52: 'Pads/Retro Choir.fxp',       # Choir Aahs
        53: 'Pads/Robochoir 1.fxp',       # Voice Oohs
        54: 'Pads/Robochoir 2.fxp',       # Synth Voice
        56: 'Brass/Reso Brassy.fxp',
        57: 'Brass/Buggy Brass.fxp',
        58: 'Brass/Crisp Noise Brass.fxp',
        59: 'Brass/JX-10 Double Brass.fxp',
        60: 'Brass/Plastic Brass.fxp',
        61: 'Brass/Toto Brass.fxp',
        62: 'Brass/Synth Brass 1.fxp',
        63: 'Brass/Synth Brass 2.fxp',
        71: 'Winds/Clarinet.fxp',
        73: 'Winds/Flute 1.fxp',
        74: 'Winds/Flute 2.fxp',
        75: 'Winds/Dreamy Flute.fxp',
        80: 'Leads/Square.fxp',          # Lead 1 (square)
        81: 'Leads/Moogy Saw.fxp',       # Lead 2 (sawtooth)
    }

    # Resolve explicit ones first to reserve them
    for i, path_rel in explicit_presets.items():
        full_path = os.path.join(factory_dir, path_rel)
        if os.path.exists(full_path):
            mapping[i] = full_path
            used.add(full_path)

    # Map the rest dynamically
    for i in range(128):
        if i in mapping:
            continue
        
        grp = i // 8
        name = GM_NAMES[i]
        kws = [name.replace('_', ' ')] + name.split('_')
        
        # Target folders and backup keywords
        flds = []
        if grp == 0:
            flds, kws = ['keys', 'plucks', 'polysynths'], kws + ['keys', 'ep', 'piano', 'harpsi']
        elif grp == 1:
            flds, kws = ['plucks', 'percussion'], kws + ['bell', 'music', 'box', 'vibe', 'marimba', 'pluck']
        elif grp == 2:
            flds, kws = ['keys', 'leads'], kws + ['organ', 'accordion', 'circus']
        elif grp == 3:
            flds, kws = ['plucks', 'leads'], kws + ['guitar', 'pluck', 'clean', 'distortion']
        elif grp == 4:
            flds, kws = ['basses'], kws + ['bass', 'sub', 'fm']
        elif grp in [5, 6]:
            if i == 47: # Timpani
                flds, kws = ['percussion'], kws + ['tom', 'drum', 'perc']
            else:
                flds, kws = ['polysynths', 'pads'], kws + ['strings', 'violin', 'choir', 'voice', 'pad']
        elif grp == 7:
            flds, kws = ['brass', 'polysynths', 'leads'], kws + ['brass', 'trumpet', 'horn', 'section']
        elif grp in [8, 9]:
            flds, kws = ['winds', 'leads', 'polysynths'], kws + ['flute', 'wind', 'clarinet', 'sax', 'whistle']
        elif grp == 10:
            flds, kws = ['leads'], kws + ['lead', 'saw', 'square']
        elif grp == 11:
            flds, kws = ['pads'], kws + ['pad', 'warm', 'space']
        elif grp == 12:
            flds, kws = ['fx', 'leads'], kws + ['fx', 'space', 'soundtrack']
        elif grp == 13:
            flds, kws = ['plucks', 'winds', 'leads'], kws + ['sitar', 'banjo', 'pluck', 'fiddle']
        elif grp == 14:
            flds, kws = ['percussion', 'plucks'], kws + ['drum', 'perc', 'tom', 'cymbal']
        elif grp == 15:
            flds, kws = ['fx'], kws + ['noise', 'helicopter', 'phone', 'fx']

        res = find_unique_preset(kws, flds)
        mapping[i] = res

    return mapping

def midi_to_note_name(midi_num):
    notes = ['C', 'Cs', 'D', 'Ds', 'E', 'F', 'Fs', 'G', 'Gs', 'A', 'As', 'B']
    octave = (midi_num // 12) - 1
    note_index = midi_num % 12
    return f"{notes[note_index]}{octave}"

def main():
    # Detect if we are on macOS and can use the built-in General MIDI Apple DLS Music Device
    vst_path = "/System/Library/Components/CoreAudio.component"
    use_apple_dls = False
    
    if os.path.exists(vst_path):
        print(f"Found Apple DLSMusicDevice at {vst_path}. Using it for realistic General MIDI samples...")
        use_apple_dls = True
    else:
        vst_path = "/Library/Audio/Plug-Ins/VST3/Surge XT.vst3"
        print(f"Apple DLSMusicDevice not found. Falling back to Surge XT VST3 at {vst_path}...")
        if not os.path.exists(vst_path):
            print(f"Error: Surge XT VST3 not found at {vst_path}")
            sys.exit(1)

    # Directories
    samples_dir = "General_MIDI_samples"
    instruments_dir = "General_MIDI_instruments"
    os.makedirs(samples_dir, exist_ok=True)
    os.makedirs(instruments_dir, exist_ok=True)

    backup_files = {}
    midi_programs_dir = "/Users/password9090/Documents/Surge XT/Patches/MIDI Programs"
    
    if not use_apple_dls:
        print("Mapping 128 GM slots to Surge XT presets...")
        factory_dir = "/Library/Application Support/Surge XT/patches_factory"
        preset_mapping = build_preset_mapping(factory_dir)
        
        print("Backing up existing user MIDI Programs...")
        if os.path.exists(midi_programs_dir):
            for f in glob.glob(os.path.join(midi_programs_dir, "*")):
                if os.path.isfile(f):
                    with open(f, "rb") as src:
                        backup_files[os.path.basename(f)] = src.read()
                    os.remove(f)
        else:
            os.makedirs(midi_programs_dir, exist_ok=True)
            
        print("Copying mapped preset files to user MIDI Programs folder...")
        for i in range(128):
            inst_name = GM_NAMES[i]
            src_preset = preset_mapping[i]
            dest_preset = os.path.join(midi_programs_dir, f"{i:03d}_{inst_name}.fxp")
            shutil.copy2(src_preset, dest_preset)

    try:
        # Configure DawDreamer engine
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
            if use_apple_dls:
                master_f.write("// Generated from Apple DLSMusicDevice (Roland Sound Canvas samples)\n\n")
            else:
                master_f.write("// Generated from Surge XT factory presets\n\n")
            master_f.write("<control>\n")
            master_f.write(f"default_path={samples_dir}/\n\n")
            
            for i in range(128):
                inst_name = GM_NAMES[i]
                
                print(f"Sampling [{i:03d}/127] {inst_name}...")
                
                # Send MIDI Program Change to load the preset
                synth.clear_midi()
                mid = mido.MidiFile()
                track = mido.MidiTrack()
                mid.tracks.append(track)
                track.append(mido.Message('program_change', program=i, time=0))
                temp_mid_path = "temp_pc_run.mid"
                mid.save(temp_mid_path)
                
                synth.load_midi(temp_mid_path, all_events=True)
                # DLS Music Device loads instantly; 0.2s is plenty to process the event
                wait_time = 0.2 if use_apple_dls else 1.5
                engine.render(wait_time)
                synth.clear_midi()
                
                if os.path.exists(temp_mid_path):
                    os.remove(temp_mid_path)
                
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
                        # Slice to first 2 channels (stereo) to avoid empty channels from DLSMusicDevice
                        if audio.shape[0] > 2:
                            audio = audio[:2]
                        
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

    finally:
        if not use_apple_dls:
            print("Cleaning up copied MIDI Programs and restoring original files...")
            # Clear copied presets
            for f in glob.glob(os.path.join(midi_programs_dir, "*")):
                if os.path.isfile(f):
                    os.remove(f)
            # Restore backup
            for name, content in backup_files.items():
                with open(os.path.join(midi_programs_dir, name), "wb") as dest:
                    dest.write(content)
            print("Restored original user MIDI Programs.")

if __name__ == "__main__":
    main()
