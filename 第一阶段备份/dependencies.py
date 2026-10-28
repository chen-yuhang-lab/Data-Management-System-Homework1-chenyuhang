"""
dependencies.py 依赖项
JWT鉴权依赖 get_current_user，用于接口权限保护
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from bson import ObjectId

from config import JWT_SECRET_KEY, JWT_ALGORITHM
from database import users

# token从请求头 Authorization: Bearer xxx 获取
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/user/login")


def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    JWT鉴权依赖函数
    返回当前登录用户字典；未登录/非法token抛出401
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="token无效或者已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    # 查询数据库用户
    user = users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise credentials_exception
    # 把 _id转字符串方便后续使用
    user["_id"] = str(user["_id"])
    return user
