# 铁路货车停时计费台规则登记

- 规模：中型

## 功能模块

| 模块 | 动作 | 接口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 样例采信 | 预览并定位坏行 | `POST /api/stages/intake` | `app/intake/service.py` | `tests/test_intake.py` |
| M2 停时归并 | 检查领域约束 | `POST /api/stages/prepare` | `app/modules/prepare.py` | `tests/test_prepare.py` |
| M3 阶梯计费 | 查看业务计算结果 | `POST /api/stages/calculate` | `app/modules/calculate.py` | `tests/test_calculate.py` |
| M4 账款复核 | 查看签收判定 | `POST /api/stages/policy` | `app/modules/policy.py` | `tests/test_policy.py` |
| M5 运行对账 | 对照输入、采信和隔离行 | `POST /api/stages/balance` | `app/modules/reconcile.py` | `tests/test_reconcile.py` |
| M6 批次复核 | 执行批次并签发或暂缓 | `POST /api/runs、PATCH /api/runs/<id>` | `app/review/service.py` | `tests/test_review.py` |
| M7 证据交付 | 下载复核清单 | `GET /api/runs/<id>/evidence` | `app/evidence/render.py` | `tests/test_evidence.py` |
| M8 月末处置 | 按签发、争议与保留期处置凭据 | `POST /api/runs/<id>/disposal` | `app/retention/service.py` | `tests/test_retention.py`、`tests/test_retention_http.py` |
| M9 争议登记 | 登记与关闭未结争议 | `POST /api/runs/<id>/disputes` | `app/retention/disputes.py` | `tests/test_retention.py`、`tests/test_retention_http.py` |

## 输入陷阱

| 编号 | 规则 | 处理 | 测试 |
|---|---|---|---|
| TRAP-02 | 去除 BOM | `app/intake/reader.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-03 | 按逻辑记录读取引号内换行 | `app/intake/reader.py` | `tests/test_intake.py::test_quoted_newline_is_one_logical_record` |
| TRAP-04 | 重复表头计入忽略行 | `app/intake/service.py` | `tests/test_intake.py::test_repeated_header_is_counted` |
| TRAP-05 | 异常列数隔离 | `app/intake/schema.py` | `tests/test_intake.py::test_extra_column_is_isolated` |
| TRAP-06 | 归一化全角数字和千分位 | `app/intake/numeric.py` | `tests/test_intake.py::test_full_width_and_grouping_are_canonical` |
| TRAP-07 | 空值行隔离 | `app/intake/numeric.py` | `tests/test_intake.py::test_sentinel_keeps_row_out_of_total` |
| TRAP-08 | 记录键保留前导零 | `app/intake/schema.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-14 | 冲突版本都进入隔离 | `app/intake/resolve.py` | `tests/test_intake.py::test_duplicate_conflict_removes_both_copies` |
| TRAP-16 | 引号未闭合时拒收文件 | `app/intake/reader.py` | `tests/test_intake.py::test_unclosed_quote_invalidates_source` |
| TRAP-18 | 区分空文件、全空白和仅表头 | `app/intake/reader.py` | `tests/test_intake.py::test_empty_states_have_distinct_causes` |
| TRAP-26 | 拒绝旧版本复核 | `app/review/store.py` | `tests/test_review.py::test_review_optimistic_lock` |

## 领域反例

停时按左闭右开分钟段记录。先剪裁并合并暂停时段，再扣除免计分钟。前 60 分钟每分 1 分钱，后 60 分钟每分 3 分钱，余下每分 5 分钱。

逐组预期结论见 `tests/test_policy.py`，计算过程证据见 `tests/test_calculate.py`。

## 月末交接处置保证

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 未结争议原凭据完整保留 | `app/retention/policy.py`、`app/retention/disputes.py` | `test_open_dispute_keeps_original_voucher_intact` |
| 保留期满且无争议才清空敏感值 | `app/retention/policy.py::decide` | `test_expired_without_dispute_purges_sensitive_values` |
| 清空不可由处置结果还原（无原文无哈希） | `app/retention/redact.py` | `test_purged_result_cannot_reconstruct_sensitive_text` |
| 记录键、金额、来源分组仍可核对 | `app/retention/service.py` 对账段 | `test_purge_keeps_keys_amounts_and_source_relations` |
| 同任务重试不新增处置记录 | 依据哈希幂等，决策时刻不入键 | `test_retry_same_task_adds_no_disposal_record` |
| 补录记录不被误删，只清说明列 | 脱敏仅覆盖 `note` 字段 | `test_purge_keeps_keys_amounts_and_source_relations` |
| 交接失败保留旧版本与原凭据 | `DisposalStore.commit_disposal` 单事务 | `test_failed_handoff_keeps_previous_version` |
| 页面与下载同一份结果 | `app/retention/render.py` 统一序列化 | `test_page_and_download_read_identical_disposal_bytes` |
| 并行处置只落一条记录 | 主键 UPSERT + 依据哈希短路 | `test_parallel_disposal_commits_single_record` |

敏感值仅指自由文本：来源凭据每行说明列 `note` 与批次复核意见；分钟段、金额、记录键、业务分组等结构化核对字段不属于敏感值，处置中一律保留。处置历史写入只追加的 `disposal_ledger` 版本台账，当前结果存于 `disposals`，二者在同一事务内更新。
