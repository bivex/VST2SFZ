#!/usr/bin/env python3
import os
import sys
import glob
import shutil
import numpy as np
import soundfile as sf
import mido
import dawdreamer as daw


def detect_pitch_midi(audio, sr):
    """Detect the fundamental pitch of a rendered sample, return as MIDI note.

    Surge XT factory presets often bake in a key transpose (e.g. the "Piano
    Remains 1" patch plays a requested C4 as C5, +12 semitones). If we set
    pitch_keycenter to the *requested* note, sfizz assumes the sample is in
    that key and applies no correction — so the note comes out transposed.

    Detecting the actual pitch and writing THAT as pitch_keycenter makes
    sfizz transpose the sample to whatever key is played, canceling the
    preset's built-in offset. Uses the autocorrelation peak over the sustain
    portion of the note (more reliable than the raw FFT peak for harmonically
    rich timbres, where an overtone can dominate the spectrum).
    """
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    # Sustain window: skip attack (first 0.1s), take next 0.6s
    start = int(sr * 0.1)
    seg = mono[start:start + int(sr * 0.6)]
    if seg.size == 0 or float(np.max(np.abs(seg))) < 1e-5:
        return None
    seg = seg - float(np.mean(seg))  # remove DC
    seg = seg * np.hanning(len(seg))
    # Autocorrelation: lag in samples → period → frequency → MIDI
    corr = np.correlate(seg, seg, mode="full")
    corr = corr[len(seg):]  # keep right half (positive lags)
    # Ignore lags below ~MIDI 108 (4186 Hz) and above ~MIDI 0 (8 Hz)
    min_lag = max(2, int(sr / 4200))
    max_lag = min(len(corr) - 1, int(sr / 60))
    if max_lag <= min_lag:
        return None
    region = corr[min_lag:max_lag + 1]
    if region.size == 0:
        return None
    best_lag = int(np.argmax(region)) + min_lag
    freq = sr / best_lag
    if freq <= 0:
        return None
    midi = 69 + 12 * np.log2(freq / 440.0)
    return int(round(midi))


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
    """Map each of the 128 GM instruments to an explicit Surge XT factory preset."""
    # GM program index -> relative preset path under factory_dir.
    explicit = {
        # 0-7: Pianos
          0: 'Plucks/Piano Remains 1.fxp',      # Acoustic Grand Piano
          1: 'Keys/Artificial 2.fxp',           # Bright Acoustic Piano
          2: 'Keys/Artificial 1.fxp',           # Electric Grand Piano
          3: 'Keys/Experiment.fxp',             # Honky-Tonk Piano
          4: 'Keys/EP 1.fxp',                   # Electric Piano 1
          5: 'Keys/DX EP.fxp',                  # Electric Piano 2
          6: 'Keys/Digi Harpsi.fxp',            # Harpsichord
          7: 'Keys/Dirt.fxp',                   # Clavinet
        # 8-15: Chromatic Percussion
          8: 'Plucks/Bell 1.fxp',               # Celesta
          9: 'Plucks/Bell 2.fxp',               # Glockenspiel
         10: 'Plucks/Magic Music Box.fxp',      # Music Box
         11: 'Plucks/Fantasy Bell.fxp',         # Vibraphone
         12: 'Plucks/Woody.fxp',                # Marimba
         13: 'Plucks/Tinker.fxp',               # Xylophone
         14: 'Plucks/Belle.fxp',                # Tubular Bells
         15: 'Plucks/Metallic.fxp',             # Dulcimer
        # 16-23: Organs & Accordions
         16: 'Keys/Organ 1.fxp',                # Drawbar Organ
         17: 'Keys/Organ 2.fxp',                # Percussive Organ
         18: 'Keys/Organ 3.fxp',                # Rock Organ
         19: 'Keys/Church.fxp',                 # Church Organ
         20: 'Keys/House Organ.fxp',            # Reed Organ
         21: 'Keys/Circus 1.fxp',               # Accordion
         22: 'Keys/Circus 2.fxp',               # Harmonica
         23: 'Keys/Circus 1.fxp',               # Tango Accordion (Fixed: Rhodes EP -> Accordion)
        # 24-31: Guitars
         24: 'Plucks/Guitar.fxp',               # Acoustic Guitar Nylon
         25: 'Plucks/Magical Guitar.fxp',       # Acoustic Guitar Steel
         26: 'Plucks/Clean.fxp',                # Electric Guitar Jazz
         27: 'Plucks/E-Guitar.fxp',             # Electric Guitar Clean
         28: 'Plucks/Ambient E-Guitar.fxp',     # Electric Guitar Muted
         29: 'Leads/Synth Guitar 1.fxp',        # Overdriven Guitar
         30: 'Leads/Synth Guitar 2.fxp',        # Distorted Guitar
         31: 'Plucks/Harmonics 1.fxp',          # Guitar Harmonics
        # 32-39: Basses
         32: 'Basses/Wide Bassline.fxp',        # Acoustic Bass
         33: 'Basses/Fingered.fxp',             # Electric Bass (finger)
         34: 'Basses/Bass 1.fxp',               # Electric Bass (pick)
         35: 'Basses/Bass 2.fxp',               # Fretless Bass
         36: 'Basses/FM Slap.fxp',              # Slap Bass 1
         37: 'Basses/Bass 3.fxp',               # Slap Bass 2
         38: 'Basses/Lord Sawtooth.fxp',        # Synth Bass 1
         39: 'Basses/Sub 1.fxp',                # Synth Bass 2 (Fixed: Saw Lo-Fi -> Pure Sub Bass)
        # 40-47: Strings
         40: 'Polysynths/Violini Poly.fxp',     # Violin
         41: 'Pads/Subtle Comb Strings.fxp',    # Viola
         42: 'Polysynths/Anthemish 1.fxp',      # Cello
         43: 'Basses/Deep End.fxp',             # Contrabass
         44: 'Polysynths/Anthemish 2.fxp',      # Tremolo Strings
         45: 'Plucks/Comb Pluck.fxp',           # Pizzicato Strings
         46: 'Plucks/Simple Waveguide.fxp',     # Orchestral Harp
         47: 'Percussion/Synth Tom 1.fxp',      # Timpani
        # 48-55: Ensemble
         48: 'Polysynths/Juno-60 Strings.fxp',  # String Ensemble 1
         49: 'Pads/Sawteeth.fxp',               # String Ensemble 2
         50: 'Polysynths/Notched Saws.fxp',     # Synth Strings 1
         51: 'Pads/Harsh Saw.fxp',              # Synth Strings 2
         52: 'Pads/Retro Choir.fxp',            # Choir Aahs
         53: 'Pads/Ooh.fxp',                    # Voice Oohs
         54: 'Pads/Synth Choir MW O-Ah.fxp',    # Synth Voice
         55: 'Chords/Tek Stab.fxp',             # Orchestra Hit
        # 56-63: Brass
         56: 'Brass/Reso Brassy.fxp',           # Trumpet
         57: 'Brass/Buggy Brass.fxp',           # Trombone
         58: 'Brass/Crisp Noise Brass.fxp',     # Tuba
         59: 'Brass/JX-10 Double Brass.fxp',    # Muted Trumpet
         60: 'Brass/Plastic Brass.fxp',         # French Horn
         61: 'Brass/Toto Brass.fxp',            # Brass Section
         62: 'Brass/Synth Brass 1.fxp',         # Synth Brass 1
         63: 'Brass/Synth Brass 2.fxp',         # Synth Brass 2
        # 64-71: Reed
         64: 'Winds/Tragic Winds.fxp',          # Soprano Sax
         65: 'Winds/Fake Ethno.fxp',            # Alto Sax
         66: 'Leads/Shanai.fxp',                # Tenor Sax
         67: 'Winds/Low.fxp',                   # Baritone Sax
         68: 'Leads/Violini Solo.fxp',          # Oboe
         69: 'Winds/Flute 1.fxp',               # English Horn
         70: 'Winds/Flute 2.fxp',               # Bassoon
         71: 'Winds/Clarinet.fxp',              # Clarinet
        # 72-79: Pipe
         72: 'Winds/Dreamy Flute.fxp',          # Piccolo
         73: 'Winds/Cyber Flute.fxp',           # Flute
         74: 'Leads/Sine Lead.fxp',             # Recorder
         75: 'Leads/Talky 1 MW.fxp',            # Pan Flute
         76: 'Pads/Formants MW.fxp',            # Blown Bottle
         77: 'Leads/Talky 2 MW.fxp',            # Shakuhachi
         78: 'Leads/Vocal Lead.fxp',            # Whistle
         79: 'Leads/Formant Pulse.fxp',         # Ocarina
        # 80-87: Synth Lead
         80: 'Leads/Square.fxp',                # Lead 1 (square)
         81: 'Leads/Moogy Saw.fxp',             # Lead 2 (sawtooth)
         82: 'Leads/Sync Lead.fxp',             # Lead 3 (calliope)
         83: 'Leads/Crisp PWM.fxp',             # Lead 4 (chiff)
         84: 'Leads/Resofest 1.fxp',            # Lead 5 (charang)
         85: 'Leads/Classic Lead 1.fxp',        # Lead 6 (voice)
         86: 'Leads/Saw Octaves.fxp',           # Lead 7 (fifths)
         87: 'Leads/Tight Bassline.fxp',        # Lead 8 (bass + lead)
        # 88-95: Synth Pad
         88: 'Pads/FM Pad.fxp',                 # Pad 1 (new age)
         89: 'Pads/MKS-70 Warm Pad.fxp',        # Pad 2 (warm)
         90: 'Polysynths/Jupiter-8.fxp',        # Pad 3 (polysynth)
         91: 'Pads/Choir Pad Thing.fxp',        # Pad 4 (choir)
         92: 'Pads/Bell Pad.fxp',               # Pad 5 (bowed)
         93: 'Pads/Chowning.fxp',               # Pad 6 (metallic)
         94: 'Pads/Sparkly.fxp',                # Pad 7 (halo)
         95: 'Pads/Harmonic Sweep.fxp',         # Pad 8 (sweep)
        # 96-103: Synth Effects
         96: 'FX/Radio Noise.fxp',              # FX 1 (rain)
         97: 'FX/Space Adventure 1.fxp',        # FX 2 (soundtrack)
         98: 'FX/Space Cadet.fxp',              # FX 3 (crystal)
         99: 'FX/Space Adventure 2.fxp',        # FX 4 (atmosphere)
        100: 'FX/Fireworks.fxp',                # FX 5 (brightness)
        101: 'FX/Aliens.fxp',                   # FX 6 (goblins)
        102: 'FX/Vinyl.fxp',                    # FX 7 (echoes)
        103: 'FX/Geiger.fxp',                   # FX 8 (sci-fi)
        # 104-111: Ethnic
        104: 'Plucks/Mystic.fxp',               # Sitar
        105: 'Leads/Banjo Remains.fxp',         # Banjo
        106: 'Plucks/Saw Pluck.fxp',            # Shamisen
        107: 'Plucks/Wire.fxp',                 # Koto
        108: 'Plucks/Nice Pluck 1.fxp',         # Kalimba
        109: 'Leads/Rundfunk Funk.fxp',         # Bagpipe
        110: 'Leads/Classical.fxp',             # Fiddle
        111: 'Leads/Scream Lead.fxp',           # Shanai
        # 112-119: Percussive
        112: 'Plucks/Nice Pluck 2.fxp',         # Tinkle Bell
        113: 'Plucks/Nice Pluck 3.fxp',         # Agogo
        114: 'Plucks/Nice Pluck 4.fxp',         # Steel Drums
        115: 'Plucks/Square Pop.fxp',           # Woodblock
        116: 'Percussion/Synth Tom 2.fxp',      # Taiko Drum
        117: 'Percussion/Synth Tom 3.fxp',      # Melodic Tom
        118: 'Percussion/Verber.fxp',           # Synth Drum
        119: 'Percussion/Drum One.fxp',         # Reverse Cymbal
        # 120-127: Sound Effects
        120: 'FX/Crackling.fxp',                # Guitar Fret Noise
        121: 'FX/Harm.fxp',                     # Breath Noise
        122: 'FX/Rather Low.fxp',               # Seashore
        123: 'FX/Bork.fxp',                     # Bird Tweet
        124: 'FX/DTMF.fxp',                     # Telephone Ring
        125: 'FX/Alarm.fxp',                    # Helicopter
        126: 'FX/Busy.fxp',                     # Applause
        127: 'FX/Damage Dealer.fxp',            # Gunshot
    }

    mapping = {}
    for i, path_rel in explicit.items():
        full_path = os.path.join(factory_dir, path_rel)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f'GM preset not found for slot {i}: {full_path}')
        mapping[i] = full_path
    return mapping

