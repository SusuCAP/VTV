# Tauri 本地媒体 Agent

Mac 控制端通过 Rust 命令承担大文件接入，不把视频内容交给 React 或控制 API 代理。

## 处理流程

1. 使用系统文件选择器选择 MP4/MOV/MKV/WebM。
2. `ffprobe` 读取容器、视频流、音频流、时长、编码、帧率和声道信息；无可读流时拒绝上传。
3. 使用 4 MiB 缓冲区流式计算完整文件 SHA-256，不把完整视频读入内存。
4. 调用 multipart init；服务端按项目 + SHA-256 复用未完成会话。
5. 按服务端 32–128 MiB part size 顺序读取文件；每个分片计算 SHA-256、上传到预签名 URL，并把 ETag/大小/checksum 写入数据库 checkpoint。
6. 重启或中断后重新选择同一文件，客户端跳过服务端已确认且大小一致的分片。
7. 全部分片完成后提交独立文件 SHA-256，服务端创建 Episode、Media Asset 和 ingest DAG。

## 安全边界

- 文件路径只作为 `Command::arg` 传给 `ffprobe`，不经 shell 拼接。
- S3 凭据不进入客户端；客户端只接收短期 part URL。
- ETag 只用于 multipart complete，不充当内容哈希。
- 文件 SHA-256、part SHA-256、对象大小和 checkpoint 清单分别校验。
- Tauri capability 仅开放默认核心权限和文件选择。

浏览器开发模式不具有本地 Agent，点击上传时会明确报错；项目查询和分析提交仍可独立联调。
