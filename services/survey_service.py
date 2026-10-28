"""
services/survey_service.py
问卷业务服务层
生成short_id、问卷状态校验逻辑，所有问卷业务逻辑封装在此
"""
import random
import string
from datetime import datetime
from bson import ObjectId
from database import surveys

# short_id字符集：大小写字母+数字
SHORT_ID_CHARSET = string.ascii_letters + string.digits
SHORT_ID_LENGTH = 6


def generate_short_id() -> str:
    """
    生成全局唯一short_id，用于问卷访问url /survey/{short_id}
    循环生成，直到数据库不存在该short_id，保证唯一性
    """
    while True:
        short_id = "".join(random.choice(SHORT_ID_CHARSET) for _ in range(SHORT_ID_LENGTH))
        # 查询数据库判断是否重复
        exist = surveys.find_one({"short_id": short_id})
        if exist is None:
            return short_id


def is_survey_closed(survey_doc: dict) -> bool:
    """
    判断问卷是否不可填写：手动关闭 或者 超过截止时间
    :param survey_doc: 问卷完整文档
    :return: True代表问卷已经关闭，不允许填写；False允许填写
    """
    # 手动关闭优先
    if survey_doc.get("is_closed") is True:
        return True

    deadline = survey_doc.get("deadline")
    # 截止时间不为空，且当前时间大于截止时间
    if deadline is not None and isinstance(deadline, datetime):
        now = datetime.utcnow()
        if now > deadline:
            return True

    return False


def check_survey_owner(survey_doc: dict, login_user_id: str) -> bool:
    """
    校验登录用户是否是问卷的创建者
    :param survey_doc: 从数据库取出的问卷文档
    :param login_user_id: 当前登录用户id字符串
    :return: True为归属本人，False无权限
    """
    owner_id = str(survey_doc.get("owner_user_id"))
    return owner_id == login_user_id


def get_survey_by_short_id(short_id: str):
    """根据short_id获取问卷文档"""
    return surveys.find_one({"short_id": short_id})


def get_survey_by_id(survey_id_str: str):
    """根据survey_id字符串获取问卷文档"""
    try:
        obj_id = ObjectId(survey_id_str)
    except Exception:
        return None
    return surveys.find_one({"_id": obj_id})