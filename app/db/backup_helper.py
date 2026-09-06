"""
مساعد النسخ الاحتياطي - نظامين مكمّلين لبعض:

1. **نسخة لحظية (فورية)**: ملف واحد يتحدث تلقائيًا فور أي عملية تعدّل
   قاعدة البيانات (بيع، إرجاع، إضافة دواء، تعديل مخزون، أي شي) - عبر
   SQLAlchemy session event (after_commit)، بدون مؤقت دوري وبدون تراكم
   نسخ كثيرة مزعجة. هذي الحماية الأساسية الآن.

2. **نسخ مؤرشفة يدوية**: لقطات بطابع زمني تنعمل بس لما المستخدم يضغط
   "خذ نسخة الآن" بنفسه، أو عند إغلاق البرنامج - يحتفظ بآخر 10 لقطات
   ويسمح بالاستعادة من أي وحدة منها تحديدًا (مفيدة لو تحتاج ترجع لنقطة
   زمنية معينة، مو بس آخر حالة).

ملاحظة إصلاح مهمة (تحديث): كان فيه نسخ تلقائي دوري كل 30 دقيقة بمؤقت -
المستخدم اعتبره "كثير ومزعج" (يراكم نسخ كثيرة بدون داعي). الحل: النسخ
التلقائي صار "لحظي" فعليًا (فور كل عملية، مو كل 30 دقيقة) لكن **بملف
واحد بس يتحدث باستمرار** (مو ملف جديد كل مرة) - حماية أقوى (لا تخسر أي
عملية أبدًا، حتى لو صار عطل بعد ثانية من آخر عملية) بدون تراكم ملفات.
"""
import os
import re
import shutil
import glob
import sqlite3
from datetime import datetime
from sqlalchemy import text

from .database import DB_PATH
from .settings_helper import get_setting, set_setting

BACKUP_PREFIX = "H1_backup_"
BACKUP_SUFFIX = ".db"
MAX_BACKUPS = 10  # نحتفظ بآخر 10 لقطات يدوية بس، ونحذف الأقدم تلقائيًا
INSTANT_BACKUP_FILENAME = "H1_backup_instant.db"
INSTANT_TIMESTAMP_FILENAME = "H1_backup_instant.timestamp"
PERIODIC_BACKUP_FILENAME = "H1_backup_periodic.db"  # نسخة دورية (كل 30 دقيقة + عند الإغلاق) - ملف واحد ثابت يتحدث، مو نسخة جديدة كل مرة
SETTING_FOLDER_KEY = "backup_folder"
SETTING_LAST_BACKUP_KEY = "last_backup_at"
SETTING_AUTO_BACKUP_KEY = "auto_backup_enabled"


def get_backup_folder(session):
    return get_setting(session, SETTING_FOLDER_KEY, "")


def set_backup_folder(session, folder_path):
    set_setting(session, SETTING_FOLDER_KEY, folder_path or "")


