#!/usr/bin/env python3
"""
Multiprocessed VST color chain processing for GM samples.

Uses Python's multiprocessing to process 2048 samples in parallel across
multiple CPU cores, minimizing processing time. Loads the plugins once
per worker process when starting up.

Each GM family gets tailored settings for:
  CHOWTape → TDR Nova → TDR Kotelnikov → TAL-Chorus-LX → Dragonfly Room → A1StereoControl → BasicLimiter
"""
import os
import re
import sys
import glob
import argparse
import numpy as np
import soundfile as sf
import dawdreamer as daw
import multiprocessing

CHOW_PATH = "/Library/Audio/Plug-Ins/VST3/CHOWTapeModel.vst3"
NOVA_PATH = "/Library/Audio/Plug-Ins/VST3/TDR Nova.vst3"
KOTELNIKOV_PATH = "/Library/Audio/Plug-Ins/VST3/TDR Kotelnikov.vst3"
CHORUS_PATH = "/Library/Audio/Plug-Ins/VST3/TAL-Chorus-LX.vst3"
STEREO_PATH = "/Library/Audio/Plug-Ins/VST3/A1StereoControl.vst3"
DRAGONFLY_PATH = "/Library/Audio/Plug-Ins/VST3/DragonflyRoomReverb.vst3"
LIMITER_PATH = "/Library/Audio/Plug-Ins/VST3/BasicLimiter.vst3"

SAMPLE_RATE = 96000
BUFFER_SIZE = 512

# Worker globals initialized once per process
_engine = None
_tape = None
_eq = None
_kotelnikov = None
_chorus = None
_stereo = None
_reverb = None
_limiter = None

# ---------------------------------------------------------------------------
# Per-group presets.
# ---------------------------------------------------------------------------

def _preset(tape_drive=0.35, tape_sat=0.4, tape_bass=0.5, tape_treble=0.5,
            hp_freq=0.087, b1_gain=0.444, b1_q=0.339, b1_freq=0.32,
            b3_gain=0.562, b3_q=0.393, b3_freq=0.68,
            b4_gain=0.583, b4_q=0.438, b4_freq=0.85,
            rvb_dry=0.88, rvb_early=0.08, rvb_late=0.04,
            rvb_size=0.167, rvb_predelay=0.08, rvb_decay=0.03,
            rvb_diffuse=0.7, rvb_spin=0.16, rvb_hicut=1.0,
            stereo_width=0.50, chorus_wet=0.0,
            bypass=False):
    return {
        "bypass": bypass,
        "tape": {0: 0.889, 1: 0.5, 2: 1.0,
                 16: tape_drive, 17: tape_sat, 18: 0.5,
                 8: tape_bass, 9: tape_treble},
        "eq": {50: hp_freq,
               2: b1_gain, 3: b1_q, 4: b1_freq,
               26: b3_gain, 27: b3_q, 28: b3_freq,
               38: b4_gain, 39: b4_q, 40: b4_freq},
        "reverb": None if rvb_dry >= 1.0 else {
            2: rvb_dry, 3: rvb_early, 5: rvb_late,
            6: rvb_size, 8: rvb_predelay, 9: rvb_decay,
            10: rvb_diffuse, 11: rvb_spin, 13: rvb_hicut},
        "chorus_wet": chorus_wet,
        "stereo": {3: stereo_width, 19: 1.0}  # 3: width, 19: SafeBass ON
    }

