# Zenology Pro — Preset Format Notes (Verified)

## Source: Official Roland Documentation

> Roland EXZ format verified against official Roland support articles,
> benis.it technical blog, and Roland Cloud documentation.

## What EXZ Actually Is

**EXZ = Roland Wave Expansion** for the **ZEN-Core sound engine**.

Not just "parameter presets" — each `.exz` is a **waveform expansion pack**
containing:

1. **New raw audio waveforms** (samples / multisamples)
2. **Synth parameter settings** (the "tone" / preset data using those waveforms)
3. **A 48-byte embedded user license** tied to your Roland Cloud account

This is fundamentally different from Surge XT's `.fxp` (patch = parameters
pointing at built-in oscillators).  Zenology EXZ presets ship **their own
samples** inside the file.

## Dual-Format Encoding (Official)

Every modern EXZ packs **two versions** of the same multisamples:

| Format | Description | Target hardware |
|---|---|---|
| 16-bit linear PCM | Uncompressed, full quality | Fantom, high-end models |
| FCE-DPCM | Roland proprietary compressed | Jupiter-X, Fantom-0, RD-88, etc. |

The hardware auto-selects based on available user flash memory.

## 48-Byte License Layer

- Roland Cloud Manager **embeds a unique encrypted 48-byte license** inside
  each `.exz` at download time.
- Hardware checks this license on import: "Incorrect License!" error if the
  account doesn't match.
- The `.fzi` collection pointers in `~/Library/Application Support/Roland
  Cloud/ZENOLOGY/` are **download receipts**, not the actual data.

## File Structure (Reconstructed)

```
Offset 0x00:  VEXP`          magic (4 bytes, ASCII)
Offset 0x04:  0x60           fixed header size
Offset 0x08:  0x02           format version
Offset 0x0A:  0x00..0x08     subtype / hardware target flags
Offset 0x10:  *EXM001        encoded preset ID + filename area (16 bytes)
Offset 0x20:  JUPITER-8      ASCII preset name (16 bytes, space-padded)
Offset 0x30:  24 bytes       checksum / metadata trailer
Offset 0x40:  0x60 0x00 0x00 0x00 0x80 0x00 0x00 0x00   offset table (see below)
Offset 0x48:  ...
Offset 0x50:  ...
Offset 0x58:  ...             first data section offset / size pointers
Offset 0x60+:  BLOB           first data section (often Roland-compressed, 0x78 0x9c zlib not always present)
Offset 0x70+:  layout struct  4× uint32 repetition pattern (see below)
```

### Offset 0x40 area (8-byte pairs = offset/size tables)

```
0x40:  00000000  60000000    → offset=0x60, size=varied
0x48:  80000000  <size>      → second section offset=0x80
0x50:  01000000  e0000000    → third section offset=0x100, size=0xe0?
0x58:  <offset>  <size>      → fourth data section
```

### Offset 0x70 area (repeating 8-byte pattern)

```
EXM001: 02 01 02 01 02 01 02  00 × 9
EXM002: c0 00 c0 00 c0 00 40  00 × 9
EXM003: 10 80 10 80 10 80 10  00 × 9
EXM004: 80 02 80 02 80 02 80  00 × 9
EXM005: c0 00 c0 00 c0 00 40  00 × 9
```

Repetition counts correlate with hardware variant. `02 01 ...` for EXM001
(4 repeats) vs `c0 00 ...` for multi-section PRST packs.

## EXZ vs SDZ Comparison (Official)

| Feature | `.exz` Wave Expansion | `.sdz` Sound Pack |
|---|---|---|
| Contains | Raw waveform samples + tone params | Synth params only (no samples) |
| USB install location | **Root directory** | `/ROLAND/SOUND/` subfolder |
| Memory impact | Consumes user wave flash | High tone count, minimal wave mem |
| Same tone can live in | Both (EXZ provides the samples) | SDZ only (params referencing existing waves) |
| License per file | Yes — 48-byte account-bound blob | No |
| Zenology source | Both (VST3 bundle `.exz` + user `.fzi` collection) | VST3 bundle `.sdz` only |

## Why Headless Loading Fails

`.exz` is a **compound archive**:

1. Roland FCE-DPCM compressed multisample blobs (proprietary codec)
2. ZEN-Core parameter block (the actual preset)
3. 48-byte encrypted license
4. Per-hardware variant selection data

**No public specification exists** for the internal block layout, parameter
offset map, or FCE-DPCM codec.  `dawdreamer` `load_vst3_preset()` only accepts
standard VST3 `.vstpreset` (XML chunk format) and rejects `.exz` outright.

## What Works in DawDreamer

```python
import dawdreamer as daw

