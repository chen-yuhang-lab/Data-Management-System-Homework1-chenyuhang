# 基于 FastAPI + MongoDB 的在线问卷系统（第二阶段）

---

## 1. 第二阶段做了什么

第二阶段没有推倒重做，而是在第一阶段代码上做**增量扩展**：

- 保留原有 `users / surveys / questions / jump_rules / answers` 五个集合；
- 保留原有注册登录、问卷 CRUD、四种题型、跳转、校验、提交、按问卷统计等全部功能；
- 新增“题目模板 + 不可变版本”机制；
- 新增题库、题目共享、题目派生、已发布问卷冻结、题目使用情况追踪、单题跨问卷统计；
- 新增第一阶段数据迁移脚本，旧题目和旧答卷可以平滑接入新结构。

需求与实现的对应关系：

| 需求变更 | 实现方式 | 主要接口 |
|---|---|---|
| 保存常用题目，重复使用 | 题目保存为 `question_templates` + `question_versions`，可从题库选题 | `POST /api/question_bank/templates`、`POST /api/question_bank/templates/{id}/add_to_survey` |
| 把题目分享给别人 | `question_shares` 保存授权，被共享用户可查看和使用 | `POST /api/question_bank/templates/{id}/share` |
| 修改题目不影响已发布问卷 | 已发布问卷题目冻结；版本不可变；问卷题目实例保存内容副本 | 修改/删除接口返回 409 |
| 记录题目修改历史 | 每次修改新增 `question_versions`，形成 v1→v2→v3 | `GET /api/question_bank/templates/{id}/versions` |
| 同一题不同版本同时存在 | 问卷题目实例固定 `version_id`，不同问卷可指向不同版本 | `POST .../versions`、`POST .../add_to_survey` |
| 查看题目被哪些问卷使用 | 按 `questions.template_id` 反查并聚合问卷 | `GET .../templates/{id}/usage` |
| 建立题目库 | `question_banks` + `question_bank_items` 独立关联集合 | `/api/bank/*` |
| 单题跨问卷统计 | 答卷快照记录 `template_id/version_id`，聚合所有引用该题的问卷 | `GET /api/statistics/question/{template_id}` |

---

## 2. 目录结构（第二阶段新增文件）

```
survey_system/
├── main.py                         # 已修改：注册第二阶段路由，版本号改为2.0.0
├── config.py                       # 已修改：支持环境变量覆盖 MongoDB/JWT 配置
├── database.py                     # 已修改：新增第二阶段集合与索引（原集合保留）
├── schemas.py                      # 第一阶段设计文档，保持原样
├── schemas_phase2.py               # 新增：第二阶段集合设计文档
├── utils.py                        # 新增：ObjectId/datetime 递归 JSON 序列化
│
├── routers/
│   ├── question.py                 # 已修改：发布后冻结、create_new_version、fork
│   ├── statistics.py               # 已修改：新增跨问卷统计接口
│   ├── question_bank.py            # 新增：题目模板/版本/共享/使用情况
│   └── bank.py                     # 新增：题库管理
│
├── services/
│   ├── question_bank_service.py    # 新增：题库、版本、共享核心业务
│   ├── cross_stat_service.py       # 新增：单题跨问卷聚合统计
│   └── validate_service.py         # 已修改：答卷快照增加模板/版本字段
│
├── scripts/
│   ├── __init__.py
│   └── migrate_phase2.py           # 新增：第一阶段数据迁移（默认 dry-run）
│
├── requirements-test.txt           # 新增：测试依赖说明
├── README_phase2.md                # 本文件
├── test_cases_phase2.md            # 新增：第二阶段手工测试用例
```

---

## 3. 数据模型变化

### 3.1 新增集合

