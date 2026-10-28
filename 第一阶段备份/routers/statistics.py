"""
routers/statistics.py
问卷统计查询路由
调用stat_service.aggregate_survey_stat；权限校验仅问卷创建者可以访问统计
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from typing import Optional

from dependencies import get_current_user
from database import db, users, surveys, questions, jump_rules, answers
from services.survey_service import get_survey_by_id, check_survey_owner
from services.stat_service import aggregate_survey_stat

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
        doc["_id"] = str(doc["_id"])
        doc["survey_id"] = str(doc["survey_id"])
        if doc.get("submit_user_id"):
            doc["submit_user_id"] = str(doc["submit_user_id"])
        ans_list.append(doc)
    return {
        "code": 0,
        "data": ans_list
    }
