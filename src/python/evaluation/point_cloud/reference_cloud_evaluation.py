#!/usr/bin/env python3
"""
Minimal interactive evaluation of a reconstructed point cloud against a LiDAR
reference.

Pipeline:
  1. Load clouds
  2. Statistical Outlier Removal on the reconstruction
  3. Load or pick reference landmarks and cache them
  4. Pick the same landmarks on the reconstruction
  5. Kabsch alignment from landmark correspondences
  6. Single-scale rigid ICP refinement with GMLoss
  7. Downsample the aligned reconstruction to a common evaluation voxel
  8. Compute asymmetric distances reconstructed -> full reference
  9. Report RMSE, median, count, P@2cm, P@5cm

The evaluation is intentionally asymmetric: only reconstructed points are
measured against the reference. This matches the modality gap here:
semi-dense event-based structure versus dense LiDAR surface support.
"""

import argparse
import copy
import json
import os
import sys
import time

import numpy as np
import open3d as o3d


PICK_VOXEL = 0.05
DISPLAY_VOXEL = 0.02
EVAL_VOXEL = 0.02
PRECISION_AT_2CM = 0.02
PRECISION_AT_5CM = 0.05
SOR_NEIGHBORS = 50
SOR_STD_RATIO = 1.0
ICP_MAX_CORRESPONDENCE = 0.10
ICP_MAX_ITERATIONS = 20
PICK_POINT_SIZE = 8.0
VIEW_POINT_SIZE = 4.0
REFERENCE_COLOR = np.array([0.08, 0.45, 0.75], dtype=float)
RECON_COLOR = np.array([0.90, 0.38, 0.02], dtype=float)
BACKGROUND_COLOR = np.array([1.0, 1.0, 1.0], dtype=float)
LANDMARK_COLORS = np.array([
    [0.906, 0.298, 0.235],
    [0.180, 0.800, 0.443],
    [0.204, 0.596, 0.859],
    [0.945, 0.769, 0.059],
    [0.608, 0.349, 0.714],
    [0.902, 0.494, 0.133],
    [0.102, 0.737, 0.612],
    [0.929, 0.392, 0.545],
], dtype=float)


def default_landmark_path(reference_path):
    stem, _ = os.path.splitext(os.path.abspath(reference_path))
    return f"{stem}.landmarks.json"


def window_size():
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        width = int(root.winfo_screenwidth() * 0.85)
        height = int(root.winfo_screenheight() * 0.85)
        root.destroy()
        return max(width, 1280), max(height, 720)
    except Exception:
        return 1600, 1000


def show_geometries(geometries, title, point_size):
    width, height = window_size()
    vis = o3d.visualization.Visualizer()
    vis.create_window(window_name=title, width=width, height=height)
    for geometry in geometries:
        vis.add_geometry(geometry)
    render = vis.get_render_option()
    render.point_size = point_size
    render.background_color = BACKGROUND_COLOR
    render.show_coordinate_frame = True
    vis.run()
    vis.destroy_window()


def pick_points(pcd, title):
    width, height = window_size()
    print("   [Shift+Click] pick, [Shift+RightClick] undo, close when done.")
    vis = o3d.visualization.VisualizerWithEditing()
    vis.create_window(window_name=title, width=width, height=height)
    vis.add_geometry(pcd)
    render = vis.get_render_option()
    render.point_size = PICK_POINT_SIZE
    render.background_color = BACKGROUND_COLOR
    render.show_coordinate_frame = True
    vis.run()
    vis.destroy_window()
    return vis.get_picked_points()


def preview_cloud(pcd, color):
    cloud = pcd.voxel_down_sample(DISPLAY_VOXEL)
    cloud.paint_uniform_color(color)
    return cloud


def marker_radius(pcd):
    extent = np.linalg.norm(np.asarray(pcd.get_max_bound()) - np.asarray(pcd.get_min_bound()))
    return max(0.01, 0.01 * extent)


def landmark_markers(pcd, points):
    radius = marker_radius(pcd)
    markers = []
    for i, point in enumerate(np.asarray(points)):
        sphere = o3d.geometry.TriangleMesh.create_sphere(radius=radius)
        sphere.compute_vertex_normals()
        sphere.translate(point)
        sphere.paint_uniform_color(LANDMARK_COLORS[i % len(LANDMARK_COLORS)])
        markers.append(sphere)
    return markers


def show_landmarks(pcd, points, title, color):
    show_geometries([preview_cloud(pcd, color), *landmark_markers(pcd, points)], title, VIEW_POINT_SIZE)


