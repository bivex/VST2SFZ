#!/usr/bin/env python3
"""
VST color chain processing for GM samples.

Processes raw samples through real VST plugins via DawDreamer:
  CHOWTapeModel (tape saturation) → TDR Nova (EQ) → Dragonfly Room (reverb)

This replaces the pedalboard-based process_samples.py with professional-grade
plugins for warmer, more authentic timbres. The chain adds:
  - Even/odd harmonics (tape saturation) for warmth and life
  - Surgical EQ (high-pass rumble cut, de-mud, air boost)
  - Short room ambience (pre-delay sense of space, not wash)

Usage:
  python process_samples_vst.py [--input General_MIDI_samples_raw]
                                [--output General_MIDI_samples]
"""
import os
import sys
import glob
import shutil
import argparse

import numpy as np
import soundfile as sf
import dawdreamer as daw

# Plugin paths (VST3 preferred, fall back to VST2)
CHOW_PATH = "/Library/Audio/Plug-Ins/VST3/CHOWTapeModel.vst3"
NOVA_PATH = "/Library/Audio/Plug-Ins/VST3/TDR Nova.vst3"
DRAGONFLY_PATH = "/Library/Audio/Plug-Ins/VST3/DragonflyRoomReverb.vst3"

SAMPLE_RATE = 96000
BUFFER_SIZE = 512


def configure_tape(tape):
    """CHOW Tape: light saturation for warmth.

    Settings: modest input gain boost (drives the tape model harder without
    clipping), medium tape drive + saturation, tone flat. The result adds
    even harmonics that make the sound "warm" rather than "sterile digital".
    """
    # Input Gain: index 0, range -30..+6 dB, normalized 0..1
    # +3 dB input to drive the tape slightly harder
    tape.set_parameter(0, 0.889)  # ~+3 dB
    # Output Gain: index 1, range -30..+30 dB — leave at 0 dB
    tape.set_parameter(1, 0.5)
    # Dry/Wet: index 2 — 100% wet
    tape.set_parameter(2, 1.0)
    # Tape Drive: index 16, range 0..1 — medium drive
    tape.set_parameter(16, 0.35)
    # Tape Saturation: index 17, range 0..1 — gentle saturation
    tape.set_parameter(17, 0.4)
    # Tape Bias: index 18, range 0..1 — neutral
    tape.set_parameter(18, 0.5)
    # Tone Bass: index 8 — slight warmth
    tape.set_parameter(8, 0.55)
    # Tone Treble: index 9 — slight air
    tape.set_parameter(9, 0.52)


def configure_eq(eq):
    """TDR Nova: surgical EQ.

    - High-pass at ~35 Hz (remove sub-rumble)
    - Slight low-shelf cut at 250 Hz (de-mud)
    - Presence bump at 3 kHz
    - Air shelf at 10 kHz
    """
    # HP Frequency: index 50 — set to ~35 Hz (range 10..300 Hz, normalized)
    # 0.049 default = 15 Hz; we want 35 Hz → ~0.087
    eq.set_parameter(50, 0.087)
    # HP active (implied by frequency > minimum)

    # Band 1: low shelf at 250 Hz, -2 dB
    eq.set_parameter(2, 0.444)   # Band 1 Gain: -2 dB (range -24..+24, 0.5=0)
    eq.set_parameter(3, 0.339)   # Q: 0.4 (wide shelf)
    eq.set_parameter(4, 0.32)    # Frequency: ~250 Hz

    # Band 3: presence bell at 3 kHz, +1.5 dB
    eq.set_parameter(26, 0.562)  # Band 3 Gain: +1.5 dB
    eq.set_parameter(27, 0.393)  # Q: 0.5
    eq.set_parameter(28, 0.68)   # Frequency: ~3000 Hz

    # Band 4: high shelf at 10 kHz, +2 dB
    eq.set_parameter(38, 0.583)  # Band 4 Gain: +2 dB
    eq.set_parameter(39, 0.438)  # Q: 0.6
    eq.set_parameter(40, 0.85)   # Frequency: ~10000 Hz


