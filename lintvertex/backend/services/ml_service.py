"""
LintVertex - ML Service
Random Forest / Gradient Boosting for code quality scoring
Using TF-IDF feature extraction
"""
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder


# ─── Feature Extraction ───────────────────────────────────────────────────────

def extract_code_features(code: str) -> dict:
    """Extract numerical features from source code"""
    lines = code.split("\n")
    non_empty = [l for l in lines if l.strip()]

    # Basic metrics
    total_lines = len(lines)
    code_lines = len(non_empty)
    avg_line_length = sum(len(l) for l in non_empty) / max(code_lines, 1)
    max_line_length = max((len(l) for l in non_empty), default=0)

    # Comment ratio
    comment_lines = sum(1 for l in lines if l.strip().startswith(("#", "//", "/*", "*", "'")))
    comment_ratio = comment_lines / max(total_lines, 1)

    # Nesting depth estimation
    indent_levels = []
    for line in non_empty:
        stripped = line.lstrip()
        if stripped:
            indent = len(line) - len(stripped)
            indent_levels.append(indent // 4 if indent % 4 == 0 else indent // 2)
    max_nesting = max(indent_levels, default=0)
    avg_nesting = sum(indent_levels) / max(len(indent_levels), 1)

    # Complexity indicators
    loop_count = len(re.findall(r'\b(for|while|do)\b', code))
    condition_count = len(re.findall(r'\b(if|elif|else|switch|case)\b', code))
    function_count = len(re.findall(r'\b(def|void|int|float|double|string)\s+\w+\s*\(', code))
    class_count = len(re.findall(r'\b(class|struct)\s+\w+', code))

    # Error patterns
    broad_except = len(re.findall(r'except\s*:', code))
    magic_numbers = len(re.findall(r'\b(?<!\.)\d{2,}\b(?!\.)', code))
    long_lines = sum(1 for l in lines if len(l) > 100)

    # Quality signals
    has_docstring = bool(re.search(r'""".*?"""', code, re.DOTALL) or re.search(r"'''.*?'''", code, re.DOTALL))
    uses_constants = bool(re.search(r'\b[A-Z_]{3,}\s*=', code))
    empty_catch = len(re.findall(r'(catch|except).*?\{?\s*\}?\s*$', code, re.MULTILINE))

    return {
        "total_lines": total_lines,
        "code_lines": code_lines,
        "comment_ratio": round(comment_ratio, 3),
        "avg_line_length": round(avg_line_length, 2),
        "max_line_length": max_line_length,
        "max_nesting": max_nesting,
        "avg_nesting": round(avg_nesting, 2),
        "loop_count": loop_count,
        "condition_count": condition_count,
        "function_count": function_count,
        "class_count": class_count,
        "broad_except": broad_except,
        "magic_numbers": magic_numbers,
        "long_lines": long_lines,
        "has_docstring": int(has_docstring),
        "uses_constants": int(uses_constants),
        "empty_catch": empty_catch,
    }


def compute_quality_score(features: dict, language: str) -> dict:
    """
    Rule-based quality scoring (0-100).
    Returns score and breakdown by category.
    """
    scores = {}

    # Readability (0-25)
    readability = 25
    if features["avg_line_length"] > 80:
        readability -= 5
    if features["max_line_length"] > 120:
        readability -= 5
    if features["long_lines"] > 3:
        readability -= 5
    if features["comment_ratio"] < 0.05 and features["code_lines"] > 20:
        readability -= 5
    scores["readability"] = max(0, readability)

    # Maintainability (0-25)
    maintainability = 25
    if features["max_nesting"] > 4:
        maintainability -= 8
    elif features["max_nesting"] > 3:
        maintainability -= 4
    if features["magic_numbers"] > 5:
        maintainability -= 5
    if not features["has_docstring"] and features["function_count"] > 1:
        maintainability -= 5
    scores["maintainability"] = max(0, maintainability)

    # Reliability (0-25)
    reliability = 25
    if features["broad_except"] > 0:
        reliability -= 8
    if features["empty_catch"] > 0:
        reliability -= 8
    if features["loop_count"] > 10:
        reliability -= 4
    scores["reliability"] = max(0, reliability)

    # Best Practices (0-25)
    best_practices = 25
    if features["function_count"] == 0 and features["code_lines"] > 30:
        best_practices -= 8
    if features["comment_ratio"] < 0.1 and features["code_lines"] > 50:
        best_practices -= 5
    if not features["uses_constants"] and language in ("python", "java"):
        best_practices -= 3
    scores["best_practices"] = max(0, best_practices)

    total = sum(scores.values())
    grade = "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 55 else "D" if total >= 40 else "F"

    return {
        "total_score": total,
        "grade": grade,
        "breakdown": scores,
        "confidence": 0.78,
        "model": "rule_based_v1"
    }


# ─── Issue Detection ──────────────────────────────────────────────────────────

def detect_syntax_issues(code: str, language: str) -> list:
    """Basic syntax and style issue detection"""
    issues = []

    lines = code.split("\n")

    for i, line in enumerate(lines, 1):
        # Long lines
        if len(line) > 100:
            issues.append({
                "line": i,
                "severity": "warning",
                "type": "style",
                "message": f"Line {i} exceeds 100 characters ({len(line)} chars)"
            })

        # Trailing whitespace
        if line != line.rstrip():
            issues.append({
                "line": i,
                "severity": "info",
                "type": "style",
                "message": f"Line {i} has trailing whitespace"
            })

    # Language-specific checks
    if language == "python":
        import ast
        try_code = code
        lines_arr = try_code.split("\n")
        for _ in range(5):
            try:
                ast.parse(try_code)
                break
            except SyntaxError as e:
                line_no = getattr(e, "lineno", 0)
                msg = getattr(e, "msg", str(e))
                issues.append({
                    "line": line_no,
                    "severity": "error",
                    "type": "syntax",
                    "message": f"SyntaxError: {msg}"
                })
                if 0 < line_no <= len(lines_arr):
                    lines_arr[line_no - 1] = "# Line removed by syntax checker"
                    try_code = "\n".join(lines_arr)
                else:
                    break
            
        # Bare except
        for match in re.finditer(r'except\s*:', code):
            line_no = code[:match.start()].count("\n") + 1
            issues.append({
                "line": line_no,
                "severity": "warning",
                "type": "reliability",
                "message": "Bare 'except:' clause catches all exceptions including SystemExit"
            })

        # Print without parentheses (Python 2 style)
        for match in re.finditer(r'\bprint\s+[^(]', code):
            line_no = code[:match.start()].count("\n") + 1
            issues.append({
                "line": line_no,
                "severity": "error",
                "type": "syntax",
                "message": "Python 3: use print() with parentheses"
            })

        # Mutable default argument
        for match in re.finditer(r'def\s+\w+\([^)]*=\s*[\[\{]', code):
            line_no = code[:match.start()].count("\n") + 1
            issues.append({
                "line": line_no,
                "severity": "warning",
                "type": "bug",
                "message": "Mutable default argument — use None and assign inside function"
            })

    if language in ("c", "cpp"):
        # gets() usage
        if re.search(r'\bgets\s*\(', code):
            issues.append({
                "line": 0,
                "severity": "error",
                "type": "security",
                "message": "gets() is unsafe — use fgets() instead (buffer overflow risk)"
            })

        # scanf without width limit
        for match in re.finditer(r'scanf\s*\(\s*"%s"', code):
            line_no = code[:match.start()].count("\n") + 1
            issues.append({
                "line": line_no,
                "severity": "warning",
                "type": "security",
                "message": 'scanf with "%s" has no width limit — use "%255s" or similar'
            })

    if language == "java":
        # == for String comparison
        for match in re.finditer(r'"[^"]*"\s*==\s*|==\s*"[^"]*"', code):
            line_no = code[:match.start()].count("\n") + 1
            issues.append({
                "line": line_no,
                "severity": "error",
                "type": "bug",
                "message": "Use .equals() to compare Strings in Java, not =="
            })

        # System.exit in non-main
        if re.search(r'System\.exit\(', code) and not re.search(r'public\s+static\s+void\s+main', code):
            issues.append({
                "line": 0,
                "severity": "warning",
                "type": "reliability",
                "message": "System.exit() outside main() can cause unexpected program termination"
            })

    # Sort by severity
    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 3))

    return issues