def show_overlay(source, target, transform, title):
    src = preview_cloud(source, RECON_COLOR)
    tgt = preview_cloud(target, REFERENCE_COLOR)
    src.transform(transform)
    show_geometries([src, tgt], title, VIEW_POINT_SIZE)


def yes_no(prompt):
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"y", "n"}:
            return answer == "y"


def save_landmarks(path, reference_path, points):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "reference": os.path.abspath(reference_path),
                "point_count": int(len(points)),
                "points": np.asarray(points, dtype=float).tolist(),
            },
            f,
            indent=2,
        )


def load_landmarks(path, reference_path):
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    points = np.asarray(payload.get("points", []), dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 3:
        raise ValueError(f"Landmark file '{path}' does not contain >= 3 valid 3D points.")
    saved_reference = payload.get("reference")
    if saved_reference and os.path.abspath(saved_reference) != os.path.abspath(reference_path):
        print("   Warning: cached landmarks were created for a different reference cloud.")
    return points


def select_reference_landmarks(reference, reference_pick, reference_path, landmark_path, force_repick=False):
    if not force_repick and os.path.isfile(landmark_path):
        try:
            points = load_landmarks(landmark_path, reference_path=reference_path)
            print(f"\n   Loaded {len(points)} saved reference landmarks:")
            print(f"   {landmark_path}")
            print("   Review the saved landmarks on the reference cloud.")
            show_landmarks(reference, points, "Reference landmarks", REFERENCE_COLOR)
            if yes_no("   Use these saved reference landmarks? [y/n]: "):
                return points
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"   Could not load cached reference landmarks: {exc}")

    while True:
        ref_pick = copy.deepcopy(reference_pick)
        ref_pick.paint_uniform_color(REFERENCE_COLOR)
        print("\nPick >= 3 landmarks on the REFERENCE cloud (blue).")
        ref_idx = pick_points(ref_pick, "Reference cloud")
        if len(ref_idx) < 3:
            print("   Too few picks on the reference cloud.")
            if yes_no("   Retry reference landmark picking? [y/n]: "):
                continue
            return None
        points = np.asarray(ref_pick.points)[ref_idx]
        show_landmarks(reference, points, "Reference landmarks", REFERENCE_COLOR)
        if yes_no("   Save and use these reference landmarks? [y/n]: "):
            save_landmarks(landmark_path, reference_path, points)
            print(f"   Saved reference landmarks: {landmark_path}")
            return points


def pick_reconstruction_landmarks(reconstruction, reconstruction_pick, count):
    while True:
        recon_pick = copy.deepcopy(reconstruction_pick)
        recon_pick.paint_uniform_color(RECON_COLOR)
        print("\nPick the same landmarks on the RECONSTRUCTED cloud (gold).")
        print(f"   Required picks: {count} in the same order as the reference colors.")
        recon_idx = pick_points(recon_pick, "Reconstructed cloud")
        if len(recon_idx) < count:
            print(f"   Too few picks on the reconstructed cloud (need {count}).")
            if yes_no("   Retry reconstructed landmark picking? [y/n]: "):
                continue
            return None
        if len(recon_idx) > count:
            print(f"   Using the first {count} reconstructed picks.")
        points = np.asarray(recon_pick.points)[recon_idx[:count]]
        show_landmarks(reconstruction, points, "Reconstructed landmarks", RECON_COLOR)
        if yes_no("   Use these reconstructed landmarks? [y/n]: "):
            return points


def kabsch(source_points, target_points):
    source_center = source_points.mean(axis=0)
    target_center = target_points.mean(axis=0)
    H = (source_points - source_center).T @ (target_points - target_center)
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ np.diag([1.0, 1.0, np.sign(np.linalg.det(Vt.T @ U.T))]) @ U.T
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = target_center - R @ source_center
    return T


def sor_filter(pcd, nb_neighbors, std_ratio):
    if len(pcd.points) < 3 or nb_neighbors <= 0:
        return pcd, 0
    filtered, _ = pcd.remove_statistical_outlier(
        nb_neighbors=min(nb_neighbors, len(pcd.points) - 1),
        std_ratio=std_ratio,
    )
    return filtered, len(pcd.points) - len(filtered.points)


def estimate_normals(pcd, radius):
    pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=30))
    return pcd


def run_icp(source, target, init, max_correspondence, max_iterations):
    source_icp = estimate_normals(copy.deepcopy(source), max_correspondence * 2.0)
    target_icp = estimate_normals(copy.deepcopy(target), max_correspondence * 2.0)
    loss = o3d.pipelines.registration.GMLoss(max_correspondence)
    return o3d.pipelines.registration.registration_icp(
        source_icp,
        target_icp,
        max_correspondence,
        init,
        o3d.pipelines.registration.TransformationEstimationPointToPlane(loss),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=max_iterations),
    )


