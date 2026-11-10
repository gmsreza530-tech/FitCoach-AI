"""Structured workout validation and deterministic Persian Telegram rendering."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, List

MOVEMENT_PATTERNS = {
    "horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull",
    "squat", "hinge", "lunge", "isolation", "core", "carry", "power",
}
MUSCLE_GROUPS = {
    "chest", "back", "shoulders", "triceps", "biceps", "quadriceps",
    "hamstrings", "glutes", "calves", "core",
}
PUSH_PATTERNS = {"horizontal_push", "vertical_push"}
PULL_PATTERNS = {"horizontal_pull", "vertical_pull"}
ADVANCED_BEGINNER_BLOCKLIST = (
    "weighted pull", "بارفیکس با وزنه", "muscle-up", "ماسل‌آپ",
    "snatch", "اسنچ", "clean and jerk", "کلین اند جرک",
)


class WorkoutFormatError(ValueError):
    """Raised when an AI workout payload is incomplete or fails a hard quality rule."""


def _clean(value: Any, field: str, *, required: bool = True, max_length: int = 500) -> str:
    if value is None:
        value = ""
    text = str(value).strip()
    if required and not text:
        raise WorkoutFormatError(f"فیلد «{field}» خالی است.")
    if len(text) > max_length:
        text = text[:max_length].rstrip()
    return text


def _digits(value: Any) -> str:
    text = str(value)
    return text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def _number(value: Any, field: str, low: int, high: int) -> int:
    match = re.search(r"\d+", _digits(value))
    if not match:
        raise WorkoutFormatError(f"مقدار «{field}» باید عددی باشد.")
    number = int(match.group())
    if not low <= number <= high:
        raise WorkoutFormatError(f"مقدار «{field}» باید بین {low} و {high} باشد.")
    return number


def _extract_json(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str):
        raise WorkoutFormatError("خروجی برنامه ساختار معتبری ندارد.")
    text = payload.strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise WorkoutFormatError("ساختار JSON برنامه پیدا نشد.")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise WorkoutFormatError("ساختار برنامه قابل خواندن نیست.") from exc
    if not isinstance(data, dict):
        raise WorkoutFormatError("ریشه برنامه باید یک شیء JSON باشد.")
    return data


def _profile_days(profile: Dict[str, Any]) -> int | None:
    value = profile.get("days")
    if value in (None, ""):
        return None
    match = re.search(r"\d+", _digits(value))
    if not match:
        return None
    days = int(match.group())
    return days if 1 <= days <= 7 else None


def _is_beginner(profile: Dict[str, Any]) -> bool:
    level = _digits(profile.get("experience", "")).lower()
    return "beginner" in level or "مبتدی" in level or "تازه‌کار" in level


def validate_workout_plan(payload: Any, profile: Dict[str, Any] | None = None) -> List[str]:
    """Apply deterministic structural and basic programming checks.

    Hard failures prevent the plan from being delivered. Warnings require coach review.
    This is a rule-based quality gate, not a clinical or evidence-grading system.
    """
    data = _extract_json(payload)
    profile = profile or {}
    days = data.get("weekly_schedule")
    if not isinstance(days, list) or not 1 <= len(days) <= 7:
        raise WorkoutFormatError("تعداد روزهای برنامه باید بین ۱ تا ۷ باشد.")

    expected_days = _profile_days(profile)
    if expected_days is not None and len(days) != expected_days:
        raise WorkoutFormatError(
            f"تعداد جلسات برنامه ({len(days)}) با پروفایل ورزشکار ({expected_days}) یکسان نیست."
        )

    beginner = _is_beginner(profile)
    warnings: List[str] = []
    weekly_sets: Dict[str, int] = {}

    for day_index, day in enumerate(days, start=1):
        if not isinstance(day, dict):
            raise WorkoutFormatError(f"اطلاعات روز {day_index} معتبر نیست.")
        day_name = _clean(day.get("day") or f"روز {day_index}", "نام روز", max_length=80)
        focus = _clean(day.get("focus"), "تمرکز روز", required=False, max_length=140).lower()
        exercises = day.get("exercises")
        if not isinstance(exercises, list) or not 1 <= len(exercises) <= 15:
            raise WorkoutFormatError(f"روز «{day_name}» باید حداقل یک و حداکثر ۱۵ حرکت داشته باشد.")

        seen_names = set()
        day_patterns: List[str] = []
        for ex_index, exercise in enumerate(exercises, start=1):
            if not isinstance(exercise, dict):
                raise WorkoutFormatError(f"حرکت {ex_index} در {day_name} معتبر نیست.")
            name = _clean(exercise.get("name"), "نام حرکت", max_length=120)
            normalized_name = re.sub(r"[^a-z0-9آ-ی]", "", unicodedata.normalize("NFKC", name).lower())
            if normalized_name in seen_names:
                raise WorkoutFormatError(f"حرکت «{name}» در روز «{day_name}» تکراری است.")
            seen_names.add(normalized_name)

            pattern = _clean(exercise.get("movement_pattern"), "الگوی حرکتی", max_length=40).lower()
            if pattern not in MOVEMENT_PATTERNS:
                raise WorkoutFormatError(f"الگوی حرکتی «{pattern}» برای حرکت «{name}» معتبر نیست.")
            day_patterns.append(pattern)

            muscles = exercise.get("muscle_groups")
            if not isinstance(muscles, list) or not muscles:
                raise WorkoutFormatError(f"عضلات هدف حرکت «{name}» مشخص نشده‌اند.")
            for muscle in muscles:
                if str(muscle).lower() not in MUSCLE_GROUPS:
                    raise WorkoutFormatError(f"گروه عضلانی نامعتبر در حرکت «{name}»: {muscle}")
            sets = _number(exercise.get("sets"), "ست", 1, 6)
            _clean(exercise.get("reps"), "تکرار", max_length=40)
            rest = _number(exercise.get("rest"), "استراحت (ثانیه)", 30, 600)
            _ = rest
            if exercise.get("rir") not in (None, ""):
                _number(exercise.get("rir"), "RIR", 0, 5)

            skill = _clean(exercise.get("skill_level"), "سطح مهارت حرکت", max_length=20).lower()
            if skill not in {"beginner", "intermediate", "advanced"}:
                raise WorkoutFormatError(f"سطح مهارت حرکت «{name}» معتبر نیست.")
            if beginner and (skill == "advanced" or any(token in name.lower() for token in ADVANCED_BEGINNER_BLOCKLIST)):
                raise WorkoutFormatError(
                    f"حرکت «{name}» برای پروفایل مبتدی به‌عنوان حرکت پیشرفته علامت‌گذاری شده است."
                )

            for muscle in muscles:
                key = str(muscle).lower()
                weekly_sets[key] = weekly_sets.get(key, 0) + sets

        focus_is_push = "push" in focus or "فشار" in focus
        focus_is_pull = "pull" in focus or "کشش" in focus
        if focus_is_push and any(pattern in PULL_PATTERNS for pattern in day_patterns):
            raise WorkoutFormatError(f"روز «{day_name}» با تمرکز Push شامل حرکت کششی است.")
        if focus_is_pull and any(pattern in PUSH_PATTERNS for pattern in day_patterns):
            raise WorkoutFormatError(f"روز «{day_name}» با تمرکز Pull شامل حرکت فشاری است.")
        if focus_is_pull and day_patterns.count("vertical_pull") > 1:
            warnings.append(f"در «{day_name}» بیش از یک حرکت کشش عمودی وجود دارد؛ تنوع و هم‌پوشانی بررسی شود.")

    high_volume = [f"{muscle}: {sets} ست" for muscle, sets in weekly_sets.items() if sets > 20]
    if high_volume:
        warnings.append("حجم هفتگی بعضی عضلات از ۲۰ ست بیشتر است (" + "، ".join(high_volume) + ").")

    limitations = _clean(profile.get("limitations"), "محدودیت‌ها", required=False, max_length=350).lower()
    medication = _clean(profile.get("medication"), "دارو", required=False, max_length=200).lower()
    no_flags = {"", "خیر", "ندارد", "none", "no"}
    if limitations not in no_flags or medication not in no_flags:
        warnings.append("پروفایل شامل محدودیت پزشکی یا دارو است؛ برنامه باید پیش از اجرا توسط متخصص مربوطه بررسی شود.")

    return list(dict.fromkeys(warnings))


def format_workout_plan(payload: Any, profile: Dict[str, Any] | None = None) -> str:
    """Validate and render a stable, readable Persian workout plan."""
    data = _extract_json(payload)
    profile = profile or {}
    warnings = validate_workout_plan(data, profile)

    title = _clean(data.get("title") or "برنامه تمرینی هفتگی", "عنوان", max_length=100)
    goal = _clean(data.get("goal") or profile.get("goal") or "طبق پروفایل ثبت‌شده", "هدف", max_length=160)
    days = data["weekly_schedule"]
    lines: List[str] = [
        "🏋️‍♂️ برنامه تمرینی FitCoach AI",
        f"📌 {title}",
        f"🎯 هدف: {goal}",
    ]
    name = _clean(profile.get("name"), "نام ورزشکار", required=False, max_length=80)
    level = _clean(profile.get("experience"), "سطح", required=False, max_length=100)
    equipment = _clean(profile.get("equipment"), "تجهیزات", required=False, max_length=100)
    meta = [item for item in (f"👤 {name}" if name else "", f"📊 سطح: {level}" if level else "", f"🏟 تجهیزات: {equipment}" if equipment else "") if item]
    if meta:
        lines.extend(meta)

    warmup = _clean(data.get("warmup"), "گرم‌کردن", required=False, max_length=500)
    if warmup:
        lines.extend(["", "🔥 گرم‌کردن", warmup])

    for index, day in enumerate(days, start=1):
        day_name = _clean(day.get("day") or f"روز {index}", "نام روز", max_length=80)
        focus = _clean(day.get("focus"), "تمرکز روز", required=False, max_length=140)
        exercises = day["exercises"]
        lines.extend(["", "━━━━━━━━━━━━", f"📅 {day_name}" + (f" | {focus}" if focus else "")])
        for ex_index, exercise in enumerate(exercises, start=1):
            ex_name = _clean(exercise.get("name"), "نام حرکت", max_length=120)
            sets = _clean(exercise.get("sets"), "ست", max_length=30)
            reps = _clean(exercise.get("reps"), "تکرار", max_length=40)
            rest = _clean(exercise.get("rest"), "استراحت", max_length=40)
            rir = _clean(exercise.get("rir"), "RIR", required=False, max_length=30)
            note = _clean(exercise.get("note"), "نکته اجرا", required=False, max_length=220)
            lines.append(f"{ex_index}. {ex_name}")
            lines.append(f"   • ست: {sets}  |  تکرار: {reps}")
            lines.append(f"   • استراحت: {rest}" + (f"  |  RIR: {rir}" if rir else ""))
            if note:
                lines.append(f"   • نکته اجرا: {note}")
        day_note = _clean(day.get("note"), "نکته روز", required=False, max_length=250)
        if day_note:
            lines.append(f"📝 نکته روز: {day_note}")

    cooldown = _clean(data.get("cooldown"), "سردکردن", required=False, max_length=400)
    general_notes = data.get("general_notes") or []
    cautions = data.get("medical_cautions") or []
    if isinstance(general_notes, str):
        general_notes = [general_notes]
    if isinstance(cautions, str):
        cautions = [cautions]
    if not isinstance(general_notes, list) or not isinstance(cautions, list):
        raise WorkoutFormatError("بخش نکات برنامه ساختار معتبری ندارد.")

    lines.extend(["", "━━━━━━━━━━━━", "📌 نکات مهم برنامه"])
    if cooldown:
        lines.append(f"🧘 سردکردن: {cooldown}")
    for note in general_notes[:8]:
        clean_note = _clean(note, "نکته", required=False, max_length=250)
        if clean_note:
            lines.append(f"• {clean_note}")
    for caution in cautions[:5]:
        clean_caution = _clean(caution, "هشدار", required=False, max_length=250)
        if clean_caution:
            lines.append(f"⚠️ {clean_caution}")
    if warnings:
        lines.extend(["", "⚠️ موارد نیازمند بازبینی مربی:"])
        lines.extend(f"• {warning}" for warning in warnings)
    lines.append("⛔ در صورت درد تیز، سرگیجه، درد قفسه سینه یا تنگی نفس، تمرین را متوقف کن و ارزیابی پزشکی بگیر.")
    lines.append("— FitCoach AI")
    return "\n".join(lines)
