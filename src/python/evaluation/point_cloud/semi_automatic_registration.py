#!/usr/bin/env python3
"""
Multi-scan LiDAR registration for building a reference point cloud.

Pipeline:
  1. Topology   -- FPFH + RANSAC for pairwise overlap and registration order
  2. Backbone   -- Semi-automatic pairwise registration (RANSAC seeds or
                   manual picking + Kabsch), refined by multi-scale ICP
  3. Loop close -- Automatic ICP for non-backbone pairs above overlap gate
  4. Merge      -- Pose-graph optimization, transform + downsample + filter

A JSON checkpoint is written after every accepted backbone pair so the
session can be resumed if interrupted.
"""

import argparse
import copy
import glob
import json
import os
import sys
import time

import numpy as np
import open3d as o3d

TOPOLOGY_VOXEL = 0.10
TOPOLOGY_EVAL_DIST = 0.10
MIN_TOPOLOGY_FITNESS = 0.08
ICP_VOXELS = [0.16, 0.08, 0.04, 0.02, 0.01]
LOOP_VOXELS = [0.08, 0.04, 0.02, 0.01]
PICK_VOXEL = 0.05
MERGE_VOXEL = 0.02
EVAL_DIST = 0.08
CORR_FACTOR = 2.5
LOOP_MIN_TOPO = 0.12
LOOP_MIN_FIT = 0.30
LOOP_MAX_RMSE = 0.016
MIN_SCAN_SUPPORT = 2
RANSAC_RETRIES = 5
PICK_POINT_SIZE = 8.0
VIEW_POINT_SIZE = 4.0
SOURCE_COLOR = np.array([1.0, 0.706, 0.0], dtype=float)
TARGET_COLOR = np.array([0.0, 0.651, 0.929], dtype=float)
BACKGROUND_COLOR = np.array([1.0, 1.0, 1.0], dtype=float)


def load_scans(folder):
    paths = sorted(glob.glob(os.path.join(folder, "*.pcd")))
    if len(paths) < 2:
        sys.exit(f"Need >= 2 .pcd files in '{folder}', found {len(paths)}.")
    pcds = []
    for p in paths:
        pcd = o3d.io.read_point_cloud(p)
        if not pcd.has_points():
            sys.exit(f"'{p}' is empty.")
        pcds.append(pcd)
    return paths, pcds


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


def downsample(pcd, voxel):
    down = pcd.voxel_down_sample(voxel)
    down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 2, max_nn=30))
    return down


def compute_fpfh(pcd, voxel):
    down = downsample(pcd, voxel)
    fpfh = o3d.pipelines.registration.compute_fpfh_feature(
        down, o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 5, max_nn=100),
    )
    return down, fpfh


def run_ransac(src_down, tgt_down, src_fpfh, tgt_fpfh, voxel):
    return o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
        src_down, tgt_down, src_fpfh, tgt_fpfh,
        mutual_filter=True,
        max_correspondence_distance=voxel * 1.5,
        estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
        ransac_n=3,
        checkers=[
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(voxel * 1.5),
        ],
        criteria=o3d.pipelines.registration.RANSACConvergenceCriteria(100000, 0.999),
    )


def show_overlay(source, target, transform, title, voxel):
    src = source.voxel_down_sample(max(voxel, 0.01))
    tgt = target.voxel_down_sample(max(voxel, 0.01))
    src.paint_uniform_color(SOURCE_COLOR)
    tgt.paint_uniform_color(TARGET_COLOR)
    src.transform(transform)
    show_geometries([src, tgt], title, VIEW_POINT_SIZE)


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


def yes_no(prompt):
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"y", "n"}:
            return answer == "y"


