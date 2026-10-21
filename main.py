"""
main.py
FastAPI项目入口文件
启动项目，注册全部路由，初始化MongoDB连接，配置全局异常捕获
启动命令：python -m uvicorn main:app --reload
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# 导入database模块，执行pymongo连接初始化；调用索引初始化函数
import database

# 导入各个路由模块
from routers import user, survey, question, fill_survey, statistics

# 创建FastAPI实例
app = FastAPI(
    title="MongoDB问卷系统-阶段一",
    description="课程大作业，基于FastAPI + MongoDB实现在线问卷系统",
    version="1.0.0"
)

# 项目启动时初始化数据库索引，只执行一次
database.init_indexes()


# 全局异常处理器，捕获服务端未知异常，统一返回json格式
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局未捕获异常处理，避免直接返回原生堆栈给前端"""
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "msg": f"服务器内部错误：{str(exc)}",
            "data": None
        }
    )


# 注册全部业务路由
app.include_router(user.router)
app.include_router(survey.router)
app.include_router(question.router)
app.include_router(fill_survey.router)
app.include_router(statistics.router)


@app.get("/")
async def root():
    """根路径测试接口"""
    return {
        "code": 0,
        "msg": "问卷系统服务运行正常",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
