#!/usr/bin/env python3
"""
Sequential VST color chain processing for GM samples.

Uses DawDreamer to apply a high-quality production mastering/coloring chain:
  CHOWTape → spiff → TDR Nova → TDR Kotelnikov → Fresh Air → TAL-Chorus-LX → Dragonfly Room → A1StereoControl → BasicLimiter

Runs sequentially in a single thread to prevent CPU overload.
"""
import os
import re
import copy
import sys
import glob
import argparse
import numpy as np
import soundfile as sf
import dawdreamer as daw

CHOW_PATH = "/Library/Audio/Plug-Ins/VST3/CHOWTapeModel.vst3"
SPIFF_PATH = "/Library/Audio/Plug-Ins/VST3/spiff.vst3"
NOVA_PATH = "/Library/Audio/Plug-Ins/VST3/TDR Nova.vst3"
KOTELNIKOV_PATH = "/Library/Audio/Plug-Ins/VST3/TDR Kotelnikov.vst3"
FRESH_AIR_PATH = "/Library/Audio/Plug-Ins/VST3/Fresh Air.vst3"
CHORUS_PATH = "/Library/Audio/Plug-Ins/VST3/TAL-Chorus-LX.vst3"
STEREO_PATH = "/Library/Audio/Plug-Ins/VST3/A1StereoControl.vst3"
DRAGONFLY_PATH = "/Library/Audio/Plug-Ins/VST3/DragonflyRoomReverb.vst3"
LIMITER_PATH = "/Library/Audio/Plug-Ins/VST3/BasicLimiter.vst3"

SAMPLE_RATE = 96000
BUFFER_SIZE = 512

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
            fresh_mid=0.0, fresh_high=0.0,
            spiff_mode=1.0, spiff_boost=0.0, spiff_cut=0.0, spiff_sens=0.5, spiff_bypass=True,
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
        "stereo": {3: stereo_width, 19: 1.0},  # 3: width, 19: SafeBass ON
        "fresh_air": {
            "bypass": fresh_mid == 0.0 and fresh_high == 0.0,
            "mid": fresh_mid,
            "high": fresh_high
        },
        "spiff": {
            "bypass": spiff_bypass,
            "mode": spiff_mode,  # 1.0 = boost, 0.0 = cut
            "boost": spiff_boost,
            "cut": spiff_cut,
            "sens": spiff_sens
        }
    }

