# General MIDI (GM) 128 Instrument SFZ Pack

This document details the task of generating a full General MIDI (128 instruments) pack in SFZ format on macOS.

## 1. Overview & Objective
The goal is to produce a high-compatibility, high-quality, and authentic General MIDI (128 instruments) sample library in SFZ format.
Each instrument is sampled at **every single one of the 128 MIDI notes** (from MIDI 0 to 127) and **2 velocity layers**:
* **Soft:** velocity = 64 (ranges 0-80)
* **Hard:** velocity = 127 (ranges 81-127)

This matrix results in **32,768 high-quality 24-bit stereo `.wav` files** at 96 kHz, producing completely authentic, transposition-free responses with zero pitch-stretching artifacts.

---

## 2. Sound Engine: Surge XT
The pack is sampled from **Surge XT** (`/Library/Audio/Plug-Ins/VST3/Surge XT.vst3`), an open-source subtractive/wavetable synthesizer with a large factory patch library.

Each of the 128 GM program slots is bound to a **single, hand-picked factory preset** via an explicit mapping table in `sample_gm_pack.py` (`build_preset_mapping`). The mapping is:
* **Deterministic** — no fuzzy matching; every slot maps to a specific preset path.
* **Unique** — all 128 presets are distinct (zero duplicates).
* **Validated** — a missing preset raises `FileNotFoundError` at load time.
* **Specialized presets** — including `Circus 1.fxp` for Tango Accordion (slot 23) and `Sub 1.fxp` for pure Sub Bass (slot 39).

Presets are loaded by copying each mapped factory patch into Surge XT's user patch library (`~/Documents/Surge XT/Patches/MIDI Programs`) as program slot `i`, then switching the active patch with a MIDI `program_change` event. The script backs up any existing user presets before the run and restores them afterwards.

---

## 3. How the Sampling Script Works
The script [sample_gm_pack.py](file:///Volumes/External/Code/VST2SFZ/sample_gm_pack.py) automates the process using `DawDreamer`:

1. **Host Setup:** Loads the Surge XT VST3 inside a DawDreamer render engine at 96 kHz.
2. **Preset Selection:** Switches the active patch with a MIDI `program_change` event (1.5 s settle render).
3. **Note Sampling:** Renders notes C2, C3, C4, C5, C6, C7, and C8 at velocities 64 and 127:
   * Duration: 1.0 second hold, 0.5 seconds release (1.5 seconds total).
   * **Format:** Saves the audio as a standard 24-bit stereo PCM WAV file at 96 kHz.
4. **SFZ Mapping:**
   * Generates individual `.sfz` files for each instrument under [General_MIDI_instruments/](file:///Volumes/External/Code/VST2SFZ/General_MIDI_instruments/).
   * Generates [General_MIDI.sfz](file:///Volumes/External/Code/VST2SFZ/General_MIDI.sfz) (master file), [General_MIDI_sfizz.sfz](file:///Volumes/External/Code/VST2SFZ/General_MIDI_sfizz.sfz) (sfizz-compatible raw paths), and [General_MIDI_sfizz_processed.sfz](file:///Volumes/External/Code/VST2SFZ/General_MIDI_sfizz_processed.sfz) (sfizz-compatible processed paths).

---

## 4. How to Run the Scripts
To run the sampling process and generate/overwrite the instrument files:
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python sample_gm_pack.py
```

To run the studio post-processing chain (MS stereo widening, tube warmth saturation, RMS normalization, cosine fade-outs):
```bash
/opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python process_samples.py
```

---

## 5. Build Steps & Verification
End-to-end pipeline:

1. **Verify environment**:
   ```bash
   /opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python -c "import dawdreamer, mido, soundfile, numpy, pedalboard; print('OK')"
   ```
2. **Render samples + build SFZ**:
   ```bash
   /opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python sample_gm_pack.py
   ```
3. **Post-process samples**:
   ```bash
   /opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python process_samples.py
   ```

### Build Artifacts

| Artifact | Count | Description |
|----------|------:|-------------|
| `General_MIDI.sfz` | 1 | Master file — 128 `<group>` blocks with `prg_num=i` |
| `General_MIDI_sfizz_processed.sfz` | 1 | Sfizz master file using absolute paths to processed samples |
| `General_MIDI_instruments/gm_###_*.sfz` | 128 | Individual standalone SFZs |
| `General_MIDI_samples/gm_###_*.wav` | 32,768 | 24-bit stereo PCM, 96 kHz, 1.5s, post-processed |

### Sample naming convention
```
gm_{program:03d}_{note_name}_v{velocity}.wav
gm_000_C-1_v64.wav   ← Program 0 (Piano), C-1, Soft
gm_000_G9_v127.wav   ← Program 0 (Piano), G9, Hard
```

### SFZ region mapping (per instrument)
Each instrument spans the full keyboard 0–127, with a dedicated region for every single MIDI note (transposition-free):

| Sample | MIDI Note | `lokey`–`hikey` | Velocity Layer | `lovel`–`hivel` |
|--------|----------:|-----------------|----------------|----------------:|
| `gm_###_{note_name}_v64.wav` | `note` | `note`–`note` | Soft | 0–80 |
| `gm_###_{note_name}_v127.wav` | `note` | `note`–`note` | Hard | 81–127 |

---

## 6. Sizing & Scaling Analysis
When deciding how many notes to render per instrument, here is the size projection:

| Sampling Density | Total Samples | Pack Size (on disk) | Surge Render Time | Pros/Cons |
|------------------|--------------:|--------------------:|------------------:|-----------|
| **8 key zones** | 2,048 | **1.8 GB** | ~1.2 min | Excellent quality/size ratio. Very minor pitch stretch. |
| **12 key zones** (every 3 st) | 3,072 | **2.5 GB** | ~1.7 min | Negligible pitch stretch. |
| **88 key range** (every key) | 22,528 | **18.1 GB** | ~12 min | Perfect sound across standard piano range. High memory footprint. |
| **128 key range** (current) | 32,768 | **27.6 GB** | ~18 min | **Active.** Zero transposition, complete authenticity. Heavy disk footprint. |
