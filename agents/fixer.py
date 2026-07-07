"""
Fixer — applies review fix instructions by regenerating affected cases only.

Unlike the full case_designer, this targets only the cases flagged in
the review report, preserving unaffected cases untouched.
"""

from typing import List, Optional

from agents.llm_client import LLMClient
from agents.case_designer import CaseDesigner
from schemas.models import ReviewReport, TestCase, Rule


class Fixer:
    """Regenerate only the test cases affected by review findings."""

    def __init__(self, client: LLMClient):
        self.client = client
        self.designer = CaseDesigner(client)

    def fix(self, report: ReviewReport, cases: List[TestCase],
            rules: List[Rule]) -> List[TestCase]:
        """Apply fixes to affected cases.

        Strategy:  Extract affected case IDs from report issues,
        then use CaseDesigner.design_fix() to regenerate only those.

        Args:
            report: Review findings.
            cases: Current test cases.
            rules: Business rules.

        Returns:
            Updated list of test cases.
        """
        if report.is_passing():
            print("   ✅ 审查通过，无需修复")
            return cases

        # Extract affected case IDs from issues
        affected_ids = set()
        for issue in report.issues:
            if issue.location and issue.location.startswith("TC-"):
                affected_ids.add(issue.location)

        if not affected_ids:
            # Issues are global, regenerate all
            print(f"   🔄 全局问题，全量修复")
            return self.designer.design(rules)

        print(f"   🔄 局部修复 {len(affected_ids)} 条用例: {', '.join(sorted(affected_ids))}")
        return self.designer.design_fix(
            rules=rules,
            fix_instructions=report.fix_instructions,
            affected_case_ids=list(affected_ids),
            existing_cases=cases,
        )
