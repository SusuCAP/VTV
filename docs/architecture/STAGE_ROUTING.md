# Stage Worker 路由

本地编排器不再把所有 Stage 交给 Mock。`StageRouter` 按类型路由：

- `INGEST_VALIDATE`、`PROXY_GENERATE`、`SHOT_DETECT` → Media Worker；
- `AUDIO_STEM_SEPARATION` → Audio Worker；
- `ASR_ALIGN`、`VISION_ANALYSIS`、`PROJECT_SYNTHESIS` → Analysis Worker；
- 尚未进入真实实现的生产/QC Stage → 确定性 Mock Worker。

具体 Worker 的输出目录位于 `--work-root/<project>/<episode-or-project>/<stage-run>`，并以
`file://` URI 进入 Stage Result。任何 Worker 异常都会被转换为 `EXECUTION_FAILED`，保留
错误类、消息和 retryable 标志，让 Scheduler 按标准失败路径处理，而不是中止编排进程。

CLI 默认 `--worker-mode local`，`--worker-mode modal` 会把 Audio/Analysis stages 派发到 Modal，
也可显式使用 `--worker-mode mock` 做纯编排合同测试。
StageRouter 已支持 S3/MinIO 输入物化和输出回传；具体 Worker 仍只处理 file URI，因此模型
代码不持有对象存储凭据。真实 PostgreSQL + MinIO 全链仍需本机镜像可用后进行最终验收。
