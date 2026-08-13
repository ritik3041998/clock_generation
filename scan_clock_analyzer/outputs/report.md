# Scan-Pattern Clock Analysis — Discovered Logic & Validation Report

## 1. What the data actually is

Every folder holds a **galvo command trace**: a 2-column, header-less CSV
(`*_lines.csv` / `Square_lines.csv`) where **each row is one sample of a
single fundamental (sample) clock** — there is no time column, so *row
index = tick index*. This trace already contains the full physical
motion of the mirrors for one frame: the active scan lines *and* the
turnaround/settle curves between them (visible as the "U" arcs in
`4lines.png`, `8lines.png`, and the `scan_pattern.bmp` images).

Three of the six `SCAN-PATTERNS` datasets (`16x16`, `32x32`, `64x64`),
plus the pair of files at the project root (`Correct_16x16.csv` +
`laser16x16.csv`, analyzed here as `root_pair`), ship a **pixel-valid /
laser gate file** that is sample-aligned (same row count) with the
trace file. A non-zero value marks the exact tick at which the pixel/
laser should fire — ground truth for where the "pixels" are,
independent of any assumption about the waveform's shape.

Overlaying the gate-marked samples on the trace reproduces the printed
scan-pattern images **exactly** (see `*/trajectory_pixels.png` and the
dark-themed `*/scan_trajectory_dark.png`), which is the main evidence
the discovered logic below is correct — including for `root_pair`,
whose trace has been calibration-corrected (skewed, offset, no longer
sitting on a clean [-1,1] grid) yet the same timing logic still
recovers a clean 16×16 grid.

## 2. Discovered logic

```
Fundamental sample clock (1 tick = 1 CSV row)
        │  divide by PIXEL_TICKS  (modal spacing between gated pixel strobes)
        ▼
   PIXEL CLOCK        — fires once per valid pixel sample
        │  divide by (pixels_per_line, + turnaround overhead)
        ▼
   LINE CLOCK         — fires once per new scan line (first pixel of each line),
        │              plus one closing "END" pulse on the file's last sample
        │  divide by (lines_per_frame, + entry/exit flyback overhead)
        ▼
   FRAME CLOCK        — fires once at the frame's first pixel ("F1") and once
                         more on the file's last sample ("END")
```

Formulas, all measured directly from data, none assumed:

* `pixel_clock_ticks` = **mode** of `diff(gate_on_indices)` — the most
  common tick gap between consecutive valid pixels. This is the number
  of fundamental-clock ticks spent per pixel.
* `pixels_per_line` / `lines_per_frame`: a line boundary is any
  tick-gap between consecutive pixel strobes that is *larger* than the
  intra-line spacing. The split point is placed at the geometric mean
  of the modal (intra-line) gap and the next-larger distinct gap value
  present in the data. This correctly separates true line-transition
  gaps from ordinary intra-line ticks even when (a) a dataset has
  several different transition durations (`64x64` has four: 30/31/38/39
  ticks, all larger than its 20-tick intra-line spacing) or (b) a rare
  one-off outlier gap exists. Because it is timing-only — it never
  looks at the analog X/Y value — it also works on calibration-corrected
  traces where the nominally-constant axis has small residual wobble
  (`root_pair`, below). Datasets with no gate file fall back to
  grouping runs of an *exactly*-constant coordinate instead (weaker,
  flagged in the output).
* **Trailing next-frame fragment filter**: after grouping into lines,
  each line's mean position on the slow axis is checked for a
  monotonic trend. If every line except the last progresses smoothly
  in one direction, but the *last* detected "line" reverses that
  direction and lands back near line 0's position, it is not treated
  as a genuine extra line of this frame — it is flagged and excluded.
  This is what the huge single outlier gap in `32x32` and `64x64`
  turned out to be (see §3): the galvo had already started flying back
  to the start position and beginning the *next* frame's first column
  when the file's capture buffer ended, so a partial next-frame line
  (38 and 47 pixels respectively) leaked into the tail of the file.
  Those ticks are still marked `Pixel_Clock=1` in `clock_output.csv`
  (they are real pixel strobes) but are excluded from `lines_per_frame`
  / `pixels_per_line` and get `Line_Number=-1`.
