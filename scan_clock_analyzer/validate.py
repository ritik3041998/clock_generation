"""
validate.py
-----------
Cross-checks the detected clock structure against independent facts we
can read directly from the data (grid size implied by the pixel count,
consistency of the digital counter file if present, reconstruction of
total sample count from lines*pixels+overhead). Produces a list of
(check, expected, actual, deviation, verdict) rows plus free-text notes
on anything ambiguous.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from pixel_detect import PixelStructure
from clock_calc import ClockResult


@dataclass
class ValidationRow:
    check: str
    expected: float
    actual: float
    deviation_pct: float
    verdict: str
    note: str = ""


def validate(ps: PixelStructure, cr: ClockResult, counter: np.ndarray | None) -> list[ValidationRow]:
    rows: list[ValidationRow] = []

    # 1. total active pixels should equal pixels_per_line * lines_per_frame,
    # after excluding any pixels identified as leaked next-frame fragment
    # (those are real pixel-clock strobes but not part of this frame's grid).
    total_active = len(ps.pixel_indices) - ps.trailing_fragment_pixels
    grid_predicted = cr.pixels_per_line * cr.lines_per_frame
    dev = 100 * abs(grid_predicted - total_active) / max(1, total_active)
    note = "Confirms the detected line/pixel grid actually tiles the active-pixel set."
    if ps.trailing_fragment_pixels:
        note += (f" ({ps.trailing_fragment_pixels} active pixels excluded as leaked "
                 "next-frame fragment - see warnings.)")
    rows.append(ValidationRow(
        "active_pixels == pixels_per_line * lines_per_frame",
        total_active, grid_predicted, dev,
        "PASS" if dev < 1 else "FAIL",
        note
    ))

    # 2. reconstructed frame length from lines+overhead vs actual file length
    reconstructed = (cr.lines_per_frame - 1) * cr.line_clock_ticks + \
        cr.pixel_clock_ticks * cr.pixels_per_line + cr.frame_overhead_ticks
    dev2 = 100 * abs(reconstructed - cr.frame_clock_ticks) / max(1, cr.frame_clock_ticks)
    rows.append(ValidationRow(
        "reconstructed frame ticks == total waveform samples",
        cr.frame_clock_ticks, reconstructed, dev2,
        "PASS" if dev2 < 1 else "FAIL",
        "Confirms pixel/line/frame ticks are consistent with the raw sample count."
    ))

    # 3. line period stability (steady state vs modal)
    if len(cr.line_clock_ticks_all) >= 3:
        gaps = cr.line_clock_ticks_all
        modal = cr.line_clock_ticks
        frac_matching = np.mean(gaps == modal)
        rows.append(ValidationRow(
            "fraction of lines matching modal line period",
            1.0, float(frac_matching), 100 * abs(1 - frac_matching),
            "PASS" if frac_matching > 0.5 else "AMBIGUOUS",
            f"{int(frac_matching*len(gaps))}/{len(gaps)} line transitions exactly match the "
            f"modal line period ({modal} ticks); others reflect first/last-line edge effects "
            "or resonant-scan settling variability."
        ))

    # 4. cross-check against the independent digital counter file, if present
    if counter is not None and len(counter) == ps.total_samples:
        col2 = counter[:, 1]
        n_counter_states = len(np.unique(np.round(col2, 6)))
        rows.append(ValidationRow(
            "distinct counter states (info only, not a strict pass/fail)",
            cr.lines_per_frame, n_counter_states,
            100 * abs(n_counter_states - cr.lines_per_frame) / max(1, cr.lines_per_frame),
            "INFO",
            "The digital counter file free-runs at the sample-clock rate and is not a "
            "clean line index, so large deviation here is expected, not an error."
        ))

    return rows
