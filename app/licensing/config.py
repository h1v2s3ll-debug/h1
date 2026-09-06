"""
إعدادات نظام الترخيص - كل شي خاص بالتفعيل موجود هنا بمكان واحد.
"""

# الرابط اللي حصلت عليه بعد نشر Apps Script (ينتهي بـ /exec)
WEB_APP_URL = "https://script.google.com/macros/s/AKfycbw6I0L69Wh-QuL-siFAvwFmFJD8g92osAyvLGMYa4SeiOCHUNC7wDkkMTGwM5upmY57/exec"

APP_DISPLAY_NAME = "نظام H1 للصيدليات"

TRIAL_DAYS = 14           # مدة التجربة المجانية من أول تشغيل
# ملاحظة: ما فيه إجبار على اتصال دوري بعد الموافقة - يشتغل أوفلاين للأبد.
# الإلغاء (revoked) يطبّق بس لو صار اتصال ناجح فعلي بعدين وشاف السيرفر الحالة الجديدة.
HTTP_TIMEOUT_SECONDS = 6  # مهلة الاتصال بالسيرفر - قصيرة حتى ما تعلّق البرنامج لو النت بطيء/مقطوع

SUPPORT_WHATSAPP_NUMBER = "07774605020"  # رقم التواصل الظاهر بشاشات التسجيل/التفعيل والحظر
