"""
Code Parser — statically analyze Java Controller/Service source for test-relevant facts.

Generalised from agentscope-testgen/agents/controller_analyzer.py:
  - Method-splitting by @annotation group + brace matching (proven algorithm)
  - Extended to extract: validation annotations, exception throw sites, state guards

No LLM needed — all regex/rule-driven.
"""

import re
from pathlib import Path
from typing import List, Optional

from schemas.models import CodeFact, ConstraintType


# ── Annotation patterns ─────────────────────────────────────────────
ANNOTATION = {
    "requestMapping": re.compile(r'@RequestMapping\s*\(\s*["\']([^"\']+)["\']'),
    "getMapping":     re.compile(r'@GetMapping\s*\(\s*["\']([^"\']+)["\']'),
    "postMapping":    re.compile(r'@PostMapping\s*\(\s*["\']([^"\']+)["\']'),
    "putMapping":     re.compile(r'@PutMapping\s*\(\s*["\']([^"\']+)["\']'),
    "deleteMapping":  re.compile(r'@DeleteMapping\s*\(\s*["\']([^"\']+)["\']'),
    "apiOperation":   re.compile(r'@ApiOperation\s*\(\s*["\']([^"\']+)["\']'),
    "validated":      re.compile(r'@Validated\b'),
}

# Validation annotations on DTO fields and method parameters
VALIDATION = {
    "notNull":     re.compile(r'@NotNull\b(?:\([^)]*\))?'),
    "notBlank":    re.compile(r'@NotBlank\b(?:\([^)]*\))?'),
    "notEmpty":    re.compile(r'@NotEmpty\b(?:\([^)]*\))?'),
    "size":        re.compile(r'@Size\s*\(([^)]*)\)'),
    "min":         re.compile(r'@Min\s*\(([^)]*)\)'),
    "max":         re.compile(r'@Max\s*\(([^)]*)\)'),
    "pattern":     re.compile(r'@Pattern\s*\(([^)]*)\)'),
    "email":       re.compile(r'@Email\b'),
    "decimalMin":  re.compile(r'@DecimalMin\s*\(([^)]*)\)'),
    "decimalMax":  re.compile(r'@DecimalMax\s*\(([^)]*)\)'),
    "positive":    re.compile(r'@Positive\b'),
    "positiveOrZero": re.compile(r'@PositiveOrZero\b'),
    "negative":    re.compile(r'@Negative\b'),
    "range":       re.compile(r'@Range\s*\(([^)]*)\)'),
}

# Exception throw patterns
THROW = re.compile(
    r'throw\s+new\s+(\w+Exception)\s*(?:\(([^)]*)\))?',
    re.MULTILINE
)

# State-guard: if (status == X || status.equals(Y))
STATE_GUARD = re.compile(
    r'if\s*\(\s*[\w.]+(?:\.equals\([^)]+\)|[!=]=\s*[\w."\']+)',
    re.MULTILINE
)

# Import statements
IMPORT = re.compile(r'import\s+([\w.]+);')

# Swiss-army: @RequestBody parameter name
REQUEST_BODY = re.compile(r'@RequestBody\s+(\w+)\s+(\w+)')

# Custom validator annotations (e.g. @EnumValue, @Phone)
CUSTOM_ANNOTATION = re.compile(r'@(\w+)\s*(?:\()?', re.MULTILINE)

TABLE_MAP = {
    "oversea": ["oversea_strategy_conf", "oversea_strategy_sort",
                 "oversea_strategy_conf_approval", "oversea_strategy_conf_online",
                 "oversea_product_stay_history"],
    "mallstay": ["mall_stay_strategy", "mall_stay_strategy_sort"],
    "repairservice": ["repair_service", "repair_service_maintain"],
    "maintainability": ["maintain_ability"],
    "repaircode": ["repair_code"],
}


