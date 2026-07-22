# Worker 对象存储物化

具体 Worker 保持纯本地文件处理边界，`StageRouter` 负责对象存储 I/O：

1. 对每个 `s3://` 输入流式下载到 Stage 隔离目录的临时文件；
2. 下载完成后同时验证数据库声明的字节数与 SHA-256，再原子替换目标文件；
3. 以 `file://` AssetRef 调用 Media/Analysis Worker；
4. 上传前重新计算 Worker 输出的大小与 SHA-256，并与 Stage Result 声明对比；
5. 以 `project/episode/stage/variant/hash/filename` 不可变 key 上传，返回新的 S3 AssetRef。

S3 写入携带 SHA-256 checksum、`immutable=true` metadata 和 `If-None-Match: *`，防止同一
业务 key 被静默覆盖。任何完整性错误都转换为 Stage 失败，错误文件不会登记为 Media Asset。

本地编排器从 `VTV_S3_ENDPOINT`、region、access key、secret key 和 bucket 环境变量创建
与控制 API 一致的 S3/MinIO 客户端。没有配置对象存储时仍可处理纯 file URI；遇到 S3 URI
会明确失败，而不是把它误当作本地路径。
