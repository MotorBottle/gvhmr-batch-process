from __future__ import annotations

import argparse
from pathlib import Path

from gvhmr_runner.bridge.render_skeleton import (
    compute_joints_once,
    render_skeleton_incam,
    render_skeleton_only,
    save_joints_json,
)
from gvhmr_runner.gvhmr_env import body_model_asset_path, prepare_gvhmr_runtime

prepare_gvhmr_runtime(change_cwd=True)

import hydra
import torch
from einops import einsum
from hydra import compose, initialize_config_module
from pytorch3d.transforms import quaternion_to_matrix
from tqdm import tqdm

from hmr4d.configs import register_store_gvhmr
from hmr4d.model.gvhmr.gvhmr_pl_demo import DemoPL
from hmr4d.utils.geo.hmr_cam import (
    convert_K_to_K4,
    create_camera_sensor,
    estimate_K,
    get_bbx_xys_from_xyxy,
)
from hmr4d.utils.geo_transform import apply_T_on_points, compute_T_ayfz2ay, compute_cam_angvel
from hmr4d.utils.net_utils import detach_to_cpu, to_cuda
from hmr4d.utils.preproc import Extractor, SimpleVO, Tracker, VitPoseExtractor
from hmr4d.utils.pylogger import Log
from hmr4d.utils.smplx_utils import make_smplx
from hmr4d.utils.video_io_utils import (
    get_video_lwh,
    get_video_reader,
    get_writer,
    merge_videos_horizontal,
    read_video_np,
    save_video,
)
from hmr4d.utils.vis.cv2_utils import draw_bbx_xyxy_on_image_batch, draw_coco17_skeleton_batch
from hmr4d.utils.vis.renderer import Renderer, get_global_cameras_static, get_ground_params_from_points


CRF = 23


def parse_args_to_cfg():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=str, default="inputs/demo/dance_3.mp4")
    parser.add_argument("--output_root", type=str, default=None, help="by default to outputs/demo")
    parser.add_argument("-s", "--static_cam", action="store_true", help="If true, skip DPVO")
    parser.add_argument("--use_dpvo", action="store_true", help="If true, use DPVO. By default not using DPVO.")
    parser.add_argument(
        "--f_mm",
        type=int,
        default=None,
        help="Focal length of fullframe camera in mm. Leave it as None to use default values.",
    )
    parser.add_argument("--verbose", action="store_true", help="If true, draw intermediate results")
    parser.add_argument(
        "--video_render",
        type=lambda value: value.lower() == "true",
        default=True,
        help="Enable or disable video rendering. If false, only generates PT files.",
    )
    parser.add_argument(
        "--video_type",
        type=str,
        default="all",
        help="Comma-separated list: mesh_incam,mesh_global,mesh_comparison,skeleton_incam,skeleton_only or 'all'.",
    )
    args = parser.parse_args()

    if args.video_render:
        enabled_videos = (
            {"mesh_incam", "mesh_global", "mesh_comparison", "skeleton_incam", "skeleton_only"}
            if args.video_type.lower() == "all"
            else {video_type.strip() for video_type in args.video_type.split(",")}
        )
    else:
        enabled_videos = set()

    video_path = Path(args.video)
    assert video_path.exists(), f"Video not found at {video_path}"
    length, width, height = get_video_lwh(video_path)
    Log.info(f"[Input]: {video_path}")
    Log.info(f"(L, W, H) = ({length}, {width}, {height})")

    with initialize_config_module(version_base="1.3", config_module="hmr4d.configs"):
        overrides = [
            f"video_name={video_path.stem}",
            f"static_cam={args.static_cam}",
            f"verbose={args.verbose}",
            f"use_dpvo={args.use_dpvo}",
        ]
        if args.f_mm is not None:
            overrides.append(f"f_mm={args.f_mm}")
        if args.output_root is not None:
            overrides.append(f"output_root={args.output_root}")
        register_store_gvhmr()
        cfg = compose(config_name="demo", overrides=overrides)

    Log.info(f"[Output Dir]: {cfg.output_dir}")
    Log.info(f"[Video Output Control] Enabled: {enabled_videos if enabled_videos else 'None (PT files only)'}")
    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.preprocess_dir).mkdir(parents=True, exist_ok=True)

    Log.info(f"[Copy Video] {video_path} -> {cfg.video_path}")
    if not Path(cfg.video_path).exists() or get_video_lwh(video_path)[0] != get_video_lwh(cfg.video_path)[0]:
        reader = get_video_reader(video_path)
        writer = get_writer(cfg.video_path, fps=30, crf=CRF)
        for img in tqdm(reader, total=get_video_lwh(video_path)[0], desc="Copy"):
            writer.write_frame(img)
        writer.close()
        reader.close()

    return cfg, enabled_videos


