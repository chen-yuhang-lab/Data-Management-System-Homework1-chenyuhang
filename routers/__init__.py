"""
routers/__init__.py
路由模块包初始化文件
导出各个路由模块，供main.py导入使用

第二阶段新增：question_bank（题目版本/共享）、bank（题库管理）
"""
from . import user
from . import survey
from . import question
from . import fill_survey
from . import statistics
from . import question_bank
from . import bank

__all__ = [
    "user",
    "survey",
    "question",
    "fill_survey",
    "statistics",
    "question_bank",
    "bank",
]
