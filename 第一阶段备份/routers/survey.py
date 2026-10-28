"""
routers/survey.py
问卷CRUD路由接口
接收http请求，调用survey_service业务函数，不写复杂业务逻辑
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from bson import ObjectId

from dependencies import get_current_user
from database import surveys
from services.survey_service import (
    generate_short_id,
    is_survey_closed,
    check_survey_owner,
    get_survey_by_id
)

router = APIRouter(prefix="/api/survey", tags=["问卷管理模块"])


# ---------------------- 请求模型 ----------------------
class SurveyCreateReq(BaseModel):
    title: str
    description: str = ""
    allow_anonymous: bool = False
    deadline: datetime | None = None


class SurveyUpdateReq(BaseModel):
    title: str | None = None
    description: str | None = None
    allow_anonymous: bool | None = None
    deadline: datetime | None = None


class SurveyPublishReq(BaseModel):
    is_published: bool


class SurveyCloseReq(BaseModel):
    is_closed: bool


# ---------------------- 接口 ----------------------
@router.post("", summary="创建问卷")
async def create_survey(
    req: SurveyCreateReq,
    current_user=Depends(get_current_user)
):
    """登录用户创建问卷，自动生成唯一short_id，归属当前登录用户"""
    login_user_id = current_user["_id"]

    short_id = generate_short_id()
    new_survey = {
        "owner_user_id": ObjectId(login_user_id),
        "title": req.title,
        "description": req.description,
        "allow_anonymous": req.allow_anonymous,
        "is_published": False,
        "is_closed": False,
        "deadline": req.deadline,
        "short_id": short_id
    }
    res = surveys.insert_one(new_survey)

    return {
        "code": 0,
        "msg": "问卷创建成功",
        "data": {
            "survey_id": str(res.inserted_id),
            "short_id": short_id,
            "access_url": f"/survey/{short_id}",
            "is_published": False,
            "is_closed": False
        }
    }


@router.get("/my", summary="获取我创建的问卷列表")
async def get_my_surveys(current_user=Depends(get_current_user)):
    """仅返回当前登录用户自己创建的问卷"""
    login_user_id = current_user["_id"]
    cursor = surveys.find({"owner_user_id": ObjectId(login_user_id)})
    survey_list = []
    for item in cursor:
        survey_list.append({
            "survey_id": str(item["_id"]),
            "title": item["title"],
            "short_id": item["short_id"],
            "is_published": item["is_published"],
            "is_closed": item["is_closed"],
            "deadline": item.get("deadline")
        })
    return {"code": 0, "msg": "ok", "data": survey_list}


@router.put("/{survey_id}", summary="修改问卷基础信息")
async def update_survey(
    survey_id: str,
    req: SurveyUpdateReq,
    current_user=Depends(get_current_user)
):
    survey = get_survey_by_id(survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    # 权限校验：只能修改自己的问卷
    if not check_survey_owner(survey, current_user["_id"]):
        raise HTTPException(status_code=403, detail="无权操作该问卷")

    update_data = req.model_dump(exclude_unset=True)
    surveys.update_one({"_id": ObjectId(survey_id)}, {"$set": update_data})
    return {"code": 0, "msg": "问卷修改成功"}


@router.patch("/{survey_id}/publish", summary="发布/取消发布问卷")
async def publish_survey(
    survey_id: str,
    req: SurveyPublishReq,
    current_user=Depends(get_current_user)
):
    survey = get_survey_by_id(survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    if not check_survey_owner(survey, current_user["_id"]):
        raise HTTPException(status_code=403, detail="无权操作该问卷")

    surveys.update_one(
        {"_id": ObjectId(survey_id)},
        {"$set": {"is_published": req.is_published}}
    )
    return {"code": 0, "msg": "发布状态更新成功"}


@router.patch("/{survey_id}/close", summary="关闭问卷")
async def close_survey(
    survey_id: str,
    req: SurveyCloseReq,
    current_user=Depends(get_current_user)
):
    survey = get_survey_by_id(survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    if not check_survey_owner(survey, current_user["_id"]):
        raise HTTPException(status_code=403, detail="无权操作该问卷")

    surveys.update_one(
        {"_id": ObjectId(survey_id)},
        {"$set": {"is_closed": req.is_closed}}
    )
    return {"code": 0, "msg": "问卷关闭状态更新成功"}


@router.delete("/{survey_id}", summary="删除问卷")
async def delete_survey(
    survey_id: str,
    current_user=Depends(get_current_user)
):
    """
    删除问卷；注意：业务层需要级联删除questions、jump_rules，保留answers答卷
    本路由仅做权限校验，级联清理逻辑后续可在service层封装
    """
    survey = get_survey_by_id(survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    if not check_survey_owner(survey, current_user["_id"]):
        raise HTTPException(status_code=403, detail="无权操作该问卷")

    surveys.delete_one({"_id": ObjectId(survey_id)})
    return {"code": 0, "msg": "问卷已删除"}
