# TestCase Agent — 多智能体测试用例编写框架

基于 PRD / 代码 / 设计文档，自动生成结构化测试用例（Excel + XMind），内置审查-修复闭环，**锚定规格而非现状**。

## 解决了什么问题

现有 `~/.claude/skills/` 下有四个测试用例相关 skill，它们都是**对话式 skill**——在当前会话里触发一次，人工搬运中间结果。存在三个痛点：

| 痛点 | 本框架解法 |
|------|-----------|
| **① 不可重复调用**：每次需人工触发对话，无法脚本化/CI 集成 | CLI 驱动，`python main.py --prd ... --module ...`，可脚本化 |
| **② 生成与评审分离**：生成用例后需手动丢给 evaluator skill 评分，发现问题后再手动改 | **审查-修复闭环**：生成后自动过五维评分+同义反复检测，不合格的用例局部重生成（最多 3 轮） |
| **③ 铁律靠人记忆**：三层断言/拒绝路径断言/码值语义/异常占比等经验全靠编码时记住，遗漏即为假绿 | **Prompt 硬编码**：铁律写入系统 prompt，LLM 每轮自检，规则引擎确定性拦截 |

## 核心设计

### 流程：5 阶段 + 审查-修复闭环

```
Stage 1      Stage 2       Stage 3       Stage 4        Stage 5       Stage 6
 收集         规则抽取       用例设计       审查            修复循环       导出
(纯规则)      (LLM)         (LLM)        (引擎+LLM)       (LLM)        (文件)
   │            │             │              │              │            │
   │  PRD       │  Rule[]     │  TestCase[]  │  ReviewReport│  局部重生成  │  xlsx
   │  Code ─────┤  三方对齐    │  铁律约束      │  五维评分     │  受影响用例  │  xmind
   │  Design    │  差异标记    │  类型矩阵      │  同义反复检测  │            │
```

### 四条铁律（编码进 Prompt，不靠人记忆）

| # | 铁律 | 来源 | 违规后果 |
|---|------|------|---------|
| 1 | **锚定规格而非现状**：预期结果必须可追溯到 Rule citation，禁止照当前页面/接口现状写同义反复断言 | UI 测试教训 | 100% 通过 ≠ 用例好，意味着零信息量 |
| 2 | **拒绝路径要正向断言触发**：去重/权限/校验等后端合理拒绝，必须断言"正确拒绝"，不能换参数绕过 | XXX项目去重测试教训 | 绕过=掩盖缺陷 |
| 3 | **业务拒绝 ≠ 系统崩溃**：code=500 是 BusinessException 拒绝（非崩溃），code=-1 才是未捕获异常 | XXX项目 code 语义实测 | 用 `assertNotEquals(code, 500)` 会把正确拒绝误判为失败 |
| 4 | **异常场景 20%-40%**：每个功能点至少配 正向 + 异常/反向 + 边界 三件套 | XXX项目 三次迭代经验 | 异常占比 <6% 是常见陷阱 |

### 审查：规则引擎 + LLM 混合

**规则引擎**（无需 LLM，快且确定性）：
- 必填字段非空、编号/标题重复
- 预期结果模糊词（"成功"/"正常"/"通过"独自出现）
- 异常场景占比是否 ≥ scope.md 声明的阈值
- 每条 Rule 是否至少有一条对应用例
- 有 unique/business_rule 约束的 Rule 是否有拒绝路径断言

**LLM 语义审查**（五维评分，与 `test-case-quality-evaluator` skill 对齐）：

| 维度 | 权重 | 说明 |
|------|------|------|
| 需求覆盖面 | 35% | 每条 Rule 是否有对应用例？正向/异常/边界是否齐全？ |
| 用例类型覆盖 | 20% | 正向/反向/边界/异常/状态/权限/并发/集成/降级 |
| 结构与可操作性 | 20% | 步骤原子化、预期可验证、必填字段非空 |
| 逻辑规范符合性 | 15% | 场景独立性、预期可追溯到 Rule、同义反复检测 |
| 格式完整度 | 10% | 编号连续、标题简明、来源引用完整 |

评分公式：`score = 100 - (critical × 15) - (warnings × 5) - (suggestions × 2)`

## 快速开始

### 1. 安装

```bash
cd testcase-agent
pip install -r requirements.txt   # openai + openpyxl
# 可选: pip install python-docx pdfplumber  # .docx/.pdf PRD 支持
```

### 2. 配置 LLM

```bash
cp .env.example .env
# 编辑 .env，填入你的 API 配置。与 agentscope-testgen 共用同一套格式：
#   LLM_PROVIDER=openai
#   LLM_BASE_URL=https://your-api-gateway.com
#   LLM_MODEL=deepseek-v4-pro
#   OPENAI_API_KEY=sk-your-key
```

