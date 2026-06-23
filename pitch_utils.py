#!/usr/bin/env python3
"""
Shared fundamental-pitch detector for the GM sample-pack pipeline.

Algorithm: validated lowest-peak FFT
─────────────────────────────────────
1. Fold to mono, cut a sustain window (skip first 0.1 s, take 0.6 s).
2. Remove DC, apply Hanning window, compute magnitude spectrum.
3. Collect all local peaks in 16 Hz – 8.4 kHz (MIDI 0–120) that exceed
   5 % of the band maximum.
4. Walk peaks from lowest to highest frequency.
   For each candidate at frequency F:
     • Look up the magnitude at the 2nd-harmonic position (2 × F).
     • If  mag(candidate) < ARTIFACT_RATIO × mag(2F),  the candidate is a
       ghost / sub-octave artefact (room resonance, VST bleed, DC harmonic)
       rather than a true fundamental — skip it and continue.
   The first candidate that passes the artefact check is returned.
5. Fallback: if every candidate was rejected, use the lowest one anyway
   (rare; handles instruments whose 2nd harmonic is simply absent).
6. Apply parabolic sub-bin interpolation for sub-semitone accuracy.

Why this matters
────────────────
• The plain lowest-peak method (as used in the original sample_gm_pack.py)
  produces a −12-semitone octave error on ~12 % of samples because some
  Surge XT presets leak a faint sub-bass ghost peak one octave below the
  real note.  The artefact check catches it: the ghost at F/2 is always
  ≪ 10 % as loud as the real note at F.

• The loudest-peak method (as used in the original patch_sfz_pitches.py)
  fixes octave-below errors but introduces +1-octave errors on instruments
  where the 2nd harmonic dominates (strings, brass).  We don't use it.

• Weak-fundamental instruments (violin-like, fundamental ≈ 20–30 % of
  2nd harmonic) still pass the check because 0.2 > ARTIFACT_RATIO (0.10).

Benchmark on 963 v127 samples from audit_pitch.csv
  fft_low (old)     75.1 %  within ±0.5 st,  188 octave errors
  fft_validated     ~88 %   expected (eliminates ghost-peak failures)
"""

import numpy as np

# ── tuneable constants ────────────────────────────────────────────────────────

# Candidate is treated as a ghost artefact when its magnitude is below this
# fraction of the magnitude at the 2nd-harmonic frequency position.
# 0.10 → skip if 2nd harmonic position is >10× louder.
ARTIFACT_RATIO: float = 0.10

# MIDI-note frequency band to search (covers MIDI 0–120).
FREQ_MIN_HZ: float = 16.0
FREQ_MAX_HZ: float = 8400.0

# Sustain window: skip attack, then analyse this many seconds.
ATTACK_SKIP_S: float = 0.10
SUSTAIN_WIN_S: float = 0.60

# Peaks below this fraction of the band maximum are ignored.
PEAK_THRESHOLD: float = 0.05  # 5 % — lower than original 10 % to catch weak fundamentals


# ── public API ────────────────────────────────────────────────────────────────

def detect_pitch_midi(audio: np.ndarray, sr: int) -> int | None:
    """Return the MIDI note number of the fundamental pitch, or None.

    Parameters
    ----------
    audio : np.ndarray
        Shape (N,), (N, channels), or (channels, N).  Stereo is folded to mono.
    sr : int
        Sample rate in Hz.

    Returns
    -------
    int | None
        Rounded MIDI note (0–127), or None for silence / non-tonal input.
    """
    # ── fold to mono ──────────────────────────────────────────────────────────
    if audio.ndim == 1:
        mono = audio.astype(np.float64)
    elif audio.shape[0] <= 2 and audio.ndim == 2 and audio.shape[0] < audio.shape[1]:
        # (channels, N) layout — rare but happens with DawDreamer before reshape
        mono = audio.mean(axis=0).astype(np.float64)
    else:
        # (N, channels) layout — standard after sf.read / after .T in pack script
        mono = audio.mean(axis=1).astype(np.float64)

    # ── sustain window ────────────────────────────────────────────────────────
    start = int(sr * ATTACK_SKIP_S)
    end = start + int(sr * SUSTAIN_WIN_S)
    seg = mono[start:end]
    if seg.size == 0 or float(np.max(np.abs(seg))) < 1e-5:
        return None  # silence or near-silence

    # ── DC removal + windowing ────────────────────────────────────────────────
    seg = (seg - float(np.mean(seg))) * np.hanning(len(seg))

    # ── magnitude spectrum ────────────────────────────────────────────────────
    spec = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
    bin_width = float(freqs[1] - freqs[0])  # Hz per bin

    # ── valid frequency band ──────────────────────────────────────────────────
    valid_mask = (freqs >= FREQ_MIN_HZ) & (freqs <= FREQ_MAX_HZ)
    valid_idx = np.where(valid_mask)[0]
    if valid_idx.size == 0:
        return None

    max_mag = float(np.max(spec[valid_idx]))
    if max_mag < 1e-5:
        return None
    threshold = PEAK_THRESHOLD * max_mag

    # ── collect all significant local peaks ───────────────────────────────────
    peaks: list[tuple[int, float, float]] = []   # (bin_idx, freq_hz, magnitude)
    for i in valid_idx:
        if 0 < i < len(spec) - 1:
            if (spec[i] >= spec[i - 1]
                    and spec[i] >= spec[i + 1]
                    and spec[i] >= threshold):
                peaks.append((int(i), float(freqs[i]), float(spec[i])))

    if not peaks:
        # Absolute maximum as fallback (handles pure-sine edge cases)
        best_idx = int(valid_idx[np.argmax(spec[valid_idx])])
        return _finalize(spec, freqs, best_idx, bin_width)

    # ── walk peaks low→high; skip ghost sub-octave artefacts ─────────────────
    peaks_by_freq = sorted(peaks, key=lambda p: p[1])
    best_idx: int | None = None

    for idx, freq_hz, mag in peaks_by_freq:
        # Artefact check: is the 2nd-harmonic position much louder?
        target_2f = 2.0 * freq_hz
        if target_2f <= FREQ_MAX_HZ:
            nearest_bin = int(np.argmin(np.abs(freqs - target_2f)))
            mag_at_2f = float(spec[nearest_bin])
            if mag < ARTIFACT_RATIO * mag_at_2f:
                # This candidate is ≪ 10 % as loud as what's at 2×freq →
                # almost certainly a ghost artefact, not the true fundamental.
                continue

        best_idx = idx
        break

    if best_idx is None:
        # Every candidate was rejected (pathological spectrum).
        # Fall back to the lowest peak — least-bad option.
        best_idx = peaks_by_freq[0][0]

    return _finalize(spec, freqs, best_idx, bin_width)


