#!/usr/bin/env python3
"""
Diva Synth Pack — renders a curated bank of u-he Diva analog-synth voices
to multisampled SFZ instruments.

Unlike the Dexed pack (which targets the 96 GM melodic programs), Diva is a
pure analog-modelling synth, so there is no GM map to follow. Instead each
curated factory .h2p preset becomes its own instrument, grouped into the four
playable Diva categories — bass / lead / poly / pad. Drone, FX, and rhythmic
(arp/sequence) presets are intentionally excluded: they don't multisample into
a clean keymap.

Voice selection: hand-picked from the Diva factory library
(/Library/Audio/Presets/u-he/Diva), chosen for sustained, pitched, key-tracking
tones that sample cleanly. Names are shown next to each entry.

Loading: Diva loads natively in dawdreamer, and .h2p presets load straight
through plugin.load_preset(path) — no SYX-bank / program_change dance like the
DX7 pack needs.

Post-processing: subsonic HPF + per-group transparent EQ/comp + trim/fade,
then whole-instrument LUFS normalisation (shared gain, true-peak guarded).
No reverb — dry samples for use in samplers/DAWs.

Output goes to Diva_pack_* directories.
"""

import os
import sys
import glob
import numpy as np
import soundfile as sf
import dawdreamer as daw
from pitch_utils import detect_pitch_midi

try:
    import pyloudnorm as pyln

    HAS_PYLOUDNORM = True
except ImportError:
    HAS_PYLOUDNORM = False

DIVA_PATH = "/Library/Audio/Plug-Ins/VST3/Diva.vst3"
PRESET_ROOT = "/Library/Audio/Presets/u-he/Diva"

SAMPLE_RATE = 44100
BUFFER_SIZE = 512
NOTES_TO_SAMPLE = [24, 36, 48, 60, 72, 84, 96, 108]  # C1–C8
VELOCITIES = [64, 127]
VEL_RANGES = [(0, 95), (96, 127)]
VEL_XFADE = [(0, 0, 85, 95), (85, 95, 127, 127)]
DURATION = 2.0  # note-on length
RELEASE = 1.5  # tail for slow analog releases / pads
TOTAL_DURATION = DURATION + RELEASE
SETTLE_RENDER = 0.5  # silence rendered after preset load so the patch settles

TARGET_LUFS = -18.0  # industry standard for sampler libraries


