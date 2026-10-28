"""
services/stat_service.py
问卷统计业务服务层
封装MongoDB aggregate聚合管道，对answers集合做答卷统计
支持全问卷统计 / 指定单个question_id统计
统计来源：answers.question_snapshot 答卷快照数据
"""
from typing import List, Dict, Optional, Any
from bson import ObjectId
from pymongo.cursor import Cursor
from database import answers


def aggregate_survey_stat(survey_id: str, filter_question_id: Optional[str] = None) -> Dict[str, Any]:
    """
    执行聚合统计
    :param survey_id: 问卷id字符串
    :param filter_question_id: 可选，题目id；传入则仅统计该一道题目
    :return: 统计结果字典 total_submit:总提交数，question_stats:各题统计数组
    """
    survey_obj_id = ObjectId(survey_id)

    # -------- MongoDB aggregate 聚合管道 --------
    pipeline = [
        # 阶段1：筛选该问卷所有答卷
        {
            "$match": {
                "survey_id": survey_obj_id
            }
        },
        # 阶段2：展开每一条答卷里面的question_snapshot数组，每一行变成一道答题记录
        {
            "$unwind": "$question_snapshot"
        }
    ]

    # 如果指定单题统计，增加匹配题目id条件
    if filter_question_id is not None:
        q_obj_id = ObjectId(filter_question_id)
        pipeline.append({
            "$match": {
                "question_snapshot.question_id": q_obj_id
            }
        })

    # 阶段3：按题目id分组，收集该题所有用户答案、题型、题目标题
    pipeline.append({
        "$group": {
            "_id": {
                "qid": "$question_snapshot.question_id",
                "q_title": "$question_snapshot.question_title",
                "q_type": "$question_snapshot.question_type"
            },
            "answer_list": {"$push": "$question_snapshot.user_answer"}
        }
    })

    # 执行聚合
    cursor: Cursor = answers.aggregate(pipeline)
    group_result: List[Dict] = list(cursor)

    # 总提交答卷数：统计该survey_id下answers文档总数
    total_submit = answers.count_documents({"survey_id": survey_obj_id})

    question_stats = []

    for item in group_result:
        qid = str(item["_id"]["qid"])
        q_title = item["_id"]["q_title"]
        q_type = item["_id"]["q_type"]
        ans_list = item["answer_list"]
        valid_ans = [a for a in ans_list if a is not None]
        stat_out = {}

        if q_type == "single_choice":
            # 单选题：每个选项计数，总作答人数
            opt_count = {}
            for a in valid_ans:
                opt_count[a] = opt_count.get(a, 0) + 1
            stat_out["total_answer"] = len(valid_ans)
            stat_out["option_count"] = opt_count

        elif q_type == "multi_choice":
            # 多选题：答案是数组，每个选项累加被选中次数
            opt_count = {}
            for ans_arr in valid_ans:
                if isinstance(ans_arr, list):
                    for opt in ans_arr:
                        opt_count[opt] = opt_count.get(opt, 0) + 1
            stat_out["option_count"] = opt_count

        elif q_type == "text_fill":
            # 文本填空：返回全部原始文本
            stat_out["raw_text"] = valid_ans

        elif q_type == "number_fill":
            # 数字填空：计算平均值；过滤无法转数字的脏数据
            num_list = []
            for a in valid_ans:
                try:
                    num_list.append(float(a))
                except (ValueError, TypeError):
                    pass
            if len(num_list) > 0:
                stat_out["avg"] = sum(num_list) / len(num_list)
            else:
                stat_out["avg"] = None
        else:
            stat_out["note"] = "未知题型"

        question_stats.append({
            "question_id": qid,
            "question_title": q_title,
            "question_type": q_type,
            "stat": stat_out
        })

    return {
        "total_submit": total_submit,
        "question_stats": question_stats
    }