#!/usr/bin/env python3
import os
import sys
import re
import math
import argparse
import numpy as np
import soundfile as sf
import dawdreamer as daw

def note_to_midi(note_str):
    """
    Converts note name (e.g. C4, D#3, Bb5) or MIDI number string to MIDI note integer.
    """
    if note_str is None:
        raise TypeError("MIDI note cannot be None")
    if not isinstance(note_str, (int, str)):
        raise TypeError(f"MIDI note must be a string or integer, got: {type(note_str).__name__}")
        
    if isinstance(note_str, int):
        if note_str < 0 or note_str > 127:
            raise ValueError(f"MIDI note out of bounds (0-127): {note_str}")
        return note_str
    if isinstance(note_str, str) and note_str.isdigit():
        midi_num = int(note_str)
        if midi_num < 0 or midi_num > 127:
            raise ValueError(f"MIDI note out of bounds (0-127): {midi_num}")
        return midi_num
        
    note_str = note_str.strip()
    # Match: letter (A-G), optional accidental (#, b, sharp, flat), octave (integer)
    match = re.match(r"^([A-G]|[a-g])(#|b|sharp|flat)?(-?\d+)$", note_str)
    if not match:
        raise ValueError(f"Invalid note format: '{note_str}'. Must be like 'C4', 'D#3', 'Bb5', or a MIDI number.")
        
    letter = match.group(1).upper()
    accidental = match.group(2)
    octave = int(match.group(3))
    
    note_map = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
    val = note_map[letter]
    
    if accidental:
        acc_lower = accidental.lower()
        if acc_lower in ('#', 'sharp'):
            val += 1
        elif acc_lower in ('b', 'flat'):
            val -= 1
            
    midi = val + (octave + 1) * 12
    if midi < 0 or midi > 127:
        raise ValueError(f"MIDI note out of bounds (0-127): {midi} (from {note_str})")
    return midi

