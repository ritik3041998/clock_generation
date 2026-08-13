"""
analyze.py
----------
Entry point. Usage:

    python analyze.py <pattern_folder> [<pattern_folder> ...] [--out OUTDIR] [--master-clock-hz HZ]

Runs the full pipeline (load -> detect pixels -> compute clocks ->
validate -> visualize) on one or more scan-pattern folders and writes:

    OUTDIR/clock_frequencies.csv   summary across all datasets
    OUTDIR/<name>/details.csv      per-line timing detail for that dataset
    OUTDIR/<name>/validation.csv   validation checks for that dataset
    OUTDIR/<name>/*.png            plots for that dataset
    OUTDIR/report.md               written analysis (formulas, assumptions, results)
"""
from __future__ import annotations
import argparse
import os
import sys
import pandas as pd

from io_utils import load_pattern_folder
from pixel_detect import detect_pixel_structure
from clock_calc import compute_clocks
from validate import validate
from visualize import (plot_trajectory_with_pixels, plot_clock_hierarchy, plot_line_period_stability,
                        plot_dark_trajectory, plot_full_clock_timing)
from export_full import write_full_csv

DEFAULT_TIMEBASE_HZ = 1_000_000  # 1 MHz -> 1 tick = 1 us; only used to label Time_s / ms axes


def analyze_folder(folder: str, out_root: str, master_clock_hz: float | None):
    pd_data = load_pattern_folder(folder)
    ps = detect_pixel_structure(pd_data.waveform, pd_data.gate)
    cr = compute_clocks(ps, master_clock_hz)
    checks = validate(ps, cr, pd_data.counter)

    out_dir = os.path.join(out_root, pd_data.name)
    os.makedirs(out_dir, exist_ok=True)

    # full per-tick "logic analyzer" export + full-frame plots, using the
    # real master clock if supplied, otherwise a neutral 1 MHz timebase
    # purely for a readable time axis (does not affect the tick-based logic)
    timebase_hz = master_clock_hz or DEFAULT_TIMEBASE_HZ
    write_full_csv(pd_data.waveform, pd_data.gate, ps, timebase_hz,
                    os.path.join(out_dir, "clock_output.csv"))
    plot_dark_trajectory(pd_data.waveform, ps,
                          os.path.join(out_dir, "scan_trajectory_dark.png"), pd_data.name)
    plot_full_clock_timing(ps, cr, timebase_hz,
                            os.path.join(out_dir, "clock_timing_full.png"), pd_data.name)

    # per-line detail
    detail = pd.DataFrame({
        "line_index": range(len(cr.line_clock_ticks_all)),
        "ticks_to_next_line": cr.line_clock_ticks_all,
        "pixels_in_line": ps.pixels_per_line_all[:len(cr.line_clock_ticks_all)],
    })
    detail.to_csv(os.path.join(out_dir, "details.csv"), index=False)

    # validation
    val_df = pd.DataFrame([v.__dict__ for v in checks])
    val_df.to_csv(os.path.join(out_dir, "validation.csv"), index=False)

    # plots
    plot_trajectory_with_pixels(pd_data.waveform, ps,
                                 os.path.join(out_dir, "trajectory_pixels.png"), pd_data.name)
    plot_clock_hierarchy(ps, cr, os.path.join(out_dir, "clock_hierarchy.png"), pd_data.name)
    plot_line_period_stability(cr, os.path.join(out_dir, "line_period_stability.png"), pd_data.name)

    summary = {
        "dataset": pd_data.name,
        "waveform_file": pd_data.waveform_file,
        "gate_file": pd_data.gate_file or "",
        "detection_method": ps.method,
        "total_samples": ps.total_samples,
        "pixels_per_line": cr.pixels_per_line,
        "lines_per_frame": cr.lines_per_frame,
        "pixel_clock_ticks": cr.pixel_clock_ticks,
        "line_clock_ticks": cr.line_clock_ticks,
        "frame_clock_ticks": cr.frame_clock_ticks,
        "pixel_to_line_divider": round(cr.pixel_to_line_divider, 3),
        "line_to_frame_divider": round(cr.line_to_frame_divider, 3),
        "frame_overhead_ticks": cr.frame_overhead_ticks,
        "master_clock_hz": master_clock_hz or "",
        "pixel_clock_hz": cr.pixel_clock_hz or "",
        "line_clock_hz": cr.line_clock_hz or "",
        "frame_clock_hz": cr.frame_clock_hz or "",
        "warnings": " | ".join(ps.warnings),
        "validation": "; ".join(f"{v.check}={v.verdict}" for v in checks),
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+", help="one or more scan-pattern folders")
    ap.add_argument("--out", default="outputs", help="output directory")
    ap.add_argument("--master-clock-hz", type=float, default=None,
                     help="fundamental sample-clock rate in Hz, if known, to convert "
                          "tick counts into real frequencies")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    summaries = []
    for folder in args.folders:
        try:
            summaries.append(analyze_folder(folder, args.out, args.master_clock_hz))
        except Exception as e:
            summaries.append({"dataset": os.path.basename(folder.rstrip("/\\")),
                               "error": str(e)})

    df = pd.DataFrame(summaries)
    df.to_csv(os.path.join(args.out, "clock_frequencies.csv"), index=False)
    print(df.to_string(index=False))
    print(f"\nWritten to {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
