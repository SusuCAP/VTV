# Rights Release 执行门禁

`rights_releases` 是人物替换、声音克隆、口型重建、翻译和发行等生产操作的数据库权威授权记录。
调用方提交的布尔值不能代替此记录；控制平面必须在生成 StageJob 前读取当前 release 并执行范围
检查。

## 不可变版本

授权按 `project + subject_type + subject_id + version` 唯一。同一主体只允许一条未撤销的当前
release。创建新版本必须显式引用当前 `supersedes_release_id`，事务会先把旧版本标记为
`REVOKED/SUPERSEDED`，再建立新版本，避免两个授权同时生效。

每条 release 保存：

- `REAL_PERSON / VIRTUAL_CHARACTER / SOURCE_MEDIA / VOICE` 主体；
- 明确的 allowed operations、markets、languages 和研究/商业范围；
- `valid_from / expires_at / revoked_at` 与 CAS `state_version`；
- 未成年人监护同意标记；
- 来源资产 ID、受限 evidence URI 和 evidence SHA-256；
- 创建人、撤销人、撤销原因及完整时间戳。

## 实时判定

`evaluate_rights_release` 一次返回全部失败原因，包括撤销、尚未生效、过期、操作/市场/语言不在
范围及商业使用不允许。控制面 API 提供 create/list/check/revoke，所有查询通过 Project 关联强制
workspace 隔离，撤销使用 `expected_state_version` 防止并发覆盖。

TTS Stage 的 `VoiceRightsSnapshot` 和 `TTS_CANDIDATES` 产物同时记录 rights release ID 与
state version。生产 DAG 接入时，调度器须在派发前重新检查权威 release；授权在运行中撤销时，
最终条件提交必须拒绝旧 state version 的结果。
