"""Generate ESVO mapping/tracking/time-surface config files.
    mapping.yaml
    tracking.yaml
    ts_parameters.yaml
"""
import os
import argparse
import yaml
import numpy as np

# Dataset families used when comparing official presets:
# - RPG stereo DAVIS240C (UZH RPG): indoor hand-held stereo event-camera scenes in
#   a motion-capture room; sequences include bin, boxes, desk, monitor, reader.
#   Dataset source: https://rpg.ifi.uzh.ch/ECCV18_stereo_davis.html
#   YAML sources:
#     - ESVO/esvo_core/cfg/mapping/mapping_rpg.yaml
#     - ESVO/esvo_core/cfg/tracking/tracking_rpg.yaml
#     - ESVO2/esvo2_core/cfg/mapping/mapping_rpg_AA.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_rpg_AA.yaml
# - UPenn / MVSEC indoor_flying (DAVIS346B): Multi Vehicle Stereo Event Camera, hexacopter, driving, handheld
#   indoor and outdoor environment; mostly translation-dominant motion with hovering segments.
#   Dataset source: https://daniilidis-group.github.io/mvsec/
#   YAML sources:
#     - ESVO/esvo_core/cfg/mapping/mapping_upenn.yaml
#     - ESVO/esvo_core/cfg/tracking/tracking_upenn.yaml
#     - ESVO2/esvo2_core/cfg/mapping/mapping_upenn_AA.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_upenn_AA.yaml
# - HKUST lab: authors' stereo event-camera recording of a cluttered lab / machine
#   facility scene.
#   Dataset source: https://arxiv.org/abs/2007.15548
#   YAML sources:
#     - ESVO/esvo_core/cfg/mapping/mapping_hkust.yaml
#     - ESVO/esvo_core/cfg/tracking/tracking_hkust.yaml
# - DVXplorer / HNU outdoor: ESVO2 authors' outdoor stereo DVXplorer dataset
#   with IMU and GNSS; hnu_campus is a closed-loop campus trajectory and
#   hnu_peachlake is a winding narrow-street sequence.
#   Dataset source: https://arxiv.org/abs/2410.09374
#   YAML sources:
#     - ESVO2/esvo2_core/cfg/mapping/mapping_dvx_AA_mapping.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_dvx_AA_mapping.yaml

DVX_SHARED_MAPPING_PRESET = {
    "residual_vis_threshold": 18,
    "stdVar_vis_threshold": 0.22,
    "age_max_range": 10,
    "age_vis_threshold": 1,
    "fusion_radius": 1,
    "FUSION_STRATEGY": "CONST_FRAMES",
    "maxNumFusionFrames": 3,
    "maxNumFusionPoints": 20000,
    "Denoising": False,
    "SmoothTimeSurface": True,
    "Regularization": True,
    "bVisualizeGlobalPC": True,
    "visualizeGPC_interval": 0.5,
    "NumGPC_added_oper_refresh": 10000,
    "visualize_range": 6,
    "PROCESS_EVENT_NUM": 7000,
    "TS_HISTORY_LENGTH": 100,
    "INIT_SGM_DP_NUM_THRESHOLD": 500,
    "mapping_rate_hz": 20,
    "patch_size_X": 15,
    "patch_size_Y": 7,
    "LSnorm": "Tdist",
    "Tdist_nu": 2.182,
    "Tdist_scale": 17.277,
    "Tdist_stdvar": 59.763,
    "BM_half_slice_thickness": 0.001,
    "BM_step": 1,
    "BM_ZNCC_Threshold": 0.22,
    "BM_bUpDownConfiguration": False,
}

DVX_SHARED_TRACKING_PRESET = {
    "TS_HISTORY_LENGTH": 100,
    "REF_HISTORY_LENGTH": 10,
    "tracking_rate_hz": 100,
    "patch_size_X": 1,
    "patch_size_Y": 1,
    "kernelSize": 5,
    "MAX_REGISTRATION_POINTS": 3500,
    "BATCH_SIZE": 450,
    "MAX_ITERATION": 15,
    "LSnorm": "Huber",
    "huber_threshold": 22,
    "MIN_NUM_EVENTS": 1500,
    "RegProblemType": 1,
    "SAVE_TRAJECTORY": True,
    "SEQUENCE_NAME": "reconstruction",
    "VISUALIZE_TRAJECTORY": True,
    "PATH_TO_SAVE_TRAJECTORY": "/output/",
}

