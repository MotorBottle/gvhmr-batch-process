# Test Workspace

- 把待测视频放进 `test/uploads/`
- 运行 `python3 test/run_batch_test.py`
- 结果会写到 `test/results/<batch_id>/`

常用示例：

```bash
python3 test/run_batch_test.py --video-render --video-type skeleton_only
python3 test/run_batch_test.py --video-render --video-type all
python3 test/run_batch_test.py --no-download-artifacts
```
