"""
Rule Extractor — RawInputs → Rule[] via LLM with tri-party alignment.

Uses the rule_extractor_prompt.md template and RawInputs to produce
a structured list of business rules with tri-party diff marks.
"""

import json
from pathlib import Path
from typing import List

from agents.llm_client import LLMClient
from schemas.models import RawInputs, Rule, Source, ConstraintType, DiffMark


PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "rule_extractor_prompt.md"


class RuleExtractor:
    """Extract structured business rules from raw inputs using LLM."""

    def __init__(self, client: LLMClient):
        self.client = client
        self.system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def extract(self, raw: RawInputs, force_sources: str = "all") -> List[Rule]:
        """Extract rules from all available sources.

        Args:
            raw: Collected raw inputs.
            force_sources: "all" / "prd_only" / "code_only" — useful for testing.

        Returns:
            List of Rule objects.
        """
        if not raw.has_any():
            print("⚠️  无任何输入，无法抽取规则")
            return []

        user_msg = self._build_user_message(raw, force_sources)
        print(f"🧠 规则抽取中（输入约 {len(user_msg)} 字符）...")

        try:
            result = self.client.chat_json(self.system_prompt, user_msg)
            rules_raw = result.get("rules", [])
            print(f"   抽取到 {len(rules_raw)} 条规则")
        except Exception as e:
            print(f"⚠️  LLM 规则抽取失败: {e}")
            return []

        return self._parse_rules(rules_raw)

    def _build_user_message(self, raw: RawInputs, force_sources: str) -> str:
        parts = []

        if raw.prd_text and force_sources in ("all", "prd_only"):
            parts.append(f"## 需求文档 (PRD)\n\n{raw.prd_text[:8000]}")

        if raw.design_text and force_sources in ("all",):
            parts.append(f"## 设计文档\n\n{raw.design_text[:4000]}")

        if raw.code_facts and force_sources in ("all", "code_only"):
            facts_text = self._format_code_facts(raw.code_facts)
            parts.append(f"## 代码事实\n\n{facts_text}")

        if raw.scope_md:
            parts.append(f"## 组织分工边界（以下内容不在本团队测试范围，不出规则）\n\n{raw.scope_md}")

        if raw.glossary_md:
            parts.append(f"## 领域术语表（用于消歧义，防止幻觉）\n\n{raw.glossary_md}")

        parts.append("\n请输出 JSON，包含所有识别到的可测试业务规则。")
        return "\n\n".join(parts)

    def _format_code_facts(self, facts: List) -> str:
        """Format CodeFacts as a compact text table."""
        lines = ["| API路径 | 方法 | 分类 | 约束类型 | 字段 | 详情 | 消息 |",
                 "|---------|------|------|---------|------|------|------|"]
        for f in facts:
            lines.append(
                f"| {f.api_path} | {f.api_method} | {f.category} | "
                f"{f.constraint_type.value} | {f.field} | {f.detail} | {f.message or ''} |"
            )
        return "\n".join(lines[:100])  # Cap at 100 rows to avoid token explosion

    @staticmethod
    def _parse_rules(raw_list: list) -> List[Rule]:
        """Convert raw JSON dicts to Rule dataclasses."""
        rules = []
        for item in raw_list:
            try:
                rules.append(Rule(
                    id=item.get("id", "RULE-???"),
                    source=Source(item.get("source", "prd")),
                    module=item.get("module", ""),
                    field=item.get("field", ""),
                    constraint_type=ConstraintType(item.get("constraint_type", "business_rule")),
                    description=item.get("description", ""),
                    expected_behavior=item.get("expected_behavior", ""),
                    citation=item.get("citation", ""),
                    diff_mark=DiffMark(item.get("diff_mark", "")) if item.get("diff_mark") else DiffMark.CONSISTENT,
                    depends_on=item.get("depends_on", []),
                ))
            except (ValueError, TypeError) as e:
                print(f"⚠️  跳过无法解析的 Rule: {item.get('id','?')} — {e}")
        return rules