| 集合 | 作用 | 关键字段 |
|---|---|---|
| `question_templates` | 题目的逻辑主记录 | `owner_user_id`、`current_version_id`、`current_version_no`、`parent_template_id` |
| `question_versions` | 不可变题目版本 | `template_id`、`version_no`、`parent_version_id`、`question_title`、题型配置 |
| `question_banks` | 题库 | `owner_user_id`、`name`、`is_public` |
| `question_bank_items` | 题库-题目关联 | `bank_id`、`template_id` |
| `question_shares` | 题目共享授权 | `template_id`、`shared_with_user_id`、`can_use`、`is_active` |

### 3.2 原有集合的兼容扩展

`questions`（问卷题目实例）新增：

```json
{
  "template_id": "ObjectId | null",
  "version_id": "ObjectId | null",
  "version_no": 1,
  "source": "manual | question_bank | fork | phase1",
  "bank_id": "ObjectId | null"
}
```

`answers.question_snapshot[]` 新增：

```json
{
  "template_id": "ObjectId | null",
  "version_id": "ObjectId | null",
  "version_no": 1
}
```

旧数据没有这些字段也能正常运行；执行迁移脚本后会补齐。

### 3.3 为什么不是把题目直接嵌在问卷里

第一阶段的 `questions` 已经是“问卷题目实例”，如果第二阶段继续让每份问卷各存一份题目，就无法做到：

- 一个题目被多个问卷复用；
- 修改题目时只影响新问卷；
- 查看题目历史版本；
- 跨问卷统计同一题。

因此增加“模板 + 版本”两层，同时保留 `questions` 作为实例层。这样既满足新需求，又不需要重写第一阶段的填写、校验、跳转、统计代码。

---

## 4. 关键业务规则

### 4.1 题目版本

- 新建题目 → `v1`；
- 每次“创建新版本” → 版本号 +1，旧版本永不修改；
- “恢复旧版本”不会删除历史，而是把旧内容复制成新版本，例如 `v1 → v2 → v3(恢复自v1)`；
- 每份问卷的题目实例固定指向一个 `version_id`；
- 修改一份问卷的题目时，其他问卷引用旧版本的题目不变。

### 4.2 已发布问卷冻结

已发布问卷的题目结构不可变：

- 新增题目 → 409；
- 修改题目 → 409；
- 删除题目 → 409。

如果确实需要调整，有三种方式：

1. 先取消发布（`PATCH /api/survey/{id}/publish` 传 `false`）再修改；
2. 在题目库中为题目创建新版本，供新问卷使用；
3. 使用 `POST /api/question/{question_id}/fork` 以旧题为蓝本生成一道新题，加入新问卷。

### 4.3 共享

- 共享的是“使用权”，不是“修改权”；
- 被共享用户可以查看题目、把题目加入自己的未发布问卷；
- 被共享用户不能修改原题模板、不能查看原题跨问卷统计；
- 被共享用户可以 `fork` 出自己独立的题目；
- 取消共享后，已加入问卷的题目副本仍然保留（不影响历史数据），但不能继续使用该模板。

### 4.4 跨问卷统计

`GET /api/statistics/question/{template_id}`：

- 统计所有引用该模板的问卷中的答卷；
- 支持 `version_id` 参数只看某个版本；
- 返回总体统计 `overall` 和按问卷拆分 `by_survey`；
- 新答卷用快照里的 `template_id` 匹配；
- 旧答卷没有模板字段时，用 `question_id` 回退匹配；
- 只有题目创建者可以查看。

---

## 5. 启动步骤

### 5.1 启动 MongoDB

窗口 1（保持不关）：

```bat
mongod --dbpath D:\mongodb_data
```

如果使用默认端口 27017，下面命令无需改配置。

### 5.2 安装依赖

窗口 2：

```bat
cd C:\Users\86156\Desktop\数据系统大作业第一阶段\survey_system
python -m pip install -r requirements.txt
```

### 5.3 迁移第一阶段数据

先预演，确认输出无误：

```bat
python scripts/migrate_phase2.py
```

再真正执行：

```bat
python scripts/migrate_phase2.py --apply
```

迁移脚本是幂等的，重复执行不会重复建版本；它不会删除任何旧字段。

### 5.4 启动服务

