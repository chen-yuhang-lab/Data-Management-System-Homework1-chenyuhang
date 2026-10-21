"""
database.py MongoDB初始化连接
导出db对象以及各个集合对象，项目统一从此处获取集合
"""
from pymongo import MongoClient
from config import MONGO_URI, MONGO_DB_NAME

# 创建客户端
client = MongoClient(MONGO_URI)
# 获取数据库
db = client[MONGO_DB_NAME]

# 导出全部集合
users = db["users"]
surveys = db["surveys"]
questions = db["questions"]
jump_rules = db["jump_rules"]
answers = db["answers"]


def init_indexes():
    """初始化数据库必要索引，项目启动调用一次"""
    # 用户用户名字唯一索引
    users.create_index("username", unique=True)
    # 问卷short_id唯一索引
    surveys.create_index("short_id", unique=True)
    surveys.create_index("owner_user_id")
    questions.create_index("survey_id")
    jump_rules.create_index("survey_id")
    jump_rules.create_index("source_question_id")
    answers.create_index("survey_id")
    answers.create_index("submit_user_id")