from __future__ import annotations

import json
from pathlib import Path

from gvhmr_runner.bridge.skeleton_renderer import (
    SMPL_JOINT_NAMES,
    SMPL_SKELETON,
    draw_smpl_skeleton_on_image,
    project_joints_to_2d,
)
from gvhmr_runner.gvhmr_env import body_model_asset_path, prepare_gvhmr_runtime

prepare_gvhmr_runtime()

import numpy as np
import torch
from einops import einsum
from tqdm import tqdm

from hmr4d.utils.net_utils import to_cuda
from hmr4d.utils.smplx_utils import make_smplx
from hmr4d.utils.video_io_utils import get_video_lwh, get_video_reader, get_writer


CRF = 23


def compute_joints_once(cfg):
    print("[Precompute] Loading SMPL models (once)...")
    smplx = make_smplx("supermotion").cuda()
    smplx2smpl = torch.load(body_model_asset_path("smplx2smpl_sparse.pt")).cuda()
    J_regressor = torch.load(body_model_asset_path("smpl_neutral_J_regressor.pt")).cuda()

    print("[Precompute] Loading prediction results (once)...")
    pred = torch.load(cfg.paths.hmr4d_results)

    print("[Precompute] Computing SMPL joints (once)...")
    smplx_out = smplx(**to_cuda(pred["smpl_params_incam"]))
    pred_c_verts = torch.stack([torch.matmul(smplx2smpl, verts) for verts in smplx_out.vertices])
    joints_incam = einsum(J_regressor, pred_c_verts, "j v, l v i -> l j i")

    smplx_out_global = smplx(**to_cuda(pred["smpl_params_global"]))
    pred_g_verts = torch.stack([torch.matmul(smplx2smpl, verts) for verts in smplx_out_global.vertices])
    joints_global = einsum(J_regressor, pred_g_verts, "j v, l v i -> l j i")

    K = pred["K_fullimg"][0].cuda()
    print("[Precompute] Projecting joints to 2D (batch operation)...")
    joints_2d = project_joints_to_2d(joints_incam, K)

    print(f"[Precompute] Complete. Precomputed {len(joints_incam)} frames with {joints_incam.shape[1]} joints")
    return {
        "joints_incam": joints_incam,
        "joints_global": joints_global,
        "joints_2d": joints_2d,
        "K": K,
        "pred": pred,
    }


def render_skeleton_incam(cfg, output_skeleton_path, precomputed=None):
    output_skeleton_path = Path(output_skeleton_path)
    if output_skeleton_path.exists():
        print(f"[Render Skeleton Incam] Video already exists at {output_skeleton_path}")
        return

    if precomputed is not None:
        joints_2d = precomputed["joints_2d"]
    else:
        print("[Render Skeleton Incam] Computing joints (no precomputed data)...")
        pred = torch.load(cfg.paths.hmr4d_results)
        smplx = make_smplx("supermotion").cuda()
        smplx2smpl = torch.load(body_model_asset_path("smplx2smpl_sparse.pt")).cuda()
        J_regressor = torch.load(body_model_asset_path("smpl_neutral_J_regressor.pt")).cuda()

        smplx_out = smplx(**to_cuda(pred["smpl_params_incam"]))
        pred_c_verts = torch.stack([torch.matmul(smplx2smpl, verts) for verts in smplx_out.vertices])
        joints_incam = einsum(J_regressor, pred_c_verts, "j v, l v i -> l j i")
        joints_2d = project_joints_to_2d(joints_incam, pred["K_fullimg"][0].cuda())

    video_path = cfg.video_path
    length, _, _ = get_video_lwh(video_path)
    reader = get_video_reader(video_path)
    writer = get_writer(str(output_skeleton_path), fps=30, crf=CRF)
    num_frames = min(length, len(joints_2d))

    for frame_idx, img_raw in tqdm(enumerate(reader), total=num_frames, desc="Rendering Skeleton Incam"):
        if frame_idx >= num_frames:
            break
        writer.write_frame(
            draw_smpl_skeleton_on_image(
                img_raw,
                joints_2d[frame_idx],
                joint_color=(0, 255, 0),
                bone_color=(0, 200, 0),
                joint_radius=6,
                bone_thickness=3,
            )
        )

    writer.close()
    reader.close()
    print(f"[Render Skeleton Incam] Saved to {output_skeleton_path}")


