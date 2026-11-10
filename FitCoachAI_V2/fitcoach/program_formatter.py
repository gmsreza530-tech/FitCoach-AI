"""Deterministic Telegram formatter for structured workout plans."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List


class WorkoutFormatError(ValueError):
    """Raised when an AI workout payload is incomplete or malformed."""


def _clean(value: Any, field: str, *, required: bool = True, max_length: int = 500) -> str:
    if value is None:
        value = ""
    text = str(value).strip()
    if required and not text:
        raise WorkoutFormatError(f"فیلد «{field}» خالی است.")
    if len(text) > max_length:
        text = text[:max_length].rstrip()
    return text


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


def format_workout_plan(payload: Any, profile: Dict[str, Any] | None = None) -> str:
    """Validate and render a stable, readable Persian workout plan."""
    data = _extract_json(payload)
    profile = profile or {}

    title = _clean(data.get("title") or "برنامه تمرینی هفتگی", "عنوان", max_length=100)
    goal = _clean(data.get("goal") or profile.get("goal") or "طبق پروفایل ثبت‌شده", "هدف", max_length=160)
    days = data.get("weekly_schedule")
    if not isinstance(days, list) or not 1 <= len(days) <= 7:
        raise WorkoutFormatError("تعداد روزهای برنامه باید بین ۱ تا ۷ باشد.")

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

    limitations = _clean(profile.get("limitations"), "محدودیت‌ها", required=False, max_length=350)
    medication = _clean(profile.get("medication"), "دارو", required=False, max_length=200)
    if (limitations and limitations.lower() not in {"خیر", "ندارد", "none", "no"}) or (medication and medication.lower() not in {"خیر", "ندارد", "none", "no"}):
        lines.extend(["", "⚠️ توجه ایمنی: در پروفایل محدودیت پزشکی یا مصرف دارو ثبت شده است. اجرای برنامه باید با نظر متخصص مربوطه تأیید شود."])

    warmup = _clean(data.get("warmup"), "گرم‌کردن", required=False, max_length=500)
    if warmup:
        lines.extend(["", "🔥 گرم‌کردن", warmup])

    for index, day in enumerate(days, start=1):
        if not isinstance(day, dict):
            raise WorkoutFormatError(f"اطلاعات روز {index} معتبر نیست.")
        day_name = _clean(day.get("day") or f"روز {index}", "نام روز", max_length=80)
        focus = _clean(day.get("focus"), "تمرکز روز", required=False, max_length=140)
        exercises = day.get("exercises")
        if not isinstance(exercises, list) or not 1 <= len(exercises) <= 15:
            raise WorkoutFormatError(f"روز «{day_name}» باید حداقل یک و حداکثر ۱۵ حرکت داشته باشد.")
        lines.extend(["", f"━━━━━━━━━━━━", f"📅 {day_name}" + (f" | {focus}" if focus else "")])
        for ex_index, exercise in enumerate(exercises, start=1):
            if not isinstance(exercise, dict):
                raise WorkoutFormatError(f"حرکت {ex_index} در {day_name} معتبر نیست.")
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
    lines.append("⛔ در صورت درد تیز، سرگیجه، درد قفسه سینه یا تنگی نفس، تمرین را متوقف کن و ارزیابی پزشکی بگیر.")
    lines.append("— FitCoach AI")
    return "\n".join(lines)
