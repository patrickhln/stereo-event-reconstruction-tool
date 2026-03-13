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

# Dataset families used when comparing official presets:
# - RPG stereo DAVIS240C (UZH RPG): indoor hand-held stereo event-camera scenes in
#   a motion-capture room; sequences include bin, boxes, desk, monitor, reader.
#   Dataset source: https://rpg.ifi.uzh.ch/ECCV18_stereo_davis.html
#   YAML sources:
#     - ESVO2/esvo2_core/cfg/mapping/mapping_rpg_AA.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_rpg_AA.yaml
# - UPenn / MVSEC indoor_flying (DAVIS346B): Multi Vehicle Stereo Event Camera, hexacopter, driving, handheld
#   indoor and outdoor environment; mostly translation-dominant motion with hovering segments.
#   Dataset source: https://daniilidis-group.github.io/mvsec/
#   YAML sources:
#     - ESVO2/esvo2_core/cfg/mapping/mapping_upenn_AA.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_upenn_AA.yaml
# - DSEC (Prophesse Gen3.1): large-scale outdoor driving scenes, including HDR and night-driving
#   sequences.
#   Dataset source: https://dsec.ifi.uzh.ch/
#   YAML sources:
#     - ESVO2/esvo2_core/cfg/mapping/mapping_dsec_AA.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_dsec_AA.yaml
# - TUM-VIE (Prophesee Gen4 HD): small indoor hand-held visual-inertial event-camera scenes.
#   Dataset source: https://cvg.cit.tum.de/data/datasets/visual-inertial-event-dataset
#   YAML sources:
#     - ESVO2/esvo2_core/cfg/mapping/mapping_tum_AA.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_tum_AA.yaml
# - VECtor (Prophesee Gen3 CD): small indoor hand-held event-camera scenes, including HDR and
#   aggressive-motion captures.
#   Dataset source: https://star-datasets.github.io/vector/
#   YAML sources:
#     - ESVO2/esvo2_core/cfg/mapping/mapping_vector_AA.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_vector_AA.yaml
# - DVXplorer / HNU outdoor: ESVO2 authors' outdoor stereo DVXplorer dataset
#   with IMU and GNSS; hnu_campus is a closed-loop campus trajectory and
#   hnu_peachlake is a winding narrow-street sequence.
#   Dataset source: https://arxiv.org/abs/2410.09374
#   YAML sources:
#     - ESVO2/esvo2_core/cfg/mapping/mapping_dvx_AA_mapping.yaml
#     - ESVO2/esvo2_core/cfg/mapping/mapping_dvx_AA_tracking.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_dvx_AA_mapping.yaml
#     - ESVO2/esvo2_core/cfg/tracking/tracking_dvx_AA_tracking.yaml

DVX_IMAGE_REPRESENTATION_PRESET = {
    "synchronize_on_external_time": True,
    "use_stereo_cam": True,
    "representation_mode": 2,
    "decay_ms": 20,
    "median_blur_kernel_size": 1,
    "blur_size": 7,
    "use_sim_time": True,
    "x_patches": 8,
    "y_patches": 6,
    "generation_rate_hz": 100,
}

