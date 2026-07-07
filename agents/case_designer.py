"""
Case Designer — Rule[] → TestCase[] via LLM, with hardcoded iron rules.

This is the core intelligence of the framework. The system prompt encodes
lessons from [[ui-test-spec-vs-status-quo]] and other project memory.
"""

import json
from pathlib import Path
from typing import List, Optional

from agents.llm_client import LLMClient
from schemas.models import Rule, TestCase, CaseType, Priority


PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "case_designer_prompt.md"

# Max rules per LLM batch to keep context manageable
BATCH_SIZE = 30


class CaseDesigner:
    """Design structured test cases from business rules using LLM."""

    def __init__(self, client: LLMClient):
        self.client = client
        self._base_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def design(self, rules: List[Rule],
               few_shot_text: Optional[str] = None) -> List[TestCase]:
        """Generate test cases covering all rules.

        Args:
            rules: Extracted business rules.
            few_shot_text: Style-reference examples (NOT content authority).

        Returns:
            List of TestCase objects.
        """
        if not rules:
            print("⚠️  无规则输入，无法生成测试用例")
            return []

        # Build system prompt with few-shot injected
        system = self._build_system_prompt(few_shot_text)

        all_cases: List[TestCase] = []
        # Process rules in batches if there are many
        for i in range(0, len(rules), BATCH_SIZE):
            batch = rules[i:i + BATCH_SIZE]
            batch_label = f"({i + 1}-{min(i + BATCH_SIZE, len(rules))}/{len(rules)})"
            print(f"🧠 用例设计中 {batch_label}，{len(batch)} 条规则...")

            user_msg = self._build_user_message(batch)
            try:
                result = self.client.chat_json(system, user_msg,
                                               temperature=0.4, max_tokens=8000)
                cases_raw = result.get("cases", [])
                parsed = self._parse_cases(cases_raw)
                all_cases.extend(parsed)
                print(f"   生成 {len(parsed)} 条用例")
            except Exception as e:
                print(f"⚠️  用例生成失败: {e}")
                continue

        # Re-index IDs for global uniqueness
        self._re_index(all_cases)

        return all_cases

    def design_fix(self, rules: List[Rule],
                   fix_instructions: List[str],
                   affected_case_ids: List[str],
                   existing_cases: List[TestCase]) -> List[TestCase]:
        """Re-generate only affected cases based on review fix instructions.

        Args:
            rules: All rules (context).
            fix_instructions: What to fix.
            affected_case_ids: Which case IDs need regeneration.
            existing_cases: All current cases (unaffected ones are preserved).

        Returns:
            Merged list: unaffected original + regenerated affected.
        """
        fix_prompt = "## 修复指示\n" + "\n".join(f"- {f}" for f in fix_instructions)
        fix_prompt += "\n\n## 受影响的用例 ID（只需重新生成这些）\n"
        fix_prompt += ", ".join(affected_case_ids)
        fix_prompt += "\n\n请只输出这些用例的修正版本 JSON。每个用例保留原 id。"

        rules_text = self._rules_to_text(rules)
        user_msg = f"## 业务规则\n{rules_text}\n\n{fix_prompt}"

        system = self._build_system_prompt(None)

        try:
            result = self.client.chat_json(system, user_msg,
                                           temperature=0.3, max_tokens=6000)
            fixed_raw = result.get("cases", [])
            fixed_cases = self._parse_cases(fixed_raw)

            # Merge: keep unaffected, replace affected
            fixed_ids = {c.id for c in fixed_cases}
            merged = [c for c in existing_cases if c.id not in fixed_ids]
            merged.extend(fixed_cases)
            return merged
        except Exception as e:
            print(f"⚠️  修复生成失败: {e}")
            return existing_cases

    def _build_system_prompt(self, few_shot_text: Optional[str]) -> str:
        prompt = self._base_prompt
        if few_shot_text:
            prompt = prompt.replace("{{FEW_SHOT}}", few_shot_text)
        else:
            prompt = prompt.replace("{{FEW_SHOT}}",
                                    "(无 Few-shot 示例，请完全基于输入的规则清单设计用例)")
        return prompt

    def _build_user_message(self, rules: List[Rule]) -> str:
        rules_text = self._rules_to_text(rules)
        return f"""## 业务规则清单

{rules_text}

请基于以上规则生成完整的测试用例 JSON。确保：
1. 每条规则至少有一条对应用例（正向或反向）
2. 唯一性约束/必填校验/业务规则的拒绝路径有正向拒绝用例
3. 异常场景（反向+边界+异常类型）占比 20%-40%
"""

    @staticmethod
    def _rules_to_text(rules: List[Rule]) -> str:
        lines = ["| ID | 来源 | 模块 | 字段 | 类型 | 描述 | 预期行为 | 引用 | 差异 |",
                 "|----|------|------|------|------|------|---------|------|------|"]
        for r in rules:
            diff = r.diff_mark.value if r.diff_mark.value else "-"
            lines.append(
                f"| {r.id} | {r.source.value} | {r.module} | {r.field} | "
                f"{r.constraint_type.value} | {r.description} | "
                f"{r.expected_behavior} | {r.citation} | {diff} |"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_cases(raw_list: list) -> List[TestCase]:
        """Convert raw JSON dicts to TestCase dataclasses."""
        cases = []
        for item in raw_list:
            try:
                cases.append(TestCase(
                    id=item.get("id", "TC-UNKNOWN-000"),
                    module=item.get("module", ""),
                    title=item.get("title", ""),
                    case_type=CaseType(item.get("case_type", "正向")),
                    priority=Priority(item.get("priority", "P2")),
                    precondition=item.get("precondition", ""),
                    steps=item.get("steps", ""),
                    expected=item.get("expected", ""),
                    source=item.get("source", ""),
                    remark=item.get("remark", ""),
                    trace_rules=item.get("trace_rules", []),
                ))
            except (ValueError, TypeError) as e:
                print(f"⚠️  跳过无法解析的 TestCase: {item.get('id','?')} — {e}")
        return cases

    @staticmethod
    def _re_index(cases: List[TestCase]):
        """Re-index case IDs for consistent numbering."""
        # Group by module prefix
        by_prefix = {}
        for c in cases:
            prefix = c.id.rsplit("-", 1)[0] if "-" in c.id else "TC-XX"
            by_prefix.setdefault(prefix, []).append(c)

        for prefix, group in by_prefix.items():
            for idx, case in enumerate(group, start=1):
                case.id = f"{prefix}-{idx:03d}"