GROUP_PRESETS = {
    0:  _preset(tape_drive=0.30, tape_sat=0.35, tape_treble=0.55,            # Pianos: bright, warm
                b4_gain=0.583, b4_freq=0.85,
                rvb_dry=0.85, rvb_early=0.10, rvb_late=0.05,
                rvb_decay=0.05, rvb_size=0.20,
                stereo_width=0.50, chorus_wet=0.0),
    1:  _preset(tape_drive=0.15, tape_sat=0.20,                              # Chrom Perc: clear, bright
                b3_gain=0.604, b3_freq=0.72,
                rvb_dry=0.80, rvb_early=0.12, rvb_late=0.08,
                rvb_decay=0.10, rvb_diffuse=0.8,
                stereo_width=0.55),
    2:  _preset(tape_drive=0.50, tape_sat=0.50, tape_bass=0.45,              # Organs: warm, rotary motion
                b1_gain=0.375, b1_freq=0.30,
                b3_gain=0.562, b3_freq=0.62,
                rvb_dry=0.82, rvb_early=0.08, rvb_late=0.10,
                rvb_decay=0.12, rvb_size=0.30,
                stereo_width=0.60, chorus_wet=0.15),
    3:  _preset(tape_drive=0.40, tape_sat=0.45,                              # Guitars: dense, warm
                b3_gain=0.583, b3_freq=0.72,
                rvb_dry=0.88, rvb_early=0.06, rvb_late=0.06,
                rvb_decay=0.04, rvb_size=0.15,
                stereo_width=0.55),
    4:  _preset(tape_drive=0.60, tape_sat=0.55, tape_bass=0.60,              # Bass: powerful, centered low-end
                hp_freq=0.06,
                b1_gain=0.625, b1_freq=0.18,
                b3_gain=0.444, b3_freq=0.55,
                rvb_dry=1.0,
                stereo_width=0.50),
    5:  _preset(tape_drive=0.20, tape_sat=0.25,                              # Strings: wide, spacious orchestra
                b3_gain=0.583, b3_freq=0.72,
                rvb_dry=0.75, rvb_early=0.10, rvb_late=0.15,
                rvb_decay=0.18, rvb_size=0.40, rvb_diffuse=0.85,
                stereo_width=0.70),
    6:  _preset(tape_drive=0.15, tape_sat=0.20,                              # Ensemble: voluminous, huge field
                b4_gain=0.604, b4_freq=0.88,
                rvb_dry=0.70, rvb_early=0.12, rvb_late=0.18,
                rvb_decay=0.25, rvb_size=0.45, rvb_diffuse=0.9,
                stereo_width=0.75),
    7:  _preset(tape_drive=0.45, tape_sat=0.50,                              # Brass: bright, powerful
                b3_gain=0.604, b3_freq=0.68,
                rvb_dry=0.82, rvb_early=0.10, rvb_late=0.08,
                rvb_decay=0.10, rvb_size=0.25,
                stereo_width=0.60),
    8:  _preset(tape_drive=0.25, tape_sat=0.30,                              # Reed: warm, expressive
                b3_gain=0.583, b3_freq=0.62,
                rvb_dry=0.85, rvb_early=0.08, rvb_late=0.07,
                rvb_decay=0.07, rvb_size=0.20,
                stereo_width=0.55),
    9:  _preset(tape_drive=0.15, tape_sat=0.20,                              # Pipe: open, airy, wide cathedral
                b4_gain=0.604, b4_freq=0.88,
                rvb_dry=0.78, rvb_early=0.10, rvb_late=0.12,
                rvb_decay=0.15, rvb_size=0.35, rvb_diffuse=0.85,
                stereo_width=0.65),
    10: _preset(tape_drive=0.50, tape_sat=0.50,                              # Synth Leads: punchy, thick lead
                b1_gain=0.458, b1_freq=0.25,
                b3_gain=0.583, b3_freq=0.75,
                rvb_dry=0.88, rvb_early=0.06, rvb_late=0.06,
                rvb_decay=0.02, rvb_size=0.10,
                stereo_width=0.55, chorus_wet=0.20),
    11: _preset(tape_drive=0.30, tape_sat=0.35,                              # Synth Pads: deep, wide, lush chorus
                b1_gain=0.375, b1_freq=0.30,
                b4_gain=0.562, b4_freq=0.88,
                rvb_dry=0.65, rvb_early=0.10, rvb_late=0.25,
                rvb_decay=0.30, rvb_size=0.50, rvb_diffuse=0.95, rvb_spin=0.25,
                stereo_width=0.75, chorus_wet=0.40),
    12: _preset(tape_drive=0.10, tape_sat=0.15,                              # FX: atmospheric, massive field
                rvb_dry=0.60, rvb_early=0.10, rvb_late=0.30,
                rvb_decay=0.40, rvb_size=0.60, rvb_diffuse=0.95, rvb_spin=0.30,
                stereo_width=0.80, chorus_wet=0.30),
    13: _preset(tape_drive=0.30, tape_sat=0.35,                              # Ethnic: authentic
                b3_gain=0.583, b3_freq=0.72,
                rvb_dry=0.82, rvb_early=0.08, rvb_late=0.10,
                rvb_decay=0.10, rvb_size=0.25,
                stereo_width=0.55),
    14: _preset(tape_drive=0.20, tape_sat=0.25,                              # Percussive: punchy, tight center
                b3_gain=0.604, b3_freq=0.72,
                rvb_dry=0.80, rvb_early=0.10, rvb_late=0.10,
                rvb_decay=0.07, rvb_diffuse=0.8,
                stereo_width=0.50),
    15: _preset(bypass=True),                                                # Sound FX: raw passthrough
}