def estimate_topology(pcds, voxel, eval_dist):
    n = len(pcds)
    print(f"\n[1/4] Topology search ({n*(n-1)//2} pairs, voxel={voxel:.2f} m)")
    downs, fpfhs = [], []
    for k, pcd in enumerate(pcds):
        d, f = compute_fpfh(pcd, voxel)
        downs.append(d)
        fpfhs.append(f)
        print(f"   scan {k}: {len(d.points)} pts")

    overlap = np.zeros((n, n))
    seeds = {}
    for i in range(n):
        for j in range(i + 1, n):
            result = run_ransac(downs[i], downs[j], fpfhs[i], fpfhs[j], voxel)
            ev = o3d.pipelines.registration.evaluate_registration(
                downs[i], downs[j], eval_dist, result.transformation,
            )
            overlap[i, j] = overlap[j, i] = float(ev.fitness)
            seeds[(i, j)] = result.transformation
            print(f"   {i}-{j}: {overlap[i, j]:.3f}")

    return overlap, seeds, {k: (downs[k], fpfhs[k]) for k in range(n)}


def plan_order(overlap, min_fitness):
    n = overlap.shape[0]
    best_i, best_j = np.unravel_index(np.argmax(np.triu(overlap, k=1)), overlap.shape)
    root = int(best_i)
    registered = {root, int(best_j)}
    order = [(root, int(best_j))]

    while len(registered) < n:
        best_score, best_src, best_tgt = -1, -1, -1
        for src in registered:
            for tgt in range(n):
                if tgt in registered:
                    continue
                if overlap[src, tgt] >= min_fitness and overlap[src, tgt] > best_score:
                    best_score = overlap[src, tgt]
                    best_src, best_tgt = src, tgt
        if best_tgt < 0:
            missing = sorted(set(range(n)) - registered)
            sys.exit(f"Cannot extend spanning tree. Unreachable: {missing}\n"
                     f"Try lowering --min-topology-fitness (currently {min_fitness}).")
        registered.add(best_tgt)
        order.append((best_src, best_tgt))

    return root, order


def get_seed(seeds, src, tgt):
    if src < tgt:
        return seeds.get((src, tgt))
    T = seeds.get((tgt, src))
    return np.linalg.inv(T) if T is not None else None


def rerun_ransac(fpfh_cache, src_id, tgt_id, voxel, eval_dist):
    src_down, src_fpfh = fpfh_cache[src_id]
    tgt_down, tgt_fpfh = fpfh_cache[tgt_id]
    result = run_ransac(src_down, tgt_down, src_fpfh, tgt_fpfh, voxel)
    ev = o3d.pipelines.registration.evaluate_registration(
        src_down, tgt_down, eval_dist, result.transformation,
    )
    return result.transformation, float(ev.fitness)


def multiscale_icp(src, tgt, init, voxels, corr_factor):
    T = init
    for v in sorted(voxels, reverse=True):
        sd = downsample(src, v)
        td = downsample(tgt, v)
        res = o3d.pipelines.registration.registration_icp(
            sd, td, v * corr_factor, T,
            o3d.pipelines.registration.TransformationEstimationPointToPlane(),
            o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=100),
        )
        T = res.transformation
        fit, rmse = float(res.fitness), float(res.inlier_rmse)
        print(f"   ICP @ {v*1000:6.1f} mm: fitness={fit:.3f}, rmse={rmse*1000:.1f} mm")
    # Information matrix from finest scale (sd, td still bound from last iteration)
    info = o3d.pipelines.registration.get_information_matrix_from_point_clouds(
        sd, td, min(voxels) * corr_factor, T,
    )
    return T, info, fit, rmse


