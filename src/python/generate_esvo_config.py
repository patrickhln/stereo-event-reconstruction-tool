"""
Generate:
    mapping.yaml
    tracking.yaml
    ts_parameters.yaml
"""
import os
import argparse
import yaml
import numpy as np

def load_esvo_calib(esvo_dir):
    """Load ESVO calibration files from the esvo config directory."""
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
    K = np.array(left_calib["camera_matrix"]["data"]).reshape(3, 3)
    fx = K[0, 0]
    fy = K[1, 1]
    return (fx + fy) / 2

def generate_mapping_config(output_path, width, baseline, focal_length, min_depth=0.5, max_depth=10.0):
    """
    mapping.yaml computed parameters based on ESVO/esvo_core/cfg/mapping/mapping_rpg.yaml
    
    Disparity calculation strategy:
    - Official ESVO uses max_disparity=40, min_disparity=1 for all configs (RPG, HKUST, UPenn)
    - These configs target DAVIS240C (240x180) cameras
    - For higher resolution, we scale proportionally but cap conservatively
    - ESVO's block matching can be unstable with very large disparity ranges
    """
    # Reference: Official ESVO configs use these values for DAVIS240C (240px width)
    OFFICIAL_MAX_DISPARITY = 40
    OFFICIAL_MIN_DISPARITY = 1
    OFFICIAL_WIDTH = 240

    # Scale factor for current resolution
    scale_factor = width / OFFICIAL_WIDTH

    # Computed disparity from geometry: d = baseline * focal_length / depth
    computed_max_disp = baseline * focal_length / min_depth
    computed_min_disp = baseline * focal_length / max_depth

    # Strategy:
    # - Use geometry-computed disparity for the requested depth range.
    # - Apply a conservative cap scaled from DAVIS to keep matching stable.

    scaled_official_max = int(OFFICIAL_MAX_DISPARITY * scale_factor)

    # Apply conservative bounds
    min_disparity = max(OFFICIAL_MIN_DISPARITY, int(computed_min_disp))
    max_disparity = min(int(computed_max_disp), scaled_official_max)

    # Ensure valid range (max > min with reasonable margin) when possible
    if min_disparity + 20 <= scaled_official_max:
        max_disparity = max(max_disparity, min_disparity + 20)

    # Compute actual depth range achievable with these disparity bounds
    actual_min_depth = baseline * focal_length / max_disparity
    actual_max_depth = baseline * focal_length / max(min_disparity, 1)

    # Warn if we're significantly limiting the requested depth range
    if actual_min_depth > min_depth * 1.2:
        print(f"NOTE: Disparity capped at {max_disparity} (scaled from official {OFFICIAL_MAX_DISPARITY})")
        print(f"      Actual min depth: {actual_min_depth:.2f}m (requested: {min_depth:.2f}m)")

    inv_depth_min = 1.0 / max_depth
    inv_depth_max = 1.0 / min_depth
    is_high_res = width >= 480

    # patch size for DAVID346 was 15x7 (resolution 346x260)
    # patch size for higher-res sensors scaled proportionally:
    scale = width / 346.0
    patch_x = int(15 * scale)
    patch_y = int(7 * scale)

    # keep odd
    if patch_x % 2 == 0:
        patch_x += 1
    if patch_y % 2 == 0:
        patch_y += 1

    # clamp to reasonable bounds
    patch_x = max(15, min(patch_x, 31))
    patch_y = max(7, min(patch_y, 15))

    config = {
        # depth range (computed from user settings)
        'invDepth_min_range': round(inv_depth_min, 2),
        'invDepth_max_range': round(inv_depth_max, 2),
        
        # visualization thresholds 
        'residual_vis_threshold': 20,
        'stdVar_vis_threshold': 0.1,  
        'age_max_range': 10,
        'age_vis_threshold': 1,
        
        # fusion - use CONST_POINTS like official configs
        'fusion_radius': 0,
        'FUSION_STRATEGY': 'CONST_POINTS',
        'maxNumFusionFrames': 40,
        'maxNumFusionPoints': 8000 if is_high_res else 5000,
        
        # processing
        'Denoising': True,
        'SmoothTimeSurface': False,
        'Regularization': True,
        
        # visualization
        'bVisualizeGlobalPC': True,
        'visualizeGPC_interval': 3,
        'NumGPC_added_per_refresh': 1000,
        'visualize_range': min(max_depth, 5.0),
        
        # core parameters
        'PROCESS_EVENT_NUM': 2000 if is_high_res else 1000,
        'TS_HISTORY_LENGTH': 100,
        'INIT_SGM_DP_NUM_THRESHOLD': 600 if is_high_res else 500,
        'mapping_rate_hz': 20,
        
        # patch size 
        'patch_size_X': patch_x,
        'patch_size_Y': patch_y,
        
        # optimization
        'Lnorm': 'Tdist',
        'Tdist_nu': 2.1897,
        'Tdist_scale': 16.6397,
        'Tdist_stdvar': 56.5347,
        
        # block matching (disparity computed from depth range)
        'BM_half_slice_thickness': 0.001,
        'BM_min_disparity': min_disparity,
        'BM_max_disparity': max_disparity,
        'BM_step': 1,
        'BM_ZNCC_Threshold': 0.1,
        'BM_bUpDownConfiguration': False,
    }

    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"Written mapping config: {output_path}")
    print(f"  - Disparity range: {min_disparity} - {max_disparity}")
    print(f"  - Inv depth range: {inv_depth_min:.2f} - {inv_depth_max:.2f}")
    print(f"  - Patch size: {patch_x}x{patch_y}")
    

