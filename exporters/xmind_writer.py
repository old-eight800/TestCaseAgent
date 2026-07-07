"""
XMind Writer — exports TestCase[] to .xmind (ZIP archive with content.json).

Tree structure: L1 = module → L2 = case_type → L3 = priority group → leaf = test case.

This structure is compatible with test-case-quality-evaluator's parsing script
which expects L1=module, L2=scenario, leaf=expected_result.
"""

import json
import zipfile
import uuid
from pathlib import Path
from typing import List, Dict

from schemas.models import TestCase


def _make_node(title: str, node_id: str = None) -> dict:
    return {
        "id": node_id or str(uuid.uuid4()),
        "title": title,
        "children": {"attached": []},
    }


def write_xmind(cases: List[TestCase], output_path: str, sheet_title: str = "测试用例") -> str:
    """Write test cases to an XMind file.

    Args:
        cases: Test cases to export.
        output_path: Path for the .xmind file.
        sheet_title: Sheet (tab) title.

    Returns:
        The output path.
    """
    # Group cases: module → case_type → [cases]
    tree: Dict[str, Dict[str, List[TestCase]]] = {}
    for c in cases:
        tree.setdefault(c.module, {}).setdefault(c.case_type.value, []).append(c)

    # Build root topic
    root = _make_node(sheet_title)
    root["structureClass"] = "org.xmind.ui.map.unbalanced"

    for module_name, type_groups in sorted(tree.items()):
        module_node = _make_node(module_name)

        for case_type, cases_in_type in sorted(type_groups.items()):
            type_node = _make_node(f"{case_type} ({len(cases_in_type)})")

            for case in cases_in_type:
                # Leaf node: title (first line) + steps + expected
                title = (
                    f"[{case.priority.value}] {case.title}\n"
                    f"前置: {case.precondition[:80]}\n"
                    f"步骤: {case.steps[:120]}\n"
                    f"预期: {case.expected[:120]}"
                )
                leaf = _make_node(title)

                # Children of leaf: structured fields
                fields = [
                    _make_node(f"用例编号: {case.id}"),
                    _make_node(f"优先级: {case.priority.value}"),
                    _make_node(f"前置条件: {case.precondition}"),
                    _make_node(f"操作步骤: {case.steps}"),
                    _make_node(f"预期结果: {case.expected}"),
                    _make_node(f"来源: {case.source}") if case.source else None,
                    _make_node(f"备注: {case.remark}") if case.remark else None,
                ]
                leaf["children"]["attached"] = [f for f in fields if f is not None]
                type_node["children"]["attached"].append(leaf)

            module_node["children"]["attached"].append(type_node)

        root["children"]["attached"].append(module_node)

    # Build content.json
    content = [{
        "id": str(uuid.uuid4()),
        "title": sheet_title,
        "rootTopic": root,
    }]

    # Write ZIP
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.json", json.dumps(content, ensure_ascii=False, indent=2))
        # XMind also expects metadata.json
        meta = {"creator": {"name": "testcase-agent", "version": "1.0"}}
        zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False))
        # manifest.json
        manifest = {
            "file-entries": {
                "content.json": {},
                "metadata.json": {},
            }
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))

    print(f"🧠 XMind 已保存: {output_path} ({len(cases)} 条用例)")
    return output_path
