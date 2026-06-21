#!/usr/bin/env python3
"""
Multi-timbral GM MIDI renderer.

Renders a General MIDI file through a multi-timbral SFZ bank (e.g.
General_MIDI.sfz) where each <group> selects an instrument via `prg_num`.

Differences from render_sfz_midi.py:
  * Honors `prg_num` on <group> blocks to build a program -> regions map.
  * Tracks MIDI `program_change` per channel so different channels play
    different instruments.
  * Channel 10 (index 9) is treated as the GM drum channel: drum notes
    are looked up by absolute key (using prg_num=0 as the fallback bank),
    matching the standard GM convention.
"""
import os
import sys
import re
import math
import argparse
import mido
import numpy as np
import soundfile as sf


def parse_sfz(sfz_path):
    """
    Parse an SFZ file into:
      default_path (str)
      program_regions (dict: prg_num -> list of region opcode dicts)
    Each <group> with a `prg_num` opens a context for the <region> blocks
    that follow it, until the next <group>.
    """
    sfz_dir = os.path.dirname(os.path.abspath(sfz_path))
    with open(sfz_path, "r") as f:
        content = f.read()
    # Strip comments
    content_clean = re.sub(r"//.*", "", content)
    # Split into header blocks, preserving order
    blocks = re.split(r"<", content_clean)

    default_path = ""
    program_regions = {}
    current_prg = 0
    current_group_ops = {}

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        match = re.match(r"^(\w+)\s*>\s*(.*)$", block, re.DOTALL)
        if not match:
            continue
        header_name = match.group(1).lower()
        body = match.group(2)
        opcodes = {}
        pattern = r"(\w+)\s*=\s*([^\s=]+|\"[^\"]*\")"
        for key, val in re.findall(pattern, body):
            opcodes[key.lower()] = val.strip('"')

        if header_name == "control":
            if "default_path" in opcodes:
                default_path = os.path.join(sfz_dir, opcodes["default_path"])
        elif header_name == "group":
            # New group: update current program context
            current_group_ops = opcodes
            if "prg_num" in opcodes:
                current_prg = int(opcodes["prg_num"])
        elif header_name == "region":
            # Region inherits group opcodes, then region opcodes override
            merged = dict(current_group_ops)
            merged.update(opcodes)
            program_regions.setdefault(current_prg, []).append(merged)

    return default_path, program_regions


def parse_midi_file(midi_path):
    """
    Parse a MIDI file into a list of note events, each tagged with channel
    and the program active on that channel at note-on time.
    Returns: notes (list of dicts), duration_sec (float), programs_per_channel
    """
    print(f"Parsing MIDI file: {midi_path}")
    mid = mido.MidiFile(midi_path)
    notes = []
    active_notes = {}  # (channel, note) -> (start_time, velocity)
    channel_programs = {}  # channel -> current program (default 0)
    current_time_sec = 0.0

    for msg in mid:
        current_time_sec += msg.time
        if msg.type == 'program_change':
            channel_programs[msg.channel] = msg.program
        elif msg.type == 'note_on' and msg.velocity > 0:
            ch = msg.channel
            prog = channel_programs.get(ch, 0)
            key = (ch, msg.note)
            if key in active_notes:
                start_time, velocity, prev_prog = active_notes.pop(key)
                notes.append({
                    "note": msg.note,
                    "velocity": velocity,
                    "start_time": start_time,
                    "duration": current_time_sec - start_time,
                    "channel": ch,
                    "program": prev_prog,
                })
            active_notes[key] = (current_time_sec, msg.velocity, prog)
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            ch = msg.channel
            key = (ch, msg.note)
            if key in active_notes:
                start_time, velocity, prog = active_notes.pop(key)
                notes.append({
                    "note": msg.note,
                    "velocity": velocity,
                    "start_time": start_time,
                    "duration": current_time_sec - start_time,
                    "channel": ch,
                    "program": prog,
                })

    # Close still-active notes at end of file
    for (ch, note), (start_time, velocity, prog) in active_notes.items():
        notes.append({
            "note": note,
            "velocity": velocity,
            "start_time": start_time,
            "duration": max(0.1, current_time_sec - start_time),
            "channel": ch,
            "program": prog,
        })

    return notes, current_time_sec, mid.length