def generate_tracking_config(output_path, width, min_depth=0.5, max_depth=10.0):
    """
    tracking.yaml based on ESVO/esvo_core/cfg/tracking/tracking_hkust.yaml
    
    IMPORTANT: Tracking uses FIXED 1x1 patch size for image registration,
    unlike mapping which uses larger patches
    """
    inv_depth_min = 1.0 / max_depth
    inv_depth_max = 1.0 / min_depth
    is_high_res = width >= 480
    
    config = {
        'invDepth_min_range': round(inv_depth_min, 2),
        'invDepth_max_range': round(inv_depth_max, 2),
        
        'TS_HISTORY_LENGTH': 100,
        'REF_HISTORY_LENGTH': 10,
        'tracking_rate_hz': 100,  # Must be faster than mapping_rate_hz to avoid race condition
        
        # tracking parameters 
        'patch_size_X': 1,  # MUST be 1 for tracking (not scaled!)
        'patch_size_Y': 1,  # MUST be 1 for tracking (not scaled!)
        'kernelSize': 5,
        
        'MAX_REGISTRATION_POINTS': 4000,
        'BATCH_SIZE': 500,
        'MAX_ITERATION': 10,
        
        'LSnorm': 'Huber',
        'huber_threshold': 50,
        'MIN_NUM_EVENTS': 800 if is_high_res else 1000,
        
        'RegProblemType': 1,  # 1=analytical (faster and more stable)
        
        'SAVE_TRAJECTORY': True,
        'SEQUENCE_NAME': 'reconstruction',
        'VISUALIZE_TRAJECTORY': True,
        'PATH_TO_SAVE_TRAJECTORY': '/output/',
    }
    
    with open(output_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print(f"Written tracking config: {output_path}")


def generate_ts_parameters(output_path):
    """
    ts_parameters.yaml based on ESVO/esvo_core/cfg/time_surface/ts_parameters.yaml
    """
    config = {
        'use_sim_time': True,
        'ignore_polarity': True,
        'time_surface_mode': 0,  # 0=backward, 1=forward
        'decay_ms': 20,
        'median_blur_kernel_size': 1,
        'max_event_queue_len': 20,
    }
    
    with open(output_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print(f"Written time surface config: {output_path}")

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
    print()

    generate_mapping_config(
        os.path.join(esvo_config_dir, 'mapping.yaml'),
        width, baseline, focal_length, min_depth, max_depth
    )
    
    generate_tracking_config(
        os.path.join(esvo_config_dir, 'tracking.yaml'),
        width, min_depth, max_depth
    )
    
    generate_ts_parameters(
        os.path.join(esvo_config_dir, 'ts_parameters.yaml')
    )
    
    print(f"\nAll configs written to: {esvo_config_dir}")
    

def main():
    parser = argparse.ArgumentParser()
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