DVX_MAPPING_PRESET = {
    "residual_vis_threshold": 30,
    "residual_vis_threshold_ln": 30,
    "stdVar_vis_threshold": 1,
    "stdVar_vis_threshold_ln": 1,
    "age_max_range": 10,
    "age_vis_threshold": 1,
    "patch_size_X": 15,
    "patch_size_Y": 7,
    "patch_size_X_2": 5,
    "patch_size_Y_2": 31,
    "BM_half_slice_thickness": 0.001,
    "BM_step": 3,
    "BM_ZNCC_Threshold": 0.2,
    "BM_bUpDownConfiguration": False,
    "distance_from_last_frame": 0.20,
    "SmoothTimeSurface": True,
    "fusion_radius": 2,
    "FUSION_STRATEGY": "CONST_FRAMES",
    "maxNumFusionFrames": 5,
    "maxNumFusionFrames_ln": 5,
    "maxNumFusionPoints": 20000,
    "LSnorm": "Tdist",
    "Tdist_nu": 2.182,
    "Tdist_scale": 17.277,
    "Tdist_stdvar": 59.763,
    "LSnorm_ln": "Tdist",
    "Tdist_nu_ln": 2.182,
    "Tdist_scale_ln": 17.277,
    "Tdist_stdvar_ln": 59.763,
    "Denoising": False,
    "PROCESS_EVENT_NUM": 10000, 
    "PROCESS_EVENT_NUM_AA": 10000, 
    "x_patches": 8,
    "y_patches": 6,
    "select_points_from_AA": True,
    "eta_for_select_points": 0.1,
    "Regularization": True,
    "RegularizationRadius": 20,
    "RegularizationMinNeighbours": 32,
    "RegularizationMinCloseNeighbours": 32,
    "bVisualizeGlobalPC": True,
    "visualizeGPC_interval": 0.5,
    "NumGPC_added_per_refresh": 10000,
    "visualize_range": 30,
    "TS_HISTORY_LENGTH": 100,
    "INIT_SGM_DP_NUM_THRESHOLD": 500,
    "mapping_rate_hz": 20,
    "large_scale": True,
}

DVX_TRACKING_PRESET = {
    "TS_HISTORY_LENGTH": 100,
    "REF_HISTORY_LENGTH": 10,
    "tracking_rate_hz": 100,
    "patch_size_X": 1,
    "patch_size_Y": 1,
    "kernelSize": 5,
    "MAX_REGISTRATION_POINTS": 2000,
    "BATCH_SIZE": 300,
    "MAX_ITERATION": 10,
    "LSnorm": "Huber",
    "huber_threshold": 50,
    "MIN_NUM_EVENTS": 1000,
    "RegProblemType": 1,
    "SAVE_TRAJECTORY": True,
    "VISUALIZE_TRAJECTORY": True,
}

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

def is_dvx_profile(width):
    return width >= 480

def compute_disparity_bounds(baseline, focal_length, min_depth, max_depth, disparity_cap):
    computed_max_disp = baseline * focal_length / min_depth
    computed_min_disp = baseline * focal_length / max_depth

    min_disparity = max(0, int(np.floor(0.95 * computed_min_disp)))
    max_disparity = min(disparity_cap, int(np.ceil(1.05 * computed_max_disp)))
    if max_disparity <= min_disparity:
        max_disparity = min(disparity_cap, min_disparity + 1)

    return min_disparity, max_disparity

