"""
routers/question_bank.py

第二阶段新增：题目库 / 题目版本 / 题目共享路由。
本层只负责 HTTP 参数解析、权限入口和异常转换，核心逻辑在 services/question_bank_service.py。
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from dependencies import get_current_user
from services import question_bank_service as svc

router = APIRouter(prefix="/api/question_bank", tags=["题库与题目版本模块"])

QUESTION_TYPE_PATTERN = r"^(single_choice|multi_choice|text_fill|number_fill)$"


# ============================== 请求模型 ==============================
class QuestionContentCreateReq(BaseModel):
    question_title: str
    question_type: str = Field(pattern=QUESTION_TYPE_PATTERN)
    is_required: bool = False

    single_options: Optional[List[str]] = None

    multi_options: Optional[List[str]] = None
    multi_min: Optional[int] = None
    multi_max: Optional[int] = None
    multi_exact: Optional[int] = None

    text_min_len: Optional[int] = None
    text_max_len: Optional[int] = None

    num_min: Optional[float] = None
    num_max: Optional[float] = None
    num_must_int: Optional[bool] = None


class TemplateCreateReq(QuestionContentCreateReq):
    bank_id: Optional[str] = None
    change_note: str = "初始版本"


class TemplateVersionReq(BaseModel):
    question_title: Optional[str] = None
    question_type: Optional[str] = Field(None, pattern=QUESTION_TYPE_PATTERN)
    is_required: Optional[bool] = None

    single_options: Optional[List[str]] = None

    multi_options: Optional[List[str]] = None
    multi_min: Optional[int] = None
    multi_max: Optional[int] = None
    multi_exact: Optional[int] = None

    text_min_len: Optional[int] = None
    text_max_len: Optional[int] = None

    num_min: Optional[float] = None
    num_max: Optional[float] = None
    num_must_int: Optional[bool] = None

    change_note: str = ""


class ShareReq(BaseModel):
    target_username: str
    can_use: bool = True


class AddToSurveyReq(BaseModel):
    survey_id: str
    version_id: Optional[str] = None
    bank_id: Optional[str] = None


class ForkTemplateReq(BaseModel):
    version_id: Optional[str] = None
    title: Optional[str] = None


# ============================== 异常转换 ==============================
def _call(func, *args, **kwargs):
    """执行业务函数，把业务异常转换为 HTTPException。"""
    try:
        return func(*args, **kwargs)
    except svc.QuestionBankError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


# ============================== 题目模板 / 版本 ==============================
@router.post("/templates", summary="新建题目并保存到题目库（自动生成v1版本）")
async def create_template(
    req: TemplateCreateReq,
    current_user=Depends(get_current_user),
):
    content = req.model_dump(exclude_unset=True, exclude={"bank_id", "change_note"})
    template_id, version_id = _call(
        svc.create_template,
        current_user["_id"],
        content,
        bank_id=req.bank_id,
        change_note=req.change_note,
    )
    detail = _call(svc.get_template_detail, template_id, current_user["_id"])
    return {
        "code": 0,
        "msg": "题目创建成功",
        "data": {
            "template_id": template_id,
            "version_id": version_id,
            "template": detail,
        },
    }


@router.get("/templates", summary="查看我可用的题目（我创建的/共享给我的/全部）")
async def list_templates(
    scope: str = Query("all", pattern=r"^(mine|shared|all)$", description="mine=我创建的，shared=共享给我的，all=全部"),
    current_user=Depends(get_current_user),
):
    data = _call(svc.list_templates_for_user, current_user["_id"], scope)
    return {"code": 0, "msg": "ok", "data": data}


@router.get("/templates/{template_id}", summary="查看题目详情及全部历史版本")
async def get_template(
    template_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.get_template_detail, template_id, current_user["_id"])
    return {"code": 0, "msg": "ok", "data": data}


@router.get("/templates/{template_id}/versions", summary="查看题目版本历史（v1→v2→v3）")
async def get_template_versions(
    template_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.get_version_history, template_id, current_user["_id"])
    return {"code": 0, "msg": "ok", "data": data}


@router.post("/templates/{template_id}/versions", summary="创建题目新版本（不影响旧版本和旧问卷）")
async def create_template_version(
    template_id: str,
    req: TemplateVersionReq,
    current_user=Depends(get_current_user),
):
    patch = req.model_dump(exclude_unset=True, exclude={"change_note"})
    data = _call(
        svc.create_new_version,
        template_id,
        current_user["_id"],
        patch,
        req.change_note,
    )
    return {"code": 0, "msg": "新版本创建成功", "data": data}


@router.post("/templates/{template_id}/restore/{version_id}", summary="恢复历史版本（生成一个新版本，不删除历史）")
async def restore_template_version(
    template_id: str,
    version_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.restore_version, template_id, version_id, current_user["_id"])
    return {"code": 0, "msg": "旧版本已恢复为新版本", "data": data}


@router.post("/templates/{template_id}/fork", summary="基于某题派生一个属于当前用户的新题目")
async def fork_template(
    template_id: str,
    req: ForkTemplateReq,
    current_user=Depends(get_current_user),
):
    new_template_id, new_version_id = _call(
        svc.fork_template,
        template_id,
        current_user["_id"],
        req.version_id,
        req.title,
    )
    detail = _call(svc.get_template_detail, new_template_id, current_user["_id"])
    return {
        "code": 0,
        "msg": "题目派生成功",
        "data": {
            "template_id": new_template_id,
            "version_id": new_version_id,
            "template": detail,
        },
    }


@router.delete("/templates/{template_id}", summary="从题目库删除题目（软删除，问卷副本不受影响）")
async def delete_template(
    template_id: str,
    force: bool = Query(False, description="仍被问卷使用时是否强制从题库移除"),
    current_user=Depends(get_current_user),
):
    data = _call(svc.delete_template, template_id, current_user["_id"], force)
    return {"code": 0, "msg": "题目已从题库删除", "data": data}


# ============================== 共享 ==============================
@router.post("/templates/{template_id}/share", summary="把题目共享给其他用户")
async def share_template(
    template_id: str,
    req: ShareReq,
    current_user=Depends(get_current_user),
):
    data = _call(
        svc.share_template,
        template_id,
        current_user["_id"],
        req.target_username,
        req.can_use,
    )
    return {"code": 0, "msg": "题目共享成功", "data": data}


@router.get("/templates/{template_id}/shares", summary="查看题目的共享名单")
async def list_template_shares(
    template_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.list_shares, template_id, current_user["_id"])
    return {"code": 0, "msg": "ok", "data": data}


@router.delete("/templates/{template_id}/shares/{target_user_id}", summary="取消题目共享")
async def revoke_template_share(
    template_id: str,
    target_user_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.revoke_share, template_id, current_user["_id"], target_user_id)
    return {"code": 0, "msg": "共享已取消", "data": data}


# ============================== 问卷使用 ==============================
@router.get("/templates/{template_id}/usage", summary="查看题目被哪些问卷使用（含使用版本）")
async def template_usage(
    template_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.get_template_usage, template_id, current_user["_id"])
    return {"code": 0, "msg": "ok", "data": data}


@router.post("/templates/{template_id}/add_to_survey", summary="从题目库选择题目加入问卷")
async def add_template_to_survey(
    template_id: str,
    req: AddToSurveyReq,
    current_user=Depends(get_current_user),
):
    data = _call(
        svc.add_template_to_survey,
        req.survey_id,
        template_id,
        current_user["_id"],
        req.version_id,
        req.bank_id,
    )
    return {"code": 0, "msg": "题目已加入问卷", "data": data}