def configure_reverb(reverb):
    """Dragonfly Room: very subtle short room ambience.

    Not a wash — just enough early reflections to give the sample a sense of
    being in a physical space, which prevents the "vacuum" dryness of raw
    synth output.
    """
    # Dry Level: index 2 — 88% dry (keep the sample prominent)
    reverb.set_parameter(2, 0.88)
    # Early Level: index 3 — 8% early reflections
    reverb.set_parameter(3, 0.08)
    # Late Level: index 5 — 4% late tail (very subtle)
    reverb.set_parameter(5, 0.04)
    # Size: index 6 — small room (12 m default is fine)
    reverb.set_parameter(6, 0.167)
    # Decay: index 9 — short (0.4s default is fine)
    reverb.set_parameter(9, 0.03)


def main():
    parser = argparse.ArgumentParser(description="VST color chain processing for GM samples.")
    parser.add_argument("--input", default="General_MIDI_samples_raw",
                        help="Source directory with raw samples")
    parser.add_argument("--output", default="General_MIDI_samples",
                        help="Output directory for processed samples")
    parser.add_argument("--max-workers", type=int, default=1,
                        help="(reserved) parallel workers")
    args = parser.parse_args()

    src_dir = args.input
    out_dir = args.output
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(src_dir, "*.wav")))
    if not files:
        print(f"Error: no WAV files in {src_dir}")
        sys.exit(1)
    print(f"Found {len(files)} raw samples in {src_dir}")

    # Verify plugins exist
    for name, path in [("CHOWTape", CHOW_PATH), ("TDR Nova", NOVA_PATH),
                        ("Dragonfly", DRAGONFLY_PATH)]:
        if not os.path.exists(path):
            print(f"Error: {name} not found at {path}")
            sys.exit(1)
    print("All VST plugins found.")

    # Build the engine + plugin graph ONCE (reuse across all samples)
    engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)

    tape = engine.make_plugin_processor("tape", CHOW_PATH)
    eq = engine.make_plugin_processor("eq", NOVA_PATH)
    reverb = engine.make_plugin_processor("reverb", DRAGONFLY_PATH)

    configure_tape(tape)
    configure_eq(eq)
    configure_reverb(reverb)

    # Graph: tape → eq → reverb
    # We load the input sample into the tape processor via a "file" input node.
    # DawDreamer doesn't have a direct file-input node, so we use the
    # tape processor as a passthrough by rendering through the chain.
    # Instead, we process via the graph: [tape] ← input, [eq] ← tape, [reverb] ← eq
    # But DawDreamer plugins expect MIDI/automation, not raw audio input.
    # Workaround: use a "wave" processor (additive) as the source, or process
    # by feeding audio directly.

    # DawDreamer approach: create a graph where a "wave" processor holds the
    # sample data, then chain effects.
    print("Processing samples...")
    for idx, f in enumerate(files):
        name = os.path.basename(f)
        if idx % 200 == 0 or idx == len(files) - 1:
            print(f"  [{idx+1}/{len(files)}] {name}")

        audio, sr = sf.read(f)
        if audio.ndim == 1:
            audio = np.column_stack((audio, audio))
        if sr != SAMPLE_RATE:
            # Resample (shouldn't happen, samples are 96k)
            import librosa
            audio = librosa.resample(audio.T, orig_sr=sr, target_sr=SAMPLE_RATE).T

        # DawDreamer: use engine.load_graph with the sample as source.
        # The cleanest way: add the sample as an additive source.
        # We use a temporary graph per file.
        additive = engine.make_additive_processor("src")
        additive.add_sound(audio.T)  # (channels, samples)
        engine.load_graph([
            (additive, []),
            (tape, ["src"]),
            (eq, ["tape"]),
            (reverb, ["eq"]),
        ])
        engine.render(len(audio) / SAMPLE_RATE)
        out = engine.get_audio()

        # Peak-normalize to 0.95
        peak = np.max(np.abs(out))
        if peak > 1e-6:
            out = out * (0.95 / peak)

        sf.write(os.path.join(out_dir, name), out.T, SAMPLE_RATE, subtype="PCM_24")

    print(f"\nDone! Processed {len(files)} samples → {out_dir}")


if __name__ == "__main__":
    main()
