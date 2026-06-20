import dawdreamer as daw
import mido
import numpy as np
import os
import soundfile as sf

def create_bach_midi(output_path="melody.mid"):
    # 4 bars of Bach's Prelude in C Major
    # We will represent absolute notes as: (time_sec, msg_type, note, velocity, duration)
    # We will build a list of absolute events (time, type, note, velocity)
    abs_events = []
    
    # Helper to add a bar of arpeggios
    # Each bar has two identical halves of 8 notes each (total 16 notes, 4.0 seconds per bar)
    def add_bar(start_time, n1, n2, n3, n4, n5):
        # n1: Bass 1
        # n2: Bass 2
        # n3: Tenor
        # n4: Alto
        # n5: Soprano
        
        # We repeat the 8-note pattern twice
        for half in [0, 2.0]:
            t_offset = start_time + half
            # Absolute note-on times and durations
            notes = [
                (0.0, n1, 2.0),
                (0.25, n2, 1.75),
                (0.5, n3, 1.5),
                (0.75, n4, 1.25),
                (1.0, n5, 1.0),
                (1.25, n3, 0.75),
                (1.5, n4, 0.5),
                (1.75, n5, 0.25),
            ]
            for t_rel, note_num, dur in notes:
                on_t = t_offset + t_rel
                off_t = t_offset + t_rel + dur
                abs_events.append((on_t, 'note_on', {'note': note_num, 'velocity': 90}))
                abs_events.append((off_t, 'note_off', {'note': note_num, 'velocity': 0}))

    # Bar 1: C3, E3, G3, C4, E4
    add_bar(0.0, 48, 52, 55, 60, 64)
    # Bar 2: D3, F3, A3, D4, F4
    add_bar(4.0, 50, 53, 57, 62, 65)
    # Bar 3: B2, D3, G3, D4, F4
    add_bar(8.0, 47, 50, 55, 62, 65)
    # Bar 4: C3, E3, G3, C4, E4
    add_bar(12.0, 48, 52, 55, 60, 64)
    
    # End on a long held C Major chord
    abs_events.append((16.0, 'note_on', {'note': 36, 'velocity': 90})) # C2
    abs_events.append((16.0, 'note_on', {'note': 48, 'velocity': 90})) # C3
    abs_events.append((16.0, 'note_on', {'note': 52, 'velocity': 85})) # E3
    abs_events.append((16.0, 'note_on', {'note': 55, 'velocity': 85})) # G3
    abs_events.append((16.0, 'note_on', {'note': 60, 'velocity': 80})) # C4
    abs_events.append((16.0, 'note_on', {'note': 64, 'velocity': 80})) # E4
    
    abs_events.append((20.0, 'note_off', {'note': 36, 'velocity': 0}))
    abs_events.append((20.0, 'note_off', {'note': 48, 'velocity': 0}))
    abs_events.append((20.0, 'note_off', {'note': 52, 'velocity': 0}))
    abs_events.append((20.0, 'note_off', {'note': 55, 'velocity': 0}))
    abs_events.append((20.0, 'note_off', {'note': 60, 'velocity': 0}))
    abs_events.append((20.0, 'note_off', {'note': 64, 'velocity': 0}))
    
    # Sort events chronologically, note-offs before note-ons if they occur at the exact same tick
    abs_events.sort(key=lambda x: (x[0], 0 if x[1] == 'note_off' else 1))
    
    # Convert absolute events to mido delta events
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    track.append(mido.Message('program_change', program=0, time=0))
    
    ticks_per_second = 960 # Tick resolution
    prev_tick = 0
    for time_sec, msg_type, args in abs_events:
        abs_tick = int(round(time_sec * ticks_per_second))
        delta_tick = max(0, abs_tick - prev_tick)
        prev_tick = abs_tick
        
        msg = mido.Message(msg_type, time=delta_tick, **args)
        track.append(msg)
        
    mid.save(output_path)
    return output_path

def render_melody():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    
    mid_path = os.path.join(project_root, "temp_melody_vst.mid")
    create_bach_midi(mid_path)
    print(f"Created MIDI file: {mid_path}")
    
    sr = 96000
    engine = daw.RenderEngine(sr, 512)
    
    vst_path = "/Library/Audio/Plug-Ins/VST3/Surge XT.vst3"
    print(f"Loading plugin: {vst_path}")
    synth = engine.make_plugin_processor("synth", vst_path)
    
    # Connect in graph
    engine.load_graph([(synth, [])])
    
    # Load MIDI file
    synth.load_midi(mid_path)
    
    # Render 21 seconds (16s melody + 4s final chord + 1s tail)
    render_dur = 21.0
    print(f"Rendering {render_dur} seconds of performance...")
    engine.render(render_dur)
    
    audio = engine.get_audio()
    
    # Apply a nice reverb via Pedalboard to make it sound lush
    print("Applying reverb and delay post-processing...")
    import pedalboard
    from pedalboard import Pedalboard, Reverb, Delay
    
    board = Pedalboard([
        Reverb(room_size=0.6, wet_level=0.25, dry_level=0.75),
        Delay(delay_seconds=0.375, feedback=0.2, mix=0.1) # dotted eighth delay
    ])
    
    processed = board(audio, sr)
    
    output_path = os.path.join(project_root, "Surge_DX_Piano_Melody.wav")
    sf.write(output_path, processed.T, sr, subtype='PCM_24')
    print(f"Melody successfully rendered and saved to {output_path}!")
    
    # Clean up temp midi file
    if os.path.exists(mid_path):
        os.remove(mid_path)

if __name__ == "__main__":
    render_melody()