# ── Curated Diva voices ──────────────────────────────────────────────────────
# Each tuple: (group, slot_name, preset_relpath). slot_name is the SFZ-safe
# instrument name; preset_relpath is relative to PRESET_ROOT. Verified to exist
# on disk. prg_num is assigned by enumeration order (0..N-1).
DIVA_VOICES = [
    # ── Bass ──────────────────────────────────────────────────────────────
    ("bass", "analog_bass", "1 BASS/XS Analog Bass.h2p"),
    ("bass", "warm_bass", "1 BASS/XS Warm Bass.h2p"),
    ("bass", "sub_tri_bass", "1 BASS/MK Bass Sub Tri.h2p"),
    ("bass", "picked_bass", "1 BASS/MK Bass Picked.h2p"),
    ("bass", "funk_bass", "1 BASS/MK Bass Funkay.h2p"),
    ("bass", "upright_bass", "1 BASS/TUC Upright Bass.h2p"),
    ("bass", "cable_bass", "1 BASS/HS Cable Bass.h2p"),
    ("bass", "boomer_bass", "1 BASS/HS Boomer.h2p"),
    # ── Lead ──────────────────────────────────────────────────────────────
    ("lead", "sine_lead", "2 LEAD/MK Sine Lead.h2p"),
    ("lead", "saw_rubber_lead", "2 LEAD/MK Saw Rubber.h2p"),
    ("lead", "razor_lead", "2 LEAD/HS Razor.h2p"),
    ("lead", "vintage_lead", "2 LEAD/XS Vintage Lead.h2p"),
    ("lead", "clarinet", "2 LEAD/MK Clarinet.h2p"),
    ("lead", "flute", "2 LEAD/MK Flute.h2p"),
    ("lead", "oboe", "2 LEAD/MK Oboe.h2p"),
    ("lead", "viola", "2 LEAD/MK Viola.h2p"),
    # ── Poly synth ────────────────────────────────────────────────────────
    ("poly", "big_old_polly", "3 POLY SYNTH/HS Big Old Polly.h2p"),
    ("poly", "fum_piano", "3 POLY SYNTH/HS Fum Piano.h2p"),
    ("poly", "can_piano", "3 POLY SYNTH/HS CanPiano.h2p"),
    ("poly", "glass_piano", "3 POLY SYNTH/TAS Glass Piano.h2p"),
    ("poly", "pianissimo", "3 POLY SYNTH/MM Pianissimo.h2p"),
    ("poly", "wavey_ep", "3 POLY SYNTH/HS Wavey EP.h2p"),
    ("poly", "analog_clavinova", "3 POLY SYNTH/XS Analog Clavinova.h2p"),
    ("poly", "gammond_organ", "3 POLY SYNTH/HS Gammond.h2p"),
    ("poly", "brass_long", "3 POLY SYNTH/MK Brass Long.h2p"),
    ("poly", "strings_pwm", "3 POLY SYNTH/MK Strings Long PWM.h2p"),
    ("poly", "cello", "3 POLY SYNTH/MK Cello.h2p"),
    ("poly", "accordion", "3 POLY SYNTH/MK Accordion.h2p"),
    # ── Pad / dream ───────────────────────────────────────────────────────
    ("pad", "beauty_pad", "4 DREAM SYNTH/BS Beauty Pad.h2p"),
    ("pad", "angel_wings", "4 DREAM SYNTH/HS Angel Wings.h2p"),
    ("pad", "june_sunshine", "4 DREAM SYNTH/HS June Sunshine.h2p"),
    ("pad", "sun_strings", "4 DREAM SYNTH/HS SunStrings.h2p"),
    ("pad", "dramatic_strings", "4 DREAM SYNTH/MM Dramatic Strings.h2p"),
    ("pad", "choir_clouds", "4 DREAM SYNTH/MM Choir In The Clouds.h2p"),
    ("pad", "explorer_pad", "4 DREAM SYNTH/TUC Explorer Pad.h2p"),
    ("pad", "analog_e_piano", "4 DREAM SYNTH/XS Analog E. Piano.h2p"),
    ("pad", "sweet_mellow", "4 DREAM SYNTH/XS Sweet And Mellow.h2p"),
    ("pad", "frost_piano", "4 DREAM SYNTH/MK Frost Piano.h2p"),
    ("pad", "sine_piano", "4 DREAM SYNTH/MK Sine Piano.h2p"),
    ("pad", "icicles", "4 DREAM SYNTH/HS Icicles.h2p"),
]


