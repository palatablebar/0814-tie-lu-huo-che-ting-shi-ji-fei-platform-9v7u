# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据和复核信息的 JSON。

## 月末交接处置

`POST /api/runs/<id>/disposal` 对一批执行月末处置，返回 `retention-disposal/1` 结果。查询参数 `retention_days` 可覆盖默认保留期限（1 至 36500 天整数，默认 1825 天，自批次执行时刻起算）；JSON 体可带 `at` 指定决策时刻（ISO 8601，便于审计与复核演练）。处置依据不变时重试返回同一结果，不新增处置记录。

处置规则：批次未签发、存在未结争议或保留期未满时结论为 `RETAINED`，原凭据完整保留；三者均不成立时结论为 `PURGED`，敏感值（凭据说明列 `voucher[].note` 与复核意见 `review_note`）覆盖式清空且不留哈希，记录键、业务分组、分钟段与金额等结构化字段全部保留。

`GET /api/runs/<id>/disposal` 供页面读取，`GET /api/runs/<id>/disposal/download` 供下载，两端序列化同一份处置结果，后者带 `attachment` 与 `no-store`。尚无处置结果返回 404 `DISPOSAL_NOT_FOUND`。`GET /api/disposals` 列出最近 50 条当前处置结果。

## 争议登记

`POST /api/runs/<id>/disputes` 登记争议，JSON 体含 3 至 200 字 `note`；同批次已有未结争议返回 409 `DISPUTE_DUPLICATE`。`GET /api/runs/<id>/disputes` 列出该批争议。`POST /api/disputes/<dispute_id>/close` 关闭未结争议，未知争议返回 404。争议未结期间处置结论恒为 `RETAINED`。