# ── internal helper ───────────────────────────────────────────────────────────

def _finalize(spec: np.ndarray, freqs: np.ndarray, idx: int, bin_width: float) -> int | None:
    """Apply parabolic interpolation and convert Hz → MIDI int."""
    freq = float(freqs[idx])
    if 0 < idx < len(freqs) - 1:
        a0 = float(spec[idx - 1])
        a1 = float(spec[idx])
        a2 = float(spec[idx + 1])
        denom = a0 - 2.0 * a1 + a2
        if denom != 0.0:
            offset = 0.5 * (a0 - a2) / denom
            freq += offset * bin_width
    if freq <= 0.0:
        return None
    midi = 69.0 + 12.0 * np.log2(freq / 440.0)
    return int(round(midi))


# ── second public API: loudest-peak for uncompensated raw renders ─────────────
#
# Two different contexts require two different strategies:
#
#   detect_pitch_midi          — used by sample_gm_pack.py
#     The render loop compensates the preset's built-in transpose BEFORE
#     rendering: it plays (note − preset_transpose) so the output lands at
#     the target note.  The rendered audio therefore has a normal harmonic
#     structure where the fundamental is (often) one of the stronger low
#     peaks.  Validated lowest-peak finds it reliably.
#
#   detect_pitch_midi_loudest  — used by patch_sfz_pitches.py
#     The raw dry samples were rendered WITHOUT transpose compensation
#     (they were stored before the mastering chain).  The dominant spectral
#     energy is the "perceived" pitch of the preset — which may be many
#     octaves away from the filename note.  The loudest peak in the musical
#     range is the best single-number summary of what the listener hears,
#     and it matches the keycenters that sample_gm_pack.py computed during
#     the original render (88.7 % agreement vs 56 % for lowest-peak).


def detect_pitch_midi_loudest(audio: np.ndarray, sr: int) -> int | None:
    """Return the MIDI note of the loudest spectral peak, or None.

    Intended for use on **raw, uncompensated** Surge XT renders where the
    dominant energy is the actual perceived pitch of the preset.

    Parameters
    ----------
    audio : np.ndarray
        Shape (N,), (N, channels), or (channels, N).
    sr : int
        Sample rate in Hz.
    """
    # ── fold to mono ──────────────────────────────────────────────────────────
    if audio.ndim == 1:
        mono = audio.astype(np.float64)
    elif audio.shape[0] <= 2 and audio.ndim == 2 and audio.shape[0] < audio.shape[1]:
        mono = audio.mean(axis=0).astype(np.float64)
    else:
        mono = audio.mean(axis=1).astype(np.float64)

    # ── sustain window ────────────────────────────────────────────────────────
    start = int(sr * ATTACK_SKIP_S)
    end = start + int(sr * SUSTAIN_WIN_S)
    seg = mono[start:end]
    if seg.size == 0 or float(np.max(np.abs(seg))) < 1e-5:
        return None

    # ── DC removal + windowing ────────────────────────────────────────────────
    seg = (seg - float(np.mean(seg))) * np.hanning(len(seg))

    # ── magnitude spectrum ────────────────────────────────────────────────────
    spec = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
    bin_width = float(freqs[1] - freqs[0])

    # ── loudest peak in valid band ────────────────────────────────────────────
    valid_mask = (freqs >= FREQ_MIN_HZ) & (freqs <= FREQ_MAX_HZ)
    masked = spec.copy()
    masked[~valid_mask] = 0.0
    best_idx = int(np.argmax(masked))
    if masked[best_idx] <= 0.0:
        return None

    return _finalize(spec, freqs, best_idx, bin_width)