def render_note_vectorized(sample_data, ratio, velocity, duration_samples, release_samples=44100):
    num_src_samples, num_channels = sample_data.shape
    max_resampled_samples = int(math.ceil(num_src_samples / ratio))
    total_samples = min(duration_samples + release_samples, max_resampled_samples)
    if total_samples <= 0:
        return np.zeros((0, num_channels), dtype=np.float32)

    t = np.arange(total_samples, dtype=np.float32)
    src_ptrs = t * ratio
    idx_low = np.floor(src_ptrs).astype(np.int32)
    idx_high = idx_low + 1

    valid_mask = idx_low < num_src_samples
    note_buffer = np.zeros((total_samples, num_channels), dtype=np.float32)

    if np.any(valid_mask):
        frac = src_ptrs[valid_mask] - idx_low[valid_mask]
        frac = frac[:, np.newaxis]
        low_idx = idx_low[valid_mask]
        high_idx = np.clip(idx_high[valid_mask], 0, num_src_samples - 1)
        val_low = sample_data[low_idx]
        val_high = sample_data[high_idx]
        val = (1.0 - frac) * val_low + frac * val_high

        if release_samples > 0 and duration_samples < total_samples:
            release_ramp = np.ones(total_samples, dtype=np.float32)
            off_indices = np.arange(total_samples - duration_samples, dtype=np.float32)
            release_ramp[duration_samples:] = np.maximum(0.0, 1.0 - off_indices / release_samples)
            val = val * release_ramp[valid_mask][:, np.newaxis]

        val = val * (velocity / 127.0)
        note_buffer[valid_mask] = val

    return note_buffer