```bat
python -m uvicorn main:app --reload
```

打开：

- Swagger：<http://127.0.0.1:8000/docs>
- OpenAPI：<http://127.0.0.1:8000/openapi.json>

---


## 6. 手工测试（Swagger）

完整用例见 `test_cases_phase2.md`。



## 7. 第二阶段新增 API 清单

### 7.1 题目模板 / 版本 / 共享

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/question_bank/templates` | 新建题目并保存到题目库，生成 v1 |
| GET | `/api/question_bank/templates?scope=mine/shared/all` | 查看可用题目 |
| GET | `/api/question_bank/templates/{template_id}` | 题目详情 + 全部版本 |
| GET | `/api/question_bank/templates/{template_id}/versions` | 版本历史 |
| POST | `/api/question_bank/templates/{template_id}/versions` | 创建新版本 |
| POST | `/api/question_bank/templates/{template_id}/restore/{version_id}` | 恢复旧版本（生成新版本） |
| POST | `/api/question_bank/templates/{template_id}/fork` | 派生一个属于当前用户的新题目 |
| DELETE | `/api/question_bank/templates/{template_id}?force=false` | 从题库软删除题目 |
| POST | `/api/question_bank/templates/{template_id}/share` | 共享给其他用户 |
| GET | `/api/question_bank/templates/{template_id}/shares` | 查看共享名单 |
| DELETE | `/api/question_bank/templates/{template_id}/shares/{user_id}` | 取消共享 |
| GET | `/api/question_bank/templates/{template_id}/usage` | 查看题目被哪些问卷使用 |
| POST | `/api/question_bank/templates/{template_id}/add_to_survey` | 从题库选题加入问卷 |

### 7.2 题库

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/bank` | 创建题库 |
| GET | `/api/bank/my` | 我的题库 |
| GET | `/api/bank/public` | 公开题库 |
| GET | `/api/bank/{bank_id}` | 题库详情 |
| PUT | `/api/bank/{bank_id}` | 修改题库 |
| DELETE | `/api/bank/{bank_id}` | 删除题库（不删题目） |
| POST | `/api/bank/{bank_id}/items` | 题目加入题库 |
| GET | `/api/bank/{bank_id}/items` | 题库题目列表 |
| DELETE | `/api/bank/{bank_id}/items/{template_id}` | 题目移出题库 |

### 7.3 题目与统计扩展

| 方法 | 路径 | 说明 |
|---|---|---|
| PUT | `/api/question/{question_id}?create_new_version=true` | 修改题目并生成新版本 |
| POST | `/api/question/{question_id}/fork` | 以旧题生成新题（可用于已发布问卷） |
| GET | `/api/statistics/question/{template_id}?version_id=...` | 单题跨问卷统计 |

---

## 8. 兼容性与旧功能验证

第二阶段保留了第一阶段全部接口和数据字段：

- `POST /api/user/register`、`POST /api/user/login` 不变；
- `/api/survey/*` 不变；
- `/api/question` 原有字段不变，仅在已发布问卷上增加 409 冻结规则；
- `/api/fill/survey/{short_id}`、`/api/fill/submit/{short_id}` 不变，快照额外记录版本字段；
- `/api/statistics/survey/{survey_id}`、`/api/statistics/answers/{survey_id}` 不变；
- 跳转规则 `jump_rules` 不变；
- 历史答卷 `question_snapshot` 仍可正常读取。

旧数据迁移：

```bat
python scripts/migrate_phase2.py --apply
```

迁移后：

- 旧题目获得 `template_id/version_id`；
- 旧答卷快照补齐 `template_id/version_id`；
- 旧问卷、旧统计、旧跳转仍可正常使用。

> 兼容性注意：第一阶段测试用例中的“编辑题目/删除题目”如果在**问卷已发布**之后执行，
> 第二阶段会按新需求返回 409。这不是旧功能失效，而是需求明确要求的“已发布问卷冻结”。
> 如需回归第一阶段编辑功能，请在发布前执行，或先取消发布。

---