engine = daw.RenderEngine(44100, 512)
synth  = engine.make_plugin_processor(
    "zen", "/Library/Audio/Plug-Ins/VST3/Roland/ZENOLOGY.vst3")
engine.load_graph([(synth, [])])

# 301 parameters, float 0.0–1.0 — READ + WRITE works perfectly
print(synth.get_plugin_parameter_size())        # → 301
synth.set_parameter(0, 0.5)                     # write
synth.get_parameter(0)                          # read  → 0.5

# Full snapshot
patch = synth.get_patch()   # [(0, val), (1, val), ... (300, val)]
synth.set_patch(patch)      # restore

# Save/load disk blob (DawDreamer internal format, not .exz)
synth.save_state("capture.bin")
synth.load_state("capture.bin")
```

## Preset Locations on This Machine

| Type | Path |
|---|---|
| User collection pointers | `~/Library/Application Support/Roland Cloud/ZENOLOGY/*.fzi` |
| User EXZ payload dirs | `~/Library/Application Support/Roland Cloud/ZENOLOGY/EXM*_*/` |
| VST3 factory EXZ | `/Library/Audio/Plug-Ins/VST3/Roland/ZENOLOGY.vst3/Contents/Resources/Patch/PRST_*.exz` |
| VST3 factory SDZ | `/Library/Audio/Plug-Ins/VST3/Roland/ZENOLOGY.vst3/Contents/Resources/Patch/PRST_*.sdz` |
| Zenology presets list | `zenology_presets.json` (in this project root) |

## Available Presets (from .fzi + .exz)

### EXM Series — Emulation Packs (5 installs)
EXM001 JUPITER-8 · EXM002 JUNO-106 · EXM003 JX-8P · EXM004 SH-101 · EXM005 JD-800

### EXZ001–EXZ015 — Wave Expansions
Stage Piano 1/2 · Session Drums · Power Drums · Studio Sounds ·
World Instruments · Orchestra · Vintage Keys · Symphonique Str ·
Big Brass Ens · Classic EPs · Dance Trax · Concert Grand Pno ·
Complete Piano · Vintage Synth

### ZEZ001–ZEZ009 — zen narrative series
Hazy Pop · Dark Adaptations · Liquid · Dub Tech · Light Echoes ·
Cosmic Horizon · Electric Film · Retro Modular · Lifted Soul

### PRST_A–G, H–L — Factory Preset Banks
Factory Presets · AX Collection · Synth Legend · Basic Synth ·
XV Collection · Essential · Essential Drum · Stellar Black ·
Sun Gate · Nebulous Forms · Volatile Memories · Essential 2

### M01–M05 — Patch-Manual Series
M01S01–04 JP-8 patches · M02S01–02 JU-106 patches ·
M03S01–05 JX-8P patches · M04S01 SH-101 patches ·
M05S01–03 JD-800 patches

### SDZ001–SDZ135 — Zen Narrative / Downloadable Content
~135 individual presets covering keys, synths, drums, FX, bass, etc.

### User Presets
`User.fzi` — user-saved custom presets

## Workaround: JSON Parameter Snapshots

Since `.exz` cannot be parsed headlessly, the only viable automation path:

```python
# dump_zenology_preset.py — run once per preset WITH GUI OPEN
import dawdreamer as daw
engine = daw.RenderEngine(44100, 512)
synth = engine.make_plugin_processor("zen", ZENOLOGY_PATH)
engine.load_graph([(synth, [])])
# load preset via GUI in Zenology, then:
patch = synth.get_patch()
import json
json.dump([{"index": i, "value": float(v)} for i, v in patch],
          open("zen_patches/JUPITER_8.json", "w"))

# sample_zenology_pack.py — headless render
synth.set_patch(json.load(open("zen_patches/JUPITER_8.json")))
# ... render notes as usual
```

Caveat: **No multisamples inside EXZ are extracted.**  Zenology uses its
internal sample ROM (or loaded EXZ waveforms) to synthesize audio; `set_patch()`
restores only the parameter state.  Whether a given preset produces audible
audio in init mode depends entirely on whether Zenology's internal rom
has compatible waveforms loaded for that tone type.
