"""
نظام التحديث الجزئي (Partial Update) - يقارن ملفات app/ المحلية بمانفست
النسخة الأحدث، يحمّل بس الملفات المتغيّرة (من GitHub Releases)، يتحقق من
سلامتها (SHA-256)، ويطبّقها بأمان بعد إغلاق البرنامج.

هذا الملف "منطق بحت" - ما يعتمد على PySide6/Qt إطلاقًا، حتى يصير سهل
الاختبار لحاله. الواجهة (شريط تقدم، أزرار، رسائل) موجودة بـ
app/ui/backup_view.py وتستدعي الدوال هنا.

⚠️ ما يلمس قاعدة البيانات (olivia.db) ولا إعدادات المستخدم ولا النسخ
الاحتياطية إطلاقًا - فقط ملفات app/*.py (كود البرنامج نفسه).

⚠️ منفصل تمامًا عن نظام الترخيص/فحص التحديث الكامل (app/update_checker.py،
Apps Script) - ما يلمسه ولا يعتمد عليه إطلاقًا. المانفست وملفات التحديث
كلها من GitHub (نفس الـrepo، مكان واحد بس):
    manifest.json  -> بجذر الـrepo نفسه (GitHub raw)
    الملفات الفعلية -> GitHub Releases (نفس الـrepo)

خطوات الاستخدام المتوقّعة من المستدعي (بنفس هذا الترتيب):
    manifest = fetch_manifest()
    if manifest and is_partial_update_possible(manifest):
        to_download, to_delete = compute_diff(manifest)
        staging_dir = download_update_files(manifest, to_download, progress_callback)
        # ... تأكيد المستخدم ...
        apply_update_and_relaunch(staging_dir, to_delete)
        # المستدعي يسكّر البرنامج مباشرة بعدها (QApplication.quit() مثلاً)
    else:
        # Full Update كـ fallback - نفس آلية app/update_checker.py الحالية
        # (فتح رابط التحميل بالمتصفح)، بدون أي تغيير عليها.
"""
import os
import sys
import json
import hashlib
import shutil
import tempfile
import subprocess
import urllib.request

from app.version import APP_VERSION
from app.update_checker import _version_tuple

# ⚠️ غيّرها لاسم الـrepo الحقيقي حقك على GitHub (بصيغة "username/repo")
# قبل أي استخدام فعلي - هذا الثابت الوحيد اللي لازم تعدّله يدويًا بكل
# هذا الملف.
GITHUB_REPO = "h1v2s3ll-debug/h1.git"

# رابط ملف المانفست نفسه - نفترض إنه محفوظ بجذر الـrepo مباشرة (فرع main)
# باسم manifest.json، ويتحدّث (commit) كل ما تطلع نسخة جديدة. GitHub
# raw.githubusercontent.com يرجّع محتوى الملف مباشرة (مو صفحة HTML).
MANIFEST_URL = f"https://raw.githubusercontent.com/{h1v2s3ll-debug/h1.git}/main/manifest.json"

HTTP_TIMEOUT_SECONDS = 10


class UpdateDownloadError(Exception):
    """تنرمى لو فشل تحميل أو تحقق أي ملف من ملفات التحديث. الـstaging
    ينحذف تلقائيًا قبل ما تنرمى - app/ الحقيقي ما يتأثر إطلاقًا."""
    pass