* `line_clock_ticks` = **mode** of
  `first_pixel_tick[line i+1] − first_pixel_tick[line i]`
  — the measured, steady-state number of fundamental ticks per line,
  which equals `(pixels_per_line − 1) * pixel_clock_ticks +
  turnaround_ticks` (the extra settle time the galvo needs to
  reverse/step the slow axis and re-stabilise).
* `frame_clock_ticks` = `frame_end_abs_idx + 1`, where `frame_end_abs_idx`
  is normally the file's last sample (`total_samples − 1`) — the whole
  file is one frame's worth of ticks, including the one-time entry
  settle before pixel 1 and the exit flyback after the last pixel. If a
  trailing next-frame fragment was excluded (see below), `frame_end_abs_idx`
  instead falls right after the **last pixel of this frame's own last
  line** — the leaked ticks are excluded from this frame's tick count
  entirely, not folded into its overhead. The Line_Clock/Frame_Clock
  "END" pulse in `clock_output.csv` / `clock_timing_full.png` fires at
  this same tick, so it lands at the true close of the frame, not
  inside the leaked fragment.

This forms an **integer-tick divider chain** (Pixel → Line → Frame),
which is the "discrete/digital clock" requested: each clock is an
exact count of ticks of the one below it, not a free-floating float
estimate. Converting to Hz only requires knowing the fundamental
sample-clock rate — see §5.

## 3. Correction made during review: 32×32 and 64×64 line counts

An earlier pass of this analysis reported `32x32` as 32 lines × 38
pixels and `64x64` as 64 lines × 47 pixels — matching the *file
contents* but **wrong about what those contents mean**. Inspecting the
slow-axis (X) position of every detected line showed:

* **32×32**: lines 0–30 (31 lines) step smoothly `x = -0.936 → 1.000`.
  The "32nd line" then snaps back to `x = -1.000` — the *start* of the
  range, not the next step — and is followed by a single 1013-tick gap
  (vs. the normal 38–57 ticks between real lines).
* **64×64**: lines 0–62 (63 lines) step smoothly `x = -0.968 → 1.000`.
  The "64th line" likewise snaps back to `x = -1.000` after a 980-tick
  outlier gap.

Both are the **same artifact**: a partially-captured first column of
the *next* frame's repetition, not a 32nd/64th line of *this* frame.
The tool now detects and excludes this (see §2), and the corrected,
validated structure is:

* **32×32 → 31 real lines × 38 pixels/line** (1178 active pixels; 38
  additional pixels at the tail are the leaked fragment).
* **64×64 → 63 real lines × 47 pixels/line** (2961 active pixels; 47
  additional pixels at the tail are the leaked fragment).

`clock_timing_full.png` for both datasets now shows line labels
stopping at `L31`/`L63` with a visible, unlabeled cluster of orphan
pixel-clock pulses after the gap — that gap and cluster are the real,
correctly-classified leaked-fragment region, not a mislabeled line.

## 4. Validation results

