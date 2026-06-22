#!/usr/bin/env python3
"""
VST color chain processing for GM samples — per-group professional presets.

Each GM family (group = program_index // 8) gets tailored settings for the
4-plugin chain (CHOWTape → TDR Nova → Dragonfly Room → BasicLimiter),
matching how a mixing engineer would treat each instrument type.

Usage:
  python process_samples_vst.py [--input General_MIDI_samples_raw]
                                [--output General_MIDI_samples]
"""
import os
import re
import sys
import glob
import argparse

import numpy as np
import soundfile as sf
import dawdreamer as daw

CHOW_PATH = "/Library/Audio/Plug-Ins/VST3/CHOWTapeModel.vst3"
NOVA_PATH = "/Library/Audio/Plug-Ins/VST3/TDR Nova.vst3"
KOTELNIKOV_PATH = "/Library/Audio/Plug-Ins/VST3/TDR Kotelnikov.vst3"
DRAGONFLY_PATH = "/Library/Audio/Plug-Ins/VST3/DragonflyRoomReverb.vst3"
LIMITER_PATH = "/Library/Audio/Plug-Ins/VST3/BasicLimiter.vst3"

SAMPLE_RATE = 96000
BUFFER_SIZE = 512


# ---------------------------------------------------------------------------
# Per-group presets.
#
# Each preset is a dict with keys:
#   tape:   dict of CHOW param indices → values
#   eq:     dict of TDR Nova param indices → values
#   reverb: dict of Dragonfly param indices → values, or None to bypass
#   bypass: if True, skip ALL processing (copy raw)
#
# Param indices (verified via dawdreamer get_parameters_description):
#   CHOW: 0=InputGain, 1=OutputGain, 2=DryWet, 16=Drive, 17=Saturation,
#         18=Bias, 8=ToneBass, 9=ToneTreble
#   Nova: 50=HP Freq, 2/3/4 = B1 Gain/Q/Freq, 26/27/28 = B3 Gain/Q/Freq,
#         38/39/40 = B4 Gain/Q/Freq
#   Dragonfly: 2=Dry, 3=Early, 5=Late, 6=Size, 8=Predelay, 9=Decay,
#              10=Diffuse, 11=Spin, 13=HighCut
# ---------------------------------------------------------------------------

def _preset(tape_drive=0.35, tape_sat=0.4, tape_bass=0.5, tape_treble=0.5,
            hp_freq=0.087, b1_gain=0.444, b1_q=0.339, b1_freq=0.32,
            b3_gain=0.562, b3_q=0.393, b3_freq=0.68,
            b4_gain=0.583, b4_q=0.438, b4_freq=0.85,
            rvb_dry=0.88, rvb_early=0.08, rvb_late=0.04,
            rvb_size=0.167, rvb_predelay=0.08, rvb_decay=0.03,
            rvb_diffuse=0.7, rvb_spin=0.16, rvb_hicut=1.0,
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
    }


# GM group → preset. group = program_index // 8.
# 0=Pianos, 1=Chromatic Perc, 2=Organs, 3=Guitars, 4=Bass, 5=Strings,
# 6=Ensemble, 7=Brass, 8=Reed, 9=Pipe, 10=Synth Leads, 11=Synth Pads,
# 12=FX, 13=Ethnic, 14=Percussive, 15=Sound FX

