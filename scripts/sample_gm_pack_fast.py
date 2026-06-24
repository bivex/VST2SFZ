#!/usr/bin/env python3
"""
Fast parallel version of sample_gm_pack.py.

The original renders all 128 GM programs sequentially in a single
DawDreamer engine instance, switching presets via MIDI program_change.
Each program takes ~1s for the preset-settle render + ~16 note renders +
pitch detection — the full pack is roughly 128 × ~10s ≈ 20 minutes.

This version parallelises across PROGRAMS: each worker handles a slice of
programs in its own DawDreamer engine with its own Surge XT instance.
Programs are independent (distinct presets, no shared state inside Surge),
so they parallelise cleanly. Worker output is gathered back to the parent
process which writes the master SFZ files in program order.

Output is functionally equivalent to the sequential script:
  - Identical sample WAV files (rendered with the same preset + notes).
  - Identical SFZ region lines (same pitch_keycenter / lokey / hikey /
    vel ranges — clamp logic and pitch detection are reused verbatim).
  - Identical preset-mapping, backup/restore of ~/Documents/Surge user
    patches, and pitch detection uses the same detect_pitch_midi function.

Because the same Surge XT binary renders the same input with the same
parameters, audio output is bit-equivalent to the sequential version on
deterministic presets; Surge's oscillator init is deterministic per
program-change so there is no inter-worker nondeterminism from the synth
itself (unlike the post-processing VST chain, which has noisy plugins).

Usage:
    python sample_gm_pack_fast.py                 # default 8 workers
    python sample_gm_pack_fast.py --workers 4     # explicit
    python sample_gm_pack_fast.py --programs 0 1 2 3   # render subset
"""

import argparse
import os
import shutil
import sys
import time
import traceback
from multiprocessing import Pool, cpu_count

import numpy as np
import soundfile as sf
import mido

# Reuse the single source of truth from the sequential script: the
# preset mapping table, GM_NAMES, note helpers, pitch detector, and all
# the rendering constants (notes_to_sample, velocities, durations, sr).
import sample_gm_pack as sp


# Surge XT VST path. Not exposed at module level in sample_gm_pack.py
# (it's a local variable in main()), so define it here and let main()
# pass it explicitly to render tasks via the closure.
VST_PATH = "/Library/Audio/Plug-Ins/VST3/Surge XT.vst3"
SAMPLE_RATE = 96000


# Per-worker state. DawDreamer engines cannot be pickled across processes,
# so each worker builds its own engine+Surge once and reuses it for every
# program in its slice.
_WORKER = {}


def _init_worker():
    """Pool initializer: build a private engine + Surge XT per worker."""
    import dawdreamer as daw
    devnull = open(os.devnull, "w")
    old_stderr = os.dup(2)
    os.dup2(devnull.fileno(), 2)
    try:
        engine = daw.RenderEngine(SAMPLE_RATE, 512)
        synth = engine.make_plugin_processor("synth", VST_PATH)
        engine.load_graph([(synth, [])])
        _WORKER["engine"] = engine
        _WORKER["synth"] = synth
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()


