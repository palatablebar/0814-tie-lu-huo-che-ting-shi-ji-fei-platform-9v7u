# 字段与业务定义

输入编码 UTF-8，允许 BOM。首行必须匹配样例列顺序。记录键和业务组保留原始字符串。`kind` 允许 stay, pause, invoice。说明列 `note` 可以跨行，限制 200 字。

业务字段按 `start_min`、`end_min`、`free_min`、`amount_cents` 排列。数字接受非负整数、全角数字和完整千分位。空串、短横线、N/A、NULL 与未知为缺值。无关字段用 0 占位。

停时按左闭右开分钟段记录。先剪裁并合并暂停时段，再扣除免计分钟。前 60 分钟每分 1 分钱，后 60 分钟每分 3 分钱，余下每分 5 分钱。

`incoming.csv` 包含四个业务组，第二组提供不同边界，第三组触发业务拒收，第四组需要核对。另含重复表头、冲突记录、重复回放与错误列数。`ready.csv` 含可以签发的两个组。

## 月末处置字段

敏感值仅指自由文本：每行说明列 `note`（交接明细、复核底稿、补录记录、已对照来源等）与批次复核意见。`record`、`case`、`kind`、`start_min`、`end_min`、`free_min`、`amount_cents` 为结构化核对字段，处置中一律保留，保证账实与来源关系可核对。

处置结果 `retention-disposal/1` 含：`disposition`（`RETAINED`/`PURGED`）、`basis` 与 `basis_hash`（幂等依据，决策时刻不入哈希）、`policy`（保留期、截止时刻、判定理由、未结争议数）、`reconciliation`（记录键、业务分组、发票金额、凭据行数）、`voucher`（结构化凭据，清空后 `note` 为 `null`）、`review`（签发状态、版本、复核时间戳，清空后意见为 `null`）、`redaction`（敏感字段登记与本次清空字段）。

保留期限自批次执行时刻（`manifest.created`）起算，默认 1825 天，可在处置请求中以 1 至 36500 的整数覆盖。
