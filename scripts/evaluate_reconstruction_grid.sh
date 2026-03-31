#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

# Filter stems — each must have a matching $SESSION/config/filters/<stem>.yaml.
# The script always includes the unfiltered branch.
FILTER_STEMS=(
    "hot_only"
    "hot_then_ba"
    "hot_then_k"
)

# Render model used for ESVO and ESVO2.
MODEL="e2vidplus"

# Render models for RTAB-Map — each produces its own reconstruction directory.
RTABMAP_MODELS=(
    "e2vid"
	"e2vidplus"
    "firenet"
)

# Usage:
#   ./scripts/evaluate_reconstruction_grid.sh <session> <scene_name> \
#       <calibration_branch> [reference.pcd]
#
# Example:
#   ./scripts/evaluate_reconstruction_grid.sh session_mar_17 \
#       kaffee_kueche_02 \
#       big_checkerboard_after_fix_01/filtered_hot_then_ba
#
# By default (RUN_EVAL=0) the script only runs reconstructions and saves
# point clouds.  Set RUN_EVAL=1 to also run reference cloud comparison.
#
# Environment overrides:
#   METHODS          subset of methods to run (default: "esvo esvo2 rtabmap")
#   PLAYBACK_RATE    bag playback rate (default: 0.2)
#   MIN_DEPTH        min depth in meters for ESVO/ESVO2 (default: 0.5)
#   MAX_DEPTH        max depth in meters for ESVO/ESVO2 (default: 5.0)
#   FORCE            re-run even if outputs already exist (default: 0)
#   EVAL_VOXEL       common evaluation voxel size in meters (default: 0.02)
#   REFERENCE_LANDMARKS  override cached reference landmark JSON path
#   RESULTS_ROOT     override the results directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/lib/path_utils.sh"

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
say() { printf '\n==> %s\n' "$*"; }

BUILD_DIR="${BUILD_DIR:-$ROOT_DIR/build/Release}"
SERT="${SERT:-$BUILD_DIR/sert}"
SESSION_INPUT="${1:-session_mar_17}"
SCENE_INPUT="${2:-kaffee_kueche_02}"
CALIB_BRANCH_INPUT="${3:-big_checkerboard_after_fix_01/filtered_hot_then_ba}"
REFERENCE_PCD_INPUT="${4:-$ROOT_DIR/src/python/evaluation/point_cloud/reference_point_cloud.pcd}"
METHODS_SPEC="${METHODS:-esvo esvo2 rtabmap}"
PLAYBACK_RATE="${PLAYBACK_RATE:-0.2}"
MIN_DEPTH="${MIN_DEPTH:-0.7}"
MAX_DEPTH="${MAX_DEPTH:-4.0}"
FORCE="${FORCE:-0}"
RUN_EVAL="${RUN_EVAL:-0}"
EVAL_VOXEL="${EVAL_VOXEL:-0.02}"
REFERENCE_LANDMARKS="${REFERENCE_LANDMARKS:-}"

[[ -x "$SERT" ]] || die "SERT binary not found: $SERT"

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

resolve_scene_group() {
    local session_root="$1" candidate="$2" path
    if [[ -d "$candidate" ]]; then
        path="$(realpath "$candidate")"
    elif [[ -d "$session_root/scenes/$candidate" ]]; then
        path="$(realpath "$session_root/scenes/$candidate")"
    else
        return 1
    fi
    [[ -d "$path/raw" ]] && path="$(dirname "$path")"
    [[ -d "$path/unfiltered/raw" ]] || return 1
    printf '%s\n' "$path"
}

resolve_calib_branch() {
    local session_root="$1" candidate="$2" path
    if [[ -d "$candidate" ]]; then
        path="$(realpath "$candidate")"
    elif [[ -d "$session_root/calibrations/$candidate" ]]; then
        path="$(realpath "$session_root/calibrations/$candidate")"
    else
        return 1
    fi
    [[ -d "$path/raw" ]] || return 1
    printf '%s\n' "$path"
}

SESSION="$(resolve_session "$SESSION_INPUT")" || die "Session not found: $SESSION_INPUT"

SCENE_GROUP="$(resolve_scene_group "$SESSION" "$SCENE_INPUT")" \
    || die "Scene group not found or invalid: $SCENE_INPUT"
SCENE_NAME="$(basename "$SCENE_GROUP")"