DVX_TS_PRESET = {
    "use_sim_time": True,
    "ignore_polarity": True,
    "time_surface_mode": 0,
    "decay_ms": 18,
    "median_blur_kernel_size": 1,
    "max_event_queue_len": 20,
}

SENSOR_PROFILES = {
    'davis346': {
        'width': 346,
        'height': 260,
        'max_eps': 12e6,
        'decay_ms': 30,
        'ts_queue': 20,
    },
    'dvxplorer': {
        'width': 640,
        'height': 480,
        'max_eps': 165e6,
        'decay_ms': 20,
        'ts_queue': 20,
        'tracking_rate_hz': 100,
        'mapping_rate_hz': 20,
        'tracking_ts_history': 100,
        'mapping_ts_history': 100,
        'batch_size': 300,
        'process_event_num': 10000, 
    },
}

def detect_sensor_profile(width, height):
    pixels = width * height
    if pixels <= 346 * 260 * 1.2:
        return SENSOR_PROFILES['davis346']
    else:
        return SENSOR_PROFILES['dvxplorer']


def is_dvxplorer_profile(profile):
    return profile['max_eps'] > 50e6

def compute_disparity_bounds(baseline, focal_length, min_depth, max_depth, disparity_cap):
    computed_max_disp = baseline * focal_length / min_depth
    computed_min_disp = baseline * focal_length / max_depth

    min_disparity = max(0, int(np.floor(0.95 * computed_min_disp)))
    max_disparity = min(disparity_cap, int(np.ceil(1.05 * computed_max_disp)))
    if max_disparity <= min_disparity:
        max_disparity = min(disparity_cap, min_disparity + 1)

    return min_disparity, max_disparity, computed_min_disp, computed_max_disp

def load_esvo_calib(esvo_dir):
    """Load left/right ESVO calibration YAML files."""
    with open(os.path.join(esvo_dir, "left.yaml"), "r") as f:
        left = yaml.safe_load(f)
    with open(os.path.join(esvo_dir, "right.yaml"), "r") as f:
        right = yaml.safe_load(f)

    return left, right

def compute_baseline(right_calib):
    T = np.array(right_calib["T_right_left"]["data"]).reshape(3, 4)
    translation = T[:, 3]
    return np.linalg.norm(translation)

def compute_focal_length(left_calib):
    """Return rectified focal length from the projection matrix P.

    ESVO undistorts and rectifies events before stereo matching, so the
    disparity search bounds must use P's focal length — not the unrectified
    camera matrix K.  Using K overestimates the focal length (and thus the
    maximum disparity) by the amount that rectification narrows the FoV.
    """
    P = np.array(left_calib["projection_matrix"]["data"]).reshape(3, 4)
    fx = P[0, 0]
    fy = P[1, 1]
    return (fx + fy) / 2

