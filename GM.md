# General MIDI (GM) 128 Instrument SFZ Pack

This document details the task of generating a full General MIDI (128 instruments) pack in SFZ format on macOS.

## 1. Overview & Objective
The goal is to produce a high-compatibility, lightweight, and authentic General MIDI (128 instruments) sample library in SFZ format. 
Each instrument is sampled at 4 pitch levels across the keyboard range (C2, C4, C6, C8 / MIDI 36, 60, 84, 108) with high-quality 24-bit stereo `.wav` files at 96 kHz.

---

## 2. Sound Engine: Surge XT
The pack is sampled from **Surge XT** (`/Library/Audio/Plug-Ins/VST3/Surge XT.vst3`), an open-source subtractive/wavetable synthesizer with a large factory patch library.

Each of the 128 GM program slots is bound to a **single, hand-picked factory preset** via an explicit mapping table in `sample_gm_pack.py` (`build_preset_mapping`). The mapping is:
* **Deterministic** — no fuzzy matching or "first unused" fallbacks; every slot maps to a specific preset path.
* **Unique** — all 128 presets are distinct (zero duplicates).
* **Validated** — a missing or renamed preset raises `FileNotFoundError` at load time instead of silently degrading the pack.
* **Documented** — each slot carries a comment with its GM instrument name.

Presets are loaded by copying each mapped factory patch into Surge XT's user patch library (`~/Documents/Surge XT/Patches/MIDI Programs`) as program slot `i`, then switching the active patch with a MIDI `program_change` event. The script backs up any existing user presets before the run and restores them afterwards, so the user's library is left untouched.

> Note: `synth.load_state(preset_path)` does NOT reliably switch the active patch through DawDreamer (the spectral output stays identical regardless of the preset). The MIDI program_change path is required for preset switching to actually take effect.

> Note: Surge XT presets are subtractive/wavetable approximations of acoustic instruments, so the timbres are synthetic-sounding rather than recorded samples. This is a deliberate trade-off for a self-contained, reproducible, cross-platform engine.

---

## 3. How the Sampling Script Works
The script [sample_gm_pack.py](file:///Volumes/External/Code/VST2SFZ/sample_gm_pack.py) automates the process using `DawDreamer`:

1. **Host Setup:** Loads the Surge XT VST3 inside a DawDreamer render engine at 96 kHz.
2. **Preset Selection:** For each of the 128 GM instruments:
   * Looks up the bound factory preset from the explicit mapping table.
   * Copies it into Surge XT's user patch library as program slot `i`.
   * Switches the active patch with a MIDI `program_change` event (1.5 s settle render).
3. **Note Sampling:** Renders notes C2, C4, C6, and C8 at a velocity of 100:
   * Duration: 1.0 second hold, 0.5 seconds release (1.5 seconds total).
   * **Format:** Saves the audio as a standard 24-bit stereo PCM WAV file at 96 kHz.
4. **SFZ Mapping:** 
   * Generates individual `.sfz` files for each instrument under [General_MIDI_instruments/](file:///Volumes/External/Code/VST2SFZ/General_MIDI_instruments/).
   * Appends the regions mapped by key range to the master [General_MIDI.sfz](file:///Volumes/External/Code/VST2SFZ/General_MIDI.sfz) file, using `prg_num` to select the patch in multi-timbral samplers.

---

## 4. How to Run the Script
To run the sampling process and generate/overwrite the instrument files using Surge XT:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python sample_gm_pack.py
```

### Resulting Structure
* [General_MIDI.sfz](file:///Volumes/External/Code/VST2SFZ/General_MIDI.sfz) — The master SFZ file (maps all 128 programs via `prg_num`).
* [General_MIDI_instruments/](file:///Volumes/External/Code/VST2SFZ/General_MIDI_instruments/) — 128 individual `.sfz` instrument files (e.g. `gm_000_acoustic_grand_piano.sfz`).
* [General_MIDI_samples/](file:///Volumes/External/Code/VST2SFZ/General_MIDI_samples/) — 512 `.wav` samples (4 notes per instrument) rendered in stereo.

---

## 5. Build Steps (Quick Reference)
End-to-end pipeline to (re)generate the pack from scratch:

1. **Verify environment** — the dedicated conda env with `dawdreamer`, `mido`, `soundfile`, `numpy`:
   ```bash
   /opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python -c "import dawdreamer, mido, soundfile, numpy; print('OK')"
   ```
2. **Verify sound source** — Apple DLSMusicDevice must be present:
   ```bash
   ls /System/Library/Components/CoreAudio.component
   ```
3. **Render samples + build SFZ** (single command does everything — WAVs, individual SFZs, and the master `General_MIDI.sfz`):
   ```bash
   /opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python sample_gm_pack.py
   ```
4. **Verify output** — expect 512 WAVs, 128 instrument SFZs, and a master SFZ with all 128 programs:
   ```bash
   ls General_MIDI_samples/*.wav | wc -l     # → 512
   ls General_MIDI_instruments/*.sfz | wc -l # → 128
   grep -c "prg_num=" General_MIDI.sfz       # → 128
   ```

### Build Artifacts
Running `sample_gm_pack.py` produces three coordinated outputs in one pass:

| Artifact | Count | Description |
|----------|------:|-------------|
| `General_MIDI.sfz` | 1 | Master file — 128 `<group>` blocks, each with `prg_num=i` and 4 key-zoned `<region>`s |
| `General_MIDI_instruments/gm_###_*.sfz` | 128 | One SFZ per instrument (standalone loadable, `default_path=../General_MIDI_samples/`) |
| `General_MIDI_samples/gm_###_*.wav` | 512 | 4 notes (C2/C4/C6/C8) per instrument, 24-bit stereo PCM, 96 kHz, 1.5s |

### Sample naming convention
```
gm_{program:03d}_{note}.wav
gm_000_C2.wav  ← Program 0 (Acoustic Grand Piano), C2
gm_073_C4.wav  ← Program 73 (Flute), C4
```

### SFZ region mapping (per instrument)
Each instrument spans the full keyboard 0–127, split at the midpoints between sample pitches:

| Sample | `pitch_keycenter` | `lokey`–`hikey` |
|--------|------------------:|-----------------|
| C2 | 36 | 0–48 |
| C4 | 60 | 49–72 |
| C6 | 84 | 73–96 |
| C8 | 108 | 97–127 |

### Known limitation
`gm_047_C8.wav` (Timpani, MIDI 108 / ~4186 Hz) renders as near-silence — Roland Sound Canvas timpani samples do not cover that pitch range. The corresponding SFZ region (`lokey=97 hikey=127`) will be effectively silent for program 47.

---

## 6. Previewing
To quickly audition instruments, concatenate a subset of C4 WAVs and play:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python - <<'PY'
import soundfile as sf, numpy as np
sr = 44100; gap = int(sr*0.30); chunks = []
for i in range(16):
    a, _ = sf.read(f"General_MIDI_samples/gm_{i:03d}_C4.wav")
    chunks += [a, np.zeros((gap, 2))]
out = np.concatenate(chunks)
sf.write("preview_first_16_C4.wav", out.astype(np.float32), sr, subtype='PCM_16')
PY
afplay preview_first_16_C4.wav
```
