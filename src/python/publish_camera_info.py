#!/usr/bin/env python3
"""
publish camera_info topics from ESVO calibration YAML files.

This is needed because ESVO's TimeSurface node requires camera_info
to compute undistortion/rectification maps
"""

import sys
import yaml
import rospy
from sensor_msgs.msg import CameraInfo


def load_esvo_calib(yaml_path):
    with open(yaml_path, 'r') as f:
        return yaml.safe_load(f)


def calib_to_camera_info(calib, frame_id):
    msg = CameraInfo()
    msg.header.frame_id = frame_id
    
    msg.width = calib['image_width']
    msg.height = calib['image_height']
    
    msg.distortion_model = calib.get('distortion_model', 'plumb_bob')
    
    # Distortion coefficients (D)
    dist = calib.get('distortion_coefficients', {})
    msg.D = dist.get('data', [0, 0, 0, 0, 0])
    
    # Camera matrix (K) - 3x3 -> flat array of 9
    cam_mat = calib.get('camera_matrix', {})
    msg.K = cam_mat.get('data', [1, 0, 0, 0, 1, 0, 0, 0, 1])
    
    # Rectification matrix (R) - 3x3 -> flat array of 9
    rect_mat = calib.get('rectification_matrix', {})
    msg.R = rect_mat.get('data', [1, 0, 0, 0, 1, 0, 0, 0, 1])
    
    # Projection matrix (P) - 3x4 -> flat array of 12
    proj_mat = calib.get('projection_matrix', {})
    msg.P = proj_mat.get('data', [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0])
    
    return msg


def main():
    if len(sys.argv) < 3:
        print("Usage: publish_camera_info.py <left.yaml> <right.yaml>")
        sys.exit(1)
    
    left_yaml = sys.argv[1]
    right_yaml = sys.argv[2]
    
    rospy.init_node('camera_info_publisher', anonymous=True)
    
    left_calib = load_esvo_calib(left_yaml)
    right_calib = load_esvo_calib(right_yaml)
    
    left_msg = calib_to_camera_info(left_calib, 'dvs')
    right_msg = calib_to_camera_info(right_calib, 'dvs')
    
    left_pub = rospy.Publisher('/davis/left/camera_info', CameraInfo, queue_size=10)
    right_pub = rospy.Publisher('/davis/right/camera_info', CameraInfo, queue_size=10)
    
    rospy.loginfo(f"Publishing camera_info from {left_yaml} and {right_yaml}")
    rospy.loginfo(f"  Left:  {left_msg.width}x{left_msg.height}, model={left_msg.distortion_model}")
    rospy.loginfo(f"  Right: {right_msg.width}x{right_msg.height}, model={right_msg.distortion_model}")
    
    # publish at 1000 Hz to match official ESVO setup (hkust_calib_info.launch uses -r 1000)
    rate = rospy.Rate(1000)
    while not rospy.is_shutdown():
        now = rospy.Time.now()
        left_msg.header.stamp = now
        right_msg.header.stamp = now
        left_pub.publish(left_msg)
        right_pub.publish(right_msg)
        rate.sleep()


if __name__ == '__main__':
    main()
