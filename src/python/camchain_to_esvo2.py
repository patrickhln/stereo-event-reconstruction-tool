""" Convert Kalibr camchain to ESVO2 calibration format.

ESVO2 calibration includes all ESVO fields plus T_b_c (body/IMU to camera transform).

Usage:
    python3 camchain_to_esvo2.py /path/to/session/calibrations/<calibration_name>
"""
import os
import argparse
import yaml
import numpy as np
import cv2

def load_camchain(camchain_path):
    with open(camchain_path, "r") as f:
        return yaml.safe_load(f)

def kalibr_to_camera_matrix(intrinsics):
    fx, fy, cx, cy = intrinsics
    return np.array([
        [fx, 0, cx],
        [0, fy, cy],
        [0, 0, 1]
    ], dtype=np.float64)

def kalibr_to_distortion(distortion_coeffs):
    return np.array(distortion_coeffs, dtype=np.float64)

def compute_stereo_rectification(K1, D1, K2, D2, R, T, image_size):
    """
    K1, K2: Camera matrices (3x3)
    D1, D2: Distortion coefficients
    R: Rotation matrx from cam0 to cam1 (3x3)
    T: Translation vector from cam0 to cam1 (3x1)
    image_size: (width, height)
    """

    # R1, R2, P1, P2, Q, roi1, roi2 = cv2.stereoRectify(
    R1, R2, P1, P2, _, _, _ = cv2.stereoRectify(
        K1, D1, K2, D2,
        image_size,
        R, T,
        flags=cv2.CALIB_ZERO_DISPARITY,
        alpha=0
    )
    return R1, R2, P1, P2

def matrix_to_yaml_data(matrix):
    return matrix.flatten().tolist()

def read_camera_metadata(raw_dir):
    path = os.path.join(raw_dir, "camera_metadata.txt")
    with open(path, "r") as f:
        lines = f.readlines()
    left_cam = lines[1].strip()
    left_width, left_height = map(int, lines[2].strip().split())
    right_cam = lines[3].strip()
    # right_width, right_height = map(int, lines[4].strip().split())
    
    return left_cam, right_cam, left_width, left_height

def write_esvo2_calib(output_path, camera_name, width, height, K, D, R_rect, P, T_right_left, T_b_c):
    """
    Write ESVO2-format calibration YAML.
    
    Args:
        output_path: Path to output .yaml file
        camera_name: Camera name string
        width, height: Image dimensions
        K: Camera matrix (3x3)
        D: Distortion coefficients
        R_rect: Rectification rotation (3x3)
        P: Projection matrix (3x4)
        T_right_left: Transform from right camera to left camera (3x4)
        T_b_c: Transform from body (IMU) to camera (3x4) - NEW for ESVO2
    """
    calib = {
        "image_width": int(width),
        "image_height": int(height),
        "camera_name": camera_name,
        "camera_matrix": {
            "rows": 3,
            "cols": 3,
            "data": matrix_to_yaml_data(K)
        },
        "distortion_model": "plumb_bob",
        "distortion_coefficients": {
            "rows": 1,
            "cols": len(D),
            "data": D.tolist()
        },
        "rectification_matrix": {
            "rows": 3,
            "cols": 3,
            "data": matrix_to_yaml_data(R_rect)
        },
        "projection_matrix": {
            "rows": 3,
            "cols": 4,
            "data": matrix_to_yaml_data(P)
        },
        "T_right_left": {
            "rows": 3,
            "cols": 4,
            "data": matrix_to_yaml_data(T_right_left)
        },
        # ESVO2-specific: Body (IMU) to Camera transform
        "T_b_c": {
            "rows": 3,
            "cols": 4,
            "data": matrix_to_yaml_data(T_b_c)
        }
    }
    with open(output_path, "w") as f:
        yaml.dump(calib, f, default_flow_style=False, sort_keys=False)

    print(f"Written: {output_path}")

def get_identity_T_b_c():
    """Return identity 3x4 transform (assumes IMU aligned with camera)."""
    return np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0]
    ], dtype=np.float64)

def load_transform_4x4(raw_transform, field_name):
    """Load and validate a 4x4 homogeneous transform from YAML data."""
    transform = np.array(raw_transform, dtype=np.float64)
    if transform.shape != (4, 4):
        raise ValueError(f"Expected {field_name} to be 4x4, got {transform.shape}")
    return transform


def load_imu_cam_calibration(camchain):
    """Extract T_b_c (imu/body -> camera) from Kalibr camchain data.

    - If `T_cam_imu` exists, Kalibr convention is camera <- imu, so it already
      matches ESVO2's expected imu/body -> camera transform.
    - If `T_imu_cam` exists, invert it to get imu/body -> camera.

    Returns:
        (T_b_c_3x4, source_string) or (None, None)
    """
    cam0 = camchain.get("cam0", {})

    if "T_cam_imu" in cam0:
        T_cam_imu = load_transform_4x4(cam0["T_cam_imu"], "T_cam_imu")
        return T_cam_imu[:3, :], "T_cam_imu"

    if "T_imu_cam" in cam0:
        T_imu_cam = load_transform_4x4(cam0["T_imu_cam"], "T_imu_cam")
        T_b_c_4x4 = np.linalg.inv(T_imu_cam)
        return T_b_c_4x4[:3, :], "inverse(T_imu_cam)"

    return None, None

