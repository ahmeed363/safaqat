import os
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
import yt_dlp
from config.settings import settings

class MediaProcessor:
    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or settings.MEDIA_TEMP_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download_audio_from_post(self, post_url: str) -> Optional[str]:
        """
        تنزيل الصوت فقط من فيديو فيسبوك أو ريلز بصيغة خفيفة وسريعة (mp3/m4a)
        لتوفير استهلاك البيانات وتسريع إرساله لنموذج الذكاء الاصطناعي.
        """
        file_id = str(uuid.uuid4())[:8]
        output_template = str(self.output_dir / f"audio_{file_id}.%(ext)s")

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
                'preferredquality': '128',
            }],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(post_url, download=True)
                downloaded_file = str(self.output_dir / f"audio_{file_id}.m4a")
                if os.path.exists(downloaded_file):
                    return downloaded_file
                # في حال حفظه بامتداد آخر
                for f in self.output_dir.glob(f"audio_{file_id}.*"):
                    return str(f)
        except Exception as e:
            # إذا تعذر التحميل بالصوت فقط، حاول تنزيل الفيديو كاملاً بحجم صغير
            return self.download_video_fallback(post_url, file_id)
        
        return None

    def download_video_fallback(self, post_url: str, file_id: str) -> Optional[str]:
        """تنزيل الفيديو بجودة منخفضة كخطة بديلة"""
        output_template = str(self.output_dir / f"video_{file_id}.%(ext)s")
        ydl_opts = {
            'format': 'worst[ext=mp4]/worst', # أصغر حجم ممكن لتوفير السرعة
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(post_url, download=True)
                for f in self.output_dir.glob(f"video_{file_id}.*"):
                    return str(f)
        except Exception:
            return None
        return None

    def cleanup_file(self, file_path: str):
        """حذف الملف المؤقت بعد انتهاء التحليل للحفاظ على مساحة القرص"""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

media_processor = MediaProcessor()
