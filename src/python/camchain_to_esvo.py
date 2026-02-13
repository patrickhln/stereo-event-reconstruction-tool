import os
import argparse
import yaml
import numpy as np
import cv2

"""
Kalibr stereo_frames-camchain.yaml example:

cam0:
  cam_overlaps: [1]
  camera_model: pinhole
  distortion_coeffs: [-0.393755886723044, 0.1578236986777623, 0.001656356049571968, 0.00032067252192923034]
  distortion_model: radtan
  intrinsics: [509.05525532054565, 509.7717036288223, 315.04780418913816, 232.2210468373924]
  resolution: [640, 480]
  rostopic: /cam0/image_raw
cam1:
  T_cn_cnm1:
  - [0.9999545017667643, -0.0005117317293874756, -0.009525362303296779, -0.12854050294855657]
  - [0.0004824110669692113, 0.9999951397785822, -0.003080210831438786, -0.00017045688726975925]
  - [0.0095268922495426, 0.003075475547095976, 0.9999498886315327, -0.0013323862658618138]
  - [0.0, 0.0, 0.0, 1.0]
  cam_overlaps: [0]
  camera_model: pinhole
  distortion_coeffs: [-0.39361371002158435, 0.15666835551222588, 0.00027446219143602193, 0.00014280100552356733]
  distortion_model: radtan
  intrinsics: [511.17391465532654, 511.8852633487132, 318.37307957778876, 245.06985333202755]
  resolution: [640, 480]
  rostopic: /cam1/image_raw
"""

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

def write_esvo_calib(output_path, camera_name, width, height, K, D, R_rect, P, T_right_left): 
    """
    Write ESVO-format calibration YAML.
    
    Args:
        output_path: Path to output .yaml file
        camera_name: Camera name string
        width, height: Image dimensions
        K: Camera matrix (3x3)
        D: Distortion coefficients
        R_rect: Rectification rotation (3x3)
        P: Projection matrix (3x4)
        T_right_left: Transform from left to right (3x4) - REQUIRED for BOTH cameras!
    
    Note: ESVO expects T_right_left in BOTH left.yaml and right.yaml (same values)
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
        # T_right_left is ALWAYS included (same in both left.yaml and right.yaml)
        "T_right_left": {
            "rows": 3,
            "cols": 4,
            "data": matrix_to_yaml_data(T_right_left)
        }
    }
    with open(output_path, "w") as f:
        yaml.dump(calib, f, default_flow_style=False, sort_keys=False)

    print(f"Written: {output_path}")

def convert_camchain_to_esvo(camchain_path, raw_dir, output_dir):

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

    T_cn_cnm1 = np.array(cam1["T_cn_cnm1"]) # 4x4
    R = T_cn_cnm1[:3, :3] # Rotation
    T = T_cn_cnm1[:3, 3:4] # Translation (3x1)

    print(f"Image size: {width}x{height}")
    print(f"Baseline: {np.linalg.norm(T):.4f} m ")

    R0, R1, P0, P1 = compute_stereo_rectification(
        K0, D0, K1, D1, R, T, (width, height)
    )

    # T_right_left for ESVO (3x4 matrix)
    # CRITICAL: Kalibr's T_cn_cnm1 is T_left_to_right (cam0 -> cam1)
    # But ESVO expects T_right_left = T_right_to_left (cam1 -> cam0)
    # So we need to compute the INVERSE of T_cn_cnm1!
    # For rigid transform T = [R|t], inverse = [R^T | -R^T * t]
    R_inv = R.T
    T_inv = -R.T @ T
    T_right_left = np.hstack([R_inv, T_inv])
    
    # Verify: T_right_left should have POSITIVE x-translation (baseline)
    # if right camera is to the right of left camera
    print(f"T_right_left translation: [{T_right_left[0,3]:.4f}, {T_right_left[1,3]:.4f}, {T_right_left[2,3]:.4f}]")

    write_esvo_calib(
        os.path.join(output_dir, "left.yaml"),
        camera_name=f"{left_cam}_left",
        width=width, height=height,
        K=K0, D=D0, R_rect=R0, P=P0,
        T_right_left=T_right_left
    )
    write_esvo_calib(
        os.path.join(output_dir, "right.yaml"),
        camera_name=f"{right_cam}_right",
        width=width, height=height,
        K=K1, D=D1, R_rect=R1, P=P1,
        T_right_left=T_right_left
    )
    print(f"\nESVO calibration written to: {output_dir}")

def main():
    parser = argparse.ArgumentParser(
        description="Convert Kalibr camchain to ESVO calibration format"
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
            output = os.path.join(current, "config", "esvo")
            break
        current = os.path.dirname(current)
    else:
        raise FileNotFoundError(f"No session.yaml found above {calib}")
    
    convert_camchain_to_esvo(camchain, os.path.join(calib, "raw"), output)


if __name__ == "__main__":
    main()
