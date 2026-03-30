# Test Workspace

- 把待测视频放进 `test/uploads/`
- 运行 `python3 test/run_batch_test.py`
- 结果会写到 `test/results/<timestamp>__<batch_id>/`
- 每个 job 的结果目录会带上原始文件名
- batch 根目录下会生成 `job_index.json` 和 `job_index.csv`
- `job_index.csv` 里可直接按 `result_dir_name` 或 `job_id` 反查原始输入文件

常用示例：

```bash
python3 test/run_batch_test.py --video-render --video-type skeleton_only
python3 test/run_batch_test.py --video-render --video-type all
python3 test/run_batch_test.py --no-static-camera --use-dpvo
python3 test/run_batch_test.py --no-static-camera --use-dpvo --video-render --video-type mesh_incam,mesh_global
python3 test/run_batch_test.py --no-download-artifacts
```

批量把一个已下载 batch 中所有成功的 `hmr4d_results.pt` 转成 `SMPL-X body-only` 的 `.npz`：

```bash
python3 test/export_batch_npz.py test/results/<timestamp>__<batch_id>
```

默认会在该 batch 根目录下生成：

```text
ouput/
  README.md
  index.json
  index.csv
  <job_id>__<video_stem>.npz
```

导出的 `.npz` 约定：

- `model_type = "smplx"`
- `pose_rep = "body_only"`
- `coordinate_system = "world_y_up"`
- `betas` 是序列级 `10D`
- `root_orient` 是 `(F, 3)`
- `pose_body` 是 `(F, 63)`
- `poses` 是 `(F, 22, 3)`，其中 `poses[:, 0, :] == root_orient`
- `trans` 是 `(F, 3)`
