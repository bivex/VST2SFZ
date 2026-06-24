#!/usr/bin/env python3
"""
Apple GM Pack — renders the full General MIDI instrument set (programs 0-127)
plus the GM drum kit from Apple's built-in DLSMusicDevice AU.

DLSMusicDevice is the Roland GS / Sound Canvas sample set baked into macOS
(gs_instruments.dls). It is a real multisample ROMpler, so it covers the
acoustic half of GM (pianos, guitars, orchestra, drums) that a synth like Diva
or an FM engine like DX7 cannot reproduce convincingly. Quality is "GM-grade"
(mid-90s Roland), but it is authentic and complete with zero install.

Loading: the AU loads in dawdreamer by passing the CoreAudio.component path to
make_plugin_processor. Voices are selected with a MIDI program_change (melodic
programs 0-127); the drum kit plays on MIDI channel 10 (index 9) regardless of
program.

Pipeline (shared with the Dexed pack): render 8 notes x 2 velocities, subsonic
HPF + per-group EQ/comp + trim/fade, whole-instrument LUFS normalisation with a
true-peak guard, pitch-detected key zones, velocity crossfades.

Output goes to Apple_GM_* directories. Three banks are written: a master bank
(prg_num + an embedded drum section on channel 10) and two sfizz banks
(loprog/hiprog; drums come from a separate channel-10 synth as sfizz ignores
the lochan gate).
"""

import os
import sys
import glob
import numpy as np
import soundfile as sf
import mido
import dawdreamer as daw

from pitch_utils import detect_pitch_midi

# Reuse the battle-tested DSP + SFZ helpers from the Dexed pack so behaviour
# (EQ curves, true-peak guard, median LUFS anchor, drum section) stays identical.
from sample_dexed_pack import (
    GM_NAMES as DEXED_GM_NAMES,  # 0-95 only; we extend to 127 below
    get_group,
    midi_to_note_name,
    postprocess,
    normalize_instrument_set,
    write_drum_section,
    DRUM_NOTES,
)

# Apple DLSMusicDevice lives inside the system CoreAudio component bundle.
DLS_PATH = "/System/Library/Components/CoreAudio.component"

SAMPLE_RATE = 44100
BUFFER_SIZE = 512
NOTES_TO_SAMPLE = [24, 36, 48, 60, 72, 84, 96, 108]  # C1–C8
VELOCITIES = [64, 127]
VEL_RANGES = [(0, 95), (96, 127)]
VEL_XFADE = [(0, 0, 85, 95), (85, 95, 127, 127)]
DURATION = 2.0
RELEASE = 1.0
TOTAL_DURATION = DURATION + RELEASE
SETTLE_RENDER = 0.6

TARGET_LUFS = -18.0

# ── Full GM 0-127 melodic names ──────────────────────────────────────────────
# Slots 96-127 (effects / ethnic / percussive / sound-fx) that the Dexed pack
# omits. DLSMusicDevice covers all of them.
GM_NAMES_96_127 = [
    "sfx_rain",            # 96  FX 1 (rain)
    "sfx_soundtrack",      # 97  FX 2 (soundtrack)
    "sfx_crystal",         # 98  FX 3 (crystal)
    "sfx_atmosphere",      # 99  FX 4 (atmosphere)
    "sfx_brightness",      # 100 FX 5 (brightness)
    "sfx_goblins",         # 101 FX 6 (goblins)
    "sfx_echoes",          # 102 FX 7 (echoes)
    "sfx_scifi",           # 103 FX 8 (sci-fi)
    "sitar",               # 104
    "banjo",               # 105
    "shamisen",            # 106
    "koto",                # 107
    "kalimba",             # 108
    "bagpipe",             # 109
    "fiddle",              # 110
    "shanai",              # 111
    "tinkle_bell",         # 112
    "agogo",               # 113
    "steel_drums",         # 114
    "woodblock",           # 115
    "taiko_drum",          # 116
    "melodic_tom",         # 117
    "synth_drum",          # 118
    "reverse_cymbal",      # 119
    "guitar_fret_noise",   # 120
    "breath_noise",        # 121
    "seashore",            # 122
    "bird_tweet",          # 123
    "telephone_ring",      # 124
    "helicopter",          # 125
    "applause",            # 126
    "gunshot",             # 127
]

