"""
Reviewer — hybrid: rule-engine hard checks + LLM semantic review.

Rule-engine checks are fast and deterministic (no LLM needed).
LLM checks cover semantic dimensions (同义反复, coverage completeness).
"""

import json
import re
from pathlib import Path
from typing import List, Optional

from agents.llm_client import LLMClient
from schemas.models import TestCase, Rule, ReviewReport, ReviewIssue, CaseType


PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "reviewer_prompt.md"


class Reviewer:
    """Hybrid reviewer: rule engine + LLM."""

    def __init__(self, client: LLMClient):
        self.client = client
        self._llm_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def review(self, cases: List[TestCase], rules: List[Rule],
               scope_text: Optional[str] = None,
               use_llm: bool = True) -> ReviewReport:
        """Run full review: rule-engine first, then LLM semantic check.

        Args:
            cases: Generated test cases.
            rules: Business rules they should cover.
            scope_text: Optional scope.md content for exception ratio threshold.
            use_llm: If False, skip LLM semantic review (fast mode).
        """
        report = ReviewReport()

        # 1. Rule-engine checks (fast, deterministic, always runs)
        self._check_fields_non_empty(cases, report)
        self._check_ids_unique(cases, report)
        self._check_titles_unique(cases, report)
        self._check_vague_expected(cases, report)
        self._check_exception_ratio(cases, report, scope_text)
        self._check_rule_coverage(cases, rules, report)
        self._check_rejection_paths(cases, rules, report)

        # 2. LLM semantic review (optional, slower/$$$)
        if use_llm:
            self._llm_review(cases, rules, report)

        # 3. Compute score
        self._compute_score(report)

        return report

    # ── Rule-engine checks ────────────────────────────────────────

    def _check_fields_non_empty(self, cases: List[TestCase], report: ReviewReport):
        """Check required fields are non-empty."""
        required = ["title", "module", "precondition", "steps", "expected"]
        for c in cases:
            for field in required:
                val = getattr(c, field, "")
                if not val or val.strip() == "":
                    report.critical += 1
                    report.issues.append(ReviewIssue(
                        "critical", "字段完整性", c.id,
                        f"必填字段 '{field}' 为空",
                        f"为 {c.id} 填写 {field}"
                    ))

    def _check_ids_unique(self, cases: List[TestCase], report: ReviewReport):
        seen = {}
        for c in cases:
            if c.id in seen:
                report.critical += 1
                report.issues.append(ReviewIssue(
                    "critical", "编号唯一性", c.id,
                    f"用例编号重复: {c.id} 与 {seen[c.id].id} 相同",
                    f"将 {c.id} 重新编号"
                ))
            seen[c.id] = c

    def _check_titles_unique(self, cases: List[TestCase], report: ReviewReport):
        seen = {}
        for c in cases:
            if c.title in seen:
                report.warnings += 1
                report.issues.append(ReviewIssue(
                    "warning", "标题唯一性", c.id,
                    f"用例标题重复: '{c.title}' 与 {seen[c.title]} 相同",
                    f"请区分 {c.id} 和 {seen[c.title]} 的标题"
                ))
            seen[c.title] = c.id

    def _check_vague_expected(self, cases: List[TestCase], report: ReviewReport):
        vague = re.compile(
            r'^(成功|正常|正确|OK|ok|通过|无异常|没问题|正常显示|功能正常)$'
        )
        for c in cases:
            expected_stripped = c.expected.strip()
            if vague.match(expected_stripped):
                report.warnings += 1
                report.issues.append(ReviewIssue(
                    "warning", "预期结果质量", c.id,
                    f"预期结果模糊: '{c.expected}'（无具体可验证条件）",
                    f"改为可验证的具体断言（如 'code=0; DB 中 status 字段更新为 1'）"
                ))

    def _check_exception_ratio(self, cases: List[TestCase], report: ReviewReport,
                                scope_text: Optional[str] = None):
        """Check that exception/negative/boundary cases are 20%-40%.

        If scope.md declares an explicit exception (like [[mall-liuhuo-test-scope]]
        16% acceptable), use that threshold instead.
        """
        if not cases:
            return

        exception_types = {CaseType.REVERSE, CaseType.BOUNDARY, CaseType.EXCEPTION,
                           CaseType.CONCURRENCY, CaseType.DEGRADATION}
        exception_count = sum(1 for c in cases if c.case_type in exception_types)
        ratio = exception_count / len(cases) * 100

        # Check if scope overrides the threshold
        low_threshold = 20.0
        if scope_text:
            m = re.search(r'异常场景[占比例]+\s*~?\s*(\d+)%', scope_text)
            if m:
                low_threshold = float(m.group(1))

        if ratio < low_threshold:
            report.warnings += 1
            report.issues.append(ReviewIssue(
                "warning", "异常场景占比", "全局",
                f"异常场景占比仅 {ratio:.0f}%（低于 {low_threshold:.0f}%）",
                f"补充反向/边界/异常用例，建议增加 {int((low_threshold/100)*len(cases)-exception_count)} 条"
            ))

    def _check_rule_coverage(self, cases: List[TestCase], rules: List[Rule],
                              report: ReviewReport):
        """Check that every rule has at least one test case."""
        covered = set()
        for c in cases:
            for rule_id in c.trace_rules:
                covered.add(rule_id)

        for r in rules:
            if r.id not in covered:
                report.warnings += 1
                report.issues.append(ReviewIssue(
                    "warning", "规则覆盖", r.id,
                    f"规则 {r.id} ({r.description}) 无对应用例",
                    f"为 {r.id} 添加至少一条用例（正向或反向）"
                ))

    def _check_rejection_paths(self, cases: List[TestCase], rules: List[Rule],
                                report: ReviewReport):
        """For rules with unique/business_rule/required constraints, verify
        at least one case asserts the rejection path (not bypasses it)."""
        rejection_types = {"unique", "business_rule", "required", "permission",
                           "state_guard", "concurrency"}

        for r in rules:
            if r.constraint_type.value not in rejection_types:
                continue
            # Check if any case for this rule is a rejection assertion
            rule_cases = [c for c in cases if r.id in c.trace_rules]
            if not rule_cases:
                continue  # already caught by _check_rule_coverage

            has_rejection = any(
                c.case_type in (CaseType.REVERSE, CaseType.EXCEPTION,
                                CaseType.PERMISSION, CaseType.CONCURRENCY)
                or "拒绝" in c.expected
                or "≠" in c.expected
                or "!=" in c.expected
                or "不应" in c.expected
                or "错误" in c.expected
                or "失败" in c.expected
                for c in rule_cases
            )

            if not has_rejection:
                report.warnings += 1
                report.issues.append(ReviewIssue(
                    "warning", "拒绝路径覆盖", r.id,
                    f"规则 {r.id} ({r.description}) 缺少拒绝路径断言——"
                    "所有用例都是正向 happy path",
                    f"为 {r.id} 添加一条预期拒绝的用例（如图绕过去→正向断言拒绝触发）"
                ))

    # ── LLM semantic review ────────────────────────────────────────

    def _llm_review(self, cases: List[TestCase], rules: List[Rule],
                     report: ReviewReport):
        """Run LLM-based semantic review following the five-dimension framework."""
        cases_json = json.dumps(
            [{
                "id": c.id, "module": c.module, "title": c.title,
                "case_type": c.case_type.value, "priority": c.priority.value,
                "precondition": c.precondition, "steps": c.steps,
                "expected": c.expected, "source": c.source, "remark": c.remark,
            } for c in cases],
            ensure_ascii=False, indent=2
        )

        rules_json = json.dumps(
            [{"id": r.id, "description": r.description,
              "expected_behavior": r.expected_behavior} for r in rules],
            ensure_ascii=False, indent=2
        )

        user_msg = f"""## 业务规则
{rules_json}

## 测试用例
{cases_json[:8000]}

## 已由规则引擎发现的问题（不要重复报）
{json.dumps([{'severity': i.severity, 'description': i.description} for i in report.issues], ensure_ascii=False)}

请按五维评分标准进行语义审查，输出 JSON。"""

        try:
            result = self.client.chat_json(self._llm_prompt, user_msg,
                                           temperature=0.2, max_tokens=4000)
            # Merge LLM findings
            for issue_text in result.get("critical_issues", []):
                report.critical += 1
                report.issues.append(ReviewIssue(
                    "critical", "语义审查", "全局", issue_text, ""
                ))
            for issue_text in result.get("warnings", []):
                report.warnings += 1
                report.issues.append(ReviewIssue(
                    "warning", "语义审查", "全局", issue_text, ""
                ))
            report.fix_instructions = result.get("fix_instructions", [])
            report.dimensions = result.get("dimensions", {})
            report.score = result.get("score", report.score)
        except Exception as e:
            print(f"⚠️  LLM 审查失败，仅使用规则引擎结果: {e}")

    # ── Scoring ────────────────────────────────────────────────────

    def _compute_score(self, report: ReviewReport):
        """Score = 100 - (critical * 15) - (warnings * 5) - (suggestions * 2)."""
        report.total_issues = len(report.issues)
        report.critical = sum(1 for i in report.issues if i.severity == "critical")
        report.warnings = sum(1 for i in report.issues if i.severity == "warning")
        report.suggestions = sum(1 for i in report.issues if i.severity == "suggestion")
        report.score = max(0, 100 - report.critical * 15
                                 - report.warnings * 5
                                 - report.suggestions * 2)