GROUP_NAMES = {
    0: "Pianos", 1: "Chromatic Perc", 2: "Organs", 3: "Guitars",
    4: "Bass", 5: "Strings", 6: "Ensemble", 7: "Brass",
    8: "Reed", 9: "Pipe", 10: "Synth Leads", 11: "Synth Pads",
    12: "FX", 13: "Ethnic", 14: "Percussive", 15: "Sound FX",
}

def get_preset_for_program(prog):
    """Returns the preset configuration customized for the specific GM program."""
    group = prog // 8
    preset = GROUP_PRESETS.get(group, GROUP_PRESETS[0]).copy()
    
    # Custom tweaks for specific instruments:
    if prog in (4, 5):  # Electric Piano 1 (Rhodes) and Electric Piano 2 (DX EP)
        preset["chorus_wet"] = 0.45
        preset["stereo"] = {3: 0.65, 19: 1.0}  # Width 130%, SafeBass ON
        
    return preset

def apply_preset(tape, eq, reverb, chorus, stereo, preset):
    """Configure all plugins for a given preset dict."""
    for idx, val in preset["tape"].items():
        tape.set_parameter(idx, val)
    for idx, val in preset["eq"].items():
        eq.set_parameter(idx, val)
        
    rvb_settings = preset["reverb"]
    if rvb_settings is not None:
        for idx, val in rvb_settings.items():
            reverb.set_parameter(idx, val)
            
    # Configure Chorus (TAL-Chorus-LX)
    chorus_wet = preset.get("chorus_wet", 0.0)
    if chorus_wet > 0.0:
        chorus.set_parameter(1, chorus_wet)  # Dry/Wet
        chorus.set_parameter(2, 1.0)         # Stereo Width 10.0
        chorus.set_parameter(3, 1.0)         # Chorus 1 ON
        chorus.set_parameter(4, 0.0)         # Chorus 2 OFF
        chorus.set_parameter(6, 0.0)         # Bypass OFF (Active)
    else:
        chorus.set_parameter(6, 1.0)         # Bypass ON
        
    # Configure Stereo (A1StereoControl)
    for idx, val in preset["stereo"].items():
        stereo.set_parameter(idx, val)

def configure_kotelnikov(kotelnikov):
    """TDR Kotelnikov: transparent mastering compressor."""
    kotelnikov.set_parameter(0, 0.45)   # Threshold ~-14 dBFS
    kotelnikov.set_parameter(3, 0.45)   # Ratio 1.5:1
    kotelnikov.set_parameter(4, 0.30)   # Attack ~3 ms
    kotelnikov.set_parameter(5, 0.40)   # Release Peak ~100 ms
    kotelnikov.set_parameter(6, 0.55)   # Release RMS ~300 ms
    kotelnikov.set_parameter(8, 0.0)    # Dry Mix off
    kotelnikov.set_parameter(9, 1.0)    # Dry Wet 100%
    kotelnikov.set_parameter(11, 0.55)  # Out Gain +3 dB makeup

def configure_limiter(limiter):
    """BasicLimiter: true brick-wall ceiling at -1 dBFS."""
    limiter.set_parameter(0, 0.0)   # bypass off
    limiter.set_parameter(1, 0.45)  # threshold ~-1 dB
    limiter.set_parameter(7, 1.0)   # true peak on

def program_from_name(filename):
    """Extract GM program index from gm_NNN_*.wav."""
    m = re.match(r"gm_(\d{3})_", filename)
    return int(m.group(1)) if m else 0

# ---------------------------------------------------------------------------
# Multiprocessing Worker Setup
# ---------------------------------------------------------------------------

def init_worker():
    """Initializes global DawDreamer engine and VST processors once per process."""
    global _engine, _tape, _eq, _kotelnikov, _chorus, _stereo, _reverb, _limiter
    _engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)
    _tape = _engine.make_plugin_processor("tape", CHOW_PATH)
    _eq = _engine.make_plugin_processor("eq", NOVA_PATH)
    _kotelnikov = _engine.make_plugin_processor("kot", KOTELNIKOV_PATH)
    _chorus = _engine.make_plugin_processor("cho", CHORUS_PATH)
    _stereo = _engine.make_plugin_processor("ste", STEREO_PATH)
    _reverb = _engine.make_plugin_processor("reverb", DRAGONFLY_PATH)
    _limiter = _engine.make_plugin_processor("limiter", LIMITER_PATH)
    configure_kotelnikov(_kotelnikov)
    configure_limiter(_limiter)