### 3. 运行

```bash
# 纯 PRD 模式（最简）
python main.py --prd docs/prd/mall-stay-strategy.md --module mallstay

# PRD + 代码模式（自动从 Controller/Service 抽取校验规则）
python main.py \
  --prd docs/prd/mall-stay-strategy.md \
  --code ../com/src/main/java/.../Controller.java \
  --code ../com/src/main/java/.../Service.java \
  --module mallstay

# 完整三输入 + 风格参考 + 双格式输出
python main.py \
  --prd docs/prd.md \
  --code Controller.java \
  --design docs/design.md \
  --module mallstay \
  --few-shot output/prev_cases.xlsx \
  --format xlsx,xmind

# 快速出稿（跳过审查修复循环）
python main.py --prd docs/prd.md --module mymodule --no-review --format xlsx
```

### 4. 输出

```
output/<module>/
├── rules_<module>_<ts>.json           # 中间产物：规则清单（可审查）
├── candidate_cases_<module>_<ts>.json # 中间产物：审查前的用例
├── review_report_<module>_<ts>.json   # 审查报告（五维 + issue 清单）
├── test_cases_<module>_<ts>.xlsx      # 最终产物：Excel 用例表
└── test_cases_<module>_<ts>.xmind     # 最终产物：XMind 思维导图
```

## 模块级配置（可选）

为每个模块创建 `context/<module>/` 目录，放置两个可选文件：

### `scope.md` — 组织分工边界

声明不在本团队测试范围的内容，审查时不会因此扣分：

```markdown
# scope.md — 测试范围声明

## 不在测试范围
- 基础信息页的数据本质规则：由产品团队验收
- 上传平台嵌入页面：属第三方提供
- 计算逻辑/调拨数量公式：归其他团队负责

## 例外说明
本项目异常场景占比 ~16% 属正常范围，不按 20%~40% 标准扣分。
```

### `glossary.md` — 领域术语表

防止 LLM 幻觉，注入规则抽取上下文：

```markdown
# glossary.md — 领域术语表

## code 语义
- 0 = 业务成功
- 2 = 参数校验失败（@Validated 拦截）
- 500 = 业务规则拒绝（BusinessException）
- -1 = 未捕获系统异常

```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--prd` | PRD/需求文档路径 (.md/.docx/.pdf/.txt) | — |
| `--code` | Java 源文件路径（可多次指定） | — |
| `--design` | 设计文档路径 | — |
| `--module` | 模块名 | `default` |
| `--context-dir` | context/ 目录路径 | `testcase-agent/context/` |
| `--output-dir` | 输出目录 | `output/<module>/` |
| `--format` | 输出格式（逗号分隔: `xlsx,xmind`） | `xlsx,xmind` |
| `--few-shot` | 已有用例文件作为风格参考（可多次指定） | — |
| `--max-rounds` | 最大审查-修复轮数 | `3` |
| `--no-review` | 跳过审查修复循环 | `false` |
| `--force-sources` | 限定规则抽取来源: `all`/`prd_only`/`code_only` | `all` |
| `--env` | .env 文件路径 | `testcase-agent/.env` |

> 至少需要一个输入源（`--prd` / `--code` / `--design`），缺失项自动跳过对应来源标记。

## 目录结构

```
testcase-agent/
├── main.py                        # CLI 入口
├── .env.example                   # LLM 配置模板
├── requirements.txt               # openai + openpyxl
│
├── schemas/
│   └── models.py                  # 核心数据类型（dataclass，无 LLM 依赖）
├── parsers/
│   ├── prd_parser.py              # 多格式文档读取 + scope/glossary 加载
│   └── code_parser.py             # Java Controller/Service 静态分析
├── agents/
│   ├── llm_client.py              # .env 驱动 + OpenAI 薄封装
│   ├── input_collector.py        # Stage 1: 输入收集（纯规则）
│   ├── rule_extractor.py         # Stage 2: 规则抽取（LLM + 三方对齐）
│   ├── case_designer.py          # Stage 3: 用例设计（LLM + 铁律约束）
│   ├── reviewer.py               # Stage 4: 审查（规则引擎 + LLM 混合）
│   ├── fixer.py                  # Stage 5: 局部修复
│   └── orchestrator.py           # 编排 + 审查-修复循环
├── exporters/
│   ├── excel_writer.py            # 标准 10 列 Excel
│   └── xmind_writer.py            # XMind content.json 树
├── prompts/
│   ├── rule_extractor_prompt.md
│   ├── case_designer_prompt.md    # ★ 四条铁律在此
│   └── reviewer_prompt.md        # 五维评分标准
└── context/<module>/
    ├── scope.md                   # 可选：测试范围边界
    └── glossary.md                # 可选：领域术语表
```

