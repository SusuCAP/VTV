# Modal Analysis Runtime

`modal_apps/analysis.py` 定义 `vtv-analysis` App，并暴露两个仅通过 Modal SDK 调用的函数：

- `health`：最小部署与身份验证探针；
- `execute_analysis_stage`：接收 JSON StageJob，执行 S3 输入物化、Analysis Worker、输出完整性
  校验和不可变 S3 回传，再返回强类型 StageResult。

镜像固定 Python 3.12，安装 FFmpeg、Demucs 4.1.0、faster-whisper 1.2.1、pyannote.audio 4.0.7 和其他锁定
Python 依赖，并仅复制运行所需 workspace 源码。分析函数使用 L4、4 CPU、16 GiB 内存、
1 小时超时和两次平台重试。业务幂等仍由
Stage Attempt/数据库条件提交保证，Modal 调用 ID 不作为业务 ID。

本地编排器新增 `--worker-mode modal`。基础媒体阶段仍在本地路由，Stem 与三个分析阶段通过
`ModalStageExecutor` 调用部署后的函数；返回的 stage/attempt identity 不匹配时拒绝结果，
平台连接异常转换为可重试的标准失败。

## 密钥边界

Modal token 只保存在用户级 CLI profile。S3 与远程模型凭据只能放入 Modal Secret，并在部署
前通过 `VTV_MODAL_SECRET_NAME` 选择；没有 Secret 时仍可部署和调用 health，但遇到 S3 输入会
在执行前明确拒绝。StageJob、Registry、Git 和日志均不保存这些密钥。

## 部署

```bash
VTV_MODAL_SECRET_NAME=vtv-runtime .venv/bin/modal deploy modal_apps/analysis.py
.venv/bin/modal run modal_apps/analysis.py::health
```

2026-07-22 首次测试部署在连接 `https://api.modal.com` 时收到 HTTP 503；官方状态页显示服务
正常，但本机直连和代理路径均返回 Envoy 503。因此代码、配置和本地合同已验证，云端部署与
health 调用待网络路径恢复后重试。
