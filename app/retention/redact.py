"""敏感值脱敏。

敏感值的界定（见 docs/DATA-DICTIONARY.md）：仅自由文本 `note`
（来源凭据每行的说明列、批次复核意见）。记录键、业务分组、分钟段、
免计分钟、金额等结构化核对字段一律保留，保证账实仍可核对。

脱敏只做覆盖式清空，不保留原文、哈希或可逆变换，处置结果本身
无法还原被清空的内容。
"""

# 被清空的敏感字段，登记后供处置结果审计
SENSITIVE_FIELDS = ("voucher[].note", "review_note")
CLEARED = None


def redact_voucher(rows):
    """返回拷贝后的凭据，说明列统一清空为 null；不修改原对象。"""
    return [
        {**row, "note": CLEARED} if "note" in row else dict(row) for row in rows
    ]
