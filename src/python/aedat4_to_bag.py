import time
import os
import argparse
import numpy as np
import yaml
import dv_processing as dv
from rosbags.rosbag1 import Writer
from rosbags.typesys import Stores, get_typestore, get_types_from_msg

def read_camera_metadata(raw_dir):
    path = os.path.join(raw_dir, "camera_metadata.txt")
    with open(path, "r") as f:
        lines = f.readlines()
    left_cam = lines[1].strip()
    left_width, left_height = map(int, lines[2].strip().split())
    right_cam = lines[3].strip()
    # right_width, right_height = map(int, lines[4].strip().split())
    
    return left_cam, right_cam, left_width, left_height

def load_esvo_calibration(calib_dir):
    left_path = os.path.join(calib_dir, "left.yaml")
    right_path = os.path.join(calib_dir, "right.yaml")
    
    if not os.path.exists(left_path) or not os.path.exists(right_path):
        return None, None
    
    with open(left_path, 'r') as f:
        left_calib = yaml.safe_load(f)
    with open(right_path, 'r') as f:
        right_calib = yaml.safe_load(f)
    
    return left_calib, right_calib

def create_camera_info_msg(calib, timestamp_ns, typestore):
    CameraInfoMsg = typestore.types["sensor_msgs/msg/CameraInfo"]
    HeaderMsg = typestore.types["std_msgs/msg/Header"]
    TimeMsg = typestore.types["builtin_interfaces/msg/Time"]
    RegionOfInterestMsg = typestore.types["sensor_msgs/msg/RegionOfInterest"]
    
    secs = int(timestamp_ns // 1e9)
    nsecs = int(timestamp_ns % 1e9)
    
    header = HeaderMsg(
        seq=0,
        stamp=TimeMsg(sec=secs, nanosec=nsecs),
        frame_id="dvs"
    )
    
    width = calib['image_width']
    height = calib['image_height']
    
    K = calib['camera_matrix']['data']
    D = calib['distortion_coefficients']['data']
    R = calib['rectification_matrix']['data']
    P = calib['projection_matrix']['data']
    
    roi = RegionOfInterestMsg(
        x_offset=0,
        y_offset=0,
        height=0,
        width=0,
        do_rectify=False
    )
    
    return CameraInfoMsg(
        header=header,
        height=height,
        width=width,
        distortion_model='plumb_bob',
        D=np.array(D, dtype=np.float64),
        K=np.array(K, dtype=np.float64),
        R=np.array(R, dtype=np.float64),
        P=np.array(P, dtype=np.float64),
        binning_x=0,
        binning_y=0,
        roi=roi
    )

def create_event_array_msg(events, timestamp_ns, typestore, width, height):
    """Create EventArray message from EventStore using numpy for speed."""
    HeaderMsg = typestore.types["std_msgs/msg/Header"]
    TimeMsg = typestore.types["builtin_interfaces/msg/Time"]
    EventMsg = typestore.types["dvs_msgs/msg/Event"]
    EventArrayMsg = typestore.types["dvs_msgs/msg/EventArray"]

    secs = int(timestamp_ns // 1e9)
    nsecs = int(timestamp_ns % 1e9)

    header = HeaderMsg(
        seq=0,
        stamp=TimeMsg(sec=secs, nanosec=nsecs),
        frame_id="dvs"
    )

    events_np = events.numpy() 
    
    ts_us = events_np['timestamp']
    ev_secs = (ts_us // 1_000_000).astype(np.int32)
    ev_nsecs = ((ts_us % 1_000_000) * 1000).astype(np.int32)
    
    event_list = [
        EventMsg(
            x=int(events_np['x'][i]),
            y=int(events_np['y'][i]),
            ts=TimeMsg(sec=int(ev_secs[i]), nanosec=int(ev_nsecs[i])),
            polarity=bool(events_np['polarity'][i])
        )
        for i in range(len(events_np))
    ]

    return EventArrayMsg(
        header=header,
        height=height,
        width=width,
        events=event_list
    )

def chunk_events_by_time(recording, window_us=1000):
    left_reader = recording.getLeftReader()
    right_reader = recording.getRightReader()

    left_store = dv.EventStore()
    right_store = dv.EventStore()
    left_exhausted = False
    right_exhausted = False

    def refill_left():
        nonlocal left_exhausted
        batch = left_reader.getNextEventBatch()
        if batch is None or batch.size() == 0:
            left_exhausted = True
            return False
        left_store.add(batch)
        return True

    def refill_right():
        nonlocal right_exhausted
        batch = right_reader.getNextEventBatch()
        if batch is None or batch.size() == 0:
            right_exhausted = True
            return False
        right_store.add(batch)
        return True

    # Initial fill
    refill_left()
    refill_right()

    if left_store.isEmpty() and right_store.isEmpty():
        return  # no events at all

    # Determine start time
    if left_store.isEmpty():
        start_time = right_store.getLowestTime()
    elif right_store.isEmpty():
        start_time = left_store.getLowestTime()
    else:
        start_time = min(left_store.getLowestTime(), right_store.getLowestTime())

    current_time = start_time

    while True:
        window_end = current_time + window_us
        
        # ensure enough events loaded for this window
        while not left_exhausted and (left_store.isEmpty() or left_store.getHighestTime() < window_end):
            if not refill_left():
                break
        
        while not right_exhausted and (right_store.isEmpty() or right_store.getHighestTime() < window_end):
            if not refill_right():
                break
        
        # extract chunks using sliceTime 
        left_chunk = left_store.sliceTime(current_time, window_end)
        right_chunk = right_store.sliceTime(current_time, window_end)
        
        if left_exhausted and right_exhausted:
            # get any remaining events
            if not left_store.isEmpty() or not right_store.isEmpty():
                left_remaining = left_store.sliceTime(current_time) if not left_store.isEmpty() else None
                right_remaining = right_store.sliceTime(current_time) if not right_store.isEmpty() else None
                if (left_remaining and left_remaining.size() > 0) or (right_remaining and right_remaining.size() > 0):
                    yield (current_time, left_remaining, right_remaining)
            break

        # yield this window's events
        has_left = left_chunk is not None and left_chunk.size() > 0
        has_right = right_chunk is not None and right_chunk.size() > 0
        if has_left or has_right:
            yield (current_time, left_chunk if has_left else None, right_chunk if has_right else None)

        # clean up old events to prevent memory growth
        if not left_store.isEmpty():
            left_store = left_store.sliceTime(window_end)
        if not right_store.isEmpty():
            right_store = right_store.sliceTime(window_end)

        current_time = window_end

    

    
def convert_aedat4_to_bag(capture_dir, window_ms=1.0, override=True, calib_dir=None):
    raw_dir = os.path.join(capture_dir, "raw")
    intermediate_dir = os.path.join(capture_dir, "intermediate")

    aedat4_path = os.path.join(raw_dir, "stereo_recording.aedat4")
    output_path = os.path.join(intermediate_dir, "scene_events.bag")

    if not os.path.exists(aedat4_path):
        raise FileNotFoundError(f"Recording not found: {aedat4_path}")

    os.makedirs(intermediate_dir, exist_ok=True)

    left_cam, right_cam, width, height = read_camera_metadata(raw_dir)
    print(f"Left camera: {left_cam}", flush=True)
    print(f"Right camera: {right_cam}", flush=True)

    # load calibration if provided
    left_calib, right_calib = None, None
    if calib_dir:
        left_calib, right_calib = load_esvo_calibration(calib_dir)
        if left_calib and right_calib:
            print(f"Loaded calibration from {calib_dir}", flush=True)
        else:
            print(f"Warning: Could not load calibration from {calib_dir}", flush=True)

    recording = dv.io.StereoCameraRecording(aedat4_path, left_cam, right_cam)

    typestore = get_typestore(Stores.ROS1_NOETIC)

    register_dvs_msgs(typestore)

    print(f"Converting {aedat4_path} to {output_path}", flush=True)
    print(f"Using {window_ms}ms time windows (~{1000/window_ms:.0f} Hz)", flush=True)
        
    if os.path.exists(output_path) and override is True:
        os.remove(output_path)

    window_us = int(window_ms * 1000)

    with Writer(output_path) as bag:
        EVENT_TYPE = "dvs_msgs/msg/EventArray"
        CAMERA_INFO_TYPE = "sensor_msgs/msg/CameraInfo"

        connection_left = bag.add_connection(
          topic="/davis/left/events",
          msgtype=typestore.types[EVENT_TYPE].__msgtype__,
          typestore=typestore
        )
        connection_right = bag.add_connection(
          topic="/davis/right/events",
          msgtype=typestore.types[EVENT_TYPE].__msgtype__,
          typestore=typestore
        )

        # add camera_info connections if calibration is available
        cam_info_left_conn = None
        cam_info_right_conn = None
        if left_calib and right_calib:
            cam_info_left_conn = bag.add_connection(
                topic="/davis/left/camera_info",
                msgtype=typestore.types[CAMERA_INFO_TYPE].__msgtype__,
                typestore=typestore
            )
            cam_info_right_conn = bag.add_connection(
                topic="/davis/right/camera_info",
                msgtype=typestore.types[CAMERA_INFO_TYPE].__msgtype__,
                typestore=typestore
            )

        msg_count = 0
        cam_info_count = 0
        t0 = time.time()
        last_print = 0.0
        last_cam_info_us = 0
        cam_info_interval_us = 10_000  # Write camera_info every 10ms (100 Hz)

        # get time range from left camera for ETA calculation
        start_us, end_us = recording.getLeftReader().getTimeRange()
        total_us = end_us - start_us

        for timestamp_us, left_events, right_events in chunk_events_by_time(recording, window_us):
            timestamp_ns = int(timestamp_us) * 1000
            
            # Write camera_info periodically (100 Hz)
            if cam_info_left_conn and cam_info_right_conn and (timestamp_us - last_cam_info_us >= cam_info_interval_us):
                left_cam_info = create_camera_info_msg(left_calib, timestamp_ns, typestore)
                right_cam_info = create_camera_info_msg(right_calib, timestamp_ns, typestore)
                
                left_cam_bytes = typestore.serialize_ros1(left_cam_info, CAMERA_INFO_TYPE)
                right_cam_bytes = typestore.serialize_ros1(right_cam_info, CAMERA_INFO_TYPE)
                
                bag.write(cam_info_left_conn, timestamp_ns, bytes(left_cam_bytes))
                bag.write(cam_info_right_conn, timestamp_ns, bytes(right_cam_bytes))
                
                last_cam_info_us = timestamp_us
                cam_info_count += 1
            
            if left_events is not None and left_events.size() > 0:
                left_msg = create_event_array_msg(left_events, timestamp_ns, typestore, width, height)
                left_bytes = typestore.serialize_ros1(left_msg, EVENT_TYPE)
                bag.write(connection_left, timestamp_ns, bytes(left_bytes))

            if right_events is not None and right_events.size() > 0:
                right_msg = create_event_array_msg(right_events, timestamp_ns, typestore, width, height)
                right_bytes = typestore.serialize_ros1(right_msg, EVENT_TYPE)
                bag.write(connection_right, timestamp_ns, bytes(right_bytes))

            msg_count += 1
            now = time.time()
            if now - last_print >= 1:
                elapsed = now - t0
                progress = (timestamp_us - start_us) / total_us
                eta = (elapsed / progress - elapsed) if progress > 0.01 else 0
                print(f"\r{progress*100:5.1f}% | {msg_count:,} windows | ETA {eta:.0f}s", end="", flush=True)
                last_print = now
        print()

    print(f"Done! Created {output_path} with {msg_count} event message pairs", flush=True)

def register_dvs_msgs(typestore):
    # Define the message types as they appear in dvs_msgs
    # See: https://github.com/uzh-rpg/rpg_dvs_ros/tree/master/dvs_msgs
    DVS_EVENT_MSG = """
    uint16 x
    uint16 y
    time ts
    bool polarity
    """

    DVS_EVENT_ARRAY_MSG = """
    std_msgs/Header header
    uint32 height
    uint32 width
    dvs_msgs/Event[] events
    """

    typestore.register(get_types_from_msg(DVS_EVENT_MSG, "dvs_msgs/msg/Event"))
    typestore.register(get_types_from_msg(DVS_EVENT_ARRAY_MSG, "dvs_msgs/msg/EventArray"))

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--path", required=True, help="Path to capture directory (contains raw/stereo_recording.aedat4)")
    parser.add_argument("--window-ms", type=float, default=1.0, help="Time window for event chunking in ms (default: 1.0 (ESVO))")
    parser.add_argument("--calibration", help="Path to ESVO calibration directory containing left.yaml and right.yaml")

    args = parser.parse_args()
    
    convert_aedat4_to_bag(args.path, args.window_ms, calib_dir=args.calibration)

if __name__ == "__main__":
    main()
        

