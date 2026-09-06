"""
نقطة انطلاق تطبيق H1 لسطح المكتب.
شغّل الملف هذا بالأمر: python -m app.main   (من مجلد olivia_system الرئيسي)
"""
import sys
import os

# ---- حماية عامة: sys.stdout / sys.stderr ممكن تكون None ----
# لازم هذا يكون أول شي يصير بالملف، قبل أي استيراد ثاني - لأن مكتبات
# كثيرة (uvicorn، وحتى print() العادية بالكود) تفترض وجود stdout/stderr
# صالحين. لما البرنامج يشتغل كـ exe مبني بوضعية "بدون كونسول" (اللي
# نستخدمها بالبناء النهائي عشان ما تفتح شباك أسود خلف البرنامج)، ويندوز
# ما يعطي البرنامج أي مخرج قياسي إطلاقًا، فتصير sys.stdout و sys.stderr
# قيمتها None حرفيًا (مو فاضية) - وأي print() أو مكتبة تحاول تكتب أو حتى
# تسأل خاصية زي .isatty() عليها تنهار بخطأ AttributeError فورًا. هذا بالضبط
# سبب مشكلة "سيرفر الموبايل يفشل بالتشغيل بصمت". الحل: لو لقيناها None،
# نعوّضها بمخرج وهمي (os.devnull) ما يسوي شي بس موجود وما ينهار.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import threading
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from app.db.database import init_db
from app.db.seed_data import seed
from app.ui.login_window import LoginWindow, ensure_default_admin
from app.ui.main_window import MainWindow
from app.ui.theme import stylesheet_for
from app.ui.fonts import load_bundled_fonts
from app.licensing.license_manager import check_license


def main():
    # ---- ضبط سياسة مقياس DPI قبل إنشاء QApplication ----
    # لازم تنضبط قبل إنشاء QApplication مباشرة، وإلا ما تأثر أبدًا.
    # PassThrough تخلي Qt يتعامل مع نسب التكبير الكسرية (125%، 150%، 175%)
    # بدقة بدل ما يقرّبها لأقرب رقم صحيح، وهذا يقلل فروقات الحجم الغريبة
    # بين شاشة وأخرى (كانت أحد أسباب تضخم الحد الأدنى لارتفاع النافذة).
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)

    # ---- منع إغلاق البرنامج كامل بالغلط عند إغلاق أي نافذة فرعية ----
    # افتراضيًا (quitOnLastWindowClosed=True)، Qt يغلق التطبيق بالكامل تلقائيًا
    # أي لحظة يوصل فيها عدد "النوافذ المستقلة" (بدون أب - parent) المرئية
    # للصفر - حتى لو مؤقتًا وللحظة وحدة أثناء تبديل نافذة بثانية. وهذا بالضبط
    # كان يصير هنا: LoginWindow() تحت تنبني بدون أب (parent) أصلًا، فهي
    # "نافذة مستقلة" من منظور Qt - ولما تنسكر بعد تسجيل الدخول الناجح (وقبل
    # ما MainWindow تنبني وتنعرض)، أو حتى بأي لحظة ثانية بمنتصف تشغيل
    # البرنامج تتغيّر فيها حالة الظهور للحظة، كان يقدر يصير إغلاق كامل غير
    # متوقع للبرنامج (هذا سبب مشكلة "فتح نافذة فاتورة أو غيرها وسدها يسد كل
    # الواجهات"). الحل القياسي والآمن: نعطّل هذا السلوك التلقائي هنا، ونتحكم
    # بإغلاق البرنامج يدويًا وبشكل صريح بس (MainWindow.closeEvent تحت).
    app.setQuitOnLastWindowClosed(False)

    # ---- أيقونة البرنامج (شريط المهام + كل النوافذ) ----
    # نحتاج نكتشف المسار الصحيح لملف app_icon.ico بحالتين مختلفتين:
    # 1) شغّال كسكربت بايثون عادي (python -m app.main) -> الأيقونة بجذر
    #    المشروع، يعني مجلد فوق app/ مباشرة.
    # 2) شغّال كملف exe مبني بـ PyInstaller (وضعية --onefile) -> كل
    #    الملفات المرفقة (datas) تتفك مؤقتًا بمجلد sys._MEIPASS وقت
    #    التشغيل، فلازم نقرأ منه بدل مسار الكود العادي.
    if getattr(sys, "frozen", False):
        _base_dir = sys._MEIPASS
    else:
        _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _icon_path = os.path.join(_base_dir, "app_icon.ico")
    if os.path.isfile(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    # ---- تسجيل تشخيصي مؤقت لمعرفة سبب النافذة السريعة اللي تختفي ----
    # يسجّل تلقائيًا أي نافذة مستقلة تنفتح (حتى لو اختفت بجزء من الثانية)
    # بملف: ~/.olivia_pharmacy/app_debug.log - بعد ما نلقى ونصلّح السبب،
    # نشيل هذا السطر والملف debug_logger.py بالكامل، مو جزء دائم بالبرنامج.
    from app.debug_logger import setup_debug_logging
    setup_debug_logging(app)

    app.setLayoutDirection(Qt.RightToLeft)
    # يحمّل خط Cairo المرفق فعليًا بـ assets/fonts/ ويسجّله مع Qt قبل ما
    # نطبّق الستايل - يصير هو الخط الافتراضي لكل نافذة بالتطبيق تلقائيًا
    # بدون أي إعداد يدوي إضافي (H1 Visual Foundation Upgrade).
    bundled_font_family = load_bundled_fonts()
    app.setStyleSheet(stylesheet_for(bundled_font_family))

    if not check_license():
        sys.exit(0)

    init_db()
    seed()
    ensure_default_admin()

    # سيرفر محلي مصغّر لصفحة "إضافة/تحديث الأدوية من الموبايل" - يشتغل بالخلفية
    # طول ما البرنامج مفتوح. لو صار خطأ بتشغيله ما نوكف البرنامج، بس نسجل
    # الخطأ بملف لوق حتى نقدر نعرف السبب لو ما اشتغل عند المستخدم.
    try:
        from app.mobile_server import start_server
        threading.Thread(target=start_server, daemon=True).start()
    except Exception:
        import traceback
        log_dir = os.path.expanduser("~/.olivia_pharmacy")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "mobile_server_error.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())

    login = LoginWindow()
    if login.exec() == LoginWindow.Accepted:
        window = MainWindow(login.authenticated_user)
        window.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
