"""
scripts/migrate_phase2.py

第一阶段数据迁移脚本（可选，但强烈建议执行一次）。

作用：
1. 为第一阶段已有的 questions 文档补建题目模板和 v1 版本，
   写入 template_id / version_id / version_no，并标记 source=phase1；
2. 为历史 answers 的 question_snapshot 补上 template_id / version_id / version_no，
   使跨问卷统计可以覆盖旧答卷；
3. 初始化第二阶段新增索引。

特点：
- 幂等：已迁移的题目会跳过，可重复执行；
- 不删除、不覆盖任何旧字段；
- 默认 dry-run，只打印统计，不写数据库；确认后加 --apply 才真正执行；
- 不使用事务（兼容单机 MongoDB），单题失败会记录并继续，最后输出失败清单。

用法（在项目根目录 survey_system 下执行）：
    python scripts/migrate_phase2.py            # 预演，不写库
    python scripts/migrate_phase2.py --apply    # 真正执行
    python scripts/migrate_phase2.py --apply --survey-id <survey_id>  # 只迁移一份问卷
"""
import argparse
import os
import sys
from datetime import datetime

# 允许从项目根目录直接执行：python scripts/migrate_phase2.py
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database  # noqa: E402
from bson import ObjectId  # noqa: E402
from services import question_bank_service as svc  # noqa: E402


def migrate_question(question, survey, dry_run: bool):
    """为一道第一阶段题目补建模板/版本，并回填历史答卷快照。"""
    content = svc._content_from_doc(question)  # 内部工具，迁移脚本复用
    try:
        svc.validate_question_content(content)
    except svc.QuestionBankError as exc:
        return False, f"题目内容不合法，已跳过：{exc.message}"

    if dry_run:
        return True, "would migrate"

    now = datetime.utcnow()
    # 直接插入模板和 v1，保证版本号固定为1
    template_doc = {
        "owner_user_id": survey["owner_user_id"],
        "title": (content.get("question_title") or "").strip(),
        "question_type": content.get("question_type"),
        "current_version_id": None,
        "current_version_no": 0,
        "parent_template_id": None,
        "source_version_id": None,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    template_id = database.question_templates.insert_one(template_doc).inserted_id

    version_doc = {
        "template_id": template_id,
        "version_no": 1,
        "parent_version_id": None,
        "restored_from_version_id": None,
        "source_question_id": question["_id"],
        "created_by": survey["owner_user_id"],
        "created_at": now,
        "change_note": "第一阶段题目迁移归档",
    }
    version_doc.update(content)
    version_id = database.question_versions.insert_one(version_doc).inserted_id

    database.question_templates.update_one(
        {"_id": template_id},
        {"$set": {
            "current_version_id": version_id,
            "current_version_no": 1,
            "updated_at": now,
        }},
    )
    database.questions.update_one(
        {"_id": question["_id"]},
        {"$set": {
            "template_id": template_id,
            "version_id": version_id,
            "version_no": 1,
            "source": "phase1",
            "updated_at": now,
        }},
    )

    # 回填历史答卷快照（旧答案没有版本信息）
    database.answers.update_many(
        {"question_snapshot.question_id": question["_id"]},
        {"$set": {
            "question_snapshot.$[elem].template_id": template_id,
            "question_snapshot.$[elem].version_id": version_id,
            "question_snapshot.$[elem].version_no": 1,
        }},
        array_filters=[{"elem.question_id": question["_id"]}],
    )
    return True, "migrated"


def main():
    parser = argparse.ArgumentParser(description="第一阶段问卷数据迁移到第二阶段题目版本结构")
    parser.add_argument("--apply", action="store_true", help="真正写入数据库；不加此参数只预演")
    parser.add_argument("--survey-id", default=None, help="只迁移指定问卷")
    args = parser.parse_args()

    dry_run = not args.apply
    print("=" * 70)
    print("第二阶段数据迁移")
    print(f"数据库：{database.db.name}")
    print(f"模式：{'DRY-RUN（不写库）' if dry_run else 'APPLY（写库）'}")
    print("=" * 70)

    if not dry_run:
        database.init_indexes()
        print("索引初始化完成")

    survey_query = {}
    if args.survey_id:
        survey_query["_id"] = ObjectId(args.survey_id)

    total_questions = 0
    migrated = 0
    skipped = 0
    failed = []

    for survey in database.surveys.find(survey_query):
        question_cursor = database.questions.find({
            "survey_id": survey["_id"],
            "template_id": {"$exists": False},
        })
        for question in question_cursor:
            total_questions += 1
            ok, message = migrate_question(question, survey, dry_run)
            if ok:
                migrated += 1
                print(f"[OK] survey={survey['_id']} question={question['_id']} {message}")
            else:
                skipped += 1
                failed.append({
                    "survey_id": str(survey["_id"]),
                    "question_id": str(question["_id"]),
                    "reason": message,
                })
                print(f"[SKIP] survey={survey['_id']} question={question['_id']} {message}")

    print("-" * 70)
    print(f"待迁移题目：{total_questions}")
    print(f"成功/预演：{migrated}")
    print(f"跳过：{skipped}")
    if failed:
        print("失败清单：")
        for item in failed:
            print(f"  {item}")
    print("完成" if not dry_run else "预演完成；确认无误后加 --apply 真正执行")


if __name__ == "__main__":
    main()
