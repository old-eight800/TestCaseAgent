#!/usr/bin/env python3
"""
TestCase Agent — 多智能体测试用例编写框架

基于 PRD / 代码 / 设计文档生成结构化测试用例（Excel + XMind），
内置审查-修复闭环，锚定规格而非现状。

用法:
    # 纯 PRD 模式
    python main.py --prd docs/prd.md --module mymodule

    # PRD + 代码模式
    python main.py --prd docs/prd.md --code ../ai-products/.../Controller.java --module mallstay

    # 完整三输入
    python main.py --prd docs/prd.md --code Controller.java --code Service.java --design design.md --module test

    # Few-shot 风格参考 + 指定输出格式
    python main.py --module mallstay --prd prd.md --few-shot prev_cases.xlsx --format xlsx,xmind

    # 跳过审查（快速出稿）
    python main.py --module mallstay --prd prd.md --no-review
"""

import argparse
import sys
from pathlib import Path

# Ensure the project root is on sys.path for module imports
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.orchestrator import Orchestrator


def main():
    parser = argparse.ArgumentParser(
        description="TestCase Agent — 多智能体测试用例编写框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --prd docs/prd.md --module mallstay
  %(prog)s --prd docs/prd.md --code ServerController.java --module oversea
  %(prog)s --module repaire --code Controller.java --code Service.java
  %(prog)s --prd prd.md --few-shot prev.xlsx --no-review
        """,
    )

    # ── Input sources ─────────────────────────────────────────────
    parser.add_argument("--prd", dest="prd_path", default=None,
                        help="PRD / 需求文档路径 (.md/.docx/.pdf/.txt)")
    parser.add_argument("--code", dest="code_paths", action="append", default=None,
                        help="Java 源文件路径（可重复多次，如 --code A.java --code B.java）")
    parser.add_argument("--design", dest="design_path", default=None,
                        help="设计文档路径")

    # ── Module & context ──────────────────────────────────────────
    parser.add_argument("--module", default="default",
                        help="模块名（用于 output/<module>/ 和 context/<module>/ 加载）")
    parser.add_argument("--context-dir", default=None,
                        help="context/ 目录路径（默认: testcase-agent/context/）")

    # ── Output ────────────────────────────────────────────────────
    parser.add_argument("--output-dir", default=None,
                        help="输出目录（默认: output/<module>/）")
    parser.add_argument("--format", default="xlsx,xmind",
                        help="输出格式，逗号分隔（默认: xlsx,xmind）")

    # ── Few-shot ──────────────────────────────────────────────────
    parser.add_argument("--few-shot", dest="few_shot_paths", action="append",
                        default=None,
                        help="已有用例文件路径作为风格参考（可多次指定）")

    # ── Pipeline control ──────────────────────────────────────────
    parser.add_argument("--max-rounds", type=int, default=3,
                        help="最大审查-修复轮数（默认: 3）")
    parser.add_argument("--no-review", action="store_true",
                        help="跳过审查修复循环（快速出稿）")
    parser.add_argument("--force-sources", default="all",
                        choices=["all", "prd_only", "code_only"],
                        help="限定规则抽取来源（默认: all）")
    parser.add_argument("--env", dest="env_path", default=None,
                        help=".env 文件路径（默认: testcase-agent/.env）")

    args = parser.parse_args()

    # Validate: at least one input source
    if not args.prd_path and not args.code_paths and not args.design_path:
        print("❌ 至少需要提供一个输入源: --prd / --code / --design")
        parser.print_help()
        sys.exit(1)

    # Validate code files exist
    if args.code_paths:
        for cp in args.code_paths:
            p = Path(cp)
            if not p.exists():
                alt = PROJECT_ROOT.parent / cp
                if not alt.exists():
                    print(f"⚠️  代码文件不存在: {cp} (已跳过)")

    # Run
    orch = Orchestrator()
    result = orch.run(
        module=args.module,
        prd_path=args.prd_path,
        code_paths=args.code_paths,
        design_path=args.design_path,
        few_shot_paths=args.few_shot_paths,
        output_dir=args.output_dir,
        formats=args.format,
        max_rounds=args.max_rounds,
        force_sources=args.force_sources,
        context_dir=args.context_dir,
        no_review=args.no_review,
    )

    # Summary
    print("\n" + "=" * 60)
    print("📊 Pipeline 结果摘要")
    print(f"   状态: {result['status']}")
    print(f"   模块: {result.get('module', '-')}")
    print(f"   规则数: {result.get('rules_count', '-')}")
    print(f"   用例数: {result.get('cases_count', '-')}")
    print(f"   审查分数: {result.get('review_score', '-')}/100")
    print(f"   审查轮数: {result.get('review_rounds', '-')}")

    outputs = result.get("output_files", {})
    for fmt, path in outputs.items():
        print(f"   输出 [{fmt}]: {path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