def find_matching_region(regions, note, velocity):
    for r in regions:
        lokey = int(r.get("lokey", 0))
        hikey = int(r.get("hikey", 127))
        lovel = int(r.get("lovel", 1))
        hivel = int(r.get("hivel", 127))
        if lokey <= note <= hikey and lovel <= velocity <= hivel:
            return r
    return None


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))

    default_midi = ""
    default_sfz = os.path.join(project_root, "General_MIDI.sfz")
    default_output = os.path.join(project_root, "General_MIDI_Render.wav")

    parser = argparse.ArgumentParser(
        description="Render a multi-timbral GM MIDI file to WAV using a prg_num-based SFZ bank."
    )
    parser.add_argument("--midi", type=str, default=default_midi, required=True, help="Path to input MIDI file")
    parser.add_argument("--sfz", type=str, default=default_sfz, help="Path to SFZ bank file")
    parser.add_argument("--output", type=str, default=default_output, help="Path to output WAV file")
    parser.add_argument("--sr", type=int, default=44100, help="Rendering sample rate (Hz)")
    parser.add_argument("--release", type=float, default=0.5, help="Envelope release time (seconds)")
    parser.add_argument("--no-effects", action="store_true", help="Skip reverb/delay post-processing")
    parser.add_argument("--no-normalize", action="store_true", help="Skip final peak normalization")
    args = parser.parse_args()

    if not os.path.exists(args.midi):
        print(f"Error: MIDI file not found: {args.midi}")
        sys.exit(1)
    if not os.path.exists(args.sfz):
        print(f"Error: SFZ file not found: {args.sfz}")
        sys.exit(1)

    default_path, program_regions = parse_sfz(args.sfz)
    print(f"SFZ bank: {len(program_regions)} programs mapped (prg 0..{max(program_regions) if program_regions else -1}).")

    midi_notes, midi_duration, _ = parse_midi_file(args.midi)
    print(f"Parsed {len(midi_notes)} notes from MIDI ({midi_duration:.1f}s).")

    # Report program usage
    used_programs = sorted(set(n["program"] for n in midi_notes))
    print(f"Programs used: {used_programs}")

    # Warn about missing programs in the bank
    missing = [p for p in used_programs if p not in program_regions]
    if missing:
        print(f"Warning: programs {missing} referenced in MIDI but not in SFZ bank; those notes will be skipped.")

    sr = args.sr
    release_samples = int(args.release * sr)

    max_time = 0.0
    for n in midi_notes:
        max_time = max(max_time, n["start_time"] + n["duration"])
    total_duration_sec = max_time + args.release
    total_samples = int(math.ceil(total_duration_sec * sr))
    print(f"Total audio duration: {total_duration_sec:.2f}s ({total_samples} samples)")

    output_audio = np.zeros((total_samples, 2), dtype=np.float32)
    sample_cache = {}

    print("Synthesizing notes...")
    percent_mark = max(1, len(midi_notes) // 10)

    for idx, n in enumerate(midi_notes):
        if idx % percent_mark == 0 or idx == len(midi_notes) - 1:
            progress = (idx + 1) / len(midi_notes) * 100
            print(f"Synthesis progress: {progress:.0f}% ({idx + 1}/{len(midi_notes)} notes)")

        note = n["note"]
        velocity = n["velocity"]
        start_time = n["start_time"]
        duration = n["duration"]
        program = n["program"]
        channel = n["channel"]

        # Channel 10 (index 9) is the GM drum channel, but only when no
        # explicit melodic program_change is set. Heuristic:
        #   - program 0 on ch9  => standard GM drum kit (key-percussion mapping)
        #   - program != 0 on ch9 => melodic instrument placed on the drum
        #     channel (non-standard but valid; e.g. some files put a lead
        #     voice there). Render it normally via its own program.
        drum_mode = False
        if channel == 9 and program == 0:
            drum_mode = True
            # Our SFZ bank has no dedicated percussion kit; fall back to
            # program 0 (Acoustic Grand Piano) regions as the nearest stand-in.
            regions = program_regions.get(0, [])
        else:
            regions = program_regions.get(program, [])
        if not regions:
            continue

        region = find_matching_region(regions, note, velocity)
        if not region:
            continue

        sample_name = region["sample"]
        sample_file_path = os.path.join(default_path, sample_name)

        if sample_file_path not in sample_cache:
            if not os.path.exists(sample_file_path):
                print(f"Warning: Sample file not found: {sample_file_path}")
                continue
            data, sample_sr = sf.read(sample_file_path)
            if data.ndim == 1:
                data = np.column_stack((data, data))
            sample_cache[sample_file_path] = (data, sample_sr)

        sample_data, sample_sr = sample_cache[sample_file_path]

        keycenter = int(region.get("pitch_keycenter", 60))
        # Drum kit: play back at native pitch (no key-based transpose), since
        # each key is a distinct percussion sound rather than a pitched note.
        if drum_mode:
            ratio = 1.0
        else:
            ratio = 2.0 ** ((note - keycenter) / 12.0)
        if sample_sr != sr:
            ratio *= (sample_sr / sr)

        duration_samples = int(duration * sr)
        note_audio = render_note_vectorized(
            sample_data,
            ratio,
            velocity,
            duration_samples,
            release_samples,
        )

        start_sample = int(start_time * sr)
        end_sample = min(total_samples, start_sample + note_audio.shape[0])
        mix_len = end_sample - start_sample
        if mix_len > 0:
            output_audio[start_sample:end_sample] += note_audio[:mix_len]

    # Post-processing (optional)
    if not args.no_effects:
        print("Applying reverb and delay effects...")
        try:
            from pedalboard import Pedalboard, Reverb, Delay
            board = Pedalboard([
                Reverb(room_size=0.75, wet_level=0.30, dry_level=0.70),
                Delay(delay_seconds=0.370, feedback=0.18, mix=0.10)
            ])
            processed = board(output_audio.T, sr)
            output_data = processed.T
        except Exception as e:
            print(f"Warning: pedalboard failed or not available, saving dry output. ({e})")
            output_data = output_audio
    else:
        output_data = output_audio

    # Normalize (optional)
    max_val = np.max(np.abs(output_data))
    print(f"Max processed amplitude: {max_val:.4f}")
    if max_val > 0.0 and not args.no_normalize:
        target_peak = 0.95
        output_data = output_data * (target_peak / max_val)
        print(f"Audio normalized to {target_peak:.2f} peak level.")

    print(f"Saving WAV output to: {args.output}")
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    sf.write(args.output, output_data, sr, subtype='PCM_24')
    print("Render complete! Enjoy your audio.")


if __name__ == "__main__":
    main()