GM_NAMES = list(DEXED_GM_NAMES) + GM_NAMES_96_127  # 128 names total
assert len(GM_NAMES) == 128, f"expected 128 GM names, got {len(GM_NAMES)}"


def render_note(engine, inst, prog, note, vel, channel=0):
    """Render a single note for a given GM program. channel=9 → drum kit."""
    inst.clear_midi()
    add_note_with_channel(inst, prog, note, vel, channel)
    engine.render(TOTAL_DURATION)
    audio = engine.get_audio()
    inst.clear_midi()
    return _to_stereo(audio)


def _to_stereo(audio: np.ndarray) -> np.ndarray:
    """DLSMusicDevice returns 4 channels; collapse to interleaved stereo."""
    if audio.ndim == 1:
        return np.column_stack((audio, audio))
    # dawdreamer gives (channels, frames); transpose to (frames, channels)
    if audio.shape[0] < audio.shape[1]:
        audio = audio.T
    if audio.shape[1] == 1:
        return np.column_stack((audio[:, 0], audio[:, 0]))
    return audio[:, :2]


def add_note_with_channel(inst, prog, note, vel, channel):
    """Build a temp MIDI clip with program_change + note on the given channel.

    add_midi_note() has no channel argument, so the drum kit (GM channel 10 /
    index 9) must be driven through a MIDI file. We route melodic voices the
    same way for consistency.
    """
    mid = mido.MidiFile()
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    if channel != 9:  # drums ignore program; only set it for melodic voices
        tr.append(mido.Message("program_change", program=prog, channel=channel, time=0))
    ticks = mid.ticks_per_beat
    on_t = 0
    off_t = int(ticks * (DURATION / 0.5))  # ~tempo-independent length
    tr.append(mido.Message("note_on", note=note, velocity=vel, channel=channel, time=on_t))
    tr.append(mido.Message("note_off", note=note, velocity=0, channel=channel, time=off_t))
    tmp = f"/tmp/dls_{channel}_{prog}_{note}.mid"
    mid.save(tmp)
    inst.load_midi(tmp, all_events=True)
    try:
        os.remove(tmp)
    except OSError:
        pass


def select_program(engine, inst, prog, channel=0):
    """Send a program_change and let the patch settle before sampling."""
    inst.clear_midi()
    mid = mido.MidiFile()
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.Message("program_change", program=prog, channel=channel, time=0))
    tmp = f"/tmp/dls_pc_{channel}_{prog}.mid"
    mid.save(tmp)
    inst.load_midi(tmp, all_events=True)
    engine.render(SETTLE_RENDER)
    inst.clear_midi()
    try:
        os.remove(tmp)
    except OSError:
        pass