@torch.no_grad()
def run_preprocess(cfg):
    Log.info("[Preprocess] Start!")
    tic = Log.time()
    video_path = cfg.video_path
    paths = cfg.paths
    static_cam = cfg.static_cam
    verbose = cfg.verbose

    if not Path(paths.bbx).exists():
        tracker = Tracker()
        bbx_xyxy = tracker.get_one_track(video_path).float()
        bbx_xys = get_bbx_xys_from_xyxy(bbx_xyxy, base_enlarge=1.2).float()
        torch.save({"bbx_xyxy": bbx_xyxy, "bbx_xys": bbx_xys}, paths.bbx)
        del tracker
    else:
        bbx_xys = torch.load(paths.bbx)["bbx_xys"]
        Log.info(f"[Preprocess] bbx (xyxy, xys) from {paths.bbx}")
    if verbose:
        video = read_video_np(video_path)
        bbx_xyxy = torch.load(paths.bbx)["bbx_xyxy"]
        save_video(draw_bbx_xyxy_on_image_batch(bbx_xyxy, video), cfg.paths.bbx_xyxy_video_overlay)

    if not Path(paths.vitpose).exists():
        vitpose_extractor = VitPoseExtractor()
        vitpose = vitpose_extractor.extract(video_path, bbx_xys)
        torch.save(vitpose, paths.vitpose)
        del vitpose_extractor
    else:
        vitpose = torch.load(paths.vitpose)
        Log.info(f"[Preprocess] vitpose from {paths.vitpose}")
    if verbose:
        video = read_video_np(video_path)
        save_video(draw_coco17_skeleton_batch(video, vitpose, 0.5), paths.vitpose_video_overlay)

    if not Path(paths.vit_features).exists():
        extractor = Extractor()
        vit_features = extractor.extract_video_features(video_path, bbx_xys)
        torch.save(vit_features, paths.vit_features)
        del extractor
    else:
        Log.info(f"[Preprocess] vit_features from {paths.vit_features}")

    if not static_cam:
        if not Path(paths.slam).exists():
            if not cfg.use_dpvo:
                simple_vo = SimpleVO(cfg.video_path, scale=0.5, step=8, method="sift", f_mm=cfg.f_mm)
                torch.save(simple_vo.compute(), paths.slam)
            else:
                from hmr4d.utils.preproc.slam import SLAMModel

                length, width, height = get_video_lwh(cfg.video_path)
                intrinsics = convert_K_to_K4(estimate_K(width, height))
                slam = SLAMModel(video_path, width, height, intrinsics, buffer=4000, resize=0.5)
                bar = tqdm(total=length, desc="DPVO")
                while True:
                    ret = slam.track()
                    if ret:
                        bar.update()
                    else:
                        break
                torch.save(slam.process(), paths.slam)
        else:
            Log.info(f"[Preprocess] slam results from {paths.slam}")

    Log.info(f"[Preprocess] End. Time elapsed: {Log.time() - tic:.2f}s")


def load_data_dict(cfg):
    paths = cfg.paths
    length, width, height = get_video_lwh(cfg.video_path)
    if cfg.static_cam:
        R_w2c = torch.eye(3).repeat(length, 1, 1)
    else:
        traj = torch.load(cfg.paths.slam)
        if cfg.use_dpvo:
            traj_quat = torch.from_numpy(traj[:, [6, 3, 4, 5]])
            R_w2c = quaternion_to_matrix(traj_quat).mT
        else:
            R_w2c = torch.from_numpy(traj[:, :3, :3])
    K_fullimg = (
        create_camera_sensor(width, height, cfg.f_mm)[2].repeat(length, 1, 1)
        if cfg.f_mm is not None
        else estimate_K(width, height).repeat(length, 1, 1)
    )

    return {
        "length": torch.tensor(length),
        "bbx_xys": torch.load(paths.bbx)["bbx_xys"],
        "kp2d": torch.load(paths.vitpose),
        "K_fullimg": K_fullimg,
        "cam_angvel": compute_cam_angvel(R_w2c),
        "f_imgseq": torch.load(paths.vit_features),
    }


