# Zenology Pro — Preset Format Notes

## Overview

Roland Zenology Pro stores presets in several proprietary formats. The only
reliable headless path via DawDreamer is **JSON parameter snapshots** produced
by `dump_zenology_preset.py`.

## File Formats

### `.fzi` — Roland Cloud Collection Pointer

- **Size:** always 864 bytes
- **Structure:**
  ```
  Offset 0x00:  KoaFziFile00001 PG-ZNLGY    (ASCII header, 32 bytes)
  Offset 0x20:  0x00 × (rest of file)       (all null bytes)
  ```
- **Contents:** NONE — pure metadata pointer, no preset data embedded.
- **Role:** Indicates user has "purchased / downloaded" a preset pack via
  Roland Cloud. The actual preset payload lives elsewhere.
- **DawDreamer:** `load_vst3_preset()` rejects it (`RuntimeError: extension is
  not .vstpreset`). Cannot be loaded headlessly.

### `.exz` — Roland VEXP Preset Payload

- **Size:** varies (QU002 ≈ 191 KB up to PRST_D ≈ 1.9 MB)
- **Header (16 bytes):**
  ```
  56 45 58 50 60 00 00 00  08 02 00 00  04 00 00 00
  "VEXP\`"   ...version?    ...flags?   ...data offset
  ```
- **Naming convention encodes the preset ID:**
  - `EXM001` / `EXZ001` / `PRST_A` / `SDZ001` / `M01S04` / `ZEZ001`
  - Found both **inside** the VST3 bundle (read-only) and in the user Library.
- **Some files contain plaintext strings (preset name, tone name).**
- **Many are zlib-compressed** (`0x78 0x9c` signature at offset 0x60 in
  `Initial.exz`); the actual parameters are in the compressed blob.
- **Parameter mapping is NOT documented publicly.** Unknown byte offsets,
  types, normalization, and block sizes.
- **DawDreamer:** `load_vst3_preset()` and `load_preset()` both return `False`
  / raise `RuntimeError`. Cannot reverse-engineer reliably without Roland spec.

### `.sdz` — Alternative Roland Preset Container

- Same naming convention as `.exz` (PRST_H–L, user packs).
- Binary content; likely a related Rowan archive format.
- Treated identically to `.exz` for our purposes: **not loadable headlessly**.

### `User.bin` — Internal User Patch Storage

- **Location:** inside the VST3 bundle:
  `/Library/Audio/Plug-Ins/VST3/Roland/ZENOLOGY.vst3/Contents/Resources/Patch/User.bin`
- **Header:** `56 5A 61 01 00`  then `RC001` then `EXTaZCOR 200`
  (appears to be a Roland ZIP-compressed binary archive)
- Contains user-saved presets + zlib-compressed blobs.
- Not directly parseable without reverse-engineering.

### `.vstpreset` — Standard VST3 Preset (NOT used by Zenology)

- Standard format (XML-based chunk inside a binary container).
- No `.vstpreset` files were found anywhere on disk for Zenology Pro.
- `dawdreamer.PluginProcessor.load_vst3_preset()` strictly requires this
  extension and **will refuse** `.fzi` / `.exz` files.

## What DawDreamer CAN Do

```python
import dawdreamer as daw

engine = daw.RenderEngine(44100, 512)
synth  = engine.make_plugin_processor("zen",
    "/Library/Audio/Plug-Ins/VST3/Roland/ZENOLOGY.vst3")
engine.load_graph([(synth, [])])

# 301 parameters, all float 0.0–1.0
n = synth.get_plugin_parameter_size()          # → 301
desc = synth.get_plugin_parameters_description()  # [{index, name, min, max, default}, ...]

# Read/write individual params
v = synth.get_parameter(0)     # read LFO RATE
synth.set_parameter(0, 0.5)    # write

# Snapshot / restore full patch
patch = synth.get_patch()      # → [(0, val), (1, val), ... (300, val)]
synth.set_patch(patch)         # restore

# Save to / load from disk (binary blob, format internal to DAWDreamer/Roland)
synth.save_state("patch.bin")
synth.load_state("patch.bin")   # ← works ONLY with DawDreamer's own .bin
```

## Recommended Headless Workflow

### Step 1 — Dump Presets (one-time, requires GUI Zenology)

```bash
# With Zenology open in any DAW / standalone:
python dump_zenology_preset.py --name "JUPITER-8"
python dump_zenology_preset.py --name "JD-800 Cosmic"
# ... one invocation per preset
```

Output: `zen_patches/JUPITER_8.json`, `zen_patches/JD_800_Cosmic.json`, etc.

Format of JSON:
```json
[
  {"index": 0,  "value": 0.0},
  {"index": 1,  "value": 0.5},
  ...
  {"index": 300, "value": 0.25}
]
```

### Step 2 — Render Pack (headless, no GUI needed)

```bash
python sample_zenology_pack.py
# or subset:
python sample_zenology_pack.py --presets "JUPITER-8" "JD-800 Cosmic"
# or skip presets with no dump:
python sample_zenology_pack.py --skip-missing
```

### Step 3 — Use the SFZ

```bash
sfizz zenology_gm.sfz    # directly
# or via the project's renderers/render_sfz_midi.py
python renderers/render_sfz_midi.py --sfz zenology_gm.sfz --midi input.mid --output out.wav
```

## Known Limitations

| Feature | Status |
|---|---|
| Load `.fzi` headlessly | ❌ Not possible — pointer-only format |
| Load `.exz` headlessly | ❌ Proprietary binary, no public spec |
| `get_patch()` / `set_patch()` | ✅ Fully working (301 float params) |
| `save_state()` / `load_state()` | ⚠️ Works only with DawDreamer's own `.bin` format |
| Program-change MIDI | ❌ Does NOT trigger preset switch in headless mode |
| Preset transposition detection | ✅ Same pitch-detection pipeline as `sample_gm_pack.py` |

## Preset Locations on This Machine

- **Roland Cloud library:** `~/Library/Application Support/Roland Cloud/ZENOLOGY/*.fzi`
- **Factory payloads (inside VST3 bundle):** `/Library/Audio/Plug-Ins/VST3/Roland/ZENOLOGY.vst3/Contents/Resources/Patch/*.exz *.sdz`
- **Per-preset subdirs:** `~/Library/Application Support/Roland Cloud/ZENOLOGY/EXM*_*/`  → `.exz` + `.png` + PDF sound list
