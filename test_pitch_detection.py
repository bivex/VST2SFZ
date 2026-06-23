#!/usr/bin/env python3
"""
Test suite for `detect_pitch_midi` in sample_gm_pack.py.

Three layers:
  1. Synthetic tones (pure sines, harmonics, weak fundamental, octave ambiguity)
  2. Edge cases (silence, noise, sub-bass, very high notes, DC offset)
  3. Regression on real rendered samples (cross-check against filename + audit)

Run:   python test_pitch_detection.py
"""

import os
import sys
import unittest
import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sample_gm_pack import detect_pitch_midi

NOTE_LETTERS = ["c", "cs", "d", "ds", "e", "f", "fs", "g", "gs", "a", "as", "b"]


def midi_to_freq(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def name_to_midi(name):
    import re
    m = re.match(r"([A-G])(s?)(-?\d+)$", name)
    key = (m.group(1) + m.group(2)).lower()
    octave = int(m.group(3))
    return NOTE_LETTERS.index(key) + (octave + 1) * 12


def synth_tone(midi, sr=44100, dur=1.0, harmonics=None, noise_db=-60,
               start_at=0.0, take_until=None, detune_cents=0, dc=0.0):
    """Build a multi-harmonic tone. harmonics is a dict {n: amplitude} (n=1 is fundamental).

    harmonics default = pure fundamental. noise_db sets additive white noise floor.
    start_at/take_until select a sub-window (seconds) to simulate attack/sustain.
    detune_cents shifts all partials. dc adds a DC offset.
    """
    if harmonics is None:
        harmonics = {1: 1.0}
    f0 = midi_to_freq(midi) * (2 ** (detune_cents / 1200))
    t = np.arange(int(sr * dur)) / sr
    sig = np.zeros_like(t)
    for n, amp in harmonics.items():
        sig += amp * np.sin(2 * np.pi * f0 * n * t)
    # normalize to peak 0.9
    peak = float(np.max(np.abs(sig)))
    if peak > 0:
        sig = sig * (0.9 / peak)
    # additive noise floor
    if noise_db is not None and np.isfinite(noise_db):
        noise = np.random.RandomState(42).randn(len(t))
        noise = noise / float(np.max(np.abs(noise) + 1e-12)) * (0.9 * 10 ** (noise_db / 20))
        sig = sig + noise
    if dc != 0:
        sig = sig + dc
    # sub-window (mono)
    s = int(start_at * sr)
    e = int(take_until * sr) if take_until else len(sig)
    mono = sig[s:e]
    return mono.astype(np.float32), sr


class PureToneTests(unittest.TestCase):
    """detect_pitch_midi must return the requested MIDI for a pure sine."""

    def _check(self, midi, tol=0):
        audio, sr = synth_tone(midi)
        got = detect_pitch_midi(audio, sr)
        self.assertIsNotNone(got, f"MIDI {midi}: detector returned None")
        self.assertEqual(got, midi, f"MIDI {midi}: got {got}")

    def test_mid_range_notes(self):
        for midi in [48, 55, 60, 64, 67, 72, 79]:
            with self.subTest(midi=midi):
                self._check(midi)

    def test_extreme_low(self):
        # C1=24 (32.7 Hz) and C0=12 (16.3 Hz, near 16 Hz cutoff)
        self._check(24)
        self._check(28)

    def test_extreme_low_near_cutoff(self):
        # MIDI 16 ≈ 20.6 Hz — just above the 16 Hz floor
        self._check(16)

    def test_extreme_high(self):
        # C8=108 (~4186 Hz) and top of range
        self._check(96)
        self._check(108)


class HarmonicStructureTests(unittest.TestCase):
    """Instruments with rich harmonic content / weak fundamental."""

    def test_weak_fundamental_strong_2nd_harmonic(self):
        """Violin-like: fundamental at 0.1, 2nd harmonic at 1.0 (10x stronger).

        A 'lowest-peak' detector should still pick the fundamental.
        """
        midi = 67  # G4 ≈ 392 Hz
        audio, sr = synth_tone(midi, harmonics={1: 0.1, 2: 1.0, 3: 0.6, 4: 0.3})
        got = detect_pitch_midi(audio, sr)
        self.assertIsNotNone(got)
        self.assertEqual(got, midi, f"weak fundamental: got {got}, want {midi}")

    def test_strong_third_harmonic_brass(self):
        """Brass-like: strong odd harmonics, weaker even."""
        midi = 62  # D4
        audio, sr = synth_tone(midi, harmonics={1: 0.7, 2: 0.3, 3: 1.0, 5: 0.5})
        got = detect_pitch_midi(audio, sr)
        self.assertIsNotNone(got)
        self.assertEqual(got, midi, f"brass harmonics: got {got}, want {midi}")

    def test_octave_ambiguity(self):
        """Two equal-strength partials one octave apart. Lowest-peak must win."""
        midi = 60  # C4
        audio, sr = synth_tone(midi, harmonics={1: 1.0, 2: 1.0})
        got = detect_pitch_midi(audio, sr)
        self.assertEqual(got, midi, f"octave ambiguity: got {got}, want {midi}")

    def test_missing_fundamental(self):
        """Fun acoustic case: fundamental removed, only harmonics 2,3,4 present.

        This is genuinely ambiguous — many detectors report +1 octave here.
        We assert that the detector returns EITHER the true pitch OR one octave up.
        Both are defensible; we just pin current behaviour.
        """
        midi = 60
        audio, sr = synth_tone(midi, harmonics={2: 1.0, 3: 0.7, 4: 0.5})
        got = detect_pitch_midi(audio, sr)
        self.assertIn(got, (midi, midi + 12), f"missing fundamental: got {got}")

    def test_detuned_tone(self):
        """+50 cents sharp: sitting exactly on the semitone boundary. With the
        zero-pad detector the raw estimate lands at 60.4999 (within 0.001% of
        60.5), so the rounding result is genuinely ambiguous. We accept either
        neighbor (60 or 61) — both are physically correct at the ±50c edge."""
        midi = 60
        audio, sr = synth_tone(midi, detune_cents=50)
        got = detect_pitch_midi(audio, sr)
        self.assertIn(got, (midi, midi + 1),
                      f"+50c boundary: got {got}, expected {midi} or {midi+1}")

    def test_detuned_down_rounds_down(self):
        """-50 cents: same boundary ambiguity, accept either neighbor."""
        midi = 60
        audio, sr = synth_tone(midi, detune_cents=-50)
        got = detect_pitch_midi(audio, sr)
        self.assertIn(got, (midi - 1, midi),
                      f"-50c boundary: got {got}, expected {midi-1} or {midi}")

    def test_detuned_clearly_inside_range(self):
        """±40 cents: well inside the semitone, MUST round to the requested note
        (the boundary is ±50c). This pins the boundary to a sane location."""
        midi = 60
        for cents in (-40, -20, 0, 20, 40):
            with self.subTest(cents=cents):
                audio, sr = synth_tone(midi, detune_cents=cents)
                got = detect_pitch_midi(audio, sr)
                self.assertEqual(got, midi, f"{cents:+d}c: got {got}, want {midi}")


class EdgeCaseTests(unittest.TestCase):

    def test_silence_returns_none(self):
        audio = np.zeros(int(44100 * 1.0), dtype=np.float32)
        self.assertIsNone(detect_pitch_midi(audio, 44100))

    def test_near_silence_returns_none(self):
        audio = (np.random.RandomState(1).randn(44100) * 1e-7).astype(np.float32)
        self.assertIsNone(detect_pitch_midi(audio, 44100))

    def test_pure_noise_returns_none_or_unstable(self):
        """White noise has no pitch. Detector may return None or a garbage value —
        we accept None or any MIDI, but it should NOT crash."""
        audio = (np.random.RandomState(7).randn(44100) * 0.9).astype(np.float32)
        try:
            got = detect_pitch_midi(audio, 44100)
        except Exception as e:
            self.fail(f"noise crashed detector: {e}")

    def test_dc_offset_handled(self):
        """+0.3 DC offset should not derail pitch detection (script removes DC)."""
        midi = 60
        audio, sr = synth_tone(midi, dc=0.3)
        got = detect_pitch_midi(audio, sr)
        self.assertEqual(got, midi, f"DC offset: got {got}, want {midi}")

    def test_attack_only_short_window(self):
        """If the 0.1s..0.7s sustain window falls outside the signal, return None."""
        midi = 60
        audio, sr = synth_tone(midi, dur=0.05)  # only 50ms total
        got = detect_pitch_midi(audio, sr)
        self.assertIsNone(got, f"short signal should return None, got {got}")

    def test_sub_bass_just_above_cutoff(self):
        """MIDI 12 ≈ 16.35 Hz — right at the 16 Hz lower cutoff."""
        audio, sr = synth_tone(12, dur=1.5)
        got = detect_pitch_midi(audio, sr)
        # at the very edge of the window; accept None or 12
        self.assertIn(got, (None, 12), f"sub-bass edge: got {got}")


class RealSampleRegressionTests(unittest.TestCase):
    """Cross-check detect_pitch_midi against the actual rendered GM samples.

    These tests confirm that on real Surge XT output the detector agrees with
    the filename's requested note within +/-1 semitone (accounting for the
    known FM-preset velocity jitter and clamp behavior).
    """

    @classmethod
    def setUpClass(cls):
        cls.raw_dir = "General_MIDI_samples_raw"
        cls.has_samples = os.path.isdir(cls.raw_dir) and any(
            f.startswith("gm_") for f in os.listdir(cls.raw_dir)
        )

    def _check_real(self, fname, expected_midi, tol=1):
        if not self.has_samples:
            self.skipTest("no raw samples present")
        path = os.path.join(self.raw_dir, fname)
        if not os.path.exists(path):
            self.skipTest(f"{fname} not present")
        audio, sr = sf.read(path)
        got = detect_pitch_midi(audio, sr)
        self.assertIsNotNone(got, f"{fname}: None")
        self.assertLessEqual(abs(got - expected_midi), tol,
                             f"{fname}: got {got}, expected {expected_midi}±{tol}")

    def test_piano_c4(self):
        self._check_real("gm_000_C4_v127.wav", name_to_midi("C4"))

    def test_piano_low(self):
        self._check_real("gm_000_C2_v127.wav", name_to_midi("C2"))

    def test_bass_c2(self):
        self._check_real("gm_033_C2_v127.wav", name_to_midi("C2"))

    def test_strings_c5(self):
        self._check_real("gm_048_C5_v127.wav", name_to_midi("C5"))

    def test_brass_c4(self):
        self._check_real("gm_061_C4_v127.wav", name_to_midi("C4"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