def midi_to_note_name(midi_num):
    notes = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"]
    octave = (midi_num // 12) - 1
    return f"{notes[midi_num % 12]}{octave}"


def trim_and_fade(
    audio: np.ndarray,
    sr: int,
    silence_thresh: float = 0.0005,
    fade_out_ms: float = 40.0,
) -> np.ndarray:
    envelope = np.max(np.abs(audio), axis=1)
    nonsilent = np.where(envelope > silence_thresh)[0]
    if len(nonsilent) == 0:
        return audio
    start = max(0, nonsilent[0] - int(0.002 * sr))
    audio = audio[start:]
    fade_samples = int(fade_out_ms / 1000 * sr)
    fade_samples = min(fade_samples, len(audio))
    fade_curve = np.linspace(1.0, 0.0, fade_samples) ** 2
    audio[-fade_samples:] *= fade_curve[:, np.newaxis]
    return audio


def postprocess(audio: np.ndarray, sr: int, group: str = "poly") -> np.ndarray:
    """Shape one rendered buffer: subsonic HPF + per-group EQ/comp + trim/fade.

    Loudness normalisation is intentionally NOT done here (it would flatten the
    velocity layers). Normalise the whole instrument as a set instead — see
    normalize_instrument_set.
    """
    if audio.ndim == 1:
        audio = np.column_stack((audio, audio))
    elif audio.ndim == 2:
        if audio.shape[0] <= 6 and audio.shape[1] > audio.shape[0]:
            audio = audio.T
        if audio.shape[1] == 1:
            audio = np.column_stack((audio, audio))
        elif audio.shape[1] > 2:
            audio = audio[:, :2]

    try:
        from pedalboard import (  # type: ignore
            Pedalboard,
            HighpassFilter,
            HighShelfFilter,
            LowShelfFilter,
            PeakFilter,
            Compressor,
        )

        # Subsonic high-pass first. Analog-modelled oscillators (esp. with PWM
        # and detuned/sub osc) put energy below the fundamental that eats
        # headroom and corrupts LUFS. 30 Hz cascaded twice (~24 dB/oct); bass
        # group uses 26 Hz to preserve low fundamentals.
        hp_hz = 26.0 if group == "bass" else 30.0
        fx = [
            HighpassFilter(cutoff_frequency_hz=hp_hz),
            HighpassFilter(cutoff_frequency_hz=hp_hz),
        ]

        if group == "bass":
            fx += [
                LowShelfFilter(cutoff_frequency_hz=60, gain_db=2.0),
                PeakFilter(cutoff_frequency_hz=3200, gain_db=-2.0, q=1.4),
                HighShelfFilter(cutoff_frequency_hz=6000, gain_db=-2.5),
            ]
            comp = Compressor(
                threshold_db=-12.0, ratio=2.5, attack_ms=8.0, release_ms=120.0
            )
        elif group == "lead":
            fx += [
                PeakFilter(cutoff_frequency_hz=3200, gain_db=-2.0, q=1.4),
                HighShelfFilter(cutoff_frequency_hz=6000, gain_db=1.5),
            ]
            comp = Compressor(
                threshold_db=-12.0, ratio=2.5, attack_ms=6.0, release_ms=100.0
            )
        elif group == "pad":
            fx += [
                PeakFilter(cutoff_frequency_hz=3200, gain_db=-2.0, q=1.4),
                HighShelfFilter(cutoff_frequency_hz=8000, gain_db=1.5),
                LowShelfFilter(cutoff_frequency_hz=100, gain_db=-1.5),
            ]
            comp = Compressor(
                threshold_db=-14.0, ratio=2.0, attack_ms=40.0, release_ms=300.0
            )
        else:  # poly
            fx += [
                PeakFilter(cutoff_frequency_hz=3200, gain_db=-2.0, q=1.4),
                HighShelfFilter(cutoff_frequency_hz=8000, gain_db=1.5),
            ]
            comp = Compressor(
                threshold_db=-12.0, ratio=2.5, attack_ms=8.0, release_ms=120.0
            )

        fx.append(comp)
        board = Pedalboard(fx)
        processed = board(audio.T, sr).T
    except Exception as e:
        print(f"  [postprocess skipped: {e}]")
        processed = audio

    return trim_and_fade(processed, sr)


def _true_peak(buf: np.ndarray, sr: int, oversample: int = 4) -> float:
    """Inter-sample (true) peak via Nx oversampling per channel."""
    try:
        from scipy.signal import resample_poly
    except Exception:
        return float(np.max(np.abs(buf))) if buf.size else 0.0
    if buf.ndim == 1:
        buf = buf[:, None]
    tp = 0.0
    for c in range(buf.shape[1]):
        up = resample_poly(buf[:, c], oversample, 1)
        if up.size:
            tp = max(tp, float(np.max(np.abs(up))))
    return tp


def normalize_instrument_set(
    rendered: dict, sr: int, target_lufs: float = TARGET_LUFS, tp_ceiling: float = 0.891
) -> None:
    """Loudness-normalise a whole instrument's buffers with ONE shared gain.

    rendered: {(note_idx, vel_idx): np.ndarray}. A single gain (median LUFS of
    the loud v127 layer across active notes) is applied to every buffer. This
    anchors the instrument to the target loudness while preserving velocity
    dynamics and key balance. A final per-buffer true-peak guard (-1 dBTP) keeps
    inter-sample levels codec-safe. Mutates rendered in place.
    """
    keys = list(rendered.keys())
    if not keys:
        return

    ref_keys = [k for k in keys if k[1] == 1] or keys

    gain = 1.0
    if HAS_PYLOUDNORM:
        meter = pyln.Meter(sr)
        per_note = []
        for k in ref_keys:
            buf = rendered[k]
            if len(buf) / sr <= 0.4:
                continue
            lo = meter.integrated_loudness(buf)
            try:
                lo = lo.item()
            except AttributeError:
                lo = float(lo)
            if not np.isinf(lo) and not np.isnan(lo) and lo > -32.0:
                per_note.append(lo)
        if per_note:
            ref_lufs = float(np.median(per_note))
            gain = 10.0 ** ((target_lufs - ref_lufs) / 20.0)
        else:
            peak = max(
                (float(np.max(np.abs(rendered[k]))) for k in ref_keys), default=0.0
            )
            if peak > 1e-6:
                gain = 0.85 / peak
    else:
        peak = max((float(np.max(np.abs(rendered[k]))) for k in ref_keys), default=0.0)
        if peak > 1e-6:
            gain = 0.85 / peak

    for k in keys:
        buf = rendered[k] * gain
        tp = _true_peak(buf, sr)
        if tp > tp_ceiling:
            buf = buf * (tp_ceiling / tp)
        rendered[k] = buf


def load_diva_preset(plugin, preset_path: str) -> bool:
    """Load a Diva .h2p preset. Returns True on success."""
    for method in ("load_preset", "load_state"):
        fn = getattr(plugin, method, None)
        if fn is None:
            continue
        try:
            fn(preset_path)
            return True
        except Exception:
            continue
    return False


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(DIVA_PATH):
        print(f"Error: Diva not found at {DIVA_PATH}")
        sys.exit(1)

    # Resolve + validate every curated preset up-front.
    voices = []  # (prg, group, slot_name, full_path)
    for prg, (group, slot_name, relpath) in enumerate(DIVA_VOICES):
        full = os.path.join(PRESET_ROOT, relpath)
        if not os.path.exists(full):
            print(f"Error: preset not found for {slot_name}: {relpath}")
            sys.exit(1)
        voices.append((prg, group, slot_name, full))

    samples_dir = os.path.join(project_root, "Diva_pack_samples")
    instruments_dir = os.path.join(project_root, "Diva_pack_instruments")
    os.makedirs(samples_dir, exist_ok=True)
    os.makedirs(instruments_dir, exist_ok=True)

    print(f"Curated {len(voices)} Diva voices")
    print("Initializing Diva engine...")
    devnull = open(os.devnull, "w")
    old_stderr = os.dup(2)
    os.dup2(devnull.fileno(), 2)
    try:
        engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)
        diva = engine.make_plugin_processor("diva", DIVA_PATH)
        engine.load_graph([(diva, [])])
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()

    # Absolute paths everywhere — some plugins chdir on preset load.
    master_path = os.path.join(project_root, "Diva_pack.sfz")
    sfizz_path = os.path.join(project_root, "Diva_pack_sfizz.sfz")

    master_f = open(master_path, "w")
    sfizz_f = open(sfizz_path, "w")

    for f, is_sfizz in [(master_f, False), (sfizz_f, True)]:
        f.write("// Diva Synth Pack — u-he Diva analog modelling\n")
        f.write(f"// {len(voices)} curated voices, 2 velocity layers, 8 key zones\n\n")
        f.write("<control>\n")
        if not is_sfizz:
            f.write(f"default_path={samples_dir}/\n")
        f.write("\n")

    total = len(voices)
    written_samples: set[str] = set()
    for idx, (prg, group, slot_name, preset_path) in enumerate(voices):
        preset_base = os.path.basename(preset_path)
        print(
            f"[{idx + 1}/{total}] prg {prg:02d}  {group}/{slot_name}  ({preset_base})"
        )

        diva.clear_midi()
        if not load_diva_preset(diva, preset_path):
            print(f"  ! preset load failed, skipping: {preset_base}")
            continue
        engine.render(SETTLE_RENDER)  # let the patch settle
        diva.clear_midi()

        # Render 8 notes × 2 velocities
        rendered = {}
        for n_idx, note in enumerate(NOTES_TO_SAMPLE):
            for v_idx, vel in enumerate(VELOCITIES):
                diva.clear_midi()
                diva.add_midi_note(note, vel, 0.0, DURATION)
                engine.render(TOTAL_DURATION)
                audio = engine.get_audio()
                diva.clear_midi()
                if audio.ndim == 1:
                    audio = np.column_stack((audio, audio))
                elif audio.shape[0] == 2:
                    audio = audio.T
                rendered[(n_idx, v_idx)] = audio

        # Post-process (subsonic HPF + per-group EQ/comp + trim/fade)
        for key in list(rendered.keys()):
            rendered[key] = postprocess(rendered[key], SAMPLE_RATE, group=group)

        # Loudness-normalise the instrument as a SET (shared gain, TP-guarded)
        normalize_instrument_set(rendered, SAMPLE_RATE)

        # Pitch detection on v127 layer
        note_pitches = {}
        for n_idx, note in enumerate(NOTES_TO_SAMPLE):
            det = detect_pitch_midi(rendered[(n_idx, 1)], SAMPLE_RATE)
            note_pitches[n_idx] = det if det is not None else note

        # Clamp: collapse runs of identical detected pitches
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
                rep = (i + run_end) // 2
                kept.append(rep)
                print(
                    f"  ~ clamp {midi_to_note_name(NOTES_TO_SAMPLE[i])}.."
                    f"{midi_to_note_name(NOTES_TO_SAMPLE[run_end])} → "
                    f"{midi_to_note_name(NOTES_TO_SAMPLE[rep])}"
                )
            else:
                kept.append(i)
            i = run_end + 1

        dropped = set()
        for v_idx in range(len(VELOCITIES)):
            for i in range(len(NOTES_TO_SAMPLE)):
                if float(np.max(np.abs(rendered[(i, v_idx)]))) < 0.001:
                    dropped.add(i)
                    print(
                        f"  ~ drop silent note {midi_to_note_name(NOTES_TO_SAMPLE[i])}"
                    )

        kept = [i for i in kept if i not in dropped]
        if not kept:
            print(f"  ! all notes silent/dropped, skipping {slot_name}")
            continue

        # Write individual SFZ
        indiv_path = os.path.join(
            instruments_dir, f"diva_{prg:03d}_{group}_{slot_name}.sfz"
        )
        indiv_f = open(indiv_path, "w")
        indiv_f.write(f"// Diva {prg}: {group}/{slot_name} ({preset_base})\n")
        indiv_f.write("<control>\n")
        indiv_f.write(f"default_path={samples_dir}/\n\n")
        indiv_f.write(f"<group>\nprg_num={prg}\n")

        master_f.write(f"// {group}/{slot_name}\n<group>\nprg_num={prg}\n")
        sfizz_f.write(f"// {group}/{slot_name}\n<group>\nloprog={prg} hiprog={prg}\n")

        for k, n_idx in enumerate(kept):
            note = NOTES_TO_SAMPLE[n_idx]
            if k == 0:
                lokey = 0
            else:
                lokey = (NOTES_TO_SAMPLE[kept[k - 1]] + note) // 2 + 1
            if k == len(kept) - 1:
                hikey = 127
            else:
                hikey = (note + NOTES_TO_SAMPLE[kept[k + 1]]) // 2
            actual_pitch = note_pitches[n_idx]

            for v_idx, vel in enumerate(VELOCITIES):
                lovel, hivel = VEL_RANGES[v_idx]
                xfin_lo, xfin_hi, xfout_lo, xfout_hi = VEL_XFADE[v_idx]
                note_name = midi_to_note_name(note)
                sample_name = f"diva_{prg:03d}_{note_name}_v{vel}.wav"
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
                sfizz_f.write(
                    f"<region> sample={samples_dir}/{sample_name} {base}\n"
                )

        indiv_f.close()
        master_f.write("\n")
        sfizz_f.write("\n")

    master_f.close()
    sfizz_f.close()

    # ── Sweep orphan samples ─────────────────────────────────────────────────
    removed = 0
    for f in glob.glob(os.path.join(samples_dir, "diva_*.wav")):
        if os.path.basename(f) not in written_samples:
            try:
                os.remove(f)
                removed += 1
            except OSError:
                pass
    print(f"Swept {removed} orphan sample(s); {len(written_samples)} live samples.")

    print(f"\n✓ Diva pack complete! {total} voices → {samples_dir}/")


if __name__ == "__main__":
    main()
