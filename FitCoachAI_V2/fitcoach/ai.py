from groq import Groq
from fitcoach.config import GROQ_API_KEY,GROQ_MODEL
from fitcoach.db import search_knowledge

SYSTEM = """
تو FitCoach AI، دستیار تمرین و تغذیه زیر نظر مربی هستی.
پاسخ فارسی، دقیق و ساختاریافته بده. دانش بازیابی‌شده مربی را به‌عنوان روش و ترجیحات او لحاظ کن؛
اما اگر با اصول ایمنی یا شواهد معتبر تعارض داشت، خطر را صریح بگو و از اجرای خطرناک خودداری کن.
تشخیص پزشکی، درمان، تجویز دارو یا تغییر دوز دارو ممنوع است.
در آسیب/بیماری/دارو/درد یا علائم هشدار، برنامه محافظه‌کارانه بده و در صورت نیاز ارجاع به پزشک/فیزیوتراپیست بده.
هیچ حرکت یا توصیه‌ای را کاملاً بی‌خطر تضمین نکن. برای داده‌های ناقص سؤال روشن‌کننده بپرس.
برنامه تمرین باید شامل روز، هدف، حرکت، ست، تکرار، استراحت، RIR و نکته اجرا باشد.
تغذیه عمومی و غیر افراطی باشد؛ کالری بسیار پایین و کاهش وزن سریع پیشنهاد نده.
"""
def ask(profile,question,coach_id):
    if not GROQ_API_KEY:
        goal = str(profile.get("goal", "تناسب اندام"))
        days = int(profile.get("days") or 3)
        limitations = str(profile.get("limitations") or "").strip().lower()
        medication = str(profile.get("medication") or "").strip().lower()
        has_flags = any(x in limitations for x in ("آسیب", "درد", "بیماری", "محدود", "injur", "pain", "medical")) or medication not in ("", "خیر", "ندارد", "no", "none")
        if has_flags:
            safe_text = ("به‌دلیل ثبت محدودیت یا دارو، این نسخه رایگان حرکت مشخصی تجویز نمی‌کند. "
                         "ابتدا محدودیت را با پزشک یا فیزیوتراپیست روشن کن و برنامه را با متخصص واجد صلاحیت بررسی کن.")
        else:
            safe_text = ("الگوی شروع عمومی (فقط در صورت نداشتن درد یا منع پزشکی و با اجرای صحیح):\n"
                         "روز A: اسکوات یا جایگزین متناسب ۲-۳×۸-۱۲، پرس سینه یا شنا ۲-۳×۸-۱۲، زیربغل ۲-۳×۸-۱۲، پلانک ۲ ست.\n"
                         "روز B: هیپ‌هینج سبک ۲×۸-۱۰، پرس سرشانه ۲×۸-۱۲، لت/کش ۲-۳×۸-۱۲، لانج کنترل‌شده ۲×۸ هر پا.\n"
                         "روز C: تکرار A با شدت قابل‌کنترل یا فعالیت سبک و تمرین تکنیک. بین جلسات سخت استراحت کافی داشته باش.\n"
                         "شدت را حدود ۲-۴ تکرار در ذخیره نگه دار؛ با درد تیز یا غیرعادی توقف کن. این الگو نسخه شخصی‌سازی‌شده یا تأیید پزشکی نیست.")
        return ("🤖 حالت رایگان بدون API فعال است\n\n"
                f"هدف ثبت‌شده: {goal} | روز تمرین: {days}\n\n{safe_text}\n\n"
                "این پاسخ با قواعد داخلی و بدون مدل زبانی تولید شده است؛ برای پاسخ هوشمندتر می‌توان از سهمیه رایگان سرویس AI در صورت دسترسی استفاده کرد.")
    knowledge=search_knowledge(coach_id,question,7)
    p="\n".join(f"{k}: {v}" for k,v in profile.items() if v not in (None,""))
    ktext="\n".join(f"- {x}" for x in knowledge) or "مورد مرتبطی از فایل‌های مربی پیدا نشد."
    client=Groq(api_key=GROQ_API_KEY)
    try:
        r=client.chat.completions.create(
          model=GROQ_MODEL,temperature=0.35,max_tokens=1800,
          messages=[
            {"role":"system","content":SYSTEM},
            {"role":"user","content":f"پروفایل ورزشکار:\n{p}\n\nدانش مرتبط مربی:\n{ktext}\n\nدرخواست:\n{question}"}
          ])
        return r.choices[0].message.content or "پاسخی دریافت نشد."
    except Exception as e:
        return f"خطا در سرویس AI ({type(e).__name__}). کلید API، مدل و Runtime Logs بررسی شوند."
