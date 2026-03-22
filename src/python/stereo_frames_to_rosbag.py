import os
import numpy as np
import argparse
import cv2
import yaml
from rosbags.typesys import Stores, get_typestore
from rosbags.rosbag1 import Writer

from path_utils import require_branch_root, require_frames_dir

def load_frames_and_timestamps(frames_path):
    if os.path.exists(frames_path):
        frames_path_list = sorted([
            os.path.join(frames_path, f)
            for f in os.listdir(frames_path)
            if f.endswith(".png")
        ])
        timestamps_file_path = os.path.join(frames_path, "timestamps.txt") 
        if os.path.exists(timestamps_file_path):
            try:
                # rpg_e2vid format: one float timestamp per line
                timestamps = np.loadtxt(timestamps_file_path, ndmin=1)
            except ValueError:
                # event_cnn_minimal format: "frame_xxx.png <timestamp>"
                timestamps = np.loadtxt(timestamps_file_path, usecols=1, ndmin=1)
            assert len(frames_path_list) == len(timestamps), "Frame/timestamp count mismatch!"
            return frames_path_list, timestamps
        else:
            raise FileNotFoundError(f"Could not find timestamps.txt under path: {timestamps_file_path}")
    else:
        raise FileNotFoundError(f"Path {frames_path} does not exists.")
    
def match_stereo_pairs(left_ts, right_ts, max_diff_ms=10.0):
    # Match left and right frames by closest timestamp
    # left_ts: array of left timestamps
    # right_ts: array of right timestamps
    # max_diff_ms: Maxumum allowed time difference for matching
    # keep in mind: save the actual timestamp of each frame still in the .bag
    # and let kalibr --approx-sync handle the rest for now
    max_diff_sec = max_diff_ms / 1000.0
    pairs = []
    missed = 0

    max_diff_occured = 0

    for left_idx, left_t in enumerate(left_ts):
        time_diffs = np.abs(right_ts - left_t) 
        right_idx = np.argmin(time_diffs)

        if max_diff_occured < time_diffs[right_idx]:
            max_diff_occured = time_diffs[right_idx]

        right_matched_timestamp = right_ts[right_idx] 
        if time_diffs[right_idx] <= max_diff_sec:
            pairs.append((left_idx, right_idx, left_t, right_matched_timestamp))
        else:
            missed+=1

    print(f"Matched {len(pairs)} pairs, missed: {missed}")
    print(f"max_diff_occured: {max_diff_occured}")
    return pairs

def create_image_msg_from_array(img, timestamp_sec, frame_id, seq, typestore):
    """Build a ROS Image message from a numpy array (already processed)."""
    height, width = img.shape

    secs = int(timestamp_sec)
    nsecs = int((timestamp_sec - secs) * 1e9)

    ImageMsg = typestore.types['sensor_msgs/msg/Image']
    HeaderMsg = typestore.types['std_msgs/msg/Header']
    TimeMsg = typestore.types['builtin_interfaces/msg/Time']
    
    header = HeaderMsg(
        seq=seq,
        stamp=TimeMsg(sec=secs, nanosec=nsecs),
        frame_id=frame_id
    )
    
    return ImageMsg(
        header=header,
        height=height,
        width=width,
        encoding='mono8',
        is_bigendian=0,
        step=width,
        data=np.frombuffer(img.tobytes(), dtype=np.uint8)
    )


def create_image_msg(image_path, timestamp_sec, frame_id, seq, typestore):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Failed to read image: {image_path}")
    return create_image_msg_from_array(img, timestamp_sec, frame_id, seq, typestore)


def load_camchain_for_camera_info(camchain_path):
    with open(camchain_path, "r") as f:
        camchain = yaml.safe_load(f)

    cam0 = camchain["cam0"]
    cam1 = camchain["cam1"]

    width, height = cam0["resolution"]

    fx0, fy0, cx0, cy0 = cam0["intrinsics"]
    fx1, fy1, cx1, cy1 = cam1["intrinsics"]

    K0 = np.array([[fx0, 0.0, cx0], [0.0, fy0, cy0], [0.0, 0.0, 1.0]], dtype=np.float64)
    K1 = np.array([[fx1, 0.0, cx1], [0.0, fy1, cy1], [0.0, 0.0, 1.0]], dtype=np.float64)
    D0 = np.array(cam0["distortion_coeffs"], dtype=np.float64)
    D1 = np.array(cam1["distortion_coeffs"], dtype=np.float64)

    T_cn_cnm1 = np.array(cam1["T_cn_cnm1"], dtype=np.float64)
    R = T_cn_cnm1[:3, :3]
    T = T_cn_cnm1[:3, 3:4]

    R0, R1, P0, P1, _, _, _ = cv2.stereoRectify(
        K0, D0, K1, D1, (int(width), int(height)), R, T, flags=cv2.CALIB_ZERO_DISPARITY, alpha=0
    )

    return {
        "left": {
            "width": int(width),
            "height": int(height),
            "K": K0,
            "D": D0,
            "R": R0,
            "P": P0,
        },
        "right": {
            "width": int(width),
            "height": int(height),
            "K": K1,
            "D": D1,
            "R": R1,
            "P": P1,
        },
    }


