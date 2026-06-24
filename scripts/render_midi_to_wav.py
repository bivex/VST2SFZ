#!/usr/bin/env python3
"""
Render a MIDI file to WAV using the GM SFZ pack via sfizz (pysfizz).

sfizz is multi-timbral: each MIDI channel plays its own GM program, so a
full arrangement (melody + bass + accompaniment + drums) renders correctly
in one pass — unlike Dexed which is monophonic (one timbre for everything).

Uses the Birka venv which has the compiled _sfizz extension.

Usage:
    python render_midi_to_wav.py input.mid output.wav
    python render_midi_to_wav.py input.mid output.wav --sfz path/to.sfz
"""

import argparse
import os
import sys

import mido
import numpy as np
import soundfile as sf

# pysfizz lives in the Birka venv
sys.path.insert(0, "/Volumes/External/Code/Birka/.venv/lib/python3.12/site-packages")
from pysfizz import _sfizz

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SFZ = os.path.join(_ROOT, "sfz", "General_MIDI_sfizz_processed.sfz")
SAMPLE_RATE = 44100
BLOCK_FRAMES = 1024


def render(midi_path, sfz_path, out_path, sample_rate=SAMPLE_RATE):
    print(f"Loading SFZ: {sfz_path}")
    synth = _sfizz.Synth(sample_rate, BLOCK_FRAMES)
    ok = synth.load_sfz_file(sfz_path)
    if not ok:
        print("Error: failed to load SFZ")
        sys.exit(1)
    print(f"  regions: {synth.get_num_regions()}")
    synth.set_sample_quality(2)  # high quality
    synth.enable_freewheeling()

    # Parse MIDI
    mid = mido.MidiFile(midi_path)
    ticks_per_beat = mid.ticks_per_beat or 480
    tempo = mido.bpm2tempo(120)
    total_sec = mid.length or 30.0
    total_samples = int((total_sec + 3.0) * sample_rate)  # +3s release tail
    print(f"MIDI: {os.path.basename(midi_path)} ({total_sec:.1f}s)")

    # Convert all messages to (sample_offset, type, data)
    events = []
    current_tick = 0
    for msg in mido.merge_tracks(mid.tracks):
        current_tick += msg.time
        if msg.type == "set_tempo":
            tempo = msg.tempo
            continue
        if msg.is_meta:
            continue
        sec = mido.tick2second(current_tick, ticks_per_beat, tempo)
        sample_offset = int(sec * sample_rate)
        events.append((sample_offset, msg))
    events.sort(key=lambda x: x[0])
    print(f"  events: {len(events)}")

    # Render in blocks, dispatching MIDI events via the Synth's direct API
    # sfizz pysfizz exposes: note_on(delay, key, vel), note_off(delay, key),
    # cc(delay, cc, val), pitch_wheel(delay, value), program_change(delay, pgm)
    output = np.zeros((2, total_samples), dtype=np.float32)
    event_idx = 0
    block_start = 0
    progress_step = max(1, sample_rate * 5)  # log every 5s

    while block_start < total_samples:
        block_end = min(block_start + BLOCK_FRAMES, total_samples)
        frames = block_end - block_start

        # Dispatch events whose sample offset falls in this block.
        # delay is relative to the start of the block.
        while event_idx < len(events) and events[event_idx][0] < block_end:
            offset, msg = events[event_idx]
            delay = max(0, min(BLOCK_FRAMES - 1, offset - block_start))
            t = msg.type
            if t == "note_on" and msg.velocity > 0:
                synth.note_on(delay, msg.note, msg.velocity)
            elif t == "note_off" or (t == "note_on" and msg.velocity == 0):
                synth.note_off(delay, msg.note, 0)
            elif t == "control_change":
                synth.cc(delay, msg.control, msg.value)
            elif t == "program_change":
                synth.program_change(delay, msg.program)
            elif t == "pitchwheel":
                synth.pitch_wheel(delay, msg.pitch)
            event_idx += 1

        # Render block — sfizz returns a tuple (left, right), each
        # BLOCK_FRAMES float32 samples. We copy into the output buffers.
        left, right = synth.render_block()

        actual = min(frames, BLOCK_FRAMES)
        output[0, block_start:block_end] = left[:actual]
        output[1, block_start:block_end] = right[:actual]
        block_start = block_end

        if block_start % progress_step < BLOCK_FRAMES:
            print(f"  {block_start/sample_rate:.0f}s / {total_samples/sample_rate:.0f}s")

    # Interleave (samples, 2) and normalize
    stereo = output.T[:total_samples]
    peak = float(np.max(np.abs(stereo)))
    if peak > 1e-6:
        stereo = stereo * (0.95 / peak)
    print(f"  peak: {peak:.4f} → normalized to 0.95")

    sf.write(out_path, stereo, sample_rate, subtype="PCM_24")
    print(f"✓ Wrote {out_path} ({stereo.shape[0]/sample_rate:.1f}s)")


def main():
    parser = argparse.ArgumentParser(description="Render MIDI to WAV via sfizz GM pack.")
    parser.add_argument("midi", help="Input MIDI file")
    parser.add_argument("output", help="Output WAV file")
    parser.add_argument("--sfz", default=DEFAULT_SFZ,
                        help=f"SFZ file (default: GM processed pack)")
    args = parser.parse_args()

    if not os.path.exists(args.midi):
        print(f"Error: MIDI not found: {args.midi}"); sys.exit(1)
    if not os.path.exists(args.sfz):
        print(f"Error: SFZ not found: {args.sfz}"); sys.exit(1)

    render(args.midi, args.sfz, args.output)


if __name__ == "__main__":
    main()
