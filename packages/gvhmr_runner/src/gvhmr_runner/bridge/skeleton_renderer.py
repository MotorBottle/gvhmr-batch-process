from __future__ import annotations

import cv2
import numpy as np
import torch


SMPL_SKELETON = [
    [0, 1],
    [0, 2],
    [0, 3],
    [3, 6],
    [6, 9],
    [9, 12],
    [12, 15],
    [9, 13],
    [13, 16],
    [16, 18],
    [18, 20],
    [20, 22],
    [9, 14],
    [14, 17],
    [17, 19],
    [19, 21],
    [21, 23],
    [1, 4],
    [4, 7],
    [7, 10],
    [2, 5],
    [5, 8],
    [8, 11],
]

SMPL_JOINT_NAMES = [
    "Pelvis",
    "Left_Hip",
    "Right_Hip",
    "Spine1",
    "Left_Knee",
    "Right_Knee",
    "Spine2",
    "Left_Ankle",
    "Right_Ankle",
    "Spine3",
    "Left_Foot",
    "Right_Foot",
    "Neck",
    "Left_Collar",
    "Right_Collar",
    "Head",
    "Left_Shoulder",
    "Right_Shoulder",
    "Left_Elbow",
    "Right_Elbow",
    "Left_Wrist",
    "Right_Wrist",
    "Left_Hand",
    "Right_Hand",
]


def project_joints_to_2d(joints_3d: torch.Tensor, K: torch.Tensor) -> torch.Tensor:
    if joints_3d.dim() == 2:
        projected = torch.matmul(K, joints_3d.T)
        joints_2d = projected[:2] / projected[2:3]
        return joints_2d.T

    projected = torch.matmul(K, joints_3d.transpose(1, 2))
    joints_2d = projected[:, :2] / projected[:, 2:3]
    return joints_2d.transpose(1, 2)


def draw_smpl_skeleton_on_image(
    img: np.ndarray,
    joints_2d: np.ndarray | torch.Tensor,
    *,
    draw_joints: bool = True,
    draw_bones: bool = True,
    joint_color: tuple[int, int, int] = (0, 255, 0),
    bone_color: tuple[int, int, int] = (0, 200, 0),
    joint_radius: int = 5,
    bone_thickness: int = 3,
) -> np.ndarray:
    img_out = img.copy()

    if isinstance(joints_2d, torch.Tensor):
        joints_2d = joints_2d.cpu().numpy()

    if draw_bones:
        for j1_idx, j2_idx in SMPL_SKELETON:
            j1 = joints_2d[j1_idx].astype(int)
            j2 = joints_2d[j2_idx].astype(int)
            h, w = img.shape[:2]
            if 0 <= j1[0] < w and 0 <= j1[1] < h and 0 <= j2[0] < w and 0 <= j2[1] < h:
                cv2.line(img_out, tuple(j1), tuple(j2), bone_color, bone_thickness)

    if draw_joints:
        for joint in joints_2d:
            j = joint.astype(int)
            h, w = img.shape[:2]
            if 0 <= j[0] < w and 0 <= j[1] < h:
                cv2.circle(img_out, tuple(j), joint_radius, joint_color, -1)

    return img_out