def create_camera_info_msg(calib, timestamp_sec, frame_id, seq, typestore):
    CameraInfoMsg = typestore.types["sensor_msgs/msg/CameraInfo"]
    HeaderMsg = typestore.types["std_msgs/msg/Header"]
    TimeMsg = typestore.types["builtin_interfaces/msg/Time"]
    RegionOfInterestMsg = typestore.types["sensor_msgs/msg/RegionOfInterest"]

    secs = int(timestamp_sec)
    nsecs = int((timestamp_sec - secs) * 1e9)

    header = HeaderMsg(
        seq=seq,
        stamp=TimeMsg(sec=secs, nanosec=nsecs),
        frame_id=frame_id
    )

    roi = RegionOfInterestMsg(
        x_offset=0,
        y_offset=0,
        height=0,
        width=0,
        do_rectify=False
    )

    return CameraInfoMsg(
        header=header,
        height=calib["height"],
        width=calib["width"],
        distortion_model="plumb_bob",
        D=np.array(calib["D"], dtype=np.float64),
        K=np.array(calib["K"], dtype=np.float64).reshape(-1),
        R=np.array(calib["R"], dtype=np.float64).reshape(-1),
        P=np.array(calib["P"], dtype=np.float64).reshape(-1),
        binning_x=0,
        binning_y=0,
        roi=roi
    )


def write_rosbag(output_path, pairs, left_frames_paths, right_frames_paths,
                 camera_calib=None):

    typestore = get_typestore(Stores.ROS1_NOETIC)
    IMAGE_TYPE = "sensor_msgs/msg/Image"
    CAMERA_INFO_TYPE = "sensor_msgs/msg/CameraInfo"

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    if os.path.exists(output_path):
        os.remove(output_path)
        print(f"Removed existing bag file: {output_path}")

    calib_for_bag = camera_calib
    with Writer(output_path) as bag:
        connection_left = bag.add_connection(
            topic="/cam0/image_raw",
            msgtype=typestore.types[IMAGE_TYPE].__msgtype__,
            typestore=typestore
        )
        connection_right = bag.add_connection(
            topic="/cam1/image_raw",
            msgtype=typestore.types[IMAGE_TYPE].__msgtype__,
            typestore=typestore
        )

        connection_left_info = None
        connection_right_info = None
        if calib_for_bag is not None:
            connection_left_info = bag.add_connection(
                topic="/cam0/camera_info",
                msgtype=typestore.types[CAMERA_INFO_TYPE].__msgtype__,
                typestore=typestore
            )
            connection_right_info = bag.add_connection(
                topic="/cam1/camera_info",
                msgtype=typestore.types[CAMERA_INFO_TYPE].__msgtype__,
                typestore=typestore
            )

        for seq, (left_idx, right_idx, left_t, right_t) in enumerate(pairs):
            left_msg = create_image_msg(left_frames_paths[left_idx], left_t, "cam0", seq, typestore)
            right_msg = create_image_msg(right_frames_paths[right_idx], right_t, "cam1", seq, typestore)
            
            left_bytes = typestore.serialize_ros1(left_msg, IMAGE_TYPE)
            right_bytes = typestore.serialize_ros1(right_msg, IMAGE_TYPE)

            bag.write(connection_left, int(left_t * 1e9), bytes(left_bytes))
            bag.write(connection_right, int(right_t * 1e9), bytes(right_bytes))

            if calib_for_bag is not None:
                assert connection_left_info is not None
                assert connection_right_info is not None
                left_info = create_camera_info_msg(calib_for_bag["left"], left_t, "cam0", seq, typestore)
                right_info = create_camera_info_msg(calib_for_bag["right"], right_t, "cam1", seq, typestore)

                left_info_bytes = typestore.serialize_ros1(left_info, CAMERA_INFO_TYPE)
                right_info_bytes = typestore.serialize_ros1(right_info, CAMERA_INFO_TYPE)

                bag.write(connection_left_info, int(left_t * 1e9), bytes(left_info_bytes))
                bag.write(connection_right_info, int(right_t * 1e9), bytes(right_info_bytes))
            
            if (seq + 1) % 100 == 0:
                print(f"Written {seq + 1}/{len(pairs)} pairs...")


def main():
    parser = argparse.ArgumentParser(description="Convert stereo frames to ROS bag")
    parser.add_argument("--path", required=True, help="Path to branch root")
    parser.add_argument("--model", required=True, help="Render model whose frames should be converted")
    parser.add_argument("--max_diff_ms", type=float, default=10.0, help="Max timestamp diff for matching timestamps of frames")
    parser.add_argument("--camchain", required=False, default=None, help="Kalibr camchain yaml (optional, adds camera_info)")

    args = parser.parse_args()

    branch_root = require_branch_root(args.path)
    frames_dir = require_frames_dir(branch_root, args.model)

    left_frames_path_list, left_timestamps = load_frames_and_timestamps(os.path.join(frames_dir, "left"))
    right_frames_path_list, right_timestamps = load_frames_and_timestamps(os.path.join(frames_dir, "right"))

    pairs = match_stereo_pairs(left_timestamps, right_timestamps, args.max_diff_ms)

    camera_calib = None
    if args.camchain:
        if not os.path.exists(args.camchain):
            raise FileNotFoundError(f"Camchain file not found: {args.camchain}")
        camera_calib = load_camchain_for_camera_info(args.camchain)
        print(f"Loaded camera calibration from: {args.camchain}")
    else:
        print("No --camchain provided. Writing image topics only (no camera_info).")

    write_rosbag(
        os.path.join(branch_root, "intermediate", f"stereo_frames_{args.model}.bag"),
        pairs,
        left_frames_path_list,
        right_frames_path_list,
        camera_calib=camera_calib,
    )

if __name__ == "__main__":
    main()
