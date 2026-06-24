#!/usr/bin/env python3
"""
Sequential VST color chain processing for GM samples.

Uses DawDreamer to apply a high-quality production mastering/coloring chain:
  CHOWTape → SDRR2 → spiff → soothe2 → FabFilter Pro-Q 4 → TDR Kotelnikov GE → Fresh Air → TAL-Chorus-LX → FabFilter Pro-R 2 → A1StereoControl → FabFilter Pro-L 2

Runs sequentially in a single thread to prevent CPU overload.
"""

import os
import re
import copy
import sys
import glob
import argparse
import numpy as np
import soundfile as sf
import scipy.signal
import dawdreamer as daw

CHOW_PATH = "/Library/Audio/Plug-Ins/VST3/CHOWTapeModel.vst3"
SDRR_PATH = "/Library/Audio/Plug-Ins/VST3/SDRR2.vst3"
SPIFF_PATH = "/Library/Audio/Plug-Ins/VST3/spiff.vst3"
SOOTHE_PATH = "/Library/Audio/Plug-Ins/VST3/soothe2.vst3"
PRO_Q_PATH = "/Library/Audio/Plug-Ins/VST3/FabFilter Pro-Q 4.vst3"
KOTELNIKOV_GE_PATH = "/Library/Audio/Plug-Ins/VST3/TDR Kotelnikov GE.vst3"
FRESH_AIR_PATH = "/Library/Audio/Plug-Ins/VST3/Fresh Air.vst3"
CHORUS_PATH = "/Library/Audio/Plug-Ins/VST3/TAL-Chorus-LX.vst3"
STEREO_PATH = "/Library/Audio/Plug-Ins/VST3/A1StereoControl.vst3"
PRO_R_PATH = "/Library/Audio/Plug-Ins/VST3/FabFilter Pro-R 2.vst3"
PRO_L_PATH = "/Library/Audio/Plug-Ins/VST3/FabFilter Pro-L 2.vst3"
PRO_MB_PATH = "/Library/Audio/Plug-Ins/VST3/FabFilter Pro-MB.vst3"

SAMPLE_RATE = 96000
BUFFER_SIZE = 512

# ---------------------------------------------------------------------------
# Per-group presets.
# ---------------------------------------------------------------------------


def _preset(
    tape_drive=0.35,
    tape_sat=0.4,
    tape_bass=0.5,
    tape_treble=0.5,
    sdrr_bypass=True,
    sdrr_mode=0.0,
    sdrr_drive=0.20,
    sdrr_mix=0.50,
    spiff_mode=1.0,
    spiff_boost=0.0,
    spiff_cut=0.0,
    spiff_sens=0.5,
    spiff_bypass=True,
    soothe_bypass=True,
    soothe_depth=0.35,
    soothe_sharpness=0.50,
    soothe_selectivity=0.40,
    hp_freq=35.0,
    b1_freq=250.0,
    b1_gain=0.0,
    b1_q=0.5,
    b1_dyn=-2.0,
    b3_freq=3000.0,
    b3_gain=0.0,
    b3_q=0.5,
    b4_freq=10000.0,
    b4_gain=0.0,
    b4_q=0.5,
    rvb_dry=0.88,
    rvb_early=0.08,
    rvb_late=0.04,
    rvb_size=0.167,
    rvb_predelay=0.08,
    rvb_decay=0.03,
    rvb_diffuse=0.7,
    rvb_spin=0.16,
    rvb_hicut=1.0,
    stereo_width=0.50,
    chorus_wet=0.0,
    fresh_mid=0.0,
    fresh_high=0.0,
    mb_bypass=True,
    mb_params=None,
    bypass=False,
):
    return {
        "bypass": bypass,
        "tape": {
            0: 0.889,
            1: 0.5,
            2: 1.0,
            16: tape_drive,
            17: tape_sat,
            18: 0.5,
            8: tape_bass,
            9: tape_treble,
        },
        "sdrr": {
            "bypass": sdrr_bypass,
            "mode": sdrr_mode,
            "drive": sdrr_drive,
            "mix": sdrr_mix,
        },
        "spiff": {
            "bypass": spiff_bypass,
            "mode": spiff_mode,  # 1.0 = boost, 0.0 = cut
            "boost": spiff_boost,
            "cut": spiff_cut,
            "sens": spiff_sens,
        },
        "soothe": {
            "bypass": soothe_bypass,
            "depth": soothe_depth,
            "sharpness": soothe_sharpness,
            "selectivity": soothe_selectivity,
        },
        "eq": {
            "hp_freq": hp_freq,
            "b1_freq": b1_freq,
            "b1_gain": b1_gain,
            "b1_q": b1_q,
            "b1_dyn": b1_dyn,
            "b3_freq": b3_freq,
            "b3_gain": b3_gain,
            "b3_q": b3_q,
            "b4_freq": b4_freq,
            "b4_gain": b4_gain,
            "b4_q": b4_q,
        },
        "reverb": None
        if rvb_dry >= 1.0
        else {
            2: rvb_dry,
            3: rvb_early,
            5: rvb_late,
            6: rvb_size,
            8: rvb_predelay,
            9: rvb_decay,
            10: rvb_diffuse,
            11: rvb_spin,
            13: rvb_hicut,
        },
        "chorus_wet": chorus_wet,
        "stereo": {3: stereo_width, 19: 1.0},  # 3: width, 19: SafeBass ON
        "fresh_air": {
            "bypass": fresh_mid == 0.0 and fresh_high == 0.0,
            "mid": fresh_mid,
            "high": fresh_high,
        },
        "pro_mb": {"bypass": mb_bypass, "params": mb_params or {}},
    }