def register_pair_interactive(src_pcd, tgt_pcd, src_id, tgt_id, seed, cfg, fpfh_cache):
    print(f"\n{'='*55}\nRegistering scan {tgt_id} <- scan {src_id}\n{'='*55}")
    src_down = src_pcd.voxel_down_sample(cfg.pick_voxel)
    tgt_down = tgt_pcd.voxel_down_sample(cfg.pick_voxel)

    while True:
        init = None
        active_seed = seed

        # Try RANSAC seeds
        if seed is not None:
            current_seed = seed
            for attempt in range(cfg.ransac_retries):
                ev = o3d.pipelines.registration.evaluate_registration(
                    src_down, tgt_down, cfg.pick_voxel, current_seed,
                )
                label = "RANSAC seed" if attempt == 0 else f"RANSAC re-roll {attempt}"
                print(f"   {label}: fitness={ev.fitness:.3f}, "
                      f"mean correspondence error: {ev.inlier_rmse*1000:.1f} mm")
                show_overlay(src_pcd, tgt_pcd, current_seed,
                             f"{label} {src_id} (gold) + {tgt_id} (blue)", cfg.pick_voxel)

                if yes_no("   Accept this seed and run ICP? [y/n]: "):
                    init = current_seed
                    active_seed = current_seed
                    break

                remaining = cfg.ransac_retries - attempt - 1
                if remaining > 0:
                    print(f"   Re-rolling RANSAC ({remaining} attempts left) ...")
                    current_seed, _ = rerun_ransac(
                        fpfh_cache, src_id, tgt_id, cfg.topology_voxel, cfg.topology_eval_dist,
                    )
                else:
                    print("   All RANSAC attempts rejected. Falling back to manual picking.")

        # Manual picking fallback
        while init is None:
            src_aligned = copy.deepcopy(src_down)
            if active_seed is not None:
                src_aligned.transform(active_seed)
            src_aligned.paint_uniform_color(SOURCE_COLOR)
            tgt_pick = copy.deepcopy(tgt_down)
            tgt_pick.paint_uniform_color(TARGET_COLOR)

            print(f"\nPick >= 3 corresponding points on scan {src_id} (gold).")
            si = pick_points(src_aligned, f"Scan {src_id} (SOURCE, gold)")
            print(f"Now pick the same points on scan {tgt_id} (blue).")
            ti = pick_points(tgt_pick, f"Scan {tgt_id} (TARGET, blue)")

            if len(si) < 3 or len(ti) < 3:
                print("   Too few picks (need >= 3 on each).")
                if yes_no("   Retry picking? [y/n]: "):
                    continue
                return None

            n = min(len(si), len(ti))
            if len(si) != len(ti):
                print(f"   Count mismatch, using first {n} pairs.")

            sp_aligned = np.asarray(src_aligned.points)[si[:n]]
            tp = np.asarray(tgt_pick.points)[ti[:n]]
            if active_seed is not None:
                seed_inv = np.linalg.inv(active_seed)
                sp_original = (seed_inv[:3, :3] @ sp_aligned.T).T + seed_inv[:3, 3]
            else:
                sp_original = sp_aligned

            init = kabsch(sp_original, tp)
            landmark_errors = np.linalg.norm(
                (init[:3, :3] @ sp_original.T).T + init[:3, 3] - tp, axis=1,
            )
            print(f"   Kabsch from {n} pairs, mean error: {landmark_errors.mean()*1000:.1f} mm")
            show_overlay(src_pcd, tgt_pcd, init, f"Kabsch {src_id}->{tgt_id}", cfg.pick_voxel)

            if not yes_no("   Run ICP on this initialization? [y/n]: "):
                init = None
                if yes_no("   Retry picking? [y/n]: "):
                    continue
                return None

        # ICP refinement
        print("   Running multi-scale ICP ...")
        T, info, fit, rmse = multiscale_icp(
            src_pcd, tgt_pcd, init, cfg.icp_voxels, cfg.corr_factor,
        )
        show_overlay(src_pcd, tgt_pcd, T, f"ICP result {src_id}->{tgt_id}", cfg.pick_voxel)
        print(f"   Result: fitness={fit:.3f}, rmse={rmse*1000:.1f} mm")

        if yes_no("   Accept? [y/n]: "):
            return T, info, fit, rmse
        if not yes_no("   Retry from scratch? [y/n]: "):
            return None


