#!/usr/bin/env python3
"""
Headless Dexed VST3 renderer via DawDreamer.

Dexed is a DX7 emulator. It stores presets as MIDI Program Change slots
(32 per bank), NOT as .vstpreset files. This script loads any preset by
its slot number via program_change, renders notes, and saves WAVs.

It also captures the full plugin patch (all 2238 parameters) to JSON so
the preset can be reloaded instantly without re-sending program_change.

Usage:
    # Render one note from preset 0 (E.PIANO 1)
    python render_dexed.py --program 0 --note 60 --out /tmp/out.wav

    # Capture a patch to JSON (all 2238 params)
    python render_dexed.py --program 0 --save-patch /tmp/dexed_epiano1.json

    # Render from a saved patch (no program_change needed)
    python render_dexed.py --load-patch /tmp/dexed_epiano1.json --note 60

    # List all 32 factory presets (audibility check)
    python render_dexed.py --list

Why NOT get_patch()[:155]:
    Dexed has 2238 VST parameters, not 155. The "155" is the DX7 SYX
    voice-parameter count (6 operators × 21 params + globals), but the
    plugin exposes FAR more (master, FX, MIDI, per-operator GUI state).
    Truncating to 155 loses most of the state. Capture all 2238.

    Also, get_patch() returns a list of (index, value) TUPLES, not plain
    floats — so [float(v) for v in patch] crashes. We unpack the tuples.

Requirements:
    /opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python3
    (has dawdreamer, mido, soundfile, numpy)
"""

import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf
import mido
import dawdreamer as daw

DEXED_PATH = "/Library/Audio/Plug-Ins/VST3/Dexed.vst3"
SAMPLE_RATE = 44100
BUFFER_SIZE = 512


def make_engine():
    """Create a DawDreamer engine with Dexed loaded. Suppresses iLok/socket
    stderr noise the same way sample_gm_pack.py does."""
    devnull = open(os.devnull, "w")
    old_stderr = os.dup(2)
    os.dup2(devnull.fileno(), 2)
    try:
        engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)
        dexed = engine.make_plugin_processor("dexed", DEXED_PATH)
        engine.load_graph([(dexed, [])])
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()
    return engine, dexed


def load_program(dexed, engine, program):
    """Switch Dexed to a factory preset slot via MIDI program_change.

    Dexed responds to program_change 0..31 for the current bank. We send
    the message, render a short settle buffer (0.5s) so the preset fully
    loads, then clear the MIDI queue. No REAPER / GUI needed.
    """
    dexed.clear_midi()
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.Message("program_change", program=program, time=0))
    tmp = f"/tmp/dexed_pc_{os.getpid()}.mid"
    mid.save(tmp)
    dexed.load_midi(tmp, all_events=True)
    engine.render(0.5)  # settle: let the preset take effect
    dexed.clear_midi()
    os.remove(tmp)


def load_syx(dexed, syx_path):
    """Load a DX7 .syx file into Dexed via the plugin's load_state.

    Supports both formats:
      - 163 bytes: single voice → lands in slot 0
      - 4104 bytes: 32-voice bank → slots 0..31 (pick with --program)

    load_state takes the raw SYX path directly; Dexed parses the SysEx
    payload (0xF0...0xF7) internally.
    """
    size = os.path.getsize(syx_path)
    dexed.load_state(syx_path)
    if size <= 200:
        kind = "single voice"
    elif size >= 4000:
        kind = f"32-voice bank (use --program 0..31 to pick)"
    else:
        kind = "unknown format"
    return kind, size


def save_patch(dexed, path):
    """Capture the full plugin patch (all 2238 params) to JSON.

    get_patch() returns [(index, value), ...] tuples — we unpack to a flat
    {index: value} dict so reloading is unambiguous and JSON-friendly.
    """
    patch = dexed.get_patch()
    data = {str(i): float(v) for i, v in patch}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return len(data)


def load_patch(dexed, path):
    """Load a previously captured patch via set_patch.

    Rebuilds the [(index, value), ...] tuple list that set_patch expects
    from the JSON {index: value} dict saved by save_patch.
    """
    with open(path) as f:
        data = json.load(f)
    patch = [(int(k), float(v)) for k, v in data.items()]
    dexed.set_patch(patch)


def render_note(dexed, engine, note, velocity, duration, release=0.5):
    """Render a single note and return stereo audio (samples, 2)."""
    dexed.clear_midi()
    dexed.add_midi_note(note, velocity, 0.0, duration)
    engine.render(duration + release)
    audio = engine.get_audio()
    dexed.clear_midi()
    # DawDreamer returns (channels, samples) or (samples,) — normalise to
    # (samples, 2) which is what soundfile.write expects.
    if audio.ndim == 1:
        audio = np.column_stack((audio, audio))
    elif audio.shape[0] == 2:
        audio = audio.T
    return audio


