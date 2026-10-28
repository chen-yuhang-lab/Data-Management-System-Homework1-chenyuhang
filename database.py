"""
database.py MongoDB初始化连接
导出db对象以及各个集合对象，项目统一从此处获取集合

第二阶段扩展（不删除第一阶段集合）：
新增 question_templates / question_versions / question_banks / question_bank_items / question_shares
原有 users / surveys / questions / jump_rules / answers 保持原样，旧代码无需修改。
"""
from pymongo import MongoClient
from config import MONGO_URI, MONGO_DB_NAME

# 创建客户端
client = MongoClient(MONGO_URI)
# 获取数据库
db = client[MONGO_DB_NAME]

# 导出全部集合（第一阶段）
users = db["users"]
surveys = db["surveys"]
questions = db["questions"]
jump_rules = db["jump_rules"]
answers = db["answers"]

# 第二阶段新增集合
question_templates = db["question_templates"]      # 题目的逻辑主记录（一个题目对应多个版本）
question_versions = db["question_versions"]        # 题目不可变版本内容
question_banks = db["question_banks"]              # 题库
question_bank_items = db["question_bank_items"]    # 题库-题目关联
question_shares = db["question_shares"]            # 题目共享授权


def init_indexes():
    """初始化数据库必要索引，项目启动调用一次；可重复执行"""
    # ---------------- 第一阶段索引 ----------------
    # 用户名唯一索引
    users.create_index("username", unique=True)
    # 问卷short_id唯一索引
    surveys.create_index("short_id", unique=True)
    surveys.create_index("owner_user_id")
    questions.create_index("survey_id")
    jump_rules.create_index("survey_id")
    jump_rules.create_index("source_question_id")
    answers.create_index("survey_id")
    answers.create_index("submit_user_id")

    # ---------------- 第二阶段索引 ----------------
    # 问卷题目实例与题目模板/版本的关联
    questions.create_index("template_id")
    questions.create_index("version_id")

    # 题目模板
    question_templates.create_index("owner_user_id")
    question_templates.create_index("current_version_id")
    question_templates.create_index("is_deleted")

    # 题目版本：同一模板内版本号唯一
    question_versions.create_index(
        [("template_id", 1), ("version_no", 1)],
        unique=True
    )
    question_versions.create_index("template_id")
    question_versions.create_index("created_by")

    # 题库
    question_banks.create_index("owner_user_id")
    question_bank_items.create_index(
        [("bank_id", 1), ("template_id", 1)],
        unique=True
    )
    question_bank_items.create_index("template_id")

    # 共享授权：同一题目对同一用户只保留一条有效授权
    question_shares.create_index(
        [("template_id", 1), ("shared_with_user_id", 1)],
        unique=True
    )
    question_shares.create_index("shared_with_user_id")
    question_shares.create_index("owner_user_id")

    # 跨问卷统计会按快照中的题目/模板/版本检索
    answers.create_index("question_snapshot.question_id")
    answers.create_index("question_snapshot.template_id")
    answers.create_index("question_snapshot.version_id")