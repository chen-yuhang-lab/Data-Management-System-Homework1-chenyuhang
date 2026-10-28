"""
routers/user.py 用户注册、登录路由
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import bcrypt
from datetime import datetime, timedelta
import jwt
from fastapi import APIRouter, Form, HTTPException
from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES
from database import users

router = APIRouter(prefix="/api/user", tags=["用户账号模块"])


# 请求体模型
class RegisterReq(BaseModel):
    username: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    """生成JWT token工具函数"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


@router.post("/register")
async def register(req: RegisterReq):
    """用户注册接口，密码bcrypt哈希存储，校验用户名不能重复"""
    # 判断用户名是否存在
    exist_user = users.find_one({"username": req.username})
    if exist_user:
        raise HTTPException(status_code=400, detail="用户名已存在")

    # bcrypt加密密码
    password_bytes = req.password.encode("utf-8")
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password_bytes, salt)

    new_user = {
        "username": req.username,
        "password_hash": password_hash,
        "register_time": datetime.utcnow()
    }
    result = users.insert_one(new_user)
    return {
        "code": 0,
        "msg": "注册成功",
        "data": {
            "user_id": str(result.inserted_id),
            "username": req.username
        }
    }


@router.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...)
):
    """用户登录接口，表单接收账号密码，适配Swagger OAuth弹窗，返回JWT token"""
    user = users.find_one({"username": username})
    if not user:
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    # 校验密码哈希
    input_pwd_bytes = password.encode("utf-8")
    if not bcrypt.checkpw(input_pwd_bytes, user["password_hash"]):
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    # 生成token
    access_token_expires = timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user["_id"])}, expires_delta=access_token_expires
    )
    # 注意：OAuth2弹窗要求返回格式必须包含 access_token、token_type
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "code": 0,
        "msg": "登录成功",
        "data": {
            "token": access_token,
            "user_id": str(user["_id"]),
            "username": user["username"]
        }
    }
