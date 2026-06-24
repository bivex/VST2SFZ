#!/usr/bin/env python3
import os
import sys
import glob
import shutil
import numpy as np
import soundfile as sf
import mido
import dawdreamer as daw
from pitch_utils import detect_pitch_midi, detect_pitch_midi_loudest


# detect_pitch_midi is imported from pitch_utils (validated lowest-peak algorithm)


# ─── GM Drum Kit ─────────────────────────────────────────────────────────────
# KSHMR Vol.5 samples shared between General MIDI and Dexed packs.
# NOT rendered by Surge XT; we reference existing WAV files from
# General_MIDI_samples_drums/ (produced by kshmr_drum_mapping.py).
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
    """Append a GM Drum Kit section (ch10, N35-N81) to an open SFZ file.

    Uses absolute paths to KSHMR Vol.5 samples from drum_samples_dir.
    Only writes notes for which both velocity-layer WAV files exist.
    """
    f.write("\n")
    f.write("// ─── GM Drum Kit (channel 10 / MIDI ch 9) ──────────────────────────────────\n")
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
          0: 'Keys/EP 1.fxp',                   # Acoustic Grand Piano (EP-style: strong fundamental + soft harmonics, closest to real piano in Surge factory)
          1: 'Keys/Soft Suitcase.fxp',          # Bright Acoustic Piano (suitcase EP, brighter than EP 1)
          2: 'Polysynths/Oldie.fxp',            # Electric Grand Piano (vintage poly-synth with piano-like attack)
          3: 'Plucks/Convex.fxp',               # Honky-Tonk Piano (plucked with detuned harmonics, honky character)
          4: 'Keys/EP 2.fxp',                   # Electric Piano 1
          5: 'Plucks/Sinus Verby Pops.fxp',     # Electric Piano 2 (pure sine EP, bright)
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
         23: 'Leads/Butter.fxp',               # Tango Accordion (Fixed: Circus 1 dup with prog 21 -> Butter sustained lead)
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
         33: 'Basses/Sub 2.fxp',              # Electric Bass (finger) (strong fundamental)
         34: 'Basses/Bass 1.fxp',               # Electric Bass (pick)
         35: 'Basses/Bass 2.fxp',               # Fretless Bass
         36: 'Basses/FM Slap.fxp',              # Slap Bass 1
         37: 'Basses/Bass 3.fxp',               # Slap Bass 2
         38: 'Basses/Square Bass.fxp',          # Synth Bass 1 (Fixed: Lord Sawtooth clamped -> Square Bass, full range)
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
         66: 'MPE/Baritonosaurus Saxus.fxp',     # Tenor Sax (Fixed: Shanai FM -> Baritonosaurus, real sax-like)
         67: 'Winds/Low.fxp',                   # Baritone Sax
         68: 'Leads/Violini Solo.fxp',          # Oboe
         69: 'Winds/Flute 1.fxp',               # English Horn
         70: 'Winds/Flute 2.fxp',               # Bassoon
         71: 'Winds/Clarinet.fxp',              # Clarinet
        # 72-79: Pipe
         72: 'Winds/Dreamy Flute.fxp',          # Piccolo
         73: 'Winds/Cyber Flute.fxp',          # Flute (was Tragic Winds dup with prog 64)
         74: 'Plucks/Soft Space Oboe Pops.fxp', # Recorder (Fixed: Flute 2 dup -> Soft Space Oboe, breathy sustained)
         75: 'Leads/Talky 1 MW.fxp',            # Pan Flute
         76: 'Pads/Formants MW.fxp',            # Blown Bottle
         77: 'Leads/Smoothness World Cup.fxp',  # Shakuhachi (Fixed: Talky 2 -> Smoothness, pure sustained flute tone)
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
    # Raw Surge XT output goes into General_MIDI_samples_raw. The VST mastering
    # chain (process_samples_vst.py) then reads from here and writes the
    # processed samples into General_MIDI_samples. This keeps raw and processed
    # in sync: General_MIDI_sfizz.sfz points at _raw, General_MIDI_sfizz_processed.sfz
    # points at the processed dir.
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    samples_dir = os.path.join(_root, "General_MIDI_samples_raw")
    processed_dir = os.path.join(_root, "General_MIDI_samples")
    instruments_dir = os.path.join(_root, "General_MIDI_instruments")
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
        # Velocity ranges with 20-unit crossfade zone centred on the midpoint
        # between the two sample velocities: (64+127)//2 = 95.
        # lovel/hivel define the region that plays; xfin/xfout define the
        # fade edges so sfizz blends smoothly instead of hard-switching at 80.
        vel_ranges = [(0, 95), (96, 127)]          # hard trigger boundaries
        vel_xfade  = [(0, 0, 85, 95),              # (xfin_lo, xfin_hi, xfout_lo, xfout_hi)
                      (85, 95, 127, 127)]           # v127 fades in where v64 fades out
        
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

            # Silencing low-level stderr during VST initialization to hide URI mapping warnings
            devnull = open(os.devnull, 'w')
            old_stderr = os.dup(2)
            os.dup2(devnull.fileno(), 2)
            try:
                engine = daw.RenderEngine(sr, 512)
                synth = engine.make_plugin_processor("synth", vst_path)
                engine.load_graph([(synth, [])])
            finally:
                os.dup2(old_stderr, 2)
                os.close(old_stderr)
                devnull.close()

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

            # Detect Preset Transposition
            # Play a reference note (MIDI 60 = C4) WITHOUT compensation and
            # detect what pitch comes out.  This is a raw, uncompensated render
            # so we use detect_pitch_midi_loudest (dominant spectral peak),
            # which agrees with sample_gm_pack's own keycenter computation
            # 88.7 % of the time on raw samples vs 56 % for lowest-peak.
            preset_transpose = 0
            ref_note = 60
            synth.add_midi_note(ref_note, 127, 0.0, 0.6)
            engine.render(1.0)
            ref_audio = engine.get_audio()
            synth.clear_midi()

            if ref_audio.ndim == 1:
                ref_audio = np.column_stack((ref_audio, ref_audio))
            elif ref_audio.shape[0] == 2:
                ref_audio = ref_audio.T

            detected_ref_pitch = detect_pitch_midi_loudest(ref_audio, sr)
            if detected_ref_pitch is not None:
                diff = detected_ref_pitch - ref_note
                # Synthesizer presets are almost always transposed in octaves
                # (multiples of 12).  We snap to the nearest octave multiple
                # and only apply if the raw diff is within 1 semitone of it.
                # Max ±48 st (±4 octaves) covers all Surge XT factory presets
                # including extreme cases like prog 120/121 (+39 st).
                nearest_octave = int(round(diff / 12.0)) * 12
                if abs(diff - nearest_octave) <= 1 and abs(nearest_octave) <= 48:
                    preset_transpose = nearest_octave
                    if preset_transpose != 0:
                        print(f"  Detected preset transposition: {preset_transpose:+} semitones")
                else:
                    preset_transpose = 0
            else:
                print("  Could not detect preset pitch, using 0 transpose offset")
            
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
                    
                    # Render note with inverse transposition applied
                    synth.clear_midi()
                    play_note = max(0, min(127, note - preset_transpose))
                    synth.add_midi_note(play_note, vel, 0.0, duration)
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
                        synth.add_midi_note(play_note, vel, 0.0, duration)
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

            # Detect pitch for each note based on the loudest velocity (v127) layer
            note_pitches = {}
            for idx, note in enumerate(notes_to_sample):
                audio_v127 = rendered_audio[(idx, 1)]  # v127 corresponds to velocities_to_sample[1]
                detected_pitch = detect_pitch_midi(audio_v127, sr)
                if detected_pitch is None:
                    detected_pitch = note
                note_pitches[idx] = detected_pitch

            # Clamp detection: when a preset physically can't produce the requested
            # pitch, consecutive requested notes collapse onto the same detected pitch
            # (e.g. C5/C6/C7/C8 all come out as MIDI 60 on a bass preset). Writing a
            # fake pitch_keycenter for those would make sfizz transpose them wildly
            # (the "munchkin" effect). Instead we collapse each run of identical
            # detected pitches into one representative sample and let its key zone
            # stretch across the whole clamped range, so every key still sounds in
            # tune using a real, in-range sample.
            kept_indices = []
            idx = 0
            while idx < len(notes_to_sample):
                run_end = idx
                while (run_end + 1 < len(notes_to_sample)
                       and note_pitches[run_end + 1] == note_pitches[idx]):
                    run_end += 1
                if run_end > idx:
                    rep = (idx + run_end) // 2
                    kept_indices.append(rep)
                    start_name = midi_to_note_name(notes_to_sample[idx])
                    end_name = midi_to_note_name(notes_to_sample[run_end])
                    rep_name = midi_to_note_name(notes_to_sample[rep])
                    print(f"  ~ clamp: {start_name}..{end_name} all play MIDI {note_pitches[idx]} -> kept {rep_name}")
                else:
                    kept_indices.append(idx)
                idx = run_end + 1

            # Persist + map regions, recomputing key boundaries so the kept samples
            # tile the full 0..127 range without gaps left by the collapsed notes.
            for k, idx in enumerate(kept_indices):
                note = notes_to_sample[idx]
                if k == 0:
                    lokey = 0
                else:
                    prev_note = notes_to_sample[kept_indices[k - 1]]
                    lokey = (prev_note + note) // 2 + 1

                if k == len(kept_indices) - 1:
                    hikey = 127
                else:
                    next_note = notes_to_sample[kept_indices[k + 1]]
                    hikey = (note + next_note) // 2

                actual_pitch = note_pitches[idx]

                for v_idx, vel in enumerate(velocities_to_sample):
                    lovel, hivel = vel_ranges[v_idx]
                    xfin_lo, xfin_hi, xfout_lo, xfout_hi = vel_xfade[v_idx]
                    note_name = midi_to_note_name(note)
                    sample_name = f"gm_{i:03d}_{note_name}_v{vel}.wav"
                    sample_path = os.path.join(samples_dir, sample_name)
                    audio = rendered_audio[(idx, v_idx)]

                    # Save WAV as 24-bit PCM
                    sf.write(sample_path, audio, sr, subtype='PCM_24')

                    # xfin/xfout give sfizz a smooth 10-unit crossfade zone
                    # centred on velocity 90 so the v64→v127 transition is
                    # inaudible instead of a hard cut.
                    xf = (f" xfin_lovel={xfin_lo} xfin_hivel={xfin_hi}"
                          f" xfout_lovel={xfout_lo} xfout_hivel={xfout_hi}")
                    base = (f"pitch_keycenter={actual_pitch}"
                            f" lokey={lokey} hikey={hikey}"
                            f" lovel={lovel} hivel={hivel}{xf}")

                    # Write regions
                    line_indiv     = f"<region> sample={sample_name} {base}\n"
                    line_master    = f"<region> sample={sample_name} {base}\n"
                    line_sfizz_raw = f"<region> sample={samples_dir}/{sample_name} {base}\n"
                    line_sfizz_proc = f"<region> sample={processed_dir}/{sample_name} {base}\n"

                    indiv_f.write(line_indiv)
                    master_f.write(line_master)
                    sfizz_sfz_f.write(line_sfizz_raw)
                    sfizz_proc_f.write(line_sfizz_proc)

            indiv_f.close()
            master_f.write("\n")
            sfizz_sfz_f.write("\n")
            sfizz_proc_f.write("\n")

        # ── Append GM Drum Kit ─────────────────────────────────────────────────
        # IMPORTANT: the drum section is embedded ONLY in the master bank, whose
        # consumer (render_sfz_midi_gm.py) routes channel 10 itself. It is NOT
        # embedded into the sfizz banks: the drum regions are gated by
        # lochan=10, but the sfizz consumer (pysfizz) plays every note on
        # channel 1 and IGNORES lochan, so an embedded section leaks a
        # percussion hit onto every melodic note in the N35-N81 key range
        # (verified: melodic note 60 correlated 0.80 with the bongo sample).
        # sfizz consumers get drums from the standalone General_MIDI_sfizz_drums.sfz
        # loaded into a separate drum synth (see kshmr_drum_mapping.py / Birka).
        drum_samples_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "General_MIDI_samples_drums")
        if os.path.isdir(drum_samples_dir):
            print("\nAppending GM drum kit section (master bank only)...")
            write_drum_section(master_f, drum_samples_dir)
        else:
            print(f"Warning: drum samples dir not found: {drum_samples_dir}")
            print("  Run kshmr_drum_mapping.py first to generate drum samples.")

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
