"""
clock_calc.py
-------------
Turns a PixelStructure into the Pixel -> Line -> Frame clock hierarchy.

Discovered logic (validated across 16x16 / 32x32 / 64x64 / Square, see
report.md):

  * Every row of the scan-waveform CSV is one tick of a single
    fundamental sample clock (the fastest clock in the system).
  * A PIXEL is not necessarily one tick: the modal spacing between
    consecutive valid-pixel strobes (gate!=0) gives the number of
    fundamental ticks per pixel -> this IS the pixel-clock divider,
    measured directly from the data, not assumed.
  * A LINE is `pixels_per_line` pixels plus one turnaround/settle gap
    (the extra ticks spent slewing the slow axis and re-stabilising
    before the first pixel of the next line). The measured line
    period in ticks = the distance between the first pixel of
    consecutive lines - this is an exact, per-line measurement, and
    we report both the modal (steady-state) value and its spread.
  * A FRAME ends at `frame_end_abs_idx + 1` ticks: normally this is the
    whole waveform file (`total_samples`), including the entry settle
    (before pixel 1) and exit flyback (after the last pixel). If the
    file's tail was found to contain a leaked, partially-captured first
    line of the *next* frame (see pixel_detect.py), the frame instead
    ends right after the last pixel of this frame's own last line - the
    leaked ticks are excluded from this frame's clock count entirely,
    not folded into its overhead.

  All three clocks therefore form an exact integer-tick divider chain
  relative to the fundamental sample clock:

      pixel_clock_ticks   = modal intra-line tick spacing
      line_clock_ticks    = modal (first-pixel-of-line[i+1] - first-pixel-of-line[i])
      frame_clock_ticks   = frame_end_abs_idx + 1 (one full frame's own ticks)

  Converting to Hz requires knowing the fundamental sample-clock rate
  (this is a DAC/ADC output rate that is not encoded in any of the
  supplied CSVs - there is no time column or metadata). We therefore
  report frequencies as exact tick-count DIVIDERS by default, and only
  produce Hz numbers when the caller supplies `master_clock_hz`
  (typical of a real deployment where the FPGA/DAQ sample rate is a
  known system constant, e.g. 40 MHz, 1 MHz, ...).
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from pixel_detect import PixelStructure


@dataclass
class ClockResult:
    pixel_clock_ticks: int
    line_clock_ticks: int
    frame_clock_ticks: int
    pixels_per_line: int
    lines_per_frame: int
    line_clock_ticks_all: np.ndarray   # per-line measured period (ticks)
    frame_overhead_ticks: int          # entry/exit settle not covered by lines
    master_clock_hz: float | None
    pixel_clock_hz: float | None
    line_clock_hz: float | None
    frame_clock_hz: float | None
    pixel_to_line_divider: float
    line_to_frame_divider: float


def compute_clocks(ps: PixelStructure, master_clock_hz: float | None = None) -> ClockResult:
    pixel_ticks = max(1, ps.intra_line_tick_spacing)

    if len(ps.line_to_line_tick_gap):
        # steady-state (modal) line period, robust to first/last edge effects
        gaps = ps.line_to_line_tick_gap
        line_ticks = int(np.bincount(gaps).argmax())
    else:
        # fewer than 2 lines: treat the whole frame as a single "line"
        line_ticks = ps.total_samples

    frame_ticks = ps.frame_end_abs_idx + 1 if ps.frame_end_abs_idx >= 0 else ps.total_samples

    lines_per_frame = max(1, ps.lines_per_frame)
    active_span = (lines_per_frame - 1) * line_ticks + pixel_ticks * ps.pixels_per_line
    frame_overhead = max(0, frame_ticks - active_span)

    pixel_to_line = line_ticks / pixel_ticks if pixel_ticks else float("nan")
    line_to_frame = frame_ticks / line_ticks if line_ticks else float("nan")

    pixel_hz = line_hz = frame_hz = None
    if master_clock_hz:
        pixel_hz = master_clock_hz / pixel_ticks
        line_hz = master_clock_hz / line_ticks
        frame_hz = master_clock_hz / frame_ticks

    return ClockResult(
        pixel_clock_ticks=pixel_ticks,
        line_clock_ticks=line_ticks,
        frame_clock_ticks=frame_ticks,
        pixels_per_line=ps.pixels_per_line,
        lines_per_frame=lines_per_frame,
        line_clock_ticks_all=ps.line_to_line_tick_gap,
        frame_overhead_ticks=frame_overhead,
        master_clock_hz=master_clock_hz,
        pixel_clock_hz=pixel_hz,
        line_clock_hz=line_hz,
        frame_clock_hz=frame_hz,
        pixel_to_line_divider=pixel_to_line,
        line_to_frame_divider=line_to_frame,
    )