GROUP_PRESETS = {
    0:  _preset(tape_drive=0.30, tape_sat=0.35, tape_treble=0.55,            # Pianos: bright, warm
                b4_gain=0.583, b4_freq=0.85,
                rvb_dry=0.85, rvb_early=0.10, rvb_late=0.05,
                rvb_decay=0.05, rvb_size=0.20,
                stereo_width=0.50, chorus_wet=0.0,
                fresh_mid=0.08, fresh_high=0.12),
    1:  _preset(tape_drive=0.15, tape_sat=0.20,                              # Chrom Perc: clear, bright mallets
                b3_gain=0.604, b3_freq=0.72,
                rvb_dry=0.80, rvb_early=0.12, rvb_late=0.08,
                rvb_decay=0.10, rvb_diffuse=0.8,
                stereo_width=0.55,
                fresh_mid=0.05, fresh_high=0.15,
                spiff_mode=1.0, spiff_boost=0.15, spiff_sens=0.40, spiff_bypass=False),
    2:  _preset(tape_drive=0.50, tape_sat=0.50, tape_bass=0.45,              # Organs: warm, rotary motion
                b1_gain=0.375, b1_freq=0.30,
                b3_gain=0.562, b3_freq=0.62,
                rvb_dry=0.82, rvb_early=0.08, rvb_late=0.10,
                rvb_decay=0.12, rvb_size=0.30,
                stereo_width=0.60, chorus_wet=0.15,
                fresh_mid=0.02, fresh_high=0.02),
    3:  _preset(tape_drive=0.40, tape_sat=0.45,                              # Guitars: dense, warm pick attack
                b3_gain=0.583, b3_freq=0.72,
                rvb_dry=0.88, rvb_early=0.06, rvb_late=0.06,
                rvb_decay=0.04, rvb_size=0.15,
                stereo_width=0.55,
                fresh_mid=0.10, fresh_high=0.18,
                spiff_mode=1.0, spiff_boost=0.10, spiff_sens=0.40, spiff_bypass=False),
    4:  _preset(tape_drive=0.60, tape_sat=0.55, tape_bass=0.60,              # Bass: powerful, centered low-end
                hp_freq=0.06,
                b1_gain=0.625, b1_freq=0.18,
                b3_gain=0.444, b3_freq=0.55,
                rvb_dry=1.0,
                stereo_width=0.50,
                fresh_mid=0.0, fresh_high=0.0),
    5:  _preset(tape_drive=0.20, tape_sat=0.25,                              # Strings: wide, spacious orchestra
                b3_gain=0.583, b3_freq=0.72,
                rvb_dry=0.75, rvb_early=0.10, rvb_late=0.15,
                rvb_decay=0.18, rvb_size=0.40, rvb_diffuse=0.85,
                stereo_width=0.70,
                fresh_mid=0.05, fresh_high=0.10),
    6:  _preset(tape_drive=0.15, tape_sat=0.20,                              # Ensemble: voluminous, huge field
                b4_gain=0.604, b4_freq=0.88,
                rvb_dry=0.70, rvb_early=0.12, rvb_late=0.18,
                rvb_decay=0.25, rvb_size=0.45, rvb_diffuse=0.9,
                stereo_width=0.75,
                fresh_mid=0.04, fresh_high=0.08),
    7:  _preset(tape_drive=0.45, tape_sat=0.50,                              # Brass: bright, powerful
                b3_gain=0.604, b3_freq=0.68,
                rvb_dry=0.82, rvb_early=0.10, rvb_late=0.08,
                rvb_decay=0.10, rvb_size=0.25,
                stereo_width=0.60,
                fresh_mid=0.03, fresh_high=0.05),
    8:  _preset(tape_drive=0.25, tape_sat=0.30,                              # Reed: warm, expressive
                b3_gain=0.583, b3_freq=0.62,
                rvb_dry=0.85, rvb_early=0.08, rvb_late=0.07,
                rvb_decay=0.07, rvb_size=0.20,
                stereo_width=0.55,
                fresh_mid=0.05, fresh_high=0.10),
    9:  _preset(tape_drive=0.15, tape_sat=0.20,                              # Pipe: open, airy, wide cathedral
                b4_gain=0.604, b4_freq=0.88,
                rvb_dry=0.78, rvb_early=0.10, rvb_late=0.12,
                rvb_decay=0.15, rvb_size=0.35, rvb_diffuse=0.85,
                stereo_width=0.65,
                fresh_mid=0.05, fresh_high=0.10),
    10: _preset(tape_drive=0.50, tape_sat=0.50,                              # Synth Leads: punchy, thick lead
                b1_gain=0.458, b1_freq=0.25,
                b3_gain=0.583, b3_freq=0.75,
                rvb_dry=0.88, rvb_early=0.06, rvb_late=0.06,
                rvb_decay=0.02, rvb_size=0.10,
                stereo_width=0.55, chorus_wet=0.20,
                fresh_mid=0.15, fresh_high=0.20),
    11: _preset(tape_drive=0.30, tape_sat=0.35,                              # Synth Pads: deep, wide, lush chorus
                b1_gain=0.375, b1_freq=0.30,
                b4_gain=0.562, b4_freq=0.88,
                rvb_dry=0.65, rvb_early=0.10, rvb_late=0.25,
                rvb_decay=0.30, rvb_size=0.50, rvb_diffuse=0.95, rvb_spin=0.25,
                stereo_width=0.75, chorus_wet=0.40,
                fresh_mid=0.08, fresh_high=0.15),
    12: _preset(tape_drive=0.10, tape_sat=0.15,                              # FX: atmospheric, massive field
                rvb_dry=0.60, rvb_early=0.10, rvb_late=0.30,
                rvb_decay=0.40, rvb_size=0.60, rvb_diffuse=0.95, rvb_spin=0.30,
                stereo_width=0.80, chorus_wet=0.30,
                fresh_mid=0.10, fresh_high=0.20),
    13: _preset(tape_drive=0.30, tape_sat=0.35,                              # Ethnic: authentic strings
                b3_gain=0.583, b3_freq=0.72,
                rvb_dry=0.82, rvb_early=0.08, rvb_late=0.10,
                rvb_decay=0.10, rvb_size=0.25,
                stereo_width=0.55,
                fresh_mid=0.08, fresh_high=0.12,
                spiff_mode=1.0, spiff_boost=0.20, spiff_sens=0.50, spiff_bypass=False),
    14: _preset(tape_drive=0.20, tape_sat=0.25,                              # Percussive: punchy, tight center drums
                b3_gain=0.604, b3_freq=0.72,
                rvb_dry=0.80, rvb_early=0.10, rvb_late=0.10,
                rvb_decay=0.07, rvb_diffuse=0.8,
                stereo_width=0.50,
                fresh_mid=0.12, fresh_high=0.18,
                spiff_mode=1.0, spiff_boost=0.40, spiff_sens=0.60, spiff_bypass=False),
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
    preset = copy.deepcopy(GROUP_PRESETS.get(group, GROUP_PRESETS[0]))
    
    # Custom tweaks for specific instruments:
    if prog in (4, 5):  # Electric Piano 1 (Rhodes) and Electric Piano 2 (DX EP)
        preset["chorus_wet"] = 0.45
        preset["stereo"] = {3: 0.65, 19: 1.0}  # Width 130%, SafeBass ON
        preset["fresh_air"] = {"bypass": False, "mid": 0.12, "high": 0.18}
        
    return preset

def apply_preset(tape, eq, reverb, chorus, stereo, fresh_air, spiff, preset):
    """Configure all plugins for a given preset dict."""
    # CHOWTape
    for idx, val in preset["tape"].items():
        tape.set_parameter(idx, val)
    # TDR Nova
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
        chorus.set_parameter(1, 0.0)         # Dry/Wet to 0.0
        chorus.set_parameter(6, 1.0)         # Bypass ON
        
    # Configure Stereo (A1StereoControl)
    for idx, val in preset["stereo"].items():
        stereo.set_parameter(idx, val)

    # Configure Fresh Air (Slate Digital)
    fresh_settings = preset["fresh_air"]
    if fresh_settings["bypass"]:
        fresh_air.set_parameter(2, 1.0)  # Bypass ON
    else:
        fresh_air.set_parameter(2, 0.0)  # Bypass OFF
        fresh_air.set_parameter(0, fresh_settings["mid"])
        fresh_air.set_parameter(1, fresh_settings["high"])
        fresh_air.set_parameter(3, 1.0)  # Trim 0.0 dB

    # Configure spiff (oeksound)
    spiff_settings = preset["spiff"]
    if spiff_settings["bypass"]:
        spiff.set_parameter(38, 1.0)  # Bypass ON
        spiff.set_parameter(41, 1.0)  # Bypass ON
    else:
        spiff.set_parameter(38, 0.0)  # Bypass OFF
        spiff.set_parameter(41, 0.0)  # Bypass OFF
        spiff.set_parameter(0, spiff_settings["mode"])  # 1.0 = boost
        if spiff_settings["mode"] > 0.5:
            spiff.set_parameter(2, spiff_settings["boost"])  # boost depth
        else:
            spiff.set_parameter(1, spiff_settings["cut"])    # cut depth
        spiff.set_parameter(3, spiff_settings["sens"])       # sensitivity
        spiff.set_parameter(35, 1.0)                         # Mix 100%

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
# Sequential Processing Loop
# ---------------------------------------------------------------------------

def process_file(filepath, out_dir, engine, tape, spiff, eq, kotelnikov, fresh_air, chorus, stereo, reverb, limiter):
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
            return True, None
            
        audio_2d = audio.T.astype(np.float32)
        apply_preset(tape, eq, reverb, chorus, stereo, fresh_air, spiff, preset)
        
        # Build dynamic graph: pb → tape → spiff → eq → kotelnikov → fresh_air → chorus → [reverb] → stereo → limiter
        pb = engine.make_playback_processor("pb", audio_2d)
        
        connections = [
            (pb, []),
            (tape, ["pb"]),
            (spiff, ["tape"]),
            (eq, ["spiff"]),
            (kotelnikov, ["eq"]),
            (fresh_air, ["kot"]),
            (chorus, ["fresh"]),
        ]
        
        last_node = "cho"
        if preset["reverb"] is not None:
            connections.append((reverb, ["cho"]))
            last_node = "reverb"
            
        connections.append((stereo, [last_node]))
        connections.append((limiter, ["ste"]))
        
        engine.load_graph(connections)
        
        duration = len(audio) / sr
        engine.render(duration)
        out = engine.get_audio("limiter")
        
        # Peak-normalize to 0.95
        peak = float(np.max(np.abs(out)))
        if peak > 1e-6:
            out = out * (0.95 / peak)
            
        sf.write(os.path.join(out_dir, filename), out.T, SAMPLE_RATE, subtype="PCM_24")
        return True, None
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return False, f"{e}\n{tb}"

# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Single-threaded VST color chain processing.")
    parser.add_argument("--input", default="General_MIDI_samples_raw")
    parser.add_argument("--output", default="General_MIDI_samples")
    args = parser.parse_args()

    src_dir, out_dir = args.input, args.output
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(src_dir, "*.wav")))
    if not files:
        print(f"Error: no WAV files in {src_dir}")
        sys.exit(1)
    print(f"Found {len(files)} raw samples in {src_dir}")

    # Validate VST paths before starting
    for name, path in [("CHOWTape", CHOW_PATH), ("spiff", SPIFF_PATH), ("TDR Nova", NOVA_PATH),
                        ("Kotelnikov", KOTELNIKOV_PATH), ("Fresh Air", FRESH_AIR_PATH),
                        ("Chorus", CHORUS_PATH), ("StereoControl", STEREO_PATH),
                        ("Dragonfly", DRAGONFLY_PATH), ("BasicLimiter", LIMITER_PATH)]:
        if not os.path.exists(path):
            print(f"Error: {name} not found at {path}")
            sys.exit(1)

    print("Initializing DawDreamer engine and VST plugins (single-threaded)...")
    engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)
    tape = engine.make_plugin_processor("tape", CHOW_PATH)
    spiff = engine.make_plugin_processor("spiff", SPIFF_PATH)
    eq = engine.make_plugin_processor("eq", NOVA_PATH)
    kotelnikov = engine.make_plugin_processor("kot", KOTELNIKOV_PATH)
    fresh_air = engine.make_plugin_processor("fresh", FRESH_AIR_PATH)
    chorus = engine.make_plugin_processor("cho", CHORUS_PATH)
    stereo = engine.make_plugin_processor("ste", STEREO_PATH)
    reverb = engine.make_plugin_processor("reverb", DRAGONFLY_PATH)
    limiter = engine.make_plugin_processor("limiter", LIMITER_PATH)
    configure_kotelnikov(kotelnikov)
    configure_limiter(limiter)

    print(f"Processing {len(files)} samples sequentially...")
    total = len(files)
    for idx, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        success, err = process_file(filepath, out_dir, engine, tape, spiff, eq, kotelnikov, fresh_air, chorus, stereo, reverb, limiter)
        if not success:
            print(f"  [{idx}/{total}] FAILED: {filename} - {err}")
        elif idx % 100 == 0 or idx == total:
            print(f"  Processed [{idx}/{total}] samples... Last: {filename}")

    print(f"\n✓ Done! All {len(files)} samples processed → {out_dir}")

if __name__ == "__main__":
    main()
