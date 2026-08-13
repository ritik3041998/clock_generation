"""
visualize.py
------------
Plots that show the raw scan trajectory, the detected pixel/line/frame
clock boundaries overlaid on it, and the pixel->line->frame timing
relationship as a small "logic analyzer" style trace.
"""
from __future__ import annotations
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pixel_detect import PixelStructure
from clock_calc import ClockResult


def _frame_slice(waveform: np.ndarray, ps: PixelStructure):
    """Waveform trimmed to this frame's own ticks only (drops any leaked
    next-frame fragment at the tail) plus the matching pixel indices."""
    frame_end = ps.frame_end_abs_idx if ps.frame_end_abs_idx >= 0 else len(waveform) - 1
    return waveform[:frame_end + 1], ps.in_frame_pixel_indices


def plot_trajectory_with_pixels(waveform: np.ndarray, ps: PixelStructure, out_path: str, title: str):
    waveform, pixel_indices = _frame_slice(waveform, ps)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(waveform[:, 0], waveform[:, 1], lw=0.4, color="#888888", label="full waveform (all ticks)")
    pts = waveform[pixel_indices]
    line_start_abs = pixel_indices[ps.line_start_pixel_idx]
    ax.scatter(pts[:, 0], pts[:, 1], s=4, color="#d62728", label="detected pixel-clock ticks")
    ax.scatter(waveform[line_start_abs, 0], waveform[line_start_abs, 1],
               s=30, facecolors="none", edgecolors="#1f77b4", linewidths=1.2,
               label="detected line-start (line clock)")
    ax.set_title(f"{title}\n{ps.lines_per_frame} lines x {ps.pixels_per_line} px/line "
                 f"({ps.method})")
    ax.set_xlabel("X (galvo command)")
    ax.set_ylabel("Y (galvo command)")
    ax.legend(loc="upper right", fontsize=7)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_clock_hierarchy(ps: PixelStructure, cr: ClockResult, out_path: str, title: str):
    """Logic-analyzer-style view: pixel ticks, line-start pulses, frame span,
    for a short window at the start of the scan so individual pixels are visible."""
    n_lines_to_show = min(3, ps.lines_per_frame)
    if n_lines_to_show < 1:
        return
    line_starts = ps.pixel_indices[ps.line_start_pixel_idx]
    window_end = line_starts[n_lines_to_show] if n_lines_to_show < len(line_starts) else ps.total_samples
    window_start = max(0, line_starts[0] - cr.pixel_clock_ticks * 2)

    pix_in_window = ps.pixel_indices[(ps.pixel_indices >= window_start) & (ps.pixel_indices < window_end)]
    lines_in_window = line_starts[(line_starts >= window_start) & (line_starts < window_end)]

    fig, axes = plt.subplots(3, 1, figsize=(9, 4.2), sharex=True)
    t = np.arange(window_start, window_end)

    axes[0].vlines(pix_in_window, 0, 1, color="#d62728", lw=1)
    axes[0].set_ylabel("Pixel\nclock")
    axes[0].set_yticks([])

    axes[1].vlines(lines_in_window, 0, 1, color="#1f77b4", lw=1.5)
    axes[1].set_ylabel("Line\nclock")
    axes[1].set_yticks([])

    if window_start == 0:
        axes[2].axvline(0, color="#2ca02c", lw=1.5)
    axes[2].text(0.5, 0.5, "1 frame-clock pulse per file "
                 f"(every {cr.frame_clock_ticks} ticks) - none in this zoomed window",
                 transform=axes[2].transAxes, ha="center", va="center", fontsize=7, color="#555555")
    axes[2].set_ylabel("Frame\nclock")
    axes[2].set_yticks([])
    axes[2].set_xlabel("Sample tick index (fundamental clock)")

    axes[0].set_title(f"{title}: Pixel -> Line -> Frame clock relationship "
                       f"(first {n_lines_to_show} lines shown)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_dark_trajectory(waveform: np.ndarray, ps: PixelStructure, out_path: str, title: str):
    """Full scan trajectory (all ticks, white) with every detected pixel-clock
    event marked (red), on a dark background - matches the "scan pattern"
    reference images shipped with the datasets."""
    waveform, pixel_indices = _frame_slice(waveform, ps)
    pts = waveform[pixel_indices]
    fig, ax = plt.subplots(figsize=(6, 6))
    fig.patch.set_facecolor("black")
    ax.set_facecolor("black")
    ax.plot(waveform[:, 0], waveform[:, 1], lw=0.6, color="white")
    ax.scatter(pts[:, 0], pts[:, 1], s=6, color="#ff2222", zorder=3)
    ax.set_title(f"{title}: Scan Trajectory with Pixel-Clock Events", color="white")
    ax.set_xlabel("X Voltage", color="white")
    ax.set_ylabel("Y Voltage", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("white")
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, facecolor="black")
    plt.close(fig)


def plot_full_clock_timing(ps: PixelStructure, cr: ClockResult, master_clock_hz: float,
                            out_path: str, title: str):
    """Full-frame (not zoomed) logic-analyzer view: every pixel-clock tick,
    every line-clock pulse (labelled L1..Ln + END), and the frame-clock
    pulses (labelled F1 + END), across THIS frame only, in milliseconds.
    Any leaked next-frame fragment at the file's tail is dropped entirely,
    not just excluded from the counts - it does not appear on this plot."""
    frame_end = ps.frame_end_abs_idx if ps.frame_end_abs_idx >= 0 else ps.total_samples - 1
    n = frame_end + 1
    t_ms = np.arange(n) / master_clock_hz * 1000.0
    pixel_indices = ps.in_frame_pixel_indices

    pix_t = t_ms[pixel_indices]
    line_start_abs = pixel_indices[ps.line_start_pixel_idx]
    line_t = list(t_ms[line_start_abs]) + [t_ms[-1]]
    line_labels = [f"L{i+1}" for i in range(len(line_start_abs))] + ["END"]
    frame_t = ([t_ms[line_start_abs[0]]] if len(line_start_abs) else []) + [t_ms[-1]]
    frame_labels = (["F1"] if len(line_start_abs) else []) + ["END"]

    fig, axes = plt.subplots(3, 1, figsize=(12, 6), sharex=True)

    axes[0].vlines(pix_t, 0, 1, color="#ff7f0e", lw=0.6)
    axes[0].set_ylabel("Pixel Clock")
    axes[0].set_yticks([0, 1])
    axes[0].set_title("Clock Timing - Full Frame")

    axes[1].vlines(line_t, 0, 1, color="#1f77b4", lw=1.2)
    for x, lbl in zip(line_t, line_labels):
        axes[1].text(x, 1.05, lbl, ha="center", va="bottom", fontsize=6, color="#1f77b4")
    axes[1].set_ylabel("Line Clock")
    axes[1].set_yticks([0, 1])
    axes[1].set_ylim(0, 1.3)

    axes[2].vlines(frame_t, 0, 1, color="#2ca02c", lw=1.5)
    for x, lbl in zip(frame_t, frame_labels):
        axes[2].text(x, 1.05, lbl, ha="center", va="bottom", fontsize=7, color="#2ca02c")
    axes[2].set_ylabel("Frame Clock")
    axes[2].set_yticks([0, 1])
    axes[2].set_ylim(0, 1.3)
    axes[2].set_xlabel("Time (ms)")

    fig.suptitle(title, y=1.0)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_line_period_stability(cr: ClockResult, out_path: str, title: str):
    if len(cr.line_clock_ticks_all) < 2:
        return
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.plot(cr.line_clock_ticks_all, marker="o", ms=3, lw=0.8, color="#1f77b4")
    ax.axhline(cr.line_clock_ticks, color="#d62728", ls="--", lw=1,
               label=f"modal line period = {cr.line_clock_ticks} ticks")
    ax.set_xlabel("Line index")
    ax.set_ylabel("Ticks to next line")
    ax.set_title(f"{title}: line-clock period stability")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
