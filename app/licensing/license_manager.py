"""
منطق الترخيص - مستقل تمامًا عن باقي البرنامج (ما يستورد شي من app.db أو app.ui
عدا نافذة التفعيل). نقطة الدخول الوحيدة اللي يحتاجها main.py هي check_license().
"""
import os
import json
import uuid
import platform
import hashlib
import urllib.request
import urllib.parse
from datetime import date

from app.licensing.config import (
    WEB_APP_URL, TRIAL_DAYS, HTTP_TIMEOUT_SECONDS,
)

STATE_DIR = os.path.join(os.path.expanduser("~"), ".olivia_pharmacy")
STATE_PATH = os.path.join(STATE_DIR, "license.json")


def _get_stable_machine_key():
    """
    مصدر بصمة ثابت فعليًا من نظام التشغيل - على عكس uuid.getnode() اللي ممكن
    يرجّع قيمة مختلفة كل تشغيل (خصوصًا بويندوز لو فيه أكثر من كرت شبكة، أو
    الواي فاي يتصل/ينفصل بين مرة وأخرى). كل مصدر هنا ثابت طول عمر تنصيب
    النظام (ما يتغيّر إلا بفورمات كامل).
    """
    system = platform.system()

    if system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            if guid:
                return guid
        except Exception:
            pass

    elif system == "Linux":
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                    if val:
                        return val
            except OSError:
                pass

    elif system == "Darwin":
        try:
            import subprocess
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL, timeout=5,
            ).decode("utf-8", errors="ignore")
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        except Exception:
            pass

    # ما قدرنا نحصل على معرف ثابت من نظام التشغيل - نرجع None حتى نعرف
    # بالدالة اللي تستدعينا إننا لازم نعتمد على احتياطي آخر.
    return None


def get_device_id():
    """
    بصمة جهاز ثابتة. نعتمد أساسًا على معرف نظام التشغيل الثابت (MachineGuid
    بويندوز / machine-id بلينكس / IOPlatformUUID بماك) لأنه ما يتغيّر أبدًا
    بين مرات التشغيل - على عكس uuid.getnode() اللي كان يرجّع قيم مختلفة
    أحيانًا (خصوصًا بويندوز مع أكثر من كرت شبكة) ويسبب ظهور الجهاز كأنه
    "جهاز جديد" كل مرة عند السيرفر.
    """
    stable_key = _get_stable_machine_key()
    if stable_key:
        raw = f"{stable_key}-{platform.node()}"
    else:
        # احتياطي أخير لو تعذّر الوصول لمعرف نظام التشغيل - نفس الطريقة القديمة
        raw = f"{uuid.getnode()}-{platform.node()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _today_str():
    return date.today().isoformat()


def _days_between(old_str, new_date=None):
    if not old_str:
        return None
    old = date.fromisoformat(old_str)
    new = new_date or date.today()
    return (new - old).days


def _load_state():
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _http_post_json(payload):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            WEB_APP_URL, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None  # ما فيه نت أو السيرفر ما رد - نتعامل وياها كـ"غير معروف" مو خطأ قاتل


def _http_get_json(params):
    try:
        qs = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{WEB_APP_URL}?{qs}", timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _try_register(pharmacy_name, phone, device_id):
    result = _http_post_json({
        "action": "register",
        "pharmacy_name": pharmacy_name,
        "phone": phone,
        "device_id": device_id,
    })
    return result.get("status") if result else None


def _try_check_status(device_id):
    result = _http_get_json({"device_id": device_id})
    if result and "status" in result:
        return result["status"]
    return None


