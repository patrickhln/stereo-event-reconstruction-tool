import sys
import os
import heapq
import argparse
import time

import numpy as np

from rosbags.typesys import Stores, get_typestore, get_types_from_msg
from rosbags.rosbag1 import Writer

DVS_EVENT_MSG = """
uint16 x
uint16 y
builtin_interfaces/Time ts
bool polarity
"""

DVS_EVENT_ARRAY_MSG = """
std_msgs/Header header
uint32 height
uint32 width
dvs_msgs/Event[] events
"""

def events_txt_to_rosbag(left_txt, right_txt, output_bag):
    # https://github.com/uzh-rpg/rpg_dvs_ros/tree/master/dvs_msgs/msg
    typestore = get_typestore(Stores.ROS1_NOETIC)
    typestore.register(get_types_from_msg(DVS_EVENT_MSG, "dvs_msgs/msg/Event"))
    typestore.register(get_types_from_msg(DVS_EVENT_ARRAY_MSG, "dvs_msgs/msg/EventArray"))
    
    EventArray = typestore.types["dvs_msgs/msg/EventArray"]
    Event = typestore.types["dvs_msgs/msg/Event"]
    Header = typestore.types["std_msgs/msg/Header"]
    Time = typestore.types["builtin_interfaces/msg/Time"]

    window_ms = 1.0

    left_raw = stream_events(left_txt)
    right_raw = stream_events(right_txt)
    
    # create grouped streams (chunks of 1ms)
    # so 1000 messages/second -> https://github.com/HKUST-Aerial Robotics/ESVO/tree/master/events_repacking_helper
    left_groups = stream_groups_by_time(left_raw, window_ms) 
    right_groups = stream_groups_by_time(right_raw, window_ms) 

    left_tagged = ( (g[0][0], "left", g, w, h) for g, w, h in left_groups )
    right_tagged = ( (g[0][0], "right", g, w, h) for g, w, h in right_groups )

    timeline = heapq.merge(left_tagged, right_tagged, key=lambda x: x[0])

    if os.path.exists(output_bag):
        os.remove(output_bag)
        print(f"Removed existing bag file: {output_bag}")

    print(f"Starting creating messages and writing {output_bag}")
    with Writer(output_bag) as bag:
        start = time.time()
        connection_left = bag.add_connection(
            topic="/cam0/events",
            msgtype="dvs_msgs/msg/EventArray",
            typestore=typestore
        )
        connection_right = bag.add_connection(
            topic="/cam1/events",
            msgtype="dvs_msgs/msg/EventArray",
            typestore=typestore
        )

        count = 0
        for seq, (timestamp, side, group, width, height) in enumerate(timeline):
            
            if side == "left":
                msg = create_event_array_msg(group, width, height, "cam0", seq, EventArray, Event, Header, Time)
                bag.write(connection_left, int(timestamp * 1e9), typestore.serialize_ros1(msg, msg.__msgtype__))
                #                                                                              ^^^^^^^^^^^^^^^
                #                                                                            = "dvs_msgs/msg/EventArray" 
            else:
                msg = create_event_array_msg(group, width, height, "cam1", seq, EventArray, Event, Header, Time)
                bag.write(connection_right, int(timestamp * 1e9), typestore.serialize_ros1(msg, msg.__msgtype__))

            count += 1
            if count % 2000 == 0:
                print(f"Processed {count} messages...", end="\r")

        end = time.time()

    print(f"Done writing {output_bag}! Total messages: {count}, took {(end-start):.2f} seconds")

def read_events(txt_path):
    with open(txt_path) as f:
        width, height = map(int, f.readline().split())
        events = []
        for line in f:
            t, x, y, pol = line.split()
            events.append((float(t), int(x), int(y), int(pol) > 0))
        return events, width, height

def stream_events(txt_path):
    
    with open(txt_path) as f:
        header_line = f.readline()

        if not header_line:
            return # empty file

        width, height = map(int, header_line.split())

    data = np.loadtxt(txt_path, skiprows=1)
    return data, width, height

def stream_groups_by_time(event_data_tuple, window_ms):
    if event_data_tuple is None: 
        return
    data, w, h = event_data_tuple
    if len(data) == 0: 
        return

    times = data[:, 0]
    start_time = times[0]
    window_sec = window_ms / 1000.0

    # Calculate split indices efficiently using binary search
    # Create boundaries: [start+win, start+2*win, ...]
    boundaries = np.arange(start_time + window_sec, times[-1] + window_sec, window_sec)
    split_indices = np.searchsorted(times, boundaries)

    # Split the big array into chunks
    groups = np.split(data, split_indices)

    for g in groups:
        if len(g) > 0:
            yield g, w, h

def create_event_array_msg(events, width, height, frame_id, seq, EventArray, Event, Header, Time):

    # use last event's time for message header stamp
    last_ts = events[-1][0]

    ts_col = events[:, 0]
    secs = ts_col.astype(np.int32)
    nsecs = ((ts_col - secs) * 1e9).astype(np.int32)

    ros_events = [
        Event(x=int(r[1]), y=int(r[2]), ts=Time(sec=s, nanosec=ns), polarity=bool(r[3]))
        for r, s, ns in zip(events, secs, nsecs)
    ]

    return EventArray(
        header=Header(
            seq=seq,
            stamp=Time(sec=int(last_ts), nanosec=int((last_ts % 1) * 1e9)),
            frame_id=frame_id
        ),
        width=width, height=height,
        events=ros_events
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="Path to session folder (should contain intermediate/leftEvents.txt and intermediate/rightEvents.txt)")

    args = parser.parse_args()
    
    leftEventsTxtPath = os.path.join(args.path, "intermediate", "leftEvents.txt")
    rightEventsTxtPath = os.path.join(args.path, "intermediate", "rightEvents.txt")

    if not os.path.exists(leftEventsTxtPath) or not os.path.exists(rightEventsTxtPath):
        print(f"Could not find both leftEvents.txt and rightEvents.txt\n{leftEventsTxtPath}\n{rightEventsTxtPath}")
        sys.exit(1)
    
    events_txt_to_rosbag(leftEventsTxtPath, rightEventsTxtPath, os.path.join(args.path, "intermediate", "stereo_events.bag"))    
    sys.exit(0)

if __name__ == "__main__":
    main()