GROUP_PRESETS = {
    0: _preset(
        tape_drive=0.30,
        tape_sat=0.35,
        tape_treble=0.55,  # Pianos: bright, warm
        sdrr_bypass=False,
        sdrr_mode=3.0,
        sdrr_drive=0.15,
        sdrr_mix=0.25,  # subtle desk saturation
        b4_gain=2.0,
        b4_freq=10000.0,
        rvb_dry=0.85,
        rvb_early=0.10,
        rvb_late=0.05,
        rvb_decay=0.05,
        rvb_size=0.20,
        stereo_width=0.50,
        chorus_wet=0.0,
        fresh_mid=0.08,
        fresh_high=0.12,
    ),
    1: _preset(
        tape_drive=0.15,
        tape_sat=0.20,  # Chrom Perc: clear, bright mallets
        b3_gain=3.0,
        b3_freq=3500.0,
        rvb_dry=0.80,
        rvb_early=0.12,
        rvb_late=0.08,
        rvb_decay=0.10,
        rvb_diffuse=0.8,
        stereo_width=0.55,
        fresh_mid=0.05,
        fresh_high=0.15,
        spiff_mode=1.0,
        spiff_boost=0.15,
        spiff_sens=0.40,
        spiff_bypass=False,
    ),
    2: _preset(
        tape_drive=0.50,
        tape_sat=0.50,
        tape_bass=0.45,  # Organs: warm, rotary motion
        sdrr_bypass=False,
        sdrr_mode=0.0,
        sdrr_drive=0.20,
        sdrr_mix=0.35,  # tube crunch
        b1_gain=-4.5,
        b1_freq=200.0,
        b3_gain=1.5,
        b3_freq=2200.0,
        rvb_dry=0.82,
        rvb_early=0.08,
        rvb_late=0.10,
        rvb_decay=0.12,
        rvb_size=0.30,
        stereo_width=0.60,
        chorus_wet=0.15,
        fresh_mid=0.02,
        fresh_high=0.02,
    ),
    3: _preset(
        tape_drive=0.40,
        tape_sat=0.45,  # Guitars: dense, warm pick attack
        sdrr_bypass=False,
        sdrr_mode=0.0,
        sdrr_drive=0.20,
        sdrr_mix=0.30,  # tube preamp color
        spiff_mode=1.0,
        spiff_boost=0.10,
        spiff_sens=0.40,
        spiff_bypass=False,
        soothe_bypass=False,
        soothe_depth=0.35,
        soothe_sharpness=0.50,  # soothe resonances
        b3_gain=2.0,
        b3_freq=3500.0,
        rvb_dry=0.88,
        rvb_early=0.06,
        rvb_late=0.06,
        rvb_decay=0.04,
        rvb_size=0.15,
        stereo_width=0.55,
        fresh_mid=0.10,
        fresh_high=0.18,
    ),
    4: _preset(
        tape_drive=0.60,
        tape_sat=0.55,
        tape_bass=0.60,  # Bass: powerful, centered low-end
        sdrr_bypass=False,
        sdrr_mode=0.0,
        sdrr_drive=0.40,
        sdrr_mix=0.60,  # fat tube harmonics
        hp_freq=25.0,
        b1_gain=4.5,
        b1_freq=50.0,
        b1_dyn=0.0,
        b3_gain=-2.0,
        b3_freq=1000.0,
        rvb_dry=1.0,
        stereo_width=0.50,
        fresh_mid=0.0,
        fresh_high=0.0,
        mb_bypass=False,
        mb_params={
            # Band 1 (Low: 20Hz - 120Hz) — State must be 0.25..0.5 = Enabled
            0: 0.5,         # State = Enabled (was 1.0 = Unused)
            1: 0.0,         # Low Crossover = 30 Hz
            3: 0.30,        # High Crossover ≈ 120 Hz: log(120/30)/log(1000) ≈ 0.20 -> use 0.30 (~240Hz)
            6: 0.40,        # Threshold: (db+60)/60 -> 0.40 ≈ -36 dB (catch low-end transients)
            7: 0.45,        # Range: (r+30)/60 -> -3 dB max gain reduction
            8: 0.40,        # Ratio: power-law, 0.40 = 2:1
            22: 0.5,        # Band 2 State = Enabled (was 1.0 = Unused)
            23: 0.530,      # Band 2 Low Crossover ≈ 1000 Hz: log(1000/30)/log(1000)
            25: 0.833,      # Band 2 Threshold: (db+60)/60 -> -10 dB
            29: 0.45,       # Band 2 Range: -3 dB max GR
            30: 0.40,       # Band 2 Ratio: 2:1 (power-law)
        },
    ),
    5: _preset(
        tape_drive=0.20,
        tape_sat=0.25,  # Strings: wide, spacious orchestra
        sdrr_bypass=False,
        sdrr_mode=3.0,
        sdrr_drive=0.10,
        sdrr_mix=0.20,  # desk console feel
        soothe_bypass=False,
        soothe_depth=0.40,
        soothe_sharpness=0.45,  # smooth strings bowing
        b3_gain=2.0,
        b3_freq=3500.0,
        rvb_dry=0.75,
        rvb_early=0.10,
        rvb_late=0.15,
        rvb_decay=0.18,
        rvb_size=0.40,
        rvb_diffuse=0.85,
        stereo_width=0.70,
        fresh_mid=0.05,
        fresh_high=0.10,
    ),
    6: _preset(
        tape_drive=0.15,
        tape_sat=0.20,  # Ensemble: voluminous, huge field
        sdrr_bypass=False,
        sdrr_mode=3.0,
        sdrr_drive=0.10,
        sdrr_mix=0.20,
        soothe_bypass=False,
        soothe_depth=0.40,
        soothe_sharpness=0.45,
        b4_gain=3.0,
        b4_freq=12000.0,
        rvb_dry=0.70,
        rvb_early=0.12,
        rvb_late=0.18,
        rvb_decay=0.25,
        rvb_size=0.45,
        rvb_diffuse=0.9,
        stereo_width=0.75,
        fresh_mid=0.04,
        fresh_high=0.08,
    ),
    7: _preset(
        tape_drive=0.45,
        tape_sat=0.50,  # Brass: bright, powerful
        sdrr_bypass=False,
        sdrr_mode=3.0,
        sdrr_drive=0.15,
        sdrr_mix=0.20,
        soothe_bypass=False,
        soothe_depth=0.45,
        soothe_sharpness=0.55,  # suppress brass harshness
        b3_gain=3.0,
        b3_freq=3000.0,
        rvb_dry=0.82,
        rvb_early=0.10,
        rvb_late=0.08,
        rvb_decay=0.10,
        rvb_size=0.25,
        stereo_width=0.60,
        fresh_mid=0.03,
        fresh_high=0.05,
    ),
    8: _preset(
        tape_drive=0.25,
        tape_sat=0.30,  # Reed: warm, expressive
        soothe_bypass=False,
        soothe_depth=0.35,
        soothe_sharpness=0.45,
        b3_gain=2.0,
        b3_freq=2200.0,
        rvb_dry=0.85,
        rvb_early=0.08,
        rvb_late=0.07,
        rvb_decay=0.07,
        rvb_size=0.20,
        stereo_width=0.55,
        fresh_mid=0.05,
        fresh_high=0.10,
    ),
    9: _preset(
        tape_drive=0.15,
        tape_sat=0.20,  # Pipe: open, airy, wide cathedral
        soothe_bypass=False,
        soothe_depth=0.35,
        soothe_sharpness=0.45,
        b4_gain=3.0,
        b4_freq=12000.0,
        rvb_dry=0.78,
        rvb_early=0.10,
        rvb_late=0.12,
        rvb_decay=0.15,
        rvb_size=0.35,
        rvb_diffuse=0.85,
        stereo_width=0.65,
        fresh_mid=0.05,
        fresh_high=0.10,
    ),
    10: _preset(
        tape_drive=0.50,
        tape_sat=0.50,  # Synth Leads: punchy, thick lead
        sdrr_bypass=False,
        sdrr_mode=0.0,
        sdrr_drive=0.35,
        sdrr_mix=0.50,  # saturated leads
        soothe_bypass=False,
        soothe_depth=0.35,
        soothe_sharpness=0.50,  # suppress resonance spikes
        b1_gain=-1.5,
        b1_freq=150.0,
        b3_gain=2.0,
        b3_freq=4000.0,
        rvb_dry=0.88,
        rvb_early=0.06,
        rvb_late=0.06,
        rvb_decay=0.02,
        rvb_size=0.10,
        stereo_width=0.55,
        chorus_wet=0.20,
        fresh_mid=0.15,
        fresh_high=0.20,
    ),
    11: _preset(
        tape_drive=0.30,
        tape_sat=0.35,  # Synth Pads: deep, wide, lush chorus
        sdrr_bypass=False,
        sdrr_mode=3.0,
        sdrr_drive=0.15,
        sdrr_mix=0.25,
        soothe_bypass=False,
        soothe_depth=0.30,
        soothe_sharpness=0.40,
        b1_gain=-4.5,
        b1_freq=200.0,
        b4_gain=1.5,
        b4_freq=12000.0,
        rvb_dry=0.65,
        rvb_early=0.10,
        rvb_late=0.25,
        rvb_decay=0.30,
        rvb_size=0.50,
        rvb_diffuse=0.95,
        rvb_spin=0.25,
        stereo_width=0.75,
        chorus_wet=0.40,
        fresh_mid=0.08,
        fresh_high=0.15,
        mb_bypass=False,
        mb_params={
            # Band 1 (Low: 20Hz - 150Hz) — State must be 0.25..0.5 = Enabled
            0: 0.5,         # State = Enabled (was 1.0 = Unused)
            1: 0.0,         # Low Crossover = 30 Hz
            3: 0.367,       # High Crossover ≈ 150 Hz: log(150/30)/log(1000)
            6: 0.583,       # Threshold: (db+60)/60 -> -25 dB
            7: 0.45,        # Range: -3 dB max GR
            8: 0.40,        # Ratio: 2:1 (power-law)
            # Band 2 (Mid: 150Hz - 3.7kHz)
            22: 0.5,        # State = Enabled
            23: 0.367,      # Low Crossover ≈ 150 Hz
            25: 0.754,      # High Crossover ≈ 3.7 kHz: log(3700/30)/log(1000)
            28: 0.667,      # Threshold: (db+60)/60 -> -20 dB
            29: 0.45,       # Range: -3 dB max GR
            30: 0.40,       # Ratio: 2:1
            # Band 3 (High: 3.7kHz - 20kHz)
            44: 0.5,        # State = Enabled (idx 44 = Band 3 base)
            45: 0.754,      # Low Crossover ≈ 3.7 kHz
            47: 0.833,      # High Crossover ≈ 20 kHz: log(20000/30)/log(1000)
            50: 0.500,      # Threshold: (db+60)/60 -> -30 dB (gentle on highs)
            51: 0.45,       # Range: -3 dB max GR
            52: 0.40,       # Ratio: 2:1
        },
    ),
    12: _preset(
        tape_drive=0.10,
        tape_sat=0.15,  # FX: atmospheric, massive field
        sdrr_bypass=False,
        sdrr_mode=0.0,
        sdrr_drive=0.20,
        sdrr_mix=0.30,
        rvb_dry=0.60,
        rvb_early=0.10,
        rvb_late=0.30,
        rvb_decay=0.40,
        rvb_size=0.60,
        rvb_diffuse=0.95,
        rvb_spin=0.30,
        stereo_width=0.80,
        chorus_wet=0.30,
        fresh_mid=0.10,
        fresh_high=0.20,
    ),
    13: _preset(
        tape_drive=0.30,
        tape_sat=0.35,  # Ethnic: authentic strings
        sdrr_bypass=False,
        sdrr_mode=0.0,
        sdrr_drive=0.20,
        sdrr_mix=0.30,
        spiff_mode=1.0,
        spiff_boost=0.20,
        spiff_sens=0.50,
        spiff_bypass=False,
        soothe_bypass=False,
        soothe_depth=0.35,
        soothe_sharpness=0.50,
        b3_gain=2.0,
        b3_freq=3500.0,
        rvb_dry=0.82,
        rvb_early=0.08,
        rvb_late=0.10,
        rvb_decay=0.10,
        rvb_size=0.25,
        stereo_width=0.55,
        fresh_mid=0.08,
        fresh_high=0.12,
    ),
    14: _preset(
        tape_drive=0.20,
        tape_sat=0.25,  # Percussive: punchy, tight center drums
        sdrr_bypass=False,
        sdrr_mode=0.0,
        sdrr_drive=0.25,
        sdrr_mix=0.35,  # round tube saturation
        b3_gain=3.0,
        b3_freq=3500.0,
        rvb_dry=0.80,
        rvb_early=0.10,
        rvb_late=0.10,
        rvb_decay=0.07,
        rvb_diffuse=0.8,
        stereo_width=0.50,
        fresh_mid=0.12,
        fresh_high=0.18,
        spiff_mode=1.0,
        spiff_boost=0.40,
        spiff_sens=0.60,
        spiff_bypass=False,
    ),
    15: _preset(bypass=True),  # Sound FX: raw passthrough
}