def process_file_worker(args):
    """Processes a single WAV sample inside a worker process."""
    filepath, out_dir = args
    filename = os.path.basename(filepath)
    prog = program_from_name(filename)
    preset = get_preset_for_program(prog)
    
    try:
        audio, sr = sf.read(filepath)
        if audio.ndim == 1:
            audio = np.column_stack((audio, audio))
            
        if preset["bypass"]:
            # Raw passthrough — just normalize and copy
            out = audio.T.astype(np.float32)
            peak = float(np.max(np.abs(out)))
            if peak > 1e-6:
                out = out * (0.95 / peak)
            sf.write(os.path.join(out_dir, filename), out.T, SAMPLE_RATE, subtype="PCM_24")
            return filename, True, None
            
        audio_2d = audio.T.astype(np.float32)
        apply_preset(_tape, _eq, _reverb, _chorus, _stereo, preset)
        
        # Build dynamic graph: pb → tape → eq → kotelnikov → chorus → [reverb] → stereo → limiter
        pb = _engine.make_playback_processor("pb", audio_2d)
        
        connections = [
            (pb, []),
            (_tape, ["pb"]),
            (_eq, ["tape"]),
            (_kotelnikov, ["eq"]),
            (_chorus, ["kot"]),
        ]
        
        last_node = "cho"
        if preset["reverb"] is not None:
            connections.append((_reverb, ["cho"]))
            last_node = "reverb"
            
        connections.append((_stereo, [last_node]))
        connections.append((_limiter, ["ste"]))
        
        _engine.load_graph(connections)
        
        duration = len(audio) / SAMPLE_RATE
        _engine.render(duration)
        out = _engine.get_audio()
        
        # Peak-normalize to 0.95
        peak = float(np.max(np.abs(out)))
        if peak > 1e-6:
            out = out * (0.95 / peak)
            
        sf.write(os.path.join(out_dir, filename), out.T, SAMPLE_RATE, subtype="PCM_24")
        return filename, True, None
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return filename, False, f"{e}\n{tb}"

# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Multiprocessed VST color chain processing.")
    parser.add_argument("--input", default="General_MIDI_samples_raw")
    parser.add_argument("--output", default="General_MIDI_samples")
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel worker processes")
    args = parser.parse_args()

    src_dir, out_dir = args.input, args.output
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(src_dir, "*.wav")))
    if not files:
        print(f"Error: no WAV files in {src_dir}")
        sys.exit(1)
    print(f"Found {len(files)} raw samples in {src_dir}")

    # Validate VST paths before launching processes
    for name, path in [("CHOWTape", CHOW_PATH), ("TDR Nova", NOVA_PATH),
                        ("Kotelnikov", KOTELNIKOV_PATH), ("Chorus", CHORUS_PATH),
                        ("StereoControl", STEREO_PATH), ("Dragonfly", DRAGONFLY_PATH),
                        ("BasicLimiter", LIMITER_PATH)]:
        if not os.path.exists(path):
            print(f"Error: {name} not found at {path}")
            sys.exit(1)

    # Set start method to 'spawn' for safety on macOS (essential for VST threads)
    multiprocessing.set_start_method("spawn", force=True)

    # Launch parallel process pool
    num_workers = args.workers or multiprocessing.cpu_count()
    print(f"Starting parallel processing pool with {num_workers} workers...")
    
    pool_args = [(f, out_dir) for f in files]
    
    completed = 0
    total = len(files)
    
    with multiprocessing.Pool(processes=num_workers, initializer=init_worker) as pool:
        # Use imap_unordered for speed as the order of completion doesn't matter
        for filename, success, err in pool.imap_unordered(process_file_worker, pool_args):
            completed += 1
            if not success:
                print(f"  FAILED: {filename} - {err}")
            elif completed % 100 == 0 or completed == total:
                print(f"  Processed [{completed}/{total}] samples... Last: {filename}")

    print(f"\n✓ Done! All {len(files)} samples processed → {out_dir}")

if __name__ == "__main__":
    main()
