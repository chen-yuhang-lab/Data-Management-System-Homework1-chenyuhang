"""
schemas.py
MongoDB问卷系统第一阶段集合Schema定义说明
注意：MongoDB无强制Schema，本文件仅作为设计文档，以字典样例+注释描述每个集合字段、Bson类型；
数据库实际数据由pymongo写入；本文件不负责数据库建表，仅用于项目报告查阅。
集合清单：users、surveys、questions、jump_rules、answers
"""
from bson import ObjectId
from datetime import datetime

# ------------------------------
# users 用户集合
# 存储注册用户账号信息，密码bcrypt哈希存储，禁止明文
# ------------------------------
USER_SCHEMA_SAMPLE = {
    "_id": ObjectId("670000000000000000000001"),  # ObjectId，用户唯一主键
    "username": "zhangsan",                     # str，用户名，唯一不可重复
    "password_hash": "$2b$12$xxxx",             # str，bcrypt加密后的密码哈希
    "register_time": datetime(2026, 10, 19)     # datetime，注册时间
}

# users集合索引
USERS_INDEXES = [
    {"key": [("username", 1)], "unique": True}  # 用户名唯一索引，防止重复注册
]

# ------------------------------
# surveys 问卷集合
# 问卷基础元信息，归属创建用户，对外访问依靠short_id
# ------------------------------
SURVEY_SCHEMA_SAMPLE = {
    "_id": ObjectId("670000000000000000000002"),  # ObjectId，问卷主键
    "owner_user_id": ObjectId("670000000000000000000001"), # ObjectId，问卷创建者用户_id，关联users._id
    "title": "个人情况调查问卷",                   # str，问卷标题
    "description": "本次问卷用于收集基础信息",      # str，问卷说明
    "allow_anonymous": False,                     # bool，是否允许匿名填写
    "is_published": True,                         # bool，是否发布
    "is_closed": False,                           # bool，问卷是否手动关闭
    "deadline": datetime(2026,12,31),             # datetime，问卷截止时间；为null代表无截止时间
    "short_id": "a8k2f9"                          # str，对外url短id，全局唯一 /survey/{short_id}
}

# surveys集合索引
SURVEYS_INDEXES = [
    {"key": [("owner_user_id", 1)], "unique": False}, # 根据创建者查询我的问卷
    {"key": [("short_id", 1)], "unique": True}        # short_id唯一索引，通过url快速查找问卷
]

# ------------------------------
# questions 题目集合
# 每一条代表一道题目，归属某一份问卷；支持单选、多选、文本填空、数字填空
# 校验规则全部存在本集合，业务代码不写死校验参数
# ------------------------------
QUESTION_SCHEMA_SAMPLE = {
    "_id": ObjectId("670000000000000000000003"),  # ObjectId，题目主键
    "survey_id": ObjectId("670000000000000000000002"), # ObjectId，所属问卷_id，关联surveys._id
    "question_title": "你的性别",                 # str，题目标题
    "question_type": "single_choice",            # str：single_choice单选 / multi_choice多选 / text_fill文本填空 / number_fill数字填空
    "is_required": True,                         # bool，是否必答题

    # 单选特有字段，其他题型可存null
    "single_options": ["男", "女", "其他"],

    # 多选特有字段，其他题型可存null
    "multi_options": ["苹果","香蕉","西瓜"],
    "multi_min": 1,       # 最少选择数量
    "multi_max": 3,       # 最多选择数量
    "multi_exact": None,  # 必须选择的数量；不为null则要求必须选该数目

    # 文本填空特有字段
    "text_min_len": None,
    "text_max_len": None,

    # 数字填空特有字段
    "num_min": 0,
    "num_max": 120,
    "num_must_int": True
}

# questions集合索引
QUESTIONS_INDEXES = [
    {"key": [("survey_id", 1)], "unique": False}  # 根据问卷id批量查询全部题目
]

# ------------------------------
# jump_rules 跳转规则集合
# 独立集合存储跳转逻辑，不在代码硬编码；一条记录代表一条跳转规则
# ------------------------------
JUMP_RULE_SCHEMA_SAMPLE = {
    "_id": ObjectId("670000000000000000000004"),
    "survey_id": ObjectId("670000000000000000000002"), # 归属问卷id
    "source_question_id": ObjectId("670000000000000000000003"), # 触发跳转的源题目id
    "rule_type": "single_equal", #规则类型 single_equal单选等于 / multi_contains多选包含 / number_gt数字大于 / number_lt数字小于 / number_eq数字等于
    "rule_value": "男",          # 判断条件值
    "target_question_id": ObjectId("670000000000000000000005"), #跳转目标题目id
    "priority": 1                # int，规则优先级，多条命中时取优先级高的，数字越小优先级越高
}

# jump_rules集合索引
JUMP_RULES_INDEXES = [
    {"key": [("survey_id",1)], "unique": False},
    {"key": [("source_question_id",1)], "unique": False}
]

# ------------------------------
# answers 答卷集合
# 用户提交的完整答卷；存储题目快照信息，防止问卷修改/删除题目后历史答卷失效
# ------------------------------
ANSWER_SCHEMA_SAMPLE = {
    "_id": ObjectId("670000000000000000000006"),
    "survey_id": ObjectId("670000000000000000000002"), #答卷归属问卷
    "submit_user_id": ObjectId("670000000000000000000001"), #提交用户id；匿名则为null
    "submit_time": datetime(2026,10,19),

    # 关键：保存答题时刻题目的快照，问卷后续修改题目不会破坏历史答卷解析
    "question_snapshot": [
        {
            "question_id": ObjectId("670000000000000000000003"),
            "question_title": "你的性别",
            "question_type": "single_choice",
            "user_answer": "男" # 用户答案：单选存字符串；多选存列表；填空存str/number
        }
    ]
}

# answers集合索引
ANSWERS_INDEXES = [
    {"key": [("survey_id",1)], "unique": False}, # 根据问卷id查询所有答卷，统计使用
    {"key": [("submit_user_id",1)], "unique": False}
]

# 汇总全部索引，部署时在mongodb执行创建
ALL_INDEX = {
    "users": USERS_INDEXES,
    "surveys": SURVEYS_INDEXES,
    "questions": QUESTIONS_INDEXES,
    "jump_rules": JUMP_RULES_INDEXES,
    "answers": ANSWERS_INDEXES
}