def register_backbone(pcds, overlap, seeds, root, order, cfg, checkpoint_path, fpfh_cache):
    print("\n[2/4] Backbone registration")
    poses = {root: np.eye(4)}
    edges = []

    if os.path.exists(checkpoint_path):
        with open(checkpoint_path, "r") as f:
            ckpt = json.load(f)
        if ckpt.get("root") == root and [tuple(p) for p in ckpt.get("order", [])] == order:
            poses = {int(k): np.array(v) for k, v in ckpt["poses"].items()}
            edges = list(ckpt["edges"])
            print(f"   Resumed from checkpoint: {len(poses)} scans already registered.")
        else:
            print(f"   Stale checkpoint (root={ckpt.get('root')}), discarding.")

    for src_id, tgt_id in order:
        if tgt_id in poses:
            continue
        result = register_pair_interactive(
            pcds[src_id], pcds[tgt_id], src_id, tgt_id,
            get_seed(seeds, src_id, tgt_id), cfg, fpfh_cache,
        )
        if result is None:
            sys.exit("Registration aborted.")

        T, info, fit, rmse = result
        poses[tgt_id] = poses[src_id] @ np.linalg.inv(T)
        edges.append({
            "source": src_id, "target": tgt_id,
            "transform": T.tolist(), "info": info.tolist(),
            "fitness": fit, "rmse": rmse, "type": "backbone",
        })
        with open(checkpoint_path, "w") as f:
            json.dump({"root": root, "order": order,
                       "poses": {str(k): v.tolist() for k, v in poses.items()},
                       "edges": edges}, f, indent=2)
        print(f"   Checkpoint saved ({len(poses)}/{len(pcds)} scans registered).")

    return poses, edges


def add_loop_closures(pcds, poses, backbone_edges, overlap, cfg):
    print("\n[3/4] Automatic loop closures")
    ids = sorted(poses)
    bb = {(min(e["source"], e["target"]), max(e["source"], e["target"])) for e in backbone_edges}
    loops = []
    for i in ids:
        for j in ids:
            if j <= i or (i, j) in bb or overlap[i, j] < cfg.loop_min_topo:
                continue
            print(f"   Testing {i}-{j} (topology={overlap[i,j]:.3f}) ...")
            T, info, fit, rmse = multiscale_icp(
                pcds[i], pcds[j], np.linalg.inv(poses[j]) @ poses[i],
                cfg.loop_voxels, cfg.corr_factor,
            )
            if fit < cfg.loop_min_fit or rmse > cfg.loop_max_rmse:
                print(f"   Rejected (fitness={fit:.3f}, rmse={rmse*1000:.1f} mm)")
                continue
            loops.append({
                "source": i, "target": j,
                "transform": T.tolist(), "info": info.tolist(),
                "fitness": fit, "rmse": rmse, "type": "loop",
            })
            print(f"   Accepted (fitness={fit:.3f}, rmse={rmse*1000:.1f} mm)")
    print(f"   {len(loops)} loop closures accepted.")
    return loops


def build_pose_graph(poses, edges):
    ids = sorted(poses)
    id_to_node = {sid: idx for idx, sid in enumerate(ids)}
    pg = o3d.pipelines.registration.PoseGraph()
    for sid in ids:
        pg.nodes.append(o3d.pipelines.registration.PoseGraphNode(poses[sid]))
    for e in edges:
        pg.edges.append(o3d.pipelines.registration.PoseGraphEdge(
            id_to_node[e["source"]], id_to_node[e["target"]],
            np.array(e["transform"]), np.array(e["info"]),
            uncertain=(e["type"] == "loop"),
        ))
    return pg, id_to_node


def optimize(pg, max_corr_dist, reference_node_idx=0):
    o3d.pipelines.registration.global_optimization(
        pg,
        o3d.pipelines.registration.GlobalOptimizationLevenbergMarquardt(),
        o3d.pipelines.registration.GlobalOptimizationConvergenceCriteria(),
        o3d.pipelines.registration.GlobalOptimizationOption(
            max_correspondence_distance=max_corr_dist,
            edge_prune_threshold=0.25,
            preference_loop_closure=2.0,
            reference_node=reference_node_idx,
        ),
    )


def merge(pcds, pg, id_to_node, ids, voxel):
    merged = o3d.geometry.PointCloud()
    for sid in ids:
        aligned = copy.deepcopy(pcds[sid])
        aligned.transform(pg.nodes[id_to_node[sid]].pose)
        merged += aligned
    return merged.voxel_down_sample(voxel) if voxel > 0 else merged