def render_program(task):
    """Render one GM program in this worker's engine.

    Returns a dict with:
      prog, inst_name, preset_basename,
      transpose (str|None — printed in parent),
      samples: list of (filename, audio ndarray) — caller writes WAVs,
      regions: list of dicts with all SFZ line fields,
      log: list of human-readable log strings (clamp / borrow / transpose).
    """
    prog, preset_path, midi_programs_dir, samples_dir = task
    inst_name = sp.GM_NAMES[prog]

    # Each worker reads the preset the same way the sequential script does:
    # copy the factory .fxp into the user MIDI Programs dir under the slot
    # number, then switch via program_change. The user-patch dir is shared
    # across workers, but each writes a UNIQUE slot number (prog 0..127),
    # so there are no collisions.
    dest_preset = os.path.join(midi_programs_dir, f"{prog:03d}_{inst_name}.fxp")
    shutil.copy2(preset_path, dest_preset)

    engine = _WORKER["engine"]
    synth = _WORKER["synth"]
    sr = 96000
    log = []

    # Switch preset
    synth.clear_midi()
    mid = mido.MidiFile(); track = mido.MidiTrack(); mid.tracks.append(track)
    track.append(mido.Message('program_change', program=prog, time=0))
    tmp = f"temp_pc_{os.getpid()}_{prog}.mid"
    mid.save(tmp)
    synth.load_midi(tmp, all_events=True)
    engine.render(1.5)
    synth.clear_midi()
    os.remove(tmp)

    # Detect preset transposition via a raw reference note (matches
    # sample_gm_pack.py exactly: detect_pitch_midi_loudest on C4 v127).
    preset_transpose = 0
    ref_note = 60
    synth.add_midi_note(ref_note, 127, 0.0, 0.6)
    engine.render(1.0)
    ref_audio = engine.get_audio()
    synth.clear_midi()
    if ref_audio.ndim == 1:
        ref_audio = np.column_stack((ref_audio, ref_audio))
    elif ref_audio.shape[0] == 2:
        ref_audio = ref_audio.T

    detected_ref_pitch = sp.detect_pitch_midi_loudest(ref_audio, sr)
    if detected_ref_pitch is not None:
        diff = detected_ref_pitch - ref_note
        nearest_octave = int(round(diff / 12.0)) * 12
        if abs(diff - nearest_octave) <= 1 and abs(nearest_octave) <= 48:
            preset_transpose = nearest_octave
            if preset_transpose != 0:
                log.append(f"transpose {preset_transpose:+} st")
        else:
            preset_transpose = 0
    else:
        log.append("could not detect preset pitch")

    notes = sp.NOTES_TO_SAMPLE if hasattr(sp, "NOTES_TO_SAMPLE") else [24, 36, 48, 60, 72, 84, 96, 108]
    velocities = sp.VELOCITIES if hasattr(sp, "VELOCITIES") else [64, 127]
    duration = 1.0
    total_duration = 1.5

    rendered = {}
    for idx, note in enumerate(notes):
        for v_idx, vel in enumerate(velocities):
            synth.clear_midi()
            play_note = max(0, min(127, note - preset_transpose))
            synth.add_midi_note(play_note, vel, 0.0, duration)
            engine.render(total_duration)
            audio = engine.get_audio()

            # Silent retry
            if float(np.max(np.abs(audio))) < 0.001:
                retry = f"temp_retry_{os.getpid()}_{prog}.mid"
                synth.clear_midi()
                m2 = mido.MidiFile(); t2 = mido.MidiTrack(); m2.tracks.append(t2)
                t2.append(mido.Message('program_change', program=prog, time=0))
                m2.save(retry)
                synth.load_midi(retry, all_events=True)
                engine.render(3.0)
                synth.clear_midi()
                os.remove(retry)
                synth.add_midi_note(play_note, vel, 0.0, duration)
                engine.render(total_duration)
                audio = engine.get_audio()

            if audio.ndim == 1:
                audio = np.column_stack((audio, audio))
            elif audio.shape[0] == 2:
                audio = audio.T
            rendered[(idx, v_idx)] = audio

    # Neighbor fallback per velocity layer (silence → borrow nearest audible)
    for v_idx, vel in enumerate(velocities):
        silent = [i for i in range(len(notes))
                  if float(np.max(np.abs(rendered[(i, v_idx)]))) < 0.001]
        audible = [i for i in range(len(notes)) if i not in silent]
        if silent:
            if audible:
                for sidx in silent:
                    donor = min(audible, key=lambda j: abs(j - sidx))
                    rendered[(sidx, v_idx)] = rendered[(donor, v_idx)]
                    log.append(f"borrow {sp.midi_to_note_name(notes[donor])} for silent {sp.midi_to_note_name(notes[sidx])}")
            else:
                log.append(f"all notes silent v{vel}")

    # Pitch detection per note (v127), reusing sample_gm_pack's detector
    note_pitches = {}
    for idx, note in enumerate(notes):
        audio_v127 = rendered[(idx, 1)]
        detected = sp.detect_pitch_midi(audio_v127, sr)
        if detected is None:
            detected = note
        note_pitches[idx] = detected

    # Clamp detection (identical to sample_gm_pack.py)
    kept = []
    idx = 0
    while idx < len(notes):
        run_end = idx
        while (run_end + 1 < len(notes)
               and note_pitches[run_end + 1] == note_pitches[idx]):
            run_end += 1
        if run_end > idx:
            rep = (idx + run_end) // 2
            kept.append(rep)
            log.append(f"clamp {sp.midi_to_note_name(notes[idx])}..{sp.midi_to_note_name(notes[run_end])} -> {sp.midi_to_note_name(notes[rep])}")
        else:
            kept.append(idx)
        idx = run_end + 1

    # Build the list of samples to write + SFZ region dicts.
    samples = []
    regions = []
    vel_ranges = [(0, 95), (96, 127)]
    vel_xfade = [(0, 0, 85, 95), (85, 95, 127, 127)]
    for k, idx in enumerate(kept):
        note = notes[idx]
        if k == 0:
            lokey = 0
        else:
            prev_note = notes[kept[k - 1]]
            lokey = (prev_note + note) // 2 + 1
        if k == len(kept) - 1:
            hikey = 127
        else:
            next_note = notes[kept[k + 1]]
            hikey = (note + next_note) // 2
        actual_pitch = note_pitches[idx]
        for v_idx, vel in enumerate(velocities):
            lovel, hivel = vel_ranges[v_idx]
            xfin_lo, xfin_hi, xfout_lo, xfout_hi = vel_xfade[v_idx]
            note_name = sp.midi_to_note_name(note)
            sample_name = f"gm_{prog:03d}_{note_name}_v{vel}.wav"
            samples.append((sample_name, rendered[(idx, v_idx)]))
            regions.append({
                "sample_name": sample_name,
                "pitch_keycenter": actual_pitch,
                "lokey": lokey, "hikey": hikey,
                "lovel": lovel, "hivel": hivel,
                "xfin_lo": xfin_lo, "xfin_hi": xfin_hi,
                "xfout_lo": xfout_lo, "xfout_hi": xfout_hi,
            })

    return {
        "prog": prog, "inst_name": inst_name,
        "preset": os.path.basename(preset_path),
        "log": log, "samples": samples, "regions": regions,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fast parallel GM pack renderer (multiprocessing across programs)."
    )
    parser.add_argument("--workers", type=int,
                        default=max(1, cpu_count() - 1),
                        help=f"Worker processes (default cpu-1={cpu_count()-1})")
    parser.add_argument("--programs", type=int, nargs="*",
                        help="Subset of program indices to render (default: all 0..127)")
    parser.add_argument("--samples-dir", default="General_MIDI_samples")
    parser.add_argument("--raw-dir", default="General_MIDI_samples_raw")
    args = parser.parse_args()

    # Resolve paths the same way the sequential script does
    factory_dir = "/Library/Application Support/Surge XT/patches_factory"
    preset_mapping = sp.build_preset_mapping(factory_dir)
    if not os.path.exists(VST_PATH):
        print(f"Error: Surge XT not found at {VST_PATH}")
        sys.exit(1)

    samples_dir = args.samples_dir
    raw_dir = args.raw_dir
    instruments_dir = "General_MIDI_instruments"
    midi_programs_dir = os.path.expanduser("~/Documents/Surge XT/Patches/MIDI Programs")
    os.makedirs(samples_dir, exist_ok=True)
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(instruments_dir, exist_ok=True)
    os.makedirs(midi_programs_dir, exist_ok=True)

    progs = args.programs if args.programs else list(range(128))
    is_full_pack = (len(progs) == 128)

    # ⚠ Safety: rendering a subset MUST NOT overwrite the master SFZ files,
    # otherwise a test run destroys the full pack. Subset runs write to
    # *_partial.sfz siblings; full runs (all 128) overwrite the masters.
    sfz_suffix = "" if is_full_pack else "_partial"

    # Backup user patches (same logic as sequential script)
    backup = []
    if os.path.isdir(midi_programs_dir):
        for f in os.listdir(midi_programs_dir):
            if f.endswith(".fxp"):
                src = os.path.join(midi_programs_dir, f)
                dst = src + ".bak_gm"
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    backup.append((src, dst))

    print(f"Rendering {len(progs)} programs on {args.workers} workers...")
    print(f"VST: {VST_PATH}")
    print(f"Samples → {samples_dir} (also mirrored to {raw_dir})\n")

    tasks = [(p, preset_mapping[p], midi_programs_dir, samples_dir) for p in progs]

    t0 = time.perf_counter()
    completed = 0

    # Results collected per-program; written to disk + SFZ in program order
    # (imap preserves input order, so the master SFZ comes out identical to
    # the sequential script regardless of which worker finishes first).
    master_paths = {
        f"General_MIDI{sfz_suffix}.sfz": "General_MIDI_samples_raw/",
        f"General_MIDI_sfizz{sfz_suffix}.sfz": "abs:/Volumes/External/Code/VST2SFZ/General_MIDI_samples_raw/",
        f"General_MIDI_sfizz_processed{sfz_suffix}.sfz": "abs:/Volumes/External/Code/VST2SFZ/General_MIDI_samples/",
    }
    if not is_full_pack:
        print(f"⚠ Subset render: writing to *{sfz_suffix}.sfz (masters left untouched)")
    master_files = {p: open(p, "w") for p in master_paths}
    for p, f in master_files.items():
        f.write(f"// General MIDI 128 Instrument Pack\n")
        f.write("// Generated from Surge XT factory presets (2 Velocity Layers, 8 Key Zones)\n\n")
        f.write("<control>\n")
        if p == f"General_MIDI{sfz_suffix}.sfz":
            f.write(f"default_path={samples_dir}/\n")
        f.write("\n")

    with Pool(processes=args.workers, initializer=_init_worker) as pool:
        for result in pool.imap(render_program, tasks, chunksize=1):
            prog = result["prog"]
            completed += 1
            print(f"[{completed}/{len(progs)}] prog {prog:03d} {result['inst_name']} "
                  f"({result['preset']})  {' | '.join(result['log']) if result['log'] else 'ok'}")

            # Write WAVs to both processed + raw dirs
            for sample_name, audio in result["samples"]:
                spath = os.path.join(samples_dir, sample_name)
                rpath = os.path.join(raw_dir, sample_name)
                sf.write(spath, audio, 96000, subtype="PCM_24")
                sf.write(rpath, audio, 96000, subtype="PCM_24")

            # Write individual instrument SFZ
            indiv_path = os.path.join(instruments_dir,
                                      f"gm_{prog:03d}_{result['inst_name']}.sfz")
            with open(indiv_path, "w") as f:
                f.write(f"// GM Program {prog}: {result['inst_name']}\n")
                f.write("<control>\n")
                f.write(f"default_path=../{samples_dir}/\n\n")
                f.write(f"<group>\nprg_num={prog}\n")
                for r in result["regions"]:
                    xf = (f" xfin_lovel={r['xfin_lo']} xfin_hivel={r['xfin_hi']}"
                          f" xfout_lovel={r['xfout_lo']} xfout_hivel={r['xfout_hi']}")
                    base = (f"pitch_keycenter={r['pitch_keycenter']}"
                            f" lokey={r['lokey']} hikey={r['hikey']}"
                            f" lovel={r['lovel']} hivel={r['hivel']}{xf}")
                    f.write(f"<region> sample={r['sample_name']} {base}\n")

            # Write master SFZ region lines (3 variants). Look up the live
            # filenames from master_paths keys so the _partial suffix applies
            # consistently when rendering a subset.
            #
            # One <group> header per program (NOT per region) — matches the
            # sequential script's output. Emitting <group> per region produces
            # 1926 redundant group blocks instead of 128; functionally valid
            # for sfizz but wasteful and diverges from the canonical SFZ.
            master_key   = f"General_MIDI{sfz_suffix}.sfz"
            sfizz_key    = f"General_MIDI_sfizz{sfz_suffix}.sfz"
            sfizzp_key   = f"General_MIDI_sfizz_processed{sfz_suffix}.sfz"
            master_files[sfizz_key].write(f"<group>\nloprog={prog} hiprog={prog}\n")
            master_files[sfizzp_key].write(f"<group>\nloprog={prog} hiprog={prog}\n")
            for r in result["regions"]:
                xf = (f" xfin_lovel={r['xfin_lo']} xfin_hivel={r['xfin_hi']}"
                      f" xfout_lovel={r['xfout_lo']} xfout_hivel={r['xfout_hi']}")
                base = (f"pitch_keycenter={r['pitch_keycenter']}"
                        f" lokey={r['lokey']} hikey={r['hikey']}"
                        f" lovel={r['lovel']} hivel={r['hivel']}{xf}")
                master_files[master_key].write(
                    f"<region> sample={r['sample_name']} {base}\n")
                master_files[sfizz_key].write(
                    f"<region> sample=/Volumes/External/Code/VST2SFZ/General_MIDI_samples_raw/{r['sample_name']} {base}\n")
                master_files[sfizzp_key].write(
                    f"<region> sample=/Volumes/External/Code/VST2SFZ/General_MIDI_samples/{r['sample_name']} {base}\n")

    for f in master_files.values():
        f.close()

    elapsed = time.perf_counter() - t0
    print(f"\n✓ Done! {len(progs)} programs rendered in {elapsed:.1f}s "
          f"({elapsed/len(progs):.2f}s/program on {args.workers} workers)")

    # Restore user patches
    for src, dst in backup:
        if os.path.exists(dst):
            shutil.copy2(dst, src)
            os.remove(dst)
    # Clean up our slot .fxp files
    for prog in progs:
        p = os.path.join(midi_programs_dir, f"{prog:03d}_{sp.GM_NAMES[prog]}.fxp")
        if os.path.exists(p):
            os.remove(p)
    print("Restored original user MIDI Programs.")


if __name__ == "__main__":
    main()