GROUP_PRESETS = {
    0:  _preset(tape_drive=0.30, tape_sat=0.35, tape_treble=0.55,            # Pianos: bright, warm
                b4_gain=0.583, b4_freq=0.85,                                 # +2dB air @ 10kHz
                rvb_dry=0.85, rvb_early=0.10, rvb_late=0.05,
                rvb_decay=0.05, rvb_size=0.20),                              # small room, 0.5s
    1:  _preset(tape_drive=0.15, tape_sat=0.20,                              # Chrom Perc: clear, bright
                b3_gain=0.604, b3_freq=0.72,                                 # +3dB @ 5kHz attack
                rvb_dry=0.80, rvb_early=0.12, rvb_late=0.08,
                rvb_decay=0.10, rvb_diffuse=0.8),                            # plate-ish, 0.8s
    2:  _preset(tape_drive=0.50, tape_sat=0.50, tape_bass=0.45,              # Organs: warm, fat
                b1_gain=0.375, b1_freq=0.30,                                 # -3dB @ 300Hz de-box
                b3_gain=0.562, b3_freq=0.62,                                 # +2dB @ 2kHz
                rvb_dry=0.82, rvb_early=0.08, rvb_late=0.10,
                rvb_decay=0.12, rvb_size=0.30),                              # large room, 1.0s
    3:  _preset(tape_drive=0.40, tape_sat=0.45,                              # Guitars: dense, warm
                b3_gain=0.583, b3_freq=0.72,                                 # +2dB @ 5kHz presence
                rvb_dry=0.88, rvb_early=0.06, rvb_late=0.06,
                rvb_decay=0.04, rvb_size=0.15),                              # small room, 0.4s
    4:  _preset(tape_drive=0.60, tape_sat=0.55, tape_bass=0.60,              # Bass: powerful, tight
                hp_freq=0.06,                                                # HP ~30Hz
                b1_gain=0.625, b1_freq=0.18,                                 # +3dB @ 80Hz sub
                b3_gain=0.444, b3_freq=0.55,                                 # -2dB @ 400Hz mud
                rvb_dry=1.0),                                                # NO reverb
    5:  _preset(tape_drive=0.20, tape_sat=0.25,                              # Strings: wide, spacious
                b3_gain=0.583, b3_freq=0.72,                                 # +2dB @ 5kHz bow
                rvb_dry=0.75, rvb_early=0.10, rvb_late=0.15,
                rvb_decay=0.18, rvb_size=0.40, rvb_diffuse=0.85),            # hall, 1.5s
    6:  _preset(tape_drive=0.15, tape_sat=0.20,                              # Ensemble: voluminous
                b4_gain=0.604, b4_freq=0.88,                                 # +3dB @ 8kHz air
                rvb_dry=0.70, rvb_early=0.12, rvb_late=0.18,
                rvb_decay=0.25, rvb_size=0.45, rvb_diffuse=0.9),             # large hall, 2.0s
    7:  _preset(tape_drive=0.45, tape_sat=0.50,                              # Brass: bright, powerful
                b3_gain=0.604, b3_freq=0.68,                                 # +3dB @ 3kHz brightness
                rvb_dry=0.82, rvb_early=0.10, rvb_late=0.08,
                rvb_decay=0.10, rvb_size=0.25),                              # medium room, 0.8s
    8:  _preset(tape_drive=0.25, tape_sat=0.30,                              # Reed: warm, expressive
                b3_gain=0.583, b3_freq=0.62,                                 # +2dB @ 2kHz presence
                rvb_dry=0.85, rvb_early=0.08, rvb_late=0.07,
                rvb_decay=0.07, rvb_size=0.20),                              # small room, 0.6s
    9:  _preset(tape_drive=0.15, tape_sat=0.20,                              # Pipe: open, airy
                b4_gain=0.604, b4_freq=0.88,                                 # +3dB @ 10kHz breath
                rvb_dry=0.78, rvb_early=0.10, rvb_late=0.12,
                rvb_decay=0.15, rvb_size=0.35, rvb_diffuse=0.85),            # hall, 1.2s
    10: _preset(tape_drive=0.50, tape_sat=0.50,                              # Synth Leads: punchy
                b1_gain=0.458, b1_freq=0.25,                                 # -2dB @ 200Hz
                b3_gain=0.583, b3_freq=0.75,                                 # +2dB @ 4kHz
                rvb_dry=0.88, rvb_early=0.06, rvb_late=0.06,
                rvb_decay=0.02, rvb_size=0.10),                              # tiny room, 0.3s
    11: _preset(tape_drive=0.30, tape_sat=0.35,                              # Synth Pads: deep, wide
                b1_gain=0.375, b1_freq=0.30,                                 # -3dB @ 300Hz
                b4_gain=0.562, b4_freq=0.88,                                 # +1dB @ 8kHz
                rvb_dry=0.65, rvb_early=0.10, rvb_late=0.25,
                rvb_decay=0.30, rvb_size=0.50, rvb_diffuse=0.95, rvb_spin=0.25),  # huge hall, 2.5s
    12: _preset(tape_drive=0.10, tape_sat=0.15,                              # FX: atmospheric
                rvb_dry=0.60, rvb_early=0.10, rvb_late=0.30,
                rvb_decay=0.40, rvb_size=0.60, rvb_diffuse=0.95, rvb_spin=0.30),  # massive, 3.0s
    13: _preset(tape_drive=0.30, tape_sat=0.35,                              # Ethnic: authentic
                b3_gain=0.583, b3_freq=0.72,                                 # +2dB @ 4kHz
                rvb_dry=0.82, rvb_early=0.08, rvb_late=0.10,
                rvb_decay=0.10, rvb_size=0.25),                              # medium room, 0.8s
    14: _preset(tape_drive=0.20, tape_sat=0.25,                              # Percussive: punchy
                b3_gain=0.604, b3_freq=0.72,                                 # +3dB @ 5kHz punch
                rvb_dry=0.80, rvb_early=0.10, rvb_late=0.10,
                rvb_decay=0.07, rvb_diffuse=0.8),                            # plate, 0.6s
    15: _preset(bypass=True),                                               # Sound FX: raw passthrough
}


GROUP_NAMES = {
    0: "Pianos", 1: "Chromatic Perc", 2: "Organs", 3: "Guitars",
    4: "Bass", 5: "Strings", 6: "Ensemble", 7: "Brass",
    8: "Reed", 9: "Pipe", 10: "Synth Leads", 11: "Synth Pads",
    12: "FX", 13: "Ethnic", 14: "Percussive", 15: "Sound FX",
}


def apply_preset(tape, eq, reverb, preset):
    """Configure all plugins for a given preset dict."""
    for idx, val in preset["tape"].items():
        tape.set_parameter(idx, val)
    for idx, val in preset["eq"].items():
        eq.set_parameter(idx, val)
    rvb_settings = preset["reverb"]
    if rvb_settings is not None:
        for idx, val in rvb_settings.items():
            reverb.set_parameter(idx, val)


