"""处置结果序列化：页面读取与下载交付共用同一份字节，杜绝两份口径。"""

import json

CONTENT_TYPE = "application/json; charset=utf-8"
DISPOSAL_SCHEMA = "retention-disposal/1"


def render(result):
    return (
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