def evaluation_cloud(reconstruction_aligned, eval_voxel):
    if eval_voxel <= 0:
        return reconstruction_aligned
    return reconstruction_aligned.voxel_down_sample(eval_voxel)


def compute_metrics(reconstruction_aligned, reference, eval_voxel):
    reconstruction_eval = evaluation_cloud(reconstruction_aligned, eval_voxel)
    if not reconstruction_eval.has_points():
        raise ValueError("Reconstructed cloud is empty after alignment.")
    if not reference.has_points():
        raise ValueError("Reference cloud is empty.")

    distances = np.asarray(reconstruction_eval.compute_point_cloud_distance(reference))
    return {
        "median_error_cm": float(np.median(distances)) * 100.0,
        "rmse_error_cm": float(np.sqrt(np.mean(distances ** 2))) * 100.0,
        "precision_at_2cm": float(np.mean(distances <= PRECISION_AT_2CM)),
        "precision_at_5cm": float(np.mean(distances <= PRECISION_AT_5CM)),
        "evaluated_reconstructed_point_count": int(len(reconstruction_eval.points)),
    }


def align(reconstruction, reference, reference_path, landmark_path, pick_voxel, icp_max_correspondence, icp_max_iterations):
    print("\n[2/3] Alignment")
    reconstruction_pick = reconstruction.voxel_down_sample(pick_voxel)
    reference_pick = reference.voxel_down_sample(pick_voxel)
    print(f"   Reconstructed: {len(reconstruction_pick.points)} pts for picking")
    print(f"   Reference:     {len(reference_pick.points)} pts for picking")

    reference_points = select_reference_landmarks(reference, reference_pick, reference_path, landmark_path)
    if reference_points is None:
        return None

    while True:
        source_points = pick_reconstruction_landmarks(reconstruction, reconstruction_pick, len(reference_points))
        if source_points is None:
            return None

        kabsch_transform = kabsch(source_points, reference_points)
        landmark_errors = np.linalg.norm(
            (kabsch_transform[:3, :3] @ source_points.T).T + kabsch_transform[:3, 3] - reference_points,
            axis=1,
        )
        print(f"   Kabsch from {len(reference_points)} pairs, mean landmark error: {landmark_errors.mean() * 1000:.1f} mm")
        show_overlay(reconstruction, reference, kabsch_transform, "Kabsch alignment")

        print("   Running single-scale ICP ...")
        icp = run_icp(reconstruction, reference, kabsch_transform, icp_max_correspondence, icp_max_iterations)
        print(f"   ICP: fitness={icp.fitness:.3f}, inlier_rmse={icp.inlier_rmse * 1000:.1f} mm")
        show_overlay(reconstruction, reference, icp.transformation, "ICP alignment")

        if yes_no("   Accept alignment? [y/n]: "):
            return {
                "reference_points": reference_points,
                "kabsch_transform": kabsch_transform,
                "kabsch_mean_landmark_error_cm": float(landmark_errors.mean()) * 100.0,
                "icp_result": icp,
                "transform": icp.transformation,
            }
        if yes_no("   Re-pick reference landmarks? [y/n]: "):
            reference_points = select_reference_landmarks(
                reference,
                reference_pick,
                reference_path,
                landmark_path,
                force_repick=True,
            )
            if reference_points is None:
                return None


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, help="Path to the LiDAR reference .pcd")
    parser.add_argument("--reconstructed", required=True, help="Path to the reconstructed .pcd")
    parser.add_argument("--method", required=True, help="Method label for the report")
    parser.add_argument("--pick-voxel", type=float, default=PICK_VOXEL, help="Voxel size used for landmark picking")
    parser.add_argument(
        "--eval-voxel",
        type=float,
        default=EVAL_VOXEL,
        help="Common voxel size used to downsample all aligned reconstructions before scoring",
    )
    parser.add_argument(
        "--reference-landmarks",
        default=None,
        help="Optional JSON file with cached reference landmarks (default: next to the reference cloud)",
    )
    parser.add_argument(
        "--icp-max-correspondence",
        type=float,
        default=ICP_MAX_CORRESPONDENCE,
        help="ICP max correspondence distance in meters",
    )
    parser.add_argument(
        "--icp-max-iterations",
        type=int,
        default=ICP_MAX_ITERATIONS,
        help="ICP iteration budget",
    )
    parser.add_argument("--output", default=None, help="Output JSON report path")
    return parser.parse_args()


