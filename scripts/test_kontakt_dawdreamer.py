#!/usr/bin/env python3
"""
Headless-невозможный тест: загрузить .nki в Kontakt через DawDreamer.

.nki — внутренний формат Kontakt, НЕ VST3-preset. Kontakt не экспонирует
загрузку инструмента через VST3-параметры (только CC-mapping'и). Поэтому
скрипт открывает GUI Kontakt; ты вручную открываешь .nki через браузер
Files внутри Kontakt, возвращаешься в терминал и жмёшь Enter — скрипт
рендерит звук и сообщает, есть ли сигнал.

Usage: source /tmp/dd_venv/bin/activate && python3 test_kontakt_dawdreamer.py
"""
import numpy as np
import soundfile as sf
import dawdreamer as daw
import sys

NKI_HINT = ("/Volumes/External/Samples/KONTAKT/SOUNDSSSS/AmoreGrandPiano/"
            "Amore Grand Piano v2.nki")
VST3 = "/Library/Audio/Plug-Ins/VST3/Kontakt 8.vst3"
OUT_WAV = "/tmp/kontakt_test.wav"

SR = 44100
BLOCK = 512

def main():
    re = daw.RenderEngine(SR, BLOCK)
    re.set_bpm(120)
    k = re.make_plugin_processor("kontakt", VST3)
    print(f"[ok] loaded plugin: {k.get_name()}, out channels: {k.get_num_output_channels()}")
    try:
        k.enable_all_buses()
    except Exception as e:
        print("[warn] enable_all_buses:", e)

    # Open GUI
    print("\n=== Opening Kontakt GUI ===")
    print("1. In the Kontakt window, click Files (disk icon) -> browse to:")
    print(f"   {NKI_HINT}")
    print("2. Double-click the .nki to load it as an instrument.")
    print("3. Make sure it lands in the rack (slot 1, MIDI ch 1).")
    print("4. Come back HERE and press Enter.")
    try:
        k.open_editor()
    except Exception as e:
        print("[warn] open_editor threw:", e)
        print("       (continuing — if GUI already open, proceed)")

    input("\n>>> After loading the .nki in Kontakt, press Enter to render... ")

    # Feed a C-major triad: C4(60) E4(64) G4(67), velocity 100, 0.5s in, 3s long
    k.clear_midi()
    for note in (60, 64, 67):
        k.add_midi_note(note, 100, 0.5, 3.0)

    re.load_graph([(k, [])])
    print("rendering 5s ...")
    re.render(5.0)
    audio = re.get_audio()  # shape (num_out_ch, frames)
    audio = np.asarray(audio)
    main = audio[:2]  # stereo out 1/2
    peak = float(np.max(np.abs(main))) if main.size else 0.0
    rms = float(np.sqrt(np.mean(main**2))) if main.size else 0.0

    # save
    sf.write(OUT_WAV, main.T, SR)
    print(f"\n=== RESULT ===")
    print(f"peak={peak:.6f}  rms={rms:.6f}")
    print(f"wrote {OUT_WAV} ({main.shape[1]} frames stereo)")
    if peak < 1e-5:
        print(">>> SILENT — instrument did not load or no MIDI reached it.")
        sys.exit(1)
    else:
        print(">>> HAS SIGNAL — Kontakt produced audio from the .nki. ✓")
        sys.exit(0)

if __name__ == "__main__":
    main()
