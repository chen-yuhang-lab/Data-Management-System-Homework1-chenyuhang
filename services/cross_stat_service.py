"""
services/cross_stat_service.py

第二阶段新增：单题跨问卷统计。
用途：同一个题目模板被多份问卷复用后，创建者可以查看该题在所有问卷中的总体分布。

兼容第一阶段数据：
- 新答卷的快照同时保存 template_id / version_id / question_id；
- 第一阶段旧答卷没有 template_id，因此同时按“该模板对应的所有问卷题目实例 _id”匹配；
- 迁移脚本可以把旧答卷补上 template_id / version_id，之后查询会更快。
"""
from typing import Any, Dict, List, Optional

from bson import ObjectId

from database import answers, question_templates, question_versions, questions


def _oid(value: Any) -> Optional[ObjectId]:
    if value in (None, ""):
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_values(values: List[Any]) -> List[Any]:
    return [v for v in values if v is not None and v != "" and v != []]


def _calc_stat(question_type: str, values: List[Any], options: Optional[List[str]] = None) -> Dict[str, Any]:
    """对一组答案做题型相关统计；选项题会把未选选项也补成0，便于前端画图。"""
    vals = _valid_values(values)
    total_answer = len(vals)

    if question_type == "single_choice":
        option_count: Dict[str, int] = {opt: 0 for opt in (options or [])}
        for v in vals:
            if isinstance(v, str):
                option_count[v] = option_count.get(v, 0) + 1
        option_percent = {
            k: round(v / total_answer * 100, 2) if total_answer else 0
            for k, v in option_count.items()
        }
        return {
            "total_answer": total_answer,
            "option_count": option_count,
            "option_percent": option_percent,
        }

    if question_type == "multi_choice":
        option_count: Dict[str, int] = {opt: 0 for opt in (options or [])}
        for v in vals:
            if isinstance(v, list):
                for opt in set(v):
                    option_count[opt] = option_count.get(opt, 0) + 1
        option_percent = {
            k: round(v / total_answer * 100, 2) if total_answer else 0
            for k, v in option_count.items()
        }
        return {
            "total_answer": total_answer,
            "option_count": option_count,
            "option_percent": option_percent,
        }

    if question_type == "number_fill":
        num_list = []
        for v in vals:
            if _is_number(v):
                num_list.append(float(v))
            else:
                try:
                    num_list.append(float(v))
                except (TypeError, ValueError):
                    continue
        if not num_list:
            return {
                "total_answer": total_answer,
                "count": 0,
                "avg": None,
                "min": None,
                "max": None,
            }
        return {
            "total_answer": total_answer,
            "count": len(num_list),
            "avg": round(sum(num_list) / len(num_list), 4),
            "min": min(num_list),
            "max": max(num_list),
        }

    # text_fill 或未知题型：返回原始文本，方便人工查看
    return {
        "total_answer": total_answer,
        "raw_text": vals,
    }


def aggregate_question_across_surveys(
    template_id: str,
    version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    返回：
      - 题目基本信息、总体统计 overall；
      - 按问卷拆分的统计 by_survey；
      - total_submit：包含该题作答的答卷数（按 answers._id 去重）。
    """
    template_oid = _oid(template_id)
    if not template_oid:
        return None
    template = question_templates.find_one({"_id": template_oid, "is_deleted": {"$ne": True}})
    if not template:
        return None

    version_oid = _oid(version_id) if version_id else None
    target_version = None
    if version_oid:
        target_version = question_versions.find_one({"_id": version_oid, "template_id": template_oid})
        if not target_version:
            return None
    else:
        if template.get("current_version_id"):
            target_version = question_versions.find_one({"_id": template["current_version_id"]})

    question_type = (target_version or {}).get("question_type") or template.get("question_type")
    question_title = (target_version or {}).get("question_title") or template.get("title")
    question_options = (target_version or {}).get("single_options") or (target_version or {}).get("multi_options") or []

    # 找出所有引用了该模板（以及指定版本）的问卷题目实例
    instance_query: Dict[str, Any] = {"template_id": template_oid}
    if version_oid:
        instance_query["version_id"] = version_oid
    instances = list(questions.find(
        instance_query,
        {"_id": 1, "survey_id": 1, "version_id": 1, "version_no": 1},
    ))
    instance_ids = [q["_id"] for q in instances]
    survey_ids = list({q["survey_id"] for q in instances})

    if not instances:
        return {
            "template_id": str(template_oid),
            "question_title": question_title,
            "question_type": question_type,
            "version_filter": str(version_oid) if version_oid else None,
            "total_submit": 0,
            "total_answer": 0,
            "overall": _calc_stat(question_type, [], question_options),
            "by_survey": [],
            "matched_question_instances": 0,
        }

    # 新数据用 snapshot.template_id 匹配；旧数据用 snapshot.question_id 匹配
    or_conditions: List[Dict[str, Any]] = [
        {"question_snapshot.template_id": template_oid},
    ]
    if instance_ids:
        or_conditions.append({"question_snapshot.question_id": {"$in": instance_ids}})

    match_snapshot: Dict[str, Any] = {"$or": or_conditions}
    if version_oid:
        match_snapshot["question_snapshot.version_id"] = version_oid

    pipeline = [
        {"$match": {"survey_id": {"$in": survey_ids}}},
        {"$unwind": "$question_snapshot"},
        {"$match": match_snapshot},
        {"$group": {
            "_id": "$survey_id",
            "answer_ids": {"$addToSet": "$_id"},
            "answer_values": {"$push": "$question_snapshot.user_answer"},
            "versions": {"$addToSet": "$question_snapshot.version_no"},
        }},
        {"$lookup": {
            "from": "surveys",
            "localField": "_id",
            "foreignField": "_id",
            "as": "survey",
        }},
        {"$unwind": {"path": "$survey", "preserveNullAndEmptyArrays": True}},
        {"$sort": {"survey.title": 1}},
    ]
    rows = list(answers.aggregate(pipeline))

    all_values: List[Any] = []
    by_survey: List[Dict[str, Any]] = []
    total_submit = 0
    for row in rows:
        values = row.get("answer_values", [])
        all_values.extend(values)
        total_submit += len(row.get("answer_ids", []))
        survey = row.get("survey") or {}
        by_survey.append({
            "survey_id": str(row["_id"]),
            "survey_title": survey.get("title"),
            "owner_user_id": str(survey.get("owner_user_id")) if survey.get("owner_user_id") else None,
            "is_published": survey.get("is_published", False),
            "is_closed": survey.get("is_closed", False),
            "submit_count": len(row.get("answer_ids", [])),
            "versions": sorted(v for v in row.get("versions", []) if v is not None),
            "stat": _calc_stat(question_type, values, question_options),
        })

    overall = _calc_stat(question_type, all_values, question_options)
    return {
        "template_id": str(template_oid),
        "question_title": question_title,
        "question_type": question_type,
        "version_filter": str(version_oid) if version_oid else None,
        "total_submit": total_submit,
        "total_answer": overall.get("total_answer", 0),
        "overall": overall,
        "by_survey": by_survey,
        "matched_question_instances": len(instances),
    }
