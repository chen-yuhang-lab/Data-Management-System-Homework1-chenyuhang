"""
services/question_bank_service.py

第二阶段新增：题库、题目版本、题目共享、跨问卷使用情况的核心业务层。

设计要点（与第一阶段兼容）：
1. 第一阶段 questions 集合仍然表示“某份问卷中的一道题目实例”，
   fill_survey / validate_service / jump_service / stat_service 不需要改数据结构即可继续工作。
2. 第二阶段新增“题目模板 + 不可变版本”：
   - question_templates：题目的逻辑主记录（一个题目可以有多个版本）；
   - question_versions ：每次修改产生一个不可变版本，历史版本永远保留；
   - questions          ：问卷题目实例通过 template_id / version_id 指向某个版本，
                          同时仍然保存一份内容副本，保证旧问卷和旧代码不受影响。
3. 已经发布的问卷，其题目实例被冻结（新增/修改/删除均拒绝），
   如需调整，请在题库中创建新版本，或使用派生/复制接口生成新题目。
4. 共享只授予“使用权”，不授予“修改模板权”；被共享用户可以 fork 出自己独立的题目。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from database import (
    question_bank_items,
    question_banks,
    question_shares,
    question_templates,
    question_versions,
    questions,
    surveys,
    users,
)

# 题目的全部内容字段。顺序固定，方便快照、比较和测试。
CONTENT_FIELDS = [
    "question_title",
    "question_type",
    "is_required",
    "single_options",
    "multi_options",
    "multi_min",
    "multi_max",
    "multi_exact",
    "text_min_len",
    "text_max_len",
    "num_min",
    "num_max",
    "num_must_int",
]

QUESTION_TYPES = {"single_choice", "multi_choice", "text_fill", "number_fill"}


# ============================== 异常定义 ==============================
class QuestionBankError(Exception):
    """题库业务异常基类，路由层统一转换为 HTTP 状态码。"""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class QuestionBankNotFound(QuestionBankError):
    status_code = 404


class QuestionBankPermissionDenied(QuestionBankError):
    status_code = 403


class QuestionBankConflict(QuestionBankError):
    status_code = 409


class QuestionContentInvalid(QuestionBankError):
    status_code = 400


# ============================== 基础工具 ==============================
def to_object_id(value: Any, field_name: str = "id") -> ObjectId:
    """把字符串转换成 ObjectId；非法格式时抛出业务异常。"""
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except Exception:
        raise QuestionContentInvalid(f"{field_name} 格式错误")


def opt_object_id(value: Any) -> Optional[ObjectId]:
    if value in (None, ""):
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def _id_str(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _content_from_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """从题目实例或版本文档中提取内容字段。"""
    return {field: doc.get(field) for field in CONTENT_FIELDS}


def _merge_content(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """在旧内容基础上应用补丁；补丁里显式出现的字段（包括 None）会覆盖旧值。"""
    merged = {field: base.get(field) for field in CONTENT_FIELDS}
    for field in CONTENT_FIELDS:
        if field in patch:
            merged[field] = patch[field]
    return merged


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def validate_question_content(content: Dict[str, Any]) -> None:
    """校验题目内容及各类题型的配置，错误信息直接给前端使用。"""
    title = _clean_text(content.get("question_title"))
    if not title:
        raise QuestionContentInvalid("题目标题不能为空")

    q_type = content.get("question_type")
    if q_type not in QUESTION_TYPES:
        raise QuestionContentInvalid("题目类型不合法")

    if not isinstance(content.get("is_required", False), bool):
        raise QuestionContentInvalid("is_required 必须是布尔值")

    if q_type == "single_choice":
        options = content.get("single_options") or []
        if not isinstance(options, list) or len(options) < 2:
            raise QuestionContentInvalid("单选题至少需要2个选项")
        if any(not _clean_text(opt) for opt in options):
            raise QuestionContentInvalid("单选题选项不能为空")
        if len(set(options)) != len(options):
            raise QuestionContentInvalid("单选题选项不能重复")

    elif q_type == "multi_choice":
        options = content.get("multi_options") or []
        if not isinstance(options, list) or len(options) < 2:
            raise QuestionContentInvalid("多选题至少需要2个选项")
        if any(not _clean_text(opt) for opt in options):
            raise QuestionContentInvalid("多选题选项不能为空")
        if len(set(options)) != len(options):
            raise QuestionContentInvalid("多选题选项不能重复")

        multi_min = content.get("multi_min")
        multi_max = content.get("multi_max")
        multi_exact = content.get("multi_exact")

        for name, val in (
            ("multi_min", multi_min),
            ("multi_max", multi_max),
            ("multi_exact", multi_exact),
        ):
            if val is not None and (not isinstance(val, int) or val < 0):
                raise QuestionContentInvalid(f"{name} 必须是非负整数")

        if multi_min is not None and multi_max is not None and multi_min > multi_max:
            raise QuestionContentInvalid("多选最少选择数不能大于最多选择数")
        if multi_exact is not None:
            if multi_exact < 1:
                raise QuestionContentInvalid("多选必须选择数量至少为1")
            if multi_exact > len(options):
                raise QuestionContentInvalid("多选必须选择数量不能超过选项总数")
            if multi_min is not None and multi_exact < multi_min:
                raise QuestionContentInvalid("多选必须选择数量不能小于最少选择数")
            if multi_max is not None and multi_exact > multi_max:
                raise QuestionContentInvalid("多选必须选择数量不能大于最多选择数")

    elif q_type == "text_fill":
        text_min = content.get("text_min_len")
        text_max = content.get("text_max_len")
        for name, val in (("text_min_len", text_min), ("text_max_len", text_max)):
            if val is not None and (not isinstance(val, int) or val < 0):
                raise QuestionContentInvalid(f"{name} 必须是非负整数")
        if text_min is not None and text_max is not None and text_min > text_max:
            raise QuestionContentInvalid("文本最少字数不能大于最多字数")

    elif q_type == "number_fill":
        num_min = content.get("num_min")
        num_max = content.get("num_max")
        for name, val in (("num_min", num_min), ("num_max", num_max)):
            if val is not None and not isinstance(val, (int, float)):
                raise QuestionContentInvalid(f"{name} 必须是数字")
        if num_min is not None and num_max is not None and num_min > num_max:
            raise QuestionContentInvalid("数字最小值不能大于最大值")
        must_int = content.get("num_must_int")
        if must_int is not None and not isinstance(must_int, bool):
            raise QuestionContentInvalid("num_must_int 必须是布尔值")


def merge_and_validate_question(question_doc: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    把修改补丁合并到问卷题目实例上并校验。
    路由层的普通编辑（不创建新版本）也复用这一套规则，避免两套校验标准。
    """
    merged = _merge_content(_content_from_doc(question_doc), patch)
    validate_question_content(merged)
    return merged