def render_incam(cfg):
    incam_video_path = Path(cfg.paths.incam_video)
    if incam_video_path.exists():
        Log.info(f"[Render Incam] Video already exists at {incam_video_path}")
        return

    pred = torch.load(cfg.paths.hmr4d_results)
    smplx = make_smplx("supermotion").cuda()
    smplx2smpl = torch.load(body_model_asset_path("smplx2smpl_sparse.pt")).cuda()
    faces_smpl = make_smplx("smpl").faces

    smplx_out = smplx(**to_cuda(pred["smpl_params_incam"]))
    pred_c_verts = torch.stack([torch.matmul(smplx2smpl, verts) for verts in smplx_out.vertices])

    video_path = cfg.video_path
    length, width, height = get_video_lwh(video_path)
    K = pred["K_fullimg"][0]
    renderer = Renderer(width, height, device="cuda", faces=faces_smpl, K=K)
    reader = get_video_reader(video_path)
    writer = get_writer(incam_video_path, fps=30, crf=CRF)
    num_frames = min(length, len(pred_c_verts))

    for frame_idx, img_raw in tqdm(enumerate(reader), total=num_frames, desc="Rendering Incam"):
        if frame_idx >= num_frames:
            break
        writer.write_frame(renderer.render_mesh(pred_c_verts[frame_idx].cuda(), img_raw, [0.8, 0.8, 0.8]))

    writer.close()
    reader.close()


def render_global(cfg):
    global_video_path = Path(cfg.paths.global_video)
    if global_video_path.exists():
        Log.info(f"[Render Global] Video already exists at {global_video_path}")
        return

    pred = torch.load(cfg.paths.hmr4d_results)
    smplx = make_smplx("supermotion").cuda()
    smplx2smpl = torch.load(body_model_asset_path("smplx2smpl_sparse.pt")).cuda()
    faces_smpl = make_smplx("smpl").faces
    J_regressor = torch.load(body_model_asset_path("smpl_neutral_J_regressor.pt")).cuda()

    smplx_out = smplx(**to_cuda(pred["smpl_params_global"]))
    pred_ay_verts = torch.stack([torch.matmul(smplx2smpl, verts) for verts in smplx_out.vertices])

    def move_to_start_point_face_z(verts):
        verts = verts.clone()
        offset = einsum(J_regressor, verts[0], "j v, v i -> j i")[0]
        offset[1] = verts[:, :, [1]].min()
        verts = verts - offset
        T_ay2ayfz = compute_T_ayfz2ay(einsum(J_regressor, verts[[0]], "j v, l v i -> l j i"), inverse=True)
        return apply_T_on_points(verts, T_ay2ayfz)

    verts_glob = move_to_start_point_face_z(pred_ay_verts)
    joints_glob = einsum(J_regressor, verts_glob, "j v, l v i -> l j i")
    global_R, global_T, global_lights = get_global_cameras_static(
        verts_glob.cpu(),
        beta=2.0,
        cam_height_degree=20,
        target_center_height=1.0,
    )

    video_path = cfg.video_path
    length, width, height = get_video_lwh(video_path)
    _, _, K = create_camera_sensor(width, height, 24)
    renderer = Renderer(width, height, device="cuda", faces=faces_smpl, K=K)
    scale, cx, cz = get_ground_params_from_points(joints_glob[:, 0], verts_glob)
    renderer.set_ground(scale * 1.5, cx, cz)
    color = torch.ones(3).float().cuda() * 0.8

    render_length = min(length, len(verts_glob))
    writer = get_writer(global_video_path, fps=30, crf=CRF)
    for frame_idx in tqdm(range(render_length), desc="Rendering Global"):
        cameras = renderer.create_camera(global_R[frame_idx], global_T[frame_idx])
        img = renderer.render_with_ground(verts_glob[[frame_idx]], color[None], cameras, global_lights)
        writer.write_frame(img)
    writer.close()


