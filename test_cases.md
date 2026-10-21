问卷系统测试用例（FastAPI + MongoDB）【在报告中有截图】

测试方式：Swagger UI手工接口测试，地址：http://127.0.0.1:8000/docs

前置条件：服务正常启动，MongoDB连接正常，测试前注册账号并使用JWT完成授权登录

本项目采用FastAPI内置Swagger UI作为系统交互入口，不再额外开发独立前端页面。

其他用户在同一局域网内，访问http://本机IP:8000/docs接口文档页面，即可调用问卷创建、题目添加、答卷提交、结果统计等接口，完成问卷填写与查看统计。

所有业务逻辑（答案校验、题目跳转、数据存储、统计聚合）均由后端实现，数据持久化存储在 MongoDB。

窗口1：管理员CMD（专门跑MongoDB，一直开着）

输入MongoDB启动命令：

mongod --dbpath D:\mongodb_data

这个窗口全程不能关，一关数据库就停了。

窗口2：普通CMD（普通权限，跑FastAPI项目）

普通cmd，不用管理员权限，用来执行pip安装、启动后端服务

先cd进入项目survey_system文件夹

cd C:\Users\86156\Desktop\数据系统大作业第一阶段\survey_system

安装依赖（只需要第一次执行）

python -m pip install fastapi uvicorn pymongo bcrypt pyjwt pydantic

启动后端服务

python -m uvicorn main:app --reload

浏览器打开http://127.0.0.1:8000/docs测试接口

在Swagger右上角Authorize输入用户名和密码（成功）（用户名：chen,密码：123）

测试01	用户模块	测试用户注册，校验用户名不可重复、密码bcrypt加密存储	1. 打开用户模块注册接口 POST2. 输入用户名chen，密码123. 执行请求；再次执行注册，使用完全相同用户名chen	 1. 第一次注册成功，返回成功信息；2. 第二次重复用户名注册返回错误，提示用户名已存在

测试02	用户模块	测试用户登录，验证账号密码校验，成功返回JWT Token	1. 调用登录接口 POST，填入上面注册的用户名与密码2. 执行接口	账号密码匹配，输出登录成功，返回access_token（JWT 字符串）

输出：
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2YWQ3NjJlNTkzNTM2ZWU2NjZlMTUwZWMiLCJleHAiOjE3OTI1MDk5Njh9.m7BG_4UkaJdyVLGvD8XMlhUOdixBqFUA_vQPgWGkqvQ",
  "token_type": "bearer",
  "code": 0,
  "msg": "登录成功",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2YWQ3NjJlNTkzNTM2ZWU2NjZlMTUwZWMiLCJleHAiOjE3OTI1MDk5Njh9.m7BG_4UkaJdyVLGvD8XMlhUOdixBqFUA_vQPgWGkqvQ",
    "user_id": "6ad762e593536ee666e150ec",
    "username": "chen"
  }
}

测试03	创建问卷，生成唯一short_id，校验归属用户ID	1. 授权填入JWT token2. 调用 POST /api/survey创建问卷请求体填写标题、问卷说明、是否匿名、截止时间	创建成功，返回问卷完整信息；包含唯一 short_id；问卷归属创建用户_id；问卷默认未发布、未关闭状态	

输出
{
  "code": 0,
  "msg": "问卷创建成功",
  "data": {
    "survey_id": "6ad76c35b2718f2e297ffb1b",
    "short_id": "FacyC3",
    "access_url": "/survey/FacyC3",
    "is_published": false,
    "is_closed": false
  }
}

测试04	问卷管理	获取当前登录用户创建问卷列表，权限校验（只能看自己问卷）	调用 GET /api/survey/my 接口	返回列表，仅展示当前登录用户创建的问卷；看不到其他用户创建问卷

测试05	问卷管理	修改问卷基础信息	调用PUT /api/survey/{survey_id}，修改问卷标题、说明等字段	问卷信息更新成功；仅问卷创建者可修改，其他用户访问返回403无权限	

测试06	问卷管理	发布问卷，更新发布状态	调用 、PATCH /api/survey/{survey_id}/publish	问卷状态修改为已发布；发布后才可提交答卷

输出：
{
  "code": 0,
  "msg": "发布状态更新成功"
}

