"""
pixel_detect.py
----------------
Turns a raw (waveform, gate) pair into the structural facts we need:
which sample ticks are valid pixels, which axis is the fast (in-line)
scan axis, how many pixels per line, and how many lines per frame.

Two detection paths, chosen automatically per dataset:

1. GATED path (a pixel-valid / laser strobe file is present, aligned
   1:1 with the waveform file). This is the ground-truth path: a pixel
   clock tick is, by definition, a sample where the gate is non-zero.

2. UNGATED fallback (no gate file, e.g. some datasets only ship the
   waveform). We assume every sample IS a pixel tick and detect line
   structure directly from runs of a constant coordinate. This is a
   weaker assumption and is flagged as such in the report.

In both paths, "lines" are detected as runs of consecutive pixel
samples that share a constant value on one axis (the *slow* axis);
the other axis is the *fast* axis that sweeps across the line.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass
class PixelStructure:
    method: str                      # "gated" or "ungated-fallback"
    total_samples: int               # length of the waveform file (1 frame)
    pixel_indices: np.ndarray        # sample indices (into waveform) that are valid pixels
    fast_axis: str                   # "x" or "y" : axis that sweeps across a line
    slow_axis: str                   # the other axis: changes once per line
    pixels_per_line: int             # modal number of pixels in a line
    pixels_per_line_all: np.ndarray  # per-line pixel counts (to see variability)
    lines_per_frame: int
    line_start_pixel_idx: np.ndarray # index into pixel_indices where each line starts
    intra_line_tick_spacing: int     # modal #ticks between consecutive pixels within a line
    line_to_line_tick_gap: np.ndarray  # ticks between last pixel of line i and first of i+1
    warnings: list[str]
    trailing_fragment_pixels: int = 0  # pixel ticks at the file's tail identified as a
                                        # leaked partial line of the *next* frame, and
                                        # therefore excluded from lines_per_frame/pixels_per_line
    frame_end_abs_idx: int = -1        # sample index where this frame's real content ends:
                                        # the last pixel tick of the last valid line if a
                                        # trailing fragment was excluded, else the file's last
                                        # sample (no leaked data, so the tail genuinely belongs
                                        # to this frame's exit flyback)
    in_frame_pixel_indices: np.ndarray = None  # pixel_indices with any leaked trailing-fragment
                                                # pixels dropped entirely (not just uncounted)


def _axis_line_grouping(xy: np.ndarray) -> tuple[str, np.ndarray, np.ndarray]:
    """
    Given the XY position at each *pixel* sample, decide which axis is
    constant-per-line (slow axis) by comparing how uniform the resulting
    run-length distribution is on each axis, then return
    (fast_axis_name, per_line_pixel_counts, line_start_indices_into_pixels).

    Used only for the ungated fallback path, where there is no timing
    signal to lean on and exact-value grouping is the only option.
    """
    best = None
    for axis, other in (("x", 0), ("y", 1)):
        col = other  # column index of the axis being tested as the *slow* (constant) axis
        vals = np.round(xy[:, col], 6)
        change = np.where(np.diff(vals) != 0)[0] + 1
        starts = np.concatenate(([0], change))
        seglens = np.diff(np.concatenate((starts, [len(vals)])))
        # uniformity score: fraction of segments equal to the modal length
        if len(seglens) == 0:
            continue
        modal = np.bincount(seglens).argmax()
        uniformity = np.mean(seglens == modal)
        score = uniformity * modal  # prefer uniform AND non-trivial (>1) line lengths
        cand = (score, axis, seglens, starts, modal)
        if best is None or score > best[0]:
            best = cand
    _, slow_axis, seglens, starts, modal = best
    fast_axis = "y" if slow_axis == "x" else "x"
    return fast_axis, seglens, starts


def _otsu_threshold(values: np.ndarray) -> float:
    """
    Splits tick-gap `values` into a "small" (intra-line spacing) cluster
    and a "large" (line-transition/turnaround) cluster. The modal value
    is, by construction, the intra-line spacing; the threshold is placed
    at the geometric mean of the mode and the *nearest* distinct value
    above it. Using the nearest neighbour (rather than a global 2-class
    variance split, i.e. Otsu) keeps the threshold from being dragged
    around by rare, far-away outliers (e.g. a single large gap from an
    edge/settle anomaly), while still correctly separating datasets that
    have several distinct transition durations clustered together
    (e.g. asymmetric turnarounds at 30/31/38/39 ticks vs. a 20-tick
    intra-line spacing).
    """
    uniq = np.unique(values)
    if len(uniq) < 2:
        return float(uniq[0]) + 0.5  # no variation at all -> no transitions
    modal = np.bincount(values).argmax()
    above = uniq[uniq > modal]
    if len(above) == 0:
        return float(modal) + 0.5
    return float(np.sqrt(modal * above[0]))


def _trailing_next_frame_fragment_length(xy: np.ndarray, starts: np.ndarray, seglens: np.ndarray,
                                          slow_col: int, tol: float = 0.15) -> int:
    """
    Detects a specific real-world artifact: the captured file's tail
    contains the galvo already flying back to its start position and
    beginning the *next* frame's first line, which got partially
    recorded before the buffer ended (e.g. 38 of 38 pixels of a 32x32
    dataset's real 32nd sample turned out to be the next frame's column
    1, not this frame's column 32 - see report.md for the worked case).

    Detection: track each line's mean position on the slow axis. If
    lines 0..k-2 progress monotonically (one direction, allowing a
    little jitter), but the *last* line reverses that direction and
    lands back near line 0's position, the last line is almost
    certainly leaked next-frame data, not a genuine extra line of this
    frame. Returns how many of the trailing lines to drop (0 or 1).
    """
    n_lines = len(seglens)
    if n_lines < 4:
        return 0
    reps = np.array([xy[starts[i]:starts[i] + seglens[i], slow_col].mean() for i in range(n_lines)])
    core = reps[:-1]
    diffs = np.diff(core)
    if len(diffs) < 2:
        return 0
    dominant_sign = np.sign(np.sum(diffs))
    if dominant_sign == 0 or np.mean(np.sign(diffs) == dominant_sign) < 0.85:
        return 0  # no clean monotonic trend to compare the last line against
    span = core.max() - core.min()
    if span == 0:
        return 0
    last_step_sign = np.sign(reps[-1] - reps[-2])
    reverses_direction = last_step_sign != 0 and last_step_sign != dominant_sign
    lands_near_start = abs(reps[-1] - reps[0]) < tol * span
    return 1 if (reverses_direction and lands_near_start) else 0


def _timing_line_grouping(pixel_indices: np.ndarray, xy: np.ndarray) -> tuple[str, np.ndarray, np.ndarray, int]:
    """
    Robust line-boundary detection for the GATED path: uses the digital
    tick-spacing between consecutive pixel strobes (not their analog
    position) to tell "next pixel in this line" (small, constant gap)
    apart from "first pixel of a new line" (larger gap, the turnaround/
    settle time). This works even when the position trace has been
    calibration-corrected and is no longer exactly constant along the
    slow axis.
    """
    diffs = np.diff(pixel_indices)
    modal = np.bincount(diffs).argmax()
    threshold = _otsu_threshold(diffs)
    is_transition = diffs > threshold
    starts = np.concatenate(([0], np.where(is_transition)[0] + 1))
    seglens = np.diff(np.concatenate((starts, [len(pixel_indices)])))

    # fast axis = whichever coordinate has the larger spread within a line (cosmetic only)
    first_line = xy[starts[0]:starts[0] + seglens[0]]
    fast_axis = "x" if np.ptp(first_line[:, 0]) >= np.ptp(first_line[:, 1]) else "y"
    slow_col = 1 if fast_axis == "x" else 0

    n_drop = _trailing_next_frame_fragment_length(xy, starts, seglens, slow_col)
    trailing_fragment_pixels = 0
    if n_drop:
        trailing_fragment_pixels = int(seglens[-1])
        starts = starts[:-1]
        seglens = seglens[:-1]

    return fast_axis, seglens, starts, trailing_fragment_pixels


def detect_pixel_structure(waveform: np.ndarray, gate: np.ndarray | None) -> PixelStructure:
    warnings: list[str] = []
    n = len(waveform)

    if gate is not None and len(gate) == n:
        on = np.where(gate[:, 0] != 0)[0]
        if len(on) < 4:
            warnings.append("Gate file present but has almost no active (non-zero) samples; "
                             "falling back to ungated detection.")
            gate = None
        else:
            method = "gated"
    elif gate is not None and len(gate) != n:
        warnings.append(
            f"Gate file length ({len(gate)}) does not match waveform length ({n}); "
            "the two files are not sample-aligned, so the gate is ignored. "
            "This dataset is flagged as lower-confidence."
        )
        gate = None

    if gate is not None:
        method = "gated"
        pixel_indices = on
    else:
        method = "ungated-fallback"
        pixel_indices = np.arange(n)
        warnings.append(
            "No usable pixel-valid/laser gate file found. Assuming every waveform "
            "sample is one pixel-clock tick (1 pixel = 1 sample). This is an "
            "assumption, not a measurement, and should be validated against real "
            "hardware timing if available."
        )

    xy = waveform[pixel_indices]
    trailing_fragment_pixels = 0
    if method == "gated" and len(pixel_indices) > 3:
        fast_axis, seglens, line_starts_in_pixels, trailing_fragment_pixels = \
            _timing_line_grouping(pixel_indices, xy)
    else:
        fast_axis, seglens, line_starts_in_pixels = _axis_line_grouping(xy)
    if trailing_fragment_pixels:
        warnings.append(
            f"Detected {trailing_fragment_pixels} pixel ticks at the file's tail that "
            "look like a leaked, partially-captured first line of the *next* frame "
            "(the slow-axis position reverses direction and lands back near line 0's "
            "position, instead of continuing this frame's line-to-line progression). "
            "These ticks are still marked as valid pixel-clock strobes, but are excluded "
            "from this frame's lines_per_frame / pixels_per_line counts."
        )
    pixels_per_line_all = seglens
    pixels_per_line = int(np.bincount(seglens).argmax())
    lines_per_frame = len(seglens)

    # intra-line tick spacing & line-to-line tick gap, measured on the *original*
    # sample-index timeline (pixel_indices), not the compressed pixel timeline.
    diffs = np.diff(pixel_indices)
    if len(diffs) > 0:
        intra_line_tick_spacing = int(np.bincount(diffs).argmax())
    else:
        intra_line_tick_spacing = 1

    line_start_abs_idx = pixel_indices[line_starts_in_pixels]
    line_to_line_tick_gap = np.diff(line_start_abs_idx)

    if lines_per_frame < 2:
        warnings.append(
            "Fewer than 2 lines detected - this looks like a single-loop / contour "
            "pattern rather than a raster grid. Pixel/line-clock ratios below are "
            "not meaningful for this dataset; only a frame clock can be reported."
        )

    if len(seglens) and (seglens.max() - seglens.min()) > max(1, 0.1 * pixels_per_line):
        warnings.append(
            f"Pixels-per-line varies significantly across lines "
            f"(min={seglens.min()}, max={seglens.max()}, modal={pixels_per_line}). "
            "Reporting the modal (steady-state) value; edge lines may be partial."
        )

    # Where this frame's real content ends: if a trailing next-frame fragment
    # was excluded, that's the last pixel of the last valid line (the leaked
    # ticks after it belong to the *next* frame, not this one). Otherwise
    # there's no leaked data, so the file's own last sample is this frame's
    # genuine end (it's the exit flyback of this same frame).
    if trailing_fragment_pixels and lines_per_frame > 0:
        last_line_start = line_starts_in_pixels[-1]
        last_line_len = pixels_per_line_all[-1]
        frame_end_abs_idx = int(pixel_indices[last_line_start + last_line_len - 1])
        in_frame_pixel_indices = pixel_indices[:len(pixel_indices) - trailing_fragment_pixels]
    else:
        frame_end_abs_idx = n - 1
        in_frame_pixel_indices = pixel_indices

    return PixelStructure(
        method=method,
        total_samples=n,
        pixel_indices=pixel_indices,
        fast_axis=fast_axis,
        slow_axis="y" if fast_axis == "x" else "x",
        pixels_per_line=pixels_per_line,
        pixels_per_line_all=pixels_per_line_all,
        lines_per_frame=lines_per_frame,
        line_start_pixel_idx=line_starts_in_pixels,
        intra_line_tick_spacing=intra_line_tick_spacing,
        line_to_line_tick_gap=line_to_line_tick_gap,
        warnings=warnings,
        trailing_fragment_pixels=trailing_fragment_pixels,
        frame_end_abs_idx=frame_end_abs_idx,
        in_frame_pixel_indices=in_frame_pixel_indices,
    )