def render_drum_samples(engine, inst, out_dir):
    """Render the GM drum kit (channel 10) to gm_drum_N{note}_v{vel}.wav.

    write_drum_section (imported) expects samples named gm_drum_N{n}_v064/v127
    in a directory; we generate them here straight from DLSMusicDevice so the
    master bank's drum section is self-contained — no external KSHMR pack needed.
    """
    os.makedirs(out_dir, exist_ok=True)
    written = 0
    for note, name in DRUM_NOTES:
        for vel in (64, 127):
            inst.clear_midi()
            add_note_with_channel(inst, 0, note, vel, channel=9)
            engine.render(TOTAL_DURATION)
            audio = _to_stereo(engine.get_audio())
            inst.clear_midi()
            # light shaping: trim + fade only, drums keep their transient
            from sample_dexed_pack import trim_and_fade

            audio = trim_and_fade(audio, SAMPLE_RATE, fade_out_ms=15.0)
            peak = float(np.max(np.abs(audio)))
            if peak < 0.001:
                continue
            if peak > 0.891:
                audio = audio * (0.891 / peak)
            sf.write(
                os.path.join(out_dir, f"gm_drum_N{note}_v{vel:03d}.wav"),
                audio,
                SAMPLE_RATE,
                subtype="PCM_16",
            )
        written += 1
    print(f"  drum render: {written} notes sampled")
    return written


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(os.path.abspath(__file__))

    samples_dir = os.path.join(project_root, "Apple_GM_samples")
    instruments_dir = os.path.join(project_root, "Apple_GM_instruments")
    drum_samples_dir = os.path.join(project_root, "Apple_GM_samples_drums")
    os.makedirs(samples_dir, exist_ok=True)
    os.makedirs(instruments_dir, exist_ok=True)

    print("Initializing Apple DLSMusicDevice...")
    devnull = open(os.devnull, "w")
    old_stderr = os.dup(2)
    os.dup2(devnull.fileno(), 2)
    try:
        engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)
        inst = engine.make_plugin_processor("dls", DLS_PATH)
        engine.load_graph([(inst, [])])
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()
    print(f"  loaded: {inst.get_name()}")

    master_path = os.path.join(project_root, "Apple_GM.sfz")
    sfizz_path = os.path.join(project_root, "Apple_GM_sfizz.sfz")
    sfizz_proc_path = os.path.join(project_root, "Apple_GM_sfizz_processed.sfz")

    master_f = open(master_path, "w")
    sfizz_f = open(sfizz_path, "w")
    sfizz_proc_f = open(sfizz_proc_path, "w")

    for f, is_sfizz in [(master_f, False), (sfizz_f, True), (sfizz_proc_f, True)]:
        f.write("// Apple GM Pack — DLSMusicDevice (Roland GS), programs 0-127\n")
        f.write("// 2 Velocity Layers, 8 Key Zones\n\n")
        f.write("<control>\n")
        if not is_sfizz:
            f.write(f"default_path={samples_dir}/\n")
        f.write("\n")

    total = 128
    written_samples: set[str] = set()
    for slot in range(total):
        inst_name = GM_NAMES[slot]
        print(f"[{slot + 1}/{total}] prog {slot:03d}  {inst_name}")

        select_program(engine, inst, slot, channel=0)

        # Render 8 notes × 2 velocities
        rendered = {}
        for n_idx, note in enumerate(NOTES_TO_SAMPLE):
            for v_idx, vel in enumerate(VELOCITIES):
                rendered[(n_idx, v_idx)] = render_note(
                    engine, inst, slot, note, vel, channel=0
                )
            # program_change can be reset by load_midi; re-arm between notes
            select_program(engine, inst, slot, channel=0)

        # Post-process + normalise as a set
        for key in list(rendered.keys()):
            rendered[key] = postprocess(rendered[key], SAMPLE_RATE, slot=slot)
        normalize_instrument_set(rendered, SAMPLE_RATE)

        # Pitch detection on v127 layer
        note_pitches = {}
        for n_idx, note in enumerate(NOTES_TO_SAMPLE):
            det = detect_pitch_midi(rendered[(n_idx, 1)], SAMPLE_RATE)
            note_pitches[n_idx] = det if det is not None else note

        # Clamp runs of identical detected pitches
        kept = []
        i = 0
        while i < len(NOTES_TO_SAMPLE):
            run_end = i
            while (
                run_end + 1 < len(NOTES_TO_SAMPLE)
                and note_pitches[run_end + 1] == note_pitches[i]
            ):
                run_end += 1
            if run_end > i:
                kept.append((i + run_end) // 2)
            else:
                kept.append(i)
            i = run_end + 1

        dropped = set()
        for v_idx in range(len(VELOCITIES)):
            for i in range(len(NOTES_TO_SAMPLE)):
                if float(np.max(np.abs(rendered[(i, v_idx)]))) < 0.001:
                    dropped.add(i)
        kept = [i for i in kept if i not in dropped]
        if not kept:
            print(f"  ! all notes silent, skipping {inst_name}")
            continue

        indiv_path = os.path.join(instruments_dir, f"gm_{slot:03d}_{inst_name}.sfz")
        indiv_f = open(indiv_path, "w")
        indiv_f.write(f"// GM Program {slot}: {inst_name} (Apple DLS)\n")
        indiv_f.write("<control>\n")
        indiv_f.write(f"default_path={samples_dir}/\n\n")
        indiv_f.write(f"<group>\nprg_num={slot}\n")

        master_f.write(f"<group>\nprg_num={slot}\n")
        sfizz_f.write(f"<group>\nloprog={slot} hiprog={slot}\n")
        sfizz_proc_f.write(f"<group>\nloprog={slot} hiprog={slot}\n")

        for k, n_idx in enumerate(kept):
            note = NOTES_TO_SAMPLE[n_idx]
            lokey = 0 if k == 0 else (NOTES_TO_SAMPLE[kept[k - 1]] + note) // 2 + 1
            hikey = (
                127
                if k == len(kept) - 1
                else (note + NOTES_TO_SAMPLE[kept[k + 1]]) // 2
            )
            actual_pitch = note_pitches[n_idx]

            for v_idx, vel in enumerate(VELOCITIES):
                lovel, hivel = VEL_RANGES[v_idx]
                xfin_lo, xfin_hi, xfout_lo, xfout_hi = VEL_XFADE[v_idx]
                note_name = midi_to_note_name(note)
                sample_name = f"gm_{slot:03d}_{note_name}_v{vel}.wav"
                audio = rendered[(n_idx, v_idx)]

                sf.write(
                    os.path.join(samples_dir, sample_name),
                    audio,
                    SAMPLE_RATE,
                    subtype="PCM_16",
                )
                written_samples.add(sample_name)

                xf = (
                    f" xfin_lovel={xfin_lo} xfin_hivel={xfin_hi}"
                    f" xfout_lovel={xfout_lo} xfout_hivel={xfout_hi}"
                )
                base = (
                    f"pitch_keycenter={actual_pitch}"
                    f" lokey={lokey} hikey={hikey}"
                    f" lovel={lovel} hivel={hivel}{xf}"
                )
                indiv_f.write(f"<region> sample={sample_name} {base}\n")
                master_f.write(f"<region> sample={sample_name} {base}\n")
                sfizz_f.write(f"<region> sample={samples_dir}/{sample_name} {base}\n")
                sfizz_proc_f.write(
                    f"<region> sample={samples_dir}/{sample_name} {base}\n"
                )

        indiv_f.close()
        master_f.write("\n")
        sfizz_f.write("\n")
        sfizz_proc_f.write("\n")

    # ── GM Drum Kit (channel 10) ─────────────────────────────────────────────
    print("\nRendering GM drum kit (channel 10)...")
    render_drum_samples(engine, inst, drum_samples_dir)
    print("Appending GM drum kit section (master bank only)...")
    write_drum_section(master_f, drum_samples_dir)

    master_f.close()
    sfizz_f.close()
    sfizz_proc_f.close()

    # ── Sweep orphan samples ─────────────────────────────────────────────────
    removed = 0
    for f in glob.glob(os.path.join(samples_dir, "gm_*.wav")):
        if os.path.basename(f) not in written_samples:
            try:
                os.remove(f)
                removed += 1
            except OSError:
                pass
    print(f"Swept {removed} orphan sample(s); {len(written_samples)} live samples.")
    print(f"\n✓ Apple GM pack complete! {total} programs + drum kit → {samples_dir}/")


if __name__ == "__main__":
    main()