def get_last_backup_at(session):
    """يقرأ وقت آخر نسخة - يفضّل الوقت اللحظي (أدق وأحدث) لو موجود،
    وإلا يرجع لوقت آخر لقطة يدوية."""
    folder = get_backup_folder(session)
    if folder:
        ts_path = os.path.join(folder, INSTANT_TIMESTAMP_FILENAME)
        try:
            with open(ts_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return get_setting(session, SETTING_LAST_BACKUP_KEY, "")


def is_auto_backup_enabled(session):
    return get_setting(session, SETTING_AUTO_BACKUP_KEY, "1") != "0"


def set_auto_backup_enabled(session, enabled):
    set_setting(session, SETTING_AUTO_BACKUP_KEY, "1" if enabled else "0")


# ⚠️ ملاحظة أداء مهمة (راجع تقرير التدقيق، بند 14.3) - قرار متعمّد بعدم
# التأجيل: كان المقترح الأصلي بالتقرير تأجيل تنفيذ النسخة اللحظية بضع
# ثوانٍ (تجميع عدة commits متلاحقة بنسخة وحدة) وتنفيذها بخيط خلفية منفصل.
# لكن `tests/test_backup.py` يثبت بشكل قاطع إن هذا السلوك "الفوري
# المتزامن" مقصود ومختبَر صراحة كمتطلب أساسي - مثلًا
# test_instant_backup_fires_automatically_on_any_commit يتحقق
# `os.path.exists(instant_path)` **فورًا** بعد `commit()` بدون أي انتظار
# إطلاقًا، ونفس الشي بعدة اختبارات ثانية بهذا الملف. أي تأجيل (حتى لو
# ثانية وحدة بس) يكسر هذي الاختبارات المقصودة، فهذا التأجيل **لم يُنفَّذ**
# عمدًا - راجع سجل التعديلات (CHANGELOG) للتفاصيل والتوصية البديلة.
#
# الجزء الآمن اللي *تم* تنفيذه من بند 14.3 (بدون المساس بالتوقيت الفوري
# إطلاقًا): استبدال shutil.copy2 (نسخ فيزيائي خام) بـ
# sqlite3.Connection.backup() الرسمية (تضمن نسخة متّسقة حتى لو صار كتابة
# نشطة بنفس اللحظة من خيط ثاني - خادم الموبايل بـapp/mobile_server.py
# يشتغل بخيط خلفية منفصل تمامًا ويقدر يكتب لنفس قاعدة البيانات بأي وقت)،
# + كتابة لملف مؤقت ثم استبدال ذرّي (os.replace) حتى ما تترك نسخة نصف
# مكتوبة لو صار عطل بمنتصف النسخ. هذا التحسين **لا يغيّر توقيت التنفيذ
# إطلاقًا** (لسا متزامن 100%، فورًا داخل after_commit بالضبط متل قبل) -
# بس يحسّن اتساق/أمان النسخة نفسها.
def _sqlite_consistent_copy(source_path, dest_path):
    """نسخة متّسقة لملف SQLite عبر sqlite3.Connection.backup() الرسمية
    بدل shutil.copy2 (نسخ فيزيائي خام). تكتب أولًا لملف مؤقت ثم تستبدل
    الملف الوجهة استبدالًا ذرّيًا (os.replace) حتى ما تترك ملف نصف مكتوب
    لو صار عطل بمنتصف النسخ."""
    tmp_path = dest_path + ".tmp"
    src_conn = sqlite3.connect(source_path, timeout=30)
    try:
        dest_conn = sqlite3.connect(tmp_path, timeout=30)
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()
    os.replace(tmp_path, dest_path)


def perform_instant_backup(session):
    """نسخة احتياطية "لحظية" - تُستدعى تلقائيًا وبشكل متزامن فور أي commit
    ناجح بقاعدة البيانات (بيع، إرجاع، إضافة، تعديل...) عبر حدث SQLAlchemy
    مسجّل بـ database.py. تحدّث نفس الملف دائمًا (مو ملف جديد كل مرة) -
    تعكس آخر حالة للبيانات لحظة بلحظة بدون ما تراكم نسخ كثيرة.

    ⚠️ متعمَّد إنها تبقى متزامنة (بدون تأجيل/خيط خلفية) - راجع الملاحظة
    الطويلة بأعلى الملف: هذا السلوك مختبَر صراحة بـ tests/test_backup.py
    كمتطلب أساسي (النسخة لازم تكون جاهزة فورًا لحظة رجوع commit()، بدون
    أي انتظار).

    ملاحظتين تصميم مهمتين (نتيجة تصحيح خلل فعلي أثناء التطوير):
    1. ما نقدر نستخدم استعلامات ORM عادية (session.query) على الجلسة
       الممرّرة هنا، لأن SQLAlchemy يرفضها بخطأ صريح "session is in
       'committed' state" - الجلسة داخل حدث after_commit بالضبط تكون
       بحالة انتقالية ما تسمح بأي استعلام جديد عليها. نقرأ الإعدادات
       المطلوبة (المجلد، حالة التفعيل) عبر اتصال SQL خام منفصل تمامًا
       عن الجلسة بدالها - ما يتأثر بحالتها إطلاقًا.
    2. ما نستخدم set_setting() لتسجيل وقت آخر نسخة، لأنها تسوي commit()
       جديد داخليًا - لو استدعيناها من داخل معالج after_commit (اللي هذي
       الدالة تشتغل بداخله) بيصير استدعاء متكرر لنفس الحدث (recursion).
       نسجل الوقت بملف نصي بسيط بجانب النسخة بدالها."""
    try:
        from .database import engine
        with engine.connect() as conn:
            folder_row = conn.execute(
                text("SELECT value FROM app_settings WHERE key = :k"), {"k": SETTING_FOLDER_KEY}
            ).first()
            folder = folder_row[0] if folder_row else ""
            enabled_row = conn.execute(
                text("SELECT value FROM app_settings WHERE key = :k"), {"k": SETTING_AUTO_BACKUP_KEY}
            ).first()
            enabled = (enabled_row[0] if enabled_row else "1") != "0"

        if not folder or not enabled:
            return
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, INSTANT_BACKUP_FILENAME)
        _sqlite_consistent_copy(DB_PATH, dest)
        ts_path = os.path.join(folder, INSTANT_TIMESTAMP_FILENAME)
        with open(ts_path, "w", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass  # النسخ اللحظي بالخلفية ما يجوز يقاطع عملية المستخدم لو فشل


def list_backups(session):
    """يرجّع مسارات كل النسخ الاحتياطية اليدوية (اللقطات) بنفس المجلد،
    الأحدث أولًا. ما يشمل ملف النسخة اللحظية (هذا منفصل، ملف واحد ثابت)."""
    folder = get_backup_folder(session)
    if not folder or not os.path.isdir(folder):
        return []
    pattern = os.path.join(folder, f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}")
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def instant_backup_path(session):
    """مسار ملف النسخة اللحظية (لو موجود)، وإلا None."""
    folder = get_backup_folder(session)
    if not folder:
        return None
    path = os.path.join(folder, INSTANT_BACKUP_FILENAME)
    return path if os.path.exists(path) else None


def backup_display_name(path):
    """يحوّل اسم ملف النسخة لنص واضح بالعربي بدل الاسم التقني."""
    m = re.search(r"(\d{8})_(\d{6})", os.path.basename(path))
    if not m:
        return os.path.basename(path)
    d, t = m.groups()
    try:
        dt = datetime.strptime(d + t, "%Y%m%d%H%M%S")
        return dt.strftime("%Y-%m-%d الساعة %H:%M")
    except ValueError:
        return os.path.basename(path)


def backup_file_path(session):
    """للتوافق العكسي: يرجّع أحدث نسخة احتياطية يدوية موجودة (أو None)."""
    backups = list_backups(session)
    return backups[0] if backups else None


def _record_backup_timestamp(folder, value):
    """يسجّل وقت آخر نسخة احتياطية (يدوية/دورية) - بدون المرور بـ ORM
    session.commit() إطلاقًا، حتى ما يُطلق حدث after_commit من جديد.

    ملاحظة إصلاح أداء مهمة: كانت هذي الدالتين (perform_backup/
    perform_periodic_backup) تستخدمان set_setting() العادية لتسجيل الوقت،
    وset_setting() تسوي session.commit() داخليًا - وأي commit بأي جلسة
    بكل البرنامج يُطلق تلقائيًا حدث after_commit المسجّل بـ database.py
    (راجع _register_instant_backup_hook)، فيشغّل perform_instant_backup()
    من جديد ويسوي نسخة كاملة إضافية غير مقصودة لملف قاعدة البيانات لكل
    نسخة يدوية أو دورية واحدة (نسختان فعليتان بدل واحدة).

    هذي الدالة تسجّل نفس المعلومة بنفس الشكل اللي get_last_backup_at()
    تتوقعه بالضبط (ملف الطابع الزمني بالمجلد + عمود app_settings
    الاحتياطي)، بس بدون أي نسخة إضافية:
    1. تكتب ملف الطابع الزمني (INSTANT_TIMESTAMP_FILENAME) - نفس الملف اللي
       get_last_backup_at() تقرأه أولًا وتفضّله دائمًا لو موجود، حتى تبقى
       "آخر نسخة محفوظة" بالواجهة محدّثة فورًا بعد "خذ نسخة الآن" بالضبط
       متل قبل هذا الإصلاح.
    2. تسجّل نفس القيمة بعمود app_settings عبر اتصال SQL خام منفصل تمامًا
       (نفس أسلوب perform_instant_backup() أصلًا بقراءة الإعدادات) - كنسخة
       احتياطية للحالة النادرة اللي ماكو فيها ملف طابع زمني بعد."""
    try:
        ts_path = os.path.join(folder, INSTANT_TIMESTAMP_FILENAME)
        with open(ts_path, "w", encoding="utf-8") as f:
            f.write(value)
    except OSError:
        pass
    from .database import engine
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES (:k, :v) "
                "ON CONFLICT(key) DO UPDATE SET value = :v"
            ),
            {"k": SETTING_LAST_BACKUP_KEY, "v": value},
        )


