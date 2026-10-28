"""
services/validate_service.py
表单校验业务层
封装所有答卷字段校验逻辑：必答题、多选数量、文本字数、数字范围整数校验
校验返回错误列表；无错误返回空列表
"""
from typing import List, Dict, Any
from bson import ObjectId


def validate_single_answer(question: Dict, answer_value: Any) -> List[Dict]:
    """
    校验单道题目答案
    :param question: 数据库取出的question完整文档
    :param answer_value: 用户提交的答案值
    :return: list [{"question_id":str,"msg":"错误信息"}]，无错误返回空列表
    """
    errors = []
    qid_str = str(question["_id"])
    q_type = question["question_type"]
    is_required = question.get("is_required", False)

    # ========== 必答题校验 ==========
    if is_required:
        if answer_value is None or answer_value == "" or (isinstance(answer_value, list) and len(answer_value) == 0):
            errors.append({"question_id": qid_str, "msg": "该题为必答题，请填写"})
            # 必答为空，不再做后续题型校验
            return errors

    # 选做题，答案为空直接放行
    if answer_value is None or answer_value == "":
        return errors

    # ========== 单选题校验 single_choice ==========
    if q_type == "single_choice":
        option_list = question.get("single_options", [])
        if answer_value not in option_list:
            errors.append({"question_id": qid_str, "msg": "选择的选项不合法"})

    # ========== 多选题校验 multi_choice ==========
    elif q_type == "multi_choice":
        if not isinstance(answer_value, list):
            errors.append({"question_id": qid_str, "msg": "多选答案格式错误，需要数组"})
            return errors
        opt_list = question.get("multi_options", [])
        # 校验选项都在合法选项内
        for item in answer_value:
            if item not in opt_list:
                errors.append({"question_id": qid_str, "msg": f"选项「{item}」不合法"})

        select_cnt = len(answer_value)
        multi_min = question.get("multi_min")
        multi_max = question.get("multi_max")
        multi_exact = question.get("multi_exact")

        if multi_exact is not None:
            if select_cnt != multi_exact:
                errors.append({"question_id": qid_str, "msg": f"本题必须选择{multi_exact}项"})
        else:
            if multi_min is not None and select_cnt < multi_min:
                errors.append({"question_id": qid_str, "msg": f"本题最少选择{multi_min}项"})
            if multi_max is not None and select_cnt > multi_max:
                errors.append({"question_id": qid_str, "msg": f"本题最多选择{multi_max}项"})

    # ========== 文本填空 text_fill ==========
    elif q_type == "text_fill":
        if not isinstance(answer_value, str):
            errors.append({"question_id": qid_str, "msg": "文本填空需要字符串"})
            return errors
        text_len = len(answer_value)
        t_min = question.get("text_min_len")
        t_max = question.get("text_max_len")
        if t_min is not None and text_len < t_min:
            errors.append({"question_id": qid_str, "msg": f"最少输入{t_min}个字符"})
        if t_max is not None and text_len > t_max:
            errors.append({"question_id": qid_str, "msg": f"最多输入{t_max}个字符"})

    # ========== 数字填空 number_fill ==========
    elif q_type == "number_fill":
        try:
            num_val = float(answer_value)
        except (ValueError, TypeError):
            errors.append({"question_id": qid_str, "msg": "请输入合法数字"})
            return errors

        num_must_int = question.get("num_must_int")
        if num_must_int is True:
            if not (num_val.is_integer()):
                errors.append({"question_id": qid_str, "msg": "本题要求输入整数"})

        n_min = question.get("num_min")
        n_max = question.get("num_max")
        if n_min is not None and num_val < n_min:
            errors.append({"question_id": qid_str, "msg": f"数值不能小于{n_min}"})
        if n_max is not None and num_val > n_max:
            errors.append({"question_id": qid_str, "msg": f"数值不能大于{n_max}"})

    return errors


def validate_answers_all(question_list: List[Dict], user_submit_answers: List[Dict]) -> List[Dict]:
    """
    批量校验整套答卷
    :param question_list: 问卷全部题目文档
    :param user_submit_answers: 用户提交的答案 [{"question_id":"xxx","answer_value":xxx}]
    :return: 全部错误列表，空列表代表校验全部通过
    """
    all_errors = []
    # 构建题目id:题目文档映射
    q_map: Dict[ObjectId, Dict] = {}
    for q in question_list:
        q_map[q["_id"]] = q

    for ans_item in user_submit_answers:
        qid_str = ans_item.get("question_id")
        ans_val = ans_item.get("answer_value")
        try:
            qid_obj = ObjectId(qid_str)
        except Exception:
            all_errors.append({"question_id": qid_str, "msg": "题目ID格式错误"})
            continue
        if qid_obj not in q_map:
            all_errors.append({"question_id": qid_str, "msg": "题目不存在"})
            continue
        q_doc = q_map[qid_obj]
        err = validate_single_answer(q_doc, ans_val)
        all_errors.extend(err)
    return all_errors


def build_question_snapshot(question_list: List[Dict], user_submit_answers: List[Dict]) -> List[Dict]:
    """
    生成答卷question_snapshot快照，存入answers集合
    保存提交时刻题目信息，后续修改/删除题目不会破坏历史答卷
    """
    snapshot = []
    q_map = {q["_id"]: q for q in question_list}
    for ans in user_submit_answers:
        qid_obj = ObjectId(ans["question_id"])
        q_doc = q_map.get(qid_obj)
        if not q_doc:
            continue
        snapshot.append({
            "question_id": qid_obj,
            "question_title": q_doc["question_title"],
            "question_type": q_doc["question_type"],
            "user_answer": ans["answer_value"]
        })
    return snapshot
