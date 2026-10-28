"""
config.py 项目配置文件
存放MongoDB连接、JWT相关配置

第二阶段兼容说明：
1. 原有默认值保持不变，旧启动方式无需修改；
2. 新增环境变量覆盖能力，便于自动化测试使用独立测试库（TEST_MONGO_URI / TEST_MONGO_DB）。
   生产部署时也可以直接通过 MONGO_URI / MONGO_DB_NAME 覆盖。
"""
import os

# MongoDB连接配置（环境变量优先，未配置时保持第一阶段的默认值）
MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "survey_system_db")

# JWT配置
JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY",
    "survey-secret-key-2026-replace-in-production"
)  # 正式环境请更换为随机密钥
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "120"))  # token过期时间，单位分钟