def configure_kotelnikov(kotelnikov):
    """TDR Kotelnikov: transparent mastering compressor.

    Runs AFTER EQ, BEFORE reverb. Glues the sound together and controls
    dynamics transparently (Kotelnikov is designed to be "invisible" — no
    tonal coloration, just gentle level management). Settings are gentle:
    -1 dB threshold, 1.5:1 ratio, fast peak + slow RMS release. This makes
    sfizz render output as dense and consistent as the my-py renderer.
    """
    kotelnikov.set_parameter(0, 0.45)   # Threshold ~-14 dBFS (catches peaks)
    kotelnikov.set_parameter(3, 0.45)   # Ratio 1.5:1 (very gentle)
    kotelnikov.set_parameter(4, 0.30)   # Attack ~3 ms (fast but not clicky)
    kotelnikov.set_parameter(5, 0.40)   # Release Peak ~100 ms
    kotelnikov.set_parameter(6, 0.55)   # Release RMS ~300 ms (slow, transparent)
    kotelnikov.set_parameter(8, 0.0)    # Dry Mix off
    kotelnikov.set_parameter(9, 1.0)    # Dry Wet 100% (full compression)
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


def main():
    parser = argparse.ArgumentParser(description="Per-group VST color chain processing.")
    parser.add_argument("--input", default="General_MIDI_samples_raw")
    parser.add_argument("--output", default="General_MIDI_samples")
    args = parser.parse_args()

    src_dir, out_dir = args.input, args.output
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(src_dir, "*.wav")))
    if not files:
        print(f"Error: no WAV files in {src_dir}")
        sys.exit(1)
    print(f"Found {len(files)} raw samples.")

    for name, path in [("CHOWTape", CHOW_PATH), ("TDR Nova", NOVA_PATH),
                        ("Kotelnikov", KOTELNIKOV_PATH),
                        ("Dragonfly", DRAGONFLY_PATH), ("BasicLimiter", LIMITER_PATH)]:
        if not os.path.exists(path):
            print(f"Error: {name} not found at {path}")
            sys.exit(1)

    engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)
    tape = engine.make_plugin_processor("tape", CHOW_PATH)
    eq = engine.make_plugin_processor("eq", NOVA_PATH)
    kotelnikov = engine.make_plugin_processor("kot", KOTELNIKOV_PATH)
    reverb = engine.make_plugin_processor("reverb", DRAGONFLY_PATH)
    limiter = engine.make_plugin_processor("limiter", LIMITER_PATH)
    configure_kotelnikov(kotelnikov)
    configure_limiter(limiter)

    # Group files by GM group for logging
    last_group = -1
    print(f"\nProcessing {len(files)} samples with per-group presets...\n")

    for idx, f in enumerate(files):
        name = os.path.basename(f)
        prog = program_from_name(name)
        group = prog // 8
        preset = GROUP_PRESETS.get(group, GROUP_PRESETS[0])

        if group != last_group:
            gname = GROUP_NAMES.get(group, f"Group {group}")
            bypass_tag = " [BYPASS]" if preset["bypass"] else ""
            print(f"  → {gname} (programs {group*8}-{group*8+7}){bypass_tag}")
            last_group = group

        audio, sr = sf.read(f)
        if audio.ndim == 1:
            audio = np.column_stack((audio, audio))

        if preset["bypass"]:
            # Raw passthrough — just normalize and copy
            out = audio.T.astype(np.float32)
            peak = float(np.max(np.abs(out)))
            if peak > 1e-6:
                out = out * (0.95 / peak)
            sf.write(os.path.join(out_dir, name), out.T, SAMPLE_RATE, subtype="PCM_24")
            continue

        audio_2d = audio.T.astype(np.float32)
        apply_preset(tape, eq, reverb, preset)

        # Build graph: playback → tape → eq → kotelnikov → [reverb] → limiter
        pb = engine.make_playback_processor("pb", audio_2d)
        if preset["reverb"] is not None:
            engine.load_graph([
                (pb, []),
                (tape, ["pb"]),
                (eq, ["tape"]),
                (kotelnikov, ["eq"]),
                (reverb, ["kot"]),
                (limiter, ["reverb"]),
            ])
        else:
            # No reverb (e.g. bass): eq → kotelnikov → limiter
            engine.load_graph([
                (pb, []),
                (tape, ["pb"]),
                (eq, ["tape"]),
                (kotelnikov, ["eq"]),
                (limiter, ["kot"]),
            ])

        duration = len(audio) / SAMPLE_RATE
        engine.render(duration)
        out = engine.get_audio()

        # Peak-normalize to 0.95
        peak = float(np.max(np.abs(out)))
        if peak > 1e-6:
            out = out * (0.95 / peak)

        sf.write(os.path.join(out_dir, name), out.T, SAMPLE_RATE, subtype="PCM_24")

    print(f"\n✓ Done! {len(files)} samples processed → {out_dir}")


if __name__ == "__main__":
    main()