def check_license(parent=None):
    """
    نقطة الدخول الوحيدة. يرجع True لو يخلي البرنامج يكمل الفتح، False لو لازم يقفل.
    """
    from app.licensing.activation_window import ActivationWindow

    device_id = get_device_id()
    state = _load_state()

    if state is None:
        # أول فتحة على الإطلاق - نبدأ عدّاد التجربة من الحين، بغض النظر هل راح يسجل أو لا
        state = {
            "device_id": device_id,
            "registered": False,
            "pharmacy_name": None,
            "phone": None,
            "first_run_date": _today_str(),
            "server_status": "pending",
            "last_check_date": None,
        }
        _save_state(state)

    days_used = _days_between(state["first_run_date"]) or 0
    days_left = TRIAL_DAYS - days_used

    if not state.get("registered"):
        # لسه ما سجل بياناته - كل فتحة نعطيه الخيار: يسجل الحين، أو يكمل تجربة
        if days_left <= 0:
            ActivationWindow.show_blocked(
                parent,
                "انتهت مدة التجربة المجانية (14 يوم) ولسه ما سجّلت بيانات الصيدلية.\n"
                "سجّل بياناتك لإرسال طلب التفعيل.",
            )
            return False

        choice = ActivationWindow.ask_registration_or_trial(parent, days_left)
        if choice.get("action") == "register":
            state["registered"] = True
            state["pharmacy_name"] = choice["name"]
            state["phone"] = choice["phone"]
            _save_state(state)
            _try_register(state["pharmacy_name"], state["phone"], device_id)
        return True  # سجل أو اختار يكمل تجربة - بالحالتين يكمل فتح البرنامج

    # -------- من هنا صار مسجّل فعليًا (بيانات مرسلة سابقًا) --------
    live_status = _try_check_status(device_id)
    if live_status is None or live_status == "not_found":
        # احتمال التسجيل الأول ما وصل للسيرفر (فتح أول مرة بدون نت، أو
        # قطع اتصال لحظي) - سواء ماكو رد إطلاقًا أو رد صريح "ماكو سجل"،
        # نعيد محاولة إرسال التسجيل حتى ما يضل الزبون عالق بحالة "not_found" للأبد
        _try_register(state["pharmacy_name"], state["phone"], device_id)
        live_status = _try_check_status(device_id)

    if live_status is not None:
        state["server_status"] = live_status
        state["last_check_date"] = _today_str()
        _save_state(state)
    # ملاحظة: ما نحظر البرنامج لمجرد إنه مرّ وقت طويل بدون اتصال ناجح.
    # الإلغاء يشتغل بس لو صار اتصال ناجح فعلي رجع فيه "revoked" من السيرفر -
    # يعني صيدلية تشتغل أوفلاين بالكامل للأبد، تبقى شغالة بآخر حالة معروفة عندها.

    status = state["server_status"]

    if status == "approved":
        return True

    if status in ("rejected", "revoked"):
        reason = "تم رفض طلب التفعيل." if status == "rejected" else "تم إلغاء تفعيل هذا الترخيص."
        ActivationWindow.show_blocked(parent, reason)
        return False

    # حالة انتهاء الاشتراك - مختلفة تمامًا عن "لسه بالتجربة وما وصلت
    # موافقة أصلاً". هذا مستخدم كان مفعّل ومشترك فعليًا، والاشتراك خلصت
    # مدته. لازم رسالة مختلفة عن رسالة "انتهت التجربة المجانية" تحت حتى ما
    # يتوه صاحب الصيدلية ويظن إنه أصلاً ما كان مفعّل من الأساس.
    # المطابقة هنا بـ "تحتوي على" مو مطابقة حرفية دقيقة - عشان تتحمّل أي
    # فرق إملائي بسيط بالكلمة العربية بالشيت (اكسباير/إكسباير/الخ).
    status_norm = (status or "").strip().lower()
    if any(k in status_norm for k in ("expired", "expire", "اكسباير", "إكسباير", "منتهي")):
        ActivationWindow.show_blocked(parent, "انتهت مدة الاشتراك بالبرنامج. جدّد اشتراكك لمتابعة الاستخدام.")
        return False

    # status == "pending" أو "not_found" -> مسجّل بس لسه ما وصلت الموافقة
    if days_left > 0:
        def _resend(name, phone):
            # المستخدم قد يكون عدّل الاسم/الرقم بنافذة المراجعة (مثلاً كان مدخل
            # رقم غلط أول مرة) - نحدّث الحالة المحفوظة بالقيم الجديدة قبل الإرسال.
            state["pharmacy_name"] = name
            state["phone"] = phone
            _save_state(state)
            result = _try_register(name, phone, device_id)
            return result is not None
        ActivationWindow.show_trial_notice(
            parent, days_left, resend_callback=_resend,
            current_name=state["pharmacy_name"], current_phone=state["phone"],
        )
        return True

    ActivationWindow.show_blocked(
        parent,
        "انتهت مدة التجربة المجانية (14 يوم) ولسه ما تم تفعيل الصيدلية.",
    )
    return False
