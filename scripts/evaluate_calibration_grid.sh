#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/lib/path_utils.sh"

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
say() { printf '\n==> %s\n' "$*"; }

BUILD_DIR="${BUILD_DIR:-$ROOT_DIR/build/Release}"
SERT="${SERT:-$BUILD_DIR/sert}"
SESSION_INPUT="${1:-session_mar_17}"
CALIB_INPUT="${2:-big_checkerboard_after_fix_01}"
MODEL_SPEC="${MODELS:-e2vid e2vidplus e2vidplusupdate firenet}"
TARGET_SPEC="${TARGET_CONFIG:-8 6 0.068 0.068}"
MANIFEST="${MANIFEST:-$ROOT_DIR/src/python/evaluation/calibration/checkerboard_manifest.json}"
PIPELINE_JOBS="${PIPELINE_JOBS:-1}"
VALIDATION_JOBS="${VALIDATION_JOBS:-4}"
FORCE="${FORCE:-0}"

[[ -x "$SERT" ]] || die "SERT binary not found: $SERT"
[[ -f "$MANIFEST" ]] || die "Manifest not found: $MANIFEST"
[[ "$PIPELINE_JOBS" =~ ^[1-9][0-9]*$ ]] || die "PIPELINE_JOBS must be >= 1"
[[ "$VALIDATION_JOBS" =~ ^[1-9][0-9]*$ ]] || die "VALIDATION_JOBS must be >= 1"

resolve_session() {
    local candidate="$1"
    if [[ -d "$candidate" ]]; then
        realpath "$candidate"
    elif [[ -d "$BUILD_DIR/$candidate" ]]; then
        realpath "$BUILD_DIR/$candidate"
    else
        return 1
    fi
}

resolve_calibration_group() {
    local session_root="$1" candidate="$2" path
    if [[ -d "$candidate" ]]; then
        path="$(realpath "$candidate")"
    elif [[ -d "$session_root/calibrations/$candidate" ]]; then
        path="$(realpath "$session_root/calibrations/$candidate")"
    else
        return 1
    fi
    [[ -d "$path/raw" ]] && path="$(dirname "$path")"
    [[ -d "$path/unfiltered/raw" ]] || return 1
    printf '%s\n' "$path"
}

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    die "python3/python not found"
fi

command -v conda >/dev/null 2>&1 || die "conda not found; validation requires the sert-python environment"

SESSION="$(resolve_session "$SESSION_INPUT")" || die "Session not found: $SESSION_INPUT"
CALIB_GROUP="$(resolve_calibration_group "$SESSION" "$CALIB_INPUT")" \
    || die "Calibration group not found or invalid: $CALIB_INPUT"
CALIB_NAME="$(basename "$CALIB_GROUP")"
RESULTS_ROOT="${RESULTS_ROOT:-$SESSION/evaluation/calibration_grid/$CALIB_NAME}"
TABLE_DIR="$RESULTS_ROOT/tables"
LOG_DIR="$RESULTS_ROOT/logs"
mkdir -p "$RESULTS_ROOT/validation" "$TABLE_DIR" "$LOG_DIR/pipeline" "$LOG_DIR/validation"

