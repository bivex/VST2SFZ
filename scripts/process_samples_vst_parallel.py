#!/usr/bin/env python3
"""
Parallel VST color chain processing — multiprocessing.Pool version of
process_samples_vst.py.

Each worker process holds its OWN copy of the DawDreamer engine + the full
VST3 plugin chain (CHOWTape → SDRR → spiff → soothe → Pro-Q 4 → Pro-MB →
Kotelnikov GE → Fresh Air → Chorus → Pro-R 2 → A1StereoControl → Pro-L 2).
VST3 plugins hold per-instance state, so they cannot be shared across
threads — multiprocessing (separate address spaces) is the only safe way to
parallelise. Each worker handles a chunk of samples independently.

Usage (identical CLI to process_samples_vst.py):
    python process_samples_vst_parallel.py
    python process_samples_vst_parallel.py --input DIR --output DIR --workers N

The DSP, preset table, parameter mappings, and signal graph are imported
from process_samples_vst.py so the two versions stay in lockstep — there is
exactly one source of truth for the chain.

Output is byte-for-byte equivalent to the single-threaded version because
the same VST3 binaries process the same input with the same parameters.
"""

import argparse
import glob
import os
import sys
import time
import traceback
from multiprocessing import Pool, cpu_count

import numpy as np
import scipy.signal
import soundfile as sf

# Reuse the single source of truth: presets, VST paths, sample rate,
# graph topology, kotelnikov/limiter configuration, apply_preset, etc.
import process_samples_vst as pst


# ---------------------------------------------------------------------------
# Per-worker state
# ---------------------------------------------------------------------------
# Each worker process initialises this once (via Pool initializer) and reuses
# it for every sample it processes. Stored in module-level globals so the
# pool worker function can access them without re-creating the engine.
_WORKER = {}


def _init_worker():
    """Pool initializer: build a private engine + plugin chain per worker.

    Runs once per worker process. The DawDreamer engine and every VST3
    plugin instance live in this process's address space and are never
    shared with the parent or other workers.
    """
    devnull = open(os.devnull, "w")
    old_stderr = os.dup(2)
    os.dup2(devnull.fileno(), 2)
    try:
        engine = pst.daw.RenderEngine(pst.SAMPLE_RATE, pst.BUFFER_SIZE)
        tape = engine.make_plugin_processor("tape", pst.CHOW_PATH)
        sdrr = engine.make_plugin_processor("sdrr", pst.SDRR_PATH)
        spiff = engine.make_plugin_processor("spiff", pst.SPIFF_PATH)
        soothe = engine.make_plugin_processor("soothe", pst.SOOTHE_PATH)
        pro_q = engine.make_plugin_processor("pro_q", pst.PRO_Q_PATH)
        pro_mb = engine.make_plugin_processor("pro_mb", pst.PRO_MB_PATH)
        kotelnikov_ge = engine.make_plugin_processor("kot", pst.KOTELNIKOV_GE_PATH)
        fresh_air = engine.make_plugin_processor("fresh", pst.FRESH_AIR_PATH)
        chorus = engine.make_plugin_processor("cho", pst.CHORUS_PATH)
        stereo = engine.make_plugin_processor("ste", pst.STEREO_PATH)
        reverb = engine.make_plugin_processor("reverb", pst.PRO_R_PATH)
        limiter = engine.make_plugin_processor("limiter", pst.PRO_L_PATH)
        pst.configure_kotelnikov_ge(kotelnikov_ge)
        pst.configure_limiter(limiter)

        dummy = np.zeros((2, pst.BUFFER_SIZE), dtype=np.float32)
        pb = engine.make_playback_processor("pb", dummy)

        connections = [
            (pb, []),
            (tape, ["pb"]),
            (sdrr, ["tape"]),
            (spiff, ["sdrr"]),
            (soothe, ["spiff"]),
            (pro_q, ["soothe"]),
            (pro_mb, ["pro_q"]),
            (kotelnikov_ge, ["pro_mb"]),
            (fresh_air, ["kot"]),
            (chorus, ["fresh"]),
            (reverb, ["cho"]),
            (stereo, ["reverb"]),
            (limiter, ["ste"]),
        ]
        engine.load_graph(connections)

        _WORKER.update({
            "engine": engine, "pb": pb, "tape": tape, "sdrr": sdrr,
            "spiff": spiff, "soothe": soothe, "pro_q": pro_q, "pro_mb": pro_mb,
            "reverb": reverb, "chorus": chorus, "stereo": stereo,
            "fresh_air": fresh_air,
        })
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()