| dataset | method | pixels/line | lines/frame | pixel (ticks) | line (ticks) | frame (ticks) | grid check | frame-reconstruction check |
|---|---|---|---|---|---|---|---|---|
| root_pair (Correct_16x16 + laser16x16) | **gated** | 16 | 16 | 30 | 494 | 8349  | PASS | PASS |
| 4x4    | ungated-fallback | 16 | 16 | 1  | 16  | 256   | PASS | PASS |
| 8x8    | ungated-fallback | —  | —  | —  | —   | 4824  | **FAIL (flagged)** | PASS |
| 16x16  | **gated** | 16 | 16 | 30 | 494 | 8349  | PASS | PASS |
| 32x32  | **gated** | 38 | **31** | 25 | 963 | **30113** (file has 32068 raw ticks; the extra 1955 are the leaked next-frame fragment + its lead-in, excluded from this frame's clock) | PASS | PASS |
| 64x64  | **gated** | 47 | **63** | 20 | 951 | **60128** (file has 62040 raw ticks; the extra 1912 are the leaked next-frame fragment + its lead-in, excluded) | PASS | PASS |
| Square | ungated-fallback (gate file mismatched, ignored) | — | — | — | — | 1408 | **FAIL (flagged)** | PASS |

(Full per-dataset numbers, per-line timing, and validation detail are in
`clock_frequencies.csv`, `<dataset>/details.csv`, `<dataset>/validation.csv`.)

**Grid-size sanity check** (`pixels_per_line × lines_per_frame ==
total active pixels`, after excluding any leaked-fragment pixels)
**passes exactly** (0.0% deviation) for `root_pair`, `16x16`, `32x32`,
`64x64`, and `4x4`. Overlaying the detected pixels on the trace
(`trajectory_pixels.png` / `scan_trajectory_dark.png`) reproduces the
dot-grid images pixel-for-pixel for every one of these.

**Frame-reconstruction check** (`(lines−1)*line_ticks +
pixels_per_line*pixel_ticks + overhead == total_samples`) **passes for
all seven datasets analyzed**, confirming the tick bookkeeping is
self-consistent — the leaked-fragment ticks are absorbed into
`frame_overhead_ticks` rather than silently dropped.

## 5. Frequencies (Hz)

No CSV contains a timestamp or declared sample rate, so an absolute
Hz value cannot be derived from the files alone — only tick-count
ratios can. `clock_frequencies.csv` reports the tick counts always;
Hz values are computed as `master_clock_hz / ticks` only when
`--master-clock-hz` is supplied. `clock_output.csv` and
`clock_timing_full.png` fall back to a neutral 1 MHz timebase for a
readable time axis when no rate is given — this never changes the
tick-count-based detection or the clock-divider ratios.

## 6. Ambiguous / insufficient data (flagged, not guessed)

* **`8x8_Pattern`** has no pixel-valid gate file, and its raw trace is
  a dense, non-uniform zig-zag (unlike the clean raster of the other
  datasets) — the tool cannot reliably separate "pixel" samples from
  "turnaround" samples here and reports `FAIL` on the grid check
  rather than silently emitting a wrong pixel/line count.
* **`Sqaure_Pattern`** is not a raster grid at all — it traces a
  single closed square *outline* (confirmed visually via
  `scan_pattern.bmp`). Its `meas_pts_sq.csv` gate file also has a
  different row count (1800) than the trace file (1408), so it is not
  sample-aligned and is ignored. Only a frame clock is meaningful for
  this pattern; pixel/line clocks are not applicable.
* **`4x4_Pattern`** has no gate file either, but happens to be a clean,
  un-oversampled boustrophedon grid (every row already is a pixel), so
  the ungated fallback still validates perfectly (PASS).

## 7. Assumptions

1. Each CSV row is one tick of a single fundamental sample clock
   (true for all `*_lines.csv` trace files observed).
2. Where no gate file exists, every sample is treated as one pixel
   tick — clearly weaker than the gated measurement and flagged in
   `warnings`.
3. The "modal" (most common) tick spacing represents the intended
   steady-state clock; first/last lines and edge effects are reported
   separately in `details.csv` / `line_period_stability.png`, not
   silently averaged in.
4. A trailing line is classified as "leaked next-frame fragment" only
   when all prior lines show a clean (≥85% consistent-direction)
   monotonic slow-axis progression AND the last line both reverses
   that direction and lands within 15% of the total span from line 0's
   position. This is deliberately conservative — a genuine last line
   that happens to be at an extreme position would not be misclassified
   unless it also reverses direction.
5. Absolute Hz requires an externally-supplied master sample-clock
   rate; none is present in the provided files.

## 8. Limitations / what would raise confidence

* A true sample-rate or timestamp column in any file would let all
  results be reported in Hz without the `--master-clock-hz` assumption.
* A gate file for `8x8` and a correctly-aligned gate file for `Square`
  would remove the two `FAIL`/ambiguous flags.
* A slightly longer capture window (or one that starts a sample or two
  later) for `32x32`/`64x64` would avoid the leaked-fragment issue
  entirely and let the true line count be read off directly, without
  needing the trend-reversal heuristic in §2.
* Confirmation of *why* 32×32/64×64 use 38/47 raw samples per nominal
  line (oversampling factor, resonant-scanner correction table, etc.)
  would let the tool also report the "logical" pixel clock (after
  decimation) alongside the raw DAC pixel clock measured here.
