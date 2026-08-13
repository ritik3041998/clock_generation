# Scan-Pattern Clock Analyzer

Derives Pixel / Line / Frame clock timing from galvo scan-pattern CSVs.
See `outputs/report.md` for the discovered logic, formulas, assumptions,
and validation results.

## Usage

```
python analyze.py <pattern_folder> [<pattern_folder> ...] \
    --out outputs \
    --master-clock-hz 40000000   # optional: your DAQ/FPGA sample rate, to get Hz
```

Each `<pattern_folder>` should contain:
  * a 2-column X/Y trace CSV (any filename containing "lines"), where
    each row is one fundamental-clock sample of the galvo command, and
  * optionally, a sample-aligned pixel-valid/laser gate CSV (filename
    containing "meas_pts" or "laser") whose non-zero rows mark valid
    pixel-clock ticks.

No filenames, sizes, or frequencies are hard-coded — everything is
detected from the data. Datasets that don't fit the raster-grid model
(no gate file + irregular trace, or a mismatched/missing gate file)
are flagged rather than forced through the formula; see `warnings` and
`validation` columns in `clock_frequencies.csv`.

## Layout

```
io_utils.py       load a pattern folder (trace + optional gate + optional counter)
pixel_detect.py    find pixel-clock ticks and line boundaries
clock_calc.py      turn pixel/line structure into the tick-based clock chain
validate.py        cross-checks (grid size, frame reconstruction, stability)
visualize.py        trajectory + clock-boundary + line-period-stability plots
analyze.py         CLI entry point, orchestrates the above
```

## Outputs (per run)

```
outputs/
  clock_frequencies.csv          summary across all analyzed datasets
  report.md                      written analysis (formulas/assumptions/results)
  <dataset>/
    clock_output.csv             full per-tick "logic analyzer" export: one row per
                                  fundamental-clock tick with X/Y, gate value, and
                                  Pixel_Clock/Line_Clock/Frame_Clock/Line_Number/
                                  Pixel_In_Line flags (Line_Clock/Frame_Clock also
                                  pulse once more on the final row, the "END" event)
    details.csv                  per-line tick counts and pixel counts
    validation.csv               validation checks and verdicts
    trajectory_pixels.png        trace + detected pixel/line-start overlay
    scan_trajectory_dark.png     dark-background trace + pixel-clock dots
                                  (matches the reference scan-pattern images)
    clock_hierarchy.png          pixel -> line -> frame timing, zoomed to first lines
    clock_timing_full.png        pixel/line(L1..Ln,END)/frame(F1,END) timing,
                                  full frame, in milliseconds
    line_period_stability.png    per-line period vs. modal value
```

`clock_output.csv` and `clock_timing_full.png` need a time axis: pass
`--master-clock-hz` for your real sample rate, or omit it to fall back to
a neutral 1 MHz timebase (1 tick = 1 µs) used only for labeling — it does
not change any tick-count-based detection or clock-ratio logic.
