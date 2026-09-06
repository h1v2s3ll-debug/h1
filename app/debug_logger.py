"""
أداة تشخيص مؤقتة لمعرفة سبب النافذة الصغيرة اللي تفتح وتختفي بسرعة.

الفكرة: بدل ما نحاول نمسك النافذة يدويًا بعيوننا (صعب جدًا لأنها سريعة)،
خلي البرنامج نفسه يسجّل تلقائيًا بملف نصي أي نافذة جديدة تنفتح، وأي خطأ
برمجي يصير، لحظة حدوثه بالضبط - حتى لو اختفت النافذة بجزء من الثانية،
السطر يكون قد انكتب بالملف قبل ما تختفي.

الملف الناتج: ~/.olivia_pharmacy/app_debug.log

بعد ما نلقى السبب ونصلحه، نقدر نشيل استدعاء setup_debug_logging() من
main.py ونحذف هذا الملف بالكامل - هذا مو جزء دائم من البرنامج.
"""
import os
import sys
import datetime
import traceback

from PySide6.QtCore import QObject, QEvent, qInstallMessageHandler


def _log_path():
    log_dir = os.path.expanduser("~/.olivia_pharmacy")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "app_debug.log")


def _write(line: str):
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # حتى لو فشل التسجيل نفسه، ما نبي نكسر البرنامج بسببه
        pass


class _TopLevelWindowLogger(QObject):
    """يسجّل أي widget مستقل (بدون أب) لحظة ما يظهر على الشاشة.

    هذا بالضبط النوع من النوافذ اللي وصفها المستخدم - "تفتح وتختفي بسرعة".
    أي QDialog/QWidget/QMessageBox يُبنى بدون تمرير parent له، ينفتح كنافذة
    مستقلة في نظام التشغيل - وهذا اللي نحاول نصطاده.
    """

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.Show:
                is_window = bool(getattr(obj, "isWindow", lambda: False)())
                has_parent = getattr(obj, "parent", lambda: None)() is not None
                if is_window and not has_parent:
                    title = ""
                    try:
                        title = obj.windowTitle()
                    except Exception:
                        pass
                    geo = ""
                    try:
                        g = obj.geometry()
                        geo = f"{g.width()}x{g.height()}+{g.x()}+{g.y()}"
                    except Exception:
                        pass
                    _write(
                        f"[{datetime.datetime.now()}] نافذة مستقلة ظهرت | "
                        f"النوع: {type(obj).__name__} | "
                        f"العنوان: {title!r} | "
                        f"الاسم: {obj.objectName()!r} | "
                        f"الحجم/الموقع: {geo}\n"
                        f"    -- تتبّع مكان الإنشاء (Stack) --\n"
                        + "".join(
                            "    " + line
                            for line in traceback.format_stack()[:-1]
                        )
                        + "\n"
                    )
        except Exception:
            pass
        return False  # لا نوقف أي حدث، بس نراقب ونسجل


def _qt_message_handler(msg_type, context, message):
    _write(f"[{datetime.datetime.now()}] رسالة داخلية من Qt: {message}\n")


def _exception_hook(exc_type, exc_value, exc_tb):
    _write(
        f"[{datetime.datetime.now()}] استثناء برمجي غير متوقع:\n"
        + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        + "\n"
    )
    # نطبعه بالكونسول كمان زي العادة، حتى ما نغيّر السلوك المعتاد
    sys.__excepthook__(exc_type, exc_value, exc_tb)


# نحتفظ بمرجع global للـ event filter، وإلا بايثون يحذفه من الذاكرة
# فورًا (garbage collection) ويوقف عن الشغل بصمت بدون أي رسالة خطأ.
_window_logger_instance = None


def setup_debug_logging(app):
    """استدعيها مرة وحدة بعد إنشاء QApplication مباشرة."""
    global _window_logger_instance
    _write(f"\n[{datetime.datetime.now()}] ==== بدء جلسة تشغيل جديدة ====\n")

    sys.excepthook = _exception_hook
    qInstallMessageHandler(_qt_message_handler)

    _window_logger_instance = _TopLevelWindowLogger()
    app.installEventFilter(_window_logger_instance)
