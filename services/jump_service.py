"""
services/jump_service.py
问卷跳转逻辑业务函数
跳转规则全部来自MongoDB jump_rules集合，禁止硬编码跳转条件
规则类型：
single_equal      单选回答等于指定选项
multi_contains    多选回答包含指定选项
number_gt         数字填空大于指定值
number_lt         数字填空小于指定值
number_eq         数字填空等于指定值

多条规则命中：使用priority优先级，数字越小优先级越高，取第一条命中规则；无命中则顺序下一题；问卷结束返回None
"""
from typing import List, Dict, Optional, Any
from bson import ObjectId


def find_answer_by_question_id(answers: List[Dict], question_id: ObjectId) -> Optional[Any]:
    """
    工具函数：根据question_id从用户答案列表取出用户填写的answer_value
    :param answers: 用户已填写答案列表 [{"question_id":ObjectId,"answer_value":xxx},...]
    :param question_id: 目标题目ObjectId
    :return: answer_value，找不到返回None
    """
    for ans in answers:
        if ans.get("question_id") == question_id:
            return ans.get("answer_value")
    return None


def get_next_order_question_id(current_qid: ObjectId, all_questions: List[Dict]) -> Optional[ObjectId]:
    """
    获取顺序下一题id，无下一题返回None（问卷结束）
    all_questions：问卷全部题目列表，按页面展示顺序排列
    """
    # 提取题目id顺序列表
    qid_list = [q["_id"] for q in all_questions]
    try:
        idx = qid_list.index(current_qid)
    except ValueError:
        return None
    next_idx = idx + 1
    if next_idx >= len(qid_list):
        return None
    return qid_list[next_idx]


def match_jump_rule(rule: Dict, user_answer: Any) -> bool:
    """
    判断单条跳转规则是否命中用户答案
    :param rule: jump_rules单条规则文档
    :param user_answer: 用户对源题目的作答结果
    :return: True命中，False不命中
    """
    rule_type = rule["rule_type"]
    rule_value = rule["rule_value"]

    # 没有作答直接不命中
    if user_answer is None:
        return False

    if rule_type == "single_equal":
        # 单选：回答等于指定选项
        return user_answer == rule_value

    elif rule_type == "multi_contains":
        # 多选：用户答案是列表，判断是否包含规则值
        if not isinstance(user_answer, list):
            return False
        return rule_value in user_answer

    elif rule_type == "number_gt":
        # 数字大于
        try:
            return float(user_answer) > float(rule_value)
        except (ValueError, TypeError):
            return False

    elif rule_type == "number_lt":
        # 数字小于
        try:
            return float(user_answer) < float(rule_value)
        except (ValueError, TypeError):
            return False

    elif rule_type == "number_eq":
        # 数字等于
        try:
            return float(user_answer) == float(rule_value)
        except (ValueError, TypeError):
            return False
    # 未知规则类型
    return False


def calc_next_question_id(
    answers: List[Dict],
    current_question_id: ObjectId,
    all_questions: List[Dict],
    jump_rules: List[Dict]
) -> Optional[ObjectId]:
    """
    计算跳转后的下一题ID
    :param answers: 用户已经填写完毕的答案字典列表：[{"question_id":ObjectId,"answer_value":xxx},...]
    :param current_question_id: 当前展示题目 ObjectId
    :param all_questions: 当前问卷全部题目完整文档列表（保持页面顺序）
    :param jump_rules: 当前问卷全部跳转规则（来自MongoDB jump_rules集合）
    :return: ObjectId 下一题id；无跳转返回顺序下一题；问卷结束返回None
    """

    # 1.过滤出源题目等于当前题目的所有跳转规则
    source_rules = [r for r in jump_rules if r["source_question_id"] == current_question_id]

    hit_target_id: Optional[ObjectId] = None

    if source_rules:
        # 2.按优先级升序排序，数字越小优先级越高，优先匹配靠前规则
        source_rules_sorted = sorted(source_rules, key=lambda x: x.get("priority", 999))

        # 取出当前题目的用户答案
        user_ans = find_answer_by_question_id(answers, current_question_id)

        # 3.依次遍历规则，找到第一条命中的规则
        for rule in source_rules_sorted:
            if match_jump_rule(rule, user_ans):
                hit_target_id = rule["target_question_id"]
                break

    # 4.如果命中跳转规则，返回跳转目标题目id
    if hit_target_id is not None:
        return hit_target_id

    # 5.没有命中任何跳转规则，按原始顺序取下一题
    next_order_qid = get_next_order_question_id(current_question_id, all_questions)
    return next_order_qid