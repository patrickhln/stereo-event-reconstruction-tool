#!/usr/bin/env python3
"""Validate a stereo calibration on a blinking checkerboard event capture.

Finds blink transitions in the event stream, accumulates frames around each
one, detects the checkerboard, and reports reprojection error + depth error.

Three candidate accumulation windows (15/10/20 ms) are tried per transition;
the first that gives a stereo detection is kept.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Iterator

import cv2
import dv_processing as dv
import matplotlib
import numpy as np
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PYTHON_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PYTHON_ROOT not in sys.path:
    sys.path.append(PYTHON_ROOT)

from path_utils import (
    require_branch_root,
    require_raw_dir,
    require_recording_path,
    require_stereo_camchain_path,
)

# synchronisation (anchor search)
ANCHOR_BIN_US = 10_000
ANCHOR_GRID_COLS = 16
ANCHOR_GRID_ROWS = 9
ANCHOR_SMOOTH_BINS = 3
ANCHOR_PEAK_PERCENTILE = 90.0
ANCHOR_PEAK_FACTOR = 0.50
ANCHOR_TOLERANCE_US = 40_000

# transition refinement
REFINE_BIN_US_MIN = 1_000
REFINE_SMOOTH_BINS = 3
SEARCH_RADIUS_US = 10_000

# evaluation protocol: candidate windows tried in this order
EVAL_WINDOWS_US = [15_000, 10_000, 20_000]
MAX_EVAL_WINDOW_US = max(EVAL_WINDOWS_US)

# debug plot
DEBUG_PLOT_SPAN_US = 10_000_000


# data holders 


@dataclass
class Calibration:
    width: int
    height: int
    K0: np.ndarray
    K1: np.ndarray
    D0: np.ndarray
    D1: np.ndarray
    T_10: np.ndarray
    baseline_cm: float


@dataclass
class Manifest:
    target_cols: int
    target_rows: int
    blink_period_us: int
    hold_us: int
    flush_us: int
    position_labels: list[str]


@dataclass
class Interval:
    index: int
    repeat_index: int
    label: str
    scheduled_start_us: int
    scheduled_end_us: int
    eval_start_us: int
    eval_end_us: int


# i/o

def branch_recording(capture_path: str) -> tuple[str, str]:
    root = require_branch_root(capture_path)
    return require_recording_path(root), require_raw_dir(root)


def camera_metadata(raw_dir: str) -> tuple[str, str, int, int]:
    path = os.path.join(raw_dir, "camera_metadata.txt")
    with open(path, "r", encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    if len(lines) < 5:
        raise RuntimeError(f"Unexpected camera_metadata.txt format in {raw_dir}")
    width, height = map(int, lines[2].split())
    return lines[1], lines[3], width, height


def load_manifest(path: str) -> Manifest:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    hz = raw.get("refresh_rate_hz")
    fpf = int(raw.get("flush_frames_per_level", 0))
    levels = raw.get("flush_levels") or []
    flush_us = 0
    if hz and fpf > 0 and levels:
        flush_us = int(round(1e6 * len(levels) * fpf / float(hz)))
    return Manifest(
        target_cols=int(raw["target_cols"]),
        target_rows=int(raw["target_rows"]),
        blink_period_us=int(round(float(raw["blink_period"]) * 1e6)),
        hold_us=int(round(float(raw["hold_seconds"]) * 1e6)),
        flush_us=flush_us,
        position_labels=[str(lb) for lb in raw["position_labels"]],
    )


def load_calibration(
    calibration_path: str, model: str,
) -> tuple[str, Calibration]:
    camchain_path = require_stereo_camchain_path(
        require_branch_root(calibration_path), model,
    )
    with open(camchain_path, "r", encoding="utf-8") as fh:
        camchain = yaml.safe_load(fh)
    cam0, cam1 = camchain["cam0"], camchain["cam1"]
    width, height = map(int, cam0["resolution"])

    def _K(intr):
        fx, fy, cx, cy = intr
        return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)

    K0, K1 = _K(cam0["intrinsics"]), _K(cam1["intrinsics"])
    D0 = np.array(cam0["distortion_coeffs"], dtype=np.float64)
    D1 = np.array(cam1["distortion_coeffs"], dtype=np.float64)
    T_10 = np.array(cam1["T_cn_cnm1"], dtype=np.float64)
    t_10 = T_10[:3, 3:4]
    return camchain_path, Calibration(
        width=width, height=height,
        K0=K0, K1=K1, D0=D0, D1=D1, T_10=T_10,
        baseline_cm=float(np.linalg.norm(t_10) * 100.0),
    )


# event streaming

def prime_store(reader, store: dv.EventStore, exhausted: bool) -> tuple[dv.EventStore, bool]:
    while not exhausted and store.isEmpty():
        batch = reader.getNextEventBatch()
        if batch is None or batch.size() == 0:
            exhausted = True
            break
        store.add(batch)
    return store, exhausted


def fill_store_until(
    reader, store: dv.EventStore, exhausted: bool, target_us: int,
) -> tuple[dv.EventStore, bool]:
    while not exhausted and (store.isEmpty() or int(store.getHighestTime()) < target_us):
        batch = reader.getNextEventBatch()
        if batch is None or batch.size() == 0:
            exhausted = True
            break
        store.add(batch)
    return store, exhausted


def _open_stereo(aedat4_path: str, raw_dir: str):
    left_cam, right_cam, _, _ = camera_metadata(raw_dir)
    rec = dv.io.StereoCameraRecording(aedat4_path, left_cam, right_cam)
    lr, rr = rec.getLeftReader(), rec.getRightReader()
    ls, ld = prime_store(lr, dv.EventStore(), False)
    rs, rd = prime_store(rr, dv.EventStore(), False)
    lo = int(ls.getLowestTime()) if not ls.isEmpty() else None
    ro = int(rs.getLowestTime()) if not rs.isEmpty() else None
    return lr, rr, ls, ld, rs, rd, lo, ro


def recording_start_us(aedat4_path: str, raw_dir: str) -> int:
    _, _, _, _, _, _, lo, ro = _open_stereo(aedat4_path, raw_dir)
    starts = [t for t in (lo, ro) if t is not None]
    if not starts:
        raise RuntimeError("Could not determine recording start timestamp")
    return min(starts)


def iter_windows(
    aedat4_path: str, raw_dir: str,
    windows: list[tuple[Any, int, int]],
) -> Iterator[tuple[Any, int, int, dv.EventStore | None, dv.EventStore | None]]:
    """Yield (payload, t0, t1, left_events, right_events) for each window."""
    if not windows:
        return
    windows = sorted(windows, key=lambda item: (item[1], item[2]))
    lr, rr, ls, ld, rs, rd, lo, ro = _open_stereo(aedat4_path, raw_dir)
    starts = [t for t in (lo, ro) if t is not None]
    if not starts:
        return

    def _slice(store, t0, t1):
        if store.isEmpty():
            return None
        s = store.sliceTime(t0, t1)
        return None if s.size() == 0 else s

    for payload, start_us, end_us in windows:
        if end_us <= start_us:
            continue
        ls, ld = fill_store_until(lr, ls, ld, end_us)
        rs, rd = fill_store_until(rr, rs, rd, end_us)
        yield payload, start_us, end_us, _slice(ls, start_us, end_us), _slice(rs, start_us, end_us)
        ls = ls.sliceTime(start_us) if not ls.isEmpty() else ls
        rs = rs.sliceTime(start_us) if not rs.isEmpty() else rs


# rendering / detection

def render_accumulation(
    events: dv.EventStore | None, width: int, height: int, clip_pct: float,
) -> np.ndarray:
    """Polarity-weighted accumulation frame, contrast-clipped to uint8."""
    img = np.full((height, width), 127, dtype=np.uint8)
    if events is None or events.isEmpty():
        return img
    ev = events.numpy()
    if len(ev) == 0:
        return img
    acc = np.zeros((height, width), dtype=np.float32)
    np.add.at(
        acc, (ev["y"], ev["x"]),
        np.where(ev["polarity"], 1.0, -1.0).astype(np.float32),
    )
    nz = acc != 0.0
    if not np.any(nz):
        return img
    scale = max(float(np.percentile(np.abs(acc[nz]), clip_pct)), 1.0)
    return np.round(127.5 + 127.5 * np.clip(acc / scale, -1.0, 1.0)).astype(np.uint8)


def detect_checkerboard(
    image: np.ndarray, cols: int, rows: int,
) -> np.ndarray | None:
    ok, corners = cv2.findChessboardCornersSB(
        image, (cols, rows), flags=cv2.CALIB_CB_NORMALIZE_IMAGE,
    )
    return corners if ok and corners is not None else None


def slice_events(
    events: dv.EventStore | None, start_us: int, end_us: int,
) -> dv.EventStore | None:
    if events is None or events.isEmpty():
        return None
    s = events.sliceTime(start_us, end_us)
    return s if not s.isEmpty() else None


# geometry


def make_object_points(cols: int, rows: int) -> np.ndarray:
    """Unit-spaced grid on z=0.  Scale doesn't affect reprojection error."""
    pts = np.zeros((rows * cols, 3), dtype=np.float64)
    for i in range(rows):
        for j in range(cols):
            pts[i * cols + j] = [j, i, 0.0]
    return pts


