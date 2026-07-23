# Golden Dataset Fixtures

存放用于回归测试的固定参考素材。

## 目录结构

```
fixtures/
  shots/         # 参考视频片段（10-30s MP4，不提交到 git，存入 Git LFS 或手动下载）
  baselines/     # JSON 基线输出（转录、视觉分析等），提交到 git
```

## 添加新 Golden Shot

1. 将 MP4 文件放入 `shots/` 目录
2. 用真实模型生成基线：
   ```bash
   VTV_ASR_ADAPTER_MODE=local_models \
     uv run pytest tests/golden/test_asr_golden.py --update-golden -v
   ```
3. 提交 `baselines/*.json`（**不要**提交原始视频，加入 `.gitignore`）

## 运行 Golden 测试

```bash
# 跳过（无素材时自动跳过）
uv run pytest tests/golden/ -v

# 有 GPU + 真实模型
VTV_ASR_ADAPTER_MODE=local_models uv run pytest tests/golden/ -v
```

## .gitignore 说明

`shots/` 目录的原始视频文件已通过根目录 `.gitignore` 排除（`*.mp4` 媒体文件）。
基线 JSON 文件 `baselines/*.json` 需要提交。
