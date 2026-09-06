"""مساعد بسيط لقراءة/حفظ إعدادات البرنامج (طابعة، سكانر، مفتاح API...)."""
from .models import AppSetting


def get_setting(session, key, default=""):
    row = session.query(AppSetting).get(key)
    return row.value if row else default


def set_setting(session, key, value):
    row = session.query(AppSetting).get(key)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))
    session.commit()


# --- سعر صرف الدولار مقابل الدينار (يُدخله المستخدم يدويًا من الإعدادات) ---
# مستخدم من شاشة المخزون لتحويل سعر الشراء بالدولار لسعر بالدينار وقت
# الإدخال (يخزن بالدينار دائمًا بقاعدة البيانات - نفس المنطق القديم بالضبط،
# هذا فقط يسهّل الإدخال ويمنع خطأ حسابي يدوي من المستخدم).
def get_usd_rate(session):
    value = get_setting(session, "usd_exchange_rate", "")
    try:
        rate = float(value)
    except (TypeError, ValueError):
        rate = 0
    return rate if rate > 0 else 0


def set_usd_rate(session, rate):
    set_setting(session, "usd_exchange_rate", str(rate))


# --- عدد أيام التنبيه لقرب انتهاء الصلاحية (كان ثابت 90 بكل الشاشات) ---
def get_expiry_alert_days(session):
    value = get_setting(session, "expiry_alert_days", "90")
    try:
        days = int(float(value))
    except (TypeError, ValueError):
        days = 90
    return days if days > 0 else 90


def set_expiry_alert_days(session, days):
    set_setting(session, "expiry_alert_days", str(int(days)))
