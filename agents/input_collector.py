"""
Input Collector — gathers PRD/code/design inputs into RawInputs (no LLM needed).
"""

from pathlib import Path
from typing import List, Optional

from schemas.models import RawInputs, CodeFact
from parsers.prd_parser import read_prd, load_scope, load_glossary
from parsers.code_parser import parse_java


class InputCollector:
    """Collect and pre-process all inputs before the LLM pipeline."""

    def collect(self,
                prd_path: Optional[str] = None,
                code_paths: Optional[List[str]] = None,
                design_path: Optional[str] = None,
                module: str = "default",
                context_dir: Optional[str] = None) -> RawInputs:
        """
        Gather all input sources into RawInputs.

        Args:
            prd_path: Path to PRD document (.md/.docx/.pdf/.txt)
            code_paths: List of Java source file paths
            design_path: Path to design document
            module: Module name (used for loading scope/glossary)
            context_dir: Override context directory
        """
        raw = RawInputs(module=module)

        # PRD
        if prd_path:
            print(f"📄 读取 PRD: {prd_path}")
            raw.prd_text = read_prd(prd_path)
            print(f"   {len(raw.prd_text)} 字符")

        # Code
        if code_paths:
            for cp in code_paths:
                path = Path(cp)
                if not path.exists():
                    # Try relative to project root
                    alt = Path(__file__).parent.parent.parent / cp
                    if alt.exists():
                        path = alt
                    else:
                        print(f"⚠️  代码文件不存在，跳过: {cp}")
                        continue
                print(f"📝 解析代码: {path.name}")
                try:
                    facts = parse_java(str(path), module)
                    print(f"   提取 {len(facts)} 个代码事实")
                    raw.code_facts.extend(facts)
                except Exception as e:
                    print(f"⚠️  解析失败: {path} — {e}")

        # Design
        if design_path:
            print(f"📐 读取设计文档: {design_path}")
            raw.design_text = read_prd(design_path)
            print(f"   {len(raw.design_text)} 字符")

        # Context (scope + glossary)
        raw.scope_md = load_scope(module, context_dir)
        if raw.scope_md:
            print(f"📋 加载 scope.md: {len(raw.scope_md)} 字符")
        raw.glossary_md = load_glossary(module, context_dir)
        if raw.glossary_md:
            print(f"📖 加载 glossary.md: {len(raw.glossary_md)} 字符")

        return raw
