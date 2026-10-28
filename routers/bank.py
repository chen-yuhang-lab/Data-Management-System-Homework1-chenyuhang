"""
routers/bank.py

第二阶段新增：题库管理路由。
题库用于把常用题目归类，创建问卷时可以从题库中直接选题。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dependencies import get_current_user
from services import question_bank_service as svc

router = APIRouter(prefix="/api/bank", tags=["题库管理模块"])


class BankCreateReq(BaseModel):
    name: str
    description: str = ""
    is_public: bool = False


class BankUpdateReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None


class BankItemAddReq(BaseModel):
    template_id: str


def _call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except svc.QuestionBankError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("", summary="创建题库")
async def create_bank(
    req: BankCreateReq,
    current_user=Depends(get_current_user),
):
    data = _call(
        svc.create_bank,
        current_user["_id"],
        req.name,
        req.description,
        req.is_public,
    )
    return {"code": 0, "msg": "题库创建成功", "data": data}


@router.get("/my", summary="查看我创建的题库")
async def list_my_banks(current_user=Depends(get_current_user)):
    data = _call(svc.list_banks, current_user["_id"])
    return {"code": 0, "msg": "ok", "data": data}


@router.get("/public", summary="查看公开题库")
async def list_public_banks(current_user=Depends(get_current_user)):
    data = _call(svc.list_banks, current_user["_id"], public_only=True)
    return {"code": 0, "msg": "ok", "data": data}


@router.get("/{bank_id}", summary="查看题库详情")
async def get_bank(
    bank_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.get_bank_detail, bank_id, current_user["_id"])
    return {"code": 0, "msg": "ok", "data": data}


@router.put("/{bank_id}", summary="修改题库信息")
async def update_bank(
    bank_id: str,
    req: BankUpdateReq,
    current_user=Depends(get_current_user),
):
    patch = req.model_dump(exclude_unset=True)
    data = _call(svc.update_bank, bank_id, current_user["_id"], patch)
    return {"code": 0, "msg": "题库修改成功", "data": data}


@router.delete("/{bank_id}", summary="删除题库（只删除题库和题目关联，不删除题目本身）")
async def delete_bank(
    bank_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.delete_bank, bank_id, current_user["_id"])
    return {"code": 0, "msg": "题库已删除", "data": data}


@router.post("/{bank_id}/items", summary="把题目加入题库")
async def add_bank_item(
    bank_id: str,
    req: BankItemAddReq,
    current_user=Depends(get_current_user),
):
    data = _call(svc.add_template_to_bank, bank_id, req.template_id, current_user["_id"])
    return {"code": 0, "msg": "题目已加入题库", "data": data}


@router.get("/{bank_id}/items", summary="查看题库中的题目")
async def list_bank_items(
    bank_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.list_bank_items, bank_id, current_user["_id"])
    return {"code": 0, "msg": "ok", "data": data}


@router.delete("/{bank_id}/items/{template_id}", summary="从题库移除题目")
async def remove_bank_item(
    bank_id: str,
    template_id: str,
    current_user=Depends(get_current_user),
):
    data = _call(svc.remove_template_from_bank, bank_id, template_id, current_user["_id"])
    return {"code": 0, "msg": "题目已从题库移除", "data": data}