测试07	问卷管理	关闭问卷，关闭后禁止答卷提交	1. 调用 PATCH /api/survey/{survey_id}/close 关闭问卷2. 尝试提交答卷	问卷标记为关闭；后续提交答卷接口返回错误，无法提交新答卷	

测试08	跳转逻辑测试 问卷管理	删除问卷，级联清理关联题目、跳转规则	调用 DELETE /api/survey/{survey_id}	问卷删除成功；关联题目、跳转规则同步清理；仅问卷创建者可删除	

测试09	题目管理	新增单选题，校验必填配置存入数据库	POST /api/question，传入 survey_id，题型单选，设置是否必填	题目创建成功，存入 MongoDB；包含单选配置（是否必填），归属对应问卷	
输出：
{
  "code": 0,
  "msg": "题目新增成功",
  "data": {
    "question_id": "6ad826a4b2c6d96e64d5711c"
  }
}
测试10	题目管理	新增多选题，设置最少、最多选择数量（边界：最少 = 最多）	POST /api/question，题型多选，min_select=2，max_select=2	题目创建成功；多选校验规则（最少 2、最多 2）持久化存储	

测试11	题目管理	新增文本填空题，设置最小、最大字数限制	POST /api/question，文本填空，min_words=2，max_words=10	题目创建成功；文本字数限制配置存入数据库	

测试12	题目管理	新增数字填空题，设置数值上下限，开启整数校验	POST /api/question，数字填空，min=1，max=10，is_integer=True	题目创建成功；数字范围、整数校验配置持久化	

测试13	题目管理	编辑已有题目，修改题目校验配置	PUT /api/question/{question_id} 修改题目配置	题目更新成功；校验规则更新并保存到数据库	

测试14	题目管理	删除题目，校验删除权限	DELETE /api/question/{question_id}	题目删除成功；仅问卷创建者可删除题目	

测试15	题目管理	获取问卷全部题目列表	GET /api/question/list/{survey_id}	返回该问卷下全部题目，包含各题型对应的校验配置	

测试16	问卷填写	获取问卷填写页面信息，加载题目与跳转规则	GET /api/fill/survey/{short_id}，传入问卷 short_id	返回问卷基础信息、全部题目、MongoDB 中存储的跳转规则	

测试17	校验测试，答卷提交	正常提交答卷，后端执行全部校验，答卷入库	POST /api/fill/submit/{short_id}，传入合法答案：单选、多选、文本、数字全部满足校验规则	校验全部通过，答卷存入 answers 集合；执行后端跳转逻辑	

测试18	校验测试，答卷提交	边界测试：多选题最少 = 最多，提交选项数量不符合要求	提交答卷，多选题要求 min=2 max=2，只选 1 个选项	后端校验失败，返回错误提示；答卷不写入数据库

测试19	校验测试，答卷提交	边界测试：数字填空，填写数值超出上限	数字题范围 1~10，提交数字 11	后端校验拦截，返回数值超出范围提示，不保存答卷	

测试20	校验测试，答卷提交	边界测试：必答题留空提交	将必填题目答案置空，提交答卷	后端校验失败，提示该题为必填项，答卷入库失败	

测试21	校验测试，答卷提交	跳转规则测试：多条跳转规则同时命中，执行跳转逻辑	构造答卷答案，触发多条 MongoDB 内存储跳转规则	后端读取 jump_rules，按规则判定下一题；无匹配规则按顺序走下一题；全部结束返回 None	

测试22	统计测试 统计模块	获取问卷整体统计结果	GET /api/statistics/survey/{survey_id}	单选：每个选项选择人数；多选：选项被选中总次数；文本填空：原始文本；数字填空：返回平均值

输出：
{
  "code": 0,
  "data": {
    "total_submit": 0,
    "question_stats": []
  }
}

测试23	统计模块	获取单题统计结果（传入 question_id 参数）	GET /api/statistics/survey/{survey_id}，附加question_id参数	仅返回指定题目的统计数据，其他题目不返回	

测试24	统计模块	获取问卷全部原始答卷快照，权限校验	GET /api/statistics/answers/{survey_id}	返回所有答卷快照；仅问卷创建者可以访问，其他用户返回403无权访问	