def midi_to_note_name(midi_num):
    notes = ['C', 'Cs', 'D', 'Ds', 'E', 'F', 'Fs', 'G', 'Gs', 'A', 'As', 'B']
    octave = (midi_num // 12) - 1
    note_index = midi_num % 12
    return f"{notes[note_index]}{octave}"

def main():
    vst_path = "/Library/Audio/Plug-Ins/VST3/Surge XT.vst3"
    if not os.path.exists(vst_path):
        print(f"Error: Surge XT VST3 not found at {vst_path}")
        sys.exit(1)
    print(f"Using Surge XT at {vst_path}...")

    # Directories
    samples_dir = "General_MIDI_samples"
    instruments_dir = "General_MIDI_instruments"
    os.makedirs(samples_dir, exist_ok=True)
    os.makedirs(instruments_dir, exist_ok=True)

    print("Mapping 128 GM slots to Surge XT presets...")
    factory_dir = "/Library/Application Support/Surge XT/patches_factory"
    preset_mapping = build_preset_mapping(factory_dir)

    midi_programs_dir = os.path.expanduser("~/Documents/Surge XT/Patches/MIDI Programs")
    backup_files = {}
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
        # 8 key zones (every octave C1 to C8) and 2 velocity layers (64: Soft, 127: Hard)
        notes_to_sample = [24, 36, 48, 60, 72, 84, 96, 108]  # C1, C2, C3, C4, C5, C6, C7, C8
        velocities_to_sample = [64, 127]
        vel_ranges = [(0, 80), (81, 127)]
        
        duration = 1.0
        release = 0.5
        total_duration = duration + release
        sr = 96000

        # Master SFZ files paths
        master_sfz_path = "General_MIDI.sfz"
        sfizz_sfz_path = "General_MIDI_sfizz.sfz"
        sfizz_proc_sfz_path = "General_MIDI_sfizz_processed.sfz"

        print("Opening master SFZ files...")
        master_f = open(master_sfz_path, "w")
        sfizz_sfz_f = open(sfizz_sfz_path, "w")
        sfizz_proc_f = open(sfizz_proc_sfz_path, "w")

        # Write headers
        for f, is_sfizz, is_proc in [(master_f, False, False), (sfizz_sfz_f, True, False), (sfizz_proc_f, True, True)]:
            f.write(f"// General MIDI 128 Instrument Pack {'- sfizz variant' if is_sfizz else ''}\n")
            f.write("// Generated from Surge XT factory presets (2 Velocity Layers, 8 Key Zones)\n\n")
            f.write("<control>\n")
            if not is_sfizz:
                f.write(f"default_path={samples_dir}/\n")
            f.write("\n")

        for i in range(128):
            inst_name = GM_NAMES[i]
            preset_path = preset_mapping[i]

            print(f"Sampling [{i:03d}/127] {inst_name} (Preset: {os.path.basename(preset_path)})...")

            engine = daw.RenderEngine(sr, 512)
            synth = engine.make_plugin_processor("synth", vst_path)
            engine.load_graph([(synth, [])])

            # Switch preset
            synth.clear_midi()
            mid = mido.MidiFile()
            track = mido.MidiTrack()
            mid.tracks.append(track)
            track.append(mido.Message('program_change', program=i, time=0))
            temp_mid_path = "temp_pc_run.mid"
            mid.save(temp_mid_path)
            synth.load_midi(temp_mid_path, all_events=True)
            engine.render(1.5)
            synth.clear_midi()
            if os.path.exists(temp_mid_path):
                os.remove(temp_mid_path)
            
            # Individual instrument SFZ file
            indiv_sfz_path = os.path.join(instruments_dir, f"gm_{i:03d}_{inst_name}.sfz")
            indiv_f = open(indiv_sfz_path, "w")
            indiv_f.write(f"// GM Program {i}: {inst_name}\n")
            indiv_f.write("<control>\n")
            indiv_f.write(f"default_path=../{samples_dir}/\n\n")

            # Write groups to all file descriptors
            indiv_f.write(f"<group>\nprg_num={i}\n")
            master_f.write(f"<group>\nprg_num={i}\n")
            sfizz_sfz_f.write(f"<group>\nloprog={i} hiprog={i}\n")
            sfizz_proc_f.write(f"<group>\nloprog={i} hiprog={i}\n")

            rendered_audio = {}  # (idx, v_idx) -> audio

            for idx, note in enumerate(notes_to_sample):
                for v_idx, vel in enumerate(velocities_to_sample):
                    note_name = midi_to_note_name(note)
                    
                    # Render note
                    synth.clear_midi()
                    synth.add_midi_note(note, vel, 0.0, duration)
                    engine.render(total_duration)
                    audio = engine.get_audio()

                    # Silent check & Settle-Retry
                    if float(np.max(np.abs(audio))) < 0.001:
                        print(f"  ! silent {note_name} v{vel}, retrying with longer settle...")
                        retry_mid = "temp_pc_retry.mid"
                        synth.clear_midi()
                        mid2 = mido.MidiFile(); tr2 = mido.MidiTrack(); mid2.tracks.append(tr2)
                        tr2.append(mido.Message('program_change', program=i, time=0))
                        mid2.save(retry_mid)
                        synth.load_midi(retry_mid, all_events=True)
                        engine.render(3.0)
                        synth.clear_midi()
                        if os.path.exists(retry_mid):
                            os.remove(retry_mid)
                        synth.add_midi_note(note, vel, 0.0, duration)
                        engine.render(total_duration)
                        audio = engine.get_audio()

                    # Reshape to (samples, channels)
                    if audio.ndim == 1:
                        audio = np.column_stack((audio, audio))
                    elif audio.shape[0] == 2:
                        audio = audio.T

                    rendered_audio[(idx, v_idx)] = audio

            # Neighbor fallback per velocity layer
            for v_idx, vel in enumerate(velocities_to_sample):
                silent_indices = [idx for idx in range(len(notes_to_sample)) if float(np.max(np.abs(rendered_audio[(idx, v_idx)]))) < 0.001]
                audible = [idx for idx in range(len(notes_to_sample)) if idx not in silent_indices]
                if silent_indices:
                    if audible:
                        for sidx in silent_indices:
                            donor = min(audible, key=lambda j: abs(j - sidx))
                            rendered_audio[(sidx, v_idx)] = rendered_audio[(donor, v_idx)]
                            donor_note = midi_to_note_name(notes_to_sample[donor])
                            silent_note = midi_to_note_name(notes_to_sample[sidx])
                            print(f"  ~ borrowed {donor_note} v{vel} audio for silent {silent_note}")
                    else:
                        print(f"  !! all notes silent for velocity {vel} (instrument {inst_name} may be broken)")

            # Persist + map regions
            for idx, note in enumerate(notes_to_sample):
                # Calculate key boundaries
                if idx == 0:
                    lokey = 0
                else:
                    lokey = (notes_to_sample[idx-1] + note) // 2 + 1
                    
                if idx == len(notes_to_sample) - 1:
                    hikey = 127
                else:
                    hikey = (note + notes_to_sample[idx+1]) // 2

                for v_idx, vel in enumerate(velocities_to_sample):
                    lovel, hivel = vel_ranges[v_idx]
                    note_name = midi_to_note_name(note)
                    sample_name = f"gm_{i:03d}_{note_name}_v{vel}.wav"
                    sample_path = os.path.join(samples_dir, sample_name)
                    audio = rendered_audio[(idx, v_idx)]

                    # Save WAV as 24-bit PCM
                    sf.write(sample_path, audio, sr, subtype='PCM_24')

                    # Detect the sample's actual pitch and use it as
                    # pitch_keycenter. Surge XT presets often bake in a
                    # transposition; writing the real pitch here makes sfizz
                    # apply the inverse transpose when playing a given key.
                    actual_pitch = detect_pitch_midi(audio, sr)
                    if actual_pitch is None:
                        actual_pitch = note  # fallback to requested note

                    # Write regions
                    line_indiv = f"<region> sample={sample_name} pitch_keycenter={actual_pitch} lokey={lokey} hikey={hikey} lovel={lovel} hivel={hivel}\n"
                    line_master = f"<region> sample={sample_name} pitch_keycenter={actual_pitch} lokey={lokey} hikey={hikey} lovel={lovel} hivel={hivel}\n"
                    line_sfizz_raw = f"<region> sample=/Volumes/External/Code/VST2SFZ/General_MIDI_samples_raw/{sample_name} pitch_keycenter={actual_pitch} lokey={lokey} hikey={hikey} lovel={lovel} hivel={hivel}\n"
                    line_sfizz_proc = f"<region> sample=/Volumes/External/Code/VST2SFZ/General_MIDI_samples/{sample_name} pitch_keycenter={actual_pitch} lokey={lokey} hikey={hikey} lovel={lovel} hivel={hivel}\n"
                    
                    indiv_f.write(line_indiv)
                    master_f.write(line_master)
                    sfizz_sfz_f.write(line_sfizz_raw)
                    sfizz_proc_f.write(line_sfizz_proc)

            indiv_f.close()
            master_f.write("\n")
            sfizz_sfz_f.write("\n")
            sfizz_proc_f.write("\n")

        master_f.close()
        sfizz_sfz_f.close()
        sfizz_proc_f.close()

        print("\nGeneral MIDI 128 pack rendering complete!")
        print(f"Master file: {master_sfz_path}")
        print(f"Sfizz file: {sfizz_sfz_path}")
        print(f"Sfizz processed file: {sfizz_proc_sfz_path}")

    finally:
        print("Cleaning up copied MIDI Programs and restoring original files...")
        for f in glob.glob(os.path.join(midi_programs_dir, "*")):
            if os.path.isfile(f):
                os.remove(f)
        for name, content in backup_files.items():
            with open(os.path.join(midi_programs_dir, name), "wb") as dest:
                dest.write(content)
        print("Restored original user MIDI Programs.")

if __name__ == "__main__":
    main()
