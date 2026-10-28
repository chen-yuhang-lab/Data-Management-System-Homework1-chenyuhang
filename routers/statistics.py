"""
routers/statistics.py
问卷统计查询路由
调用stat_service.aggregate_survey_stat；权限校验仅问卷创建者可以访问统计
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from typing import Optional

from dependencies import get_current_user
from database import db, users, surveys, questions, jump_rules, answers, question_templates, question_versions
from services.survey_service import get_survey_by_id, check_survey_owner
from services.stat_service import aggregate_survey_stat
from services.cross_stat_service import aggregate_question_across_surveys
from utils import to_jsonable

router = APIRouter(prefix="/api/statistics", tags=["问卷统计模块"])


@router.get("/survey/{survey_id}", summary="获取问卷统计结果，可指定question_id做单题统计")
async def get_survey_statistics(
    survey_id: str,
    question_id: Optional[str] = Query(None, description="可选，传入则只统计该题目"),
    current_user=Depends(get_current_user)
):
    """
    获取问卷统计
    权限：仅问卷创建者允许访问
    """
    survey = get_survey_by_id(survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    # 权限校验：只有问卷所有者可以查看统计
    if not check_survey_owner(survey, current_user["_id"]):
        raise HTTPException(status_code=403, detail="无权查看该问卷统计")

    stat_result = aggregate_survey_stat(survey_id, filter_question_id=question_id)
    return {
        "code": 0,
        "data": stat_result
    }


@router.get("/answers/{survey_id}", summary="获取问卷全部原始答卷列表（含快照）")
async def get_all_raw_answers(
    survey_id: str,
    current_user=Depends(get_current_user)
):
    """返回完整原始答卷数据，包含question_snapshot快照，仅创建者可读"""
    survey = get_survey_by_id(survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    if not check_survey_owner(survey, current_user["_id"]):
        raise HTTPException(status_code=403, detail="无权查看答卷")

    cursor = answers.find({"survey_id": ObjectId(survey_id)})
    ans_list = []
    for doc in cursor:
        ans_list.append(to_jsonable(doc))
    return {
        "code": 0,
        "data": ans_list
    }


@router.get("/question/{template_id}", summary="单题跨问卷统计（同一道题在所有问卷中的回答情况）")
async def get_question_cross_statistics(
    template_id: str,
    version_id: Optional[str] = Query(None, description="可选，只统计某个版本；不传则统计该题全部版本"),
    current_user=Depends(get_current_user)
):
    """
    第二阶段新增：跨问卷统计。
    只有题目创建者可以查看；被共享用户只能使用题目，不能查看所有问卷的汇总数据。
    """
    try:
        template_oid = ObjectId(template_id)
    except Exception:
        raise HTTPException(status_code=400, detail="题目ID格式错误")

    template = question_templates.find_one({"_id": template_oid, "is_deleted": {"$ne": True}})
    if not template:
        raise HTTPException(status_code=404, detail="题目不存在")
    if str(template.get("owner_user_id")) != current_user["_id"]:
        raise HTTPException(status_code=403, detail="只有题目创建者可以查看跨问卷统计")

    if version_id:
        try:
            version_oid = ObjectId(version_id)
        except Exception:
            raise HTTPException(status_code=400, detail="版本ID格式错误")
        version = question_versions.find_one({"_id": version_oid, "template_id": template_oid})
        if not version:
            raise HTTPException(status_code=404, detail="题目版本不存在")

    stat_result = aggregate_question_across_surveys(template_id, version_id=version_id)
    return {
        "code": 0,
        "data": stat_result
    }