read -r -a MODELS <<< "$MODEL_SPEC"
read -r -a TARGET_ARGS <<< "$TARGET_SPEC"
FILTER_CONFIGS=("$SESSION/config/filters"/*.yaml)
BASE_BRANCH="$CALIB_GROUP/unfiltered"
BRANCHES=("$BASE_BRANCH")

# scene_name | depth_cm | repeats
SCENES=(
    "blinking_pattern_120cm_01|120|3"
    "blinking_pattern_150cm_01|150|2"
)

for spec in "${SCENES[@]}"; do
    IFS='|' read -r sname _ _ <<< "$spec"
    [[ -d "$SESSION/scenes/$sname/unfiltered/raw" ]] \
        || die "Scene not found: $SESSION/scenes/$sname"
done

(( ${#MODELS[@]} > 0 )) || die "No models configured"

FAILED=0
throttle() {
    local limit="$1"
    while (( $(jobs -pr | wc -l) >= limit )); do
        wait -n || FAILED=1
    done
}
wait_all() {
    while (( $(jobs -pr | wc -l) > 0 )); do
        wait -n || FAILED=1
    done
}

pipeline_job() {
    local branch="$1" model="$2" branch_name log camchain
    branch_name="$(basename "$branch")"
    log="$LOG_DIR/pipeline/${branch_name}__${model}.log"
    {
        echo "[pipeline] branch=$branch_name model=$model"
        camchain="$branch/calibration/$model/stereo_frames-camchain.yaml"
        if [[ "$FORCE" == 0 && -f "$camchain" ]]; then
            echo "skip calibrate: $camchain already exists"
            return 0
        fi
        if [[ "$FORCE" == 1 || ! -d "$branch/frames/$model/left" || ! -d "$branch/frames/$model/right" ]]; then
            "$SERT" render "$branch" --model "$model"
        else
            echo "skip render: frames already exist"
        fi
        "$SERT" calibrate "$branch" --model "$model" -t checkerboard --config "${TARGET_ARGS[@]}"
    } >"$log" 2>&1 || {
        printf 'FAILED pipeline: %s / %s -> %s\n' "$branch_name" "$model" "$log" >&2
        return 1
    }
}

validation_job() {
    local calib_branch="$1" model="$2" depth_cm="$3" scene_name="$4" scene_branch="$5" repeats="$6"
    local branch_name out_dir log
    branch_name="$(basename "$calib_branch")"
    out_dir="$RESULTS_ROOT/validation/$branch_name/$model/$scene_name"
    log="$LOG_DIR/validation/${branch_name}__${model}__${scene_name}.log"
    {
        echo "[validate] calibration=$branch_name model=$model scene=$scene_name depth_cm=$depth_cm repeats=$repeats"
        if [[ "$FORCE" == 0 && -f "$out_dir/summary.json" ]]; then
            echo "skip validation: $out_dir/summary.json already exists"
            return 0
        fi
        args=(
            conda run --no-capture-output -n sert-python python3 -u
            "$ROOT_DIR/src/python/evaluation/calibration/calibration_validation.py"
            "$calib_branch" "$scene_branch"
            --model "$model"
            --manifest "$MANIFEST"
            --repeats "$repeats"
            --depth-gt-cm "$depth_cm"
            --out-dir "$out_dir"
        )
        [[ "$FORCE" == 1 ]] && args+=(--force-search)
        "${args[@]}"
    } >"$log" 2>&1 || {
        printf 'FAILED validation: %s / %s / %s -> %s\n' "$branch_name" "$model" "$scene_name" "$log" >&2
        return 1
    }
}

say "Session: $SESSION"
say "Calibration group: $CALIB_GROUP"
printf 'Models: %s\n' "${MODELS[*]}"

say "Ensuring filtered calibration branches exist"
for cfg in "${FILTER_CONFIGS[@]}"; do
    stem="$(basename "${cfg%.yaml}")"
    branch="$CALIB_GROUP/filtered_$stem"
    BRANCHES+=("$branch")
    if [[ -d "$branch/raw" ]]; then
        printf '  - reuse %s\n' "$(basename "$branch")"
    else
        printf '  - create %s\n' "$(basename "$branch")"
        "$SERT" filter "$CALIB_GROUP" --config "$cfg"
    fi
done

say "Rendering + calibrating ${#BRANCHES[@]} branches x ${#MODELS[@]} models"
for branch in "${BRANCHES[@]}"; do
    for model in "${MODELS[@]}"; do
        throttle "$PIPELINE_JOBS"
        pipeline_job "$branch" "$model" &
    done
done
wait_all
(( FAILED == 0 )) || die "Pipeline stage failed; inspect $LOG_DIR/pipeline"

say "Validating each calibration on raw blinking-pattern scenes"
for branch in "${BRANCHES[@]}"; do
    for model in "${MODELS[@]}"; do
        for spec in "${SCENES[@]}"; do
            IFS='|' read -r scene_name depth_cm scene_repeats <<< "$spec"
            throttle "$VALIDATION_JOBS"
            validation_job "$branch" "$model" "$depth_cm" "$scene_name" \
                "$SESSION/scenes/$scene_name/unfiltered" "$scene_repeats" &
        done
    done
done
wait_all
(( FAILED == 0 )) || die "Validation stage failed; inspect $LOG_DIR/validation"

say "Writing long-form and matrix summaries"
RESULTS_ROOT="$RESULTS_ROOT" TABLE_DIR="$TABLE_DIR" MODEL_ORDER="$(IFS=,; echo "${MODELS[*]}")" "$PYTHON_BIN" - <<'PY'
import csv
import json
import os
from pathlib import Path
from statistics import stdev

root = Path(os.environ["RESULTS_ROOT"])
table_dir = Path(os.environ["TABLE_DIR"])
model_order = [m for m in os.environ.get("MODEL_ORDER", "").split(",") if m]
table_dir.mkdir(parents=True, exist_ok=True)

def mean(vals):
    vals = [v for v in vals if v is not None]
    return None if not vals else sum(vals) / len(vals)

def std(vals):
    vals = [v for v in vals if v is not None]
    return None if len(vals) < 2 else stdev(vals)

def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

def fmt(v):
    return "" if v is None else f"{v:.6f}"

def branch_key(name):
    return (name != "unfiltered", name)

def model_key(name):
    return model_order.index(name) if name in model_order else len(model_order)

rows = []
for path in sorted(root.glob("validation/*/*/*/summary.json")):
    branch, model, scene = path.parts[-4:-1]
    data = json.loads(path.read_text(encoding="utf-8"))
    depth = (data.get("headline_metrics", {}) or {}).get("stereo_depth_error_cm") or {}
    reproj = (data.get("headline_metrics", {}) or {}).get("reprojection_error_px") or {}
    reproj_left = reproj.get("left") or {}
    reproj_right = reproj.get("right") or {}
    rows.append({
        "calibration_branch": branch,
        "model": model,
        "scene": scene,
        "depth_gt_cm": data["inputs"]["depth_gt_cm"],
        "window_detection_rate": data["supporting_metrics"]["window_detection_rate"],
        "reproj_left_mean_px": reproj_left.get("mean"),
        "reproj_right_mean_px": reproj_right.get("mean"),
        "depth_mae_cm": depth.get("mae_cm"),
        "depth_rmse_cm": depth.get("rmse_cm"),
        "depth_bias_cm": depth.get("bias_cm"),
        "camchain": data["inputs"]["camchain"],
        "summary_json": str(path),
    })

if not rows:
    raise SystemExit("No validation summaries found.")

rows.sort(key=lambda r: (branch_key(r["calibration_branch"]), model_key(r["model"]), r["depth_gt_cm"], r["scene"]))
write_csv(table_dir / "per_scene.csv", rows)

groups = {}
for row in rows:
    groups.setdefault((row["calibration_branch"], row["model"]), []).append(row)

aggregate = []
for (branch, model), items in sorted(groups.items(), key=lambda kv: (branch_key(kv[0][0]), model_key(kv[0][1]))):
    aggregate.append({
        "calibration_branch": branch,
        "model": model,
        "n_scenes": len(items),
        "reproj_left_mean_px_mean": mean(r["reproj_left_mean_px"] for r in items),
        "reproj_right_mean_px_mean": mean(r["reproj_right_mean_px"] for r in items),
        "depth_mae_cm_mean": mean(r["depth_mae_cm"] for r in items),
        "depth_rmse_cm_mean": mean(r["depth_rmse_cm"] for r in items),
        "depth_bias_cm_mean": mean(r["depth_bias_cm"] for r in items),
        "window_detection_rate_mean": mean(r["window_detection_rate"] for r in items),
    })

write_csv(table_dir / "aggregate_by_branch_model.csv", aggregate)

branches = sorted({row["calibration_branch"] for row in rows}, key=branch_key)
models = sorted({row["model"] for row in rows}, key=model_key)
lookup = {(row["calibration_branch"], row["model"]): row for row in aggregate}
matrices = {
    "reproj_left_mean_px_mean": "matrix_reproj_left_mean_px.csv",
    "reproj_right_mean_px_mean": "matrix_reproj_right_mean_px.csv",
    "depth_rmse_cm_mean": "matrix_depth_rmse_cm_mean.csv",
    "window_detection_rate_mean": "matrix_window_detection_rate_mean.csv",
}

for metric, filename in matrices.items():
    with (table_dir / filename).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["calibration_branch", *models])
        for branch in branches:
            writer.writerow([branch, *[fmt((lookup.get((branch, model)) or {}).get(metric)) for model in models]])

labels = {
    "reproj_left_mean_px_mean": "Reprojection Left [px]",
    "reproj_right_mean_px_mean": "Reprojection Right [px]",
    "depth_rmse_cm_mean": "Depth RMSE [cm]",
    "window_detection_rate_mean": "Detection Rate",
}

with (table_dir / "report.md").open("w", encoding="utf-8") as fh:
    fh.write(f"# Calibration Grid: {root.name}\n\n")
    fh.write(f"- Per-scene rows: {len(rows)}\n")
    fh.write(f"- Aggregated branch/model pairs: {len(aggregate)}\n\n")
    for metric, label in labels.items():
        fh.write(f"## {label}\n\n")
        fh.write("| calibration_branch | " + " | ".join(models) + " |\n")
        fh.write("|---|" + "|".join(["---"] * len(models)) + "|\n")
        for branch in branches:
            vals = [fmt((lookup.get((branch, model)) or {}).get(metric)) for model in models]
            fh.write("| " + branch + " | " + " | ".join(vals) + " |\n")
        fh.write("\n")
PY

say "Done"
printf 'Validation summaries: %s\n' "$RESULTS_ROOT/validation"
printf 'Tables: %s\n' "$TABLE_DIR"
printf 'Logs: %s\n' "$LOG_DIR"