CALIB_BRANCH="$(resolve_calib_branch "$SESSION" "$CALIB_BRANCH_INPUT")" \
    || die "Calibration branch not found: $CALIB_BRANCH_INPUT"

if [[ "$RUN_EVAL" == 1 ]]; then
    [[ -f "$REFERENCE_PCD_INPUT" ]] || die "Reference point cloud not found: $REFERENCE_PCD_INPUT"
    REFERENCE_PCD="$(realpath "$REFERENCE_PCD_INPUT")"
fi

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    die "python3/python not found"
fi

command -v conda >/dev/null 2>&1 || die "conda not found; the sert-python environment is required"

read -r -a METHODS <<< "$METHODS_SPEC"
(( ${#METHODS[@]} > 0 ))     || die "No methods configured"
(( ${#FILTER_STEMS[@]} > 0 )) || die "FILTER_STEMS is empty"

for stem in "${FILTER_STEMS[@]}"; do
    cfg="$SESSION/config/filters/${stem}.yaml"
    [[ -f "$cfg" ]] || die "Filter config not found: $cfg"
done

if [[ " ${METHODS[*]} " =~ " rtabmap " ]]; then
    for m in "${RTABMAP_MODELS[@]}"; do
        camchain="$CALIB_BRANCH/calibration/$m/stereo_frames-camchain.yaml"
        [[ -f "$camchain" ]] || die "RTAB-Map camchain not found: $camchain"
    done
fi

BASE_BRANCH="$SCENE_GROUP/unfiltered"
BRANCHES=("$BASE_BRANCH")
for stem in "${FILTER_STEMS[@]}"; do
    BRANCHES+=("$SCENE_GROUP/filtered_${stem}")
done

RESULTS_ROOT="${RESULTS_ROOT:-$SESSION/evaluation/reconstruction_grid/$SCENE_NAME}"
TABLE_DIR="$RESULTS_ROOT/tables"
LOG_DIR="$RESULTS_ROOT/logs"
mkdir -p "$TABLE_DIR" "$LOG_DIR/reconstruction"
[[ "$RUN_EVAL" == 1 ]] && mkdir -p "$RESULTS_ROOT/evaluation" "$LOG_DIR/evaluation"

REFERENCE_LANDMARK_ARGS=()
if [[ -n "$REFERENCE_LANDMARKS" ]]; then
    REFERENCE_LANDMARK_ARGS=(--reference-landmarks "$REFERENCE_LANDMARKS")
fi

say "Configuration"
printf '  Session:        %s\n' "$SESSION"
printf '  Scene:          %s\n' "$SCENE_GROUP"
printf '  Calibration:    %s\n' "$CALIB_BRANCH"
printf '  Model (ESVO):   %s\n' "$MODEL"
printf '  RTAB-Map models: %s\n' "${RTABMAP_MODELS[*]}"
printf '  Methods:        %s\n' "${METHODS[*]}"
printf '  Filters:        unfiltered  %s\n' "${FILTER_STEMS[*]}"
printf '  Eval voxel:     %s m\n' "$EVAL_VOXEL"
printf '  Mode:           %s\n' "$( [[ "$RUN_EVAL" == 1 ]] && echo "reconstruct + evaluate" || echo "reconstruct only" )"

say "Ensuring filtered scene branches exist"
for stem in "${FILTER_STEMS[@]}"; do
    branch="$SCENE_GROUP/filtered_${stem}"
    if [[ -d "$branch/raw" ]]; then
        printf '  - reuse %s\n' "$(basename "$branch")"
    else
        printf '  - create %s\n' "$(basename "$branch")"
        "$SERT" filter "$SCENE_GROUP" --config "$SESSION/config/filters/${stem}.yaml"
    fi
done

FAILED=0

in_array() {
    local needle="$1"; shift
    local item
    for item in "$@"; do [[ "$item" == "$needle" ]] && return 0; done
    return 1
}

has_rtabmap_pc() {
    local branch="$1" model="$2"
    [[ -f "$branch/reconstruction/rtabmap_${model}/pointcloud.pcd" ]] \
    || [[ -f "$branch/reconstruction/rtabmap_${model}/pointcloud_cloud.ply" ]]
}

find_rtabmap_pc() {
    local branch="$1" model="$2"
    if [[ -f "$branch/reconstruction/rtabmap_${model}/pointcloud.pcd" ]]; then
        printf '%s\n' "$branch/reconstruction/rtabmap_${model}/pointcloud.pcd"
    elif [[ -f "$branch/reconstruction/rtabmap_${model}/pointcloud_cloud.ply" ]]; then
        printf '%s\n' "$branch/reconstruction/rtabmap_${model}/pointcloud_cloud.ply"
    fi
}

say "Running reconstructions: ${#BRANCHES[@]} branches x (${METHODS[*]})"

for branch in "${BRANCHES[@]}"; do
    branch_name="$(basename "$branch")"
    say "Branch: $branch_name"

    if in_array "esvo" "${METHODS[@]}"; then
        pc="$branch/reconstruction/esvo/pointcloud.pcd"
        log="$LOG_DIR/reconstruction/${branch_name}__esvo.log"
        if [[ "$FORCE" == 0 && -f "$pc" ]]; then
            printf '  skip esvo: pointcloud already exists\n'
        else
            printf '  esvo (model=%s) -> %s\n' "$MODEL" "$log"
            (
                "$SCRIPT_DIR/run_esvo.sh" "$branch" "$CALIB_BRANCH" \
                    --model "$MODEL" \
                    --rate "$PLAYBACK_RATE" \
                    --min-depth "$MIN_DEPTH" \
                    --max-depth "$MAX_DEPTH" \
                    --save-pc --no-viz
            ) >"$log" 2>&1 && printf '  esvo: done\n' || {
                printf 'FAILED esvo on %s -> %s\n' "$branch_name" "$log" >&2
                FAILED=1
            }
        fi
    fi

    if in_array "esvo2" "${METHODS[@]}"; then
        pc="$branch/reconstruction/esvo2/pointcloud.pcd"
        log="$LOG_DIR/reconstruction/${branch_name}__esvo2.log"
        if [[ "$FORCE" == 0 && -f "$pc" ]]; then
            printf '  skip esvo2: pointcloud already exists\n'
        else
            printf '  esvo2 (model=%s) -> %s\n' "$MODEL" "$log"
            (
                "$SCRIPT_DIR/run_esvo2.sh" "$branch" "$CALIB_BRANCH" \
                    --model "$MODEL" \
                    --rate "$PLAYBACK_RATE" \
                    --min-depth "$MIN_DEPTH" \
                    --max-depth "$MAX_DEPTH" \
                    --save-pc --no-viz
            ) >"$log" 2>&1 && printf '  esvo2: done\n' || {
                printf 'FAILED esvo2 on %s -> %s\n' "$branch_name" "$log" >&2
                FAILED=1
            }
        fi
    fi

    if in_array "rtabmap" "${METHODS[@]}"; then
        for rtm in "${RTABMAP_MODELS[@]}"; do
            dst_dir="$branch/reconstruction/rtabmap_${rtm}"
            log="$LOG_DIR/reconstruction/${branch_name}__rtabmap_${rtm}.log"

            if [[ "$FORCE" == 0 ]] && has_rtabmap_pc "$branch" "$rtm"; then
                printf '  skip rtabmap-%s: pointcloud already exists\n' "$rtm"
                continue
            fi

            printf '  rtabmap (model=%s) -> %s\n' "$rtm" "$log"
            (
                if [[ "$FORCE" == 1 \
                      || ! -d "$branch/frames/$rtm/left" \
                      || ! -d "$branch/frames/$rtm/right" ]]; then
                    echo "[rtabmap-${rtm}] Rendering frames"
                    "$SERT" render "$branch" --model "$rtm"
                else
                    echo "[rtabmap-${rtm}] skip render: frames already exist"
                fi

                bag_file="$branch/intermediate/stereo_frames_${rtm}.bag"
                camchain="$CALIB_BRANCH/calibration/$rtm/stereo_frames-camchain.yaml"
                if [[ "$FORCE" == 1 || ! -f "$bag_file" ]]; then
                    echo "[rtabmap-${rtm}] Creating stereo frame bag"
                    conda run --no-capture-output -n sert-python \
                        python3 -u "$ROOT_DIR/src/python/stereo_frames_to_rosbag.py" \
                        --path "$branch" --model "$rtm" \
                        --camchain "$camchain"
                else
                    echo "[rtabmap-${rtm}] skip bag: already exists"
                fi

                "$SCRIPT_DIR/run_rtabmap.sh" "$branch" \
                    --model "$rtm" \
                    --rate "$PLAYBACK_RATE" \
                    --save-pc --no-viz

                # rtabmap always writes to reconstruction/rtabmap/; move to model-specific dir
                src_dir="$branch/reconstruction/rtabmap"
                if [[ -d "$src_dir" ]]; then
                    rm -rf "$dst_dir"
                    mv "$src_dir" "$dst_dir"
                    echo "[rtabmap-${rtm}] Output saved to $(basename "$dst_dir")"
                fi
            ) >"$log" 2>&1 && printf '  rtabmap-%s: done\n' "$rtm" || {
                printf 'FAILED rtabmap-%s on %s -> %s\n' "$rtm" "$branch_name" "$log" >&2
                FAILED=1
            }
        done
    fi
done

(( FAILED == 0 )) || say "WARNING: Some reconstructions failed; check $LOG_DIR/reconstruction"

if [[ "$RUN_EVAL" != 1 ]]; then
    say "Reconstruction complete (RUN_EVAL=0 — skipping reference comparison)"
    printf 'Produced point clouds:\n'

    for branch in "${BRANCHES[@]}"; do
        branch_name="$(basename "$branch")"
        for method in "${METHODS[@]}"; do
            case "$method" in
                esvo)
                    pc="$branch/reconstruction/esvo/pointcloud.pcd"
                    [[ -f "$pc" ]] && printf '  [ok] %s / esvo\n' "$branch_name" \
                                   || printf '  [--] %s / esvo\n' "$branch_name"
                    ;;
                esvo2)
                    pc="$branch/reconstruction/esvo2/pointcloud.pcd"
                    [[ -f "$pc" ]] && printf '  [ok] %s / esvo2\n' "$branch_name" \
                                   || printf '  [--] %s / esvo2\n' "$branch_name"
                    ;;
                rtabmap)
                    for rtm in "${RTABMAP_MODELS[@]}"; do
                        pc="$(find_rtabmap_pc "$branch" "$rtm")"
                        if [[ -n "$pc" && -f "$pc" ]]; then
                            printf '  [ok] %s / rtabmap-%s\n' "$branch_name" "$rtm"
                        else
                            printf '  [--] %s / rtabmap-%s\n' "$branch_name" "$rtm"
                        fi
                    done
                    ;;
            esac
        done
    done

    say "Done"
    printf 'Results root: %s\n' "$RESULTS_ROOT"
    printf 'Logs:         %s\n' "$LOG_DIR"
    printf '\nTo run reference comparison: RUN_EVAL=1 %s\n' "$0 $*"
    exit 0
fi

say "Evaluating point clouds against reference (interactive alignment)"

for branch in "${BRANCHES[@]}"; do
    branch_name="$(basename "$branch")"
    for method in "${METHODS[@]}"; do
        case "$method" in
            esvo|esvo2)
                pc_file="$branch/reconstruction/${method}/pointcloud.pcd"
                method_label="$method"
                ;;
            rtabmap)
                for rtm in "${RTABMAP_MODELS[@]}"; do
                    pc_file="$(find_rtabmap_pc "$branch" "$rtm")"
                    method_label="rtabmap_${rtm}"
                    out_dir="$RESULTS_ROOT/evaluation/$branch_name/$method_label"
                    out_json="$out_dir/evaluation_${method_label}.json"
                    log="$LOG_DIR/evaluation/${branch_name}__${method_label}.log"
                    mkdir -p "$out_dir"

                    if [[ -z "$pc_file" || ! -f "$pc_file" ]]; then
                        printf '  skip eval: no pointcloud for %s / %s\n' \
                            "$branch_name" "$method_label"
                        continue
                    fi
                    if [[ "$FORCE" == 0 && -f "$out_json" ]]; then
                        printf '  skip eval: %s already exists\n' "$out_json"
                        continue
                    fi

                    say "Evaluating: $branch_name / $method_label"
                    printf '  reconstructed: %s\n' "$pc_file"

                    conda run --no-capture-output -n sert-python \
                        python3 -u \
                        "$ROOT_DIR/src/python/evaluation/point_cloud/reference_cloud_evaluation.py" \
                        --reference "$REFERENCE_PCD" \
                        --reconstructed "$pc_file" \
                        --method "$method_label" \
                        --eval-voxel "$EVAL_VOXEL" \
                        "${REFERENCE_LANDMARK_ARGS[@]}" \
                        --output "$out_json" \
                    2>&1 | tee "$log" || {
                        printf 'FAILED evaluation: %s / %s -> %s\n' \
                            "$branch_name" "$method_label" "$log" >&2
                        FAILED=1
                    }
                done
                continue  # rtabmap handled inside loop above
                ;;
        esac

        out_dir="$RESULTS_ROOT/evaluation/$branch_name/$method_label"
        out_json="$out_dir/evaluation_${method_label}.json"
        log="$LOG_DIR/evaluation/${branch_name}__${method_label}.log"
        mkdir -p "$out_dir"

        if [[ ! -f "$pc_file" ]]; then
            printf '  skip eval: no pointcloud for %s / %s\n' \
                "$branch_name" "$method_label"
            continue
        fi
        if [[ "$FORCE" == 0 && -f "$out_json" ]]; then
            printf '  skip eval: %s already exists\n' "$out_json"
            continue
        fi

        say "Evaluating: $branch_name / $method_label"
        printf '  reconstructed: %s\n' "$pc_file"

        conda run --no-capture-output -n sert-python \
            python3 -u \
            "$ROOT_DIR/src/python/evaluation/point_cloud/reference_cloud_evaluation.py" \
            --reference "$REFERENCE_PCD" \
            --reconstructed "$pc_file" \
            --method "$method_label" \
            --eval-voxel "$EVAL_VOXEL" \
            "${REFERENCE_LANDMARK_ARGS[@]}" \
            --output "$out_json" \
        2>&1 | tee "$log" || {
            printf 'FAILED evaluation: %s / %s -> %s\n' \
                "$branch_name" "$method_label" "$log" >&2
            FAILED=1
        }
    done
done

say "Writing summary tables"
RESULTS_ROOT="$RESULTS_ROOT" TABLE_DIR="$TABLE_DIR" "$PYTHON_BIN" - <<'PY'
import csv
import json
import os
from pathlib import Path

root = Path(os.environ["RESULTS_ROOT"])
table_dir = Path(os.environ["TABLE_DIR"])
table_dir.mkdir(parents=True, exist_ok=True)


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        return
    fieldnames = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def branch_key(name):
    return (name != "unfiltered", name)


rows = []
for path in sorted(root.glob("evaluation/*/*/evaluation_*.json")):
    branch = path.parts[-3]
    method = path.parts[-2]
    data = json.loads(path.read_text(encoding="utf-8"))
    m = data.get("metrics", {})

    row = {
        "filter_branch": branch,
        "method": method,
        "rmse_error_cm": m.get("rmse_error_cm"),
        "median_error_cm": m.get("median_error_cm"),
        "precision_at_2cm": m.get("precision_at_2cm"),
        "precision_at_5cm": m.get("precision_at_5cm"),
        "evaluated_reconstructed_point_count": m.get("evaluated_reconstructed_point_count"),
    }

    rows.append(row)

if not rows:
    print("No evaluation results found. Skipping summary tables.")
else:
    rows.sort(key=lambda r: (branch_key(r["filter_branch"]), r["method"]))
    write_csv(table_dir / "per_method.csv", rows)

    branches = sorted({r["filter_branch"] for r in rows}, key=branch_key)
    methods = sorted({r["method"] for r in rows})
    lookup = {(r["filter_branch"], r["method"]): r for r in rows}

    matrices = {
        "rmse_error_cm": "matrix_rmse_error_cm.csv",
        "median_error_cm": "matrix_median_error_cm.csv",
        "precision_at_2cm": "matrix_precision_at_2cm.csv",
        "precision_at_5cm": "matrix_precision_at_5cm.csv",
        "evaluated_reconstructed_point_count": "matrix_evaluated_reconstructed_point_count.csv",
    }

    for metric, filename in matrices.items():
        with (table_dir / filename).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["filter_branch", *methods])
            for branch in branches:
                writer.writerow([
                    branch,
                    *[fmt((lookup.get((branch, m)) or {}).get(metric))
                      for m in methods],
                ])

    print(f"Summary: {len(rows)} evaluations across "
          f"{len(branches)} branches x {len(methods)} methods")
PY

say "Done"
printf 'Results root: %s\n' "$RESULTS_ROOT"
printf 'Tables:       %s\n' "$TABLE_DIR"
printf 'Logs:         %s\n' "$LOG_DIR"