def pnp_reprojection_error(
    corners: np.ndarray, K: np.ndarray, D: np.ndarray,
    obj_pts: np.ndarray,
) -> float | None:
    """RMS reprojection error in pixels for one camera."""
    ok, rvec, tvec = cv2.solvePnP(
        obj_pts, corners.reshape(-1, 1, 2), K, D,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        return None
    projected, _ = cv2.projectPoints(obj_pts, rvec, tvec, K, D)
    err = corners.reshape(-1, 2) - projected.reshape(-1, 2)
    return float(np.sqrt(np.mean(err ** 2)))


def triangulate_points_cm(
    corners0: np.ndarray, corners1: np.ndarray, cal: Calibration,
) -> np.ndarray | None:
    ud0 = cv2.undistortPoints(corners0, cal.K0, cal.D0)
    ud1 = cv2.undistortPoints(corners1, cal.K1, cal.D1)
    P0 = np.hstack([np.eye(3, dtype=np.float64), np.zeros((3, 1), dtype=np.float64)])
    P1 = cal.T_10[:3, :]
    pts_h = cv2.triangulatePoints(P0, P1, ud0.reshape(-1, 2).T, ud1.reshape(-1, 2).T)
    w = pts_h[3]
    if np.any(np.abs(w) < 1e-9):
        return None
    pts = (pts_h[:3] / w).T
    if not np.all(np.isfinite(pts)) or np.any(pts[:, 2] <= 0.0):
        return None
    return pts * 100.0


def plane_distance_cm(points_cm: np.ndarray) -> float:
    """Distance from the camera origin to the best-fit plane (SVD)."""
    centroid = np.mean(points_cm, axis=0)
    centered = points_cm - centroid
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[-1]
    normal /= np.linalg.norm(normal)
    return abs(float(normal @ centroid))


# anchor search (find pattern start / end) 


def localized_activity_score(
    events: dv.EventStore | None, width: int, height: int,
) -> float:
    """Favour compact event bursts over diffuse noise."""
    if events is None or events.isEmpty():
        return 0.0
    ev = events.numpy()
    total = len(ev)
    if total == 0:
        return 0.0
    tiles = np.zeros((ANCHOR_GRID_ROWS, ANCHOR_GRID_COLS), dtype=np.int32)
    tx = np.minimum((ev["x"] * ANCHOR_GRID_COLS) // width, ANCHOR_GRID_COLS - 1)
    ty = np.minimum((ev["y"] * ANCHOR_GRID_ROWS) // height, ANCHOR_GRID_ROWS - 1)
    np.add.at(tiles, (ty, tx), 1)
    max_tile = int(np.max(tiles))
    return float((max_tile * max_tile) / total)


def build_anchor_signal(
    aedat4_path: str, raw_dir: str, cal: Calibration,
) -> tuple[np.ndarray, np.ndarray]:
    """Stereo activity signal over the whole recording (one score per bin)."""
    lr, rr, ls, ld, rs, rd, lo, ro = _open_stereo(aedat4_path, raw_dir)
    starts = [t for t in (lo, ro) if t is not None]
    if not starts:
        raise RuntimeError("Could not determine recording start timestamp")

    cur = min(starts)
    times_us: list[int] = []
    scores: list[float] = []
    while True:
        end_us = cur + ANCHOR_BIN_US
        ls, ld = fill_store_until(lr, ls, ld, end_us)
        rs, rd = fill_store_until(rr, rs, rd, end_us)
        left = None if ls.isEmpty() else ls.sliceTime(cur, end_us)
        right = None if rs.isEmpty() else rs.sliceTime(cur, end_us)
        left_score = localized_activity_score(left, cal.width, cal.height)
        right_score = localized_activity_score(right, cal.width, cal.height)
        times_us.append(cur)
        scores.append(min(left_score, right_score))
        cur = end_us
        ls = ls.sliceTime(cur) if not ls.isEmpty() else ls
        rs = rs.sliceTime(cur) if not rs.isEmpty() else rs
        if ld and rd:
            hi = ([int(ls.getHighestTime())] if not ls.isEmpty() else []) + \
                 ([int(rs.getHighestTime())] if not rs.isEmpty() else [])
            if not hi or max(hi) < cur:
                break
    if not scores:
        raise RuntimeError("Anchor search could not read any event bins")
    signal = np.array(scores, dtype=np.float64)
    kernel = np.ones(ANCHOR_SMOOTH_BINS, dtype=np.float64) / ANCHOR_SMOOTH_BINS
    return np.array(times_us, dtype=np.int64), np.convolve(signal, kernel, mode="same")


def local_maxima(signal: np.ndarray, threshold: float) -> list[int]:
    peaks: list[int] = []
    for i in range(1, len(signal) - 1):
        if signal[i] < threshold:
            continue
        if signal[i] >= signal[i - 1] and signal[i] >= signal[i + 1]:
            peaks.append(i)
    return peaks


def find_pattern_anchors(
    aedat4_path: str, raw_dir: str,
    cal: Calibration, manifest: Manifest, expected_dur_us: int,
) -> tuple[int, int, dict[str, Any], dict[str, Any]]:
    times_us, signal = build_anchor_signal(aedat4_path, raw_dir, cal)
    positive = signal[signal > 0.0]
    if positive.size == 0:
        raise RuntimeError("Anchor search found no activity")
    peak_threshold = float(np.percentile(positive, ANCHOR_PEAK_PERCENTILE) * ANCHOR_PEAK_FACTOR)
    peaks = local_maxima(signal, peak_threshold)
    if not peaks:
        raise RuntimeError("Anchor search found no peaks")

    half_blink_bins = max(1, int(round((manifest.blink_period_us / 2) / ANCHOR_BIN_US)))
    tolerance_bins = max(1, int(round(ANCHOR_TOLERANCE_US / ANCHOR_BIN_US)))
    expected_dur_bins = max(1, int(round(expected_dur_us / ANCHOR_BIN_US)))

    # a peak counts as "supported" if its periodic neighbours also exist
    def supported(idx: int, direction: int) -> bool:
        for step in (1, 2):
            target = idx + direction * step * half_blink_bins
            if not any(abs(peak - target) <= tolerance_bins for peak in peaks):
                return False
        return True

    start_peaks = [idx for idx in peaks if supported(idx, 1)]
    end_peaks = [idx for idx in peaks if supported(idx, -1)]
    if not start_peaks or not end_peaks:
        raise RuntimeError("Could not find periodic start/end peaks")

    # pick the start/end pair whose span best matches the expected duration
    best_pair: tuple[int, int] | None = None
    best_error = None
    for start_idx in start_peaks:
        for end_idx in end_peaks:
            if end_idx <= start_idx:
                continue
            error = abs((end_idx - start_idx) - expected_dur_bins)
            if best_error is None or error < best_error:
                best_pair = (start_idx, end_idx)
                best_error = error
    if best_pair is None:
        raise RuntimeError("Could not match start and end anchors to the expected duration")

    start_idx, end_idx = best_pair
    pattern_start = int(times_us[start_idx])
    pattern_end = int(times_us[end_idx])
    print(
        f"[search:start] bins={len(signal)} peak_thresh={peak_threshold:.2f} "
        f"peak={int(times_us[start_idx])} anchor={pattern_start}"
    )
    print(
        f"[search:end] bins={len(signal)} peak_thresh={peak_threshold:.2f} "
        f"peak={int(times_us[end_idx])} anchor={pattern_end} duration_error_bins={best_error}"
    )
    start_info = {
        "method": "event_activity_periodic_search",
        "bin_us": ANCHOR_BIN_US,
        "peak_threshold": peak_threshold,
        "peak_count": len(peaks),
        "periodic_peak_us": int(times_us[start_idx]),
        "anchor_us": pattern_start,
    }
    end_info = {
        "method": "event_activity_periodic_search",
        "bin_us": ANCHOR_BIN_US,
        "peak_threshold": peak_threshold,
        "peak_count": len(peaks),
        "periodic_peak_us": int(times_us[end_idx]),
        "anchor_us": pattern_end,
        "duration_error_us": int(best_error * ANCHOR_BIN_US),
    }
    if pattern_end <= pattern_start:
        raise RuntimeError("Anchor search produced an invalid time range")
    return pattern_start, pattern_end, start_info, end_info


# timeline


def build_intervals(
    manifest: Manifest, repeats: int,
    pattern_start_us: int, pattern_end_us: int,
    hold_start_guard_s: float, hold_end_guard_s: float,
) -> list[Interval]:
    g_start = int(round(hold_start_guard_s * 1e6))
    g_end = int(round(hold_end_guard_s * 1e6))
    cur = pattern_start_us
    intervals: list[Interval] = []
    idx = 0
    for rep in range(repeats):
        for label in manifest.position_labels:
            s_start = cur
            s_end = cur + manifest.hold_us
            ev_start = s_start + g_start
            ev_end = min(pattern_end_us, s_end - g_end)
            if ev_end > ev_start:
                intervals.append(Interval(
                    idx, rep, label, s_start, s_end, ev_start, ev_end,
                ))
                idx += 1
            cur = s_end + manifest.flush_us
    return intervals


# transition refinement 


def event_count(events: dv.EventStore | None) -> int:
    return 0 if events is None or events.isEmpty() else int(events.size())


def refine_transition_centers(
    aedat4_path: str, raw_dir: str,
    intervals: list[Interval], manifest: Manifest,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """For each expected blink transition, nudge the center to the local
    event-activity peak so the accumulation window lands on the sharpest edge."""
    half_blink = manifest.blink_period_us // 2
    refine_bin_us = max(REFINE_BIN_US_MIN, MAX_EVAL_WINDOW_US // 5)
    searches: dict[tuple[int, int], dict[str, Any]] = {}
    windows: list[tuple[tuple[Any, int], int, int]] = []
    fallback_count = 0
    shifts_us: list[int] = []

    # debug plot data (only first DEBUG_PLOT_SPAN_US)
    debug_x: list[float] = []
    debug_y: list[float] = []
    debug_expected: list[int] = []
    debug_refined: list[int] = []
    plot_limit_us = intervals[0].scheduled_start_us + DEBUG_PLOT_SPAN_US if intervals else 0

    for iv in intervals:
        center_us = iv.scheduled_start_us + half_blink
        transition_index = 0
        while center_us < iv.scheduled_end_us:
            low = max(iv.eval_start_us + MAX_EVAL_WINDOW_US // 2, center_us - SEARCH_RADIUS_US)
            high = min(iv.eval_end_us - MAX_EVAL_WINDOW_US // 2, center_us + SEARCH_RADIUS_US)
            if low <= high:
                key = (iv.index, transition_index)
                searches[key] = {
                    "interval": iv,
                    "transition_index": transition_index,
                    "expected_center_us": int(center_us),
                    "default_center_us": int(min(max(center_us, low), high)),
                    "centers_us": [],
                    "scores": [],
                }
                probe = low
                while probe <= high:
                    start_us = probe - refine_bin_us // 2
                    end_us = start_us + refine_bin_us
                    windows.append(((key, int(probe)), start_us, end_us))
                    probe += refine_bin_us
                transition_index += 1
            center_us += half_blink

    for payload, _, _, lev, rev in iter_windows(aedat4_path, raw_dir, windows):
        key, probe_center_us = payload
        search = searches[key]
        search["centers_us"].append(int(probe_center_us))
        search["scores"].append(min(event_count(lev), event_count(rev)))

    transitions: list[dict[str, Any]] = []
    for key in sorted(searches):
        search = searches[key]
        centers_us = search["centers_us"]
        scores = np.array(search["scores"], dtype=np.float64)
        smooth = np.convolve(
            scores,
            np.ones(REFINE_SMOOTH_BINS, dtype=np.float64) / REFINE_SMOOTH_BINS,
            mode="same",
        ) if len(scores) > 0 else scores
        if len(smooth) == 0 or float(np.max(smooth)) <= 0.0:
            refined_center_us = int(search["default_center_us"])
            fallback_count += 1
        else:
            refined_center_us = int(centers_us[int(np.argmax(smooth))])
        iv = search["interval"]
        transitions.append({
            "interval": iv,
            "transition_index": search["transition_index"],
            "expected_center_us": int(search["expected_center_us"]),
            "refined_center_us": refined_center_us,
        })
        shifts_us.append(refined_center_us - int(search["expected_center_us"]))

        if int(search["expected_center_us"]) <= plot_limit_us:
            debug_x.extend(centers_us)
            debug_y.extend(smooth.tolist())
            debug_x.append(np.nan)
            debug_y.append(np.nan)
            debug_expected.append(int(search["expected_center_us"]))
            debug_refined.append(refined_center_us)

    abs_shifts = [abs(v) for v in shifts_us]
    refinement = {
        "method": "local_activity_histogram_peak",
        "search_radius_us": SEARCH_RADIUS_US,
        "refine_bin_us": int(refine_bin_us),
        "transition_count": len(transitions),
        "fallback_count": fallback_count,
        "mean_shift_us": float(np.mean(shifts_us)) if shifts_us else 0.0,
        "median_shift_us": float(np.median(shifts_us)) if shifts_us else 0.0,
        "p95_abs_shift_us": float(np.percentile(abs_shifts, 95.0)) if abs_shifts else 0.0,
    }
    plot_data = {
        "x_us": debug_x,
        "y": debug_y,
        "expected_centers_us": debug_expected,
        "refined_centers_us": debug_refined,
        "window_ranges_us": [],
    }
    return transitions, refinement, plot_data


# evaluation window construction 


def build_eval_windows(
    transitions: list[dict[str, Any]],
) -> list[tuple[tuple[Interval, int], int, int]]:
    """One read-window per transition, sized to the largest candidate.
    The evaluate loop sub-slices to each candidate internally."""
    half = MAX_EVAL_WINDOW_US // 2
    windows: list[tuple[tuple[Interval, int], int, int]] = []
    for item in transitions:
        iv = item["interval"]
        center_us = int(item["refined_center_us"])
        tidx = int(item["transition_index"])
        lo = iv.eval_start_us + half
        hi = iv.eval_end_us - half
        if lo > hi:
            continue
        clamped = min(max(center_us, lo), hi)
        windows.append(((iv, tidx), clamped - half, clamped + half))
    return windows


# debug plots 


def save_timing_debug_plot(
    path: str, pattern_start_us: int, plot_data: dict[str, Any],
) -> None:
    fig, ax = plt.subplots(figsize=(12, 4))
    x = np.array(plot_data["x_us"], dtype=np.float64)
    y = np.array(plot_data["y"], dtype=np.float64)
    if x.size > 0:
        ax.plot((x - pattern_start_us) / 1e6, y, color="tab:blue", linewidth=1.5)
    first = True
    for c in plot_data["expected_centers_us"]:
        ax.axvline((c - pattern_start_us) / 1e6, color="tab:gray", ls="--", alpha=0.5,
                   label="expected" if first else None)
        first = False
    first = True
    for c in plot_data["refined_centers_us"]:
        ax.axvline((c - pattern_start_us) / 1e6, color="tab:orange", alpha=0.7,
                   label="refined" if first else None)
        first = False
    first = True
    for s, e in plot_data.get("window_ranges_us", []):
        ax.axvspan((s - pattern_start_us) / 1e6, (e - pattern_start_us) / 1e6,
                   color="tab:orange", alpha=0.12, label="eval window" if first else None)
        first = False
    ax.set_xlim(0.0, DEBUG_PLOT_SPAN_US / 1e6)
    ax.set_xlabel("Time from pattern start [s]")
    ax.set_ylabel("Stereo event score")
    ax.set_title("Transition refinement (first 2 s)")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_detection_examples(
    path: str, manifest: Manifest,
    examples: list[tuple[str, dict[str, Any]]],
) -> None:
    canvases = []
    for title, m in examples:
        left = cv2.cvtColor(m["left_image"], cv2.COLOR_GRAY2BGR)
        right = cv2.cvtColor(m["right_image"], cv2.COLOR_GRAY2BGR)
        if m.get("corners0") is not None:
            cv2.drawChessboardCorners(left, (manifest.target_cols, manifest.target_rows),
                                      m["corners0"], bool(m.get("left_detected")))
        if m.get("corners1") is not None:
            cv2.drawChessboardCorners(right, (manifest.target_cols, manifest.target_rows),
                                      m["corners1"], bool(m.get("right_detected")))
        canvas = np.hstack([left, right])
        cv2.putText(canvas, title, (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 220, 0), 2, cv2.LINE_AA)
        canvases.append(canvas)
    if not canvases:
        return
    w = max(c.shape[1] for c in canvases)
    padded = []
    for c in canvases:
        if c.shape[1] < w:
            c = np.hstack([c, np.full((c.shape[0], w - c.shape[1], 3), 127, np.uint8)])
        padded.append(c)
    cv2.imwrite(path, np.vstack(padded))


# evaluation 


def summarize(values: list[float], depth_gt_cm: float | None = None) -> dict[str, float] | None:
    if not values:
        return None
    d = np.array(values, dtype=np.float64)
    if depth_gt_cm is not None:
        return {
            "mae_cm": float(np.mean(np.abs(d))),
            "bias_cm": float(np.mean(d)),
            "rmse_cm": float(np.sqrt(np.mean(d ** 2))),
        }
    return {"mean": float(np.mean(d)), "p95": float(np.percentile(d, 95.0))}


def evaluate(
    aedat4_path: str, raw_dir: str,
    cal: Calibration, manifest: Manifest,
    intervals: list[Interval],
    transitions: list[dict[str, Any]],
    depth_gt_cm: float, clip_pct: float, out_dir: str,
    obj_pts: np.ndarray,
) -> dict[str, Any]:
    all_depth_err: list[float] = []
    all_reproj_left: list[float] = []
    all_reproj_right: list[float] = []
    total_transitions = 0
    total_stereo = 0
    total_left = 0
    total_right = 0
    window_counts: dict[int, int] = {}
    chosen_window_ranges: list[tuple[int, int]] = []
    n_corners = manifest.target_rows * manifest.target_cols

    sample_ok: dict[str, Any] | None = None
    sample_fail: dict[str, Any] | None = None

    if not transitions:
        return _empty_result()

    probes = build_eval_windows(transitions)
    cur_block = -1

    for payload, start_us, end_us, lev, rev in iter_windows(aedat4_path, raw_dir, probes):
        iv, tidx = payload
        if iv.index != cur_block:
            cur_block = iv.index
            print(f"Block {iv.index + 1:02d}/{len(intervals):02d}"
                  f" | rep={iv.repeat_index + 1:02d}"
                  f" | pos={iv.label:>12s}")

        center_us = (start_us + end_us) // 2
        total_transitions += 1

        # try each candidate window until we get a stereo detection
        hit = False
        left_any = False
        right_any = False
        sel_c0 = sel_c1 = None
        sel_li = sel_ri = None
        sel_win = EVAL_WINDOWS_US[0]
        first_li = first_ri = None
        first_c0 = first_c1 = None

        for i, win_us in enumerate(EVAL_WINDOWS_US):
            w0 = center_us - win_us // 2
            li = render_accumulation(slice_events(lev, w0, w0 + win_us), cal.width, cal.height, clip_pct)
            ri = render_accumulation(slice_events(rev, w0, w0 + win_us), cal.width, cal.height, clip_pct)
            c0 = detect_checkerboard(li, manifest.target_cols, manifest.target_rows)
            c1 = detect_checkerboard(ri, manifest.target_cols, manifest.target_rows)

            if i == 0:
                first_li, first_ri, first_c0, first_c1 = li, ri, c0, c1
            if c0 is not None:
                left_any = True
            if c1 is not None:
                right_any = True
            if (c0 is not None and c1 is not None
                    and c0.shape[0] == n_corners and c1.shape[0] == n_corners):
                hit = True
                sel_win = win_us
                sel_c0, sel_c1, sel_li, sel_ri = c0, c1, li, ri
                break

        if left_any:
            total_left += 1
        if right_any:
            total_right += 1

        if not hit:
            if sample_fail is None and (left_any or right_any):
                sample_fail = dict(block_index=iv.index, transition_index=tidx,
                                   left_detected=left_any, right_detected=right_any,
                                   left_image=first_li, right_image=first_ri,
                                   corners0=first_c0, corners1=first_c1)
            continue

        total_stereo += 1
        window_counts[sel_win] = window_counts.get(sel_win, 0) + 1
        w0 = center_us - sel_win // 2
        chosen_window_ranges.append((w0, w0 + sel_win))

        # depth via triangulation
        pts = triangulate_points_cm(sel_c0, sel_c1, cal)
        if pts is not None:
            depth = plane_distance_cm(pts)
            all_depth_err.append(depth - depth_gt_cm)

        # per-camera reprojection error (scale-invariant)
        rpe_l = pnp_reprojection_error(sel_c0, cal.K0, cal.D0, obj_pts)
        rpe_r = pnp_reprojection_error(sel_c1, cal.K1, cal.D1, obj_pts)
        if rpe_l is not None:
            all_reproj_left.append(rpe_l)
        if rpe_r is not None:
            all_reproj_right.append(rpe_r)

        if sample_ok is None:
            sample_ok = dict(block_index=iv.index, transition_index=tidx,
                             window_us=sel_win, left_detected=True, right_detected=True,
                             left_image=sel_li, right_image=sel_ri,
                             corners0=sel_c0, corners1=sel_c1)

    # save example detections for visual sanity check
    debug_examples: dict[str, str] = {}
    examples: list[tuple[str, dict[str, Any]]] = []
    if sample_ok is not None:
        examples.append((
            f"detected | block={sample_ok['block_index']}"
            f" t={sample_ok['transition_index']} win={sample_ok['window_us']}us",
            sample_ok))
    if sample_fail is not None:
        examples.append((
            f"failed | block={sample_fail['block_index']}"
            f" t={sample_fail['transition_index']}"
            f" L={sample_fail['left_detected']} R={sample_fail['right_detected']}",
            sample_fail))
    if examples:
        p = os.path.join(out_dir, "detection_examples.png")
        save_detection_examples(p, manifest, examples)
        debug_examples["detection_examples"] = p

    return {
        "depth_error_cm": all_depth_err,
        "reproj_left_px": all_reproj_left,
        "reproj_right_px": all_reproj_right,
        "total_transitions": total_transitions,
        "total_stereo_hits": total_stereo,
        "total_left_hits": total_left,
        "total_right_hits": total_right,
        "window_counts": window_counts,
        "debug_examples": debug_examples,
        "window_ranges_us": chosen_window_ranges,
    }


def _empty_result() -> dict[str, Any]:
    return {
        "depth_error_cm": [], "reproj_left_px": [], "reproj_right_px": [],
        "total_transitions": 0, "total_stereo_hits": 0,
        "total_left_hits": 0, "total_right_hits": 0,
        "window_counts": {}, "debug_examples": {}, "window_ranges_us": [],
    }



def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Validate a stereo calibration on a blinking checkerboard capture.",
    )
    p.add_argument("calibration_path", help="Calibration branch root")
    p.add_argument("capture_path", help="Validation capture branch root")
    p.add_argument("--model", required=True)
    p.add_argument("--manifest", required=True, help="Blinking-pattern manifest")
    p.add_argument("--repeats", type=int, required=True)
    p.add_argument("--depth-gt-cm", type=float, required=True, help="Measured board distance")
    p.add_argument("--hold-start-guard-s", type=float, default=0.30)
    p.add_argument("--hold-end-guard-s", type=float, default=0.20)
    p.add_argument("--clip-percentile", type=float, default=99.0)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--force-search", action="store_true",
                   help="Re-run anchor search even if anchors.json is cached")
    args = p.parse_args()
    if args.repeats <= 0:
        p.error("--repeats must be > 0")
    if args.depth_gt_cm <= 0.0:
        p.error("--depth-gt-cm must be > 0")
    args.out_dir = os.path.abspath(args.out_dir)
    return args


def main() -> None:
    args = parse_args()
    camchain_path, cal = load_calibration(args.calibration_path, args.model)
    manifest = load_manifest(args.manifest)
    aedat4_path, raw_dir = branch_recording(args.capture_path)
    os.makedirs(args.out_dir, exist_ok=True)

    obj_pts = make_object_points(manifest.target_cols, manifest.target_rows)

    rec_start = recording_start_us(aedat4_path, raw_dir)
    n_blocks = args.repeats * len(manifest.position_labels)
    stride = manifest.hold_us + manifest.flush_us
    expected_dur = (n_blocks - 1) * stride + manifest.hold_us

    # anchor search (or load cached)
    anchors_path = os.path.join(args.out_dir, "anchors.json")
    if os.path.isfile(anchors_path) and not args.force_search:
        with open(anchors_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        pattern_start = int(cached["pattern_start_us"])
        pattern_end = int(cached["pattern_end_us"])
        start_info = cached.get("start_search", {})
        end_info = cached.get("end_search", {})
        print(f"Loaded cached anchors from {anchors_path}\n"
              f"  start={pattern_start} us  end={pattern_end} us")
    else:
        pattern_start, pattern_end, start_info, end_info = find_pattern_anchors(
            aedat4_path, raw_dir, cal, manifest, expected_dur)
        start_info["pattern_start_us"] = int(pattern_start)
        end_info["pattern_end_us"] = int(pattern_end)

        # sanity check: duration shouldn't drift more than one blink period
        dur_diff = (pattern_end - pattern_start) - expected_dur
        drift_blinks = abs(dur_diff) / manifest.blink_period_us
        print(f"[timing] diff={dur_diff / 1e6:.3f}s ({drift_blinks:.2f} blinks)")
        if drift_blinks >= 1.0:
            raise RuntimeError(
                f"Anchor drift too large ({drift_blinks:.2f} blink periods) -- "
                f"anchors are likely wrong.")

        with open(anchors_path, "w", encoding="utf-8") as fh:
            json.dump({"pattern_start_us": int(pattern_start),
                        "pattern_end_us": int(pattern_end),
                        "start_search": start_info, "end_search": end_info}, fh, indent=2)
        print(f"Saved anchors -> {anchors_path}")

    intervals = build_intervals(manifest, args.repeats, pattern_start, pattern_end,
                                args.hold_start_guard_s, args.hold_end_guard_s)
    if not intervals:
        raise RuntimeError("No validation intervals remain after trimming")

    wins = ", ".join(f"{w / 1000:.0f} ms" for w in EVAL_WINDOWS_US)
    print(f"Model: {args.model} | {manifest.target_cols}x{manifest.target_rows}"
          f" | Baseline: {cal.baseline_cm:.4f} cm\n"
          f"Blocks: {len(intervals)} | Windows: [{wins}]")

    transitions, ref_info, plot_data = refine_transition_centers(
        aedat4_path, raw_dir, intervals, manifest)

    m = evaluate(aedat4_path, raw_dir, cal, manifest, intervals, transitions,
                 args.depth_gt_cm, args.clip_percentile, args.out_dir, obj_pts)

    plot_data["window_ranges_us"] = m["window_ranges_us"]
    debug_plot = os.path.join(args.out_dir, "timing_debug.png")
    save_timing_debug_plot(debug_plot, pattern_start, plot_data)

    # aggregate
    total = m["total_transitions"]
    stereo = m["total_stereo_hits"]
    det_rate = stereo / total if total > 0 else 0.0
    left_rate = m["total_left_hits"] / total if total > 0 else 0.0
    right_rate = m["total_right_hits"] / total if total > 0 else 0.0

    depth_s = summarize(m["depth_error_cm"], args.depth_gt_cm)
    reproj_l = summarize(m["reproj_left_px"])
    reproj_r = summarize(m["reproj_right_px"])

    summary = {
        "inputs": {
            "camchain": camchain_path,
            "capture": aedat4_path,
            "model": args.model,
            "depth_gt_cm": float(args.depth_gt_cm),
            "eval_windows_us": EVAL_WINDOWS_US,
            "detector": "findChessboardCornersSB",
        },
        "timing": {
            "recording_start_us": int(rec_start),
            "pattern_start_us": int(pattern_start),
            "pattern_end_us": int(pattern_end),
            "start_search": start_info,
            "end_search": end_info,
            "local_refinement": ref_info,
        },
        "counts": {
            "blocks": len(intervals),
            "transitions": total,
            "stereo_hits": stereo,
            "left_hits": m["total_left_hits"],
            "right_hits": m["total_right_hits"],
            "window_selection": {str(k): v for k, v in m["window_counts"].items()},
        },
        "headline_metrics": {
            "reprojection_error_px": {"left": reproj_l, "right": reproj_r},
            "stereo_depth_error_cm": depth_s,
        },
        "supporting_metrics": {
            "window_detection_rate": det_rate,
            "left_detection_rate": left_rate,
            "right_detection_rate": right_rate,
        },
        "debug": {"example_images": m["debug_examples"], "timing_plot": debug_plot},
    }

    out = os.path.join(args.out_dir, "summary.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    def _f(label, s, keys):
        if s is None:
            return f"{label}: n/a"
        return f"{label}: " + ", ".join(f"{k}={s[k]:.4f}" for k in keys if k in s)

    print(
        f"\n-> {out}\n"
        f"Window selection: {m['window_counts']}\n"
        f"Detection: stereo={det_rate:.1%} left={left_rate:.1%} right={right_rate:.1%}\n"
        + _f("Reproj L", reproj_l, ("mean", "p95")) + "\n"
        + _f("Reproj R", reproj_r, ("mean", "p95")) + "\n"
        + _f("Depth err", depth_s, ("mae_cm", "bias_cm", "rmse_cm"))
    )


if __name__ == "__main__":
    main()
