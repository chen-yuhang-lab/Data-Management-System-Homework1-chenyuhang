"""
schemas_phase2.py

第二阶段 MongoDB 集合设计说明（仅设计文档，不执行建表）。
第一阶段 schemas.py 保持原样，本文件只描述第二阶段新增集合和字段变化。

============================================================
一、总体思路：为什么采用“题目模板 + 不可变版本”
============================================================
第一阶段 questions 集合是“问卷题目实例”，每份问卷各自保存一份题目内容。
这样做实现简单，但无法满足第二阶段：
  - 同一道题被多个问卷复用；
  - 修改题目不能影响已发布问卷；
  - 保留历史版本、可以恢复旧版本；
  - 查看某道题被哪些问卷使用；
  - 跨问卷统计同一道题。

因此新增两层：
  question_templates：题目的逻辑主记录（“这道题是谁的、当前是哪个版本”）；
  question_versions ：不可变版本内容（每题每次修改新增一条，永不覆盖）。

questions 集合继续作为“问卷中的题目实例”，增加 template_id / version_id / version_no
指向题库版本，同时保留完整内容副本。这样：
  1. 第一阶段的 fill_survey、validate_service、jump_service、stat_service 无需改表结构即可运行；
  2. 即使题库中的题目被修改或软删除，旧问卷内容和历史答卷仍然完整；
  3. 不同问卷可以固定在不同版本上，互不影响。

============================================================
二、新增集合
============================================================
"""

# ------------------------------
# question_templates 题目模板（逻辑题目）
# 一条记录代表“一道题”这个概念，具体内容在 question_versions 中
# ------------------------------
QUESTION_TEMPLATE_SCHEMA_SAMPLE = {
    "_id": "ObjectId",                          # 模板主键
    "owner_user_id": "ObjectId",                # 创建者，关联 users._id
    "title": "你的年龄",                         # 冗余当前标题，便于列表展示
    "question_type": "number_fill",             # 冗余当前题型，便于筛选
    "current_version_id": "ObjectId",           # 当前版本，关联 question_versions._id
    "current_version_no": 3,                    # 当前版本号，从1开始递增
    "parent_template_id": None,                 # 若由其他题派生，记录来源模板
    "source_version_id": None,                  # 派生时所基于的版本
    "created_at": "datetime",
    "updated_at": "datetime",
    "is_deleted": False,                        # 软删除标记；问卷副本不受影响
    "deleted_at": None
}

QUESTION_TEMPLATE_INDEXES = [
    {"key": [("owner_user_id", 1)]},
    {"key": [("current_version_id", 1)]},
    {"key": [("is_deleted", 1)]},
]

# ------------------------------
# question_versions 题目版本（不可变）
# 每次修改新增一条，禁止覆盖旧版本；历史版本永久保留
# ------------------------------
QUESTION_VERSION_SCHEMA_SAMPLE = {
    "_id": "ObjectId",
    "template_id": "ObjectId",                  # 所属题目模板
    "version_no": 2,                            # 版本号，同一模板内唯一
    "parent_version_id": "ObjectId",            # 上一个版本，形成 v1→v2→v3 链
    "restored_from_version_id": None,           # 若由“恢复旧版本”产生，记录来源版本
    "source_question_id": None,                 # 若由第一阶段问卷题目归档而来，记录来源题目
    "created_by": "ObjectId",                   # 本版本创建人
    "created_at": "datetime",
    "change_note": "把最大值从120改为150",

    # 以下为题目内容快照，与第一阶段 questions 字段保持一致
    "question_title": "你的年龄",
    "question_type": "number_fill",
    "is_required": True,
    "single_options": None,
    "multi_options": None,
    "multi_min": None,
    "multi_max": None,
    "multi_exact": None,
    "text_min_len": None,
    "text_max_len": None,
    "num_min": 0,
    "num_max": 150,
    "num_must_int": True
}

QUESTION_VERSION_INDEXES = [
    {"key": [("template_id", 1), ("version_no", 1)], "unique": True},
    {"key": [("template_id", 1)]},
    {"key": [("created_by", 1)]},
]

