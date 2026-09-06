"""
مكتبة أيقونات موحّدة (H1 Design System) - مبنية على خط Lucide الحقيقي
المرفق بالمشروع (assets/icons/lucide.ttf)، بدل الأيقونات المرسومة يدويًا
بـ QPainter بالإصدار السابق.

كيف تشتغل: كل أيقونة بخط Lucide هي حرف Unicode برمز من نطاق Private Use
Area (0xE000+). نحمّل الخط مرة وحدة مع Qt، وبعدها أي أيقونة نحتاجها نرسمها
عبر QPainter.drawText بنفس الخط وبلون/حجم نمرره - تمامًا نفس أسلوب أي مكتبة
أيقونات احترافية (Font Awesome، Material Symbols...).

رموز الأيقونات أدناه مو مخمّنة - انسحبت فعليًا من جدول cmap بملف
lucide.ttf المرفق (عبر fontTools) للتأكد إن كل حرف يطابق الأيقونة الصحيحة
فعلاً قبل ما تنحط بالكود.

الاستخدام (نفس واجهة الإصدار السابق تمامًا - ولا سطر عند المستدعي يتغيّر):
    from app.ui.icons import icon
    btn.setIcon(icon("cart", color=COLOR_TEXT_PRIMARY, size=18))
"""
import os
import sys

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# ⚠️ لازم يكون متوافق مع وضعيتين مختلفتين تمامًا لمكان assets/icons/:
# 1) شغّال كسكربت بايثون عادي أو exe بعد فصل app/ (Partial Update) -> نفس
#    مجلد المشروع/التثبيت، نطلعله بـ3 مستويات من مكان هذا الملف (app/ui/ ->
#    app/ -> جذر المشروع).
# 2) شغّال كملف exe مبني بـ PyInstaller (--onefile) -> assets/icons تضل
#    مرفقة (datas) جوا الـexe نفسه دائمًا (خط lucide.ttf ثابت ونادر يتغيّر،
#    ما يستفيد من التحديث الجزئي)، وتتفك مؤقتًا بمجلد sys._MEIPASS وقت
#    التشغيل - بعكس app/ اللي صارت ملفات لوحدها جنب الـexe (مو مرفقة
#    بعدها)، فلازم مسار منفصل لكل وحدة، نفس أسلوب app/main.py بالضبط.
if getattr(sys, "frozen", False):
    _ASSETS_BASE_DIR = sys._MEIPASS
else:
    _ASSETS_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_FONT_PATH = os.path.join(_ASSETS_BASE_DIR, "assets", "icons", "lucide.ttf")

# اسم عائلة الخط بعد ما ينحمّل مع Qt - يتحدد فعليًا أول استخدام (_ensure_font_loaded)
_font_family = None
_load_attempted = False

# name دلالي مستخدم بالكود -> كود Unicode الحرف المطابق بخط Lucide (من cmap
# الفعلي لملف lucide.ttf المرفق - كل قيمة هنا مُتحقق منها مسبقًا).
_GLYPHS = {
    "search": 0xE151, "barcode": 0xE533, "cart": 0xE15C, "trash": 0xE18E,
    "plus": 0xE13D, "minus": 0xE11C, "check": 0xE06C, "cash": 0xE052,
    "credit_card": 0xE0AA, "wallet": 0xE204, "undo": 0xE2A1, "warning": 0xE193,
    "box": 0xE129, "receipt": 0xE3D3, "swap": 0xE24A, "chevron_down": 0xE06D,
    "chart": 0xE2A3, "clock": 0xE256, "user": 0xE19F, "logout": 0xE10E,
    "bell": 0xE059, "edit": 0xE1F9, "save": 0xE14D, "trend_down": 0xE190,
    "money": 0xE052, "clipboard": 0xE086, "camera": 0xE064, "phone": 0xE133,
    "recycle": 0xE2E9, "folder": 0xE0D7, "close": 0xE1B2, "refresh": 0xE145,
    "info": 0xE0F9, "dot": 0xE44F, "printer": 0xE141, "chat": 0xE116,
    "smartphone": 0xE163, "settings": 0xE154, "calendar": 0xE063, "list": 0xE106,
    "dashboard": 0xE1C1, "database": 0xE0AD, "backup": 0xE4E5, "building": 0xE290,
    "users": 0xE1A4, "truck": 0xE194, "pill": 0xE3BD, "stethoscope": 0xE2F1,
    "file_text": 0xE0CC, "store": 0xE3E4, "shield": 0xE158, "key": 0xE0FD,
    "lock": 0xE10B, "eye": 0xE0BA, "eye_off": 0xE0BB, "download": 0xE0B2,
    "upload": 0xE19E, "copy": 0xE09E, "share": 0xE155, "home": 0xE0F5,
    "circle_x": 0xE084, "loader": 0xE109,
    "calculator": 0xE1BC, "brain": 0xE3C6, "sparkles": 0xE412,
    "layout_dashboard": 0xE1C1, "coins": 0xE097,
}


def _ensure_font_loaded():
    """يحمّل lucide.ttf مع Qt مرة وحدة بس (أول استدعاء). آمن الاستدعاء
    المتكرر - النتيجة تتخزّن بمتغيّر الموديول."""
    global _font_family, _load_attempted
    if _load_attempted:
        return _font_family
    _load_attempted = True
    if QApplication.instance() is None or not os.path.isfile(_FONT_PATH):
        return None
    font_id = QFontDatabase.addApplicationFont(_FONT_PATH)
    if font_id == -1:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        _font_family = families[0]
    return _font_family


def _painter(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    return pm, p


_cache = {}


def icon(name, color="#111827", size=20, stroke=1.8):
    """يرجع QIcon لأيقونة موحّدة من خط Lucide الحقيقي. النتيجة تُخزَّن
    مؤقتًا (cache) لأن نفس الأيقونة تتكرر بعشرات الأزرار بكل شاشة.
    stroke: موجودة بس للتوافق مع الاستدعاءات القديمة - سماكة الخط بخط
    Lucide ثابتة أصلاً بتصميم الخط نفسه."""
    if QApplication.instance() is None:
        return QIcon()
    key = (name, color, size)
    if key in _cache:
        return _cache[key]
    pm = pixmap(name, color=color, size=size)
    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def pixmap(name, color="#111827", size=20, stroke=1.8):
    """نفس icon() بس يرجع QPixmap مباشرة - مفيد لمّا نحتاج نحطها بـ QLabel
    (مثلاً أيقونة داخل صندوق البحث) بدل زر."""
    pm, p = _painter(size)
    codepoint = _GLYPHS.get(name)
    family = _ensure_font_loaded()
    if codepoint is not None and family:
        font = QFont(family)
        # نطاق رسم الحرف أصغر شوي من حجم البكسل الكامل حتى ما يلتصق بحواف
        # الأيقونة - نفس هامش الأمان اللي كانت تستخدمه الأيقونات المرسومة يدويًا.
        font.setPixelSize(int(size * 0.86))
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, chr(codepoint))
    p.end()
    return pm