def _process_one(task):
    """Worker function: process a single sample file.

    Mirrors process_samples_vst.process_file exactly, but pulls the engine
    and plugins from this worker's globals instead of receiving them as
    arguments (which would require pickling — impossible for live VST state).

    Returns (filename, success, error_message_or_None).
    """
    filepath, out_dir = task
    filename = os.path.basename(filepath)
    w = _WORKER
    try:
        prog = pst.program_from_name(filename)
        preset = pst.get_preset_for_program(prog)

        audio, sr = sf.read(filepath)
        if audio.ndim == 1:
            audio = np.column_stack((audio, audio))

        if sr != pst.SAMPLE_RATE:
            gcd = int(np.gcd(sr, pst.SAMPLE_RATE))
            up = pst.SAMPLE_RATE // gcd
            down = sr // gcd
            audio = scipy.signal.resample_poly(audio, up, down, axis=0)
            sr = pst.SAMPLE_RATE

        if preset["bypass"]:
            out = audio.T.astype(np.float32)
            peak = float(np.max(np.abs(out)))
            if peak > 1e-6:
                out = out * (0.95 / peak)
            sf.write(os.path.join(out_dir, filename), out.T, pst.SAMPLE_RATE, subtype="PCM_24")
            return filename, True, None

        audio_2d = audio.T.astype(np.float32)
        w["pb"].set_data(audio_2d)

        pst.apply_preset(
            w["tape"], w["pro_q"], w["pro_mb"], w["reverb"], w["chorus"],
            w["stereo"], w["fresh_air"], w["spiff"], w["sdrr"], w["soothe"],
            preset,
        )

        duration = len(audio) / sr
        w["engine"].render(duration)
        out = w["engine"].get_audio("limiter")

        peak = float(np.max(np.abs(out)))
        if peak > 1e-6:
            out = out * (0.95 / peak)

        sf.write(os.path.join(out_dir, filename), out.T, pst.SAMPLE_RATE, subtype="PCM_24")
        return filename, True, None
    except Exception as e:
        return filename, False, f"{e}\n{traceback.format_exc()}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(
        description="Parallel VST color chain processing (multiprocessing.Pool)."
    )
    parser.add_argument("--input", default=os.path.join(_root, "General_MIDI_samples_raw"))
    parser.add_argument("--output", default=os.path.join(_root, "General_MIDI_samples"))
    parser.add_argument(
        "--workers", type=int, default=max(1, cpu_count() - 1),
        help=f"Number of worker processes (default: cpu_count-1 = {cpu_count()-1})",
    )
    args = parser.parse_args()

    src_dir, out_dir = args.input, args.output
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(src_dir, "*.wav")))
    if not files:
        print(f"Error: no WAV files in {src_dir}")
        sys.exit(1)

    # Validate VST paths once in the parent before spawning workers.
    for name, path in [
        ("CHOWTape", pst.CHOW_PATH),
        ("SDRR2", pst.SDRR_PATH),
        ("spiff", pst.SPIFF_PATH),
        ("soothe2", pst.SOOTHE_PATH),
        ("FabFilter Pro-Q 4", pst.PRO_Q_PATH),
        ("FabFilter Pro-MB", pst.PRO_MB_PATH),
        ("TDR Kotelnikov GE", pst.KOTELNIKOV_GE_PATH),
        ("Fresh Air", pst.FRESH_AIR_PATH),
        ("Chorus", pst.CHORUS_PATH),
        ("StereoControl", pst.STEREO_PATH),
        ("FabFilter Pro-R 2", pst.PRO_R_PATH),
        ("FabFilter Pro-L 2", pst.PRO_L_PATH),
    ]:
        if not os.path.exists(path):
            print(f"Error: {name} not found at {path}")
            sys.exit(1)

    tasks = [(f, out_dir) for f in files]
    total = len(tasks)
    print(f"Found {total} samples in {src_dir}")
    print(f"Workers: {args.workers}")
    print(f"Output:  {out_dir}")
    print(f"Spawning workers (each loads its own VST chain, ~3s init)...")

    t_start = time.perf_counter()
    completed = 0
    failed = 0
    failures = []

    # chunksize > 1 reduces inter-process communication overhead. With ~2000
    # short tasks and N workers, a chunksize of ~total/(workers*4) keeps the
    # scheduler busy without starving the tail.
    chunksize = max(1, total // (args.workers * 4))

    with Pool(processes=args.workers, initializer=_init_worker) as pool:
        for filename, success, err in pool.imap_unordered(_process_one, tasks, chunksize=chunksize):
            completed += 1
            if not success:
                failed += 1
                failures.append((filename, err))
                print(f"  [{completed}/{total}] FAILED: {filename} - {err}")
            elif completed % 100 == 0 or completed == total:
                elapsed = time.perf_counter() - t_start
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0
                print(f"  [{completed}/{total}] {filename}  "
                      f"({rate:.1f} samples/s, ETA {eta:.0f}s)")

    elapsed = time.perf_counter() - t_start
    print(f"\n✓ Done! {completed - failed}/{total} samples processed "
          f"in {elapsed:.1f}s ({total/elapsed:.1f} samples/s) → {out_dir}")
    if failed:
        print(f"  {failed} failures:")
        for fn, err in failures[:10]:
            print(f"    {fn}: {err.splitlines()[0] if err else '?'}")

    # Pitch auto-aligner runs once in the parent, exactly like the
    # single-threaded version. It operates on the RAW dry samples so it is
    # unaffected by which worker processed what.
    if "drums" not in src_dir.lower():
        print("\nRunning pitch auto-aligner on the raw dry samples...")
        import subprocess
        cmd = [sys.executable, "patch_sfz_pitches.py", "--raw-dir", src_dir]
        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f"Warning: Pitch auto-aligner failed to run: {e}")


if __name__ == "__main__":
    main()