def serialize_version(version: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """版本文档转 JSON 友好结构。"""
    if not version:
        return None
    data = {
        "version_id": str(version["_id"]),
        "template_id": str(version["template_id"]),
        "version_no": version.get("version_no"),
        "parent_version_id": _id_str(version.get("parent_version_id")),
        "restored_from_version_id": _id_str(version.get("restored_from_version_id")),
        "source_question_id": _id_str(version.get("source_question_id")),
        "created_by": _id_str(version.get("created_by")),
        "created_at": _iso(version.get("created_at")),
        "change_note": version.get("change_note", ""),
    }
    data.update(_content_from_doc(version))
    return data


def serialize_template(
    template: Dict[str, Any],
    current_version: Optional[Dict[str, Any]] = None,
    owner_username: Optional[str] = None,
    access_type: str = "owner",
    usage_count: int = 0,
    versions_count: int = 0,
    share_count: int = 0,
) -> Dict[str, Any]:
    """模板文档转 JSON 友好结构，同时带上当前版本内容，便于前端直接渲染。"""
    if current_version is None and template.get("current_version_id"):
        current_version = question_versions.find_one({"_id": template["current_version_id"]})

    data = {
        "template_id": str(template["_id"]),
        "owner_user_id": _id_str(template.get("owner_user_id")),
        "owner_username": owner_username,
        "title": template.get("title"),
        "question_type": template.get("question_type"),
        "current_version_id": _id_str(template.get("current_version_id")),
        "current_version_no": template.get("current_version_no", 0),
        "parent_template_id": _id_str(template.get("parent_template_id")),
        "source_version_id": _id_str(template.get("source_version_id")),
        "created_at": _iso(template.get("created_at")),
        "updated_at": _iso(template.get("updated_at")),
        "is_deleted": bool(template.get("is_deleted", False)),
        "access_type": access_type,
        "usage_count": usage_count,
        "versions_count": versions_count,
        "share_count": share_count,
        "current_version": serialize_version(current_version),
    }
    return data


def _get_template_or_404(template_id: str) -> Dict[str, Any]:
    template = question_templates.find_one({
        "_id": to_object_id(template_id, "template_id"),
        "is_deleted": {"$ne": True},
    })
    if not template:
        raise QuestionBankNotFound("题目不存在")
    return template


def _get_version_or_404(version_id: str, template_id: Optional[ObjectId] = None) -> Dict[str, Any]:
    version = question_versions.find_one({"_id": to_object_id(version_id, "version_id")})
    if not version:
        raise QuestionBankNotFound("题目版本不存在")
    if template_id is not None and version.get("template_id") != template_id:
        raise QuestionContentInvalid("该版本不属于指定题目")
    return version


def _owner_username(user_id: Any) -> Optional[str]:
    user = users.find_one({"_id": user_id}, {"username": 1})
    return user.get("username") if user else None


def _require_owner(template: Dict[str, Any], user_id: str) -> None:
    if str(template.get("owner_user_id")) != str(user_id):
        raise QuestionBankPermissionDenied("只有题目创建者可以执行该操作")


def _share_is_active(template_id: ObjectId, user_id: str) -> bool:
    share = question_shares.find_one({
        "template_id": template_id,
        "shared_with_user_id": to_object_id(user_id, "user_id"),
        "is_active": True,
        "can_use": True,
    })
    return share is not None


def can_use_template(template: Dict[str, Any], user_id: str) -> bool:
    """当前用户是否可以“使用”模板：创建者本人或获得有效共享授权的人。"""
    if str(template.get("owner_user_id")) == str(user_id):
        return True
    return _share_is_active(template["_id"], user_id)


def _new_version_doc(
    template_id: ObjectId,
    version_no: int,
    content: Dict[str, Any],
    created_by: ObjectId,
    parent_version_id: Optional[ObjectId] = None,
    change_note: str = "",
    source_question_id: Optional[ObjectId] = None,
    restored_from_version_id: Optional[ObjectId] = None,
) -> Dict[str, Any]:
    doc = {
        "template_id": template_id,
        "version_no": version_no,
        "parent_version_id": parent_version_id,
        "restored_from_version_id": restored_from_version_id,
        "source_question_id": source_question_id,
        "created_by": created_by,
        "created_at": datetime.utcnow(),
        "change_note": change_note or "",
    }
    doc.update(_content_from_doc(content))
    return doc


# ============================== 题目模板 / 版本 ==============================
def create_template(
    owner_user_id: str,
    content: Dict[str, Any],
    bank_id: Optional[str] = None,
    change_note: str = "初始版本",
    source_question_id: Optional[Any] = None,
    parent_template_id: Optional[Any] = None,
    source_version_id: Optional[Any] = None,
) -> Tuple[str, str]:
    """
    新建题目模板，同时生成 v1 版本。
    返回 (template_id, version_id)。
    """
    owner_oid = to_object_id(owner_user_id, "user_id")
    normalized = {field: content.get(field) for field in CONTENT_FIELDS}
    validate_question_content(normalized)

    # 先校验题库归属，避免模板已插入后才发现题库不可用
    if bank_id:
        bank = _get_bank_or_404(bank_id)
        if str(bank.get("owner_user_id")) != str(owner_user_id):
            raise QuestionBankPermissionDenied("无权操作该题库")

    now = datetime.utcnow()
    template_doc = {
        "owner_user_id": owner_oid,
        "title": _clean_text(normalized["question_title"]),
        "question_type": normalized["question_type"],
        "current_version_id": None,
        "current_version_no": 0,
        "parent_template_id": opt_object_id(parent_template_id),
        "source_version_id": opt_object_id(source_version_id),
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    template_id = question_templates.insert_one(template_doc).inserted_id

    version_doc = _new_version_doc(
        template_id=template_id,
        version_no=1,
        content=normalized,
        created_by=owner_oid,
        parent_version_id=None,
        change_note=change_note,
        source_question_id=opt_object_id(source_question_id),
    )
    version_id = question_versions.insert_one(version_doc).inserted_id

    question_templates.update_one(
        {"_id": template_id},
        {"$set": {
            "current_version_id": version_id,
            "current_version_no": 1,
            "updated_at": now,
        }},
    )

    if bank_id:
        add_template_to_bank(bank_id, str(template_id), owner_user_id)

    return str(template_id), str(version_id)


def create_new_version(
    template_id: str,
    user_id: str,
    patch: Dict[str, Any],
    change_note: str = "",
    base_content: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    在现有模板上创建一个新版本。只有模板创建者可以执行。
    旧版本不会被修改，引用旧版本的问卷保持原内容。

    base_content：可选的“修改前内容”。普通题库编辑不传，默认使用模板当前版本；
    从问卷题目实例发起修改时传入题目实例内容，确保本地修改也会进入新版本。
    """
    template = _get_template_or_404(template_id)
    _require_owner(template, user_id)

    current_version_id = template.get("current_version_id")
    if not current_version_id:
        raise QuestionBankConflict("题目当前版本异常，无法创建新版本")
    current = _get_version_or_404(str(current_version_id), template["_id"])

    base = base_content if base_content is not None else _content_from_doc(current)
    merged = _merge_content(base, patch)
    validate_question_content(merged)

    new_no = int(template.get("current_version_no") or 0) + 1
    now = datetime.utcnow()
    version_doc = _new_version_doc(
        template_id=template["_id"],
        version_no=new_no,
        content=merged,
        created_by=to_object_id(user_id, "user_id"),
        parent_version_id=current["_id"],
        change_note=change_note or f"更新为 v{new_no}",
    )
    version_id = question_versions.insert_one(version_doc).inserted_id
    question_templates.update_one(
        {"_id": template["_id"]},
        {"$set": {
            "title": _clean_text(merged["question_title"]),
            "question_type": merged["question_type"],
            "current_version_id": version_id,
            "current_version_no": new_no,
            "updated_at": now,
        }},
    )
    return serialize_version(question_versions.find_one({"_id": version_id}))


def restore_version(template_id: str, version_id: str, user_id: str) -> Dict[str, Any]:
    """
    恢复旧版本：不删除任何历史版本，而是把旧版本内容复制成一个新版本。
    这样 v1 -> v2 -> v3 的链路仍然完整，v3 记录 restored_from_version_id=v1。
    """
    template = _get_template_or_404(template_id)
    _require_owner(template, user_id)
    source = _get_version_or_404(version_id, template["_id"])

    current_version_id = template.get("current_version_id")
    current = _get_version_or_404(str(current_version_id), template["_id"]) if current_version_id else None

    new_no = int(template.get("current_version_no") or 0) + 1
    merged = _content_from_doc(source)
    validate_question_content(merged)

    version_doc = _new_version_doc(
        template_id=template["_id"],
        version_no=new_no,
        content=merged,
        created_by=to_object_id(user_id, "user_id"),
        parent_version_id=current["_id"] if current else None,
        change_note=f"恢复自 v{source.get('version_no')}",
        restored_from_version_id=source["_id"],
    )
    new_version_id = question_versions.insert_one(version_doc).inserted_id
    question_templates.update_one(
        {"_id": template["_id"]},
        {"$set": {
            "title": _clean_text(merged["question_title"]),
            "question_type": merged["question_type"],
            "current_version_id": new_version_id,
            "current_version_no": new_no,
            "updated_at": datetime.utcnow(),
        }},
    )
    return serialize_version(question_versions.find_one({"_id": new_version_id}))


def fork_template(
    template_id: str,
    user_id: str,
    version_id: Optional[str] = None,
    title: Optional[str] = None,
) -> Tuple[str, str]:
    """
    基于某个模板版本派生出一个属于当前用户的新模板。
    被共享用户可以用它把别人的题变成自己的独立题目，不影响原题。
    """
    template = _get_template_or_404(template_id)
    if not can_use_template(template, user_id):
        raise QuestionBankPermissionDenied("无权使用该题目")
    version = _get_version_or_404(version_id, template["_id"]) if version_id else _get_version_or_404(
        str(template["current_version_id"]), template["_id"]
    )

    content = _content_from_doc(version)
    if title:
        content["question_title"] = title
    return create_template(
        owner_user_id=user_id,
        content=content,
        change_note=f"派生自题目 {template_id} 的 v{version.get('version_no')}",
        parent_template_id=template["_id"],
        source_version_id=version["_id"],
    )


def get_template_detail(template_id: str, user_id: str) -> Dict[str, Any]:
    template = _get_template_or_404(template_id)
    if not can_use_template(template, user_id):
        raise QuestionBankPermissionDenied("无权查看该题目")

    current = None
    if template.get("current_version_id"):
        current = question_versions.find_one({"_id": template["current_version_id"]})
    versions = list(question_versions.find({"template_id": template["_id"]}).sort("version_no", 1))

    usage_count = questions.count_documents({"template_id": template["_id"]})
    share_count = question_shares.count_documents({"template_id": template["_id"], "is_active": True})
    access_type = "owner" if str(template["owner_user_id"]) == str(user_id) else "shared"

    result = serialize_template(
        template,
        current_version=current,
        owner_username=_owner_username(template.get("owner_user_id")),
        access_type=access_type,
        usage_count=usage_count,
        versions_count=len(versions),
        share_count=share_count,
    )
    result["versions"] = [serialize_version(v) for v in versions]
    return result


def get_version_history(template_id: str, user_id: str) -> Dict[str, Any]:
    template = _get_template_or_404(template_id)
    if not can_use_template(template, user_id):
        raise QuestionBankPermissionDenied("无权查看该题目历史")
    versions = list(question_versions.find({"template_id": template["_id"]}).sort("version_no", 1))
    return {
        "template_id": str(template["_id"]),
        "title": template.get("title"),
        "current_version_id": _id_str(template.get("current_version_id")),
        "current_version_no": template.get("current_version_no", 0),
        "versions": [serialize_version(v) for v in versions],
    }


def list_templates_for_user(user_id: str, scope: str = "all") -> List[Dict[str, Any]]:
    """
    scope:
      mine   -> 我创建的
      shared -> 别人共享给我的
      all    -> 两者合并
    """
    user_oid = to_object_id(user_id, "user_id")
    template_ids: List[ObjectId] = []
    access_map: Dict[ObjectId, str] = {}

    if scope in ("mine", "all"):
        own_ids = [
            doc["_id"]
            for doc in question_templates.find(
                {"owner_user_id": user_oid, "is_deleted": {"$ne": True}},
                {"_id": 1},
            )
        ]
        for tid in own_ids:
            access_map[tid] = "owner"
        template_ids.extend(own_ids)

    if scope in ("shared", "all"):
        shares = list(question_shares.find({
            "shared_with_user_id": user_oid,
            "is_active": True,
            "can_use": True,
        }))
        for share in shares:
            tid = share["template_id"]
            if tid not in access_map:
                access_map[tid] = "shared"
                template_ids.append(tid)

    if not template_ids:
        return []

    # 批量统计使用次数和版本数量，避免逐题查库
    usage_map = {
        row["_id"]: row["count"]
        for row in questions.aggregate([
            {"$match": {"template_id": {"$in": template_ids}}},
            {"$group": {"_id": "$template_id", "count": {"$sum": 1}}},
        ])
    }
    version_map = {
        row["_id"]: row["count"]
        for row in question_versions.aggregate([
            {"$match": {"template_id": {"$in": template_ids}}},
            {"$group": {"_id": "$template_id", "count": {"$sum": 1}}},
        ])
    }
    share_map = {
        row["_id"]: row["count"]
        for row in question_shares.aggregate([
            {"$match": {"template_id": {"$in": template_ids}, "is_active": True}},
            {"$group": {"_id": "$template_id", "count": {"$sum": 1}}},
        ])
    }

    result = []
    templates = question_templates.find({
        "_id": {"$in": template_ids},
        "is_deleted": {"$ne": True},
    })
    for template in templates:
        current = None
        if template.get("current_version_id"):
            current = question_versions.find_one({"_id": template["current_version_id"]})
        result.append(serialize_template(
            template,
            current_version=current,
            owner_username=_owner_username(template.get("owner_user_id")),
            access_type=access_map.get(template["_id"], "shared"),
            usage_count=usage_map.get(template["_id"], 0),
            versions_count=version_map.get(template["_id"], 0),
            share_count=share_map.get(template["_id"], 0),
        ))

    result.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return result


# ============================== 共享 ==============================
def share_template(
    template_id: str,
    owner_user_id: str,
    target_username: str,
    can_use: bool = True,
) -> Dict[str, Any]:
    template = _get_template_or_404(template_id)
    _require_owner(template, owner_user_id)

    target = users.find_one({"username": target_username})
    if not target:
        raise QuestionBankNotFound("目标用户不存在")
    if str(target["_id"]) == str(owner_user_id):
        raise QuestionContentInvalid("不能共享给自己")

    now = datetime.utcnow()
    question_shares.update_one(
        {
            "template_id": template["_id"],
            "shared_with_user_id": target["_id"],
        },
        {
            "$set": {
                "owner_user_id": to_object_id(owner_user_id, "user_id"),
                "can_use": bool(can_use),
                "is_active": True,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    share = question_shares.find_one({
        "template_id": template["_id"],
        "shared_with_user_id": target["_id"],
    })
    return _serialize_share(share, template, target)


def revoke_share(template_id: str, owner_user_id: str, target_user_id: str) -> Dict[str, Any]:
    template = _get_template_or_404(template_id)
    _require_owner(template, owner_user_id)
    target_oid = to_object_id(target_user_id, "target_user_id")
    result = question_shares.update_one(
        {
            "template_id": template["_id"],
            "shared_with_user_id": target_oid,
        },
        {"$set": {"is_active": False, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise QuestionBankNotFound("共享记录不存在")
    return {"template_id": str(template["_id"]), "target_user_id": str(target_oid), "is_active": False}


def list_shares(template_id: str, owner_user_id: str) -> List[Dict[str, Any]]:
    template = _get_template_or_404(template_id)
    _require_owner(template, owner_user_id)
    shares = list(question_shares.find({"template_id": template["_id"], "is_active": True}))
    target_ids = [s["shared_with_user_id"] for s in shares]
    user_map = {
        u["_id"]: u
        for u in users.find({"_id": {"$in": target_ids}})
    }
    return [
        _serialize_share(share, template, user_map.get(share["shared_with_user_id"]))
        for share in shares
    ]


def _serialize_share(share: Dict[str, Any], template: Dict[str, Any], target_user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "share_id": str(share["_id"]),
        "template_id": str(template["_id"]),
        "template_title": template.get("title"),
        "owner_user_id": _id_str(share.get("owner_user_id")),
        "shared_with_user_id": _id_str(share.get("shared_with_user_id")),
        "shared_with_username": target_user.get("username") if target_user else None,
        "can_use": bool(share.get("can_use", True)),
        "is_active": bool(share.get("is_active", True)),
        "created_at": _iso(share.get("created_at")),
        "updated_at": _iso(share.get("updated_at")),
    }


# ============================== 问卷使用 ==============================
def _question_instance_doc(
    survey: Dict[str, Any],
    content: Dict[str, Any],
    template_id: ObjectId,
    version: Dict[str, Any],
    source: str = "question_bank",
    bank_id: Optional[ObjectId] = None,
) -> Dict[str, Any]:
    doc = {
        "survey_id": survey["_id"],
        "template_id": template_id,
        "version_id": version["_id"],
        "version_no": version.get("version_no"),
        "source": source,
        "bank_id": bank_id,
        "created_at": datetime.utcnow(),
    }
    doc.update(_content_from_doc(content))
    return doc


def add_template_to_survey(
    survey_id: str,
    template_id: str,
    user_id: str,
    version_id: Optional[str] = None,
    bank_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    把题库中的某个题目版本加入问卷，生成第一阶段兼容的 questions 文档。
    问卷必须属于当前用户，且尚未发布。
    """
    survey = surveys.find_one({"_id": to_object_id(survey_id, "survey_id")})
    if not survey:
        raise QuestionBankNotFound("问卷不存在")
    if str(survey.get("owner_user_id")) != str(user_id):
        raise QuestionBankPermissionDenied("无权操作该问卷")
    if survey.get("is_published"):
        raise QuestionBankConflict("问卷已发布，题目结构已冻结；请取消发布或新建问卷后再添加题目")

    template = _get_template_or_404(template_id)
    if not can_use_template(template, user_id):
        raise QuestionBankPermissionDenied("无权使用该题目")

    if version_id:
        version = _get_version_or_404(version_id, template["_id"])
    else:
        if not template.get("current_version_id"):
            raise QuestionBankConflict("题目没有可用版本")
        version = _get_version_or_404(str(template["current_version_id"]), template["_id"])

    # 题库归属校验（如果指定了题库）
    bank_oid = None
    if bank_id:
        bank = _get_bank_or_404(bank_id)
        if str(bank.get("owner_user_id")) != str(user_id):
            raise QuestionBankPermissionDenied("无权操作该题库")
        bank_oid = bank["_id"]

    exists = questions.find_one({
        "survey_id": survey["_id"],
        "template_id": template["_id"],
        "version_id": version["_id"],
    })
    if exists:
        raise QuestionBankConflict("该题目版本已经添加到本问卷，请勿重复添加")

    content = _content_from_doc(version)
    doc = _question_instance_doc(survey, content, template["_id"], version, bank_id=bank_oid)
    question_id = questions.insert_one(doc).inserted_id

    if bank_oid is not None:
        question_bank_items.update_one(
            {"bank_id": bank_oid, "template_id": template["_id"]},
            {"$setOnInsert": {
                "added_by": to_object_id(user_id, "user_id"),
                "added_at": datetime.utcnow(),
            }},
            upsert=True,
        )

    result = {
        "question_id": str(question_id),
        "survey_id": str(survey["_id"]),
        "template_id": str(template["_id"]),
        "version_id": str(version["_id"]),
        "version_no": version.get("version_no"),
    }
    result.update(content)
    return result


def update_question_with_new_version(
    question_id: str,
    user_id: str,
    patch: Dict[str, Any],
    change_note: str = "",
) -> Dict[str, Any]:
    """
    修改问卷中的一道题，并把这次修改记录成新版本。
    规则：
      - 问卷必须未发布；
      - 如果题目模板属于当前用户，直接在原模板上追加版本；
      - 如果题目来自别人的共享模板，则为当前用户派生一个独立模板，不影响原模板；
      - 如果第一阶段旧题目没有模板，则先把旧内容固化为 v1，再生成 v2。
    """
    question = questions.find_one({"_id": to_object_id(question_id, "question_id")})
    if not question:
        raise QuestionBankNotFound("题目不存在")
    survey = surveys.find_one({"_id": question["survey_id"]})
    if not survey:
        raise QuestionBankNotFound("所属问卷不存在")
    if str(survey.get("owner_user_id")) != str(user_id):
        raise QuestionBankPermissionDenied("无权修改该题目")
    if survey.get("is_published"):
        raise QuestionBankConflict("问卷已发布，题目不可修改；请使用派生/复制接口生成新题目")

    old_content = _content_from_doc(question)
    merged = _merge_content(old_content, patch)
    validate_question_content(merged)

    template_id = opt_object_id(question.get("template_id"))
    version_result: Dict[str, Any]

    if template_id:
        template = _get_template_or_404(str(template_id))
        if str(template.get("owner_user_id")) == str(user_id):
            # 自己的题目：在原模板上追加版本
            version_result = create_new_version(str(template_id), user_id, patch, change_note, base_content=old_content)
        else:
            # 别人的共享题目：派生自己的模板（v1=原内容），再追加 v2=修改后内容
            new_template_id, _ = create_template(
                owner_user_id=user_id,
                content=old_content,
                change_note=f"基于共享题目 {template_id} 派生",
                source_question_id=question["_id"],
                parent_template_id=template_id,
                source_version_id=question.get("version_id"),
            )
            version_result = create_new_version(new_template_id, user_id, patch, change_note, base_content=old_content)
            template_id = to_object_id(new_template_id)
    else:
        # 第一阶段旧题目：固化旧内容为 v1，再生成 v2
        new_template_id, _ = create_template(
            owner_user_id=user_id,
            content=old_content,
            change_note="由第一阶段问卷题目自动归档",
            source_question_id=question["_id"],
        )
        version_result = create_new_version(new_template_id, user_id, patch, change_note, base_content=old_content)
        template_id = to_object_id(new_template_id)

    # 更新问卷题目实例（只影响当前问卷，其他问卷引用旧版本不受影响）
    set_fields = {
        field: merged.get(field) for field in CONTENT_FIELDS
    }
    set_fields.update({
        "template_id": template_id,
        "version_id": to_object_id(version_result["version_id"], "version_id"),
        "version_no": version_result["version_no"],
        "source": question.get("source") or "phase1",
        "updated_at": datetime.utcnow(),
    })
    questions.update_one({"_id": question["_id"]}, {"$set": set_fields})

    result = {
        "question_id": str(question["_id"]),
        "template_id": str(template_id),
        "version_id": version_result["version_id"],
        "version_no": version_result["version_no"],
        "content": merged,
    }
    return result


def fork_question_to_survey(
    source_question_id: str,
    user_id: str,
    target_survey_id: Optional[str] = None,
    new_title: Optional[str] = None,
) -> Dict[str, Any]:
    """
    以问卷中的某道题为蓝本，生成一道全新的题目并加入目标问卷。
    源题目完全不变，因此即使源问卷已发布也可以使用此接口。
    """
    source_question = questions.find_one({"_id": to_object_id(source_question_id, "question_id")})
    if not source_question:
        raise QuestionBankNotFound("源题目不存在")
    source_survey = surveys.find_one({"_id": source_question["survey_id"]})
    if not source_survey:
        raise QuestionBankNotFound("源问卷不存在")

    target_id = target_survey_id or str(source_question["survey_id"])
    target_survey = surveys.find_one({"_id": to_object_id(target_id, "target_survey_id")})
    if not target_survey:
        raise QuestionBankNotFound("目标问卷不存在")
    if str(target_survey.get("owner_user_id")) != str(user_id):
        raise QuestionBankPermissionDenied("无权操作目标问卷")
    if target_survey.get("is_published"):
        raise QuestionBankConflict("目标问卷已发布，不能新增题目")

    # 访问源题目：源问卷属于自己，或源题目的模板对自己共享
    allowed = str(source_survey.get("owner_user_id")) == str(user_id)
    if not allowed and source_question.get("template_id"):
        template = question_templates.find_one({"_id": source_question["template_id"]})
        allowed = bool(template and can_use_template(template, user_id))
    if not allowed:
        raise QuestionBankPermissionDenied("无权复制该题目")

    content = _content_from_doc(source_question)
    if new_title:
        content["question_title"] = new_title
    validate_question_content(content)

    new_template_id, new_version_id = create_template(
        owner_user_id=user_id,
        content=content,
        change_note=f"复制自题目 {source_question_id}",
        source_question_id=source_question["_id"],
        parent_template_id=source_question.get("template_id"),
        source_version_id=source_question.get("version_id"),
    )
    new_template = _get_template_or_404(new_template_id)
    new_version = _get_version_or_404(new_version_id, new_template["_id"])
    doc = _question_instance_doc(
        target_survey,
        content,
        new_template["_id"],
        new_version,
        source="fork",
    )
    new_question_id = questions.insert_one(doc).inserted_id

    result = {
        "question_id": str(new_question_id),
        "source_question_id": str(source_question["_id"]),
        "survey_id": str(target_survey["_id"]),
        "template_id": new_template_id,
        "version_id": new_version_id,
        "version_no": new_version.get("version_no"),
    }
    result.update(content)
    return result


def get_template_usage(template_id: str, user_id: str) -> Dict[str, Any]:
    """查看某个题目被哪些问卷使用，以及每个问卷使用的版本。"""
    template = _get_template_or_404(template_id)
    _require_owner(template, user_id)

    instance_docs = list(questions.find(
        {"template_id": template["_id"]},
        {
            "_id": 1,
            "survey_id": 1,
            "version_id": 1,
            "version_no": 1,
            "question_title": 1,
        },
    ))

    survey_map = {
        s["_id"]: s
        for s in surveys.find({"_id": {"$in": list({q["survey_id"] for q in instance_docs})}})
    }
    grouped: Dict[ObjectId, Dict[str, Any]] = {}
    for q in instance_docs:
        sid = q["survey_id"]
        item = grouped.setdefault(sid, {
            "survey_id": str(sid),
            "survey_title": survey_map.get(sid, {}).get("title"),
            "owner_user_id": _id_str(survey_map.get(sid, {}).get("owner_user_id")),
            "is_published": survey_map.get(sid, {}).get("is_published", False),
            "is_closed": survey_map.get(sid, {}).get("is_closed", False),
            "question_instances": [],
            "versions": set(),
        })
        item["question_instances"].append(str(q["_id"]))
        item["versions"].add(q.get("version_no"))

    usage = []
    for item in grouped.values():
        item["versions"] = sorted(v for v in item["versions"] if v is not None)
        usage.append(item)
    usage.sort(key=lambda x: x.get("survey_title") or "")

    return {
        "template_id": str(template["_id"]),
        "template_title": template.get("title"),
        "current_version_no": template.get("current_version_no", 0),
        "total_surveys": len(usage),
        "total_question_instances": len(instance_docs),
        "usage": usage,
    }


def delete_template(template_id: str, user_id: str, force: bool = False) -> Dict[str, Any]:
    """
    删除（软删除）题目模板。若仍有问卷在使用，默认拒绝；force=True 时只影响题库，
    问卷中的题目实例保存了内容副本，历史答卷仍可正常查看。
    """
    template = _get_template_or_404(template_id)
    _require_owner(template, user_id)
    usage_count = questions.count_documents({"template_id": template["_id"]})
    if usage_count > 0 and not force:
        raise QuestionBankConflict(
            f"该题目仍被 {usage_count} 个问卷题目实例使用；如确认只从题库移除，请传 force=true"
        )

    question_templates.update_one(
        {"_id": template["_id"]},
        {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow()}},
    )
    question_bank_items.delete_many({"template_id": template["_id"]})
    question_shares.update_many(
        {"template_id": template["_id"]},
        {"$set": {"is_active": False, "updated_at": datetime.utcnow()}},
    )
    return {
        "template_id": str(template["_id"]),
        "is_deleted": True,
        "usage_count": usage_count,
    }


# ============================== 题库 ==============================
def _get_bank_or_404(bank_id: str) -> Dict[str, Any]:
    bank = question_banks.find_one({"_id": to_object_id(bank_id, "bank_id")})
    if not bank:
        raise QuestionBankNotFound("题库不存在")
    return bank


def create_bank(owner_user_id: str, name: str, description: str = "", is_public: bool = False) -> Dict[str, Any]:
    if not _clean_text(name):
        raise QuestionContentInvalid("题库名称不能为空")
    now = datetime.utcnow()
    doc = {
        "owner_user_id": to_object_id(owner_user_id, "user_id"),
        "name": name.strip(),
        "description": description or "",
        "is_public": bool(is_public),
        "created_at": now,
        "updated_at": now,
    }
    bank_id = question_banks.insert_one(doc).inserted_id
    return _serialize_bank(question_banks.find_one({"_id": bank_id}), 0)


def _serialize_bank(bank: Dict[str, Any], item_count: int = 0) -> Dict[str, Any]:
    return {
        "bank_id": str(bank["_id"]),
        "owner_user_id": _id_str(bank.get("owner_user_id")),
        "name": bank.get("name"),
        "description": bank.get("description", ""),
        "is_public": bool(bank.get("is_public", False)),
        "item_count": item_count,
        "created_at": _iso(bank.get("created_at")),
        "updated_at": _iso(bank.get("updated_at")),
    }


def list_banks(owner_user_id: str, public_only: bool = False) -> List[Dict[str, Any]]:
    query = {"is_public": True} if public_only else {"owner_user_id": to_object_id(owner_user_id, "user_id")}
    banks = list(question_banks.find(query).sort("updated_at", -1))
    bank_ids = [b["_id"] for b in banks]
    count_map = {
        row["_id"]: row["count"]
        for row in question_bank_items.aggregate([
            {"$match": {"bank_id": {"$in": bank_ids}}},
            {"$group": {"_id": "$bank_id", "count": {"$sum": 1}}},
        ])
    }
    return [_serialize_bank(b, count_map.get(b["_id"], 0)) for b in banks]


def get_bank_detail(bank_id: str, user_id: str) -> Dict[str, Any]:
    bank = _get_bank_or_404(bank_id)
    if str(bank.get("owner_user_id")) != str(user_id) and not bank.get("is_public"):
        raise QuestionBankPermissionDenied("无权查看该题库")
    item_count = question_bank_items.count_documents({"bank_id": bank["_id"]})
    return _serialize_bank(bank, item_count)


def update_bank(bank_id: str, user_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    bank = _get_bank_or_404(bank_id)
    if str(bank.get("owner_user_id")) != str(user_id):
        raise QuestionBankPermissionDenied("无权修改该题库")

    update_fields: Dict[str, Any] = {"updated_at": datetime.utcnow()}
    if "name" in patch:
        if not _clean_text(patch["name"]):
            raise QuestionContentInvalid("题库名称不能为空")
        update_fields["name"] = patch["name"].strip()
    if "description" in patch:
        update_fields["description"] = patch["description"] or ""
    if "is_public" in patch:
        update_fields["is_public"] = bool(patch["is_public"])

    question_banks.update_one({"_id": bank["_id"]}, {"$set": update_fields})
    item_count = question_bank_items.count_documents({"bank_id": bank["_id"]})
    return _serialize_bank(question_banks.find_one({"_id": bank["_id"]}), item_count)


def delete_bank(bank_id: str, user_id: str) -> Dict[str, Any]:
    bank = _get_bank_or_404(bank_id)
    if str(bank.get("owner_user_id")) != str(user_id):
        raise QuestionBankPermissionDenied("无权删除该题库")
    question_bank_items.delete_many({"bank_id": bank["_id"]})
    question_banks.delete_one({"_id": bank["_id"]})
    return {"bank_id": str(bank["_id"]), "deleted": True}


def add_template_to_bank(bank_id: str, template_id: str, user_id: str) -> Dict[str, Any]:
    bank = _get_bank_or_404(bank_id)
    if str(bank.get("owner_user_id")) != str(user_id):
        raise QuestionBankPermissionDenied("无权操作该题库")
    template = _get_template_or_404(template_id)
    if not can_use_template(template, user_id):
        raise QuestionBankPermissionDenied("无权使用该题目")

    question_bank_items.update_one(
        {"bank_id": bank["_id"], "template_id": template["_id"]},
        {"$setOnInsert": {
            "added_by": to_object_id(user_id, "user_id"),
            "added_at": datetime.utcnow(),
        }},
        upsert=True,
    )
    return {
        "bank_id": str(bank["_id"]),
        "template_id": str(template["_id"]),
        "template_title": template.get("title"),
        "added": True,
    }


def remove_template_from_bank(bank_id: str, template_id: str, user_id: str) -> Dict[str, Any]:
    bank = _get_bank_or_404(bank_id)
    if str(bank.get("owner_user_id")) != str(user_id):
        raise QuestionBankPermissionDenied("无权操作该题库")
    result = question_bank_items.delete_one({
        "bank_id": bank["_id"],
        "template_id": to_object_id(template_id, "template_id"),
    })
    if result.deleted_count == 0:
        raise QuestionBankNotFound("题库中不存在该题目")
    return {
        "bank_id": str(bank["_id"]),
        "template_id": template_id,
        "removed": True,
    }


def list_bank_items(bank_id: str, user_id: str) -> Dict[str, Any]:
    bank = _get_bank_or_404(bank_id)
    if str(bank.get("owner_user_id")) != str(user_id) and not bank.get("is_public"):
        raise QuestionBankPermissionDenied("无权查看该题库")

    items = list(question_bank_items.find({"bank_id": bank["_id"]}).sort("added_at", 1))
    template_ids = [item["template_id"] for item in items]
    templates = {
        t["_id"]: t
        for t in question_templates.find({"_id": {"$in": template_ids}, "is_deleted": {"$ne": True}})
    }
    result = []
    for item in items:
        template = templates.get(item["template_id"])
        if not template:
            continue
        current = None
        if template.get("current_version_id"):
            current = question_versions.find_one({"_id": template["current_version_id"]})
        result.append(serialize_template(
            template,
            current_version=current,
            owner_username=_owner_username(template.get("owner_user_id")),
            access_type="owner" if str(template.get("owner_user_id")) == str(user_id) else "shared",
            usage_count=questions.count_documents({"template_id": template["_id"]}),
            versions_count=question_versions.count_documents({"template_id": template["_id"]}),
        ))
    return {
        "bank": _serialize_bank(bank, len(result)),
        "items": result,
    }
