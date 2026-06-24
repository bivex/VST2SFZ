#!/usr/bin/env python3
"""
dump_zenology_preset.py

Capture the active Zenology preset as a JSON parameter snapshot.

Workflow
--------
1. Open Zenology in your DAW / standalone.
2. Load the preset you want to capture.
3. Run:

       python dump_zenology_preset.py --name "JUPITER-8"

   Outputs:  zen_patches/JUPITER_8.json

4. sample_zenology_pack.py will automatically load that file headlessly.
"""

import argparse
import json
import os

import dawdreamer as daw

DEFAULT_VST = "/Library/Audio/Plug-Ins/VST3/Roland/ZENOLOGY.vst3"
OUT_DIR = "zen_patches"


def dump(vst_path: str, name: str, out_path: str) -> None:
    engine = daw.RenderEngine(44100, 512)
    synth = engine.make_plugin_processor("zen", vst_path)
    engine.load_graph([(synth, [])])

    print(f"Capturing preset: {name}")
    print(f"  plugin  : {synth.get_name()}")
    print(f"  n params: {synth.get_plugin_parameter_size()}")

    patch = synth.get_patch()  # [(index, value), ...]
    data = [{"index": int(i), "value": float(v)} for i, v in patch]

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  saved   : {out_path}  ({len(data)} parameters)")


def main():
    parser = argparse.ArgumentParser(description="Dump Zenology preset → JSON")
    parser.add_argument(
        "--name", required=True, help="Preset name (also used for output filename)"
    )
    parser.add_argument("--vst", default=DEFAULT_VST, help="Path to ZENOLOGY.vst3")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    safe = args.name.replace("/", "_").replace(" ", "_")
    out_path = os.path.join(args.out_dir, f"{safe}.json")
    dump(args.vst, args.name, out_path)


if __name__ == "__main__":
    main()