def main():
    cfg = parse_args()
    start = time.time()
    if cfg.reference_landmarks is None:
        cfg.reference_landmarks = default_landmark_path(cfg.reference)
    if cfg.output is None:
        out_dir = os.path.dirname(os.path.abspath(cfg.reconstructed))
        cfg.output = os.path.join(out_dir, f"evaluation_{cfg.method}.json")

    reference = o3d.io.read_point_cloud(cfg.reference)
    reconstruction = o3d.io.read_point_cloud(cfg.reconstructed)
    if not reference.has_points():
        sys.exit(f"Reference cloud '{cfg.reference}' is empty.")
    if not reconstruction.has_points():
        sys.exit(f"Reconstructed cloud '{cfg.reconstructed}' is empty.")

    print(f"Reference:     {len(reference.points)} pts  ({cfg.reference})")
    print(f"Reconstructed: {len(reconstruction.points)} pts ({cfg.reconstructed})")
    print(f"Landmarks:     {os.path.abspath(cfg.reference_landmarks)}")

    print("\n[1/3] Preprocessing reconstructed cloud")
    reconstruction, removed = sor_filter(reconstruction, SOR_NEIGHBORS, SOR_STD_RATIO)
    print(f"   SOR: nb_neighbors={SOR_NEIGHBORS}, std_ratio={SOR_STD_RATIO:.3f}")
    print(f"   Reconstructed after SOR: {len(reconstruction.points)} pts (removed {removed})")
    if not reconstruction.has_points():
        sys.exit("Reconstructed cloud is empty after Statistical Outlier Removal.")

    alignment = align(
        reconstruction,
        reference,
        cfg.reference,
        cfg.reference_landmarks,
        cfg.pick_voxel,
        cfg.icp_max_correspondence,
        cfg.icp_max_iterations,
    )
    if alignment is None:
        sys.exit("Alignment aborted.")

    reconstruction_aligned = copy.deepcopy(reconstruction)
    reconstruction_aligned.transform(alignment["transform"])

    print("\n[3/3] Computing metrics")
    metrics = compute_metrics(reconstruction_aligned, reference, cfg.eval_voxel)
    reconstruction_eval = evaluation_cloud(reconstruction_aligned, cfg.eval_voxel)
    print(f"   Evaluation voxel: {cfg.eval_voxel * 1000:.0f} mm")
    print(f"   Evaluated reconstruction points: {len(reconstruction_eval.points)}")
    print(f"   Reference points: {len(reference.points)}")

    print(f"\n{'=' * 55}")
    print(f"  Method:              {cfg.method}")
    print("  Evaluation:          asymmetric edge-to-surface")
    print(f"  Evaluated points:    {metrics['evaluated_reconstructed_point_count']}")
    print(f"  Median error:        {metrics['median_error_cm']:.2f} cm")
    print(f"  RMSE error:          {metrics['rmse_error_cm']:.2f} cm")
    print(f"  Precision @ 2 cm:    {metrics['precision_at_2cm']:.3f}")
    print(f"  Precision @ 5 cm:    {metrics['precision_at_5cm']:.3f}")
    print(f"{'=' * 55}")

    report = {
        "method": cfg.method,
        "reference": os.path.abspath(cfg.reference),
        "reconstructed": os.path.abspath(cfg.reconstructed),
        "reference_landmarks": os.path.abspath(cfg.reference_landmarks),
        "alignment": {
            "reference_landmark_count": int(len(alignment["reference_points"])),
            "kabsch_mean_landmark_error_cm": alignment["kabsch_mean_landmark_error_cm"],
            "kabsch_transform": alignment["kabsch_transform"].tolist(),
            "icp_fitness": float(alignment["icp_result"].fitness),
            "icp_inlier_rmse_cm": float(alignment["icp_result"].inlier_rmse) * 100.0,
            "icp_max_correspondence_m": cfg.icp_max_correspondence,
            "icp_max_iterations": cfg.icp_max_iterations,
            "alignment_mode": "kabsch_icp",
            "transform": alignment["transform"].tolist(),
        },
        "parameters": {
            "evaluation_voxel_m": cfg.eval_voxel,
            "precision_at_2cm_threshold_m": PRECISION_AT_2CM,
            "precision_at_5cm_threshold_m": PRECISION_AT_5CM,
            "pick_voxel_m": cfg.pick_voxel,
            "sor_neighbors": SOR_NEIGHBORS,
            "sor_std_ratio": SOR_STD_RATIO,
        },
        "metrics": metrics,
        "elapsed_s": time.time() - start,
    }

    os.makedirs(os.path.dirname(os.path.abspath(cfg.output)) or ".", exist_ok=True)
    with open(cfg.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report saved: {cfg.output}")


if __name__ == "__main__":
    main()
