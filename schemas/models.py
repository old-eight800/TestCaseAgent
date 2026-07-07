"""
Core data models for test case agent framework.

All dataclasses are LLM-free, serialisable, and independently unit-testable.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class ConstraintType(str, Enum):
    """业务约束类型"""
    REQUIRED = "required"               # 必填
    SIZE_RANGE = "size_range"           # 长度/大小范围
    VALUE_RANGE = "value_range"         # 数值范围 (min/max)
    ENUM = "enum"                       # 枚举值约束
    FORMAT = "format"                   # 格式校验 (email/phone/date)
    UNIQUE = "unique"                   # 唯一性约束
    FOREIGN_KEY = "foreign_key"         # 外键/关联存在性
    STATE_GUARD = "state_guard"         # 状态守卫 (if status==X)
    BUSINESS_RULE = "business_rule"     # 业务计算/逻辑规则
    PERMISSION = "permission"           # 权限/鉴权
    CONCURRENCY = "concurrency"         # 并发/分布式锁


class Source(str, Enum):
    """规则来源"""
    PRD = "prd"
    CODE = "code"
    DESIGN = "design"


class DiffMark(str, Enum):
    """三方差异标记"""
    CONSISTENT = ""                              # 三方一致
    CODE_NEEDS_PRD = "[代码-需求差异]"            # 代码有但需求未声明
    CODE_NEEDS_DESIGN = "[代码-设计差异]"         # 代码有但设计未体现
    DESIGN_NEEDS_CODE = "[设计-代码差异]"         # 设计有但代码未实现
    PRD_NEEDS_DESIGN = "[需求-设计差异]"          # 需求未在设计分解


class CaseType(str, Enum):
    """用例类型"""
    HAPPY = "正向"
    REVERSE = "反向"
    BOUNDARY = "边界"
    EXCEPTION = "异常"
    STATE = "状态"
    PERMISSION = "权限"
    CONCURRENCY = "并发"
    INTEGRATION = "集成"
    DEGRADATION = "降级"


class Priority(str, Enum):
    """用例优先级"""
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


@dataclass
class CodeFact:
    """从代码静态提取的约束事实"""
    file: str                                    # 源文件路径
    line: int                                    # 行号（近似）
    api_path: str                                # 所属接口路径
    api_method: str                              # HTTP 方法
    category: str                                # query / write / upload / stream
    constraint_type: ConstraintType
    field: str                                   # 字段名
    detail: str                                  # 原始文本（如 @Size(min=1,max=100)）
    message: Optional[str] = None                # 异常消息文案

    def citation(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class Rule:
    """从代码/PRD/设计三者对齐后抽取的单一业务规则"""
    id: str                                      # RULE-001
    source: Source
    module: str                                  # 所属功能模块
    field: str                                   # 涉及字段（无则为空）
    constraint_type: ConstraintType
    description: str                             # 自然语言描述 (e.g. "策略名称全局唯一")
    expected_behavior: str                       # 违规时的预期行为
    citation: str                                # 来源引用（PRD§3.2.1 / File.java:45）
    diff_mark: DiffMark = DiffMark.CONSISTENT
    depends_on: List[str] = field(default_factory=list)   # 依赖的规则 ID


@dataclass
class TestCase:
    """单条测试用例"""
    id: str                                      # TC-XX-001
    module: str                                  # 测试模块
    title: str                                   # 用例标题
    case_type: CaseType                          # 用例类型
    priority: Priority                           # 优先级
    precondition: str                            # 前置条件
    steps: str                                   # 操作步骤（多步骤用 \n 分隔）
    expected: str                                # 预期结果（必须可验证、可追溯）
    source: str                                  # 来自哪些 Rule ID
    remark: str = ""                             # 差异标记/假设规则等备注
    trace_rules: List[str] = field(default_factory=list)  # 关联的 Rule ID 列表


@dataclass
class ReviewIssue:
    """审查发现的问题"""
    severity: str                                # critical / warning / suggestion
    dimension: str                               # 审查维度
    location: str                                # 问题位置（用例 ID 或字段名）
    description: str
    fix: str                                     # 修复建议


@dataclass
class ReviewReport:
    """审查报告"""
    total_issues: int = 0
    critical: int = 0
    warnings: int = 0
    suggestions: int = 0
    issues: List[ReviewIssue] = field(default_factory=list)
    score: int = 100
    dimensions: dict = field(default_factory=dict)   # 各维度得分
    fix_instructions: List[str] = field(default_factory=list)

    def is_passing(self) -> bool:
        return self.critical == 0 and self.score >= 60


@dataclass
class RawInputs:
    """原始输入集合（Stage 1 产出）"""
    prd_text: str = ""
    code_facts: List[CodeFact] = field(default_factory=list)
    design_text: str = ""
    module: str = ""
    scope_md: Optional[str] = None              # context/<module>/scope.md 的文本
    glossary_md: Optional[str] = None            # context/<module>/glossary.md 的文本

    def has_any(self) -> bool:
        return bool(self.prd_text or self.code_facts or self.design_text)
