"""الأدوية "المعتمدة" داخل الصيدلية.

تعريف "دواء معتمد": دواء مضاف يدويًا من الصيدلاني (Product.is_custom=True)
أو استُلمت له دفعة شراء فعلية ولو مرة وحدة (له سجل بجدول batches، حتى لو
الكمية الحالية صارت صفر بعد ما انباع) - يعني دواء موجود فعليًا بالصيدلية
وله أسعار/كميات حقيقية تم التعامل معها، مو مجرد اسم وباركود من الكتالوج
الجاهز (starter_catalog.xlsx) لم يُشترَ ولم يُستخدم أبدًا.

هذا الملف لا يضيف أي عمود جديد لقاعدة البيانات - "الاعتماد" يُحسب تلقائيًا
من بيانات موجودة أصلاً (is_custom + وجود دفعات)، وإعداد التفعيل العام
يُخزَّن بجدول app_settings الموجود مسبقًا (key/value)، فما فيه أي تغيير
بمخطط قاعدة البيانات.

يُستخدم بمكانين مختلفين تمامًا:
1. فلتر يدوي بشاشة المخزون (checkbox "عرض الأدوية المعتمدة فقط") - يتحكم
   فيه المستخدم بأي وقت، بغض النظر عن الإعداد العام تحت.
2. إعداد عام بشاشة الإعدادات (اعتماد الأدوية المعتمدة) - لو مفعّل، يقصر
   التنبيهات والتقارير (نقص، قرب انتهاء، منتهي، راكد...) على المعتمدة بس
   تلقائيًا بكل الشاشات (الرئيسية والتقارير وشارة التنبيهات بالشريط الجانبي).
"""
from sqlalchemy import or_

from .models import Product, Batch
from .settings_helper import get_setting, set_setting

APPROVED_SETTING_KEY = "approved_drugs_filter_enabled"


def approved_clause(session):
    """شرط SQLAlchemy يُستخدم داخل .filter() على استعلام Product - يطابق
    فقط الأدوية المعتمدة. للاستخدام لما نبني الاستعلام مباشرة من قاعدة
    البيانات بدون ما نجيب batches مسبقًا."""
    batches_subq = session.query(Batch.product_id).distinct()
    return or_(Product.is_custom == True, Product.id.in_(batches_subq))


def is_product_approved(product):
    """نفس منطق approved_clause بس على كائن Product محمّل مسبقًا بالذاكرة
    (مع batches محمّلة عبر joinedload) - يفادي استعلام إضافي لقاعدة
    البيانات لو الكائن أصلاً موجود بالذاكرة."""
    if product.is_custom:
        return True
    return len(product.batches) > 0


def is_approved_filter_enabled(session):
    """هل إعداد "الاعتماد على الأدوية المعتمدة" مفعّل بشاشة الإعدادات؟"""
    return get_setting(session, APPROVED_SETTING_KEY, "0") == "1"


def set_approved_filter_enabled(session, enabled):
    set_setting(session, APPROVED_SETTING_KEY, "1" if enabled else "0")
