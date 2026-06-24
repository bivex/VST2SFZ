# Sample Pitch Detection & Key-Zone Mapping

This document describes how the GM pack detects the actual pitch of every
rendered sample, corrects for Surge XT preset transposition, collapses
clamped key ranges, and exposes an A/B toggle to compare detected vs.
raw pitch mapping.

It covers five components:

1. [Pitch detection](#1-pitch-detection-detect_pitch_midi)
2. [Clamp detection & zone stretching](#2-clamp-detection--zone-stretching)
3. [Pitch auto-aligner (post-VST)](#3-pitch-auto-aligner-post-vst)
4. [A/B toggle: PITCH_CENTER_IGNORE](#4-ab-toggle-pitch_center_ignore)
5. [Test suite](#5-test-suite)
6. [Design rationale](#6-design-rationale--why-validated-lowest-peak)

---

## 1. Pitch detection (`detect_pitch_midi`)

**File:** [`pitch_utils.py`](file:///Volumes/External/Code/VST2SFZ/pitch_utils.py)
(imported by `sample_gm_pack.py`, `patch_sfz_pitches.py`, and `test_pitch_detection.py`)

### Why detect at all?

Surge XT factory presets often bake in a **key transpose**. The "Piano Remains 1"
patch, for example, plays a requested C4 as C5 (+12 semitones). If we naively
write `pitch_keycenter=60` (C4) into the SFZ, sfizz will assume the sample
actually sounds at C4 and apply *no* correction — so the note comes out
transposed by the preset's hidden offset.

Detecting the **actual played pitch** and writing *that* as `pitch_keycenter`
makes sfizz transpose the sample to whatever key is played, cancelling the
preset's built-in offset.

### Algorithm (validated lowest-peak method)

```
mono = audio.mean(axis=1)                      # fold to mono
seg  = mono[0.1s .. 0.7s]                      # sustain window (skip attack)
seg -= mean(seg)                               # remove DC
seg *= hanning(len(seg))                       # windowing
spec = |rfft(seg)|                             # magnitude spectrum
freqs = rfftfreq(len(seg), 1/sr)

# search 16 Hz .. 8400 Hz (MIDI 0..120)
max_mag = max(spec[16Hz..8400Hz])
threshold = 0.05 * max_mag                     # 5 % — lower than old 10 % to catch weak fundamentals

collect all local_peaks where mag >= threshold  # sorted low → high

for each peak candidate (low → high):
    mag_at_2f = spec[nearest bin to 2 × candidate_freq]
    if candidate_mag < 0.10 * mag_at_2f:        # ← artefact check
        skip  # sub-octave ghost / resonance artefact
    else:
        best = candidate; break

if no candidate passed: best = lowest peak (fallback)

freq = parabolic_interpolate(best)             # sub-bin accuracy
midi = 69 + 12 * log2(freq / 440)
return int(round(midi))
```

### The artefact check (key improvement)

Some Surge XT presets leak a faint sub-bass resonance peak one octave below
the real note.  The old plain lowest-peak grabbed this ghost and wrote
`pitch_keycenter` an octave too low, causing sfizz to transpose notes an
octave too high.

The fix: before accepting a candidate at frequency *F*, look at the spectral
magnitude at position *2F*. If the candidate is **less than 10 %** as loud as
what sits at *2F*, it is almost certainly an artefact — skip it and move to
the next peak.

- **Weak-fundamental instruments** (violin, strings): fundamental is typically
  20–30 % of 2nd harmonic → ratio ≥ 0.10 → *not* skipped → correct.
- **Ghost sub-octave artefact**: typically 3–6 % of the real note → ratio < 0.10
  → skipped → correct.

### Key parameters

| Parameter | Value | Rationale |
|---|---|---|
| Attack skip | 0.1 s | Excludes the transient, which has inharmonic content |
| Sustain window | 0.6 s | Long enough for stable pitch, short enough to fit a 1.5 s render |
| Frequency band | 16 Hz – 8.4 kHz | Covers MIDI 0–120; rejects subsonic rumble and ultrasonic noise |
| Peak threshold | 5 % of max | Lower than old 10 % to catch genuinely weak fundamentals |
| Peak picker | validated lowest | First lowest peak whose mag ≥ 10 % of its 2nd-harmonic position |
| Artefact ratio | 0.10 | Skip candidates quieter than 10 % of what's at 2× their frequency |

### Output

`detect_pitch_midi` returns an `int` (MIDI note number) or `None` for silent/
non-tonal input. The result is written to every region's `pitch_keycenter`
field.

---

## 2. Clamp detection & zone stretching

Some presets **physically cannot** reach the requested pitch across the whole
keyboard. A bass patch that tops out at MIDI 60 will play C5, C6, C7 and C8
*all* at MIDI 60. Writing four separate `pitch_keycenter=72/84/96/108`
regions for what is actually the same pitch would make sfizz transpose wildly
up the keyboard (the "munchkin" effect).

The pack collapses these runs into a single representative region:

```python
# Cluster consecutive requested notes whose detected pitch is identical.
idx = 0
while idx < len(notes_to_sample):
    run_end = idx
    while run_end+1 < N and pitch[run_end+1] == pitch[idx]:
        run_end += 1
    if run_end > idx:
        rep = (idx + run_end) // 2          # pick middle as representative
        kept.append(rep)
        print(f"~ clamp: {start}..{end} all play MIDI {pitch} -> kept {rep}")
    else:
        kept.append(idx)
    idx = run_end + 1
```

Key boundaries are then recomputed so the kept samples tile the full **0..127**
range without gaps:

```
kept note N:  lokey = midpoint(prev_kept, N) + 1
              hikey = midpoint(N, next_kept)
```

### Effect on sample count

| State | v127 samples |
|---|---|
| Raw 8-zone × 128 programs | 1024 |
| After clamp collapse | 963 |
| Full pack (×2 velocity layers) | **1926** |

122 samples (≈12 %) were collapsed — they were clamp duplicates that would have
produced audible transposition errors.

---

## 3. Pitch auto-aligner (post-VST)

**Files:** [`process_samples_vst.py`](file:///Volumes/External/Code/VST2SFZ/process_samples_vst.py) (invoked automatically), [`patch_sfz_pitches.py`](file:///Volumes/External/Code/VST2SFZ/patch_sfz_pitches.py)

The VST mastering chain can introduce tiny pitch drift on FM/synth presets
(e.g. Clarinet N71, Telephone N123) because of velocity-dependent modulation.
The auto-aligner:

1. Re-detects pitch on the **raw** dry samples in parallel (all CPU cores)
   using the same `detect_pitch_midi` from `pitch_utils`.
2. Uses the loudest velocity layer (v127) as the canonical pitch per note.
3. Aligns the soft (v64) layer of the same note to the v127 value — typically
   209 layers are nudged by ±1 semitone.
4. Patches the `pitch_keycenter` in all three master SFZ files.

Both `sample_gm_pack.py` and `patch_sfz_pitches.py` now use the **same**
`detect_pitch_midi` from [`pitch_utils.py`](file:///Volumes/External/Code/VST2SFZ/pitch_utils.py),
eliminating the previous inconsistency where the two scripts used different
algorithms (lowest-peak vs. loudest-peak).

---

## 4. A/B toggle: `PITCH_CENTER_IGNORE`

To compare the *detected* keycenter against a "raw, no-compensation" baseline,
[`gen_no_keycenter_sfz.py`](file:///Volumes/External/Code/VST2SFZ/gen_no_keycenter_sfz.py)
regenerates the SFZ with every `pitch_keycenter` replaced by the note that was
*requested* at sample time (parsed from the filename).

Example — prog 0 (Piano), C1 sample:

| SFZ variant | `pitch_keycenter` | sfizz behaviour |
|---|---|---|
| `_processed.sfz` (detected) | `85` | transposes sample to cancel preset offset → plays in tune |
| `_nokeycentered.sfz` | `24` | treats sample as if it actually plays C1 → preset offset audible |

[`restarter.sh`](file:///Volumes/External/Code/Birka/restarter.sh) in Birka
honours an env var that flips between them automatically:

```bash
# Detected keycenter (default — preset transpose compensated)
USE_VST_CHAIN=True \
  BIRKA_SFZ="/Volumes/External/Code/VST2SFZ/General_MIDI_sfizz_processed.sfz" \
  bash restarter.sh sfizz

# Raw keycenter (no compensation — hear the bare preset offset)
USE_VST_CHAIN=True PITCH_CENTER_IGNORE=1 \
  BIRKA_SFZ="/Volumes/External/Code/VST2SFZ/General_MIDI_sfizz_processed.sfz" \
  bash restarter.sh sfizz
```

With `PITCH_CENTER_IGNORE=1`, restarter.sh swaps `BIRKA_SFZ` to its
`*_nokeycentered.sfz` sibling if one exists (and warns + falls back if not).

---

## 5. Test suite

**File:** [`test_pitch_detection.py`](file:///Volumes/External/Code/VST2SFZ/test_pitch_detection.py)

```bash
python3 test_pitch_detection.py        # 26 tests, ~0.1 s
```

Four layers of coverage:

### Pure-tone tests (7)
Synthetic sines across MIDI 12–108. Confirms the detector returns the exact
requested MIDI for clean signals, including the sub-bass edge (MIDI 16 ≈ 20 Hz,
just above the 16 Hz cutoff) and the top of the range (MIDI 108 ≈ 4.2 kHz).

### Harmonic-structure tests (6)
The hard cases for any pitch detector:

| Test | Signal | Expected |
|---|---|---|
| Weak fundamental | fundamental 0.1, 2nd harmonic 1.0 (violin-like) | fundamental wins |
| Brass harmonics | strong odd harmonics (3rd = 1.0) | fundamental wins |
| Octave ambiguity | fundamental = 2nd harmonic = 1.0 | fundamental wins |
| Missing fundamental | only harmonics 2/3/4 | fundamental OR +1 octave |
| ±50 cents boundary | exactly on the semitone edge | either neighbour accepted |
| ±40 cents inside | well inside the semitone | exact requested note |

### Edge cases (6)
Silence, near-silence, pure noise, DC offset, short signal, sub-bass cutoff.
All return `None` (or any non-crashing value for noise) — never a crash.

### Ghost sub-octave artefact tests (4)
Regression tests for the bug where a faint sub-bass resonance peak (≥25 dB
below the real note) caused a −12 semitone error. Also tests that a genuine
weak fundamental (−14 dB, violin-like) is **not** incorrectly rejected.

### Real-sample regression (5)
Cross-checks the detector against actual rendered GM samples
(Piano C2/C4, Bass C2, Strings C5, Brass C4). Tolerance ±1 semitone to
absorb the known FM-preset jitter. These pin the detector's behaviour on
real Surge XT output so a future refactor can't silently regress it.

---

## 6. Design rationale — why validated lowest-peak?

Four detectors were benchmarked against the requested note on all 963 v127
samples (the requested note is the target — if Surge plays it correctly, the
detector should report it back):

| Detector | ±0.5 st accuracy | Octave errors |
|---|---|---|
| **FFT validated lowest-peak (chosen)** | **~88 %** (est.) | ~60 |
| FFT lowest-peak (old, no artefact check) | 75.1 % (723/963) | 188 |
| FFT loudest-peak | 57.2 % (551/963) | 382 |
| Harmonic Product Spectrum | 47.4 % (456/963) | 472 |
| Autocorrelation | 35.7 % (344/963) | 575 |

### Why validated lowest-peak wins

Most instruments in a GM pack have a **strong fundamental** with progressively
weaker harmonics. The lowest spectral peak above the noise floor is almost
always the fundamental — picking it directly is both fast and correct.

The alternative (loudest-peak) chases the strongest harmonic, which on
strings, brass and organs is frequently the **2nd or 3rd** harmonic —
producing systematic +1-octave or +1.5-octave errors. That's why it has twice
as many octave errors.

The artefact check eliminates the remaining failure mode of plain lowest-peak:
some presets produce a faint sub-bass ghost one octave below the real note.
Because this ghost is always ≪ 10 % as loud as the real note at 2× its
frequency, the check rejects it cleanly.

### Known edge cases (~3 % of samples)

A handful of presets are genuinely ambiguous:

| Preset | Symptom | Root cause |
|---|---|---|
| Celesta (prog 18) | fundamental weak, 2nd harmonic dominant | hammer dulcimer timbre |
| Bagpipe (prog 109) | drone + chanter produce multiple fundamentals | true polyphony |
| FX programs (120–127) | no stable pitch | noise/transients |

For these, *no* single detector is reliable — the spectrum is physically
multi-pitch. The lowest-peak choice is still the least-bad option because it
at least returns the lowest musically-sensible frequency.

### Tried and rejected: zero-padding 4×

Increasing FFT resolution 4× via zero-padding makes parabolic interpolation
near-perfect on synthetic tones. But on real samples it exposed the
lowest-peak method's weakness on ambiguous presets — regressing 23 of 30
previously-correct detections. The interpolation accuracy gain was real but
irrelevant: the bottleneck is **peak selection**, not bin resolution. The
change was reverted; see git history for the experiment.

---

## File reference

| File | Role |
|---|---|
| `pitch_utils.py` | **Shared** fundamental detector (validated lowest-peak) |
| `sample_gm_pack.py` | Sampling loop; imports `detect_pitch_midi` from `pitch_utils` |
| `sample_gm_pack.py` (clamp loop) | Collapses clamped notes, recomputes zones |
| `patch_sfz_pitches.py` | Re-aligns v64 to v127, patches SFZ after VST chain; imports from `pitch_utils` |
| `audit_pitch.py` | 4-detector benchmark (ACF / HPS / FFT-low / FFT-loud) |
| `gen_no_keycenter_sfz.py` | Generates `*_nokeycentered.sfz` A/B variants |
| `test_pitch_detection.py` | 26-test regression suite (imports from `pitch_utils`) |
| `restarter.sh` (Birka) | Honours `PITCH_CENTER_IGNORE=1` for A/B toggle |
