import os


def require_branch_root(path: str) -> str:
    branch_root = os.path.abspath(path)
    if not os.path.isdir(branch_root):
        raise FileNotFoundError(f"Branch root not found: {branch_root}")
    if not os.path.isdir(os.path.join(branch_root, "raw")):
        raise FileNotFoundError(f"Expected branch root with raw/: {branch_root}")
    return branch_root


def require_raw_dir(branch_root: str) -> str:
    branch_root = require_branch_root(branch_root)
    raw_dir = os.path.join(branch_root, "raw")
    if not os.path.isdir(raw_dir):
        raise FileNotFoundError(f"Raw directory not found in branch root: {branch_root}")
    return raw_dir


def require_recording_path(branch_root: str) -> str:
    recording_path = os.path.join(require_raw_dir(branch_root), "stereo_recording.aedat4")
    if not os.path.isfile(recording_path):
        raise FileNotFoundError(f"Recording not found in branch root: {recording_path}")
    return recording_path


def require_frames_dir(branch_root: str, model: str) -> str:
    branch_root = require_branch_root(branch_root)
    frames_dir = os.path.join(branch_root, "frames", model)
    if not os.path.isdir(frames_dir):
        raise FileNotFoundError(f"Frames directory not found for model '{model}': {frames_dir}")
    return frames_dir


def require_calibration_artifacts_dir(branch_root: str, model: str) -> str:
    branch_root = require_branch_root(branch_root)
    calibration_dir = os.path.join(branch_root, "calibration", model)
    if not os.path.isdir(calibration_dir):
        raise FileNotFoundError(
            f"Calibration directory not found for model '{model}': {calibration_dir}"
        )
    return calibration_dir


def require_stereo_camchain_path(branch_root: str, model: str) -> str:
    camchain_path = os.path.join(
        require_calibration_artifacts_dir(branch_root, model),
        "stereo_frames-camchain.yaml",
    )
    if not os.path.isfile(camchain_path):
        raise FileNotFoundError(
            f"Calibration branch has no stereo_frames-camchain.yaml for model '{model}': {camchain_path}"
        )
    return camchain_path


def find_stereo_imucamchain_path(branch_root: str, model: str) -> str | None:
    branch_root = require_branch_root(branch_root)
    camchain_path = os.path.join(
        branch_root,
        "calibration",
        model,
        "stereo_frames-camchain-imucam.yaml",
    )
    return camchain_path if os.path.isfile(camchain_path) else None