GROUP_NAMES = {
    0: "Pianos",
    1: "Chromatic Perc",
    2: "Organs",
    3: "Guitars",
    4: "Bass",
    5: "Strings",
    6: "Ensemble",
    7: "Brass",
    8: "Reed",
    9: "Pipe",
    10: "Synth Leads",
    11: "Synth Pads",
    12: "FX",
    13: "Ethnic",
    14: "Percussive",
    15: "Sound FX",
}


def get_preset_for_program(prog):
    """Returns the preset configuration customized for the specific GM program."""
    group = prog // 8
    preset = copy.deepcopy(GROUP_PRESETS.get(group, GROUP_PRESETS[0]))

    # Custom tweaks for specific instruments:
    if prog in (4, 5):  # Electric Piano 1 (Rhodes) and Electric Piano 2 (DX EP)
        preset["chorus_wet"] = 0.45
        preset["stereo"] = {3: 0.65, 19: 1.0}  # Width 130%, SafeBass ON
        preset["fresh_air"] = {"bypass": False, "mid": 0.12, "high": 0.18}

    return preset


def apply_preset(
    tape, pro_q, pro_mb, reverb, chorus, stereo, fresh_air, spiff, sdrr, soothe, preset
):
    """Configure all plugins for a given preset dict."""
    # CHOWTape
    for idx, val in preset["tape"].items():
        tape.set_parameter(idx, val)

    # SDRR2 (Saturator)
    sdrr_settings = preset["sdrr"]
    if sdrr_settings["bypass"]:
        sdrr.set_parameter(56, 1.0)  # Bypass ON
    else:
        sdrr.set_parameter(56, 0.0)  # Bypass OFF
        sdrr_mode = sdrr_settings["mode"]
        sdrr.set_parameter(0, sdrr_mode)  # Mode

        if sdrr_mode == 0.0:  # Tube
            sdrr.set_parameter(2, sdrr_settings["drive"])
            sdrr.set_parameter(10, sdrr_settings["mix"])
        elif sdrr_mode == 3.0:  # Desk
            sdrr.set_parameter(37, sdrr_settings["drive"])
            sdrr.set_parameter(49, sdrr_settings["mix"])

    # spiff (oeksound)
    spiff_settings = preset["spiff"]
    if spiff_settings["bypass"]:
        spiff.set_parameter(38, 1.0)  # Bypass ON
        spiff.set_parameter(41, 1.0)  # Bypass ON
    else:
        spiff.set_parameter(38, 0.0)  # Bypass OFF
        spiff.set_parameter(41, 0.0)  # Bypass OFF
        spiff.set_parameter(0, spiff_settings["mode"])  # 1.0 = boost
        if spiff_settings["mode"] > 0.5:
            spiff.set_parameter(2, spiff_settings["boost"])  # boost depth
        else:
            spiff.set_parameter(1, spiff_settings["cut"])  # cut depth
        spiff.set_parameter(3, spiff_settings["sens"])  # sensitivity
        spiff.set_parameter(35, 1.0)  # Mix 100%

    # soothe2 (oeksound)
    soothe_settings = preset["soothe"]
    if soothe_settings["bypass"]:
        soothe.set_parameter(53, 1.0)  # Bypass ON
    else:
        soothe.set_parameter(53, 0.0)  # Bypass OFF
        soothe.set_parameter(3, 0.0)  # Mode: soft
        soothe.set_parameter(4, soothe_settings["depth"])
        soothe.set_parameter(5, soothe_settings["sharpness"])
        soothe.set_parameter(6, soothe_settings["selectivity"])
        soothe.set_parameter(7, 0.15)  # Attack 1.5ms
        soothe.set_parameter(8, 0.20)  # Release (medium fast)
        soothe.set_parameter(50, 1.0)  # Mix 100%

    # FabFilter Pro-Q 4 (EQ)
    eq_settings = preset["eq"]

    # Mathematical converters for Pro-Q 4
    def freq_to_val(f):
        f = max(10.0, min(30000.0, float(f)))
        return np.log10(f / 10.0) / np.log10(3000.0)

    def gain_to_val(g):
        g = max(-30.0, min(30.0, float(g)))
        return (g + 30.0) / 60.0

    def q_to_val(q):
        q = max(0.025, min(40.0, float(q)))
        return np.log10(q / 0.025) / np.log10(1600.0)

    # Band 1: Low Cut (High Pass Filter)
    pro_q.set_parameter(0, 1.0)  # Used
    pro_q.set_parameter(1, 1.0)  # Enabled
    pro_q.set_parameter(5, 0.20)  # Shape: Low Cut (verified normalized value)
    pro_q.set_parameter(6, 0.1984)  # Slope: 12 dB/oct
    pro_q.set_parameter(2, freq_to_val(eq_settings["hp_freq"]))
    pro_q.set_parameter(3, gain_to_val(0.0))  # No gain for HP Cut

    # Band 2: Low-mid Dynamic EQ (mud control)
    pro_q.set_parameter(23, 1.0)  # Used
    pro_q.set_parameter(24, 1.0)  # Enabled
    pro_q.set_parameter(28, 0.0)  # Shape: Bell
    pro_q.set_parameter(25, freq_to_val(eq_settings["b1_freq"]))
    pro_q.set_parameter(26, gain_to_val(eq_settings["b1_gain"]))
    pro_q.set_parameter(27, q_to_val(eq_settings["b1_q"]))

    b1_dyn = eq_settings["b1_dyn"]
    if abs(b1_dyn) > 1e-4:
        pro_q.set_parameter(32, gain_to_val(b1_dyn))  # Dynamic Range
        pro_q.set_parameter(33, 1.0)  # Dynamics Enabled
        pro_q.set_parameter(34, 0.0)  # Dynamics Manual (Manual Mode)
    else:
        pro_q.set_parameter(32, gain_to_val(0.0))
        pro_q.set_parameter(33, 0.0)

    # Band 3: Presence boost/cut
    pro_q.set_parameter(46, 1.0)  # Used
    pro_q.set_parameter(47, 1.0)  # Enabled
    pro_q.set_parameter(51, 0.0)  # Shape: Bell
    pro_q.set_parameter(48, freq_to_val(eq_settings["b3_freq"]))
    pro_q.set_parameter(49, gain_to_val(eq_settings["b3_gain"]))
    pro_q.set_parameter(50, q_to_val(eq_settings["b3_q"]))
    pro_q.set_parameter(55, gain_to_val(0.0))
    pro_q.set_parameter(56, 0.0)  # Dynamics Disabled

    # Band 4: Air boost/cut (High Shelf)
    pro_q.set_parameter(69, 1.0)  # Used
    pro_q.set_parameter(70, 1.0)  # Enabled
    pro_q.set_parameter(74, 0.2778)  # Shape: High Shelf
    pro_q.set_parameter(71, freq_to_val(eq_settings["b4_freq"]))
    pro_q.set_parameter(72, gain_to_val(eq_settings["b4_gain"]))
    pro_q.set_parameter(73, q_to_val(eq_settings["b4_q"]))
    pro_q.set_parameter(78, gain_to_val(0.0))
    pro_q.set_parameter(79, 0.0)  # Dynamics Disabled

    # FabFilter Pro-R 2 (Reverb)
    rvb_settings = preset["reverb"]
    if rvb_settings is not None:
        reverb.set_parameter(132, 0.0)  # Bypass OFF (0.0 = engaged)
        # Mix (idx 9): linear 0..100%. 1.0 - dry.
        dry = rvb_settings.get(2, 0.93)  # rvb_dry (key 2)
        reverb.set_parameter(9, 1.0 - dry)

        # Space (idx 0): room size, log 200ms..10s. 0.5=2.5s, 0.7=4.0s (deep hall).
        reverb.set_parameter(0, 0.70)

        # Decay Rate (idx 1): 25%..400%, 0.50 = 100% (neutral).
        # Short decay rate -> controlled tail (~200ms) per deep-hall profile.
        reverb.set_parameter(1, 0.25)

        # Predelay (idx 16): quantized steps, NOT linear.
        # 0.667 ≈ 130 ms (dry attack, deep space).
        reverb.set_parameter(16, 0.667)

        # Character (idx 5): 0.50 = neutral.
        reverb.set_parameter(5, 0.50)

        # Stereo Width (idx 7): 0.58 ≈ 70%.
        reverb.set_parameter(7, 0.58)

        # Brightness (idx 6): 0.50 = neutral.
        reverb.set_parameter(6, 0.50)

        # Distance (idx 8): 0.50 = neutral.
        reverb.set_parameter(8, 0.50)
    else:
        reverb.set_parameter(132, 0.5)  # Bypass ON (0.5+ = bypassed)
        reverb.set_parameter(9, 0.0)  # Mix 0%

    # Configure Chorus (TAL-Chorus-LX)
    chorus_wet = preset.get("chorus_wet", 0.0)
    if chorus_wet > 0.0:
        chorus.set_parameter(1, chorus_wet)  # Dry/Wet
        chorus.set_parameter(2, 1.0)  # Stereo Width 10.0
        chorus.set_parameter(3, 1.0)  # Chorus 1 ON
        chorus.set_parameter(4, 0.0)  # Chorus 2 OFF
        chorus.set_parameter(6, 0.0)  # Bypass OFF (Active)
    else:
        chorus.set_parameter(1, 0.0)  # Dry/Wet to 0.0
        chorus.set_parameter(6, 1.0)  # Bypass ON

    # Configure Stereo (A1StereoControl)
    for idx, val in preset["stereo"].items():
        stereo.set_parameter(idx, val)

    # Configure Fresh Air (Slate Digital)
    fresh_settings = preset["fresh_air"]
    if fresh_settings["bypass"]:
        fresh_air.set_parameter(2, 1.0)  # Bypass ON
    else:
        fresh_air.set_parameter(2, 0.0)  # Bypass OFF
        fresh_air.set_parameter(0, fresh_settings["mid"])
        fresh_air.set_parameter(1, fresh_settings["high"])
        fresh_air.set_parameter(3, 1.0)  # Trim 0.0 dB

    # Configure FabFilter Pro-MB
    mb_settings = preset["pro_mb"]
    if mb_settings["bypass"]:
        pro_mb.set_parameter(138, 1.0)  # Bypass ON
    else:
        pro_mb.set_parameter(138, 0.0)  # Bypass OFF
        for idx, val in mb_settings["params"].items():
            pro_mb.set_parameter(idx, val)