def app_root_dir():
    """المجلد اللي فيه app/ فعليًا - جنب الـexe وقت التشغيل الحقيقي
    (frozen)، أو جذر المشروع وقت التطوير. نفس منطق launcher.py بالضبط -
    لازم يضلوا متطابقين تمامًا وإلا التحديث يطبّق بمكان غلط."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_manifest():
    """يجيب مانفست النسخة الأحدث مباشرة من GitHub (MANIFEST_URL أعلاه) -
    ملف JSON عادي، بدون أي سيرفر وسيط. يرجع dict أو None لو ماكو نت / الملف
    مو موجود / رد غير صالح.

    شكل الملف المتوقَّع (manifest.json بجذر الـrepo):
        {
            "version": "27",
            "min_partial_from_version": "24",
            "files": [{"path": "app/ui/inventory_view.py", "sha256": "..."}, ...],
            "removed_files": ["app/ui/old_screen.py"]
        }
    (نفس الشكل اللي يطلعه dev_tools/compute_update_hashes.py جاهز للصق)."""
    try:
        with urllib.request.urlopen(MANIFEST_URL, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            manifest = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not manifest or not manifest.get("version") or not manifest.get("files"):
        return None
    return manifest


def is_partial_update_possible(manifest):
    """هل نسختنا الحالية مؤهّلة للتحديث الجزئي، أو الفرق كبير جدًا ولازم
    Full Update (مثلاً نسخة قديمة جدًا فيها تغييرات بنيوية كبيرة)."""
    min_from = manifest.get("min_partial_from_version")
    if not min_from:
        return True  # المانفست ما حدد قيد أدنى - نعتبره مسموح لأي نسخة
    return _version_tuple(APP_VERSION) >= _version_tuple(min_from)


def compute_diff(manifest):
    """يقارن ملفات app/ المحلية الحالية (SHA-256 لكل ملف) مع المانفست.
    يرجع (to_download, to_delete):
      to_download: قائمة entries من المانفست (path + sha256) لكل ملف ناقص
                   أو مختلف عن المحلي.
      to_delete:   قائمة مسارات (نصوص) لملفات محلية موجودة فعليًا لازم
                   تنحذف (وردت بـ removed_files بالمانفست)."""
    base = app_root_dir()
    to_download = []
    for entry in manifest.get("files", []):
        rel_path = entry["path"]
        expected_hash = entry["sha256"]
        local_path = os.path.join(base, rel_path.replace("/", os.sep))
        if not os.path.isfile(local_path):
            to_download.append(entry)
            continue
        try:
            if _sha256_of_file(local_path) != expected_hash:
                to_download.append(entry)
        except OSError:
            to_download.append(entry)

    to_delete = []
    for rel_path in manifest.get("removed_files", []):
        local_path = os.path.join(base, rel_path.replace("/", os.sep))
        if os.path.isfile(local_path):
            to_delete.append(rel_path)

    return to_download, to_delete


def _github_file_url(version, relative_path):
    """رابط تحميل مباشر لملف وحد من GitHub Releases (نفس GITHUB_REPO
    أعلاه). قاعدة التسمية المتفَق عليها: GitHub ما يقبل "/" بأسماء
    الملفات المرفقة بالـRelease، فلازم نستبدلها بـ"__" وقت الرفع اليدوي -
    ونفس القاعدة هنا وقت بناء رابط التحميل. مثال:
    app/ui/inventory_view.py -> app__ui__inventory_view.py"""
    flat_name = relative_path.replace("/", "__").replace("\\", "__")
    return f"https://github.com/{h1v2s3ll-debug/h1.git}/releases/download/v{version}/{flat_name}"


def staging_dir_path():
    return os.path.join(os.path.expanduser("~/.olivia_pharmacy"), "update_staging")


def discard_staged_update(staging_dir):
    """يحذف مجلد الـstaging بالكامل - يُستدعى لو المستخدم أجّل تطبيق
    التحديث بعد ما خلص التحميل والتحقق (حتى ما يضل ملفات معلّقة على
    القرص للأبد)، أو لو صار إلغاء يدوي أثناء التحميل."""
    shutil.rmtree(staging_dir, ignore_errors=True)


def download_update_files(manifest, to_download, progress_callback=None):
    """يحمّل الملفات المطلوبة لمجلد staging مؤقت منفصل تمامًا عن app/
    الحقيقي (ما يلمسه إطلاقًا بهذي المرحلة)، ويتحقق من SHA-256 لكل ملف
    فور تحميله. progress_callback(done_count, total_count, current_path)
    تُستدعى بعد كل ملف - اختيارية.

    يرجع مسار مجلد الـstaging لو نجح التحميل والتحقق لكل الملفات، أو
    يرمي UpdateDownloadError لو فشل أي ملف (ويحذف الـstaging بالكامل قبل
    الرمي - ما يترك بقايا نصف محمّلة)."""
    version = manifest["version"]
    staging_dir = staging_dir_path()
    if os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)
    os.makedirs(staging_dir, exist_ok=True)

    try:
        total = len(to_download)
        for i, entry in enumerate(to_download):
            rel_path = entry["path"]
            expected_hash = entry["sha256"]
            url = _github_file_url(version, rel_path)
            dest_path = os.path.join(staging_dir, rel_path.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = resp.read()
            except Exception as e:
                raise UpdateDownloadError(f"تعذّر تحميل {rel_path}: {e}")

            actual_hash = hashlib.sha256(data).hexdigest()
            if actual_hash != expected_hash:
                raise UpdateDownloadError(
                    f"الملف {rel_path} وصل تالف (hash غير مطابق) - حاول مرة ثانية"
                )

            with open(dest_path, "wb") as f:
                f.write(data)

            if progress_callback:
                progress_callback(i + 1, total, rel_path)

        return staging_dir
    except UpdateDownloadError:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def apply_update_and_relaunch(staging_dir, to_delete):
    """يطبّق التحديث فعليًا وينهي هذي الدالة **بدون** ما ينتظر - التطبيق
    الفعلي (نقل الملفات + الحذف + إعادة التشغيل) يصير بسكربت .bat منفصل
    يشتغل بعد ما هذا البرنامج يسكّر تمامًا، حتى ما نحاول نستبدل ملفات وهي
    مستخدمة بنفس اللحظة.

    ⚠️ لازم تكون آخر شي يستدعيه المستدعي - البرنامج لازم يسكّر مباشرة
    بعدها (QApplication.quit() أو ما يعادلها)."""
    base = app_root_dir()
    app_dir = os.path.join(base, "app")
    exe_path = sys.executable if getattr(sys, "frozen", False) else None

    bat_lines = [
        "@echo off",
        # مهلة قصيرة تضمن إن العملية الحالية سكّرت فعليًا قبل ما نحاول
        # نلمس ملفاتها.
        "timeout /t 2 /nobreak > nul",
    ]
    for root, _dirs, files in os.walk(staging_dir):
        for fname in files:
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, staging_dir)
            dest = os.path.join(app_dir, rel)
            dest_dir = os.path.dirname(dest)
            bat_lines.append(f'if not exist "{dest_dir}" mkdir "{dest_dir}"')
            bat_lines.append(f'move /y "{src}" "{dest}" > nul')
    for rel_path in to_delete:
        target = os.path.join(base, rel_path.replace("/", os.sep))
        bat_lines.append(f'del /f /q "{target}" 2>nul')
    bat_lines.append(f'rmdir /s /q "{staging_dir}" 2>nul')
    if exe_path:
        bat_lines.append(f'start "" "{exe_path}"')
    bat_lines.append('del "%~f0"')

    bat_path = os.path.join(tempfile.gettempdir(), "h1_apply_update.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write("\r\n".join(bat_lines))

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["cmd", "/c", "start", "", bat_path], creationflags=creationflags)
