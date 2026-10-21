"""
config.py 项目配置文件
存放MongoDB连接、JWT相关配置
"""

# MongoDB连接配置
MONGO_URI = "mongodb://127.0.0.1:27017/"
MONGO_DB_NAME = "survey_system_db"

# JWT配置
JWT_SECRET_KEY = "survey-secret-key-2026-replace-in-production"  # 正式环境请更换为随机密钥
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 120  # token过期时间，单位分钟