# README.md

# 基于FastAPI + MongoDB的在线问卷系统（阶段一）

## 1. 项目简介

本项目是实现简化版在线问卷系统。

主要功能：用户注册登录、创建管理问卷、支持单选/多选/文本填空/数字填空题型、配置数据库驱动的题目跳转逻辑、问卷填写提交、答卷自动快照保存、问卷结果统计。



技术栈：

- 后端框架：Python FastAPI

- 数据库：MongoDB

- 鉴权：JWT

- 密码加密：bcrypt



## 2. 目录结构说明

```
survey_system/
├── main.py                # 项目入口，注册全部路由、全局异常处理

├── config.py              # 配置：MongoDB连接、JWT密钥、过期时间

├── database.py            # MongoDB连接初始化、集合导出、索引初始化函数

├── schemas.py             # MongoDB集合设计文档（字典+注释，仅设计说明，非执行schema）

├── dependencies.py        # JWT鉴权依赖 get_current_user

├── requirements.txt       # python依赖包

├── routers/               # 路由层，只处理http请求，薄路由

│   ├── __init__.py

│   ├── user.py            # 用户注册登录接口

│   ├── survey.py          # 问卷CRUD接口

│   ├── question.py        # 题目增删改查接口

│   ├── fill_survey.py     # 问卷填写、答卷提交接口

│   └── statistics.py      # 统计查询接口

├── services/              # 业务逻辑层，核心业务代码

│   ├── __init__.py

│   ├── survey_service.py  # short_id生成、问卷状态、归属校验

│   ├── jump_service.py    # 问卷跳转逻辑业务函数

│   ├── validate_service.py# 答卷表单全套校验、快照生成

│   └── stat_service.py    # MongoDB聚合管道统计业务

├── test_cases.md          # 测试用例文档

└── README.md              # 本说明文档

```

## 3. 
本项目采用FastAPI内置Swagger UI作为系统交互入口，不再额外开发独立前端页面。

其他用户在同一局域网内，访问http://本机IP:8000/docs接口文档页面，即可调用问卷创建、题目添加、答卷提交、结果统计等接口，完成问卷填写与查看统计。

所有业务逻辑（答案校验、题目跳转、数据存储、统计聚合）均由后端实现，数据持久化存储在 MongoDB。

步骤：

开窗口1：管理员CMD（专门跑MongoDB，一直开着）

输入MongoDB启动命令：

mongod --dbpath D:\mongodb_data

这个窗口全程不能关，一关数据库就停了。

再开窗口2：普通CMD（普通权限，跑FastAPI项目）

先cd进入项目survey_system文件夹

cd C:\Users\86156\Desktop\数据系统大作业第一阶段\survey_system

安装依赖

python -m pip install fastapi uvicorn pymongo bcrypt pyjwt pydantic

启动后端服务

python -m uvicorn main:app --reload

浏览器打开 http://127.0.0.1:8000/docs 测试接口

服务默认监听：`http://127.0.0.1:8000`

## 4. 数据库索引创建说明

索引不需要手动在MongoDB shell执行。

项目启动时，`main.py`会调用`database.init_indexes()`函数，自动创建全部必要索引：

1. `users`集合：`username`唯一索引，防止用户名重复注册

2. `surveys`集合：`short_id`唯一索引；`owner_user_id`普通索引

3. `questions`集合：`survey_id`索引

4. `jump_rules`集合：`survey_id`、`source_question_id`索引

5. `answers`集合：`survey_id`、`submit_user_id`索引

> 索引作用：加快查询速度；保证short_id、username全局唯一。

> 如果数据库已经存在旧数据，重复调用`init_indexes()`不会报错。

## 5. API访问地址说明

1. 根地址：`http://127.0.0.1:8000`

2. FastAPI自动交互式接口文档（测试接口首选）：

    - Swagger文档：`http://127.0.0.1:8000/docs`

3. API统一前缀：

    - 用户模块：`/api/user`

    - 问卷管理：`/api/survey`

    - 题目管理：`/api/question`

    - 跳转规则：`/api/jump_rule`

    - 问卷填写提交：`/api/fill`

    - 统计查询：`/api/statistics`

4. 问卷对外访问url示例：`/survey/a8k2f9`，后端对应接口`/api/fill/survey/{short_id}`