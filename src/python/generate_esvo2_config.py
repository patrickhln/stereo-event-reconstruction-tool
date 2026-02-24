"""
Generate ESVO2 configuration files:
    mapping.yaml
    tracking.yaml
    image_representation.yaml (replaces ESVO's ts_parameters.yaml)
    
ESVO2 differences from ESVO:
    - USE_IMU parameter for visual-inertial mode
    - AA (Accumulated Activity) map parameters
    - image_representation node instead of esvo_time_surface
"""
import os
import argparse
import yaml
import numpy as np

def load_esvo2_calib(esvo2_dir):
    """Load ESVO2 calibration files from the esvo2 config directory."""
    with open(os.path.join(esvo2_dir, "left.yaml"), "r") as f:
        left = yaml.safe_load(f)
    with open(os.path.join(esvo2_dir, "right.yaml"), "r") as f:
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

def generate_mapping_config(output_path, width, baseline, focal_length, 
                           min_depth=0.5, max_depth=10.0, use_imu=False):
    """
    Generate ESVO2 mapping.yaml.
    
    ESVO2-specific additions:
    - USE_IMU: Enable/disable IMU integration
    - select_points_from_AA: Use AA maps for point selection
    - PROCESS_EVENT_NUM_AA: Number of points from AA map
    """
    # Reference: Official ESVO2 configs
    OFFICIAL_MAX_DISPARITY = 40
    OFFICIAL_MIN_DISPARITY = 1
    OFFICIAL_WIDTH = 240

    scale_factor = width / OFFICIAL_WIDTH
    computed_max_disp = baseline * focal_length / min_depth
    computed_min_disp = baseline * focal_length / max_depth
    scaled_official_max = int(OFFICIAL_MAX_DISPARITY * scale_factor)

    min_disparity = max(OFFICIAL_MIN_DISPARITY, int(computed_min_disp))
    max_disparity = min(int(computed_max_disp), scaled_official_max)

    if min_disparity + 20 <= scaled_official_max:
        max_disparity = max(max_disparity, min_disparity + 20)

    inv_depth_min = 1.0 / max_depth
    inv_depth_max = 1.0 / min_depth
    is_high_res = width >= 480

    # Patch size scaling
    scale = width / 346.0
    patch_x = int(15 * scale)
    patch_y = int(7 * scale)
    if patch_x % 2 == 0:
        patch_x += 1
    if patch_y % 2 == 0:
        patch_y += 1
    patch_x = max(15, min(patch_x, 31))
    patch_y = max(7, min(patch_y, 15))

    config = {
        # Configuration for depth estimation
        'invDepth_min_range': round(inv_depth_min, 2),
        'invDepth_max_range': round(inv_depth_max, 2),
        'residual_vis_threshold': 30,
        'residual_vis_threshold_ln': 30,
        'stdVar_vis_threshold': 0.1,
        'stdVar_vis_threshold_ln': 0.1,
        'age_max_range': 10,
        'age_vis_threshold': 2,
        
        # Patch size for static BM
        'patch_size_X': patch_x,
        'patch_size_Y': patch_y,
        # Patch size for temporal BM
        'patch_size_X_2': 7,
        'patch_size_Y_2': 21,
        
        # EventBM parameters
        'BM_half_slice_thickness': 0.001,
        'BM_min_disparity': min_disparity,
        'BM_max_disparity': max_disparity,
        'BM_step': 1,
        'BM_ZNCC_Threshold': 0.3,
        'BM_bUpDownConfiguration': False,
        'distance_from_last_frame': 0.04,
        'SmoothTimeSurface': True,
        
        # Configuration for fusion
        'fusion_radius': 0,
        'FUSION_STRATEGY': 'CONST_POINTS',
        'maxNumFusionFrames': 40,
        'maxNumFusionFrames_ln': 40,
        'maxNumFusionPoints': 8000 if is_high_res else 5000,
        'LSnorm': 'Tdist',
        'Tdist_nu': 2.182,
        'Tdist_scale': 17.277,
        'Tdist_stdvar': 59.763,
        'LSnorm_ln': 'Tdist',
        'Tdist_nu_ln': 2.182,
        'Tdist_scale_ln': 17.277,
        'Tdist_stdvar_ln': 59.763,
        
        # Configuration for point sampling (ESVO2 specific: AA)
        'Denoising': True,
        'PROCESS_EVENT_NUM': 6000 if is_high_res else 4000,
        'PROCESS_EVENT_NUM_AA': 6000 if is_high_res else 4000,
        'x_patches': 4,
        'y_patches': 3,
        'select_points_from_AA': True,
        'eta_for_select_points': 0.1,
        
        # Configuration for visualization
        'Regularization': True,
        'RegularizationRadius': 5,
        'RegularizationMinNeighbours': 8,
        'RegularizationMinCloseNeighbours': 8,
        
        'bVisualizeGlobalPC': True,
        'visualizeGPC_interval': 2,
        'NumGPC_added_per_refresh': 3000,
        'visualize_range': min(max_depth, 5.0),
        
        # Configuration for mapping system
        'TS_HISTORY_LENGTH': 100,
        'USE_IMU': use_imu,
        'INIT_SGM_DP_NUM_THRESHOLD': 1500 if is_high_res else 1000,
        'mapping_rate_hz': 10,
        'large_scale': False,
    }

    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"Written mapping config: {output_path}")
    print(f"  - Disparity range: {min_disparity} - {max_disparity}")
    print(f"  - USE_IMU: {use_imu}")

