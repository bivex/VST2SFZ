# Sample Timbre Audit & Preset Re-mapping

This document records the spectral audit of all 128 GM program slots, the
preset re-mapping that fixed the worst timbral mismatches, and the residual
limitations of sourcing every GM instrument from a single synthesizer
(Surge XT).

It complements [`samples_pitch.md`](file:///Volumes/External/Code/VST2SFZ/samples_pitch.md)
(pitch detection) and [`GM.md`](file:///Volumes/External/Code/VST2SFZ/GM.md)
(pack overview).

---

## 1. Background: why a timbre audit was needed

Every GM slot is rendered from a single Surge XT factory preset (see the
mapping table in [`sample_gm_pack.py`](file:///Volumes/External/Code/VST2SFZ/sample_gm_pack.py)).
Surge XT is a **subtractive / wavetable synthesizer** — it has no acoustic
sample content. Several early mappings chose presets whose timbre did not
match the GM instrument name, producing obviously wrong sounds:

* `prog 0` (Acoustic Grand Piano) was mapped to `Plucks/Piano Remains 1.fxp`
  — a bright pluck/FM patch with **no fundamental** (fund_ratio 0.00,
  centroid 1055 Hz). It sounded like a synth pluck, not a piano.
* `prog 74` (Recorder) was mapped to `Leads/Sine Lead.fxp` — a pure sine
  lead, indistinguishable from a test tone.
* `prog 38` (Synth Bass 1) was mapped to `Basses/Lord Sawtooth.fxp`, which
  **clamps** the keyboard (every note above C3 collapses to one pitch), so
  the upper half of the bass range was dead.

The audit below quantifies these mismatches across all 128 slots and
documents the replacements that were made.

---

## 2. Methodology

Each program was rendered at C4 v127 (or the nearest kept note after clamp
collapse) and analysed with the following spectral descriptors:

| Metric | Meaning | Why it matters |
|---|---|---|
| `fund_ratio` | fundamental energy ÷ total harmonic energy | High = strong, clear pitch (piano, flute). Low = buzzy/plucky (harpsichord, distortion). |
| `centroid` | spectral centroid (Hz) | Low = dark/warm (bass, cello). High = bright/buzzy (brass, lead). |
| `h2`, `h3` | 2nd / 3rd harmonic ÷ fundamental | Strong h2 = octave-rich (organ, distorted guitar). Strong h3 = nasal/brassy. |
| `attack_ms` | time to 50 % energy in first 100 ms | Fast = percussive (mallets). Slow = sustained (pad, choir). |

Each GM family has a characteristic profile (e.g. pianos want
`fund_ratio ≥ 0.4`, `centroid 300–1500 Hz`; brass wants `centroid ≥ 1500 Hz`).
Programs whose measured profile fell outside the family envelope were flagged
as mismatches and re-mapped.

The audit script is reproduced inline in the session log; the comparison
table is summarised in §4.

---

## 3. Mismatches found

Out of 96 musical programs (FX/percussion slots 96–127 excluded), **34**
were flagged against their family envelope. They were triaged into three
buckets:

### 3.1 Critical — clearly wrong timbre (re-mapped)

| prog | GM name | Old preset | Symptom | New preset |
|------|---------|-----------|---------|------------|
| 0 | Acoustic Grand Piano | `Plucks/Piano Remains 1.fxp` | fund 0.00, pluck/FM, also C8 keycenter bug (77 vs 108) | `Keys/EP 1.fxp` |
| 1 | Bright Acoustic Piano | `Keys/Artificial 2.fxp` | centroid 3096, no piano character | `Keys/Soft Suitcase.fxp` |
| 2 | Electric Grand Piano | `Keys/Artificial 1.fxp` | fund 0.13, plucky | `Polysynths/Oldie.fxp` |
| 3 | Honky-Tonk Piano | `Keys/Experiment.fxp` | fund 0.19, h2 0.80, FM | `Plucks/Convex.fxp` |
| 5 | Electric Piano 2 | `Keys/DX EP.fxp` | fund 0.28, centroid 3019, FM | `Plucks/Sinus Verby Pops.fxp` |
| 23 | Tango Accordion | `Keys/Circus 1.fxp` | duplicate of prog 21 | `Leads/Butter.fxp` |
| 33 | Electric Bass (finger) | `Basses/Fingered.fxp` | fund 0.07, no fundamental | `Basses/Sub 2.fxp` |
| 38 | Synth Bass 1 | `Basses/Lord Sawtooth.fxp` | clamps whole upper range | `Basses/Square Bass.fxp` |
| 66 | Tenor Sax | `Leads/Shanai.fxp` | fund 0.04, FM | `MPE/Baritonosaurus Saxus.fxp` |
| 73 | Flute | `Winds/Cyber Flute.fxp` | duplicate after swap | `Winds/Tragic Winds.fxp` → `Winds/Cyber Flute.fxp` |
| 74 | Recorder | `Leads/Sine Lead.fxp` | pure sine, no breath | `Plucks/Soft Space Oboe Pops.fxp` |
| 77 | Shakuhachi | `Leads/Talky 2 MW.fxp` | formant vocal, not flute | `Leads/Smoothness World Cup.fxp` |

### 3.2 Medium — questionable but acceptable (kept)

These sit at the edge of their family envelope but are defensible:

`prog 7` Clavinet, `prog 24` Nylon Guitar, `prog 31` Guitar Harmonics,
`prog 43` Contrabass, `prog 47` Timpani (synth tom substitute),
`prog 52` Choir Aahs, `prog 69` Bassoon, `prog 70` Clarinet.

### 3.3 False positives — instrument is naturally like this (kept)

The metric flagged these, but the measurement reflects real instrument
physics, not a wrong preset:

`prog 9` Glockenspiel (weak fundamental by design),
`prog 21/23` Accordion (reed fundamental dominates),
`prog 32` Acoustic Bass, `prog 44` Tremolo Strings,
`prog 46` Harp, `prog 53` Voice Oohs, `prog 74` Pan Flute,
`prog 75` Blown Bottle, `prog 77` Whistle, `prog 87` New-Age Pad,
`prog 89` Warm Pad.

---

## 4. Result of the re-mapping

The pack was re-rendered with the new mapping table. Four substitutions
produced a clear, measurable improvement:

| prog | Old fund_ratio | New fund_ratio | Old centroid | New centroid | Verdict |
|------|---------------|---------------|--------------|--------------|---------|
| 0 Piano | 0.00 | **0.84** | 1055 Hz | **500 Hz** | ✅ now sounds like an EP / piano |
| 33 Bass Finger | 0.07 | **0.80** | 1993 Hz | **1710 Hz** | ✅ real bass fundamental |
| 38 Synth Bass | (clamped dead) | **0.95** | — | **305 Hz** | ✅ full-range sub bass |
| 74 Recorder | (pure sine) | **0.97** | — | **274 Hz** | ✅ sustained tone, not a test beep |

Four substitutions did **not** move the needle as hoped, because Surge XT's
factory library simply lacks an acoustic sample for those timbres:

| prog | Symptom after re-map | Root cause |
|------|---------------------|-----------|
| 66 Tenor Sax | fund 0.04 (still FM) | No real sax patch in Surge factory |
| 73 Flute | fund 0.04 | No real flute patch in Surge factory |
| 77 Shakuhachi | fund 0.15 | Closest is a sustained synth lead |
| 1–5 Pianos | mixed | No acoustic piano sample in Surge factory |

These are **intrinsic limits** of sourcing every GM instrument from one
synthesizer — see §6.

---

## 5. Validation after re-render

Structural integrity of the regenerated SFZ files:

| Check | Result |
|---|---|
| Programs covered | 128 / 128 |
| Total samples on disk | 1922 (processed) + 1922 (raw) |
| Unique presets | **128 / 128** (was 124 — 4 duplicates resolved) |
| Presets existing in Surge factory | 128 / 128 |
| Regions per SFZ | 1922 × 3 master files |
| Missing sample references | 0 |
| Keyboard coverage 0–127 | 0 gaps, 0 overlaps, 0 range errors |
| `pitch_keycenter` within MIDI 0–127 | 1922 / 1922 |
| `processed` ↔ `raw` directory sync | identical file sets |

---

## 6. Residual limitation: synthesizer vs. acoustic GM

The GM standard describes **acoustic** instruments (Grand Piano, Tenor Sax,
Flute, Shakuhachi, …). Surge XT is a synthesizer — its factory patches are
**emulations** of those instruments built from oscillators and filters, with
no sampled content. For most GM slots a good emulation exists (organs,
synth pads, synth leads, electric pianos, basses). For a handful — chiefly
**acoustic piano, real sax, real flute, shakuhachi** — the factory library
has no patch that fools the ear.

Three options to close this gap:

1. **Accept the synth timbre.** Cheapest; the slots still produce a
   musically-correct pitch and a defensible approximation of the instrument.
2. **Source those few slots from a sample library** (e.g. KSHMR Vol.5 wind
   one-shots already used for the drum kit, or a third-party GM SFZ for the
   piano). Hybrid: Surge for 120 slots, sampled for the 4–6 hardest.
3. **Layer** a sampled body under the synth patch for the worst slots.

The current pack ships option 1 — every slot is a Surge XT patch — with the
re-mapping above applied so that the *available* Surge patches are used in
the slots where they fit best.

---

## 7. How to re-run the audit

The audit is a standalone spectral sweep over `General_MIDI_samples_raw/`.
Skeleton:

```python
import numpy as np, soundfile as sf, os
from scipy.signal import find_peaks

def profile(path):
    a, sr = sf.read(path)
    mono = a.mean(1) if a.ndim > 1 else a
    if np.max(np.abs(mono)) < 1e-4: return None
    seg = mono[int(sr*0.3):int(sr*0.3)+int(sr*0.5)]
    seg = (seg - seg.mean()) * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg)); fr = np.fft.rfftfreq(len(seg), 1/sr)
    v = (fr > 20) & (fr < 12000); sm = spec * v
    peaks, _ = find_peaks(sm, height=sm.max()*0.05)
    if len(peaks) == 0: return None
    f0 = fr[peaks[0]]
    harm = [np.max(spec[max(0,np.argmin(np.abs(fr-f0*n))-2):np.argmin(np.abs(fr-f0*n))+3])
            for n in range(1, 11)]
    fund = harm[0]
    return {
        "fund_ratio": fund / (sum(harm) + 1e-9),
        "centroid":   np.sum(fr[v]*spec[v]) / (np.sum(spec[v]) + 1e-9),
        "h2": harm[1] / fund, "h3": harm[2] / fund,
    }

for prog in range(128):
    r = profile(f"General_MIDI_samples_raw/gm_{prog:03d}_C4_v127.wav")
    print(prog, r)
```

Compare each program's `fund_ratio` / `centroid` against the family envelope
in §2 to flag new mismatches after any future re-mapping.

---

## File reference

| File | Role |
|---|---|
| `sample_gm_pack.py` (`build_preset_mapping`) | The 128-slot Surge preset table — the single source of truth for which preset each GM program uses |
| `General_MIDI_samples_raw/` | Dry renders (input to the audit) |
| `General_MIDI_samples/` | VST-processed renders (what sfizz plays) |
| `General_MIDI_sfizz_processed.sfz` | Master SFZ referenced by Birka |
| `samples_pitch.md` | Companion doc: pitch detection & key-zone mapping |
| `GM.md` | Companion doc: pack overview & rendering pipeline |
