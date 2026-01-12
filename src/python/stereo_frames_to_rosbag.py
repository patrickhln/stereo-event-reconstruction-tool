import os
import numpy as np
import argparse
import cv2
from rosbags.typesys import Stores, get_typestore
from rosbags.rosbag1 import Writer

def load_frames_and_timestamps(frames_path):
    if os.path.exists(frames_path):
        frames_path_list = sorted([
            os.path.join(frames_path, f)
            for f in os.listdir(frames_path)
            if f.endswith(".png")
        ])
        timestamps_file_path = os.path.join(frames_path, "timestamps.txt") 
        if os.path.exists(timestamps_file_path):
            timestamps = np.loadtxt(timestamps_file_path)
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

def create_image_msg(image_path, timestamp_sec, frame_id, seq, typestore):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
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

def write_rosbag(output_path, pairs, left_frames_paths, right_frames_paths):

    typestore = get_typestore(Stores.ROS1_NOETIC)
    IMAGE_TYPE = "sensor_msgs/msg/Image"

    if os.path.exists(output_path):
        os.remove(output_path)
        print(f"Removed existing bag file: {output_path}")

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

        for seq, (left_idx, right_idx, left_t, right_t) in enumerate(pairs):
            left_msg = create_image_msg(left_frames_paths[left_idx], left_t, "cam0", seq, typestore)
            right_msg = create_image_msg(right_frames_paths[right_idx], right_t, "cam1", seq, typestore)
            
            left_bytes = typestore.serialize_ros1(left_msg, IMAGE_TYPE)
            right_bytes = typestore.serialize_ros1(right_msg, IMAGE_TYPE)

            bag.write(connection_left, int(left_t * 1e9), bytes(left_bytes))
            bag.write(connection_right, int(right_t * 1e9), bytes(right_bytes))
            
            if (seq + 1) % 100 == 0:
                print(f"Written {seq + 1}/{len(pairs)} pairs...")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="Path to session folder (should contain reconstruction/left and reconstruction/right)")
    parser.add_argument("--max_diff_ms", type=float, default=10.0, help="Max timestamp diff for matching timestamps of frames")

    args = parser.parse_args()
    
    left_frames_path_list, left_timestamps = load_frames_and_timestamps(os.path.join(args.path, "reconstruction", "left"))
    right_frames_path_list, right_timestamps = load_frames_and_timestamps(os.path.join(args.path, "reconstruction", "right"))

    pairs = match_stereo_pairs(left_timestamps, right_timestamps, args.max_diff_ms)

    write_rosbag(os.path.join(args.path, "intermediate", "stereo_frames.bag"), pairs, left_frames_path_list, right_frames_path_list)

if __name__ == "__main__":
    main()
