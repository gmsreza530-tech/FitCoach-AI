import asyncio, tempfile
from pathlib import Path
from aiogram import Bot,Dispatcher,F
from aiogram.filters import Command,CommandStart
from aiogram.types import Message,ReplyKeyboardMarkup,KeyboardButton,FSInputFile
from aiogram.fsm.state import StatesGroup,State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from fitcoach.config import BOT_TOKEN,COACH_IDS,ADMIN_IDS,APPROVAL_MODE,UPLOAD_DIR,SUBSCRIPTION_DAYS,SUBSCRIPTION_PLAN_LIMIT,FREE_MODE
from fitcoach.db import *
from fitcoach.ai import ask, analyze_body_photo
from fitcoach.program_formatter import format_workout_plan, validate_workout_plan, WorkoutFormatError, _profile_days
from fitcoach.excel_import import import_excel
from fitcoach.video_analysis import analyze_video

class Form(StatesGroup):
    name=State(); age=State(); sex=State(); height=State(); weight=State()
    goal=State(); experience=State(); equipment=State(); days=State()
    recovery=State(); limitations=State(); medication=State(); notes=State()
class ProgressForm(StatesGroup): entry=State()
class QuestionForm(StatesGroup): question=State()
class WorkoutLogForm(StatesGroup): exercise=State(); sets=State(); reps=State(); weight=State(); rir=State(); notes=State()
class NutritionForm(StatesGroup): meal=State(); calories=State(); protein=State(); carbs=State(); fat=State(); notes=State()
class MeasurementForm(StatesGroup): weight=State(); waist=State(); chest=State(); arm=State(); thigh=State()
class CheckinForm(StatesGroup): sleep=State(); energy=State(); soreness=State(); adherence=State(); notes=State()
class DeleteForm(StatesGroup): confirm=State()
class BodyPhotoForm(StatesGroup): consent=State(); view=State(); photo=State()
class ExtendedMeasurementForm(StatesGroup): hip=State(); shoulder=State(); forearm=State(); calf=State(); neck=State()

def split_telegram_text(text, limit=3900):
    """Split long plain-text replies without dropping content."""
    text = str(text or "").strip()
    if not text:
        return []
    chunks, current = [], ""
    for paragraph in text.split("\n"):
        while len(paragraph) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        candidate = paragraph if not current else current + "\n" + paragraph
        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def send_long_text(message: Message, text: str, limit=3900):
    for chunk in split_telegram_text(text, limit=limit):
        await message.answer(chunk)


