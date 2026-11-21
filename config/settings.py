import os
from pathlib import Path
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings:
    # إعدادات المسارات
    BASE_DIR: Path = BASE_DIR
    DATABASE_PATH: Path = BASE_DIR / os.getenv("DATABASE_PATH", "safaqat.db")
    MEDIA_TEMP_DIR: Path = BASE_DIR / os.getenv("MEDIA_TEMP_DIR", "temp_media")

    # مفاتيح الربط البرمجي
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_BROADCAST_CHAT_ID: str = os.getenv("TELEGRAM_BROADCAST_CHAT_ID", "")
    ADMIN_TELEGRAM_ID: str = os.getenv("ADMIN_TELEGRAM_ID", "6854086264")

    # إعدادات فترات العمل الآلي
    MONITOR_INTERVAL_MINUTES: int = int(os.getenv("MONITOR_INTERVAL_MINUTES", "15"))
    DISCOVERY_INTERVAL_HOURS: int = int(os.getenv("DISCOVERY_INTERVAL_HOURS", "6"))

    # إعدادات وضع السكون الليلي (إيقاف الفحص ليلاً لحماية السيرفر والمشتركين)
    NIGHT_MODE_ENABLED: bool = os.getenv("NIGHT_MODE_ENABLED", "true").lower() in ("true", "1", "yes")
    NIGHT_START_HOUR: int = int(os.getenv("NIGHT_START_HOUR", "0"))  # 12:00 منتصف الليل بتوقيت غزة
    NIGHT_END_HOUR: int = int(os.getenv("NIGHT_END_HOUR", "7"))      # 07:00 صباحاً بتوقيت غزة

    # نماذج الذكاء الاصطناعي
    GEMINI_MODEL: str = "gemini-flash-lite-latest"

    # الكلمات المفتاحية لرصد صفقات غزة
    GAZA_KEYWORDS = [
        "سعر حرق", "عرض خاص", "وصل حديثاً", "تخفيضات", "جملة", 
        "بسعر التكلفة", "كمية محدودة", "طاقة شمسية", "إنفرتر", 
        "بطارية جل", "لوح طاقة", "دير البلح", "خانيونس", "رفح", 
        "الوسطى", "غزة", "شاحن", "مولد", "سكر", "طحين", "زيت"
    ]

settings = Settings()

# إنشاء المجلدات الضرورية تلقائياً
settings.MEDIA_TEMP_DIR.mkdir(parents=True, exist_ok=True)
