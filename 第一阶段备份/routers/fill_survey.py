"""
routers/fill_survey.py
问卷填写、答卷提交路由
根据short_id获取问卷，后端校验表单，生成快照存入answers集合
调用validate_service做校验，jump_service为跳转逻辑（渲染问卷页面使用，提交阶段不执行跳转）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from bson import ObjectId
from typing import List, Dict, Any

from dependencies import get_current_user
from database import surveys, questions, jump_rules, answers
from services.survey_service import get_survey_by_short_id, is_survey_closed
from services.validate_service import validate_answers_all, build_question_snapshot

router = APIRouter(prefix="/api/fill", tags=["问卷填写模块"])


class SubmitAnswerReq(BaseModel):
    answers: List[Dict[str, Any]]


@router.get("/survey/{short_id}", summary="获取问卷填写信息（渲染问卷页面）")
async def get_fill_survey_info(
    short_id: str,
    current_user=Depends(get_current_user)
):
    """
    根据short_id获取问卷、全部题目、跳转规则
    业务约束：必须登录；校验问卷是否发布、关闭、截止时间
    """
    survey = get_survey_by_short_id(short_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    if not survey.get("is_published"):
        raise HTTPException(status_code=403, detail="问卷尚未发布，不可填写")
    if is_survey_closed(survey):
        raise HTTPException(status_code=403, detail="问卷已关闭或已过截止时间，禁止填写")

    qs_cursor = questions.find({"survey_id": survey["_id"]})
    qs_list = []
    for q in qs_cursor:
        q["_id"] = str(q["_id"])
        q["survey_id"] = str(q["survey_id"])
        qs_list.append(q)

    jr_cursor = jump_rules.find({"survey_id": survey["_id"]})
    jr_list = []
    for r in jr_cursor:
        r["_id"] = str(r["_id"])
        r["survey_id"] = str(r["survey_id"])
        r["source_question_id"] = str(r["source_question_id"])
        r["target_question_id"] = str(r["target_question_id"])
        jr_list.append(r)

    return {
        "code": 0,
        "data": {
            "survey_id": str(survey["_id"]),
            "title": survey["title"],
            "description": survey["description"],
            "allow_anonymous": survey["allow_anonymous"],
            "is_closed": survey["is_closed"],
            "deadline": survey.get("deadline"),
            "question_list": qs_list,
            "jump_rules": jr_list
        }
    }


@router.post("/submit/{short_id}", summary="提交答卷")
async def submit_survey_answer(
    short_id: str,
    req: SubmitAnswerReq,
    current_user=Depends(get_current_user)
):
    """
    答卷提交接口
    1.校验问卷状态（发布、关闭、截止时间）
    2.validate_service执行全套后端校验
    3.校验失败返回错误列表
    4.校验通过构建question_snapshot快照写入answers集合
    MongoDB原生支持并发写入，无需额外锁即可支持多人同时提交
    """
    survey = get_survey_by_short_id(short_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    if not survey.get("is_published"):
        raise HTTPException(status_code=403, detail="问卷尚未发布，不可提交")
    if is_survey_closed(survey):
        raise HTTPException(status_code=403, detail="问卷已关闭或已过截止时间，禁止提交")

    # 获取该问卷全部题目
    question_list = list(questions.find({"survey_id": survey["_id"]}))
    # 后端完整校验用户提交答案
    error_list = validate_answers_all(question_list, req.answers)
    if len(error_list) > 0:
        return {
            "code": 400,
            "msg": "表单校验失败",
            "errors": error_list
        }

    # 校验全部通过，生成快照
    snapshot = build_question_snapshot(question_list, req.answers)
    login_user_id = current_user["_id"]

    answer_doc = {
        "survey_id": survey["_id"],
        "submit_user_id": ObjectId(login_user_id) if not survey["allow_anonymous"] else None,
        "submit_time": None,
        "question_snapshot": snapshot
    }
    from datetime import datetime
    answer_doc["submit_time"] = datetime.utcnow()

    # pymongo insert_one原生支持高并发写入，mongodb处理并发
    insert_res = answers.insert_one(answer_doc)

    return {
        "code": 0,
        "msg": "答卷提交成功",
        "data": {"answer_id": str(insert_res.inserted_id)}
    }
