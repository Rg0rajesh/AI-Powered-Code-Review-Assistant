"""
LintVertex - AI Service
Gemini as primary, Ollama as local fallback
LangGraph for pipeline orchestration
"""
import json
import logging
import requests
from typing import TypedDict, Optional
from config import Config

logger = logging.getLogger(__name__)

# ─── State Schema ─────────────────────────────────────────────────────────────

class AnalysisState(TypedDict):
    code: str
    language: str
    ml_features: dict
    ml_score: dict
    syntax_issues: list
    ai_explanation: Optional[str]
    ai_improvements: Optional[list]
    ai_provider: str
    error: Optional[str]


# ─── Prompt Builder ───────────────────────────────────────────────────────────

def build_analysis_prompt(code: str, language: str, ml_score: dict, syntax_issues: list) -> str:
    issues_summary = "\n".join([
        f"- Line {i.get('line', '?')}: [{i['severity'].upper()}] {i['message']}"
        for i in syntax_issues[:10]
    ]) if syntax_issues else "No syntax issues detected by static analysis."

    score = ml_score.get("total_score", 0)
    grade = ml_score.get("grade", "?")

    return f"""You are a senior software engineer conducting a thorough code review.

LANGUAGE: {language.upper()}
ML QUALITY SCORE: {score}/100 (Grade: {grade})

DETECTED SYNTAX/STYLE ISSUES:
{issues_summary}

CODE TO REVIEW:
```{language}
{code[:3000]}
```

Provide a structured code review with these exact sections:

## 🔍 Summary
Brief 2-3 sentence overview of the code quality and purpose.

## 🐛 Bugs & Vulnerabilities
List any bugs, security vulnerabilities, or logic errors. Be specific with line references.

## ⚡ Performance Issues
Identify performance bottlenecks, unnecessary operations, or inefficiencies.

## 💡 Improvements
Provide 3-5 actionable, specific improvements with code examples where relevant.

## ✅ Strengths
Mention 1-3 things the developer did well.

## 📊 Verdict
One sentence final assessment.

Be direct, technical, and specific. Avoid generic advice. Focus on what matters most for this specific code."""


# ─── Gemini Service ───────────────────────────────────────────────────────────

def call_gemini(prompt: str) -> str:
    """Call Gemini API for code analysis"""
    if not Config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not configured")

    try:
        import google.generativeai as genai
        genai.configure(api_key=Config.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=2048,
            )
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        raise


# ─── Ollama Fallback ──────────────────────────────────────────────────────────

def call_ollama(prompt: str) -> str:
    """Call local Ollama as fallback"""
    try:
        url = f"{Config.OLLAMA_BASE_URL}/api/generate"
        payload = {
            "model": Config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 2048}
        }
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        raise


# ─── Main Analysis Pipeline ───────────────────────────────────────────────────

def run_ai_analysis(
    code: str,
    language: str,
    ml_score: dict,
    syntax_issues: list
) -> dict:
    """
    Full AI analysis pipeline:
    1. Build prompt
    2. Try Gemini
    3. Fallback to Ollama
    4. Return structured result
    """
    prompt = build_analysis_prompt(code, language, ml_score, syntax_issues)
    ai_text = None
    provider = "none"

    # Try Gemini first
    try:
        ai_text = call_gemini(prompt)
        provider = "gemini"
        logger.info("Gemini analysis successful")
    except Exception as gemini_err:
        logger.warning(f"Gemini failed ({gemini_err}), trying Ollama fallback...")
        try:
            ai_text = call_ollama(prompt)
            provider = "ollama"
            logger.info("Ollama fallback successful")
        except Exception as ollama_err:
            logger.error(f"Both AI providers failed. Gemini: {gemini_err}, Ollama: {ollama_err}")
            ai_text = _fallback_analysis(ml_score, syntax_issues, language)
            provider = "fallback"

    return {
        "ai_explanation": ai_text,
        "ai_provider": provider,
    }


def _fallback_analysis(ml_score: dict, syntax_issues: list, language: str) -> str:
    """Generate a basic analysis report when AI is unavailable"""
    score = ml_score.get("total_score", 0)
    grade = ml_score.get("grade", "?")
    error_count = sum(1 for i in syntax_issues if i["severity"] == "error")
    warning_count = sum(1 for i in syntax_issues if i["severity"] == "warning")

    return f"""## 🔍 Summary
Static analysis completed for {language.upper()} code. Quality score: {score}/100 (Grade: {grade}).
AI-powered explanation is currently unavailable — showing ML-based analysis only.

## 🐛 Bugs & Vulnerabilities
{f'Found {error_count} error(s) and {warning_count} warning(s) in static analysis.' if syntax_issues else 'No critical issues detected by static analysis.'}

## ⚡ Performance Issues
Manual review recommended for performance optimizations.

## 💡 Improvements
- Review the detected issues listed in the Issues tab
- Add documentation and comments for clarity
- Consider code structure and modularity
- Run additional tests for edge cases

## ✅ Strengths
Code submitted for review successfully.

## 📊 Verdict
Static analysis complete. Enable AI service for detailed explanations."""


# ─── Parse AI Response into Sections ─────────────────────────────────────────

def parse_ai_sections(ai_text: str) -> dict:
    """Parse markdown sections from AI response"""
    sections = {
        "summary": "",
        "bugs": "",
        "performance": "",
        "improvements": "",
        "strengths": "",
        "verdict": "",
        "raw": ai_text
    }

    patterns = {
        "summary": r"##\s*🔍\s*Summary\s*(.*?)(?=##|\Z)",
        "bugs": r"##\s*🐛\s*Bugs.*?\s*(.*?)(?=##|\Z)",
        "performance": r"##\s*⚡\s*Performance.*?\s*(.*?)(?=##|\Z)",
        "improvements": r"##\s*💡\s*Improvements\s*(.*?)(?=##|\Z)",
        "strengths": r"##\s*✅\s*Strengths\s*(.*?)(?=##|\Z)",
        "verdict": r"##\s*📊\s*Verdict\s*(.*?)(?=##|\Z)",
    }

    import re
    for key, pattern in patterns.items():
        match = re.search(pattern, ai_text, re.DOTALL | re.IGNORECASE)
        if match:
            sections[key] = match.group(1).strip()

    return sections