def midi_to_note_name(midi_num):
    """
    Converts a MIDI note number to its standard name (e.g., 60 -> C4).
    """
    if not isinstance(midi_num, int):
        # Allow integer-like strings or float integers
        if isinstance(midi_num, float) and not midi_num.is_integer():
            raise TypeError(f"MIDI note number must be an integer, got: {midi_num}")
        try:
            midi_num = int(midi_num)
        except (ValueError, TypeError):
            raise TypeError(f"MIDI note number must be an integer, got: {midi_num}")
            
    if midi_num < 0 or midi_num > 127:
        raise ValueError(f"MIDI note out of bounds (0-127): {midi_num}")
        
    notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    octave = (midi_num // 12) - 1
    note_index = midi_num % 12
    return f"{notes[note_index]}{octave}"

def parse_note_range(notes_arg, step=1):
    """
    Parses notes argument which can be a single note, list of notes, or range (e.g. C3-C5).
    """
    if not isinstance(step, int) or step <= 0:
        raise ValueError(f"Step size must be a positive integer, got: {step}")
        
    parts = notes_arg.split(',')
    midi_notes = set()
    
    NOTE_PATTERN = r"[A-Ga-g](?:#|b|sharp|flat)?-?\d+|\d+"
    range_regex = rf"^\s*({NOTE_PATTERN})\s*-\s*({NOTE_PATTERN})\s*$"
    
    for part in parts:
        part = part.strip()
        match = re.match(range_regex, part)
        if match:
            start_note = note_to_midi(match.group(1))
            end_note = note_to_midi(match.group(2))
            for n in range(start_note, end_note + 1, step):
                midi_notes.add(n)
        else:
            midi_notes.add(note_to_midi(part))
            
    return sorted(list(midi_notes))

def generate_key_zones(midi_notes):
    """
    Computes lokey and hikey for each sampled MIDI note to stretch them across the keyboard.
    """
    zones = []
    n = len(midi_notes)
    if n == 0:
        return zones
        
    for i in range(n):
        midi = midi_notes[i]
        # lokey splits difference with previous note
        if i == 0:
            lokey = 0
        else:
            prev_midi = midi_notes[i-1]
            lokey = (prev_midi + midi) // 2 + 1
            
        # hikey splits difference with next note
        if i == n - 1:
            hikey = 127
        else:
            next_midi = midi_notes[i+1]
            hikey = (midi + next_midi) // 2
            
        zones.append({
            "midi": midi,
            "lokey": lokey,
            "hikey": hikey
        })
    return zones

def generate_velocity_layers(velocities):
    """
    Computes lovel and hivel for each velocity level.
    """
    layers = []
    v = sorted(velocities)
    n = len(v)
    if n == 0:
        return layers
        
    for j in range(n):
        vel = v[j]
        if j == 0:
            lovel = 1
        else:
            lovel = (v[j-1] + vel) // 2 + 1
            
        if j == n - 1:
            hivel = 127
        else:
            hivel = (vel + v[j+1]) // 2
            
        layers.append({
            "velocity": vel,
            "lovel": lovel,
            "hivel": hivel
        })
    return layers

def find_loop_points(midi_note, sr, note_on_duration, audio_length):
    """
    Calculates phase-aligned loop points based on the fundamental frequency of the MIDI note.
    """
    freq = 440.0 * (2.0 ** ((midi_note - 69) / 12.0))
    wavelength = sr / freq
    
    # We loop in the sustain portion of the note-on phase
    # (after attack, before note-off release)
    target_start_sec = max(0.5, note_on_duration * 0.4)
    target_end_sec = note_on_duration * 0.95
    
    loop_start = int(target_start_sec * sr)
    approx_end = int(target_end_sec * sr)
    
    approx_length = approx_end - loop_start
    if approx_length <= 0:
        return None, None
        
    num_cycles = round(approx_length / wavelength)
    if num_cycles < 1:
        num_cycles = 1
        
    exact_length = int(round(num_cycles * wavelength))
    loop_end = loop_start + exact_length
    
    # Safety checks
    note_off_sample = int(note_on_duration * sr)
    if loop_end >= note_off_sample:
        max_length = note_off_sample - loop_start - 200
        num_cycles = max_length // wavelength
        if num_cycles >= 1:
            exact_length = int(round(num_cycles * wavelength))
            loop_end = loop_start + exact_length
        else:
            return None, None
            
    if loop_end >= audio_length:
        loop_end = audio_length - 1
        
    return loop_start, loop_end

def print_progress(current, total, bar_length=45):
    percent = float(current) / total
    arrow = '=' * int(round(percent * bar_length) - 1) + '>'
    spaces = ' ' * (bar_length - len(arrow))
    sys.stdout.write(f"\rProgress: [{arrow}{spaces}] {int(round(percent * 100))}% ({current}/{total})")
    sys.stdout.flush()

def main():
    parser = argparse.ArgumentParser(
        description="Sample VST plugins and generate SFZ instruments with Velocity Layers, Round Robin, and FX.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Core settings
    parser.add_argument("--vst", type=str, required=True, help="Path to VST3/VST2/AU plugin (e.g. /path/to/plugin.vst3)")
    parser.add_argument("--preset", type=str, default=None, help="Path to preset/state file to load (.vstpreset, .fxp, .bin, .state)")
    parser.add_argument("--midi-program", type=int, default=None, help="MIDI program change number to send before note-on")
    parser.add_argument("--output-name", type=str, default=None, help="Name of output instrument. Defaults to VST name.")
    
    # Sampling range
    parser.add_argument("--notes", type=str, default="C3-C5", help="Notes to sample (e.g., C3-C5, or list 60,64,67, or range 48-72)")
    parser.add_argument("--step", type=int, default=3, help="Step size in semitones when sampling note ranges (e.g. 3 for minor thirds)")
    parser.add_argument("--velocities", type=str, default="100", help="Comma-separated list of velocities to sample (e.g. 100 or 40,80,127)")
    parser.add_argument("--round-robin", type=int, default=1, help="Number of round robin samples per note/velocity")
    
    # Timing
    parser.add_argument("--duration", type=float, default=2.0, help="Hold duration of the MIDI note-on in seconds")
    parser.add_argument("--release", type=float, default=1.0, help="Release duration in seconds recorded after note-off")
    parser.add_argument("--sr", type=int, default=44100, help="Sample rate for rendering")
    parser.add_argument("--bit-depth", type=int, choices=[16, 24, 32], default=16, help="Bit depth of the rendered WAV files (16, 24, 32)")
    parser.add_argument("--block-size", type=int, default=512, help="Block size for rendering engine")
    
    # Looping
    parser.add_argument("--auto-loop", action="store_true", help="Calculate phase-aligned loop points and write them to SFZ")
    
    # Effects (via pedalboard)
    parser.add_argument("--fx", type=str, default=None, help="Comma-separated list of effects: reverb,delay,chorus,phaser,distortion")
    parser.add_argument("--fx-reverb-mix", type=float, default=0.33, help="Reverb wet level (0.0 to 1.0)")
    parser.add_argument("--fx-reverb-room", type=float, default=0.5, help="Reverb room size (0.0 to 1.0)")
    parser.add_argument("--fx-delay-time", type=float, default=0.3, help="Delay time in seconds")
    parser.add_argument("--fx-delay-feedback", type=float, default=0.3, help="Delay feedback (0.0 to 1.0)")
    parser.add_argument("--fx-delay-mix", type=float, default=0.2, help="Delay mix (0.0 to 1.0)")
    parser.add_argument("--fx-chorus-rate", type=float, default=1.0, help="Chorus rate in Hz")
    parser.add_argument("--fx-chorus-depth", type=float, default=0.25, help="Chorus depth (0.0 to 1.0)")
    parser.add_argument("--fx-chorus-mix", type=float, default=0.5, help="Chorus mix (0.0 to 1.0)")
    parser.add_argument("--fx-phaser-rate", type=float, default=1.0, help="Phaser rate in Hz")
    parser.add_argument("--fx-phaser-depth", type=float, default=0.5, help="Phaser depth (0.0 to 1.0)")
    parser.add_argument("--fx-phaser-mix", type=float, default=0.5, help="Phaser mix (0.0 to 1.0)")
    parser.add_argument("--fx-distortion-drive", type=float, default=15.0, help="Distortion drive in dB")
    
    args = parser.parse_args()
    
    # Initialize VST paths and names
    if not os.path.exists(args.vst):
        print(f"Error: VST plugin path not found: {args.vst}")
        sys.exit(1)
        
    vst_basename = os.path.splitext(os.path.basename(args.vst))[0]
    instrument_name = args.output_name if args.output_name else vst_basename
    instrument_name = re.sub(r'[^a-zA-Z0-9_]', '_', instrument_name)
    
    # Parse notes & velocities
    try:
        midi_notes = parse_note_range(args.notes, args.step)
    except Exception as e:
        print(f"Error parsing notes: {e}")
        sys.exit(1)
        
    try:
        velocities = [int(v.strip()) for v in args.velocities.split(',')]
    except Exception as e:
        print(f"Error parsing velocities: {e}")
        sys.exit(1)
        
    if not midi_notes:
        print("Error: No midi notes selected to sample.")
        sys.exit(1)
        
    # Validate velocities are within valid MIDI range
    for v in velocities:
        if v < 1 or v > 127:
            print(f"Error: Velocity must be between 1 and 127, got: {v}")
            sys.exit(1)
            
    # Validate durations and counts
    if args.round_robin < 1:
        print(f"Error: round-robin count must be at least 1, got: {args.round_robin}")
        sys.exit(1)
        
    if args.duration <= 0:
        print(f"Error: note duration must be positive, got: {args.duration}")
        sys.exit(1)
        
    if args.release < 0:
        print(f"Error: release duration must be non-negative, got: {args.release}")
        sys.exit(1)
        
    if args.sr <= 0:
        print(f"Error: sample rate must be positive, got: {args.sr}")
        sys.exit(1)
        
    if args.block_size <= 0:
        print(f"Error: block size must be positive, got: {args.block_size}")
        sys.exit(1)
        
    # Setup directories
    samples_dir_name = f"{instrument_name}_samples"
    os.makedirs(samples_dir_name, exist_ok=True)
    
    print(f"Sampling VST: {args.vst}")
    print(f"Instrument Name: {instrument_name}")
    print(f"Output SFZ: {instrument_name}.sfz")
    print(f"Output Samples Directory: {samples_dir_name}/")
    print(f"Notes ({len(midi_notes)}): {midi_notes} (Names: {[midi_to_note_name(n) for n in midi_notes]})")
    print(f"Velocity Layers ({len(velocities)}): {velocities}")
    print(f"Round Robins: {args.round_robin}")
    print(f"Hold time: {args.duration}s, Release time: {args.release}s")
    
    # Configure RenderEngine
    engine = daw.RenderEngine(args.sr, args.block_size)
    try:
        synth = engine.make_plugin_processor("synth", args.vst)
    except Exception as e:
        print(f"Error: Failed to load VST via DawDreamer: {e}")
        sys.exit(1)
        
    # Load preset if specified
    if args.preset:
        if not os.path.exists(args.preset):
            print(f"Error: Preset file not found: {args.preset}")
            sys.exit(1)
            
        ext = os.path.splitext(args.preset)[1].lower()
        success = False
        try:
            if ext == '.vstpreset':
                print(f"Loading VST3 Preset: {args.preset}")
                success = synth.load_vst3_preset(args.preset)
            elif ext == '.fxp':
                print(f"Loading FXP Preset: {args.preset}")
                success = synth.load_preset(args.preset)
            else:
                print(f"Loading Generic State/Bin file: {args.preset}")
                synth.load_state(args.preset)
                success = True
        except Exception as e:
            print(f"Error loading preset: {e}")
            sys.exit(1)
            
        if not success:
            print(f"Warning: Preset loading returned False. Attempting to continue anyway...")
            
    engine.load_graph([(synth, [])])
    
    # Send MIDI Program Change once at startup to select correct preset
    if args.midi_program is not None:
        print(f"Sending MIDI Program Change {args.midi_program} to switch VST preset...")
        try:
            import mido
            mid = mido.MidiFile()
            track = mido.MidiTrack()
            mid.tracks.append(track)
            track.append(mido.Message('program_change', program=args.midi_program, time=0))
            temp_init_pc = "temp_init_pc.mid"
            mid.save(temp_init_pc)
            synth.load_midi(temp_init_pc)
            engine.render(0.2) # Render a fraction of a second to apply the program change
            synth.clear_midi()
            if os.path.exists(temp_init_pc):
                os.remove(temp_init_pc)
            print("VST preset switched successfully.")
        except Exception as e:
            print(f"Warning: Failed to send Program Change initialization: {e}")
    
    # Pedalboard configuration
    fx_names = []
    if args.fx:
        fx_names = [f.strip() for f in args.fx.split(',')]
        
    # Generate mapping lists
    zones = generate_key_zones(midi_notes)
    v_layers = generate_velocity_layers(velocities)
    
    # Sampling loops
    total_renders = len(midi_notes) * len(velocities) * args.round_robin
    render_count = 0
    
    # Store list of mappings for SFZ output
    sfz_regions = []
    
    print("\nStarting render process...")
    print_progress(0, total_renders)
    
    for zone in zones:
        note = zone["midi"]
        note_name = midi_to_note_name(note)
        
        for layer in v_layers:
            vel = layer["velocity"]
            
            for rr in range(1, args.round_robin + 1):
                # Unique filename
                file_basename = f"{instrument_name}_{note_name}_v{vel}_rr{rr}.wav"
                # Use clean filenames (replace # with s for web/OS compatibility if needed, but # is fine for local files)
                # Let's clean up any # signs in filename to 's' just in case, but SFZ references should match.
                safe_file_basename = file_basename.replace("#", "s")
                wav_path = os.path.join(samples_dir_name, safe_file_basename)
                
                # Render MIDI Note
                synth.clear_midi()
                synth.add_midi_note(note, vel, 0.0, args.duration)
                
                total_duration = args.duration + args.release
                engine.render(total_duration)
                
                audio = engine.get_audio() # Shape is (channels, samples)
                
                # Apply effects via Pedalboard if specified
                if fx_names:
                    try:
                        import pedalboard
                        from pedalboard import Pedalboard, Reverb, Delay, Chorus, Phaser, Distortion
                        
                        fx_list = []
                        for fx_name in fx_names:
                            fx_name = fx_name.lower()
                            if fx_name == "reverb":
                                fx_list.append(Reverb(room_size=args.fx_reverb_room, wet_level=args.fx_reverb_mix))
                            elif fx_name == "delay":
                                fx_list.append(Delay(delay_seconds=args.fx_delay_time, feedback=args.fx_delay_feedback, mix=args.fx_delay_mix))
                            elif fx_name == "chorus":
                                fx_list.append(Chorus(rate_hz=args.fx_chorus_rate, depth=args.fx_chorus_depth, mix=args.fx_chorus_mix))
                            elif fx_name == "phaser":
                                fx_list.append(Phaser(rate_hz=args.fx_phaser_rate, depth=args.fx_phaser_depth, mix=args.fx_phaser_mix))
                            elif fx_name == "distortion":
                                fx_list.append(Distortion(drive_db=args.fx_distortion_drive))
                                
                        if fx_list:
                            board = Pedalboard(fx_list)
                            audio = board(audio, args.sr)
                    except ImportError:
                        print("\nWarning: 'pedalboard' module not available. Skipping effects.")
                    except Exception as e:
                        print(f"\nWarning: Failed to apply effects: {e}")
                
                # Save WAV file
                # soundfile expects (samples, channels)
                subtype = f"PCM_{args.bit_depth}"
                sf.write(wav_path, audio.T, args.sr, subtype=subtype)
                
                # Auto-loop calculations
                loop_opcodes = ""
                if args.auto_loop:
                    l_start, l_end = find_loop_points(note, args.sr, args.duration, audio.shape[1])
                    if l_start is not None and l_end is not None:
                        loop_opcodes = f"loop_mode=loop_continuous loop_start={l_start} loop_end={l_end} "
                
                # Add mapping record
                sfz_regions.append({
                    "sample": safe_file_basename,
                    "pitch_keycenter": note,
                    "lokey": zone["lokey"],
                    "hikey": zone["hikey"],
                    "lovel": layer["lovel"],
                    "hivel": layer["hivel"],
                    "seq_position": rr,
                    "seq_length": args.round_robin,
                    "loop_opcodes": loop_opcodes
                })
                
                render_count += 1
                print_progress(render_count, total_renders)
                
    print("\nRender complete!")
    
    # Write the SFZ file
    sfz_path = f"{instrument_name}.sfz"
    print(f"Generating SFZ mapping file: {sfz_path}...")
    
    with open(sfz_path, "w") as f:
        f.write(f"// Generated by VST2SFZ (antigravity-cli)\n")
        f.write(f"// VST plugin: {args.vst}\n")
        if args.preset:
            f.write(f"// Loaded Preset: {args.preset}\n")
        f.write(f"// Sample Rate: {args.sr} Hz\n\n")
        
        f.write("<control>\n")
        f.write(f"default_path={samples_dir_name}/\n\n")
        
        f.write("<global>\n")
        # Ensure amplitude envelope release does not prematurely truncate natural release tail
        f.write(f"ampeg_release={max(args.release, 5.0)}\n\n")
        
        f.write("<group>\n")
        for region in sfz_regions:
            line = f"<region> sample={region['sample']} pitch_keycenter={region['pitch_keycenter']} "
            line += f"lokey={region['lokey']} hikey={region['hikey']} "
            line += f"lovel={region['lovel']} hivel={region['hivel']} "
            
            if region['seq_length'] > 1:
                line += f"seq_position={region['seq_position']} seq_length={region['seq_length']} "
                
            if region['loop_opcodes']:
                line += region['loop_opcodes']
                
            f.write(line.strip() + "\n")
            
    print(f"Successfully created {instrument_name}.sfz!")
    print("Sampling complete. Enjoy your SFZ instrument!")

if __name__ == "__main__":
    main()
