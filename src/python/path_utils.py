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


def require_frames_dir(branch_root: str) -> str:
    branch_root = require_branch_root(branch_root)
    frames_dir = os.path.join(branch_root, "frames")
    if not os.path.isdir(frames_dir):
        raise FileNotFoundError(f"Frames directory not found in branch root: {branch_root}")
    return frames_dir


def require_stereo_camchain_path(branch_root: str) -> str:
    branch_root = require_branch_root(branch_root)
    camchain_path = os.path.join(branch_root, "stereo_frames-camchain.yaml")
    if not os.path.isfile(camchain_path):
        raise FileNotFoundError(
            f"Calibration branch has no stereo_frames-camchain.yaml: {branch_root}"
        )
    return camchain_path