def render_skeleton_only(cfg, output_skeleton_path, precomputed=None):
    output_skeleton_path = Path(output_skeleton_path)
    if output_skeleton_path.exists():
        print(f"[Render Skeleton Only] Video already exists at {output_skeleton_path}")
        return

    if precomputed is not None:
        joints_2d = precomputed["joints_2d"]
    else:
        print("[Render Skeleton Only] Computing joints (no precomputed data)...")
        pred = torch.load(cfg.paths.hmr4d_results)
        smplx = make_smplx("supermotion").cuda()
        smplx2smpl = torch.load(body_model_asset_path("smplx2smpl_sparse.pt")).cuda()
        J_regressor = torch.load(body_model_asset_path("smpl_neutral_J_regressor.pt")).cuda()

        smplx_out = smplx(**to_cuda(pred["smpl_params_incam"]))
        pred_c_verts = torch.stack([torch.matmul(smplx2smpl, verts) for verts in smplx_out.vertices])
        joints_incam = einsum(J_regressor, pred_c_verts, "j v, l v i -> l j i")
        joints_2d = project_joints_to_2d(joints_incam, pred["K_fullimg"][0].cuda())

    video_path = cfg.video_path
    length, width, height = get_video_lwh(video_path)
    writer = get_writer(str(output_skeleton_path), fps=30, crf=CRF)
    num_frames = min(length, len(joints_2d))

    for frame_idx in tqdm(range(num_frames), desc="Rendering Skeleton Only"):
        black_bg = np.zeros((height, width, 3), dtype=np.uint8)
        writer.write_frame(
            draw_smpl_skeleton_on_image(
                black_bg,
                joints_2d[frame_idx],
                joint_color=(0, 255, 0),
                bone_color=(0, 200, 0),
                joint_radius=8,
                bone_thickness=4,
            )
        )

    writer.close()
    print(f"[Render Skeleton Only] Saved to {output_skeleton_path}")


def save_joints_json(cfg, output_json_path, precomputed=None):
    output_json_path = Path(output_json_path)
    if output_json_path.exists():
        print(f"[Save Joints JSON] File already exists at {output_json_path}")
        return

    if precomputed is not None:
        joints_incam = precomputed["joints_incam"]
        joints_global = precomputed["joints_global"]
        pred = precomputed["pred"]
    else:
        print("[Save Joints JSON] Computing joints (no precomputed data)...")
        pred = torch.load(cfg.paths.hmr4d_results)
        smplx = make_smplx("supermotion").cuda()
        smplx2smpl = torch.load(body_model_asset_path("smplx2smpl_sparse.pt")).cuda()
        J_regressor = torch.load(body_model_asset_path("smpl_neutral_J_regressor.pt")).cuda()

        smplx_out = smplx(**to_cuda(pred["smpl_params_incam"]))
        pred_c_verts = torch.stack([torch.matmul(smplx2smpl, verts) for verts in smplx_out.vertices])
        joints_incam = einsum(J_regressor, pred_c_verts, "j v, l v i -> l j i")

        smplx_out_global = smplx(**to_cuda(pred["smpl_params_global"]))
        pred_g_verts = torch.stack([torch.matmul(smplx2smpl, verts) for verts in smplx_out_global.vertices])
        joints_global = einsum(J_regressor, pred_g_verts, "j v, l v i -> l j i")

    data = {
        "num_frames": int(joints_incam.shape[0]),
        "num_joints": 24,
        "joint_names": SMPL_JOINT_NAMES,
        "skeleton_connections": SMPL_SKELETON,
        "fps": 30,
        "joints_camera_space": joints_incam.cpu().numpy().tolist(),
        "joints_global_space": joints_global.cpu().numpy().tolist(),
        "camera_intrinsics": pred["K_fullimg"][0].cpu().numpy().tolist(),
    }

    output_json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"[Save Joints JSON] Saved to {output_json_path}")


if __name__ == "__main__":
    print("Skeleton renderer utility loaded")
