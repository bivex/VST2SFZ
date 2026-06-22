#!/usr/bin/env python3
"""
VST color chain processing for GM samples.

Processes raw samples through real VST plugins via DawDreamer:
  CHOWTapeModel (tape saturation) → TDR Nova (EQ) → Dragonfly Room (reverb)

Adds warmth (tape harmonics), clarity (surgical EQ), and space (room ambience)
to raw Surge XT samples, making them sound like professionally recorded
instruments rather than sterile synth output.

Usage:
  python process_samples_vst.py [--input General_MIDI_samples_raw]
                                [--output General_MIDI_samples]
"""
import os
import sys
import glob
import argparse

import numpy as np
import soundfile as sf
import dawdreamer as daw

CHOW_PATH = "/Library/Audio/Plug-Ins/VST3/CHOWTapeModel.vst3"
NOVA_PATH = "/Library/Audio/Plug-Ins/VST3/TDR Nova.vst3"
DRAGONFLY_PATH = "/Library/Audio/Plug-Ins/VST3/DragonflyRoomReverb.vst3"

SAMPLE_RATE = 96000
BUFFER_SIZE = 512


def configure_tape(tape):
    """CHOW Tape: light saturation — adds even harmonics for warmth."""
    tape.set_parameter(0, 0.889)   # Input Gain ~+3 dB
    tape.set_parameter(1, 0.5)     # Output Gain 0 dB
    tape.set_parameter(2, 1.0)     # Dry/Wet 100%
    tape.set_parameter(16, 0.35)   # Tape Drive — medium
    tape.set_parameter(17, 0.4)    # Saturation — gentle
    tape.set_parameter(18, 0.5)    # Bias — neutral
    tape.set_parameter(8, 0.55)    # Tone Bass — slight warmth
    tape.set_parameter(9, 0.52)    # Tone Treble — slight air


def configure_eq(eq):
    """TDR Nova: HP at 35 Hz, de-mud at 250 Hz, presence at 3 kHz, air at 10 kHz."""
    eq.set_parameter(50, 0.087)    # HP Frequency ~35 Hz
    eq.set_parameter(2, 0.444)     # Band 1 Gain -2 dB
    eq.set_parameter(3, 0.339)     # Band 1 Q 0.4
    eq.set_parameter(4, 0.32)      # Band 1 Freq ~250 Hz
    eq.set_parameter(26, 0.562)    # Band 3 Gain +1.5 dB
    eq.set_parameter(27, 0.393)    # Band 3 Q 0.5
    eq.set_parameter(28, 0.68)     # Band 3 Freq ~3 kHz
    eq.set_parameter(38, 0.583)    # Band 4 Gain +2 dB
    eq.set_parameter(39, 0.438)    # Band 4 Q 0.6
    eq.set_parameter(40, 0.85)     # Band 4 Freq ~10 kHz


def configure_reverb(reverb):
    """Dragonfly Room: subtle short room ambience (88% dry, 8% early, 4% late)."""
    reverb.set_parameter(2, 0.88)  # Dry Level
    reverb.set_parameter(3, 0.08)  # Early Level
    reverb.set_parameter(5, 0.04)  # Late Level
    reverb.set_parameter(6, 0.167) # Size — small room
    reverb.set_parameter(9, 0.03)  # Decay — short (0.4s)


def main():
    parser = argparse.ArgumentParser(description="VST color chain processing for GM samples.")
    parser.add_argument("--input", default="General_MIDI_samples_raw")
    parser.add_argument("--output", default="General_MIDI_samples")
    args = parser.parse_args()

    src_dir = args.input
    out_dir = args.output
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(src_dir, "*.wav")))
    if not files:
        print(f"Error: no WAV files in {src_dir}")
        sys.exit(1)
    print(f"Found {len(files)} raw samples in {src_dir}")

    for name, path in [("CHOWTape", CHOW_PATH), ("TDR Nova", NOVA_PATH),
                        ("Dragonfly", DRAGONFLY_PATH)]:
        if not os.path.exists(path):
            print(f"Error: {name} not found at {path}")
            sys.exit(1)
    print("All VST plugins found. Building chain...")

    # Build engine + plugins ONCE
    engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)
    tape = engine.make_plugin_processor("tape", CHOW_PATH)
    eq = engine.make_plugin_processor("eq", NOVA_PATH)
    reverb = engine.make_plugin_processor("reverb", DRAGONFLY_PATH)
    configure_tape(tape)
    configure_eq(eq)
    configure_reverb(reverb)

    print(f"Processing {len(files)} samples...")
    for idx, f in enumerate(files):
        name = os.path.basename(f)
        if idx % 200 == 0 or idx == len(files) - 1:
            print(f"  [{idx+1}/{len(files)}] {name}")

        audio, sr = sf.read(f)
        if audio.ndim == 1:
            audio = np.column_stack((audio, audio))
        audio_2d = audio.T.astype(np.float32)

        # Build graph per-sample (playback needs the new audio data)
        pb = engine.make_playback_processor("pb", audio_2d)
        engine.load_graph([
            (pb, []),
            (tape, ["pb"]),
            (eq, ["tape"]),
            (reverb, ["eq"]),
        ])

        duration = len(audio) / SAMPLE_RATE
        engine.render(duration)
        out = engine.get_audio()

        # Peak-normalize to 0.95
        peak = float(np.max(np.abs(out)))
        if peak > 1e-6:
            out = out * (0.95 / peak)

        sf.write(os.path.join(out_dir, name), out.T, SAMPLE_RATE, subtype="PCM_24")

    print(f"\nDone! Processed {len(files)} samples → {out_dir}")


if __name__ == "__main__":
    main()
