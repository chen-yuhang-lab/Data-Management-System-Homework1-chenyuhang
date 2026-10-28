"""
models.py
本文件：公共Pydantic模型与类型定义
说明：因快速开发，业务请求模型暂时内联写在各个routers路由文件中，不做迁移，避免改动已有代码。
本文件存放项目通用返回结构体、常量、类型别名，消除空文件，满足作业目录要求。
"""
from pydantic import BaseModel
from typing import Any, Optional, Dict, List

# -------------------------- 通用API统一返回模型 --------------------------
class CommonResponse(BaseModel):
    """项目全局统一JSON返回格式模型"""
    code: int
    msg: str
    data: Optional[Any] = None


# -------------------------- 常量枚举定义 --------------------------
class QuestionTypeEnum:
    """题目类型常量枚举，与数据库question_type字段保持一致"""
    SINGLE_CHOICE = "single_choice"    # 单选
    MULTI_CHOICE = "multi_choice"      # 多选
    TEXT_FILL = "text_fill"            # 文本填空
    NUMBER_FILL = "number_fill"        # 数字填空


class JumpRuleTypeEnum:
    """跳转规则类型枚举，和jump_rules集合rule_type字段对应"""
    SINGLE_EQUAL = "single_equal"
    MULTI_CONTAINS = "multi_contains"
    NUMBER_GT = "number_gt"
    NUMBER_LT = "number_lt"
    NUMBER_EQ = "number_eq"


# -------------------------- 类型别名 --------------------------
AnswerItem = Dict[str, Any]
AnswerList = List[AnswerItem]