def convert_camchain_to_esvo2(camchain_path, raw_dir, output_dir, imu_cam_calib_path=None):
    """
    Convert Kalibr camchain to ESVO2 format.
    
    Args:
        camchain_path: Path to Kalibr camchain.yaml (stereo calibration)
        raw_dir: Path to raw directory containing camera_metadata.txt
        output_dir: Output directory for left.yaml and right.yaml
        imu_cam_calib_path: Optional path to Kalibr IMU-cam calibration (camchain-imucam.yaml)
    """
    left_cam, right_cam, width, height = read_camera_metadata(raw_dir)

    os.makedirs(output_dir, exist_ok=True)

    camchain = load_camchain(camchain_path)

    cam0 = camchain["cam0"]
    cam1 = camchain["cam1"]

    width, height = cam0["resolution"]

    K0 = kalibr_to_camera_matrix(cam0["intrinsics"])
    K1 = kalibr_to_camera_matrix(cam1["intrinsics"])

    D0 = kalibr_to_distortion(cam0["distortion_coeffs"])
    D1 = kalibr_to_distortion(cam1["distortion_coeffs"])

    T_cn_cnm1 = np.array(cam1["T_cn_cnm1"])  # 4x4
    R = T_cn_cnm1[:3, :3]
    T = T_cn_cnm1[:3, 3:4]

    print(f"Image size: {width}x{height}")
    print(f"Baseline: {np.linalg.norm(T):.4f} m")

    R0, R1, P0, P1 = compute_stereo_rectification(
        K0, D0, K1, D1, R, T, (width, height)
    )

    # T_right_left for ESVO2 (same as ESVO)
    # Kalibr's T_cn_cnm1 is T_left_to_right (cam0 -> cam1)
    # ESVO expects T_right_left = T_right_to_left (cam1 -> cam0) = inverse
    R_inv = R.T
    T_inv = -R.T @ T
    T_right_left = np.hstack([R_inv, T_inv])
    
    print(f"T_right_left translation: [{T_right_left[0,3]:.4f}, {T_right_left[1,3]:.4f}, {T_right_left[2,3]:.4f}]")

    # Load or generate T_b_c (IMU to camera transform)
    T_b_c = None
    t_b_c_source = None
    
    # First try to load from camchain (in case it's a camchain-imucam.yaml)
    T_b_c, t_b_c_source = load_imu_cam_calibration(camchain)
    
    # If not found in stereo camchain, load from optional IMU-cam calib file
    if T_b_c is None:
        if imu_cam_calib_path and os.path.exists(imu_cam_calib_path):
            imu_cam_chain = load_camchain(imu_cam_calib_path)
            T_b_c, t_b_c_source = load_imu_cam_calibration(imu_cam_chain)

    if T_b_c is None:
        T_b_c = get_identity_T_b_c()
        print("Using identity T_b_c (no IMU-camera calibration found)")
        print("  Note: For proper IMU integration, run Kalibr IMU-camera calibration")
    else:
        print(f"Loaded T_b_c from IMU-camera calibration ({t_b_c_source})")
        print(f"  Translation: [{T_b_c[0,3]:.4f}, {T_b_c[1,3]:.4f}, {T_b_c[2,3]:.4f}]")

    write_esvo2_calib(
        os.path.join(output_dir, "left.yaml"),
        camera_name=f"{left_cam}_left",
        width=width, height=height,
        K=K0, D=D0, R_rect=R0, P=P0,
        T_right_left=T_right_left,
        T_b_c=T_b_c
    )
    write_esvo2_calib(
        os.path.join(output_dir, "right.yaml"),
        camera_name=f"{right_cam}_right",
        width=width, height=height,
        K=K1, D=D1, R_rect=R1, P=P1,
        T_right_left=T_right_left,
        T_b_c=T_b_c
    )
    print(f"\nESVO2 calibration written to: {output_dir}")

def main():
    parser = argparse.ArgumentParser(
        description="Convert Kalibr camchain to ESVO2 calibration format"
    )
    parser.add_argument("calibration_path", help="Path to calibration directory")
    args = parser.parse_args()

    calib = os.path.abspath(args.calibration_path)
    camchain = next((os.path.join(calib, f) for f in ["stereo_frames-camchain.yaml", "camchain.yaml"] if os.path.exists(os.path.join(calib, f))), None)
    if not camchain:
        raise FileNotFoundError(f"No camchain.yaml in {calib}")

    # find session root and output 
    current = calib
    while current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, "session.yaml")):
            output_dir = os.path.join(current, "config", "esvo2")
            break
        current = os.path.dirname(current)
    else:
        raise FileNotFoundError(f"No session.yaml found above {calib}")

    camchain_stem, camchain_ext = os.path.splitext(os.path.basename(camchain))
    imu_cam_calib = next(
        (
            path
            for path in [
                os.path.join(calib, f"{camchain_stem}-imucam{camchain_ext}"),
                os.path.join(calib, "camchain-imucam.yaml"),
            ]
            if os.path.exists(path)
        ),
        None,
    )

    convert_camchain_to_esvo2(camchain, os.path.join(calib, "raw"), output_dir, imu_cam_calib)


if __name__ == "__main__":
    main()
