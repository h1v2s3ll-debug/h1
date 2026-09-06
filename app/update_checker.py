"""
فحص تحديثات البرنامج - فحص يدوي بس (زر "التأكد من وجود تحديثات" بشاشة
النسخ الاحتياطي)، ماكو أي فحص تلقائي عند فتح البرنامج.

يقارن رقم النسخة المحلي (app/version.py) برقم latest_version المخزّن
بتبويبة "updates" بنفس شيت الترخيص، عن طريق حالة check_update المضافة
لنفس Apps Script المستخدم بالترخيص (نفس WEB_APP_URL).
"""
import json
import urllib.request
import urllib.parse

from app.licensing.config import WEB_APP_URL, HTTP_TIMEOUT_SECONDS
from app.version import APP_VERSION


def _http_get_json(params):
    try:
        qs = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{WEB_APP_URL}?{qs}", timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None  # ماكو نت أو السيرفر ما رد - نتعامل وياها كخطأ اتصال عادي


def _version_tuple(v):
    """يحوّل رقم نسخة نصي لصيغة مقارنة رقمية صحيحة - حتى "10" تنحسب أكبر
    من "9" صح، و"1.10" أكبر من "1.9" صح (بدل المقارنة النصية الغلط)."""
    parts = []
    for p in str(v).strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_update():
    """
    يرجع (status, info):
      ("error", None)                              - ماكو نت / السيرفر ما رد / رد غير صالح
      ("up_to_date", None)                         - نسختك الحالية هي الأحدث
      ("update_available", {version, url, notes})  - فيه نسخة أحدث متوفرة
    """
    data = _http_get_json({"action": "check_update"})
    if not data or not data.get("ok"):
        return "error", None

    latest = data.get("latest_version", "")
    if not latest:
        return "error", None

    if _version_tuple(latest) > _version_tuple(APP_VERSION):
        return "update_available", {
            "version": latest,
            "url": data.get("download_url", "") or "",
            "notes": data.get("notes", "") or "",
        }
    return "up_to_date", None