def multiscan_consistency_filter(pcds, pg, id_to_node, ids, voxel, radius, min_support):
    trees = []
    for sid in ids:
        aligned = copy.deepcopy(pcds[sid])
        aligned.transform(pg.nodes[id_to_node[sid]].pose)
        if voxel > 0:
            aligned = aligned.voxel_down_sample(voxel)
        trees.append(o3d.geometry.KDTreeFlann(aligned))

    merged = merge(pcds, pg, id_to_node, ids, voxel)
    points = np.asarray(merged.points)
    keep = np.zeros(len(points), dtype=bool)
    for i, pt in enumerate(points):
        support = 0
        for tree in trees:
            if tree.search_radius_vector_3d(pt, radius)[0] > 0:
                support += 1
            if support >= min_support:
                break
        keep[i] = support >= min_support
    filtered = merged.select_by_index(np.where(keep)[0])
    return filtered, int(np.sum(~keep))


def evaluate_edges(pcds, pg, id_to_node, eval_dist, voxel):
    inv_map = {nid: sid for sid, nid in id_to_node.items()}
    metrics = []
    for e in pg.edges:
        si, ti = inv_map[e.source_node_id], inv_map[e.target_node_id]
        s = pcds[si].voxel_down_sample(voxel)
        t = pcds[ti].voxel_down_sample(voxel)
        s.transform(pg.nodes[e.source_node_id].pose)
        t.transform(pg.nodes[e.target_node_id].pose)
        ev = o3d.pipelines.registration.evaluate_registration(s, t, eval_dist)
        metrics.append({
            "source": si, "target": ti,
            "type": "loop" if e.uncertain else "backbone",
            "fitness": float(ev.fitness), "rmse": float(ev.inlier_rmse),
        })
    return metrics