def perform_backup(session):
    """لقطة يدوية بطابع زمني (يضغطها المستخدم بنفسه أو تصير عند إغلاق
    البرنامج) - منفصلة عن النسخة اللحظية التلقائية. يرجع (True, المسار)
    لو نجح، (False, رسالة الخطأ) لو فشل."""
    folder = get_backup_folder(session)
    if not folder:
        return False, "ماكو مجلد محدد للنسخ الاحتياطي بعد."
    try:
        os.makedirs(folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(folder, f"{BACKUP_PREFIX}{timestamp}{BACKUP_SUFFIX}")
        shutil.copy2(DB_PATH, dest)
        # راجع تعليق _record_backup_timestamp فوق - تسجيل مباشر بدون
        # commit عبر ORM حتى ما يتسبب بنسخة لحظية إضافية غير مقصودة.
        _record_backup_timestamp(folder, datetime.now().strftime("%Y-%m-%d %H:%M"))

        # تنظيف النسخ الأقدم من الحد الأقصى
        backups = list_backups(session)
        for old_path in backups[MAX_BACKUPS:]:
            try:
                os.remove(old_path)
            except OSError:
                pass
        return True, dest
    except Exception as e:
        return False, str(e)


def perform_periodic_backup(session):
    """نسخة احتياطية دورية - تُستدعى من المؤقت كل 30 دقيقة وعند إغلاق
    البرنامج بس. تحدّث ملف واحد ثابت (H1_backup_periodic.db) دائمًا بدل ما
    تسوي ملف جديد بطابع زمني كل مرة (كان قبل هذا الإصلاح يستدعي
    perform_backup فيتراكم لين آخر 10 نسخ متشابهة بدون داعي فعلي، بما إنه
    غرضها الحماية الدورية بس مو أرشيف نقاط زمنية متعددة).

    منفصلة تمامًا عن:
    - perform_instant_backup: نسخة لحظية فور كل عملية (بيع/إضافة/تعديل).
    - perform_backup: لقطة يدوية بطابع زمني، تصير بس لما المستخدم يضغط
      "خذ نسخة الآن" بنفسه من شاشة النسخ الاحتياطي - هذي لسا تحتفظ بتاريخ
      كامل (آخر 10) لأنها المفروض تسمح بالرجوع لنقطة زمنية معينة يختارها
      المستخدم بنفسه، عكس النسخة الدورية اللي بس آخر حالة تهمها."""
    folder = get_backup_folder(session)
    if not folder:
        return False, "ماكو مجلد محدد للنسخ الاحتياطي بعد."
    try:
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, PERIODIC_BACKUP_FILENAME)
        shutil.copy2(DB_PATH, dest)
        # راجع تعليق _record_backup_timestamp فوق - تسجيل مباشر بدون
        # commit عبر ORM حتى ما يتسبب بنسخة لحظية إضافية غير مقصودة.
        _record_backup_timestamp(folder, datetime.now().strftime("%Y-%m-%d %H:%M"))
        return True, dest
    except Exception as e:
        return False, str(e)


def restore_backup(session, backup_path=None):
    """يستعيد نسخة احتياطية محدّدة (أو النسخة اللحظية لو ما حدّدت وحدة -
    هي الأدق والأحدث دائمًا). يرجع (True, None) لو نجح، (False, رسالة الخطأ) لو فشل."""
    path = backup_path or instant_backup_path(session) or backup_file_path(session)
    if not path or not os.path.exists(path):
        return False, "ماكو نسخة احتياطية موجودة بالمجلد المحدد."
    try:
        # نسكر اتصال قاعدة البيانات الحالي قبل ما نستبدل الملف تحته
        from .database import engine
        session.close()
        engine.dispose()
        shutil.copy2(path, DB_PATH)
        return True, None
    except Exception as e:
        return False, str(e)