def render_midi(dexed, engine, midi_path, tail_seconds=3.0):
    """Render an entire MIDI file through Dexed.

    Dexed is monophonic-timbral: it plays ONE preset across all MIDI channels,
    ignoring program_change (we set the preset via --program / --load-patch
    before calling this). All note_on/note_off events from every channel are
    fed to the engine as a single MIDI stream.

    Returns stereo audio (samples, 2).
    """
    import mido
    mid = mido.MidiFile(midi_path)
    total_sec = mid.length or 30.0
    total_samples = int((total_sec + tail_seconds) * SAMPLE_RATE)

    # Build a single MIDI file with just note_on/note_off/control_change
    # (strip program_change so Dexed keeps the preset we loaded).
    merged = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat or 480)
    trk = mido.MidiTrack()
    merged.tracks.append(trk)
    for msg in mido.merge_tracks(mid.tracks):
        if msg.type in ("note_on", "note_off", "control_change",
                        "pitchwheel", "polytouch"):
            trk.append(msg.copy())
    tmp = f"/tmp/dexed_midi_{os.getpid()}.mid"
    merged.save(tmp)

    dexed.clear_midi()
    dexed.load_midi(tmp, all_events=True)
    os.remove(tmp)
    # Render enough time for the longest held note + tail
    engine.render(total_sec + tail_seconds)
    audio = engine.get_audio()
    dexed.clear_midi()

    if audio.ndim == 1:
        audio = np.column_stack((audio, audio))
    elif audio.shape[0] == 2:
        audio = audio.T
    return audio[:total_samples]


def main():
    parser = argparse.ArgumentParser(description="Headless Dexed VST3 renderer.")
    parser.add_argument("--program", type=int, default=None,
                        help="Factory preset slot 0..31 (loads via program_change)")
    parser.add_argument("--syx", metavar="FILE",
                        help="Load a DX7 .syx patch/bank. 163-byte = single voice, "
                             "4104-byte = 32-voice bank (use --program to pick a slot)")
    parser.add_argument("--save-patch", metavar="JSON",
                        help="Capture the current patch to a JSON file")
    parser.add_argument("--load-patch", metavar="JSON",
                        help="Load a previously captured patch JSON")
    parser.add_argument("--note", type=int, default=60,
                        help="MIDI note to render (default 60 = C4)")
    parser.add_argument("--velocity", type=int, default=100)
    parser.add_argument("--duration", type=float, default=1.5,
                        help="Note hold in seconds")
    parser.add_argument("--midi", metavar="FILE",
                        help="Render an entire MIDI file (all channels play the loaded Dexed preset)")
    parser.add_argument("--out", default=None,
                        help="Output WAV path (omit for no render)")
    parser.add_argument("--list", action="store_true",
                        help="List all 32 presets with audibility check")
    args = parser.parse_args()

    if not os.path.exists(DEXED_PATH):
        print(f"Error: Dexed not found at {DEXED_PATH}")
        sys.exit(1)

    engine, dexed = make_engine()

    # --- List mode: probe all 32 presets ---
    if args.list:
        print(f"Dexed factory presets (bank 0, slots 0..31):")
        print(f"{'slot':>4} {'peak':>8} {'status'}")
        for prog in range(32):
            load_program(dexed, engine, prog)
            audio = render_note(dexed, engine, 60, 100, 0.5, 0.3)
            peak = float(np.max(np.abs(audio))) if audio.size else 0
            status = "AUDIBLE" if peak > 0.01 else "silent/very quiet"
            print(f"{prog:>4} {peak:>8.4f} {status}")
        return

    # --- Load a preset (program_change, SYX, or patch JSON) ---
    if args.syx:
        if not os.path.exists(args.syx):
            print(f"Error: SYX not found: {args.syx}")
            sys.exit(1)
        kind, size = load_syx(dexed, args.syx)
        print(f"Loaded SYX: {args.syx} ({size} bytes, {kind})")
        # For 32-voice banks, select a slot via --program (default 0)
        if size >= 4000 and args.program is not None:
            load_program(dexed, engine, args.program)
            print(f"  → selected voice slot {args.program}")
        elif size >= 4000:
            load_program(dexed, engine, 0)
            print(f"  → defaulting to voice slot 0")
    elif args.program is not None:
        load_program(dexed, engine, args.program)
        print(f"Loaded Dexed program {args.program}")
    elif args.load_patch:
        load_patch(dexed, args.load_patch)
        print(f"Loaded patch from {args.load_patch}")

    # --- Capture patch ---
    if args.save_patch:
        n = save_patch(dexed, args.save_patch)
        print(f"Saved {n} parameters to {args.save_patch}")

    # --- Render note ---
    if args.midi:
        if not os.path.exists(args.midi):
            print(f"Error: MIDI not found: {args.midi}")
            sys.exit(1)
        if not args.out:
            print("Error: --out required with --midi")
            sys.exit(1)
        import mido
        mid = mido.MidiFile(args.midi)
        print(f"Rendering MIDI: {args.midi} "
              f"({mid.length or 0:.1f}s, {len(mid.tracks)} tracks)")
        audio = render_midi(dexed, engine, args.midi)
        peak = float(np.max(np.abs(audio)))
        if peak > 1e-6:
            audio = audio * (0.95 / peak)
        sf.write(args.out, audio, SAMPLE_RATE, subtype="PCM_24")
        print(f"✓ Rendered MIDI → {args.out} ({audio.shape[0]} samples)")
    elif args.out:
        audio = render_note(dexed, engine, args.note, args.velocity,
                            args.duration)
        # Peak-normalise to 0.95 to use the 24-bit range fully
        peak = float(np.max(np.abs(audio)))
        if peak > 1e-6:
            audio = audio * (0.95 / peak)
        sf.write(args.out, audio, SAMPLE_RATE, subtype="PCM_24")
        print(f"Rendered note {args.note} (vel {args.velocity}) → {args.out} "
              f"({audio.shape[0]} samples, peak {peak:.4f})")


if __name__ == "__main__":
    main()