def configure_kotelnikov_ge(kotelnikov):
    """TDR Kotelnikov GE: transparent mastering compressor.

    Calibrated against verified parameter defaults (audit data):
      idx 0 = Threshold  (0.0 = 0 dBFS, → negative dB)
      idx 1 = Peak Crest (0.4091 = 3.0 dB)
      idx 2 = Soft Knee  (0.0625 = 1.0 dB)
      idx 5 = Ratio      (0.5000 = 2.0:1, 0.43 ≈ 1.5:1)
      idx 6 = Attack     (0.3933 = 6 ms)
      idx 7 = Release Peak (0.3925 = 80 ms)
      idx 8 = Release RMS  (0.5207 = 220 ms)
      idx 10 = Makeup     (0.5000 = 0 dB, 0.6 ≈ +3 dB)
      idx 11 = Dry Mix    (0.0 = off)
      idx 12 = Dry Wet    (1.0 = 100% wet)
      idx 14 = Out Gain   (0.5000 = 0 dB, 0.5738 ≈ +3 dB)

    Settings: gentle transparent glue. Threshold catches peaks around
    -18 dBFS, ratio 1.5:1 barely touches dynamics, makeup +2 dB to
    compensate for the tiny level reduction.

    ⚠ idx 12 (Dry Wet) is INVERTED in the GE build: 1.0 = 0% wet (bypassed),
    0.0 = 100% wet (full compression). Verified via live parameter dump.
    """
    kotelnikov.set_parameter(0, 0.30)  # Threshold ~-18 dBFS
    kotelnikov.set_parameter(5, 0.43)  # Ratio 1.5:1
    kotelnikov.set_parameter(6, 0.39)  # Attack ~6 ms (default)
    kotelnikov.set_parameter(7, 0.42)  # Release Peak ~100 ms
    kotelnikov.set_parameter(8, 0.55)  # Release RMS ~280 ms
    kotelnikov.set_parameter(10, 0.58)  # Makeup +2 dB
    kotelnikov.set_parameter(11, 0.0)  # Dry Mix off
    kotelnikov.set_parameter(12, 0.0)  # Dry Wet = 100% WET (inverted: 0.0=full)
    kotelnikov.set_parameter(14, 0.55)  # Out Gain +2 dB
    kotelnikov.set_parameter(15, 0.598)  # SC HP Freq = 150 Hz (log), keeps bass warm
    kotelnikov.set_parameter(16, 0.5)  # SC HP Slope = 12 dB/oct


