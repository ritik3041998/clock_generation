"""
io_utils.py
-----------
Data loading for a "pattern folder": locates and loads the analog scan
waveform (X/Y galvo position per sample), the digital pixel-valid / laser
gate signal (if present), and the digital pixel/line counter file (if
present). No filenames or sizes are hard-coded - files are found by
role using flexible name matching so the tool works on new folders.

Every CSV in this dataset is a *2-column, header-less* file:
    col0, col1
Row index == sample index == one fundamental (pixel) clock tick.
"""
from __future__ import annotations
import os
import glob
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class PatternData:
    folder: str
    name: str
    waveform: np.ndarray                 # (N,2) analog X/Y per sample tick
    waveform_file: str
    gate: np.ndarray | None = None       # (M,2) pixel-valid / laser signal, M may != N
    gate_file: str | None = None
    counter: np.ndarray | None = None    # (N,2) digital pixel/line counter, if present
    counter_file: str | None = None
    images: list[str] = field(default_factory=list)


def _read_xy_csv(path: str) -> np.ndarray:
    df = pd.read_csv(path, header=None)
    return df.iloc[:, :2].to_numpy(dtype=float)


def _find(folder: str, patterns: list[str], exclude: list[str] | None = None) -> list[str]:
    exclude = exclude or []
    found = []
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(".csv"):
            continue
        low = f.lower()
        if any(x in low for x in exclude):
            continue
        if any(p in low for p in patterns):
            found.append(f)
    return found


def load_pattern_folder(folder: str) -> PatternData:
    """
    Discover and load the relevant files in a single scan-pattern folder.

    Role detection (by substring in filename, case-insensitive):
      - gate/pixel-valid signal : contains 'meas_pts' or 'laser'
      - digital counter         : filename ends with 'meas.csv' and is not a gate file
      - waveform (X/Y trace)    : contains 'lines', OR (if none found) the
                                   largest remaining 2-column csv in the folder
    Images (.bmp/.png) are collected for reference/visual correlation but not parsed.
    """
    folder = os.path.abspath(folder)
    name = os.path.basename(folder.rstrip("/\\"))

    gate_files = _find(folder, ["meas_pts", "laser"])
    counter_files = _find(folder, ["meas"], exclude=["meas_pts"])
    wave_files = _find(folder, ["lines"])

    all_csv = [f for f in sorted(os.listdir(folder)) if f.lower().endswith(".csv")]
    if not wave_files:
        # fall back: any csv not already claimed as gate/counter
        remaining = [f for f in all_csv if f not in gate_files and f not in counter_files]
        wave_files = remaining[:1]

    if not wave_files:
        raise FileNotFoundError(f"No scan-waveform CSV found in {folder}")

    wave_path = os.path.join(folder, wave_files[0])
    waveform = _read_xy_csv(wave_path)

    gate = None
    gate_path = None
    if gate_files:
        gate_path = os.path.join(folder, gate_files[0])
        gate = _read_xy_csv(gate_path)

    counter = None
    counter_path = None
    if counter_files:
        counter_path = os.path.join(folder, counter_files[0])
        counter = _read_xy_csv(counter_path)

    images = [f for f in sorted(os.listdir(folder))
              if f.lower().endswith((".bmp", ".png", ".jpg", ".jpeg"))]

    return PatternData(
        folder=folder, name=name,
        waveform=waveform, waveform_file=wave_files[0],
        gate=gate, gate_file=gate_files[0] if gate_files else None,
        counter=counter, counter_file=counter_files[0] if counter_files else None,
        images=images,
    )