class JavaCodeParser:
    """Static analyser for Java Controller and Service source files."""

    def parse_controller(self, file_path: str, module: str = "") -> List[CodeFact]:
        """Parse a Controller file and return structured CodeFacts."""
        source = Path(file_path).read_text(encoding="utf-8")
        file_name = Path(file_path).name

        # Extract class-level metadata
        base_path = self._extract_base_path(source)
        class_match = re.search(r'public\s+class\s+(\w+)', source)
        controller_name = class_match.group(1) if class_match else "Unknown"

        facts: List[CodeFact] = []
        method_blocks = self._split_methods(source)

        for block in method_blocks:
            if not self._is_api_method(block):
                continue

            http_method = self._http_method(block)
            api_path = self._api_path(block)
            full_path = f"{base_path.rstrip('/')}/{api_path.lstrip('/')}".replace("//", "/")
            summary = self._api_summary(block)
            block_line = self._block_line(source, block)

            # 1. Validation annotations
            facts.extend(self._extract_validations(
                block, file_name, block_line, full_path, http_method
            ))

            # 2. Exception throw sites
            facts.extend(self._extract_throws(
                block, file_name, block_line, full_path, http_method
            ))

            # 3. State guards
            facts.extend(self._extract_state_guards(
                block, file_name, block_line, full_path, http_method
            ))

            # 4. @Validated (parameter validation)
            if ANNOTATION["validated"].search(block):
                facts.append(CodeFact(
                    file=file_name, line=block_line,
                    api_path=full_path, api_method=http_method,
                    category="write" if http_method in ("POST", "PUT", "DELETE") else "query",
                    constraint_type=ConstraintType.REQUIRED,
                    field="requestBody",
                    detail="@Validated — 参数校验启用",
                ))

        return facts

    def parse_service(self, file_path: str, module: str = "") -> List[CodeFact]:
        """Parse a Service file — lightweight: only exception throws + state guards."""
        source = Path(file_path).read_text(encoding="utf-8")
        file_name = Path(file_path).name
        facts: List[CodeFact] = []

        method_blocks = self._split_methods(source)
        for block in method_blocks:
            # Skip private methods
            if re.search(r'^\s*private\s+', block, re.MULTILINE):
                continue

            method_match = re.search(r'public\s+[\w.<>,\s]+\s+(\w+)\s*\(', block)
            method_name = method_match.group(1) if method_match else "unknown"
            block_line = self._block_line(source, block)

            for m in THROW.finditer(block):
                ex_type = m.group(1)
                ex_msg = (m.group(2) or "").strip('()"\' ')
                facts.append(CodeFact(
                    file=file_name, line=block_line,
                    api_path=method_name, api_method="SERVICE",
                    category="write",
                    constraint_type=ConstraintType.BUSINESS_RULE,
                    field="",
                    detail=f"throw new {ex_type}()",
                    message=ex_msg if ex_msg else None,
                ))

        return facts

    # ── Private helpers ──────────────────────────────────────────

    def _extract_base_path(self, source: str) -> str:
        m = ANNOTATION["requestMapping"].search(source)
        return m.group(1) if m else "/"

    def _is_api_method(self, block: str) -> bool:
        return any(anno in block for anno in
                   ["@GetMapping", "@PostMapping", "@PutMapping",
                    "@DeleteMapping", "@RequestMapping"])

    def _http_method(self, block: str) -> str:
        if "@GetMapping" in block: return "GET"
        if "@PostMapping" in block: return "POST"
        if "@PutMapping" in block: return "PUT"
        if "@DeleteMapping" in block: return "DELETE"
        return "GET"

    def _api_path(self, block: str) -> str:
        for key in ["getMapping", "postMapping", "putMapping", "deleteMapping"]:
            m = ANNOTATION[key].search(block)
            if m: return m.group(1)
        return ""

    def _api_summary(self, block: str) -> str:
        m = ANNOTATION["apiOperation"].search(block)
        return m.group(1) if m else ""

    def _block_line(self, source: str, block: str) -> int:
        """Approximate line number of a method block in source."""
        idx = source.find(block)
        if idx < 0:
            return 0
        return source[:idx].count("\n") + 1

    def _split_methods(self, source: str) -> List[str]:
        """Split class body into @annotation-group + method blocks.

        Same proven algorithm as controller_analyzer.py.
        """
        class_pos = source.find('{', source.find('public class') if 'public class' in source else 0)
        if class_pos < 0:
            return []
        body = source[class_pos + 1:]

        lines = body.split('\n')
        sig_re = re.compile(r'^\s*(public|protected|private)\s+')
        blocks: List[str] = []

        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith('@') and not stripped.startswith('@Override'):
                start = i
                i += 1
                while i < len(lines):
                    s = lines[i].strip()
                    if (s.startswith('@') or s.startswith('//') or
                        s.startswith('/*') or s.startswith('*') or s == ''):
                        i += 1
                    elif sig_re.match(s):
                        i += 1
                        brace_count = s.count('{') - s.count('}')
                        while i < len(lines) and brace_count > 0:
                            brace_count += lines[i].count('{') - lines[i].count('}')
                            i += 1
                        blocks.append('\n'.join(lines[start:i]).strip())
                        break
                    else:
                        blocks.append('\n'.join(lines[start:i]).strip())
                        break
                else:
                    blocks.append('\n'.join(lines[start:]).strip())
            else:
                i += 1

        return [b for b in blocks if b]

    # ── Fact extractors ──────────────────────────────────────────

    def _extract_validations(self, block: str, file_name: str, line: int,
                              api_path: str, http_method: str) -> List[CodeFact]:
        facts = []
        category = "write" if http_method in ("POST", "PUT", "DELETE") else "query"

        # Extract field name near the annotation (heuristic: next word after annotation)
        def _nearby_field(block: str, anno_start: int) -> str:
            after = block[anno_start:]
            m = re.search(r'(?:private|public|protected)?\s*(\w+)\s+(\w+)\s*[;=]', after)
            if m:
                return m.group(2)
            return "unknown_field"

        for key, pattern in VALIDATION.items():
            for m in pattern.finditer(block):
                field_name = _nearby_field(block, m.start())
                detail = m.group(0).strip()
                if key == "size":
                    detail = "@Size" + m.group(1)
                    facts.append(CodeFact(
                        file=file_name, line=line, api_path=api_path,
                        api_method=http_method, category=category,
                        constraint_type=ConstraintType.SIZE_RANGE,
                        field=field_name, detail=detail,
                    ))
                elif key in ("min", "max", "decimalMin", "decimalMax", "range"):
                    facts.append(CodeFact(
                        file=file_name, line=line, api_path=api_path,
                        api_method=http_method, category=category,
                        constraint_type=ConstraintType.VALUE_RANGE,
                        field=field_name, detail=detail,
                    ))
                elif key in ("pattern", "email"):
                    facts.append(CodeFact(
                        file=file_name, line=line, api_path=api_path,
                        api_method=http_method, category=category,
                        constraint_type=ConstraintType.FORMAT,
                        field=field_name, detail=detail,
                    ))
                else:
                    facts.append(CodeFact(
                        file=file_name, line=line, api_path=api_path,
                        api_method=http_method, category=category,
                        constraint_type=ConstraintType.REQUIRED,
                        field=field_name, detail=detail,
                    ))
        return facts

    def _extract_throws(self, block: str, file_name: str, line: int,
                         api_path: str, http_method: str) -> List[CodeFact]:
        facts = []
        for m in THROW.finditer(block):
            ex_type = m.group(1)
            ex_msg = (m.group(2) or "").strip('()"\' ')

            # Deduce constraint type from exception type
            if "BusinessException" in ex_type:
                ct = ConstraintType.BUSINESS_RULE
            elif "IllegalArgument" in ex_type:
                ct = ConstraintType.REQUIRED
            elif "State" in ex_type or "Status" in ex_type:
                ct = ConstraintType.STATE_GUARD
            else:
                ct = ConstraintType.BUSINESS_RULE

            facts.append(CodeFact(
                file=file_name, line=line, api_path=api_path,
                api_method=http_method, category="write",
                constraint_type=ct,
                field="",
                detail=f"throw new {ex_type}({ex_msg})" if ex_msg else f"throw new {ex_type}()",
                message=ex_msg if ex_msg else None,
            ))
        return facts

    def _extract_state_guards(self, block: str, file_name: str, line: int,
                               api_path: str, http_method: str) -> List[CodeFact]:
        facts = []
        for m in STATE_GUARD.finditer(block):
            guard = m.group(0).strip()
            facts.append(CodeFact(
                file=file_name, line=line, api_path=api_path,
                api_method=http_method, category="write",
                constraint_type=ConstraintType.STATE_GUARD,
                field="status",
                detail=guard,
            ))
        return facts


# ── Convenience function ───────────────────────────────────────────

def parse_java(path: str, module: str = "") -> List[CodeFact]:
    """Entry point: parse a Java file and return CodeFacts."""
    parser = JavaCodeParser()
    name = Path(path).name.lower()
    if "controller" in name:
        return parser.parse_controller(path, module)
    elif "service" in name:
        return parser.parse_service(path, module)
    else:
        # Try controller first (richer extraction), fall back to service
        try:
            return parser.parse_controller(path, module)
        except Exception:
            return parser.parse_service(path, module)