def generate_mapping_config(output_path, width, height, baseline, focal_length, min_depth=0.5, max_depth=10.0):
    """Generate mapping.yaml."""
    profile = detect_sensor_profile(width, height)
    is_dvxplorer = is_dvxplorer_profile(profile)

    disparity_cap = 150 if is_dvxplorer else max(40, width // 2)
    min_disparity, max_disparity, computed_min_disp, computed_max_disp = compute_disparity_bounds(
        baseline, focal_length, min_depth, max_depth, disparity_cap
    )

    inv_depth_min = 1.0 / max_depth
    inv_depth_max = 1.0 / min_depth

    if is_dvxplorer:
        config = dict(DVX_SHARED_MAPPING_PRESET)
    else:
        config = {
            'residual_vis_threshold': 20,
            'stdVar_vis_threshold': 0.15,
            'age_max_range': 10,
            'age_vis_threshold': 1,
            'fusion_radius': 0,
            'FUSION_STRATEGY': 'CONST_POINTS',
            'maxNumFusionFrames': 40,
            'maxNumFusionPoints': 5000,
            'Denoising': True,
            'SmoothTimeSurface': False,
            'Regularization': True,
            'bVisualizeGlobalPC': True,
            'visualizeGPC_interval': 3,
            'NumGPC_added_oper_refresh': 1500,
            'visualize_range': min(max_depth, 5.0),
            'PROCESS_EVENT_NUM': profile.get('process_event_num', 1000),
            'TS_HISTORY_LENGTH': profile.get('mapping_ts_history', 100),
            'INIT_SGM_DP_NUM_THRESHOLD': 500,
            'mapping_rate_hz': profile.get('mapping_rate_hz', 20),
            'patch_size_X': 15,
            'patch_size_Y': 7,
            'LSnorm': 'Tdist',
            'Tdist_nu': 2.1897,
            'Tdist_scale': 16.6397,
            'Tdist_stdvar': 56.5347,
            'BM_half_slice_thickness': 0.001,
            'BM_step': 1,
            'BM_ZNCC_Threshold': 0.1,
            'BM_bUpDownConfiguration': False,
        }

    config.update({
        'invDepth_min_range': round(inv_depth_min, 2),
        'invDepth_max_range': round(inv_depth_max, 2),
        'BM_min_disparity': min_disparity,
        'BM_max_disparity': max_disparity,
    })

    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    actual_min_depth = baseline * focal_length / max_disparity
    actual_max_depth = baseline * focal_length / max(min_disparity, 1)

    print(f"Written mapping config: {output_path}")
    print(f"  - Sensor profile: {'DVXplorer' if is_dvxplorer else 'DAVIS'}")
    print(f"  - Disparity range: {min_disparity} - {max_disparity} (geometry: {computed_min_disp:.1f} - {computed_max_disp:.1f})")
    print(f"  - Actual depth range: {actual_min_depth:.2f}m - {actual_max_depth:.2f}m")
    print(f"  - Inv depth range: {inv_depth_min:.2f} - {inv_depth_max:.2f}")
    print(f"  - Preset: {'official_dvx_shared_analog' if is_dvxplorer else 'generic'}")
    print(f"  - Patch size: {config['patch_size_X']}x{config['patch_size_Y']}")
    print(f"  - mapping_rate_hz: {config['mapping_rate_hz']}")
    print(f"  - BM_step: {config['BM_step']}")
    

def generate_tracking_config(output_path, width, height, min_depth=0.5, max_depth=10.0):
    """Generate tracking.yaml."""
    profile = detect_sensor_profile(width, height)
    is_dvxplorer = is_dvxplorer_profile(profile)

    inv_depth_min = 1.0 / max_depth
    inv_depth_max = 1.0 / min_depth
    
    if is_dvxplorer:
        config = dict(DVX_SHARED_TRACKING_PRESET)
    else:
        config = {
            'TS_HISTORY_LENGTH': profile.get('tracking_ts_history', 100),
            'REF_HISTORY_LENGTH': 10,
            'tracking_rate_hz': profile.get('tracking_rate_hz', 100),
            'patch_size_X': 1,
            'patch_size_Y': 1,
            'kernelSize': 5,
            'MAX_REGISTRATION_POINTS': 2000,
            'BATCH_SIZE': profile.get('batch_size', 300),
            'MAX_ITERATION': 10,
            'LSnorm': 'Huber',
            'huber_threshold': 50,
            'MIN_NUM_EVENTS': 1000,
            'RegProblemType': 1,
            'SAVE_TRAJECTORY': True,
            'SEQUENCE_NAME': 'reconstruction',
            'VISUALIZE_TRAJECTORY': True,
            'PATH_TO_SAVE_TRAJECTORY': '/output/',
        }
    config.update({
        'invDepth_min_range': round(inv_depth_min, 2),
        'invDepth_max_range': round(inv_depth_max, 2),
    })
    
    with open(output_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print(f"Written tracking config: {output_path}")
    print(f"  - tracking_rate_hz: {config['tracking_rate_hz']}")
    print(f"  - MIN_NUM_EVENTS: {config['MIN_NUM_EVENTS']}")
    print(f"  - BATCH_SIZE: {config['BATCH_SIZE']}")
    print(f"  - huber_threshold: {config['huber_threshold']}")


def generate_ts_parameters(output_path, width, height):
    """Generate ts_parameters.yaml."""
    profile = detect_sensor_profile(width, height)
    is_dvxplorer = is_dvxplorer_profile(profile)

    if is_dvxplorer:
        config = dict(DVX_TS_PRESET)
    else:
        config = {
            'use_sim_time': True,
            'ignore_polarity': True,
            'time_surface_mode': 0,
            'decay_ms': profile['decay_ms'],
            'median_blur_kernel_size': 1,
            'max_event_queue_len': profile['ts_queue'],
        }
    
    with open(output_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print(f"Written time surface config: {output_path}")
    print(f"  - decay_ms: {config['decay_ms']} (effective window: ~{config['decay_ms'] * 5}ms at 1% threshold)")
    print(f"  - max_event_queue_len: {config['max_event_queue_len']}")

def generate_all_configs(session_path, min_depth=0.5, max_depth=10.0):
    esvo_config_dir = os.path.join(session_path, "config", "esvo")


    if not os.path.exists(esvo_config_dir):
        raise FileNotFoundError(f"ESVO config directory not found at {esvo_config_dir}, run camchain_to_esvo.py first")
    
    left_yaml = os.path.join(esvo_config_dir, "left.yaml")
    right_yaml = os.path.join(esvo_config_dir, "right.yaml")
    if not os.path.exists(left_yaml) or not os.path.exists(right_yaml):
        raise FileNotFoundError(f"ESVO calibration files (left.yaml, right.yaml) not found in {esvo_config_dir}, run camchain_to_esvo.py first")

    left_calib, right_calib = load_esvo_calib(esvo_config_dir)

    width = left_calib["image_width"]
    height = left_calib["image_height"]
    baseline = compute_baseline(right_calib)
    focal_length = compute_focal_length(left_calib)

    print(f"Camera: {width}x{height}")
    print(f"Baseline: {baseline:.4f} m")
    print(f"Focal length: {focal_length:.2f} px")
    print(f"Depth range: {min_depth} - {max_depth} m")
    
    profile = detect_sensor_profile(width, height)
    eps_density = profile['max_eps'] / (width * height)
    print(f"Sensor profile: {'DVXplorer' if profile['max_eps'] > 50e6 else 'DAVIS'} "
          f"(max {profile['max_eps']/1e6:.0f}M eps, {eps_density:.0f} eps/pixel)")
    print()

    generate_mapping_config(
        os.path.join(esvo_config_dir, 'mapping.yaml'),
        width, height, baseline, focal_length, min_depth, max_depth
    )
    
    generate_tracking_config(
        os.path.join(esvo_config_dir, 'tracking.yaml'),
        width, height, min_depth, max_depth
    )
    
    generate_ts_parameters(
        os.path.join(esvo_config_dir, 'ts_parameters.yaml'),
        width, height
    )
    
    print(f"\nAll configs written to: {esvo_config_dir}")
    print("\nRecommended playback rate for this sensor: 0.2")
    

def main():
    parser = argparse.ArgumentParser(
        description="Generate ESVO configuration files tuned for the detected sensor type."
    )
    parser.add_argument(
        "--session", required=True, help="Path to session directory"
    )
    parser.add_argument(
        "--min-depth",
        type=float,
        default=0.5,
        help="Minimum expected scene depth in meters (default: 0.5)"
    )
    parser.add_argument(
        "--max-depth",
        type=float,
        default=10.0,
        help="Maximum expected scene depth in meters (default: 10.0)"
    )
    
    args = parser.parse_args()
    generate_all_configs(args.session, args.min_depth, args.max_depth)


if __name__ == "__main__":
    main()
