"""
LintVertex - Language Auto-Detection Service
Rule-based + ML hybrid detection for Java, Python, C, C++
"""
import re
from typing import Literal

SupportedLanguage = Literal["python", "java", "c", "cpp", "unknown"]


# ─── Rule-Based Detection ─────────────────────────────────────────────────────

LANGUAGE_PATTERNS = {
    "python": {
        "strong": [
            r"^\s*def\s+\w+\s*\(",
            r"^\s*import\s+\w+",
            r"^\s*from\s+\w+\s+import",
            r"^\s*class\s+\w+(\s*\(\w*\))?:",
            r"print\s*\(",
            r"if\s+__name__\s*==\s*['\"]__main__['\"]",
        ],
        "weak": [
            r":\s*$",
            r"^\s{4}",
            r"#\s",
            r"elif\s",
            r"True|False|None\b",
        ]
    },
    "java": {
        "strong": [
            r"public\s+static\s+void\s+main",
            r"public\s+class\s+\w+",
            r"System\.out\.print",
            r"import\s+java\.",
            r"@Override",
            r"extends\s+\w+",
            r"implements\s+\w+",
        ],
        "weak": [
            r"public|private|protected",
            r"void\s+\w+\s*\(",
            r"new\s+\w+\(",
            r"//\s",
        ]
    },
    "cpp": {
        "strong": [
            r"#include\s*<(iostream|vector|string|algorithm|map|set)",
            r"std::",
            r"cout\s*<<",
            r"cin\s*>>",
            r"namespace\s+\w+",
            r"template\s*<",
            r"::\s*\w+",
        ],
        "weak": [
            r"#include",
            r"int\s+main\s*\(",
            r"//\s",
        ]
    },
    "c": {
        "strong": [
            r"#include\s*<(stdio|stdlib|string|math|time)\.h>",
            r"printf\s*\(",
            r"scanf\s*\(",
            r"malloc\s*\(",
            r"free\s*\(",
        ],
        "weak": [
            r"#include",
            r"int\s+main\s*\(",
            r"//\s",
        ]
    }
}


def detect_language(code: str) -> dict:
    """
    Detect programming language from source code.
    Returns {language, confidence, method}
    """
    if not code or len(code.strip()) < 10:
        return {"language": "unknown", "confidence": 0.0, "method": "insufficient_input"}

    scores = {}

    for lang, patterns in LANGUAGE_PATTERNS.items():
        strong_hits = sum(
            1 for p in patterns["strong"]
            if re.search(p, code, re.MULTILINE)
        )
        weak_hits = sum(
            1 for p in patterns["weak"]
            if re.search(p, code, re.MULTILINE)
        )
        scores[lang] = (strong_hits * 3) + (weak_hits * 1)

    # C vs C++ disambiguation
    # C++ takes priority if std:: or cout/cin found
    if scores.get("cpp", 0) > 0 and scores.get("c", 0) > 0:
        cpp_specific = bool(re.search(r"std::|cout|cin|namespace\s+\w+|template\s*<", code))
        if cpp_specific:
            scores["c"] = max(0, scores["c"] - scores["cpp"])
        else:
            scores["cpp"] = max(0, scores["cpp"] - scores["c"])

    if not scores or max(scores.values()) == 0:
        return {"language": "unknown", "confidence": 0.0, "method": "no_pattern_match"}

    detected = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = round(scores[detected] / total, 3) if total > 0 else 0.0

    return {
        "language": detected,
        "confidence": confidence,
        "method": "rule_based",
        "scores": scores
    }


# ─── Language Display Info ────────────────────────────────────────────────────

LANGUAGE_META = {
    "python": {
        "display": "Python",
        "icon": "🐍",
        "file_ext": ".py",
        "comment": "#",
    },
    "java": {
        "display": "Java",
        "icon": "♨️",
        "file_ext": ".java",
        "comment": "//",
    },
    "c": {
        "display": "C",
        "icon": "⚙️",
        "file_ext": ".c",
        "comment": "//",
    },
    "cpp": {
        "display": "C++",
        "icon": "🔧",
        "file_ext": ".cpp",
        "comment": "//",
    },
    "unknown": {
        "display": "Unknown",
        "icon": "❓",
        "file_ext": "",
        "comment": "",
    }
}


def get_language_meta(language: str) -> dict:
    return LANGUAGE_META.get(language, LANGUAGE_META["unknown"])