def parse_args():
    p = argparse.ArgumentParser(description="Register unordered LiDAR scans into a reference point cloud.")
    p.add_argument("--folder", required=True)
    p.add_argument("--topology-voxel", type=float, default=TOPOLOGY_VOXEL)
    p.add_argument("--topology-eval-dist", type=float, default=TOPOLOGY_EVAL_DIST)
    p.add_argument("--min-topology-fitness", type=float, default=MIN_TOPOLOGY_FITNESS)
    p.add_argument("--icp-voxels", nargs="+", type=float, default=ICP_VOXELS)
    p.add_argument("--loop-voxels", nargs="+", type=float, default=LOOP_VOXELS)
    p.add_argument("--pick-voxel", type=float, default=PICK_VOXEL)
    p.add_argument("--merge-voxel", type=float, default=MERGE_VOXEL)
    p.add_argument("--eval-dist", type=float, default=EVAL_DIST)
    p.add_argument("--corr-factor", type=float, default=CORR_FACTOR)
    p.add_argument("--loop-min-topo", type=float, default=LOOP_MIN_TOPO)
    p.add_argument("--loop-min-fit", type=float, default=LOOP_MIN_FIT)
    p.add_argument("--loop-max-rmse", type=float, default=LOOP_MAX_RMSE)
    p.add_argument("--min-scan-support", type=int, default=MIN_SCAN_SUPPORT)
    p.add_argument("--ransac-retries", type=int, default=RANSAC_RETRIES)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    cfg = parse_args()
    t0 = time.time()

    paths, pcds = load_scans(cfg.folder)
    names = [os.path.basename(p) for p in paths]
    print(f"Loaded {len(pcds)} scans from '{cfg.folder}'.")
    for name, pcd in zip(names, pcds):
        print(f"  {name}: {len(pcd.points)} pts")

    # 1: Topology
    overlap, seeds, fpfh_cache = estimate_topology(pcds, cfg.topology_voxel, cfg.topology_eval_dist)
    root, order = plan_order(overlap, cfg.min_topology_fitness)
    print(f"\n   Root scan: {root} ({names[root]})")
    for src, tgt in order:
        print(f"     {src} -> {tgt}  (overlap={overlap[src, tgt]:.3f})")

    if cfg.dry_run:
        print("\nDry run, stopping here.")
        return

    # 2: Backbone
    ckpt_path = os.path.join(cfg.folder, "registration_checkpoint.json")
    poses, edges = register_backbone(pcds, overlap, seeds, root, order, cfg, ckpt_path, fpfh_cache)

    # 3: Loop closures
    loops = add_loop_closures(pcds, poses, edges, overlap, cfg)
    all_edges = edges + loops

    # 4: Optimize + merge
    print("\n[4/4] Global optimization and merge")
    pg, id_to_node = build_pose_graph(poses, all_edges)
    ids = sorted(poses)
    ref_node = id_to_node[root]
    optimize_dists = {max(cfg.icp_voxels) * cfg.corr_factor}
    if loops:
        optimize_dists.add(max(cfg.loop_voxels) * cfg.corr_factor)
    for d in optimize_dists:
        optimize(pg, d, ref_node)

    metrics = evaluate_edges(pcds, pg, id_to_node, cfg.eval_dist, cfg.merge_voxel)

    if cfg.min_scan_support >= 2:
        print(f"   Multi-scan consistency filter (min_support={cfg.min_scan_support}) ...")
        merged, n_removed = multiscan_consistency_filter(
            pcds, pg, id_to_node, ids, cfg.merge_voxel,
            radius=cfg.merge_voxel * 2.0, min_support=cfg.min_scan_support,
        )
        print(f"   Removed {n_removed} inconsistent points.")
    else:
        merged = merge(pcds, pg, id_to_node, ids, cfg.merge_voxel)

    # Save outputs
    out_cloud = os.path.join(cfg.folder, "reference_point_cloud.pcd")
    out_poses = os.path.join(cfg.folder, "optimized_poses.json")
    out_report = os.path.join(cfg.folder, "registration_report.json")

    o3d.io.write_point_cloud(out_cloud, merged)
    with open(out_poses, "w") as f:
        json.dump({str(k): pg.nodes[id_to_node[k]].pose.tolist() for k in ids}, f, indent=2)

    fit_vals = [m["fitness"] for m in metrics]
    rmse_vals = [m["rmse"] for m in metrics]
    report = {
        "scans": [{"index": i, "name": names[i], "points": len(pcds[i].points)}
                  for i in range(len(pcds))],
        "parameters": vars(cfg),
        "topology_matrix": overlap.tolist(),
        "registration_order": [{"source": s, "target": t} for s, t in order],
        "edges": all_edges,
        "optimized_metrics": metrics,
        "summary": {
            "num_scans": len(pcds),
            "num_backbone": sum(1 for e in all_edges if e["type"] == "backbone"),
            "num_loops": sum(1 for e in all_edges if e["type"] == "loop"),
            "mean_fitness": float(np.mean(fit_vals)) if fit_vals else 0,
            "min_fitness": float(np.min(fit_vals)) if fit_vals else 0,
            "mean_rmse_mm": float(np.mean(rmse_vals) * 1000) if rmse_vals else 0,
            "max_rmse_mm": float(np.max(rmse_vals) * 1000) if rmse_vals else 0,
            "output_points": len(merged.points),
        },
        "elapsed_s": time.time() - t0,
    }
    with open(out_report, "w") as f:
        json.dump(report, f, indent=2)

    s = report["summary"]
    print(f"\n{'='*55}")
    print(f"  Reference cloud:  {out_cloud}")
    print(f"  Poses:            {out_poses}")
    print(f"  Report:           {out_report}")
    print(f"  Scans registered: {s['num_scans']}")
    print(f"  Backbone edges:   {s['num_backbone']}")
    print(f"  Loop closures:    {s['num_loops']}")
    print(f"  Output points:    {s['output_points']}")
    print(f"  Mean fitness:     {s['mean_fitness']:.3f}")
    print(f"  Mean RMSE:        {s['mean_rmse_mm']:.1f} mm")
    print(f"  Time:             {report['elapsed_s']:.0f} s")
    print(f"{'='*55}")

    show_geometries([merged], "Reference Point Cloud", VIEW_POINT_SIZE)


if __name__ == "__main__":
    main()