def configure_limiter(limiter):
    """FabFilter Pro-L 2: true peak mastering limiter."""
    limiter.set_parameter(17, 0.0)  # Bypass: Not Bypassed
    limiter.set_parameter(0, 0.0)  # Gain: 0.00 dB
    limiter.set_parameter(1, 0.7143)  # Style: Modern
    limiter.set_parameter(2, 0.20)  # Lookahead: 1.0 ms (was unset -> plugin default)
    limiter.set_parameter(18, 0.9667)  # Output Level: -1.00 dBTP (-30..0 linear)
    limiter.set_parameter(10, 1.0)  # True Peak Limiting: On
    limiter.set_parameter(9, 0.30)  # Oversampling: 4x (was 2x = 0.11)


def program_from_name(filename):
    """Extract GM program index from gm_NNN_*.wav."""
    m = re.match(r"gm_(\d{3})_", filename)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Sequential Processing Loop
# ---------------------------------------------------------------------------


def process_file(
    filepath,
    out_dir,
    engine,
    pb,
    tape,
    spiff,
    pro_q,
    pro_mb,
    reverb,
    chorus,
    stereo,
    fresh_air,
    sdrr,
    soothe,
):
    # Note: kotelnikov and limiter are configured once globally in main() and omitted here
    filename = os.path.basename(filepath)
    prog = program_from_name(filename)
    preset = get_preset_for_program(prog)

    try:
        audio, sr = sf.read(filepath)
        if audio.ndim == 1:
            audio = np.column_stack((audio, audio))

        # Resample to the processing sample rate if necessary
        if sr != SAMPLE_RATE:
            gcd = int(np.gcd(sr, SAMPLE_RATE))
            up = SAMPLE_RATE // gcd
            down = sr // gcd
            audio = scipy.signal.resample_poly(audio, up, down, axis=0)
            sr = SAMPLE_RATE

        if preset["bypass"]:
            # Raw passthrough — just normalize and copy
            out = audio.T.astype(np.float32)
            peak = float(np.max(np.abs(out)))
            if peak > 1e-6:
                out = out * (0.95 / peak)
            sf.write(
                os.path.join(out_dir, filename), out.T, SAMPLE_RATE, subtype="PCM_24"
            )
            return True, None

        audio_2d = audio.T.astype(np.float32)

        # Load audio into playback processor
        pb.set_data(audio_2d)

        # Configure presets
        apply_preset(
            tape,
            pro_q,
            pro_mb,
            reverb,
            chorus,
            stereo,
            fresh_air,
            spiff,
            sdrr,
            soothe,
            preset,
        )

        duration = len(audio) / sr
        engine.render(duration)
        out = engine.get_audio("limiter")

        # Peak-normalize to 0.95
        peak = float(np.max(np.abs(out)))
        if peak > 1e-6:
            out = out * (0.95 / peak)

        sf.write(os.path.join(out_dir, filename), out.T, SAMPLE_RATE, subtype="PCM_24")
        return True, None
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        return False, f"{e}\n{tb}"


# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------


def main():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(
        description="Single-threaded VST color chain processing."
    )
    parser.add_argument("--input", default=os.path.join(_root, "General_MIDI_samples_raw"))
    parser.add_argument("--output", default=os.path.join(_root, "General_MIDI_samples"))
    args = parser.parse_args()

    src_dir, out_dir = args.input, args.output
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(src_dir, "*.wav")))
    if not files:
        print(f"Error: no WAV files in {src_dir}")
        sys.exit(1)
    print(f"Found {len(files)} raw samples in {src_dir}")

    # Validate VST paths before starting
    for name, path in [
        ("CHOWTape", CHOW_PATH),
        ("SDRR2", SDRR_PATH),
        ("spiff", SPIFF_PATH),
        ("soothe2", SOOTHE_PATH),
        ("FabFilter Pro-Q 4", PRO_Q_PATH),
        ("FabFilter Pro-MB", PRO_MB_PATH),
        ("TDR Kotelnikov GE", KOTELNIKOV_GE_PATH),
        ("Fresh Air", FRESH_AIR_PATH),
        ("Chorus", CHORUS_PATH),
        ("StereoControl", STEREO_PATH),
        ("FabFilter Pro-R 2", PRO_R_PATH),
        ("FabFilter Pro-L 2", PRO_L_PATH),
    ]:
        if not os.path.exists(path):
            print(f"Error: {name} not found at {path}")
            sys.exit(1)

    # Silencing low-level stderr during VST load to hide iLok socket errors
    devnull = open(os.devnull, "w")
    old_stderr = os.dup(2)
    os.dup2(devnull.fileno(), 2)

    try:
        print("Initializing DawDreamer engine and VST plugins (single-threaded)...")
        engine = daw.RenderEngine(SAMPLE_RATE, BUFFER_SIZE)
        tape = engine.make_plugin_processor("tape", CHOW_PATH)
        sdrr = engine.make_plugin_processor("sdrr", SDRR_PATH)
        spiff = engine.make_plugin_processor("spiff", SPIFF_PATH)
        soothe = engine.make_plugin_processor("soothe", SOOTHE_PATH)
        pro_q = engine.make_plugin_processor("pro_q", PRO_Q_PATH)
        pro_mb = engine.make_plugin_processor("pro_mb", PRO_MB_PATH)
        kotelnikov_ge = engine.make_plugin_processor("kot", KOTELNIKOV_GE_PATH)
        fresh_air = engine.make_plugin_processor("fresh", FRESH_AIR_PATH)
        chorus = engine.make_plugin_processor("cho", CHORUS_PATH)
        stereo = engine.make_plugin_processor("ste", STEREO_PATH)
        reverb = engine.make_plugin_processor("reverb", PRO_R_PATH)
        limiter = engine.make_plugin_processor("limiter", PRO_L_PATH)
        configure_kotelnikov_ge(kotelnikov_ge)
        configure_limiter(limiter)
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        devnull.close()

    print("Building processing graph (reused for all samples)...")
    # Initialize with a silent dummy buffer
    dummy = np.zeros((2, BUFFER_SIZE), dtype=np.float32)
    pb = engine.make_playback_processor("pb", dummy)

    connections = [
        (pb, []),
        (tape, ["pb"]),
        (sdrr, ["tape"]),
        (spiff, ["sdrr"]),
        (soothe, ["spiff"]),
        (pro_q, ["soothe"]),
        (pro_mb, ["pro_q"]),
        (kotelnikov_ge, ["pro_mb"]),
        (fresh_air, ["kot"]),
        (chorus, ["fresh"]),
        (reverb, ["cho"]),
        (stereo, ["reverb"]),
        (limiter, ["ste"]),
    ]
    engine.load_graph(connections)

    print(f"Processing {len(files)} samples sequentially...")
    total = len(files)
    for idx, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        success, err = process_file(
            filepath,
            out_dir,
            engine,
            pb,
            tape,
            spiff,
            pro_q,
            pro_mb,
            reverb,
            chorus,
            stereo,
            fresh_air,
            sdrr,
            soothe,
        )
        if not success:
            print(f"  [{idx}/{total}] FAILED: {filename} - {err}")
        elif idx % 100 == 0 or idx == total:
            print(f"  Processed [{idx}/{total}] samples... Last: {filename}")

    print(f"\n✓ Done! All {len(files)} samples processed → {out_dir}")

    # Run patch_sfz_pitches.py on the raw (dry) samples folder to avoid FX-induced pitch detection errors
    print("\nRunning pitch auto-aligner on the raw dry samples...")
    import subprocess

    if "drums" in src_dir.lower():
        print("  → Skipping pitch auto-aligner for drum samples (not applicable).")
    else:
        cmd = [sys.executable, "patch_sfz_pitches.py", "--raw-dir", src_dir]
        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f"Warning: Pitch auto-aligner failed to run: {e}")

    # Explicit clean teardown
    engine.load_graph([])
    del engine


if __name__ == "__main__":
    main()