def generate_tracking_config(output_path, width, min_depth=0.5, max_depth=10.0, use_imu=False):
    """
    Generate ESVO2 tracking.yaml.
    
    ESVO2-specific: USE_IMU parameter
    """
    inv_depth_min = 1.0 / max_depth
    inv_depth_max = 1.0 / min_depth
    
    config = {
        'invDepth_min_range': round(inv_depth_min, 2),
        'invDepth_max_range': round(inv_depth_max, 2),
        'TS_HISTORY_LENGTH': 100,
        'REF_HISTORY_LENGTH': 10,
        'tracking_rate_hz': 100,
        'patch_size_X': 1,
        'patch_size_Y': 1,
        'kernelSize': 5,
        'MAX_REGISTRATION_POINTS': 2000,
        'BATCH_SIZE': 300,
        'MAX_ITERATION': 20,
        'LSnorm': 'Huber',
        'huber_threshold': 50,
        'MIN_NUM_EVENTS': 1000,
        'RegProblemType': 1,  # 1=analytical (faster)
        'SAVE_TRAJECTORY': True,
        'PATH_TO_SAVE_TRAJECTORY': '/output/',
        'VISUALIZE_TRAJECTORY': True,
        'USE_IMU': use_imu,
    }
    
    with open(output_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print(f"Written tracking config: {output_path}")
    print(f"  - USE_IMU: {use_imu}")

def generate_image_representation_config(output_path, is_left=True, generation_rate_hz=100):
    """
    Generate ESVO2 image_representation.yaml.
    
    This replaces ESVO's ts_parameters.yaml with more advanced event representation.
    Generates both Time Surface (TS) and Accumulated Activity (AA) maps.
    """
    config = {
        'synchronize_on_external_time': True,
        'use_stereo_cam': True,
        'representation_mode': 2,  # 0=TS, 1=AA, 2=Both (parallel)
        'decay_ms': 20,
        'median_blur_kernel_size': 1,
        'blur_size': 7,
        'use_sim_time': True,
        'is_left': is_left,
        'x_patches': 8,
        'y_patches': 6,
        'generation_rate_hz': generation_rate_hz,
    }
    
    with open(output_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    side = "left" if is_left else "right"
    print(f"Written image_representation config ({side}): {output_path}")

def generate_all_configs(session_path, min_depth=0.5, max_depth=10.0, use_imu=False):
    """Generate all ESVO2 configuration files for a session."""
    esvo2_config_dir = os.path.join(session_path, "config", "esvo2")

    if not os.path.exists(esvo2_config_dir):
        raise FileNotFoundError(
            f"ESVO2 config directory not found at {esvo2_config_dir}. "
            "Run camchain_to_esvo2.py first."
        )
    
    left_yaml = os.path.join(esvo2_config_dir, "left.yaml")
    right_yaml = os.path.join(esvo2_config_dir, "right.yaml")
    if not os.path.exists(left_yaml) or not os.path.exists(right_yaml):
        raise FileNotFoundError(
            f"ESVO2 calibration files not found in {esvo2_config_dir}. "
            "Run camchain_to_esvo2.py first."
        )

    left_calib, right_calib = load_esvo2_calib(esvo2_config_dir)

    width = left_calib["image_width"]
    height = left_calib["image_height"]
    baseline = compute_baseline(right_calib)
    focal_length = compute_focal_length(left_calib)

    print(f"Camera: {width}x{height}")
    print(f"Baseline: {baseline:.4f} m")
    print(f"Focal length: {focal_length:.2f} px")
    print(f"Depth range: {min_depth} - {max_depth} m")
    print(f"IMU mode: {use_imu}")
    print()

    generate_mapping_config(
        os.path.join(esvo2_config_dir, 'mapping.yaml'),
        width, baseline, focal_length, min_depth, max_depth, use_imu
    )
    
    generate_tracking_config(
        os.path.join(esvo2_config_dir, 'tracking.yaml'),
        width, min_depth, max_depth, use_imu
    )
    
    # Image representation configs (left generates both TS and AA, right only TS)
    generate_image_representation_config(
        os.path.join(esvo2_config_dir, 'image_representation.yaml'),
        is_left=True
    )
    generate_image_representation_config(
        os.path.join(esvo2_config_dir, 'image_representation_right.yaml'),
        is_left=False
    )
    
    print(f"\nAll ESVO2 configs written to: {esvo2_config_dir}")

def main():
    parser = argparse.ArgumentParser(
        description="Generate ESVO2 configuration files"
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
    parser.add_argument(
        "--use-imu",
        action="store_true",
        help="Enable IMU integration (requires IMU data in bag)"
    )
    
    args = parser.parse_args()
    generate_all_configs(args.session, args.min_depth, args.max_depth, args.use_imu)


if __name__ == "__main__":
    main()
