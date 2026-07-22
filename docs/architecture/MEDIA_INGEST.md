# 媒体接入与对象存储

## 上传边界

控制 API 只创建 multipart 会话、签发分片 URL 和提交元数据，不代理视频字节。Mac 客户端必须在上传前运行 `ffprobe`，并计算完整文件的独立 SHA-256。

1. `POST /v1/uploads/multipart-init` 创建不可变对象 key、数据库 `upload_session` 和 S3 provider upload ID。
2. 客户端并发上传 32–128 MiB 分片；ETag 只用于 multipart complete，不作为文件哈希。
3. `POST /v1/uploads/{id}/multipart-complete` 校验连续分片、总大小和独立 SHA-256，再调用对象存储完成操作。
4. 数据库事务创建 `media_asset`、`episode`、`EPISODE_INGEST` job、READY stage 和 Outbox 事件。
5. Worker 后续验证容器、编码、时长、帧率、音轨及对象完整性。

## 适配器

- `MemoryObjectStore`：本地和 API 契约测试。
- `S3ObjectStore`：S3、R2、MinIO 等兼容服务；生产只向客户端暴露短期预签名 URL。

所有对象使用不可变 key；“当前版本”由数据库引用表示，不覆盖旧对象。数据库提交失败后的已上传对象必须进入 orphan 清理流程。