def main():
    cfg, enabled_videos = parse_args_to_cfg()
    paths = cfg.paths

    Log.info(f"[GPU]: {torch.cuda.get_device_name()}")
    Log.info(f'[GPU]: {torch.cuda.get_device_properties("cuda")}')

    run_preprocess(cfg)
    data = load_data_dict(cfg)

    if not Path(paths.hmr4d_results).exists():
        Log.info("[HMR4D] Predicting")
        model: DemoPL = hydra.utils.instantiate(cfg.model, _recursive_=False)
        model.load_pretrained_model(cfg.ckpt_path)
        model = model.eval().cuda()
        tic = Log.sync_time()
        pred = model.predict(data, static_cam=cfg.static_cam)
        pred = detach_to_cpu(pred)
        data_time = data["length"] / 30
        Log.info(f"[HMR4D] Elapsed: {Log.sync_time() - tic:.2f}s for data-length={data_time:.1f}s")
        torch.save(pred, paths.hmr4d_results)

    if "mesh_incam" in enabled_videos:
        Log.info("[Render] Mesh incam")
        render_incam(cfg)
        old_path = Path(cfg.paths.incam_video)
        new_path = Path(cfg.output_dir) / "mesh_incam.mp4"
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)
            Log.info(f"  Renamed: {old_path.name} -> {new_path.name}")

    if "mesh_global" in enabled_videos:
        Log.info("[Render] Mesh global")
        render_global(cfg)
        old_path = Path(cfg.paths.global_video)
        new_path = Path(cfg.output_dir) / "mesh_global.mp4"
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)
            Log.info(f"  Renamed: {old_path.name} -> {new_path.name}")

    if "mesh_comparison" in enabled_videos:
        mesh_incam_path = Path(cfg.output_dir) / "mesh_incam.mp4"
        mesh_global_path = Path(cfg.output_dir) / "mesh_global.mp4"
        if mesh_incam_path.exists() and mesh_global_path.exists():
            Log.info("[Merge Videos] Creating mesh comparison")
            comparison_path = Path(cfg.output_dir) / "mesh_comparison.mp4"
            if not comparison_path.exists():
                merge_videos_horizontal([str(mesh_incam_path), str(mesh_global_path)], str(comparison_path))
                Log.info(f"  Created: {comparison_path.name}")
        else:
            Log.warn("[Merge Videos] Skipped - need both mesh_incam and mesh_global")

    if "skeleton_incam" in enabled_videos or "skeleton_only" in enabled_videos:
        Log.info("[Precompute] Joint positions (once for all skeleton rendering)")
        precomputed = compute_joints_once(cfg)

        if "skeleton_incam" in enabled_videos:
            Log.info("[Render] Skeleton incam (using precomputed data)")
            render_skeleton_incam(cfg, Path(cfg.output_dir) / "skeleton_incam.mp4", precomputed)

        if "skeleton_only" in enabled_videos:
            Log.info("[Render] Skeleton only (using precomputed data)")
            render_skeleton_only(cfg, Path(cfg.output_dir) / "skeleton_only.mp4", precomputed)

        Log.info("[Save] Joint positions JSON (using precomputed data)")
        save_joints_json(cfg, Path(cfg.output_dir) / "joints.json", precomputed)

    old_input = Path(cfg.paths.input_video) if hasattr(cfg.paths, "input_video") else Path(cfg.video_path)
    new_input = Path(cfg.output_dir) / "input.mp4"
    if old_input.exists() and old_input != new_input and not new_input.exists():
        try:
            old_input.rename(new_input)
            Log.info(f"  Renamed input: {old_input.name} -> input.mp4")
        except OSError:
            pass

    Log.info("[Complete] Processing finished")
    if enabled_videos:
        Log.info(f"  Generated videos: {', '.join(sorted(enabled_videos))}")
    else:
        Log.info("  No videos generated (PT files only)")


if __name__ == "__main__":
    main()
