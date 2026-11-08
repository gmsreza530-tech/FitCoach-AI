import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY","").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL","openai/gpt-oss-120b").strip()
COACH_IDS = {int(x) for x in os.getenv("COACH_IDS","").split(",") if x.strip().isdigit()}
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip().isdigit()}
DATABASE_PATH = Path(os.getenv("DATABASE_PATH","data/fitcoach.db"))
APPROVAL_MODE = os.getenv("APPROVAL_MODE","auto").lower()
SUBSCRIPTION_DAYS = int(os.getenv("SUBSCRIPTION_DAYS","30"))
SUBSCRIPTION_PLAN_LIMIT = int(os.getenv("SUBSCRIPTION_PLAN_LIMIT","5"))
UPLOAD_DIR = Path("uploads")
MAX_EXCEL_BYTES = 8 * 1024 * 1024

FREE_MODE = os.getenv("FREE_MODE", "true").lower() == "true"
