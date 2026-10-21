"""
routers/__init__.py
路由模块包初始化文件
导出各个路由模块，供main.py导入使用
"""
from . import user
from . import survey
from . import question
from . import fill_survey
from . import statistics

__all__ = ["user", "survey", "question", "fill_survey", "statistics"]