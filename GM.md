# General MIDI (GM) 128 Instrument SFZ Pack

This document details the task of generating a full General MIDI (128 instruments) pack in SFZ format on macOS.

## 1. Overview & Objective
The goal is to produce a high-compatibility, lightweight, and authentic General MIDI (128 instruments) sample library in SFZ format. 
Each instrument is sampled at 4 pitch levels across the keyboard range (C2, C4, C6, C8 / MIDI 36, 60, 84, 108) with high-quality 24-bit stereo `.wav` files at 96 kHz.

---

## 2. Why Surge XT Presets Sounded Synthetic
In initial attempts, we sampled the **Surge XT** synthesizer. However:
* Surge XT is a subtractive/wavetable synthesizer.
* Even though it has named factory presets (like "Violin", "Clarinet", "Nylon Guitar"), these are physical-modeling or subtractive approximations.
* Consequently, they sound like "ordinary synth bleeps/waves" rather than realistic acoustic instruments.

---

## 3. The Solution: Apple DLSMusicDevice
To get actual acoustic instruments (pianos, strings, woodwinds, brass), we switched the sampler engine to macOS's built-in **Apple DLSMusicDevice**:
* **Location:** Located inside `/System/Library/Components/CoreAudio.component`.
* **Sound Source:** Hosts Apple's system DLS sound bank (Roland Sound Canvas GS/GM samples).
* **Authenticity:** Provides genuine acoustic recorded instrument samples.
* **Compatibility:** Natively processes standard MIDI Program Change messages (0–127) to switch between the 128 GM instruments.

---

## 4. How the Sampling Script Works
The script [sample_gm_pack.py](file:///Volumes/External/Code/VST2SFZ/sample_gm_pack.py) automates the process using `DawDreamer` and `mido`:

1. **Host Setup:** Loads the DLSMusicDevice Audio Unit inside a DawDreamer render engine.
2. **Program Selection:** For each of the 128 GM instruments:
   * Generates a temporary MIDI file containing a `program_change` message for the program `i`.
   * Loads and renders the program change event to switch the active instrument.
3. **Note Sampling:** Renders notes C2, C4, C6, and C8 at a velocity of 100:
   * Duration: 1.0 second hold, 0.5 seconds release (1.5 seconds total).
   * **Stereo Slicing:** Slices the output of the plugin to the first 2 channels (`audio[:2]`) because DLSMusicDevice outputs 4 channels by default (with the last 2 being empty).
   * **Format:** Saves the audio as a standard 24-bit stereo PCM WAV file at 96 kHz.
4. **SFZ Mapping:** 
   * Generates individual `.sfz` files for each instrument under [General_MIDI_instruments/](file:///Volumes/External/Code/VST2SFZ/General_MIDI_instruments/).
   * Appends the regions mapped by key range to the master [General_MIDI.sfz](file:///Volumes/External/Code/VST2SFZ/General_MIDI.sfz) file, using `prg_num` to select the patch in multi-timbral samplers.

---

## 5. How to Run the Script
To run the sampling process and generate/overwrite the instrument files using the DLSMusicDevice:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/vst2sfz/bin/python sample_gm_pack.py
```

### Resulting Structure
* [General_MIDI.sfz](file:///Volumes/External/Code/VST2SFZ/General_MIDI.sfz) — The master SFZ file (maps all 128 programs via `prg_num`).
* [General_MIDI_instruments/](file:///Volumes/External/Code/VST2SFZ/General_MIDI_instruments/) — 128 individual `.sfz` instrument files (e.g. `gm_000_acoustic_grand_piano.sfz`).
* [General_MIDI_samples/](file:///Volumes/External/Code/VST2SFZ/General_MIDI_samples/) — 512 `.wav` samples (4 notes per instrument) rendered in stereo.

---

## 6. Build Steps (Quick Reference)
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

## 7. Previewing
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
