"""
تحميل خط Cairo العربي وتسجيله كخط افتراضي للتطبيق كامل (H1 Visual
Foundation Upgrade).

نحمّل ملفات الأوزان الثابتة (Regular/Medium/SemiBold/Bold/ExtraBold/Black/
Light/ExtraLight) بدل ملف الخط المتغيّر (Variable Font) لأن Qt يتعامل مع
كل وزن كخط منفصل مسجّل تحت نفس اسم العائلة "Cairo" - وهذا يخلي font-weight
بستايل الواجهة (QSS) يطابق فعليًا الوزن الصحيح المرسوم (600/700/800...)
بدل ما Qt يحاول يصطنع Bold برمجيًا من نسخة وحدة بس.
"""
import os
import sys

from PySide6.QtGui import QFontDatabase

# ⚠️ نفس ملاحظة app/ui/icons.py بالضبط - assets/fonts تضل مرفقة (datas)
# جوا الـexe (خط Cairo ثابت، ما يستفيد من التحديث الجزئي)، بعكس app/ اللي
# صارت ملفات لوحدها جنب الـexe بعد فصلها للتحديث الجزئي - فلازم مسار
# منفصل حسب وضعية التشغيل (frozen أو لا)، نفس أسلوب app/main.py.
if getattr(sys, "frozen", False):
    _ASSETS_BASE_DIR = sys._MEIPASS
else:
    _ASSETS_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_FONTS_DIR = os.path.join(_ASSETS_BASE_DIR, "assets", "fonts")

# الترتيب المطلوب لاسم عائلة الخط الافتراضي: Cairo أولاً (نفس تفضيل
# المستخدم بمهمة الرفع الأخيرة)، وبعده IBM Plex Sans Arabic و Noto Sans
# Arabic كاحتياط لو Cairo ما انحمّل لأي سبب.
PREFERRED_FAMILIES = ["Cairo", "IBM Plex Sans Arabic", "Noto Sans Arabic"]

_loaded_family = None
_loaded = False


def load_bundled_fonts():
    """يسجّل كل ملفات .ttf/.otf الثابتة (Static) الموجودة بـ assets/fonts/
    مع Qt، ويرجّع اسم العائلة المفضّلة اللي انحمّلت فعليًا (أو None لو
    المجلد فاضي/ماكو ملفات). آمن الاستدعاء أكثر من مرة."""
    global _loaded_family, _loaded
    if _loaded:
        return _loaded_family
    _loaded = True

    if not os.path.isdir(_FONTS_DIR):
        return None

    loaded_families = set()
    for fname in sorted(os.listdir(_FONTS_DIR)):
        if not fname.lower().endswith((".ttf", ".otf")):
            continue
        if "variablefont" in fname.lower():
            # نتجاهل ملف الخط المتغيّر ونعتمد الأوزان الثابتة بس (راجع
            # شرح السبب بأعلى الملف).
            continue
        font_id = QFontDatabase.addApplicationFont(os.path.join(_FONTS_DIR, fname))
        if font_id == -1:
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            loaded_families.add(family)

    if not loaded_families:
        return None

    for preferred in PREFERRED_FAMILIES:
        for family in loaded_families:
            if preferred.lower() in family.lower():
                _loaded_family = family
                return _loaded_family

    _loaded_family = sorted(loaded_families)[0]
    return _loaded_family
