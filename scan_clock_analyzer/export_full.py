"""
export_full.py
---------------
Writes the full, per-sample "logic analyzer" CSV (one row per fundamental
clock tick) for a dataset, in the same schema as a hardware capture would
produce:

    Sample_Index, Time_s, X_Voltage, Y_Voltage, Laser_Raw,
    Pixel_Clock, Line_Clock, Frame_Clock, Line_Number, Pixel_In_Line

This does not change any detection logic - it only re-expresses the
already-computed PixelStructure/ClockResult (from pixel_detect.py /
clock_calc.py) as an explicit tick-by-tick table:

The table covers ticks `0 .. frame_end_abs_idx` only - if the file's
tail contains a leaked, partially-captured first line of the *next*
frame (see pixel_detect.py), those trailing ticks belong to a
different frame and are dropped entirely, not just left unlabeled.
`clock_output.csv` therefore always ends exactly where this frame does.

  * Pixel_Clock  = 1 on exactly the detected pixel-valid ticks (of THIS
                   frame - the leaked fragment's pixel ticks are excluded
                   along with the rows they sit on).
  * Line_Clock   = 1 on the first pixel tick of every detected line, PLUS
                   one extra pulse on the final (last) row of the table,
                   marking completion of the frame (the "END" pulse).
  * Frame_Clock  = 1 on the first pixel tick of the first line ("F1"),
                   PLUS one on the final row ("END").
  * Line_Number / Pixel_In_Line = -1 outside any line's active span;
    inside a line's span (from its first to its last pixel tick,
    inclusive) Line_Number is that line's index, and Pixel_In_Line is
    the pixel's position within the line (0..pixels_per_line-1) on
    pixel-tick rows, -1 on the in-between (oversampled) rows.

Time_s = Sample_Index / master_clock_hz. If no master_clock_hz is given,
1,000,000 Hz (1 MHz, i.e. 1 tick = 1 microsecond) is used as a neutral
default purely for a readable time axis - it does not affect any of the
tick-count-based clock logic.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from pixel_detect import PixelStructure


def build_full_table(waveform: np.ndarray, gate: np.ndarray | None,
                      ps: PixelStructure, master_clock_hz: float) -> pd.DataFrame:
    frame_end = ps.frame_end_abs_idx if ps.frame_end_abs_idx >= 0 else ps.total_samples - 1
    n = frame_end + 1  # ticks belonging to THIS frame only

    waveform = waveform[:n]
    pixel_indices = ps.in_frame_pixel_indices

    if gate is not None and len(gate) == ps.total_samples:
        laser_raw = gate[:n, 0].astype(float)
    else:
        # synthesize a gate trace for schema consistency: 5.0 at each
        # detected pixel tick (matches the convention seen in the real
        # laser/meas_pts gate files), 0.0 elsewhere.
        laser_raw = np.zeros(n, dtype=float)
        laser_raw[pixel_indices] = 5.0

    pixel_clock = np.zeros(n, dtype=int)
    pixel_clock[pixel_indices] = 1

    line_start_abs = pixel_indices[ps.line_start_pixel_idx]
    line_clock = np.zeros(n, dtype=int)
    line_clock[line_start_abs] = 1
    line_clock[n - 1] = 1  # END pulse - the last row of THIS frame's own table

    frame_clock = np.zeros(n, dtype=int)
    if len(line_start_abs):
        frame_clock[line_start_abs[0]] = 1  # F1
    frame_clock[n - 1] = 1  # END

    line_number = np.full(n, -1, dtype=int)
    pixel_in_line = np.full(n, -1, dtype=int)

    starts = ps.line_start_pixel_idx
    seglens = ps.pixels_per_line_all
    for i, (start, length) in enumerate(zip(starts, seglens)):
        line_pixel_abs = pixel_indices[start:start + length]
        if len(line_pixel_abs) == 0:
            continue
        first_abs, last_abs = line_pixel_abs[0], line_pixel_abs[-1]
        line_number[first_abs:last_abs + 1] = i
        for j, abs_idx in enumerate(line_pixel_abs):
            pixel_in_line[abs_idx] = j

    time_s = np.arange(n) / master_clock_hz

    return pd.DataFrame({
        "Sample_Index": np.arange(n),
        "Time_s": time_s,
        "X_Voltage": waveform[:, 0],
        "Y_Voltage": waveform[:, 1],
        "Laser_Raw": laser_raw,
        "Pixel_Clock": pixel_clock,
        "Line_Clock": line_clock,
        "Frame_Clock": frame_clock,
        "Line_Number": line_number,
        "Pixel_In_Line": pixel_in_line,
    })


def write_full_csv(waveform: np.ndarray, gate: np.ndarray | None,
                    ps: PixelStructure, master_clock_hz: float, out_path: str):
    df = build_full_table(waveform, gate, ps, master_clock_hz)
    df.to_csv(out_path, index=False, float_format="%.9f")
    return df