def kb(show_coach_entry=False):
    keyboard = [
      [KeyboardButton(text="👤 حساب کاربری"),KeyboardButton(text="👛 کیف پول")],
      [KeyboardButton(text="📝 تکمیل پروفایل"),KeyboardButton(text="👤 پروفایل من")],
      [KeyboardButton(text="🏋️ برنامه تمرین"),KeyboardButton(text="🥗 راهنمای تغذیه")],
      [KeyboardButton(text="💬 سؤال از مربی"),KeyboardButton(text="📈 ثبت پیشرفت")],
      [KeyboardButton(text="🔚 پایان گفتگو")],
      [KeyboardButton(text="🎥 تحلیل فرم حرکت"),KeyboardButton(text="📚 برنامه‌های قبلی")],
      [KeyboardButton(text="🏃 ثبت تمرین"),KeyboardButton(text="🍽 ثبت غذا")],
      [KeyboardButton(text="⚖️ اندازه‌گیری بدن"),KeyboardButton(text="🛌 چک‌این روزانه")],
      [KeyboardButton(text="📊 گزارش من"),KeyboardButton(text="ℹ️ راهنما")],
      [KeyboardButton(text="📸 پرونده تصویری"),KeyboardButton(text="📏 اندازه‌های تکمیلی")]
    ]
    if show_coach_entry:
        keyboard.append([KeyboardButton(text="🧑‍🏫 بازگشت به پنل مربی")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def coach_kb():
    return ReplyKeyboardMarkup(keyboard=[
      [KeyboardButton(text="👥 ورزشکاران من"), KeyboardButton(text="📥 درخواست‌های بررسی")],
      [KeyboardButton(text="📚 دانش اختصاصی"), KeyboardButton(text="📤 راهنمای بارگذاری دانش")],
      [KeyboardButton(text="🏋️ امکانات ورزشی من")]
    ], resize_keyboard=True)

def is_coach(uid): return uid in COACH_IDS or uid in ADMIN_IDS

async def main():
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN is missing")
    init(); UPLOAD_DIR.mkdir(exist_ok=True)
    bot=Bot(BOT_TOKEN); dp=Dispatcher(storage=MemoryStorage())
    # Pose analysis is CPU-heavy; serialize it to prevent parallel uploads
    # from exhausting the small production instance. Telegram handlers stay responsive.
    video_semaphore = asyncio.Semaphore(1)

    @dp.message(CommandStart())
    async def start(m: Message, state: FSMContext):
        await state.clear()
        uid = m.from_user.id
        role = "admin" if uid in ADMIN_IDS else ("coach" if uid in COACH_IDS else "athlete")
        register_account(m.from_user, role=role)
        # Safe automatic assignment only when exactly one coach is configured.
        if role == "athlete" and len(COACH_IDS) == 1 and athlete_coach(uid) is None:
            configured_coach_id = next(iter(COACH_IDS))
            # The coach must have opened the bot once so their account role exists.
            coach_account = account_info(configured_coach_id)
            if coach_account and coach_account.get("role") == "coach":
                assign_athlete(uid, configured_coach_id)
        if is_coach(uid):
            await m.answer(
                "به FitCoach AI خوش آمدی. 🧑‍🏫\n"
                "از پنل مربی برای مدیریت استفاده کن؛ برای تمرین شخصی، امکانات ورزشی من را باز کن.",
                reply_markup=coach_kb()
            )
        else:
            await m.answer(
                "به FitCoach AI خوش آمدی. 🏋️\n"
                "ابتدا پروفایل را تکمیل کن. این ربات ابزار آموزشی است و جایگزین پزشک نیست.",
                reply_markup=kb()
            )

    @dp.message(Command("cancel"))
    async def cancel(m:Message,state:FSMContext):
        await state.clear(); await m.answer("عملیات لغو شد.",reply_markup=coach_kb() if is_coach(m.from_user.id) else kb())

    @dp.message(F.text=="📝 تکمیل پروفایل")
    async def begin(m:Message,state:FSMContext):
        await state.clear(); await state.set_state(Form.name); await m.answer("نام یا نام مستعار؟")

    @dp.message(Form.name)
    async def f1(m: Message, state: FSMContext): await state.update_data(name=(m.text or "")[:80]); await state.set_state(Form.age); await m.answer("سن؟ (۱۳ تا ۹۰)")
    @dp.message(Form.age)
    async def f2(m: Message, state: FSMContext):
        try: n=int(m.text)
        except: n=0
        if not 13<=n<=90: return await m.answer("سن معتبر وارد کن.")
        await state.update_data(age=n); await state.set_state(Form.sex); await m.answer("جنسیت (اختیاری): مرد / زن / ترجیح می‌دهم نگویم")
    @dp.message(Form.sex)
    async def f3(m: Message, state: FSMContext): await state.update_data(sex=(m.text or "")[:50]); await state.set_state(Form.height); await m.answer("قد به سانتی‌متر؟")
    @dp.message(Form.height)
    async def f4(m: Message, state: FSMContext):
        try: n=float(m.text.replace(",",".")); assert 100<=n<=230
        except: return await m.answer("قد معتبر بین ۱۰۰ تا ۲۳۰ وارد کن.")
        await state.update_data(height=n); await state.set_state(Form.weight); await m.answer("وزن به کیلوگرم؟")
    @dp.message(Form.weight)
    async def f5(m: Message, state: FSMContext):
        try: n=float(m.text.replace(",",".")); assert 25<=n<=300
        except: return await m.answer("وزن معتبر وارد کن.")
        await state.update_data(weight=n); await state.set_state(Form.goal); await m.answer("هدف: افزایش حجم / کاهش چربی / قدرت / تناسب / آمادگی ورزشی")
    @dp.message(Form.goal)
    async def f6(m: Message, state: FSMContext): await state.update_data(goal=(m.text or "")[:150]); await state.set_state(Form.experience); await m.answer("سابقه و سطح تمرینت؟ مبتدی / متوسط / پیشرفته + توضیح")
    @dp.message(Form.experience)
    async def f7(m: Message, state: FSMContext): await state.update_data(experience=(m.text or "")[:250]); await state.set_state(Form.equipment); await m.answer("امکانات: باشگاه کامل / دمبل خانه / وزن بدن / سایر")
    @dp.message(Form.equipment)
    async def f8(m: Message, state: FSMContext): await state.update_data(equipment=(m.text or "")[:150]); await state.set_state(Form.days); await m.answer("هفته‌ای چند جلسه می‌توانی تمرین کنی؟ ۱ تا ۷")
    @dp.message(Form.days)
    async def f9(m: Message, state: FSMContext):
        try: n=int(m.text); assert 1<=n<=7
        except: return await m.answer("عدد ۱ تا ۷ وارد کن.")
        await state.update_data(days=n); await state.set_state(Form.recovery); await m.answer("وضعیت خواب و ریکاوری؟ (مثلاً ۷ ساعت خواب، استرس متوسط)")
    @dp.message(Form.recovery)
    async def f10(m: Message, state: FSMContext): await state.update_data(recovery=(m.text or "")[:250]); await state.set_state(Form.limitations); await m.answer("تمام آسیب‌ها، بیماری‌ها یا محدودیت‌های پزشکی را با کاما جدا کن. اگر نداری بنویس: خیر")
    @dp.message(Form.limitations)
    async def f11(m: Message, state: FSMContext): await state.update_data(limitations=(m.text or "")[:700]); await state.set_state(Form.medication); await m.answer("داروی منظم مصرف می‌کنی؟ خیر / بله + نام دارو (در صورت تمایل)")
    @dp.message(Form.medication)
    async def f12(m: Message, state: FSMContext): await state.update_data(medication=(m.text or "")[:350]); await state.set_state(Form.notes); await m.answer("توضیحات تکمیلی، حساسیت غذایی یا حرکات ممنوع؟ اگر نداری: ندارد")
    @dp.message(Form.notes)
    async def f13(m: Message, state: FSMContext):
        await state.update_data(notes=(m.text or "")[:700]); d=await state.get_data(); save_profile(m.from_user.id,d); await state.clear()
        await m.answer("پروفایل ذخیره شد. اکنون می‌توانی از امکانات استفاده کنی.",reply_markup=kb(show_coach_entry=is_coach(m.from_user.id)))

    @dp.message(F.text=="👤 حساب کاربری")
    async def show_account(m: Message):
        uid = m.from_user.id
        role = "مدیر" if uid in ADMIN_IDS else ("مربی" if uid in COACH_IDS else "ورزشکار")
        p = profile(uid)
        a = account_info(uid)
        name = (a or {}).get("first_name") or m.from_user.first_name or "کاربر"
        username = f"@{a['username']}" if a and a.get("username") else "ثبت نشده"
        profile_status = "تکمیل‌شده" if p else "تکمیل‌نشده"
        await m.answer(
            "👤 حساب کاربری FitCoach AI\n"
            f"نام: {name}\n"
            f"شناسه تلگرام: `{uid}`\n"
            f"نام کاربری: {username}\n"
            f"نقش: {role}\n"
            f"وضعیت پروفایل ورزشی: {profile_status}\n"
            f"موجودی کیف پول: {wallet_balance(uid):,} تومان"
        )

    @dp.message(F.text=="👛 کیف پول")
    async def show_wallet(m: Message):
        uid = m.from_user.id
        balance = wallet_balance(uid)
        history = wallet_history(uid, limit=5)
        lines = ["👛 کیف پول FitCoach AI", f"موجودی: {balance:,} تومان"]
        if history:
            lines.append("\\nآخرین تراکنش‌ها:")
            for item in history:
                sign = "+" if item["amount"] > 0 else ""
                lines.append(
                    f"• {sign}{item['amount']:,} تومان | {item['description'] or item['transaction_type']}"
                )
        else:
            lines.append("\\nهنوز تراکنشی ثبت نشده است.")
        lines.append("\\nافزایش موجودی و پرداخت آنلاین در مرحله اتصال درگاه فعال خواهد شد.")
        await m.answer("\\n".join(lines))

    @dp.message(F.text=="👤 پروفایل من")
    async def show_profile(m):
        p=profile(m.from_user.id)
        if not p: return await m.answer("ابتدا پروفایل را تکمیل کن.")
        keys=[("نام","name"),("سن","age"),("قد","height"),("وزن","weight"),("هدف","goal"),("سابقه","experience"),("تجهیزات","equipment"),("جلسات","days"),("ریکاوری","recovery"),("محدودیت‌ها","limitations"),("دارو","medication"),("توضیحات","notes")]
        await m.answer("👤 پروفایل:\n"+"\n".join(f"{a}: {p.get(b) or '—'}" for a,b in keys))

    async def generate(m,kind,question):
        p=profile(m.from_user.id)
        if not p: return await m.answer("ابتدا پروفایل را تکمیل کن.")
        visual_assessment = latest_body_assessment(m.from_user.id)
        if visual_assessment:
            p["visual_assessment"] = visual_assessment
        if kind == "workout" and _profile_days(p) is None:
            return await m.answer(
                "برای ساخت برنامه دقیق، تعداد جلسات تمرین در هفته در پروفایلت مشخص یا معتبر نیست. "
                "از بخش «تکمیل پروفایل» تعداد جلسات را بین ۱ تا ۷ ثبت کن؛ "
                "تا آن زمان هیچ درخواست AI یا سهمیه برنامه مصرف نمی‌شود."
            )
        allowed, access_message = check_plan_access(m.from_user.id)
        if not allowed:
            return await m.answer(access_message + "\nبرای فعال‌سازی، با مربی تماس بگیر.")
        coach_id = athlete_coach(m.from_user.id)
        if coach_id is None:
            return await m.answer("هنوز مربی به حساب تو اختصاص داده نشده است. مدیر باید با دستور /assign شناسه_ورزشکار شناسه_مربی این اتصال را انجام دهد.")
        await m.answer("در حال ساخت پاسخ بر اساس پروفایل و فایل‌های دانش مربی... ⏳")
        if kind == "workout":
            quality_warnings = []
            answer = None
            validation_error = None

            # One corrective retry is safer than exposing an incomplete plan.
            for attempt in range(2):
                retry_question = question
                if validation_error:
                    expected_sessions = p.get("days")
                    session_instruction = (
                        f" تعداد جلسات مورد انتظار دقیقاً {expected_sessions} است؛ "
                        f"weekly_schedule باید دقیقاً {expected_sessions} عضو داشته باشد و روز استراحت در آن نیاید."
                        if expected_sessions not in (None, "")
                        else " تعداد جلسات در پروفایل مشخص نیست؛ حدس نزن و سؤال تکمیلی بپرس."
                    )
                    retry_question += (
                        "\n\nاصلاح اجباری خروجی قبلی: اعتبارسنجی برنامه این خطا را گزارش کرد: "
                        + validation_error
                        + ". تمام پروفایل ورزشکار را دوباره مبنا قرار بده."
                        + session_instruction
                        + " یک برنامه کامل و تازه تولید کن؛ فقط JSON معتبر با تمام فیلدهای اجباری. "
                        "خروجی قبلی را ادامه نده، تعداد جلسات را تغییر نده و متن ناقص را تکرار نکن."
                    )

                try:
                    raw_answer = await asyncio.to_thread(
                        ask, p, retry_question, coach_id, output_format="workout_json"
                    )
                except Exception as exc:
                    print(f"Workout AI provider failure: {type(exc).__name__}: {exc}")
                    return await m.answer("سرویس هوش مصنوعی موقتاً پاسخ نداد. هیچ سهمیه‌ای مصرف نشد؛ چند دقیقه بعد دوباره تلاش کن.")
                try:
                    quality_warnings = validate_workout_plan(raw_answer, p)
                    answer = format_workout_plan(raw_answer, p)
                    validation_error = None
                    break
                except WorkoutFormatError as exc:
                    validation_error = str(exc)
                    print(
                        f"Workout validation failed (attempt {attempt + 1}/2): "
                        f"{validation_error}; raw_length={len(raw_answer or '')}"
                    )

            if answer is None:
                return await m.answer(
                    "ساخت برنامه در دو تلاش ناموفق بود و برای جلوگیری از ارسال برنامه ناقص متوقف شد. "
                    "لطفاً دوباره تلاش کن؛ اگر تکرار شد، گزارش خطای Runtime Logs را برای بررسی بفرست."
                )
        else:
            try:
                answer=await asyncio.to_thread(ask,p,question,coach_id)
            except Exception as exc:
                print(f"AI provider failure: {type(exc).__name__}: {exc}")
                return await m.answer("سرویس هوش مصنوعی موقتاً پاسخ نداد. هیچ سهمیه‌ای مصرف نشد؛ چند دقیقه بعد دوباره تلاش کن.")
        # Persist the completed plan and consume quota in one DB transaction.
        # Any quality warning or declared health constraint requires human review.
        status="pending" if (APPROVAL_MODE=="both" or (kind == "workout" and quality_warnings)) else "approved"
        pid, ok, msg = create_program_with_quota(
            m.from_user.id, coach_id, kind, question, answer, status
        )
        if not ok:
            return await m.answer(msg + "\nبرای فعال‌سازی، با مربی تماس بگیر.")
        if status=="pending":
            await m.answer(f"درخواست برنامه ثبت شد و برای تأیید مربی ارسال شد. کد پیگیری: {pid}")
            if coach_id:
                try: await bot.send_message(coach_id,f"درخواست جدید برنامه #{pid}\nورزشکار: {m.from_user.id}\nنوع: {kind}\nبرای بررسی: /pending")
                except: pass
        else:
            await send_long_text(m, answer)
    @dp.message(F.text=="🏋️ برنامه تمرین")
    async def workout(m): await generate(m,"workout","برنامه تمرینی هفتگی شخصی‌سازی‌شده با جزئیات روزها، حرکت، ست، تکرار، استراحت، RIR و نکات فرم اجرا طراحی کن. محدودیت‌های پزشکی را در نظر بگیر.")
    @dp.message(F.text=="🥗 راهنمای تغذیه")
    async def food(m): await generate(m,"nutrition","راهنمای تغذیه عمومی و قابل اجرا برای هدف من بده؛ نمونه وعده و منابع پروتئین ارائه کن. رژیم افراطی نده.")

    async def process_coach_message(m: Message):
        uid = m.from_user.id
        p = profile(uid)
        if not p:
            end_conversation(uid)
            return await m.answer("ابتدا پروفایل را تکمیل کن.")
        question = (m.text or "").strip()
        if not question:
            return await m.answer("لطفاً پیام متنی بفرست.")
        question = question[:12000]
        coach_id = athlete_coach(uid)
        if coach_id is None:
            return await m.answer("هنوز مربی به حساب تو اختصاص داده نشده است. مدیر باید اتصال مربی را انجام دهد.")
        visual_assessment = latest_body_assessment(uid)
        if visual_assessment:
            p["visual_assessment"] = visual_assessment
        history = get_conversation_history(uid, limit=12)
        add_conversation_message(uid, "user", question)
        await m.answer("در حال بررسی سؤالت... ⏳")
        try:
            answer = await asyncio.to_thread(ask, p, question, coach_id, history=history)
        except Exception as exc:
            print(f"Coach chat AI provider failure: {type(exc).__name__}: {exc}")
            return await m.answer("سرویس هوش مصنوعی موقتاً در دسترس نیست؛ پیام تو ذخیره شد و می‌توانی دوباره تلاش کنی.")
        add_conversation_message(uid, "assistant", answer)
        await send_long_text(m, answer)

    @dp.message(F.text=="💬 سؤال از مربی")
    async def ask_start(m: Message, state: FSMContext):
        if not profile(m.from_user.id):
            return await m.answer("ابتدا پروفایل را تکمیل کن.")
        start_conversation(m.from_user.id)
        await state.set_state(QuestionForm.question)
        if get_conversation_history(m.from_user.id, limit=12):
            await m.answer("💬 گفت‌وگو فعال شد؛ تاریخچه قبلی هم در دسترس است. برای پایان /end_chat را بزن.")
        else:
            await m.answer("💬 گفت‌وگو فعال شد. پیام‌هایت را یکی‌یکی بفرست. برای پایان /end_chat یا دکمه «🔚 پایان گفتگو» را بزن.")

    @dp.message(Command("end_chat"))
    async def end_chat_command(m: Message, state: FSMContext):
        end_conversation(m.from_user.id)
        await state.clear()
        await m.answer("گفت‌وگو پایان یافت؛ تاریخچه محفوظ است.", reply_markup=kb(show_coach_entry=is_coach(m.from_user.id)))

    @dp.message(F.text=="🔚 پایان گفتگو")
    async def end_chat_button(m: Message, state: FSMContext):
        end_conversation(m.from_user.id)
        await state.clear()
        await m.answer("گفت‌وگو پایان یافت؛ تاریخچه محفوظ است.", reply_markup=kb())

    @dp.message(QuestionForm.question, F.text)
    async def ask_user(m: Message):
        if not is_conversation_active(m.from_user.id):
            return await m.answer("گفت‌وگوی فعالی نداری. برای شروع «💬 سؤال از مربی» را بزن.")
        await process_coach_message(m)

    @dp.message(F.text=="📈 ثبت پیشرفت")
    async def progress_start(m: Message, state: FSMContext): await state.set_state(ProgressForm.entry); await m.answer("وزن، رکوردها، تعداد تکرار، احساس تمرین یا تغییراتت را بنویس.")
    @dp.message(ProgressForm.entry)
    async def progress_save(m: Message, state: FSMContext):
        add_progress(m.from_user.id,(m.text or "")[:1000]); await state.clear(); await m.answer("پیشرفت ثبت شد.")
    @dp.message(F.text=="📚 برنامه‌های قبلی")
    async def old_programs(m):
        with db() as c:
            rows=c.execute("SELECT id,kind,status,created_at,content FROM programs WHERE athlete_id=? ORDER BY id DESC LIMIT 5",(m.from_user.id,)).fetchall()
        if not rows: return await m.answer("هنوز برنامه‌ای ثبت نشده.")
        for r in rows:
            await m.answer(f"برنامه #{r['id']} | {r['kind']} | {r['status']}\n{r['content'][:3500]}")

    # Structured workout logging
    @dp.message(F.text=="🏃 ثبت تمرین")
    async def workout_log_start(m: Message, state: FSMContext):
        if not profile(m.from_user.id): return await m.answer("ابتدا پروفایل را تکمیل کن.")
        await state.clear(); await state.set_state(WorkoutLogForm.exercise); await m.answer("نام حرکت؟")
    @dp.message(WorkoutLogForm.exercise)
    async def wl1(m: Message, state: FSMContext): await state.update_data(exercise=(m.text or "")[:100]); await state.set_state(WorkoutLogForm.sets); await m.answer("چند ست؟")
    @dp.message(WorkoutLogForm.sets)
    async def wl2(m: Message, state: FSMContext):
        try: v=int(m.text); assert 1<=v<=30
        except: return await m.answer("عدد ست باید بین ۱ تا ۳۰ باشد.")
        await state.update_data(sets=v); await state.set_state(WorkoutLogForm.reps); await m.answer("تکرار هر ست؟ مثلاً ۱۰،۱۰،۸")
    @dp.message(WorkoutLogForm.reps)
    async def wl3(m: Message, state: FSMContext): await state.update_data(reps=(m.text or "")[:80]); await state.set_state(WorkoutLogForm.weight); await m.answer("وزنه به کیلوگرم؟ برای وزن بدن ۰ بنویس.")
    @dp.message(WorkoutLogForm.weight)
    async def wl4(m: Message, state: FSMContext):
        try: v=float(m.text.replace(",",".")); assert 0<=v<=1000
        except: return await m.answer("وزنه معتبر وارد کن.")
        await state.update_data(weight=v); await state.set_state(WorkoutLogForm.rir); await m.answer("RIR چند بود؟ عدد ۰ تا 10 یا نامشخص")
    @dp.message(WorkoutLogForm.rir)
    async def wl5(m: Message, state: FSMContext):
        try: v=None if "نامشخص" in m.text else float(m.text.replace(",",".")); assert v is None or 0<=v<=10
        except: return await m.answer("RIR باید بین ۰ تا ۱۰ یا نامشخص باشد.")
        await state.update_data(rir=v); await state.set_state(WorkoutLogForm.notes); await m.answer("یادداشت یا میزان درد/ناراحتی؟ اگر نداری بنویس خیر.")
    @dp.message(WorkoutLogForm.notes)
    async def wl6(m: Message, state: FSMContext):
        d=await state.get_data(); add_workout(m.from_user.id,d["exercise"],d["sets"],d["reps"],d["weight"],d["rir"],(m.text or "")[:300]); await state.clear(); await m.answer("✅ تمرین ثبت شد.")

    # Nutrition log
    @dp.message(F.text=="🍽 ثبت غذا")
    async def food_log_start(m: Message, state: FSMContext):
        await state.clear(); await state.set_state(NutritionForm.meal); await m.answer("نام وعده یا غذا؟")
    @dp.message(NutritionForm.meal)
    async def nf1(m: Message, state: FSMContext): await state.update_data(meal=(m.text or "")[:100]); await state.set_state(NutritionForm.calories); await m.answer("کالری تقریبی؟")
    async def nutrition_number(m,s,key,next_state,prompt,maximum):
        try: v=float(m.text.replace(",",".")); assert 0<=v<=maximum
        except: return await m.answer(f"عدد معتبر بین صفر تا {maximum} وارد کن.")
        await s.update_data(**{key:v}); await s.set_state(next_state); await m.answer(prompt)
    @dp.message(NutritionForm.calories)
    async def nf2(m: Message, state: FSMContext): await nutrition_number(m,state,"calories",NutritionForm.protein,"پروتئین به گرم؟",10000)
    @dp.message(NutritionForm.protein)
    async def nf3(m: Message, state: FSMContext): await nutrition_number(m,state,"protein",NutritionForm.carbs,"کربوهیدرات به گرم؟",10000)
    @dp.message(NutritionForm.carbs)
    async def nf4(m: Message, state: FSMContext): await nutrition_number(m,state,"carbs",NutritionForm.fat,"چربی به گرم؟",10000)
    @dp.message(NutritionForm.fat)
    async def nf5(m: Message, state: FSMContext): await nutrition_number(m,state,"fat",NutritionForm.notes,"یادداشت اختیاری؟",10000)
    @dp.message(NutritionForm.notes)
    async def nf6(m: Message, state: FSMContext):
        d=await state.get_data(); add_nutrition(m.from_user.id,d["meal"],d["calories"],d["protein"],d["carbs"],d["fat"],(m.text or "")[:250]); await state.clear(); await m.answer("✅ وعده غذایی ثبت شد.")

    # Body measurements
    @dp.message(F.text=="⚖️ اندازه‌گیری بدن")
    async def measure_start(m: Message, state: FSMContext):
        await state.clear(); await state.set_state(MeasurementForm.weight); await m.answer("وزن فعلی به کیلوگرم؟")
    async def optional_measure(m,s,key,next_state,prompt,low,high):
        t=(m.text or "").strip()
        if t in ("-","ندارم","خالی"): v=None
        else:
            try: v=float(t.replace(",",".")); assert low<=v<=high
            except: return await m.answer(f"عدد بین {low} تا {high} یا «ندارم» وارد کن.")
        await s.update_data(**{key:v}); await s.set_state(next_state); await m.answer(prompt)
    @dp.message(MeasurementForm.weight)
    async def ms1(m: Message, state: FSMContext): await optional_measure(m,state,"weight",MeasurementForm.waist,"دور کمر به سانتی‌متر؟ یا ندارم",25,250)
    @dp.message(MeasurementForm.waist)
    async def ms2(m: Message, state: FSMContext): await optional_measure(m,state,"waist",MeasurementForm.chest,"دور سینه؟ یا ندارم",25,250)
    @dp.message(MeasurementForm.chest)
    async def ms3(m: Message, state: FSMContext): await optional_measure(m,state,"chest",MeasurementForm.arm,"دور بازو؟ یا ندارم",10,100)
    @dp.message(MeasurementForm.arm)
    async def ms4(m: Message, state: FSMContext): await optional_measure(m,state,"arm",MeasurementForm.thigh,"دور ران؟ یا ندارم",15,150)
    @dp.message(MeasurementForm.thigh)
    async def ms5(m: Message, state: FSMContext):
        d=await state.get_data(); t=(m.text or "").strip()
        try: thigh=None if t in ("-","ندارم","خالی") else float(t.replace(",",".")); assert thigh is None or 15<=thigh<=150
        except: return await m.answer("عدد معتبر یا «ندارم» وارد کن.")
        add_measurement(m.from_user.id,d["weight"],d.get("waist"),d.get("chest"),d.get("arm"),thigh); await state.clear(); await m.answer("✅ اندازه‌گیری ثبت شد.")

    # Daily check-in
    @dp.message(F.text=="🛌 چک‌این روزانه")
    async def ci_start(m: Message, state: FSMContext):
        await state.clear(); await state.set_state(CheckinForm.sleep); await m.answer("دیشب چند ساعت خوابیدی؟")
    @dp.message(CheckinForm.sleep)
    async def ci1(m: Message, state: FSMContext):
        try: v=float(m.text.replace(",",".")); assert 0<=v<=24
        except: return await m.answer("عدد ساعت خواب بین صفر تا ۲۴ وارد کن.")
        await state.update_data(sleep=v); await state.set_state(CheckinForm.energy); await m.answer("انرژی امروز از ۱ تا ۵؟")
    @dp.message(CheckinForm.energy)
    async def ci2(m: Message, state: FSMContext):
        try: v=int(m.text); assert 1<=v<=5
        except: return await m.answer("عدد ۱ تا ۵ وارد کن.")
        await state.update_data(energy=v); await state.set_state(CheckinForm.soreness); await m.answer("کوفتگی/درد عضلانی از ۱ تا ۵؟ اگر درد تیز یا غیرعادی داری توضیح بده.")
    @dp.message(CheckinForm.soreness)
    async def ci3(m: Message, state: FSMContext):
        try: v=int(m.text); assert 1<=v<=5
        except: return await m.answer("عدد ۱ تا ۵ وارد کن.")
        await state.update_data(soreness=v); await state.set_state(CheckinForm.adherence); await m.answer("پایبندی به برنامه امروز از ۱ تا ۵؟")
    @dp.message(CheckinForm.adherence)
    async def ci4(m: Message, state: FSMContext):
        try: v=int(m.text); assert 1<=v<=5
        except: return await m.answer("عدد ۱ تا ۵ وارد کن.")
        await state.update_data(adherence=v); await state.set_state(CheckinForm.notes); await m.answer("یادداشت اختیاری؛ اگر نداری بنویس خیر.")
    @dp.message(CheckinForm.notes)
    async def ci5(m: Message, state: FSMContext):
        d=await state.get_data(); add_checkin(m.from_user.id,d["sleep"],d["energy"],d["soreness"],d["adherence"],(m.text or "")[:250]); await state.clear()
        warning="\nاگر درد شدید، تیز، رو به افزایش یا همراه با تورم/بی‌حسی است، تمرین را متوقف و ارزیابی تخصصی دریافت کن." if d["soreness"]>=4 else ""
        await m.answer("✅ چک‌این ثبت شد."+warning)

    @dp.message(F.text=="📊 گزارش من")
    async def my_report(m):
        uid=m.from_user.id
        w=recent_rows("workout_logs",uid,7); n=recent_rows("nutrition_logs",uid,20); b=recent_rows("body_measurements",uid,2); c=recent_rows("daily_checkins",uid,7)
        lines=["📊 گزارش فعالیت تو",f"ثبت تمرین اخیر: {len(w)}",f"وعده‌های ثبت‌شده: {len(n)}",f"چک‌این‌ها: {len(c)}"]
        if b:
            lines.append(f"آخرین وزن ثبت‌شده: {b[0]['weight']} کیلوگرم")
            if len(b)>1 and b[1]['weight'] is not None: lines.append(f"تغییر نسبت به ثبت قبلی: {b[0]['weight']-b[1]['weight']:+.1f} کیلوگرم")
        if c:
            avg_sleep=sum(x['sleep_hours'] for x in c)/len(c); lines.append(f"میانگین خواب ثبت‌شده: {avg_sleep:.1f} ساعت")
        if n:
            lines.append(f"مجموع کالری وعده‌های ثبت‌شده اخیر: {sum(x['calories'] for x in n):.0f} kcal (فقط داده‌های ثبت‌شده، نه لزوماً کل روز)")
        lines.append("\nاین گزارش بر اساس ورودی‌های ثبت‌شده است و جایگزین ارزیابی متخصص نیست.")
        await m.answer("\n".join(lines))

    @dp.message(Command("privacy"))
    async def privacy(m):
        await m.answer("اطلاعات پروفایل و سوابق برای ارائه خدمات ذخیره می‌شوند. برای درخواست حذف داده‌های حساب، دستور /delete_my_data را بزن. فایل‌های ویدئو در پردازش موقت حذف می‌شوند.")
    @dp.message(Command("delete_my_data"))
    async def delete_data(m: Message, state: FSMContext):
        await state.set_state(DeleteForm.confirm)
        await m.answer("حذف اطلاعات قابل بازگشت نیست. برای تأیید دقیقاً بنویس: حذف اطلاعات من")
    @dp.message(DeleteForm.confirm)
    async def delete_confirm(m: Message, state: FSMContext):
        await state.clear()
        if (m.text or "").strip() != "حذف اطلاعات من":
            return await m.answer("حذف لغو شد.")
        delete_athlete_data(m.from_user.id)
        await m.answer("اطلاعات ورزشی ذخیره‌شده این حساب حذف شد. برای استفاده دوباره پروفایل را از نو بساز.")

    async def show_coach_panel(m: Message):
        if not is_coach(m.from_user.id):
            return await m.answer("⛔ این بخش فقط برای مربی مجاز است.")
        await m.answer("🧑‍🏫 پنل اختصاصی مربی\nاز دکمه‌های زیر برای مدیریت استفاده کن.", reply_markup=coach_kb())

    @dp.message(F.text == "🧑‍🏫 بازگشت به پنل مربی")
    async def return_coach_panel(m: Message):
        await show_coach_panel(m)

    @dp.message(F.text == "🏋️ امکانات ورزشی من")
    async def coach_athlete_mode(m: Message):
        if not is_coach(m.from_user.id):
            return await m.answer("⛔ دسترسی غیرمجاز است.")
        await m.answer("حالت ورزشکار برای حساب شخصی مربی فعال شد.", reply_markup=kb(show_coach_entry=True))

    @dp.message(F.text == "👥 ورزشکاران من")
    async def coach_athletes(m: Message):
        if not is_coach(m.from_user.id):
            return await m.answer("⛔ دسترسی غیرمجاز است.")
        rows = list_coach_athletes(m.from_user.id, limit=30)
        if not rows:
            return await m.answer("هنوز ورزشکاری در این ربات ثبت‌نام نکرده است.", reply_markup=coach_kb())
        lines = ["👥 فهرست ورزشکاران (حداکثر ۳۰ نفر):"]
        for row in rows:
            name = row["name"] or "پروفایل تکمیل نشده"
            username = f"@{row['username']}" if row["username"] else "بدون نام کاربری"
            goal = f" | هدف: {row['goal']}" if row["goal"] else ""
            lines.append(f"• {name} | {username} | ID: {row['telegram_id']}{goal}")
        await send_long_text(m, "\n".join(lines))

    @dp.message(F.text == "📥 درخواست‌های بررسی")
    async def coach_pending_button(m: Message):
        if not is_coach(m.from_user.id):
            return await m.answer("⛔ دسترسی غیرمجاز است.")
        items = pending(m.from_user.id)
        if not items:
            return await m.answer("درخواست معلقی وجود ندارد.")
        for item in items[-10:]:
            await send_long_text(m, f"درخواست #{item['id']}\nورزشکار: {item['athlete_id']} | نوع: {item['kind']}\n{item['content']}\nتأیید: /approve {item['id']}\nرد: /reject {item['id']} دلیل")

    @dp.message(F.text == "📚 دانش اختصاصی")
    async def coach_knowledge_button(m: Message):
        if not is_coach(m.from_user.id):
            return await m.answer("⛔ دسترسی غیرمجاز است.")
        with db() as c:
            count = c.execute("SELECT COUNT(*) FROM coach_knowledge WHERE coach_id=?", (m.from_user.id,)).fetchone()[0]
        await m.answer(f"📚 دانش اختصاصی شما\nتعداد ردیف‌های ثبت‌شده: {count}")

    @dp.message(F.text == "📤 راهنمای بارگذاری دانش")
    async def coach_upload_help(m: Message):
        if not is_coach(m.from_user.id):
            return await m.answer("⛔ دسترسی غیرمجاز است.")
        await m.answer("فایل Excel با پسوند xlsx یا xlsm را همین‌جا ارسال کن. حداکثر حجم ۸ مگابایت است.")

    @dp.message(Command("coach"))
    async def coach_panel(m):
        await show_coach_panel(m)

    @dp.message(Command("knowledge"))
    async def knowledge_count(m):
        if not is_coach(m.from_user.id): return await m.answer("⛔ این فرمان فقط برای مربی مجاز است.")
        with db() as c: n=c.execute("SELECT COUNT(*) FROM coach_knowledge WHERE coach_id=?",(m.from_user.id,)).fetchone()[0]
        await m.answer(f"ردیف‌های دانش واردشده: {n}")

    @dp.message(F.document)
    async def excel_upload(m):
        if not is_coach(m.from_user.id): return await m.answer("⛔ بارگذاری فایل فقط برای مربی مجاز است.")
        doc=m.document
        if not doc.file_name.lower().endswith((".xlsx",".xlsm")): return await m.answer("فقط فایل Excel با پسوند xlsx یا xlsm ارسال کن.")
        if doc.file_size and doc.file_size>8*1024*1024: return await m.answer("حداکثر حجم فایل ۸ مگابایت است.")
        suffix=Path(doc.file_name).suffix
        with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as tmp: path=Path(tmp.name)
        try:
            await bot.download(doc,path)
            count=await asyncio.to_thread(import_excel,path,m.from_user.id)
            await m.answer(f"✅ فایل وارد شد. {count} ردیف دانش از Excel ثبت شد.\nاز این پس پاسخ‌ها و برنامه‌ها می‌توانند از این محتوا استفاده کنند.")
        except Exception as e: await m.answer(f"خطا در خواندن فایل: {type(e).__name__}: {str(e)[:300]}")
        finally:
            try: path.unlink(missing_ok=True)
            except: pass

    @dp.message(Command("pending"))
    async def pending_cmd(m):
        if not is_coach(m.from_user.id): return await m.answer("⛔ این فرمان فقط برای مربی مجاز است.")
        items=pending(m.from_user.id)
        if not items: return await m.answer("درخواست معلقی وجود ندارد.")
        for x in items[-10:]:
            await send_long_text(m, f"#{x['id']} ورزشکار {x['athlete_id']} | {x['kind']}\\n{x['content']}\\nبرای تأیید: /approve {x['id']}\\nبرای رد: /reject {x['id']} دلیل")

    @dp.message(Command("approve"))
    async def approve_cmd(m):
        if not is_coach(m.from_user.id): return await m.answer("⛔ این فرمان فقط برای مربی مجاز است.")
        try: pid=int(m.text.split()[1])
        except: return await m.answer("فرمت: /approve ID")
        x=get_program(pid)
        if not x or x["coach_id"]!=m.from_user.id: return await m.answer("درخواست پیدا نشد یا متعلق به شما نیست.")
        if not review(pid,"approved",coach_id=m.from_user.id):
            return await m.answer("این درخواست قبلاً بررسی شده یا دیگر در وضعیت انتظار نیست.")
        try:
            for chunk in split_telegram_text(f"✅ برنامه #{pid} توسط مربی تأیید شد:\\n{x['content']}"):
                await bot.send_message(x["athlete_id"], chunk)
        except Exception:
            pass
        await m.answer("برنامه تأیید شد.")

    @dp.message(Command("reject"))
    async def reject_cmd(m):
        if not is_coach(m.from_user.id): return await m.answer("⛔ این فرمان فقط برای مربی مجاز است.")
        parts=m.text.split(maxsplit=2)
        if len(parts)<2: return await m.answer("فرمت: /reject ID توضیح")
        try: pid=int(parts[1])
        except: return await m.answer("شناسه نامعتبر است.")
        x=get_program(pid)
        if not x or x["coach_id"]!=m.from_user.id: return await m.answer("درخواست پیدا نشد.")
        note=parts[2] if len(parts)>2 else "نیازمند اصلاح"
        if not review(pid,"rejected",note,coach_id=m.from_user.id):
            return await m.answer("این درخواست قبلاً بررسی شده یا دیگر در وضعیت انتظار نیست.")
        try: await bot.send_message(x["athlete_id"],f"برنامه #{pid} فعلاً تأیید نشد.\nتوضیح مربی: {note}")
        except: pass
        await m.answer("درخواست رد شد.")

    @dp.message(Command("assign"))
    async def assign_cmd(m: Message):
        if m.from_user.id not in ADMIN_IDS:
            return await m.answer("⛔ فقط مدیر می‌تواند مربی را به ورزشکار اختصاص دهد.")
        parts = (m.text or "").split()
        if len(parts) != 3:
            return await m.answer("فرمت: /assign ATHLETE_TELEGRAM_ID COACH_TELEGRAM_ID")
        try:
            assign_athlete(int(parts[1]), int(parts[2]))
        except (ValueError, TypeError) as exc:
            return await m.answer(f"اتصال انجام نشد: {str(exc)[:180]}")
        await m.answer(f"ورزشکار {parts[1]} به مربی {parts[2]} متصل شد.")

    @dp.message(Command("grant"))
    async def grant_cmd(m):
        if m.from_user.id not in ADMIN_IDS: return
        parts=m.text.split()
        if len(parts)<2: return await m.answer("فرمت: /grant TELEGRAM_ID [days]")
        try: uid=int(parts[1]); days=int(parts[2]) if len(parts)>2 else SUBSCRIPTION_DAYS
        except: return await m.answer("شناسه یا روز نامعتبر است.")
        grant(uid,days,SUBSCRIPTION_PLAN_LIMIT)
        await m.answer(f"دسترسی {days} روزه برای {uid} فعال شد.")

    @dp.message(Command("stats"))
    async def stats_cmd(m):
        if m.from_user.id not in ADMIN_IDS: return
        a,p,k=stats(); await m.answer(f"آمار\nورزشکاران: {a}\nبرنامه‌ها: {p}\nردیف دانش مربی: {k}")

    # Athlete photo record: explicit consent, temporary local processing, no raw image storage.
    @dp.message(F.text == "📸 پرونده تصویری")
    async def body_photo_start(m: Message, state: FSMContext):
        if not profile(m.from_user.id):
            return await m.answer("ابتدا پروفایل ورزشی را تکمیل کن.")
        await state.clear()
        await state.set_state(BodyPhotoForm.consent)
        await m.answer(
            "📸 پرونده تصویری بدن\n"
            "با ارسال عکس موافقت می‌کنی تصویر برای تحلیل غیرتشخیصی توسط سرویس هوش مصنوعی پردازش شود؟\n"
            "تصویر فقط موقتاً روی سرور دریافت می‌شود؛ فایل خام در پایگاه داده ذخیره نمی‌شود. "
            "شناسه فایل تلگرام و خلاصه تحلیل در پرونده ورزشی ثبت می‌شوند.\n"
            "برای ادامه دقیقاً بنویس: موافقم"
        )

    @dp.message(BodyPhotoForm.consent, F.text)
    async def body_photo_consent(m: Message, state: FSMContext):
        if (m.text or "").strip() != "موافقم":
            await state.clear()
            return await m.answer("فرایند ثبت عکس لغو شد. هر زمان خواستی دوباره شروع کن.")
        await state.set_state(BodyPhotoForm.view)
        await m.answer("زاویه عکس را مشخص کن: روبه‌رو / نیم‌رخ / پشت")

    @dp.message(BodyPhotoForm.view, F.text)
    async def body_photo_view(m: Message, state: FSMContext):
        raw = (m.text or "").strip()
        views = {"روبه‌رو": "front", "نیم‌رخ": "side", "پشت": "back"}
        if raw not in views:
            return await m.answer("یکی از این سه مورد را بفرست: روبه‌رو، نیم‌رخ یا پشت")
        await state.update_data(view_type=views[raw])
        await state.set_state(BodyPhotoForm.photo)
        await m.answer("حالا عکس واضح و با نور مناسب را به‌صورت Photo ارسال کن. عکس باید متعلق به خودت باشد.")

    @dp.message(BodyPhotoForm.photo, F.photo)
    async def body_photo_receive(m: Message, state: FSMContext):
        data = await state.get_data()
        await m.answer("عکس دریافت شد؛ در حال تحلیل غیرتشخیصی... ⏳")
        photo = m.photo[-1]
        try:
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "athlete_photo.jpg"
                telegram_file = await bot.get_file(photo.file_id)
                await bot.download_file(telegram_file.file_path, destination=path)
                image_bytes = path.read_bytes()
                analysis = await asyncio.to_thread(
                    analyze_body_photo, image_bytes, "image/jpeg", profile(m.from_user.id)
                )
            photo_id = save_body_photo(
                m.from_user.id, photo.file_id, data["view_type"], analysis, now()
            )
            await state.clear()
            await send_long_text(
                m,
                f"✅ عکس با شناسه پرونده {photo_id} ثبت شد.\n"
                "فایل خام پس از پایان پردازش از فضای موقت حذف شد.\n\n"
                f"خلاصه تحلیل غیرتشخیصی:\n{analysis}\n\n"
                "این خلاصه در تولید برنامه‌های بعدی در کنار پروفایل و اندازه‌های واقعی لحاظ می‌شود."
            )
        except Exception as exc:
            await state.clear()
            print(f"Body photo processing failed: {type(exc).__name__}: {exc}")
            await m.answer(
                "تحلیل عکس انجام نشد و تصویری در پرونده ثبت نشد. "
                "کمی بعد دوباره تلاش کن یا از زاویه و نور مناسب‌تری عکس بفرست."
            )

    @dp.message(BodyPhotoForm.photo)
    async def body_photo_expect_image(m: Message):
        await m.answer("لطفاً عکس را به‌صورت Photo ارسال کن؛ ارسال فایل یا متن در این مرحله پشتیبانی نمی‌شود.")

    @dp.message(F.text == "📏 اندازه‌های تکمیلی")
    async def extended_measure_start(m: Message, state: FSMContext):
        if not profile(m.from_user.id):
            return await m.answer("ابتدا پروفایل ورزشی را تکمیل کن.")
        await state.clear()
        await state.set_state(ExtendedMeasurementForm.hip)
        await m.answer("اندازه‌های تکمیلی بر حسب سانتی‌متر. دور باسن؟ عدد وارد کن یا «ندارم».")

    async def save_optional_extended(m, state, key, next_state, prompt, low, high):
        raw = (m.text or "").strip()
        if raw in ("-", "ندارم", "خالی"):
            value = None
        else:
            try:
                value = float(raw.replace(",", "."))
                if not low <= value <= high:
                    raise ValueError()
            except (ValueError, TypeError):
                return await m.answer(f"عدد معتبر بین {low} تا {high} یا «ندارم» وارد کن.")
        await state.update_data(**{key: value})
        await state.set_state(next_state)
        await m.answer(prompt)

    @dp.message(ExtendedMeasurementForm.hip)
    async def em1(m: Message, state: FSMContext):
        await save_optional_extended(m, state, "hip", ExtendedMeasurementForm.shoulder,
                                     "دور سرشانه؟ یا «ندارم»", 30, 200)
    @dp.message(ExtendedMeasurementForm.shoulder)
    async def em2(m: Message, state: FSMContext):
        await save_optional_extended(m, state, "shoulder", ExtendedMeasurementForm.forearm,
                                     "دور ساعد؟ یا «ندارم»", 10, 70)
    @dp.message(ExtendedMeasurementForm.forearm)
    async def em3(m: Message, state: FSMContext):
        await save_optional_extended(m, state, "forearm", ExtendedMeasurementForm.calf,
                                     "دور ساق؟ یا «ندارم»", 15, 100)
    @dp.message(ExtendedMeasurementForm.calf)
    async def em4(m: Message, state: FSMContext):
        await save_optional_extended(m, state, "calf", ExtendedMeasurementForm.neck,
                                     "دور گردن؟ یا «ندارم»", 15, 80)
    @dp.message(ExtendedMeasurementForm.neck)
    async def em5(m: Message, state: FSMContext):
        raw = (m.text or "").strip()
        if raw in ("-", "ندارم", "خالی"):
            value = None
        else:
            try:
                value = float(raw.replace(",", "."))
                if not 15 <= value <= 80:
                    raise ValueError()
            except (ValueError, TypeError):
                return await m.answer("عدد معتبر بین ۱۵ تا ۸۰ یا «ندارم» وارد کن.")
        data = await state.get_data()
        add_extended_measurements(
            m.from_user.id, hip=data.get("hip"), shoulder=data.get("shoulder"),
            forearm=data.get("forearm"), calf=data.get("calf"), neck=value
        )
        await state.clear()
        await m.answer("✅ اندازه‌های تکمیلی در پرونده ورزشی ثبت شدند.")

    @dp.message(F.text=="🎥 تحلیل فرم حرکت")
    async def video_help(m):
        await m.answer(
            "🎥 تحلیل ویدئویی FitCoach AI\n"
            "یک ویدئوی کوتاه ۱ تا ۲۰ ثانیه‌ای از اجرای یک حرکت بفرست.\n"
            "برای نتیجه بهتر: تمام بدن و مفاصل موردنظر داخل کادر باشند، دوربین ثابت باشد و نور کافی وجود داشته باشد.\n"
            "در این نسخه، نقاط کلیدی بدن روی ویدئو نمایش داده می‌شوند؛ این خروجی تشخیص پزشکی یا تأیید قطعی صحیح‌بودن حرکت نیست."
        )

    @dp.message(F.video)
    async def analyze_uploaded_video(m:Message):
        if not m.video:
            return
        video = m.video
        if video.duration and video.duration > 20:
            return await m.answer("مدت ویدئو باید حداکثر ۲۰ ثانیه باشد.")
        if video.file_size and video.file_size > 18 * 1024 * 1024:
            return await m.answer("حجم ویدئو باید کمتر از ۱۸ مگابایت باشد.")
        if not profile(m.from_user.id):
            return await m.answer("ابتدا پروفایل ورزشکاری خود را تکمیل کن.")
        await m.answer("ویدئو دریافت شد. در حال استخراج نقاط کلیدی بدن و ساخت نسخه تصویری... ⏳")
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "input.mp4"
            out = Path(td) / "fitcoach_pose_overlay.mp4"
            try:
                file = await bot.get_file(video.file_id)
                await bot.download_file(file.file_path, destination=inp)
                async with video_semaphore:
                    metrics = await asyncio.to_thread(analyze_video, str(inp), str(out))
                caption = (
                    "✅ نسخه تصویری تحلیل آماده شد.\n"
                    f"مدت: {metrics['duration']} ثانیه\n"
                    f"فریم‌های پردازش‌شده: {metrics['frames']}\n"
                    f"نسبت فریم‌های دارای تشخیص بدن: {metrics['pose_detection_ratio']:.0%}\n\n"
                    "خطوط و نقاط روی ویدئو فقط تخمین وضعیت بدن هستند؛ "
                    "این نسخه هنوز خطای تکنیکی حرکت یا ایمنی پزشکی را تأیید نمی‌کند."
                )
                await m.answer_video(FSInputFile(out), caption=caption)
            except Exception as exc:
                msg = str(exc)
                if "نصب نیستند" in msg:
                    await m.answer("قابلیت تحلیل ویدئو روی سرور فعال نشده است. بسته‌های requirements-video.txt باید نصب شوند.")
                else:
                    await m.answer("پردازش ویدئو انجام نشد. ویدئوی کوتاه‌تر، واضح‌تر و با فرمت MP4 بفرست.\nجزئیات: " + msg[:500])

    @dp.message(F.photo)
    async def photo(m):
        await m.answer("برای ثبت عکس در پرونده، ابتدا دکمه «📸 پرونده تصویری» را بزن و رضایت و زاویه عکس را مشخص کن.")

    @dp.message(F.text=="ℹ️ راهنما")
    async def help_msg(m):
        if is_coach(m.from_user.id):
            await m.answer("راهنما: برای مدیریت از پنل مربی و برای تمرین شخصی از امکانات ورزشی من استفاده کن.\nلغو عملیات: /cancel", reply_markup=coach_kb())
        else:
            await m.answer("راهنما: پروفایل را تکمیل کن؛ سپس از برنامه تمرین، تغذیه، ثبت تمرین، غذا، اندازه‌گیری، چک‌این و گزارش استفاده کن.\nلغو عملیات: /cancel\nبرنامه‌های قبلی پس از پایان اشتراک نیز قابل مشاهده‌اند.", reply_markup=kb())

    @dp.message(F.text)
    async def active_chat_fallback(m: Message):
        # Recover an active chat after restart when in-memory FSM state is lost.
        if is_conversation_active(m.from_user.id):
            await process_coach_message(m)
            return
        await m.answer("برای شروع /start را بزن یا از منوی پایین استفاده کن.")

    @dp.message()
    async def fallback(m): await m.answer("برای شروع /start را بزن یا از منوی پایین استفاده کن.")

    try: await dp.start_polling(bot)
    finally: await bot.session.close()
