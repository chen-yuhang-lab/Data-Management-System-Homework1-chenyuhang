"""
utils.py

通用 JSON 序列化工具。
MongoDB 文档中会包含 ObjectId / datetime，FastAPI 的 jsonable_encoder
默认不认识 ObjectId，直接返回会导致 500。这里统一递归转换为字符串。
"""
from datetime import datetime
from typing import Any

from bson import ObjectId


def to_jsonable(value: Any) -> Any:
    """递归把 MongoDB 数据类型转换成 JSON 可序列化类型。"""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value