# ------------------------------
# question_banks 题库
# ------------------------------
QUESTION_BANK_SCHEMA_SAMPLE = {
    "_id": "ObjectId",
    "owner_user_id": "ObjectId",                # 题库创建者
    "name": "常用人口学题目",
    "description": "团队共用题库",
    "is_public": False,                         # 是否允许其他用户浏览
    "created_at": "datetime",
    "updated_at": "datetime"
}

QUESTION_BANK_INDEXES = [
    {"key": [("owner_user_id", 1)]},
]

# ------------------------------
# question_bank_items 题库-题目关联
# 采用独立关联集合，而不是把题目数组塞进题库文档：
#   - 一个题目可以加入多个题库；
#   - 关联可单独增删，避免大文档频繁重写；
#   - 便于按 template_id 反查所属题库。
# ------------------------------
QUESTION_BANK_ITEM_SCHEMA_SAMPLE = {
    "_id": "ObjectId",
    "bank_id": "ObjectId",                      # 题库
    "template_id": "ObjectId",                  # 题目模板
    "added_by": "ObjectId",
    "added_at": "datetime"
}

QUESTION_BANK_ITEM_INDEXES = [
    {"key": [("bank_id", 1), ("template_id", 1)], "unique": True},
    {"key": [("template_id", 1)]},
]

# ------------------------------
# question_shares 题目共享授权
# 共享的是“使用权”，不是“修改权”
# ------------------------------
QUESTION_SHARE_SCHEMA_SAMPLE = {
    "_id": "ObjectId",
    "template_id": "ObjectId",                  # 被共享题目
    "owner_user_id": "ObjectId",                # 共享发起人（题目创建者）
    "shared_with_user_id": "ObjectId",          # 被共享用户
    "can_use": True,                            # 是否允许在其问卷中使用
    "is_active": True,                          # 取消共享时置false，保留审计记录
    "created_at": "datetime",
    "updated_at": "datetime"
}

QUESTION_SHARE_INDEXES = [
    {"key": [("template_id", 1), ("shared_with_user_id", 1)], "unique": True},
    {"key": [("shared_with_user_id", 1)]},
    {"key": [("owner_user_id", 1)]},
]

# ------------------------------
# questions 问卷题目实例（第一阶段集合，第二阶段扩展字段）
# 不改变原有字段，只增加版本关联信息
# ------------------------------
QUESTION_INSTANCE_PHASE2_EXTRA_FIELDS = {
    "template_id": "ObjectId | None",           # 指向题库模板；第一阶段旧题目为None
    "version_id": "ObjectId | None",            # 指向具体版本
    "version_no": "int | None",                 # 冗余版本号，便于展示
    "source": "manual | question_bank | fork | phase1",
    "bank_id": "ObjectId | None",               # 从哪个题库选中（可选）
    "created_at": "datetime | None",
    "updated_at": "datetime | None"
}

# ------------------------------
# answers 答卷集合（第一阶段集合，第二阶段扩展快照字段）
# 快照中增加 template_id / version_id / version_no，用于跨问卷统计。
# 旧答卷没有这些字段，跨问卷统计会退化为按 question_id 匹配，不影响旧数据。
# ------------------------------
ANSWER_SNAPSHOT_PHASE2_EXTRA_FIELDS = {
    "question_snapshot[].template_id": "ObjectId | None",
    "question_snapshot[].version_id": "ObjectId | None",
    "question_snapshot[].version_no": "int | None"
}

# ------------------------------
# 全部第二阶段索引
# ------------------------------
ALL_INDEX_PHASE2 = {
    "question_templates": QUESTION_TEMPLATE_INDEXES,
    "question_versions": QUESTION_VERSION_INDEXES,
    "question_banks": QUESTION_BANK_INDEXES,
    "question_bank_items": QUESTION_BANK_ITEM_INDEXES,
    "question_shares": QUESTION_SHARE_INDEXES,
    "questions": [
        {"key": [("template_id", 1)]},
        {"key": [("version_id", 1)]},
    ],
    "answers": [
        {"key": [("question_snapshot.question_id", 1)]},
        {"key": [("question_snapshot.template_id", 1)]},
        {"key": [("question_snapshot.version_id", 1)]},
    ],
}