def generate_mapping_config(output_path, width, baseline, focal_length, 
                           min_depth=0.5, max_depth=10.0, use_imu=False):
    """
    Generate ESVO2 mapping.yaml.
    
    ESVO2-specific additions:
    - USE_IMU: Enable/disable IMU integration
    - select_points_from_AA: Use AA maps for point selection
    - PROCESS_EVENT_NUM_AA: Number of points from AA map
    """
    inv_depth_min = 1.0 / max_depth
    inv_depth_max = 1.0 / min_depth
    if is_dvx_profile(width):
        min_disparity, max_disparity = compute_disparity_bounds(
            baseline, focal_length, min_depth, max_depth, disparity_cap=150
        )
        config = dict(DVX_MAPPING_PRESET)
    else:
        min_disparity, max_disparity = compute_disparity_bounds(
            baseline, focal_length, min_depth, max_depth, disparity_cap=max(40, width // 2)
        )
        config = {
            "residual_vis_threshold": 30,
            "residual_vis_threshold_ln": 30,
            "stdVar_vis_threshold": 0.1,
            "stdVar_vis_threshold_ln": 0.1,
            "age_max_range": 10,
            "age_vis_threshold": 2,
            "patch_size_X": 15,
            "patch_size_Y": 7,
            "patch_size_X_2": 7,
            "patch_size_Y_2": 21,
            "BM_half_slice_thickness": 0.001,
            "BM_step": 1,
            "BM_ZNCC_Threshold": 0.3,
            "BM_bUpDownConfiguration": False,
            "distance_from_last_frame": 0.04,
            "SmoothTimeSurface": True,
            "fusion_radius": 0,
            "FUSION_STRATEGY": "CONST_POINTS",
            "maxNumFusionFrames": 40,
            "maxNumFusionFrames_ln": 40,
            "maxNumFusionPoints": 8000,
            "LSnorm": "Tdist",
            "Tdist_nu": 2.182,
            "Tdist_scale": 17.277,
            "Tdist_stdvar": 59.763,
            "LSnorm_ln": "Tdist",
            "Tdist_nu_ln": 2.182,
            "Tdist_scale_ln": 17.277,
            "Tdist_stdvar_ln": 59.763,
            "Denoising": True,
            "PROCESS_EVENT_NUM": 6000,
            "PROCESS_EVENT_NUM_AA": 6000,
            "x_patches": 4,
            "y_patches": 3,
            "select_points_from_AA": True,
            "eta_for_select_points": 0.1,
            "Regularization": True,
            "RegularizationRadius": 5,
            "RegularizationMinNeighbours": 8,
            "RegularizationMinCloseNeighbours": 8,
            "bVisualizeGlobalPC": True,
            "visualizeGPC_interval": 2,
            "NumGPC_added_per_refresh": 3000,
            "visualize_range": min(max_depth, 5.0),
            "TS_HISTORY_LENGTH": 100,
            "INIT_SGM_DP_NUM_THRESHOLD": 1500,
            "mapping_rate_hz": 10,
            "large_scale": False,
        }

    config.update({
        "invDepth_min_range": round(inv_depth_min, 2),
        "invDepth_max_range": round(inv_depth_max, 2),
        "BM_min_disparity": min_disparity,
        "BM_max_disparity": max_disparity,
        "USE_IMU": use_imu,
    })

    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"Written mapping config: {output_path}")
    print(f"  - Preset: {'official_dvx_large_scale' if is_dvx_profile(width) else 'generic'}")
    print(f"  - Disparity range: {min_disparity} - {max_disparity}")
    print(f"  - USE_IMU: {use_imu}")

def generate_tracking_config(output_path, width, min_depth=0.5, max_depth=10.0, use_imu=False):
    """
    Generate ESVO2 tracking.yaml.
    
    ESVO2-specific: USE_IMU parameter
    """
    inv_depth_min = 1.0 / max_depth
    inv_depth_max = 1.0 / min_depth
    
    if is_dvx_profile(width):
        config = dict(DVX_TRACKING_PRESET)
    else:
        config = {
            "TS_HISTORY_LENGTH": 100,
            "REF_HISTORY_LENGTH": 10,
            "tracking_rate_hz": 100,
            "patch_size_X": 1,
            "patch_size_Y": 1,
            "kernelSize": 5,
            "MAX_REGISTRATION_POINTS": 2000,
            "BATCH_SIZE": 300,
            "MAX_ITERATION": 20,
            "LSnorm": "Huber",
            "huber_threshold": 50,
            "MIN_NUM_EVENTS": 1000,
            "RegProblemType": 1,
            "SAVE_TRAJECTORY": True,
            "VISUALIZE_TRAJECTORY": True,
        }
    config.update({
        "invDepth_min_range": round(inv_depth_min, 2),
        "invDepth_max_range": round(inv_depth_max, 2),
        "PATH_TO_SAVE_TRAJECTORY": "/output/",
        "USE_IMU": use_imu,
    })
    
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
    config = dict(DVX_IMAGE_REPRESENTATION_PRESET)
    config.update({
        "is_left": is_left,
        "generation_rate_hz": generation_rate_hz,
    })
    
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
