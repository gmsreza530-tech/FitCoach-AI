"""Deterministic safety and progression helpers for FitCoach AI.

This module is a conservative decision-support layer, not a medical diagnostic tool.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

PUSH_PULL_PATTERNS = {
    "horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull"
}
NO_PAIN = ("بدون درد", "درد ندارم", "بدون درد و ناراحتی", "no pain", "pain-free")
PAIN_WORDS = ("درد", "دردناک", "ناراحتی", "آسیب", "pain", "injury", "hurt")
SHOULDER_WORDS = ("شانه", "سرشانه", "شون", "کتف", "shoulder", "rotator cuff")
KNEE_WORDS = ("زانو", "knee")
BACK_WORDS = ("کمر", "ستون فقرات", "lower back", "spine")
ELBOW_WORDS = ("آرنج", "elbow")
WRIST_WORDS = ("مچ", "wrist")
HIP_WORDS = ("لگن", "hip")


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _contains_any(text: str, words: Iterable[str]) -> bool:
    return any(word in text for word in words)


def analyze_training_safety(
    limitations: Any = "",
    medication: Any = "",
    training_history: Any = "",
) -> Dict[str, Any]:
    """Extract conservative exercise constraints from declared limits and recent logs."""
    source = "\n".join((_text(limitations), _text(training_history)))
    for phrase in NO_PAIN:
        source = source.replace(phrase, "")
    pain_context = "\n".join(line for line in source.splitlines() if _contains_any(line, PAIN_WORDS))
    has_pain_signal = bool(pain_context)

    region = None
    blocked_patterns: List[str] = []
    reason = ""
    needs_clarification = False

    if has_pain_signal:
        if _contains_any(pain_context, SHOULDER_WORDS):
            region = "shoulder"
            blocked_patterns = sorted(PUSH_PULL_PATTERNS)
            reason = "در سوابق، درد یا ناراحتی ناحیه شانه/سرشانه ثبت شده است."
        elif _contains_any(pain_context, KNEE_WORDS):
            region = "knee"
            blocked_patterns = ["squat", "lunge", "power"]
            reason = "در سوابق، درد یا ناراحتی زانو ثبت شده است."
        elif _contains_any(pain_context, BACK_WORDS):
            region = "back"
            blocked_patterns = ["hinge", "squat", "carry", "power"]
            reason = "در سوابق، درد یا ناراحتی کمر/پشت ثبت شده است."
        elif _contains_any(pain_context, ELBOW_WORDS):
            region = "elbow"
            blocked_patterns = sorted(PUSH_PULL_PATTERNS)
            reason = "در سوابق، درد یا ناراحتی آرنج ثبت شده است."
        elif _contains_any(pain_context, WRIST_WORDS):
            region = "wrist"
            blocked_patterns = sorted(PUSH_PULL_PATTERNS)
            reason = "در سوابق، درد یا ناراحتی مچ ثبت شده است."
        elif _contains_any(pain_context, HIP_WORDS):
            region = "hip"
            blocked_patterns = ["squat", "hinge", "lunge", "power"]
            reason = "در سوابق، درد یا ناراحتی لگن/ران ثبت شده است."
        else:
            needs_clarification = True
            reason = "درد یا ناراحتی ثبت شده اما محل آن مشخص نیست؛ پیش از طراحی برنامه باید محل و وضعیت آن روشن شود."

    data_quality_warnings = []
    progression_decisions = []
    for line in str(training_history or "").splitlines():
        if not line.lstrip().startswith("- ") or "| ست:" not in line:
            continue
        exercise_match = re.search(r":\s*([^|]+)\s*\|\s*ست:", line)
        fields = re.search(
            r"\|\s*ست:\s*([^|]+)\|\s*تکرار:\s*([^|]+)\|\s*وزنه:\s*([^ ]+)\s*کیلوگرم\s*\|\s*RIR:\s*([^|]+)\|\s*یادداشت:\s*(.*)",
            line,
        )
        if not exercise_match or not fields:
            continue
        exercise = exercise_match.group(1).strip()
        sets, reps, weight, rir, notes = (
            fields.group(1).strip(), fields.group(2).strip(),
            fields.group(3).strip(), fields.group(4).strip(),
            fields.group(5).strip(),
        )
        decision = progression_guidance(
            exercise, weight, reps, None if rir == "نامشخص" else rir, notes
        )
        progression_decisions.append(decision)
        if not decision["rir"]["usable"] and rir != "نامشخص":
            data_quality_warnings.append(decision["rir"]["reason"])
        if len(progression_decisions) >= 8:
            break
    med = _text(medication)
    medication_flag = med not in ("", "خیر", "ندارد", "no", "none", "مصرف نمی‌کنم")
    return {
        "pain_signal": bool(has_pain_signal),
        "region": region,
        "blocked_patterns": blocked_patterns,
        "reason": reason,
        "needs_clarification": needs_clarification,
        "requires_coach_review": bool(has_pain_signal or medication_flag or _text(limitations) not in ("", "خیر", "ندارد", "no", "none")),
        "medication_declared": medication_flag,
        "data_quality_warnings": list(dict.fromkeys(data_quality_warnings)),
        "progression_decisions": progression_decisions,
    }


def classify_rir(value: Any) -> Dict[str, Any]:
    """Only standard RIR values 0..5 are usable for progression decisions."""
    if value in (None, ""):
        return {"usable": False, "value": None, "reason": "RIR ثبت نشده است."}
    try:
        numeric = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return {"usable": False, "value": None, "reason": "RIR عددی معتبر نیست."}
    if not 0 <= numeric <= 5:
        return {
            "usable": False,
            "value": numeric,
            "reason": f"RIR ثبت‌شده {numeric:g} خارج از بازه معتبر ۰ تا ۵ است؛ برای تصمیم افزایش وزنه استفاده نشد.",
        }
    return {"usable": True, "value": numeric, "reason": "RIR در بازه قابل استفاده ثبت شده است."}


def progression_guidance(
    exercise: Any, weight: Any, reps: Any, rir: Any, notes: Any = ""
) -> Dict[str, Any]:
    """Return cautious, auditable guidance; never infer a load increase from one set."""
    rir_result = classify_rir(rir)
    pain = _contains_any(_text(notes), PAIN_WORDS) and not _contains_any(_text(notes), NO_PAIN)
    if pain:
        decision = "stop_and_review"
        rationale = "یادداشت درد/ناراحتی وجود دارد؛ افزایش وزنه یا توصیه ادامه حرکت صادر نمی‌شود."
    elif not rir_result["usable"]:
        decision = "hold"
        rationale = rir_result["reason"] + " بار تمرین حفظ شود و پیشرفت فقط پس از ثبت معتبر چند جلسه بررسی شود."
    else:
        decision = "observe"
        rationale = "RIR معتبر است، اما یک رکورد به‌تنهایی برای افزایش وزنه کافی نیست؛ روند چند جلسه و کیفیت اجرا بررسی شود."
    return {
        "exercise": str(exercise or "حرکت نامشخص"),
        "weight": weight,
        "reps": reps,
        "rir": rir_result,
        "decision": decision,
        "rationale": rationale,
    }
