"""
routers/question.py
问卷题目管理路由接口
实现题目新增、编辑、删除、查询问卷题目列表
支持题型：single_choice单选 / multi_choice多选 / text_fill文本填空 / number_fill数字填空
校验规则全部存储到MongoDB，业务代码不硬编码校验参数
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from bson import ObjectId
from typing import List, Optional, Union

from dependencies import get_current_user
from database import questions, surveys, jump_rules
from services.survey_service import get_survey_by_id, check_survey_owner
from services import question_bank_service as bank_svc
from utils import to_jsonable

router = APIRouter(prefix="/api/question", tags=["题目管理模块"])


class QuestionCreateReq(BaseModel):
    """新增题目请求模型"""
    survey_id: str
    question_title: str
    question_type: str = Field(pattern=r"^(single_choice|multi_choice|text_fill|number_fill)$")
    is_required: bool

    # 单选字段
    single_options: Optional[List[str]] = None

    # 多选字段
    multi_options: Optional[List[str]] = None
    multi_min: Optional[int] = None
    multi_max: Optional[int] = None
    multi_exact: Optional[int] = None

    # 文本填空
    text_min_len: Optional[int] = None
    text_max_len: Optional[int] = None

    # 数字填空
    num_min: Optional[Union[int, float]] = None
    num_max: Optional[Union[int, float]] = None
    num_must_int: Optional[bool] = None


class QuestionUpdateReq(BaseModel):
    """编辑题目请求模型，所有字段可选"""
    question_title: Optional[str] = None
    question_type: Optional[str] = Field(None, pattern=r"^(single_choice|multi_choice|text_fill|number_fill)$")
    is_required: Optional[bool] = None

    single_options: Optional[List[str]] = None
    multi_options: Optional[List[str]] = None
    multi_min: Optional[int] = None
    multi_max: Optional[int] = None
    multi_exact: Optional[int] = None

    text_min_len: Optional[int] = None
    text_max_len: Optional[int] = None

    num_min: Optional[Union[int, float]] = None
    num_max: Optional[Union[int, float]] = None
    num_must_int: Optional[bool] = None


class QuestionForkReq(BaseModel):
    """以现有题目为蓝本生成新题目；用于已发布问卷不能改题的场景"""
    target_survey_id: Optional[str] = None
    new_title: Optional[str] = None


@router.post("", summary="新增题目")
async def create_question(
    req: QuestionCreateReq,
    current_user=Depends(get_current_user)
):
    """
    为指定问卷新增一道题目
    权限校验：登录用户必须是问卷拥有者
    """
    # 查询问卷是否存在
    survey = get_survey_by_id(req.survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    # 校验归属权
    if not check_survey_owner(survey, current_user["_id"]):
        raise HTTPException(status_code=403, detail="无权为此问卷添加题目")

    # 第二阶段规则：已发布问卷的题目结构冻结，避免已收集数据与题目内容对不上
    if survey.get("is_published"):
        raise HTTPException(
            status_code=409,
            detail="问卷已发布，题目结构已冻结；请先取消发布，或使用题目库为新问卷创建新版本",
        )

    # 简单参数合法性校验：多选最少不能大于最多
    if req.multi_min is not None and req.multi_max is not None:
        if req.multi_min > req.multi_max:
            raise HTTPException(status_code=400, detail="多选最少选择数不能大于最多选择数")

    new_question = {
        "survey_id": ObjectId(req.survey_id),
        "question_title": req.question_title,
        "question_type": req.question_type,
        "is_required": req.is_required,

        "single_options": req.single_options,
        "multi_options": req.multi_options,
        "multi_min": req.multi_min,
        "multi_max": req.multi_max,
        "multi_exact": req.multi_exact,

        "text_min_len": req.text_min_len,
        "text_max_len": req.text_max_len,

        "num_min": req.num_min,
        "num_max": req.num_max,
        "num_must_int": req.num_must_int
    }

    # 第二阶段复用统一题目内容校验，避免题库与问卷题目出现两套标准
    try:
        bank_svc.validate_question_content(new_question)
    except bank_svc.QuestionBankError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    insert_result = questions.insert_one(new_question)
    return {
        "code": 0,
        "msg": "题目新增成功",
        "data": {"question_id": str(insert_result.inserted_id)}
    }


@router.put("/{question_id}", summary="编辑已有题目（可选择生成新版本）")
async def update_question(
    question_id: str,
    req: QuestionUpdateReq,
    create_new_version: bool = Query(
        False,
        description="为True时把本次修改记录为题目新版本；旧版本和引用旧版本的其他问卷保持不变",
    ),
    current_user=Depends(get_current_user)
):
    """
    修改题目，校验规则全部存入数据库。

    第二阶段规则：
    1. 已发布问卷的题目不可修改（返回409）；
    2. create_new_version=false：只修改当前问卷的题目副本，不影响题库和其他问卷；
    3. create_new_version=true：在题目模板上追加一个不可变版本，并让当前问卷指向新版本；
       如果该题来自别人的共享题目，则自动派生一个属于当前用户的独立题目，不修改原题。
    """
    # 查询题目
    q = questions.find_one({"_id": ObjectId(question_id)})
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    # 通过题目拿到所属问卷，校验权限
    survey_id_obj = q["survey_id"]
    survey = surveys.find_one({"_id": survey_id_obj})
    if not survey:
        raise HTTPException(status_code=404, detail="所属问卷不存在")
    if not check_survey_owner(survey, current_user["_id"]):
        raise HTTPException(status_code=403, detail="无权修改该题目")

    # 已发布问卷题目冻结
    if survey.get("is_published"):
        raise HTTPException(
            status_code=409,
            detail="问卷已发布，题目不可修改；请使用 /api/question/{question_id}/fork 生成新题目，或在题目库中创建新版本",
        )

    update_dict = req.model_dump(exclude_unset=True)

    if create_new_version:
        try:
            result = bank_svc.update_question_with_new_version(
                question_id=question_id,
                user_id=current_user["_id"],
                patch=update_dict,
                change_note="通过问卷题目编辑生成新版本",
            )
        except bank_svc.QuestionBankError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
        return {"code": 0, "msg": "题目修改成功，并已生成新版本", "data": result}

    # 普通编辑：只改当前问卷题目副本，不修改题目库中的模板
    try:
        merged = bank_svc.merge_and_validate_question(q, update_dict)
    except bank_svc.QuestionBankError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    questions.update_one({"_id": ObjectId(question_id)}, {"$set": merged})
    return {"code": 0, "msg": "题目修改成功", "data": {"question_id": question_id}}


@router.delete("/{question_id}", summary="删除题目")
async def delete_question(
    question_id: str,
    current_user=Depends(get_current_user)
):
    """
    删除题目，同时删除与此题目相关的跳转规则
    历史答卷依靠question_snapshot不受影响
    """
    q = questions.find_one({"_id": ObjectId(question_id)})
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    survey = surveys.find_one({"_id": q["survey_id"]})
    if not survey:
        raise HTTPException(status_code=404, detail="所属问卷不存在")
    if not check_survey_owner(survey, current_user["_id"]):
        raise HTTPException(status_code=403, detail="无权删除该题目")

    # 已发布问卷题目冻结
    if survey.get("is_published"):
        raise HTTPException(
            status_code=409,
            detail="问卷已发布，题目不可删除；历史答卷依靠快照保留，如需调整请新建问卷",
        )

    # 删除该题目相关所有跳转规则：源题目为此id，或者目标题目为此id
    jump_rules.delete_many({
        "$or": [
            {"source_question_id": ObjectId(question_id)},
            {"target_question_id": ObjectId(question_id)}
        ]
    })
    # 删除题目本身
    questions.delete_one({"_id": ObjectId(question_id)})
    return {"code": 0, "msg": "题目以及关联跳转规则已删除"}


@router.post("/{question_id}/fork", summary="以现有题目为蓝本生成新题目（不修改原题）")
async def fork_question(
    question_id: str,
    req: QuestionForkReq,
    current_user=Depends(get_current_user)
):
    """
    第二阶段新增：复制/派生题目。
    典型用途：
    - 问卷已经发布，不能直接改题，但可以为下一份问卷生成一道新题目；
    - 要把旧问卷中的题目拿到新问卷中复用。
    原题、原问卷、原答卷快照都不会被修改。
    """
    try:
        result = bank_svc.fork_question_to_survey(
            source_question_id=question_id,
            user_id=current_user["_id"],
            target_survey_id=req.target_survey_id,
            new_title=req.new_title,
        )
    except bank_svc.QuestionBankError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return {"code": 0, "msg": "新题目生成成功", "data": result}


@router.get("/list/{survey_id}", summary="获取问卷全部题目列表")
async def list_question(
    survey_id: str,
    current_user=Depends(get_current_user)
):
    """获取问卷下所有题目，返回完整校验配置字段"""
    survey = get_survey_by_id(survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    cursor = questions.find({"survey_id": ObjectId(survey_id)})
    result_list = []
    for item in cursor:
        result_list.append(to_jsonable(item))
    return {
        "code": 0,
        "data": result_list
    }