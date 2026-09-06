"""
شاشة المشتريات (فواتير الشراء).

ميزة "تصوير الفاتورة" (بالذكاء الاصطناعي - يحتاج انترنت + مفتاح API):
1) تصوّر/ترفع صورة فاتورة الشراء الورقية.
2) البرنامج يرسل الصورة مباشرة لنموذج ذكاء اصطناعي (نفس مفتاح ومزوّد
   "المستشار الذكي" المحفوظ بشاشة الإعدادات - Gemini أو Anthropic Claude)،
   ويطلب منه يقرأ الفاتورة ويرجع كل صنف باسمه وكميته وسعره كنص منظّم
   (JSON) - هذا أدق بكثير من القراءة الحرفية للنص لأن النموذج يفهم شكل
   جدول الفاتورة (مو بس يقرأ حروف)، ويشتغل مباشرة بدون أي تثبيت برنامج
   إضافي على الجهاز (خلافًا لـ Tesseract سابقًا).
3) كل صنف يرجعه الذكاء الاصطناعي يُقارَن تلقائيًا بقائمة أدويتك الحالية
   ويقترح أقرب تطابق (نفس منطق المطابقة الذكية السابق، ما تغيّر).
4) يفتحلك جدول مراجعة (ReceiptReviewDialog) - أنت تراجع/تصحح كل صف (الدواء
   المطابق، الكمية، السعر) وتشيل صح ✓ عن أي سطر غلط، وتقدر تضيف دواء جديد
   مباشرة من نفس الجدول لو الصنف مو موجود عندك أصلاً.
5) بعد ما تأكد، الأصناف المحددة تنضاف لسلة الفاتورة تحت (نفس سلة الإدخال
   اليدوي بالضبط) وانت تكمّل/تعدّل/تأكد الشراء بنفس الطريقة المعتادة.

⚠️ يحتاج انترنت شغّال وقت الاستخدام، ويحتاج نفس مفتاح API المحفوظ بشاشة
الإعدادات (قسم المستشار الذكي)، وقد يترتب عليه تكلفة استخدام بسيطة حسب
سياسة المزوّد (نفس تكلفة سؤال واحد للمستشار الذكي تقريبًا لكل صورة).

هذا كله قراءة/تخمين آلي غير مضمون 100% (خط اليد، جودة الصورة، تصميم الفاتورة
كلها تأثر) - عشان هيچي خطوة المراجعة بالجدول إجبارية قبل ما أي صنف يدخل
فعليًا للمخزون، ولا شي ينضاف أو يتغيّر بقاعدة البيانات إلا بعد ما تضغط تأكيد
الشراء بنفس زر "تأكيد الشراء" الأصلي - ولا سطر من منطق حساب المخزون/التكلفة
تغيّر.
"""
import re
import os
import json
import base64
import difflib
from datetime import date, timedelta, datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QTextEdit, QDateEdit, QFrame,
    QLineEdit, QDialog, QFormLayout, QScrollArea, QTabWidget, QCompleter,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QDate, QTimer, QThread, Signal, QEvent
from PySide6.QtGui import QColor
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from app.db.database import get_session
from app.db.settings_helper import get_setting, set_setting, get_usd_rate
from app.db.models import Product, ProductUnit, Batch, PurchaseOrder, PurchaseOrderItem, StockMovement, Supplier, InvoiceTextMapping
from app.db.purchase_accounting import bulk_order_summaries, purchase_order_summary
from app.ui.widgets import disable_scroll, NumberLineEdit, enable_touch_scroll, create_usd_price_row
from app.ui.icons import icon
from app.ui.theme import TEAL_700
from app.ui.inventory_view import AddProductDialog, _strips_from_cartons
from app.ui.mobile_view import MobileLinkCard
from app.ui.pos_view import normalize_arabic
# نافذة "إضافة مورد جديد" وتبويب "الموردون والحسابات" الجديد - انتقلت
# AddSupplierDialog لملف مستقل (supplier_accounts_view.py) حتى تنستورد من
# مكانين (هذا الملف + التبويب الجديد) بدون تكرار الكود ولا أي استيراد دائري.
from app.ui.supplier_accounts_view import AddSupplierDialog, SupplierAccountsTab


# --- استخراج أصناف الفاتورة بالذكاء الاصطناعي (Gemini أو Anthropic) ------
#
# نفس مفتاح API ونفس مزوّد "المستشار الذكي" (شاشة الإعدادات) - المستخدم ما
# يحتاج يضيف مفتاح ثاني ولا يعدّل أي إعداد جديد، الميزتين تستخدمون نفس
# الإعداد المحفوظ أصلًا.

_RECEIPT_AI_PROMPT = (
    "هذي صورة فاتورة شراء أدوية من مورد لصيدلية عراقية. اقرأ كل صنف موجود "
    "بجدول الفاتورة وارجعلي فقط مصفوفة JSON صحيحة (بدون أي نص أو شرح أو "
    "علامات ``` قبلها أو بعدها)، كل عنصر فيها بهذا الشكل بالضبط:\n"
    '[{"name": "اسم الدواء كما مكتوب بالفاتورة", "qty": رقم_الكمية_بالباكيت_أو_العلبة, '
    '"price": رقم_سعر_شراء_الوحدة_الواحدة}]\n'
    "ملاحظات مهمة:\n"
    "- تجاهل كليًا: عنوان الفاتورة، اسم المورد، التاريخ، رقم الفاتورة، "
    "المجموع الكلي، الضريبة، التوقيع، وأي سطر مو صنف دواء فعلي.\n"
    "- \"price\" يعني سعر الوحدة الواحدة (الباكيت/العلبة) مو الإجمالي "
    "(الكمية × السعر) - لو الفاتورة فيها عمود إجمالي منفصل، تجاهله.\n"
    "- لو ماكو أي صنف واضح بالصورة، ارجع مصفوفة فاضية: []\n"
    "- لا ترجع أي شي غير مصفوفة JSON نفسها."
)


def _image_to_base64(image_path):
    with open(image_path, "rb") as f:
        raw = f.read()
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    return mime, base64.b64encode(raw).decode("utf-8")


def _parse_ai_json_items(text_reply):
    """يستخرج مصفوفة JSON من رد النموذج حتى لو غلّفها بعلامات ```json عرضًا
    (شائع بالنماذج رغم طلب عدم فعل هذا بالبرومبت) - يرجع [] لو فشل التحليل
    كليًا (تظهر وقتها رسالة خطأ توضيحية للمستخدم بدل ما ينهار البرنامج."""
    cleaned = text_reply.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    items = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        try:
            qty = float(entry.get("qty", 1) or 1)
        except (TypeError, ValueError):
            qty = 1
        try:
            price = float(entry.get("price", 0) or 0)
        except (TypeError, ValueError):
            price = 0
        items.append({"name": name, "qty": qty, "price": price})
    return items


def _call_ai_vision(api_key, provider, image_path):
    """يرسل صورة الفاتورة لنموذج الذكاء الاصطناعي ويرجع نص الرد الخام
    (مصفوفة JSON متوقعة).

    ⚠️ كان هذا الملف عنده نسخته الخاصة الكاملة من كود الاتصال بـGemini/
    Anthropic (مكررة تمامًا عن app/ai_vision_helper.py المستخدم بسيرفر
    الموبايل) - وهذا سبب خلل حقيقي: إصلاحات مهمة سوّيناها بـ
    ai_vision_helper.py (إعادة محاولة تلقائية عند ازدحام الموديل 503،
    وتثبيت اسم موديل مستقر بدل alias متقلب) ما كانت تنعكس هنا إطلاقًا،
    فتصوير الفاتورة بسطح المكتب يضل يواجه نفس مشكلة "الموديل مزدحم" حتى
    بعد إصلاحها بالموبايل. الحل الصحيح: نستخدم نفس دوال الاتصال المُصلحة
    من ai_vision_helper.py هنا كمان (بدل تكرار الكود بمكانين قابلين للتباعد
    عن بعض) - نفرق بس ببرومبت الاستخراج (_RECEIPT_AI_PROMPT هنا فيه تعليمات
    أدق لصيغة qty/price اللي يتوقعها _parse_ai_json_items بهذا الملف)."""
    from app.ai_vision_helper import _call_gemini_vision, _call_anthropic_vision, _call_with_retries

    mime, b64_data = _image_to_base64(image_path)
    if provider == "gemini":
        return _call_with_retries(lambda: _call_gemini_vision(api_key, b64_data, mime, prompt=_RECEIPT_AI_PROMPT))
    return _call_with_retries(lambda: _call_anthropic_vision(api_key, b64_data, mime, prompt=_RECEIPT_AI_PROMPT))


class ReceiptAIWorker(QThread):
    """يشغّل طلب قراءة الفاتورة بخيط منفصل حتى ما تتجمد واجهة البرنامج وقت
    انتظار رد الذكاء الاصطناعي (ممكن ياخذ كم ثانية) - وبنفس الخيط نسوي
    المطابقة المحلية مع المخزون + خطوة التحقق النهائي من الذكاء الاصطناعي
    للحالات الغامضة (نداء شبكة إضافي، لازم يضل بخيط منفصل هو الثاني حتى ما
    يجمّد الواجهة). قائمة المنتجات (`products`) لازم تنجلب بالخيط الرئيسي
    *قبل* إنشاء هذا الكائن (SQLAlchemy session مو آمنة للاستخدام من خيط
    ثاني) - نمررها كقائمة tuples عادية جاهزة. نفس الشي لذاكرة التصحيحات
    السابقة (`memory_lookup`) - راجع InvoiceTextMapping بملف models.py."""
    finished_ok = Signal(list)
    finished_error = Signal(str)

    def __init__(self, api_key, provider, image_path, products, memory_lookup=None):
        super().__init__()
        self.api_key = api_key
        self.provider = provider
        self.image_path = image_path
        self.products = products
        self.memory_lookup = memory_lookup or {}

    def run(self):
        try:
            reply_text = _call_ai_vision(self.api_key, self.provider, self.image_path)
            items = _parse_ai_json_items(reply_text)
            results = _match_items_with_ai_verification(
                self.api_key, self.provider, items, self.products, self.memory_lookup,
            )
            self.finished_ok.emit(results)
        except Exception as e:
            self.finished_error.emit(str(e))


# --- مطابقة اسم دواء متسامحة (تحويل صوتي إنكليزي→عربي + تشابه نصي +
# قاعدة صارمة لمنع خلط جرعات/أشكال صيدلانية مختلفة) ------------------
# ⚠️ هذا المنطق انتقل لملف مشترك مستقل app/text_match.py (نفس المنطق،
# بالإضافة لقاعدة تعارض الجرعة/الشكل الصيدلاني الجديدة) حتى يصير قابل
# الاستخدام من سيرفر الموبايل بدون ما يحتاج يستورد PySide6 - راجع تعليق
# text_match.py لتفاصيل السبب. نبقي الأسماء القديمة هنا كأغلفة رفيعة حتى
# ما ننكسر أي استيراد موجود (مثلًا app/mobile_server.py يستورد
# _match_product_name مباشرة).

from app.text_match import (
    transliterate_latin_to_arabic as _transliterate_latin_to_arabic,
    token_match_ratio as _token_match_ratio,
    rank_by_similarity as _rank_by_similarity,
    CONFIDENT_MATCH_THRESHOLD as _CONFIDENT_MATCH_THRESHOLD,
    STRONG_MATCH_THRESHOLD,
)


def _match_product_name(name_part, products):
    """يقارن اسم مستخرج من OCR/تصوير بالذكاء الاصطناعي مع قائمة المنتجات
    (بالاسم والاسم العلمي) بعد توحيد الأحرف + تحويل صوتي لو فيه إنكليزي +
    مقارنة بالكلمات لحالها (نفس منطق app.text_match.fuzzy_ratio بالضبط).

    قاعدة صارمة جديدة: نستبعد أي مرشح فيه تعارض واضح بالجرعة/التركيز أو
    الشكل الصيدلاني عن الاسم المستخرج (راجع
    app.text_match.dosage_form_conflicts) - حتى لو تشابه الاسم نصيًا عالي
    جدًا. هذا يمنع بالضبط مشكلة "أوجمنتين 625" يتقارن غلط مع "أوجمنتين 1
    غم" لمجرد إنهم نفس الاسم ويختلفون برقم بس.

    يرجع (product_id لأقرب تطابق, نسبة تشابه من 0 إلى 1). يرجع (None, نسبة)
    لو ماكو شي قريب بشكل كافي عشان نقترحه تلقائيًا."""
    ranked = _rank_by_similarity(name_part, products, limit=1, strict_dosage_form=True)
    if not ranked or ranked[0][2] < _CONFIDENT_MATCH_THRESHOLD:
        return None, ranked[0][2] if ranked else 0.0
    return ranked[0][0], ranked[0][2]


def _match_product_candidates(name_part, products, limit=3, normalized_index=None):
    """نفس _match_product_name بس يرجع أفضل `limit` مرشحين بدل وحد بس -
    [(product_id, name, ratio), ...] (بعد استبعاد أي مرشح فيه تعارض جرعة/
    شكل صيدلاني واضح). يُستخدم لتغذية خطوة التحقق النهائي من الذكاء
    الاصطناعي (راجع app.ai_vision_helper.verify_matches_with_ai) بالحالات
    الغامضة اللي المطابقة النصية المحلية لحالها ما وصلت فيها لقرار مؤكد.

    ⚠️ تحسين أداء مهم: قبل ما نشغّل الحساب المكلف (تحليل جرعة/شكل + تشابه
    نصي تفصيلي) نعمل تصفية أولية سريعة (مقارنة نصوص بسيطة) تختصر مرشحي كل
    صنف من كتالوجك الكامل (ممكن يوصل آلاف الأدوية) لعدد صغير فعليًا قريب
    نصيًا من الاسم المستخرج. بدون هذا، كل صنف بالفاتورة كان يشغّل التحليل
    المكلف على كل دواء بمخزونك - سبب رئيسي لبطء شديد (شبه تجمّد) مع كتالوج
    كبير - فاتورة من 15 صنف كانت تاخذ **قرابة 45 ثانية** بكتالوج 19 ألف
    دواء بالاختبار! مو تخمين تقريبي - أي مرشح فيه احتمال ولو ضعيف يعدّي،
    بس اللي ماله أي علاقة نصية إطلاقًا ينرفض قبل التحليل التفصيلي.

    normalized_index: (اختياري، بس **مهم للسرعة**) قائمة [(pid, name,
    generic, name_norm, generic_norm), ...] محسوبة *مرة وحدة بس* لكل
    الكتالوج قبل ما نبدأ نطابق أصناف الفاتورة (راجع
    _match_items_with_ai_verification) - تجنّبنا نعيد توحيد نفس آلاف
    أسماء الكتالوج من جديد لكل صنف بالفاتورة (كانت التكرار هذا نصف
    سبب البطء تقريبًا). لو ماكو (None)، نبنيها هنا مرة وحدة بس لهذا
    الاستدعاء تحديدًا (أبطأ شوي، بس يشتغل صحيح لأي متصل ما يجهزها)."""
    from app.text_match import _tokenize

    if normalized_index is None:
        normalized_index = [
            (pid, name, generic, normalize_arabic(name), normalize_arabic(generic) if generic else "")
            for pid, name, generic in products
        ]

    norm_query = normalize_arabic(name_part)
    query_tokens = [t for t in _tokenize(norm_query) if len(t) >= 2]
    pool = products
    if query_tokens:
        narrowed = [
            (pid, name, generic) for pid, name, generic, name_norm, generic_norm in normalized_index
            if any(t in name_norm or (generic_norm and t in generic_norm) for t in query_tokens)
        ]
        if narrowed:
            pool = narrowed
    return _rank_by_similarity(name_part, pool, limit=limit, strict_dosage_form=True)


def _match_items_with_ai_verification(api_key, provider, items, products, memory_lookup=None):
    """يطابق كل صنف مستخرج من الفاتورة (items: [{"name","qty","price"}, ...]
    أو [{"name","quantity","unit_price"}, ...]) مع قائمة المنتجات، على 3
    مراحل متدرجة (توفير - ما نستخدم الذكاء الاصطناعي إلا للحالات اللي
    فعلاً تحتاجه):

    1. تطابق نصي شبه مؤكد **وحاسم** (ratio >= STRONG_MATCH_THRESHOLD، وفارق
       واضح عن ثاني أقرب مرشح - راجع _DECISIVE_MARGIN تحت) → نعتمده مباشرة
       بدون أي نداء إضافي.

       ⚠️ ليش "حاسم" شرط لازم، مو بس نسبة عالية: اسم بدون جرعة مذكورة
       (مثلًا "Augmentin" بس بدون رقم) يطلعله نفس النسبة العالية تقريبًا
       (٪94 مثلًا) ضد **كل** جرعات نفس الدواء المسجلة عندك (625 و1000
       ملغم مثلاً) بنفس الوقت - لأنه أصلاً ما فيه رقم جرعة نقارنه أساسًا.
       لو اعتمدنا بس "النسبة عالية" بدون تحقق من وجود فارق واضح عن باقي
       المرشحين، كنا نختار أي وحدة منهم بشكل شبه عشوائي (أول وحدة بالترتيب)
       بثقة زائفة 94% - بالضبط نوع الخطأ اللي نحاول نمنعه. لو النسبة عالية
       بس المرشحين متقاربين (يعني الاسم أصلاً ما يميّز بينهم)، هذا "غموض
       حقيقي" ولازم يوصل لخطوة 3 (تحقق الذكاء الاصطناعي)، مو "تطابق مؤكد".
    2. ماكو أي مرشح قريب بشكل كافي (ratio < CONFIDENT_MATCH_THRESHOLD أو
       ماكو مرشحين إطلاقًا) → "ماكو تطابق"، بدون نداء إضافي.
    3. الحالات "الغامضة" بالنص (تشابه معقول بس مو حاسم، شامل حالة الفارق
       الضعيف بالخطوة 1 فوق) → نجمعهم كلهم بنداء ذكاء اصطناعي واحد (batch)
       يتحقق فعليًا هل نفس الدواء أو لا (فهم لغوي حقيقي، مو تشابه شكل حروف)
       - راجع app.ai_vision_helper.verify_matches_with_ai.

    يرجع قائمة dict فيها لكل صنف: raw/name_guess/qty/price/matched_id/
    confidence/ai_verified - بنفس الشكل اللي يتوقعه ReceiptReviewDialog
    و/api/scan-invoice بالضبط.

    memory_lookup: dict اختياري {نص_موحّد: product_id} - "ذاكرة" تصحيحات
    سابقة (راجع app.db.models.InvoiceTextMapping) - أي نص يطابقه *حرفيًا
    بعد توحيد الأحرف* يُعتمد فورًا بثقة 100% بدون أي تخمين نصي ولا نداء
    ذكاء اصطناعي إطلاقًا (تصحيح المستخدم بنفسه مرة وحدة أوثق من أي تخمين
    algorithmy - نفس المورد يستخدم عادةً نفس صيغة الفاتورة كل مرة، فهذا
    يخلي البرنامج "يتعلم" فواتير مورديك المتكررة تدريجيًا). ما نمرر session
    هنا عمدًا (الدالة نفسها تُستدعى أحيانًا من خيط ثاني - راجع
    ReceiptAIWorker - وSQLAlchemy session مو آمنة عبر الخيوط) - المتصل
    (caller) هو اللي يجيب البيانات من قاعدة البيانات بخيطه الآمن ويمررها
    كـdict عادي جاهز."""
    from app.ai_vision_helper import verify_matches_with_ai
    from app.text_match import normalize_arabic
    memory_lookup = memory_lookup or {}

    # ⚠️ تحسين أداء جوهري: نطبّع أسماء الكتالوج كامل *مرة وحدة بس* هنا (قبل
    # حلقة أصناف الفاتورة)، مو داخلها. كتالوج كبير (آلاف الأدوية) كان يتوحّد
    # من جديد بكل صنف بالفاتورة - يعني لو الفاتورة فيها 15 صنف، نفس آلاف
    # الأسماء تتوحّد 15 مرة بدل مرة وحدة! هذا التكرار (مع تحليل الجرعة/الشكل
    # المكلف) كان السبب الرئيسي وراء تجمّد قراءة الفاتورة بكتالوج كبير -
    # فاتورة 15 صنف كانت تاخذ ~45 ثانية بالاختبار، هذا التحسين ينزلها بشكل
    # كبير جدًا (نفس العمل المكلف يصير مرة وحدة لكل الفاتورة، مو لكل صنف).
    normalized_index = [
        (pid, name, generic, normalize_arabic(name), normalize_arabic(generic) if generic else "")
        for pid, name, generic in products
    ]

    # الفارق الأدنى المطلوب بين أفضل مرشح وثاني أفضل مرشح حتى نعتبر التطابق
    # "حاسم" (نثق فيه محليًا بدون تحقق إضافي) - لو المرشحين متقاربين بهذا
    # القدر، يعتبر غموض حقيقي حتى لو نسبتهم عالية بالمطلق.
    _DECISIVE_MARGIN = 0.05

    parsed_lines = []
    ambiguous_indexes = []
    for item in items:
        name = item.get("name", "")
        qty = item.get("qty", item.get("quantity", 0))
        price = item.get("price", item.get("unit_price", 0))

        # المرحلة صفر (قبل أي تخمين): هل هذا النص بالضبط اتصحح يدويًا قبل
        # كذا؟ لو إي، نعتمده فورًا 100% - أوثق من أي تخمين نصي أو حتى تحقق
        # ذكاء اصطناعي، ونوفر النداء كله.
        remembered_id = memory_lookup.get(normalize_arabic(name))
        if remembered_id is not None:
            parsed_lines.append({
                "raw": name, "name_guess": name, "qty": qty, "price": price,
                "matched_id": remembered_id, "confidence": 1.0, "ai_verified": False,
                "from_memory": True, "_candidates": [],
            })
            continue

        candidates = _match_product_candidates(name, products, limit=3, normalized_index=normalized_index)
        top_id = candidates[0][0] if candidates else None
        top_name = candidates[0][1] if candidates else None
        top_ratio = candidates[0][2] if candidates else 0.0
        second_ratio = candidates[1][2] if len(candidates) > 1 else 0.0
        # ⚠️ حالة خاصة لازم تسبق فحص الفارق: تطابق حرفي كامل بعد توحيد
        # الأحرف (مثلاً النص المستخرج "بانادول" يساوي بالضبط اسم منتج
        # "بانادول" المسجل عندك) يعتبر حاسم دائمًا، حتى لو مرشح ثاني قريب
        # منه بالنسبة (مثلاً "بانادول اكسترا" - نفس الكلمة الأولى بالضبط،
        # فتطلعله نفس نسبة التشابه العالية عبر مقارنة الكلمات، بس هو منتج
        # مختلف فعليًا). التطابق الحرفي الكامل مع اسم منتج حقيقي أقوى دليل
        # ممكن نوصله محليًا - ما يحتاج فارق نسبة عن مرشح ثاني يشبهه بالاسم.
        is_exact = bool(top_name) and normalize_arabic(top_name) == normalize_arabic(name)
        is_decisive = top_ratio >= STRONG_MATCH_THRESHOLD and (
            is_exact or (top_ratio - second_ratio) >= _DECISIVE_MARGIN
        )

        line = {
            "raw": name, "name_guess": name, "qty": qty, "price": price,
            "matched_id": None, "confidence": top_ratio, "ai_verified": False,
            "from_memory": False, "_candidates": candidates,
        }
        if is_decisive:
            line["matched_id"] = top_id
        elif top_ratio >= _CONFIDENT_MATCH_THRESHOLD:
            ambiguous_indexes.append(len(parsed_lines))
        parsed_lines.append(line)

    if ambiguous_indexes and api_key:
        batch = [
            {
                "query": parsed_lines[i]["raw"],
                "candidates": [{"id": pid, "name": pname} for pid, pname, _ in parsed_lines[i]["_candidates"]],
            }
            for i in ambiguous_indexes
        ]
        chosen_ids = verify_matches_with_ai(api_key, provider, batch)
        for i, chosen_id in zip(ambiguous_indexes, chosen_ids):
            parsed_lines[i]["matched_id"] = chosen_id
            parsed_lines[i]["ai_verified"] = True
            if chosen_id is not None:
                parsed_lines[i]["confidence"] = 1.0

    for line in parsed_lines:
        del line["_candidates"]
    return parsed_lines


class ReceiptReviewDialog(QDialog):
    """جدول مراجعة الأصناف المستخرجة من صورة الفاتورة قبل ما تنضاف لسلة
    الشراء بالأسفل. هذا الكلاس ما يلمس قاعدة البيانات إطلاقًا (غير إضافة دواء
    جديد لو طلبتها بنفسك من نفس الجدول) - فقط يرجع قائمة أصناف جاهزة تنضاف
    لـ self.cart بنفس الشكل تمامًا اللي تنضاف بيه أصناف الإدخال اليدوي، وما
    شي يدخل فعليًا للمخزون إلا بعد ما تضغط "تأكيد الاستلام" الأصلي بالشاشة
    الرئيسية."""

    def __init__(self, parsed_lines, products, session, default_expiry, parent=None):
        super().__init__(parent)
        self.session = session
        self.default_expiry = default_expiry
        self._products_cache = products  # [(id, name, generic_name), ...]
        self.setWindowTitle("مراجعة أصناف الفاتورة المصوّرة")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumSize(780, 480)

        layout = QVBoxLayout(self)
        info = QLabel(
            "هذا تخمين آلي من الصورة ومو مضمون 100% - راجع كل صنف قبل ما يضاف: "
            "تأكد من الدواء المطابق والكمية والسعر، وشيل ✓ عن أي سطر غلط "
            "(ضوضاء OCR) أو مو منتج فعلي. الأسطر الملوّنة بالأحمر ماكو دواء "
            "قريب إلها بقائمتك - إما اختار الدواء يدويًا أو ضيفه كدواء جديد."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#6B7280;")
        layout.addWidget(info)

        self.table = QTableWidget()
        enable_touch_scroll(self.table)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["✓", "النص المستخرج من الصورة", "الدواء المطابق", "الكمية (باكيت)", "سعر شراء الباكيت", ""]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(320)
        layout.addWidget(self.table)

        self._rows_meta = []  # [{"raw": str}, ...] بنفس ترتيب صفوف الجدول
        self._build_rows(parsed_lines)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("إلغاء")
        cancel_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:8px 16px;")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = QPushButton("إضافة الأصناف المحددة لسلة الفاتورة")
        confirm_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px 16px;font-weight:bold;")
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)

    def _build_products_combo(self, current_product_id=None):
        combo = QComboBox()
        disable_scroll(combo)
        combo.addItem("— بدون تطابق / تجاهل —", None)
        for pid, pname, _ in self._products_cache:
            combo.addItem(pname, pid)
        if current_product_id is not None:
            idx = combo.findData(current_product_id)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        return combo

    def _build_rows(self, parsed_lines):
        self.table.setRowCount(len(parsed_lines))
        for row, line in enumerate(parsed_lines):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            auto_check = line["matched_id"] is not None and line["confidence"] >= 0.72
            check_item.setCheckState(Qt.Checked if auto_check else Qt.Unchecked)
            self.table.setItem(row, 0, check_item)

            raw_item = QTableWidgetItem(("🧠 " if line.get("from_memory") else "") + line["raw"])
            raw_item.setFlags(Qt.ItemIsEnabled)
            if line.get("from_memory"):
                raw_item.setForeground(Qt.darkGreen)
                raw_item.setToolTip("متطابق من ذاكرة تصحيحات سابقة - اتصحح يدويًا قبل كذا لنفس النص بالضبط")
            elif line["confidence"] >= 0.72:
                raw_item.setForeground(Qt.darkGreen)
            elif line["confidence"] >= 0.35:
                raw_item.setForeground(Qt.darkYellow)
            else:
                raw_item.setForeground(Qt.red)
            self.table.setItem(row, 1, raw_item)

            combo = self._build_products_combo(line["matched_id"])
            self.table.setCellWidget(row, 2, combo)

            qty_input = NumberLineEdit(decimals=2)
            qty_input.set_value(line["qty"])
            self.table.setCellWidget(row, 3, qty_input)

            price_input = NumberLineEdit()
            price_input.set_value(line["price"])
            self.table.setCellWidget(row, 4, price_input)

            new_btn = QPushButton("+ دواء جديد")
            new_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:6px;padding:4px 8px;")
            new_btn.clicked.connect(lambda _, i=row: self._add_new_product_for_row(i))
            self.table.setCellWidget(row, 5, new_btn)

            self._rows_meta.append({"raw": line["raw"], "name_guess": line["name_guess"]})
        self.table.resizeRowsToContents()

    def _add_new_product_for_row(self, row):
        dialog = AddProductDialog(self)
        dialog.name_input.setText(self._rows_meta[row]["name_guess"])
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.get_data()
        if not data["name"]:
            QMessageBox.warning(self, "تنبيه", "لازم تدخل اسم الدواء.")
            return
        product = Product(
            name=data["name"], generic_name=data["generic_name"],
            manufacturer=data["manufacturer"], category=data["category"],
            barcode=data["barcode"], base_unit="شريط", is_custom=True,
            sale_price=data["sale_price"], wholesale_price=data["wholesale_price"],
            carton_price=data["carton_price"], min_stock_threshold=data["min_threshold"],
            strips_per_carton=data["strips_per_carton"],
        )
        self.session.add(product)
        self.session.flush()
        for unit_name, factor in [("شريط", 1), ("علبة", data["strips_per_carton"])]:
            self.session.add(ProductUnit(product_id=product.id, unit_name=unit_name, conversion_factor=factor))
        self.session.commit()

        self._products_cache.append((product.id, product.name, data["generic_name"]))
        combo = self._build_products_combo(product.id)
        self.table.setCellWidget(row, 2, combo)
        self.table.item(row, 0).setCheckState(Qt.Checked)
        if data["qty_cartons"]:
            self.table.cellWidget(row, 3).set_value(data["qty_cartons"])
        if data["carton_cost"]:
            self.table.cellWidget(row, 4).set_value(data["carton_cost"])

    def get_selected_items(self):
        """يرجع قائمة أصناف جاهزة تنضاف لسلة الشراء - فقط الأسطر المؤشرة ✓
        وعندها دواء مطابق فعلي محدد بالقائمة.

        بنفس الوقت نحفظ/نحدّث "ذاكرة" المطابقة (InvoiceTextMapping) لكل
        سطر مؤكد - النص الخام المستخرج من الصورة ↔ الدواء اللي انتهيتِ
        عليه فعليًا (سواء انطابق تلقائي أو صحّحتيه يدويًا بنفسك). المرة
        الجاية نفس النص بالضبط (نفس المورد غالبًا يبعت نفس صيغة الفاتورة)
        ينطابق فورًا بدون أي تخمين."""
        result = []
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            if check_item.checkState() != Qt.Checked:
                continue
            combo = self.table.cellWidget(row, 2)
            product_id = combo.currentData()
            if product_id is None:
                continue
            qty = self.table.cellWidget(row, 3).value() or 1
            price = self.table.cellWidget(row, 4).value()
            product = self.session.query(Product).get(product_id)
            result.append({
                "product_id": product_id,
                "name": product.name if product else combo.currentText(),
                "qty": qty,
                "unit_cost": price,
                "expiry": self.default_expiry,
            })

            raw_text = self._rows_meta[row]["raw"] if row < len(self._rows_meta) else ""
            norm = normalize_arabic(raw_text)
            if norm:
                existing = self.session.query(InvoiceTextMapping).filter_by(normalized_text=norm).first()
                if existing:
                    existing.product_id = product_id
                else:
                    self.session.add(InvoiceTextMapping(normalized_text=norm, product_id=product_id))
        if result:
            self.session.commit()
        return result


class PurchaseView(QWidget):
    # تقسيم لصفحات (Pagination) لسجل فواتير الشراء - نفس فكرة وأسلوب
    # المخزون (InventoryView.PAGE_SIZE) بالضبط: مع كثرة فواتير الشراء
    # المتراكمة عبر الوقت (سجل بلا سقف طبيعي، يكبر باستمرار)، كان
    # _refresh_invoices_table يجيب *كل* فاتورة شراء موجودة منذ إنشاء
    # البرنامج بأكمله بكل مرة (بدون أي حد)، ويتكرر هذا عند كل فتح لتبويب
    # المشتريات وكل حفظ فاتورة جديدة - راجع تقرير التدقيق للتفاصيل.
    INVOICES_PAGE_SIZE = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = get_session()
        self.cart = []  # [{product_id, name, qty, unit_cost}]
        self.receipt_image_path = None
        self._invoice_page = 1
        self._invoice_total_pages = 1

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        enable_touch_scroll(scroll)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        title = QLabel("المشتريات")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        layout.addWidget(title)

        # --- المورد ---
        supplier_row = QHBoxLayout()
        supplier_row.addWidget(QLabel("المورد:"))
        self.supplier_combo = QComboBox()
        self.supplier_combo.setEditable(True)
        self.supplier_combo.setInsertPolicy(QComboBox.NoInsert)
        # بحث بالكتابة مع اقتراحات (بدل قائمة منسدلة تدورين فيها) - نفس
        # فكرة خانة بحث الدواء بالضبط، بس أبسط: عدد الموردين محدود ومحمّل
        # كامل بالخانة أصلًا، فيكفي مكمّل Qt جاهز (QCompleter) بدون حاجة
        # لبحث حي بقاعدة البيانات كل ضغطة حرف زي الدواء (كتالوجه أكبر بكثير).
        supplier_completer = QCompleter(self.supplier_combo.model(), self.supplier_combo)
        supplier_completer.setCaseSensitivity(Qt.CaseInsensitive)
        supplier_completer.setFilterMode(Qt.MatchContains)
        supplier_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.supplier_combo.setCompleter(supplier_completer)
        self._load_suppliers()
        disable_scroll(self.supplier_combo)
        # يحفظ آخر مورد تختارينه هنا (بقاعدة البيانات، يضل حتى لو رجعتِ
        # للبرنامج بجلسة جديدة كاملة) - المرة الجاية اللي تفتحين فيها فاتورة
        # شراء جديدة، نفس المورد يبين مسبقًا تلقائيًا بدل "بدون مورد محدد".
        # هذا افتراضي بس - تقدرين تغيّرينه أو ترجعينه لـ"بدون مورد" ساعة
        # ما تريدين، ونحفظ اختيارك الجديد فورًا.
        self.supplier_combo.currentIndexChanged.connect(self._on_supplier_combo_changed)
        supplier_row.addWidget(self.supplier_combo, stretch=1)
        add_supplier_btn = QPushButton("+ مورد جديد")
        add_supplier_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 12px;")
        add_supplier_btn.clicked.connect(self.add_supplier)
        supplier_row.addWidget(add_supplier_btn)
        layout.addLayout(supplier_row)

        # --- رقم وصل الاستلام (اختياري) - يغطي كل أصناف هذي الفاتورة/الطلبية
        # + تاريخ الوصل (تلقائي بتاريخ اليوم، قابل للتعديل) ---
        receipt_row = QHBoxLayout()
        receipt_row.addWidget(QLabel("رقم الوصل (اختياري):"))
        self.receipt_number_input = QLineEdit()
        self.receipt_number_input.setPlaceholderText("رقم وصل استلام البضاعة من المورد إن وجد...")
        receipt_row.addWidget(self.receipt_number_input, stretch=1)
        receipt_row.addWidget(QLabel("تاريخ الوصل:"))
        self.order_date_input = QDateEdit(QDate.currentDate())
        self.order_date_input.setCalendarPopup(True)
        self.order_date_input.setDisplayFormat("yyyy-MM-dd")
        receipt_row.addWidget(self.order_date_input)
        layout.addLayout(receipt_row)

        # --- إضافة عن طريق الباركود مباشرة ---
        # (شيلت هذا الصف المنفصل - صار البحث بالاسم والباركود مدمجين بنفس
        # الخانة تحت "الدواء:" بقسم "إضافة صنف يدويًا"، راجع تعليق
        # product_search_input هناك لتفاصيل الدمج).

        # --- تصوير الفاتورة ---
        ocr_row = QHBoxLayout()
        self.ocr_btn = QPushButton("تصوير / رفع فاتورة الشراء")
        self.ocr_btn.setIcon(icon("camera", color="white", size=15))
        self.ocr_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px 14px;")
        self.ocr_btn.clicked.connect(self.capture_receipt)
        self.receipt_label = QLabel("ماكو صورة مرفوعة")
        self.receipt_label.setStyleSheet("color:#6B7280;")
        ocr_row.addWidget(self.ocr_btn)
        ocr_row.addWidget(self.receipt_label, stretch=1)
        layout.addLayout(ocr_row)

        self.ocr_text = QTextEdit()
        self.ocr_text.setPlaceholderText("حالة تحليل الفاتورة بالذكاء الاصطناعي راح تظهر هنا...")
        self.ocr_text.setFixedHeight(90)
        self.ocr_text.setReadOnly(True)
        layout.addWidget(self.ocr_text)

        # --- إضافة صنف يدويًا ---
        # كانت كل الحقول (الدواء/الكمية/السعر/الصلاحية/الزر) بسطر أفقي واحد -
        # على شاشات أصغر هذا يخلي عرض السطر يتجاوز عرض الشاشة، فيفرض شريط
        # تمرير أفقي على الصفحة كاملة. وزّعناها الحين على 3 أسطر بدل سطر
        # وحد عشان الصفحة تضل بعرض الشاشة مهما كان حجمها.
        add_row = QFrame()
        add_row.setStyleSheet("background:white;border:1px solid #E5E7EB;border-radius:10px;padding:10px;")
        add_layout = QVBoxLayout(add_row)

        self.product_search_input = QLineEdit()
        # ⚠️ إعادة بناء جذرية (مو ترقيع) - بعد 3 أخطاء متتالية من نفس
        # المصدر (قفزة المؤشر، اختفاء الكتابة، الاختيار التلقائي لأول
        # نتيجة)، تبيّن إن استخدام QComboBox قابل للتعديل كخانة بحث حي هو
        # نفسه المشكلة الجذرية - الودجت مصمم أصلًا لسيناريو "اختاري من
        # قائمة" مو "اكتبي نص حر مع اقتراحات منفصلة معه". الحل الصحيح:
        # خانة كتابة عادية (QLineEdit) + قائمة اقتراحات منفصلة تمامًا
        # (self.product_suggestions_list تحت) - نفس فلسفة بحث الدواء
        # بالموبايل بالضبط (خانة + قائمة div منفصلة تحتها)، اللي ما واجهت
        # ولا وحدة من هالمشاكل الثلاث لأنها مبنية بهذا الفصل من الأساس.
        # "المكتوب حاليًا" و"المختار فعليًا" صاروا حالتين منفصلتين تمامًا
        # (self.product_search_input.text() مقابل self._selected_product_id) -
        # ما يصير فيهم خلط أبدًا.
        #
        # خانة موحّدة للبحث بالاسم أو مسح الباركود مع بعض: تكتب اسم فتطلع
        # اقتراحات، أو تمسح باركود (يطلع اكتشاف تلقائي بعد وقفة الكتابة).
        #
        # مهم: اختيار الدواء من قائمة الاقتراحات (نقرة أو أسهم+إنتر) بس
        # يعبّي الخانة بالدواء المختار - ما يضيفه للفاتورة مباشرة. الإضافة
        # الفعلية تصير بس بعد ما يكتب المستخدم الكمية والسعر ويضغط إنتر
        # (بأي من الحقول الثلاثة) أو زر "+ أضف للفاتورة" - وقتها بس تنمسح
        # خانة البحث تلقائيًا جاهزة للدواء الجاي (راجع _add_selected_product).
        self._selected_product_id = None
        self._selected_product_name = None
        self.product_search_input.setPlaceholderText("اكتب اسم الدواء أو امسح الباركود...")
        self.product_search_input.textEdited.connect(self._on_search_text_edited)
        self.product_search_input.returnPressed.connect(self._on_search_return_pressed)
        self.product_search_input.installEventFilter(self)

        self.product_suggestions_list = QListWidget()
        self.product_suggestions_list.setMaximumHeight(160)
        self.product_suggestions_list.setStyleSheet(
            "QListWidget{border:1px solid #CBD5E1;border-radius:8px;background:white;}"
            "QListWidget::item{padding:6px 8px;}"
            "QListWidget::item:selected{background:#DCFCE7;color:#14532D;}"
        )
        self.product_suggestions_list.itemClicked.connect(self._on_suggestion_clicked)
        self.product_suggestions_list.setVisible(False)

        self._product_search_timer = QTimer(self)
        self._product_search_timer.setSingleShot(True)
        self._product_search_timer.timeout.connect(self._run_product_search)
        self._barcode_timer = QTimer(self)
        self._barcode_timer.setSingleShot(True)
        self._barcode_timer.timeout.connect(self._auto_barcode_scan)
        self._preload_products(limit=30)
        self.qty_input = NumberLineEdit(decimals=2, placeholder="1")
        self.bonus_input = NumberLineEdit(decimals=2, placeholder="0")
        self.cost_input = NumberLineEdit(placeholder="0")
        # سلسلة إنتر طبيعية: تختار الدواء (إنتر بخانة البحث يوصّل الفوكَس
        # لخانة الكمية بدون ما يضيف لسا) → تكتب الكمية (إنتر يوصّل لخانة
        # الهدية) → تكتب الهدية إن وجدت أو تتخطاها بإنتر فاضية (توصّل
        # لخانة السعر) → تكتب السعر (إنتر هنا بس يضيف فعليًا للفاتورة -
        # نفس أثر زر "+ أضف للفاتورة"). هذا يضمن الإضافة ما تصير إلا بعد
        # ما تنكتب الكمية والسعر فعلًا، بالضبط الطلب.
        self.qty_input.returnPressed.connect(lambda: self.bonus_input.setFocus())
        self.bonus_input.returnPressed.connect(lambda: self.cost_input.setFocus())
        self.cost_input.returnPressed.connect(self.add_item)
        self.item_expiry_input = QDateEdit(QDate.currentDate().addYears(1))
        self.item_expiry_input.setCalendarPopup(True)
        disable_scroll(self.item_expiry_input)
        add_btn = QPushButton("+ أضف للفاتورة")
        add_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px 14px;")
        add_btn.clicked.connect(self.add_item)
        new_drug_btn = QPushButton("+ دواء جديد")
        new_drug_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:8px 12px;")
        new_drug_btn.clicked.connect(self.add_new_drug)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("الدواء:"))
        row1.addWidget(self.product_search_input, stretch=1)
        row1.addWidget(new_drug_btn)
        add_layout.addLayout(row1)
        add_layout.addWidget(self.product_suggestions_list)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("الكمية (بالباكيت):"))
        row2.addWidget(self.qty_input, stretch=1)
        row2.addWidget(QLabel("هدية/بونص (بالباكيت):"))
        row2.addWidget(self.bonus_input, stretch=1)
        row2.addWidget(QLabel("سعر شراء الباكيت:"))
        row2.addWidget(self.cost_input, stretch=1)
        add_layout.addLayout(row2)

        # حقل سعر شراء إضافي بالدولار - يفيد بأدوية تُشترى بالدولار (يحوّل
        # تلقائيًا لسعر بالدينار حسب سعر الصرف المحفوظ بالإعدادات ويعبّي
        # self.cost_input بالنتيجة، فتخزين السعر الفعلي بالفاتورة يضل
        # بالدينار دائمًا زي ما كان - راجع app/ui/widgets.py:create_usd_price_row).
        usd_rate = get_usd_rate(self.session)
        row2b = QHBoxLayout()
        row2b.addWidget(QLabel("أو سعرها بالدولار:"))
        usd_row, self._item_usd_input = create_usd_price_row(self.cost_input, usd_rate)
        row2b.addWidget(usd_row, stretch=1)
        add_layout.addLayout(row2b)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("الصلاحية:"))
        row3.addWidget(self.item_expiry_input, stretch=1)
        row3.addStretch()
        row3.addWidget(add_btn)
        add_layout.addLayout(row3)

        layout.addWidget(add_row)

        # --- جدول الأصناف بالفاتورة الحالية ---
        self.table = QTableWidget()
        enable_touch_scroll(self.table)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["الدواء", "الكمية (باكيت)", "سعر شراء الباكيت", "الصلاحية", ""])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(220)
        layout.addWidget(self.table)

        bottom_row = QHBoxLayout()
        self.expiry_input = QDateEdit(QDate.currentDate().addYears(1))
        self.expiry_input.setCalendarPopup(True)
        disable_scroll(self.expiry_input)
        bottom_row.addWidget(QLabel("تاريخ الصلاحية الافتراضي (لو ما غيرته لصنف معين بالجدول):"))
        bottom_row.addWidget(self.expiry_input)
        bottom_row.addStretch()
        confirm_btn = QPushButton("تأكيد الاستلام وإضافة للمخزون")
        confirm_btn.setIcon(icon("check", color="white", size=16))
        confirm_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:10px;padding:10px 18px;font-weight:bold;")
        confirm_btn.clicked.connect(self.confirm_purchase)
        bottom_row.addWidget(confirm_btn)
        layout.addLayout(bottom_row)

        # --- سجل فواتير الشراء (قسم منفصل - للاطلاع/التصفح، ما يؤثر على إنشاء فاتورة جديدة) ---
        invoices_title = QLabel("سجل فواتير الشراء")
        invoices_title.setStyleSheet("font-size:16px;font-weight:bold;margin-top:16px;")
        layout.addWidget(invoices_title)

        invoice_filter_row = QHBoxLayout()
        invoice_filter_row.addWidget(QLabel("عرض فواتير المورد:"))
        self.invoice_filter_combo = QComboBox()
        disable_scroll(self.invoice_filter_combo)
        self.invoice_filter_combo.currentIndexChanged.connect(lambda _index: self._refresh_invoices_table())
        invoice_filter_row.addWidget(self.invoice_filter_combo, stretch=1)
        layout.addLayout(invoice_filter_row)

        self.invoices_table = QTableWidget()
        enable_touch_scroll(self.invoices_table)
        self.invoices_table.setAlternatingRowColors(True)
        self.invoices_table.setColumnCount(7)
        self.invoices_table.setHorizontalHeaderLabels(
            ["رقم الفاتورة", "رقم الوصل", "التاريخ", "المورد", "عدد الأصناف", "المبلغ الإجمالي", "الحالة"]
        )
        # ⚠️ إصلاح مقاس/تناسق الجدول: كانت كل الأعمدة السبعة تاخذ نفس
        # العرض بالضبط (Stretch على الكل) - بغض النظر عن محتواها، فعمود
        # رقم قصير ("#17510") ياخذ نفس عرض عمود اسم مورد طويل ("ادوية
        # بيروت /وكالات")، وهذا يخلي الجدول يبين متباعد وغير متناسق. الحين
        # الأعمدة الرقمية/القصيرة تاخذ بس المساحة اللي تحتاجها فعليًا،
        # وعمود "المورد" (المتغيّر بالطول) ياخذ المساحة المتبقية.
        header = self.invoices_table.horizontalHeader()
        for col in (0, 1, 2, 4, 5, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.invoices_table.setStyleSheet("QTableWidget{font-size:13px;} QHeaderView::section{font-size:13px;font-weight:700;}")
        self.invoices_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.invoices_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.invoices_table.setMinimumHeight(220)
        self.invoices_table.cellClicked.connect(self._open_purchase_detail)
        layout.addWidget(self.invoices_table)

        # أزرار تنقل بين صفحات سجل الفواتير (نفس أسلوب المخزون بالضبط)
        invoice_pagination_row = QHBoxLayout()
        self.invoice_prev_page_btn = QPushButton("◀ السابق")
        self.invoice_prev_page_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 14px;")
        self.invoice_prev_page_btn.clicked.connect(self._go_prev_invoice_page)
        self.invoice_page_info_label = QLabel("")
        self.invoice_page_info_label.setAlignment(Qt.AlignCenter)
        self.invoice_page_info_label.setStyleSheet("color:#374151;font-weight:600;")
        self.invoice_next_page_btn = QPushButton("التالي ▶")
        self.invoice_next_page_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 14px;")
        self.invoice_next_page_btn.clicked.connect(self._go_next_invoice_page)
        invoice_pagination_row.addWidget(self.invoice_prev_page_btn)
        invoice_pagination_row.addWidget(self.invoice_page_info_label, stretch=1)
        invoice_pagination_row.addWidget(self.invoice_next_page_btn)
        layout.addLayout(invoice_pagination_row)

        self._load_invoice_filter_suppliers()
        self._refresh_invoices_table()

        scroll.setWidget(content)

        # --- تبويبات قسم المشتريات: "فاتورة شراء جديدة" (كل الشي أعلاه) +
        # "الموردون والحسابات" (بطاقة لكل مورد) + "الهاتف" (رابط/QR الإضافة
        # عن طريق الموبايل - تبويب مستقل تمامًا الحين، مو بطاقة مدمجة داخل
        # تبويب الفاتورة بزر فتح/طي كان موجود سابقًا). ---
        mobile_scroll = QScrollArea()
        enable_touch_scroll(mobile_scroll)
        mobile_scroll.setWidgetResizable(True)
        mobile_scroll.setFrameShape(QFrame.NoFrame)
        mobile_content = QWidget()
        mobile_content_layout = QVBoxLayout(mobile_content)
        mobile_title = QLabel("الإضافة عن طريق الموبايل")
        mobile_title.setStyleSheet("font-size:18px;font-weight:bold;")
        mobile_content_layout.addWidget(mobile_title)
        mobile_content_layout.addWidget(MobileLinkCard())
        mobile_content_layout.addStretch()
        mobile_scroll.setWidget(mobile_content)

        self.tabs = QTabWidget()
        self.tabs.addTab(scroll, "فاتورة شراء جديدة")
        self.accounts_tab = SupplierAccountsTab()
        self.tabs.addTab(self.accounts_tab, "الموردون والحسابات")
        self.tabs.addTab(mobile_scroll, "الهاتف")
        # عند الانتقال لتبويب "الموردون والحسابات" نحدّثه دائمًا - عشان أي
        # فاتورة شراء تأكدت بالتبويب الأول (تغيّر إجمالي مشتريات المورد)
        # تنعكس فورًا بالبطاقات بدون الحاجة لإعادة فتح الشاشة كلها.
        self.tabs.currentChanged.connect(self._on_tab_changed)
        outer_layout.addWidget(self.tabs)

    def _go_prev_invoice_page(self):
        if self._invoice_page > 1:
            self._invoice_page -= 1
            self._refresh_invoices_table(reset_page=False)

    def _go_next_invoice_page(self):
        if self._invoice_page < self._invoice_total_pages:
            self._invoice_page += 1
            self._refresh_invoices_table(reset_page=False)

    def _on_tab_changed(self, index):
        if self.tabs.widget(index) is self.accounts_tab:
            self.accounts_tab.refresh()

    def _preload_products(self, limit=30):
        """تعبئة أولية بسيطة (أول 30 دواء أبجديًا) عشان القائمة ما تفتح فاضية
        تمامًا أول مرة - المستخدم يكتب بعدها ويصير البحث حي (_run_product_search)."""
        products = self.session.query(Product).order_by(Product.name).limit(limit).all()
        self._populate_suggestions(products, show=False)

    def _populate_suggestions(self, products, show=True):
        """يعيد بناء قائمة الاقتراحات المنفصلة بالكامل - آمن 100% (على عكس
        QComboBox.clear() القديم) لأنها ودجت منفصل تمامًا عن خانة الكتابة،
        فما يصير أي تأثير جانبي على النص المكتوب أو موضع المؤشر مهما كانت
        كثافة إعادة البناء."""
        self.product_suggestions_list.clear()
        for p in products:
            item = QListWidgetItem(p.name)
            item.setData(Qt.UserRole, p.id)
            self.product_suggestions_list.addItem(item)
        # احتياط إضافي (مو تكرار الغلطة القديمة): نصرّح صراحة إنه ماكو
        # صف محدد بعد إعادة البناء - حتى لو QListWidget ما عنده نفس مشكلة
        # QComboBox المعروفة (تحديد أول عنصر تلقائيًا)، أفضل نتأكد صراحة
        # مو نعتمد على افتراض سلوك ودجت ثاني بعد اللي صار.
        self.product_suggestions_list.setCurrentRow(-1)
        self.product_suggestions_list.setVisible(show and bool(products))

    def _on_suggestion_clicked(self, item):
        """اختيار دواء من قائمة الاقتراحات (نقرة أو أسهم+إنتر - راجع
        eventFilter) - يعبّي خانة البحث بالاسم المختار وينقل الفوكَس
        لخانة الكمية، بدون أي إضافة فعلية للفاتورة لسا."""
        product_id = item.data(Qt.UserRole)
        product = self.session.query(Product).get(product_id)
        if not product:
            return
        self._select_product(product)

    def eventFilter(self, obj, event):
        """يخلي أسهم فوق/تحت وإنتر تتنقل بقائمة الاقتراحات وأنتِ لسا
        بخانة الكتابة (ماكو داعي تنقلين الفوكَس يدويًا للقائمة) - نفس
        تجربة استخدام QComboBox القديمة، بس بدون أي من مشاكلها."""
        if obj is self.product_search_input and event.type() == QEvent.KeyPress:
            if self.product_suggestions_list.isVisible() and self.product_suggestions_list.count() > 0:
                row = self.product_suggestions_list.currentRow()
                if event.key() == Qt.Key_Down:
                    self.product_suggestions_list.setCurrentRow(min(row + 1, self.product_suggestions_list.count() - 1))
                    return True
                if event.key() == Qt.Key_Up:
                    self.product_suggestions_list.setCurrentRow(max(row - 1, 0))
                    return True
                if event.key() in (Qt.Key_Return, Qt.Key_Enter) and row >= 0:
                    self._on_suggestion_clicked(self.product_suggestions_list.item(row))
                    return True
                if event.key() == Qt.Key_Escape:
                    self.product_suggestions_list.setVisible(False)
                    return True
        return super().eventFilter(obj, event)

    def _on_search_text_edited(self, text):
        """ملاحظة أداء مهمة: كانت _load_products() تجيب *كل* الأدوية من
        قاعدة البيانات وتحطها بالقائمة المنسدلة دفعة وحدة - مع مخزون كبير
        (آلاف الأدوية)، هذا كان يعني تحميل بطيء وقائمة يستحيل تصفّحها يدويًا
        عمليًا. الحين نستنى المستخدم يوقف عن الكتابة (250ms) ثم نستعلم عن
        أقرب 30 نتيجة بس تطابق اللي كتبه - نفس فكرة البحث بأي تطبيق كبير
        (Google، المتاجر الإلكترونية).

        نفس الخانة صارت تكتشف الباركود تلقائيًا كمان: لو النص أرقام بس
        وطويل بشكل يشبه باركود، نستنى وقفة أطول شوي (350ms - نفس مهلة
        ماسح الباركود القديم) ونحاول نطابقه مباشرة، حتى لو الماسح ما
        يرسل Enter تلقائيًا بنهاية القراءة (بعض الماسحات ما ترسل)."""
        # أي كتابة جديدة تلغي أي اختيار سابق - المستخدم يبحث من جديد الحين.
        self._selected_product_id = None
        self._selected_product_name = None
        self._product_search_timer.stop()
        self._barcode_timer.stop()
        stripped = text.strip()
        if not stripped:
            self._preload_products(limit=30)
            self.product_suggestions_list.setVisible(False)
            return
        if stripped.isdigit() and len(stripped) >= 6:
            self._barcode_timer.start(350)
            return
        if len(stripped) >= 2:
            self._product_search_timer.start(250)

    def _run_product_search(self):
        text = self.product_search_input.text().strip()
        if len(text) < 2:
            return
        norm_text = normalize_arabic(text)
        candidates = (
            self.session.query(Product)
            .filter(Product.name.ilike(f"%{text}%"))
            .order_by(Product.name)
            .limit(30)
            .all()
        )
        if not candidates:
            # fallback بسيط للأسماء اللي فيها همزات/تشكيل مختلف - يفحص عدد
            # أكبر شوي من قاعدة البيانات ويقارن بعد تطبيع الحروف بالذاكرة
            wider = self.session.query(Product).order_by(Product.name).limit(500).all()
            candidates = [p for p in wider if norm_text in normalize_arabic(p.name)][:30]

        # قائمة الاقتراحات ودجت منفصل تمامًا عن خانة الكتابة - إعادة بنائها
        # هنا (كل 250ms أثناء الكتابة) ما تلمس نص أو مؤشر product_search_input
        # إطلاقًا، مهما كانت كثافة التحديث. وما نصير محتاجين نأشر أي "اختيار
        # تلقائي" لأول نتيجة أبدًا - القائمة تبين بس كاقتراحات، والاختيار
        # الفعلي (self._selected_product_id) ما يتغيّر إلا بفعل مقصود من
        # المستخدم (نقرة أو أسهم+إنتر - راجع _on_suggestion_clicked وeventFilter).
        self._populate_suggestions(candidates, show=True)

    def _select_product(self, product):
        """يعبّي خانة البحث بالصنف المحدد (بالاسم أو الباركود، ما يفرق) وينقل
        الفوكَس لخانة الكمية - بدون أي إضافة فعلية للفاتورة لسا. هذا المسار
        الموحّد لكل طرق الاختيار (بحث بالاسم أو مسح باركود) - الإضافة
        الفعلية تصير بس بعدين لما يكتب المستخدم الكمية والسعر ويضغط إنتر
        (بخانة السعر) أو زر "+ أضف للفاتورة"."""
        self._selected_product_id = product.id
        self._selected_product_name = product.name
        # setText عادي (مو textEdited) - ما يعيد تشغيل البحث الحي، لأنه
        # مربوط بـ textEdited اللي ينطلق بس بتعديل المستخدم الفعلي للنص،
        # مو بالتغيير البرمجي زي هذا. فرق جوهري عن QComboBox القديمة اللي
        # ما كانت تميّز بين الاثنين.
        self.product_search_input.setText(product.name)
        self.product_suggestions_list.setVisible(False)
        self.qty_input.setFocus()
        self.qty_input.selectAll()

    def _on_search_return_pressed(self):
        """إنتر داخل خانة البحث الموحّدة - يغطي 3 حالات، وكلهن بس يعبّون
        خانة الدواء وينقلون الفوكَس لخانة الكمية (ما يضيفون للفاتورة
        مباشرة - الإضافة الفعلية تصير بس بعد كتابة الكمية والسعر):
        1. أكو صنف محدد فعليًا (نقرة أو أسهم+إنتر من قائمة الاقتراحات).
        2. النص المكتوب يطابق باركود دواء موجود بالضبط.
        3. النص يشبه باركود (أرقام بس) وماكو دواء بيه - نفتح شاشة "دواء
           جديد" مباشرة، وبعد الحفظ نعبّي خانة الدواء بالمنتج الجديد
           (نفس الحالتين فوق بالظبط، مو إضافة مباشرة)."""
        if self._selected_product_id is not None:
            self.qty_input.setFocus()
            self.qty_input.selectAll()
            return

        code = self.product_search_input.text().strip()
        if not code:
            return
        product = self.session.query(Product).filter_by(barcode=code).first()
        if product:
            self._select_product(product)
            return

        if code.isdigit() and len(code) >= 6:
            self._prompt_new_product_for_barcode(code)

    def _auto_barcode_scan(self):
        """نفس _on_search_return_pressed تقريبًا، بس تُستدعى تلقائيًا بعد
        وقفة الكتابة (350ms) لو النص يشبه باركود - تغطي ماسحات الباركود
        اللي ما ترسل Enter تلقائيًا بنهاية القراءة."""
        code = self.product_search_input.text().strip()
        if not code or not code.isdigit():
            return
        product = self.session.query(Product).filter_by(barcode=code).first()
        if product:
            self._select_product(product)
        else:
            self._prompt_new_product_for_barcode(code)

    def _prompt_new_product_for_barcode(self, code):
        """ماكو دواء بهذا الباركود - نفتح شاشة "دواء جديد" مباشرة مع تعبئة
        الباركود مسبقًا، وبمجرد ما يحفظ، نعبّي خانة الدواء بالمنتج
        الجديد (نفس سلوك اختيار دواء موجود بالضبط - ما يضيفه للفاتورة
        مباشرة، لازم يكتب الكمية والسعر أول)."""
        QMessageBox.information(self, "دواء جديد", "ماكو دواء بهذا الباركود - راح تفتح شاشة إضافة دواء جديد.")
        dialog = AddProductDialog(self)
        dialog.barcode_input.setText(code)
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.get_data()
        product = Product(
            name=data["name"], generic_name=data["generic_name"],
            manufacturer=data["manufacturer"], category=data["category"],
            barcode=data["barcode"] or code, base_unit="شريط", is_custom=True,
            sale_price=data["sale_price"], wholesale_price=data["wholesale_price"],
            carton_price=data["carton_price"], min_stock_threshold=data["min_threshold"],
            strips_per_carton=data["strips_per_carton"],
        )
        self.session.add(product)
        self.session.flush()
        for unit_name, factor in [("شريط", 1), ("علبة", data["strips_per_carton"])]:
            self.session.add(ProductUnit(product_id=product.id, unit_name=unit_name, conversion_factor=factor))
        self.session.commit()
        self._select_product(product)

    def _add_selected_product(self, product_id):
        """يضيف صنف للفاتورة الحالية (كارت) بالكمية/السعر/الصلاحية
        المكتوبة حاليًا بالحقول (أو الافتراضي 1/0 لو تركها فاضية - نفس
        فكرة مسح الباركود القديمة، الكمية والسعر ينعدّلون بسهولة داخل
        جدول الفاتورة تحت بعدين لو احتاج المستخدم). بعدها يفرّغ خانة
        البحث/اسم الدواء واسم الاختيار تلقائيًا حتى يقدر يدخل الدواء
        الجاي بسرعة بدون ما يحتاج يمسح النص القديم يدويًا بنفسه - بالضبط
        الطلب.

        دعم الهدية/البونص: لو خانة "هدية" مكتوب فيها رقم أكبر من صفر،
        نحسب الكمية الكلية المستلمة (مشتراة + هدية) والسعر الفعلي بعد
        خصم قيمة الهدية - راجع تعليق PurchaseOrderItem.bonus_quantity
        بملف models.py لتفاصيل المعادلة الكاملة بمثال."""
        product = self.session.query(Product).get(product_id)
        if not product:
            return
        original_qty = self.qty_input.value() or 1
        bonus_qty = self.bonus_input.value() or 0
        nominal_price = self.cost_input.value()
        total_qty = original_qty + bonus_qty
        # إجمالي الفاتورة يبقى نفسه دائمًا (الكمية المشتراة × السعر - بدون
        # طرح أي شي)، وبس يتوزّع على الكمية الكلية المستلمة (المشتراة +
        # الهدية) - فيصير السعر الفعلي للوحدة أقل تلقائيًا كل ما زادت
        # الهدية، بدون ما يتغيّر المبلغ الإجمالي المدفوع فعليًا للمورد.
        net_total = original_qty * nominal_price
        effective_unit_cost = (net_total / total_qty) if total_qty else nominal_price

        self.cart.append({
            "product_id": product_id, "name": product.name,
            "qty": total_qty, "unit_cost": effective_unit_cost,
            "original_qty": original_qty, "bonus_qty": bonus_qty, "nominal_price": nominal_price,
            "expiry": self.item_expiry_input.date().toPython(),
        })
        self.qty_input.setText("")
        self.bonus_input.setText("")
        self.cost_input.setText("")
        if hasattr(self, "_item_usd_input"):
            self._item_usd_input.setText("")
        self.render_table()

        self._selected_product_id = None
        self._selected_product_name = None
        self.product_search_input.clear()
        self.product_suggestions_list.setVisible(False)
        self.product_search_input.setFocus()

    def add_item(self):
        """يضيف الصنف الحالي للفاتورة (كمية وسعر مكتوبين حاليًا) - يشتغل
        من زر "+ أضف للفاتورة"، ومن إنتر بخانة السعر (آخر خطوة بسلسلة
        إنتر الطبيعية: اسم → كمية → سعر → إضافة)."""
        product_id = self._selected_product_id
        if product_id is None:
            return
        self._add_selected_product(product_id)

    def _load_suppliers(self):
        self.supplier_combo.blockSignals(True)
        self.supplier_combo.clear()
        self.supplier_combo.addItem("— بدون مورد محدد —", None)
        for s in self.session.query(Supplier).order_by(Supplier.name).all():
            self.supplier_combo.addItem(s.name, s.id)
        # نرجّع آخر مورد كان محفوظ (لو موجود بعده - ممكن انحذف) - راجع
        # تعليق self.supplier_combo.currentIndexChanged بالأعلى.
        saved_id = get_setting(self.session, "purchase_last_supplier_id", "")
        if saved_id:
            try:
                idx = self.supplier_combo.findData(int(saved_id))
            except ValueError:
                idx = -1
            if idx >= 0:
                self.supplier_combo.setCurrentIndex(idx)
        self.supplier_combo.blockSignals(False)

    def _on_supplier_combo_changed(self, _index):
        """يحفظ اختيار المورد الحالي بأعلى فاتورة الشراء الجديدة كإعداد
        دائم - راجع تعليق self.supplier_combo.currentIndexChanged بالأعلى."""
        supplier_id = self.supplier_combo.currentData()
        set_setting(self.session, "purchase_last_supplier_id", str(supplier_id) if supplier_id else "")

    def add_supplier(self):
        dialog = AddSupplierDialog(self)
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if not data["name"]:
                QMessageBox.warning(self, "تنبيه", "لازم تدخل اسم المورد.")
                return
            supplier = Supplier(name=data["name"], phone=data["phone"], address=data["address"])
            self.session.add(supplier)
            self.session.commit()
            self._load_suppliers()
            idx = self.supplier_combo.findData(supplier.id)
            if idx >= 0:
                self.supplier_combo.setCurrentIndex(idx)
            self._load_invoice_filter_suppliers()
            # المورد الجديد ينضاف تلقائيًا كبطاقة بتبويب "الموردون والحسابات".
            if hasattr(self, "accounts_tab"):
                self.accounts_tab.refresh()

    def _load_invoice_filter_suppliers(self):
        """فلتر مستقل خاص بسجل الفواتير - منفصل عن supplier_combo اللي فوق
        (اللي يحدد مورد الفاتورة الجديدة)، حتى ما يتصادمون مع بعض."""
        current = self.invoice_filter_combo.currentData() if self.invoice_filter_combo.count() else "ALL"
        self.invoice_filter_combo.blockSignals(True)
        self.invoice_filter_combo.clear()
        self.invoice_filter_combo.addItem("— كل الموردين —", "ALL")
        for s in self.session.query(Supplier).order_by(Supplier.name).all():
            self.invoice_filter_combo.addItem(s.name, s.id)
        idx = self.invoice_filter_combo.findData(current)
        self.invoice_filter_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.invoice_filter_combo.blockSignals(False)

    def _refresh_invoices_table(self, reset_page=True):
        # ⚠️ إصلاح أداء مهم (راجع تقرير التدقيق): كانت هذي الدالة تجيب *كل*
        # فاتورة شراء موجودة منذ إنشاء البرنامج بلا أي حد (query.all() بدون
        # limit)، مع joinedload(items) يجيب كل صنف بكل فاتورة فقط عشان يعرض
        # len(order.items) كعدّاد - سجل الفواتير ينمو بلا سقف طبيعي مع
        # الزمن، ويتكرر هذا التحميل الكامل عند كل فتح لتبويب المشتريات وكل
        # حفظ فاتورة جديدة. الحين: (أ) ترقيم صفحات حقيقي على مستوى SQL
        # (نفس أسلوب InventoryView بالضبط)، و(ب) عدد أصناف كل فاتورة يُحسب
        # باستعلام تجميع (COUNT ... GROUP BY) بدل تحميل كائنات الأصناف
        # الكاملة - نفس فكرة bulk_order_summaries أدناه بالضبط. شاشة تفاصيل
        # الفاتورة (PurchaseOrderDetailDialog) ما تغيّرت إطلاقًا، وتستمر
        # تحمّل كل الأصناف الكاملة كما هي (تحتاجها فعليًا للتعديل/الحذف).
        if reset_page:
            self._invoice_page = 1

        base_query = self.session.query(PurchaseOrder).options(joinedload(PurchaseOrder.supplier))
        supplier_id = self.invoice_filter_combo.currentData()
        if supplier_id and supplier_id != "ALL":
            base_query = base_query.filter(PurchaseOrder.supplier_id == supplier_id)

        total_count = base_query.count()
        self._invoice_total_pages = max(1, -(-total_count // self.INVOICES_PAGE_SIZE))
        self._invoice_page = max(1, min(self._invoice_page, self._invoice_total_pages))

        orders = (
            base_query.order_by(PurchaseOrder.order_date.desc())
            .offset((self._invoice_page - 1) * self.INVOICES_PAGE_SIZE)
            .limit(self.INVOICES_PAGE_SIZE)
            .all()
        )
        self._invoice_row_ids = [o.id for o in orders]

        # عدد أصناف كل فاتورة معروضة بهذي الصفحة فقط - استعلام تجميع وحد
        # (COUNT ... GROUP BY) بدل تحميل كل كائنات PurchaseOrderItem الكاملة.
        order_ids = [o.id for o in orders]
        items_count_by_order = dict(
            self.session.query(PurchaseOrderItem.purchase_order_id, func.count(PurchaseOrderItem.id))
            .filter(PurchaseOrderItem.purchase_order_id.in_(order_ids))
            .group_by(PurchaseOrderItem.purchase_order_id)
            .all()
        ) if order_ids else {}

        # حساب مجمّع لحالة تسديد/مرتجع كل الفواتير المعروضة دفعة وحدة -
        # بدل استعلامين منفصلين لكل فاتورة لحالها (نفس إصلاح الأداء
        # المطبّق بشاشة حسابات الموردين، هنا كمان حتى ما يصير بطء لو
        # الفلتر "كل الموردين" وعدد الفواتير كبير).
        summaries = bulk_order_summaries(self.session, orders)

        self.invoices_table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            # order.supplier محمّل مسبقًا (joinedload فوق) - وصول مباشر بدون
            # أي استعلام إضافي، بعكس استعلام Supplier المنفصل القديم لكل صف.
            supplier_name = order.supplier.name if order.supplier else "— بدون مورد محدد —"
            date_text = order.order_date.strftime("%Y-%m-%d") if order.order_date else ""

            self.invoices_table.setItem(row, 0, QTableWidgetItem(f"#{order.id}"))
            self.invoices_table.setItem(row, 1, QTableWidgetItem(order.receipt_number or "—"))
            self.invoices_table.setItem(row, 2, QTableWidgetItem(date_text))
            self.invoices_table.setItem(row, 3, QTableWidgetItem(supplier_name))
            self.invoices_table.setItem(row, 4, QTableWidgetItem(str(items_count_by_order.get(order.id, 0))))
            self.invoices_table.setItem(row, 5, QTableWidgetItem(f"{order.total_amount:,.0f}"))

            # حالة التسديد الفعلية (مسدد/تسديد) - أو حالة المرتجع لو
            # الفاتورة انترجعت (كامل/جزئي) - تُحسب وتُعرض بس للفواتير
            # المؤكدة فعليًا (confirmed)، لأن طلبية معلّقة أو مرفوضة مالها
            # معنى "تسديد" أصلاً (مو فاتورة شراء فعلية بعد). لغير المؤكدة،
            # تضل تعرض حالتها الأصلية (pending_review/rejected) زي ما هي.
            if order.status == "confirmed":
                summary = summaries[order.id]
                status_text = summary["status_display"] or "مسدد"
            else:
                status_text = order.status
            status_item = QTableWidgetItem(status_text)
            if status_text.startswith("مسدد"):
                status_item.setForeground(QColor("#15803D"))
            elif status_text.startswith("تسديد"):
                status_item.setForeground(QColor("#DC2626"))
            font = status_item.font()
            font.setBold(True)
            status_item.setFont(font)
            self.invoices_table.setItem(row, 6, status_item)
        self.invoices_table.resizeRowsToContents()
        # ارتفاع الجدول كان مضبوط على رقم ثابت صغير (220 بكسل) يعرض ~3
        # صفوف بس قبل ما يحتاج سكرول داخلي - نحسبه الحين ديناميكيًا حتى
        # يعرض 20 صف بدون سكرول داخلي (الصفحة نفسها فيها سكرول عام أصلًا،
        # فهذا مقبول). نحسب الارتفاع من ارتفاع صف حقيقي فعليًا (يشمل أي
        # فرق بالخط/الحشوة عند المستخدم) بدل رقم ثابت مخمّن.
        visible_rows = min(20, self.invoices_table.rowCount()) or 1
        row_height = self.invoices_table.rowHeight(0) if self.invoices_table.rowCount() else 36
        header_height = self.invoices_table.horizontalHeader().height()
        self.invoices_table.setMinimumHeight(header_height + visible_rows * row_height + 4)

        self.invoice_page_info_label.setText(
            f"صفحة {self._invoice_page} من {self._invoice_total_pages} - إجمالي {total_count} فاتورة"
        )
        self.invoice_prev_page_btn.setEnabled(self._invoice_page > 1)
        self.invoice_next_page_btn.setEnabled(self._invoice_page < self._invoice_total_pages)

    def add_new_drug(self):
        dialog = AddProductDialog(self)
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.get_data()
        if not data["name"]:
            QMessageBox.warning(self, "تنبيه", "لازم تدخل اسم الدواء.")
            return
        product = Product(
            name=data["name"], generic_name=data["generic_name"],
            manufacturer=data["manufacturer"], category=data["category"],
            barcode=data["barcode"], base_unit="شريط", is_custom=True,
            sale_price=data["sale_price"], wholesale_price=data["wholesale_price"],
            carton_price=data["carton_price"], min_stock_threshold=data["min_threshold"],
            strips_per_carton=data["strips_per_carton"],
        )
        self.session.add(product)
        self.session.flush()
        for unit_name, factor in [("شريط", 1), ("علبة", data["strips_per_carton"])]:
            self.session.add(ProductUnit(product_id=product.id, unit_name=unit_name, conversion_factor=factor))
        self.session.commit()
        self._select_product(product)
        if data["qty_cartons"]:
            self.qty_input.set_value(data["qty_cartons"])
        if data["carton_cost"]:
            self.cost_input.set_value(data["carton_cost"])

    def capture_receipt(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختر صورة فاتورة الشراء", "", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return
        self.receipt_image_path = path
        self.receipt_label.setText(path.split("/")[-1].split("\\")[-1])

        api_key = get_setting(self.session, "ai_api_key", "")
        if not api_key:
            self.ocr_text.setPlainText(
                "ماكو مفتاح API محفوظ بعد - روح لشاشة الإعدادات (قسم المستشار "
                "الذكي) وضيف مفتاحك أول حتى تشتغل ميزة قراءة الفاتورة بالذكاء "
                "الاصطناعي.\nبالوقت الحالي، أدخل الأصناف يدويًا بالأسفل وانت "
                "تشوف الصورة."
            )
            return
        provider = get_setting(self.session, "ai_provider", "gemini")

        self.ocr_text.setPlainText("جاري تحليل صورة الفاتورة بالذكاء الاصطناعي... (قد تاخذ كم ثانية)")
        self.ocr_btn.setEnabled(False)

        # نجيب قائمة الأدوية بالخيط الرئيسي *قبل* بدء الخيط الثاني - جلسة
        # SQLAlchemy مو آمنة للاستخدام من خيط ثاني، فنحولها لقائمة tuples
        # عادية (بدون أي ارتباط بالـsession) ونمررها جاهزة. نفس الشي لذاكرة
        # التصحيحات السابقة (InvoiceTextMapping) - dict عادي {نص: product_id}.
        self._receipt_products = [(p.id, p.name, p.generic_name) for p in self.session.query(Product).all()]
        memory_lookup = {
            m.normalized_text: m.product_id
            for m in self.session.query(InvoiceTextMapping).all()
        }

        self._receipt_worker = ReceiptAIWorker(api_key, provider, path, self._receipt_products, memory_lookup)
        self._receipt_worker.finished_ok.connect(self._on_receipt_ai_ok)
        self._receipt_worker.finished_error.connect(self._on_receipt_ai_error)
        self._receipt_worker.start()

    def _on_receipt_ai_ok(self, parsed_lines):
        self.ocr_btn.setEnabled(True)

        if not parsed_lines:
            self.ocr_text.setPlainText(
                "ما قدر الذكاء الاصطناعي يميّز أي صنف واضح بالصورة.\n"
                "جرب صورة أوضح (إضاءة أفضل، بدون انعكاس، الفاتورة كاملة "
                "بالإطار)، أو أدخل الأصناف يدويًا بالأسفل."
            )
            return

        # المطابقة (محلية + تحقق الذكاء الاصطناعي للحالات الغامضة) خلصت
        # أصلًا داخل ReceiptAIWorker نفسه (قبل ما توصل هنا) - كل هذا تخمين
        # للمراجعة بس، ما يدخل شي فعليًا للسلة إلا بعد ما تأكد بجدول
        # المراجعة بالأسفل.
        self.ocr_text.setPlainText(
            f"تم استخراج {len(parsed_lines)} صنف من الصورة - راجعهم بجدول التأكيد."
        )

        dialog = ReceiptReviewDialog(
            parsed_lines, self._receipt_products, self.session,
            self.expiry_input.date().toPython(), self,
        )
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() == QDialog.Accepted:
            new_items = dialog.get_selected_items()
            if new_items:
                self.cart.extend(new_items)
                self.render_table()

    def _on_receipt_ai_error(self, msg):
        self.ocr_btn.setEnabled(True)
        if "HTTP 401" in msg or "HTTP 400" in msg or "authentication" in msg.lower() or "UNAUTHENTICATED" in msg or "API_KEY_INVALID" in msg or "API key not valid" in msg:
            text = f"❌ مفتاح الـ API غير صحيح أو منتهي.\n{msg}"
        elif "HTTP 404" in msg or "not_found" in msg.lower():
            text = f"❌ خطأ بإعدادات الموديل (مشكلة بالكود، خبر المطوّر).\n{msg}"
        elif "getaddrinfo" in msg or "Network is unreachable" in msg or "timed out" in msg:
            text = (
                "❌ ماكو اتصال بالانترنت من داخل البرنامج.\n"
                "تأكد عندك نت شغّال بهذا الجهاز، وجدار حماية ويندوز ما يكون "
                "حاظر بايثون."
            )
        elif "مزدحمة مؤقتًا" in msg:
            # رسالة TransientAIError الجاهزة (راجع app/ai_vision_helper.py) -
            # مو "خطأ غير متوقع"، هذا سبب معروف ومفهوم (ازدحام مؤقت بخادم
            # المزوّد) وجربنا نعيد المحاولة تلقائيًا عدة مرات قبل ما نوصل لهذا.
            text = f"⏳ {msg}"
        else:
            text = f"صار خطأ غير متوقع أثناء تحليل الصورة: {msg}\nأدخل الأصناف يدويًا بالأسفل وانت تشوف الصورة."
        self.ocr_text.setPlainText(text)

    def render_table(self):
        self.table.setRowCount(len(self.cart))
        for row, item in enumerate(self.cart):
            self.table.setItem(row, 0, QTableWidgetItem(item["name"]))

            qty_widget = QWidget()
            qty_layout = QHBoxLayout(qty_widget)
            qty_layout.setContentsMargins(0, 0, 0, 0)
            minus_btn = QPushButton("−")
            minus_btn.setFixedWidth(36)
            minus_btn.setMinimumHeight(34)
            minus_btn.clicked.connect(lambda _, i=row: self._change_qty(i, -1))
            # عرض الكمية: لو أكو هدية مسجّلة بهذا الصنف، نبيّن "الأصلية +
            # هدية N" بدل الرقم الكلي المدموج (11 مثلًا) - بالضبط الطلب:
            # "تذكر الكمية الأصلية + عدد الهدية بشكل مفصول". لو ماكو هدية،
            # يبين الرقم العادي زي ما كان دائمًا.
            bonus_qty = item.get("bonus_qty", 0)
            if bonus_qty:
                qty_text = f"{item.get('original_qty', item['qty'] - bonus_qty):g} + هدية {bonus_qty:g}"
            else:
                qty_text = f"{item['qty']:g}"
            qty_lbl = QLabel(qty_text)
            qty_lbl.setAlignment(Qt.AlignCenter)
            plus_btn = QPushButton("+")
            plus_btn.setFixedWidth(36)
            plus_btn.setMinimumHeight(34)
            plus_btn.clicked.connect(lambda _, i=row: self._change_qty(i, 1))
            qty_layout.addWidget(minus_btn)
            qty_layout.addWidget(qty_lbl)
            qty_layout.addWidget(plus_btn)
            self.table.setCellWidget(row, 1, qty_widget)

            # عمود السعر: نعرض السعر الاسمي (اللي اتفقت عليه فعليًا مع
            # المورد) لو أكو هدية، مو السعر الفعلي المخفّض داخليًا - حتى
            # ما يصير لبس ("ليش السعر تغيّر؟") - السعر الفعلي المخفّض
            # منعكس أصلًا بعمود "الإجمالي" (يطلع أقل من qty×nominal_price).
            display_price = item.get("nominal_price", item["unit_cost"])
            price_item = QTableWidgetItem(f"{display_price:,.0f}")
            if bonus_qty:
                price_item.setToolTip(
                    f"السعر الفعلي بعد خصم قيمة الهدية: {item['unit_cost']:,.0f} للوحدة"
                )
            self.table.setItem(row, 2, price_item)

            # تاريخ صلاحية قابل للتعديل لكل صنف لحاله - مفيد لو أصناف الفاتورة
            # الواحدة عندها تواريخ صلاحية مختلفة عن بعضها
            row_expiry = item.get("expiry") or self.expiry_input.date().toPython()
            expiry_edit = QDateEdit(row_expiry)
            expiry_edit.setCalendarPopup(True)
            disable_scroll(expiry_edit)
            expiry_edit.dateChanged.connect(lambda d, i=row: self._set_item_expiry(i, d))
            self.table.setCellWidget(row, 3, expiry_edit)

            remove_btn = QPushButton("حذف")
            remove_btn.setMinimumHeight(34)
            remove_btn.setStyleSheet("color:#DC2626;border:none;font-weight:700;")
            remove_btn.clicked.connect(lambda _, i=row: self._remove_item(i))
            self.table.setCellWidget(row, 4, remove_btn)
        self.table.resizeRowsToContents()

    def _set_item_expiry(self, idx, qdate):
        if idx < len(self.cart):
            self.cart[idx]["expiry"] = qdate.toPython()

    def _change_qty(self, idx, delta):
        """أزرار +/- بجدول الفاتورة - نعدّل "الكمية الأصلية" (مو الكلية
        مباشرة) ونعيد حساب الكمية الكلية والسعر الفعلي بنفس معادلة
        الهدية (لو أكو)، حتى يضل العرض والمبلغ متّسقين مع بعض دائمًا -
        لصنف بدون هدية، هذا يرجع لنفس السلوك القديم بالضبط (زيادة/تنقيص
        الكمية مباشرة بلا تغيير بالسعر)."""
        item = self.cart[idx]
        bonus_qty = item.get("bonus_qty", 0)
        nominal_price = item.get("nominal_price", item["unit_cost"])
        new_original_qty = max(1, item.get("original_qty", item["qty"] - bonus_qty) + delta)
        new_total_qty = new_original_qty + bonus_qty
        net_total = new_original_qty * nominal_price
        item["original_qty"] = new_original_qty
        item["qty"] = new_total_qty
        item["unit_cost"] = (net_total / new_total_qty) if new_total_qty else nominal_price
        self.render_table()

    def _remove_item(self, idx):
        del self.cart[idx]
        self.render_table()

    def confirm_purchase(self):
        if not self.cart:
            QMessageBox.warning(self, "تنبيه", "ماكو أصناف بالفاتورة بعد.")
            return

        receipt_number = self.receipt_number_input.text().strip() or None

        order = PurchaseOrder(
            supplier_id=self.supplier_combo.currentData(),
            status="confirmed",
            source="تصوير_فاتورة" if self.receipt_image_path else "يدوي",
            receipt_image_path=self.receipt_image_path,
            total_amount=sum(i["qty"] * i["unit_cost"] for i in self.cart),
            receipt_number=receipt_number,
            order_date=self.order_date_input.date().toPython(),
        )
        self.session.add(order)
        self.session.flush()

        default_expiry = self.expiry_input.date().toPython()
        for item in self.cart:
            product = self.session.query(Product).get(item["product_id"])
            spc = (product.strips_per_carton or 3) if product else 3
            # "qty" و"unit_cost" بالسلة مُدخلة بالباكيت (كما يشتري الصيدلي فعليًا) -
            # نحوّلها هنا لوحدة الأساس (شريط) قبل ما نسجلها بالمخزون، لأن كل حسابات
            # المخزون والربح (Batch/StockMovement) مبنية على الشريط.
            base_qty = _strips_from_cartons(item["qty"], spc)
            bonus_qty = item.get("bonus_qty", 0)
            bonus_strip_qty = _strips_from_cartons(bonus_qty, spc) if bonus_qty else 0
            strip_cost = (item["unit_cost"] / spc) if spc else 0
            item_expiry = item.get("expiry") or default_expiry

            self.session.add(PurchaseOrderItem(
                purchase_order_id=order.id, product_id=item["product_id"],
                quantity=item["qty"], unit_cost=item["unit_cost"], bonus_quantity=bonus_qty,
            ))
            batch = Batch(
                product_id=item["product_id"],
                batch_number=f"PO-{order.id}-{item['product_id']}",
                expiry_date=item_expiry, purchase_price=strip_cost,
                quantity_received=base_qty, quantity_available=base_qty,
                supplier_id=order.supplier_id, receipt_number=receipt_number,
                carton_purchase_price=item["unit_cost"], carton_strips_per_carton=spc,
                bonus_quantity=bonus_strip_qty,
            )
            self.session.add(batch)
            self.session.flush()
            movement_note = f"استلام فاتورة شراء #{order.id} ({item['qty']} باكيت × {spc} شريط)"
            if bonus_qty:
                movement_note = (
                    f"استلام فاتورة شراء #{order.id} "
                    f"({item.get('original_qty', item['qty'] - bonus_qty):g} + هدية {bonus_qty:g} باكيت × {spc} شريط)"
                )
            self.session.add(StockMovement(
                batch_id=batch.id, movement_type="شراء", quantity=base_qty,
                note=movement_note,
            ))

        self.session.commit()
        QMessageBox.information(self, "تم", "تمت إضافة الأصناف للمخزون بنجاح.")
        self.cart = []
        self.receipt_image_path = None
        self.receipt_number_input.clear()
        self.order_date_input.setDate(QDate.currentDate())
        self.receipt_label.setText("ماكو صورة مرفوعة")
        self.ocr_text.clear()
        self.render_table()
        self._refresh_invoices_table()

    def _open_purchase_detail(self, row, col):
        if row >= len(self._invoice_row_ids):
            return
        order_id = self._invoice_row_ids[row]
        order = self.session.query(PurchaseOrder).get(order_id)
        if not order:
            return
        dialog = PurchaseOrderDetailDialog(order, self.session, self)
        dialog.raise_()
        dialog.activateWindow()
        dialog.exec()
        self._refresh_invoices_table()

    def refresh(self):
        self._load_suppliers()
        self._load_invoice_filter_suppliers()
        self._refresh_invoices_table()


class PurchaseOrderDetailDialog(QDialog):
    """تفاصيل فاتورة شراء: عرض الأصناف وتعديل الكمية/السعر، وحذف الفاتورة
    (يصحح المخزون تلقائيًا بالرجوع للدفعة المرتبطة بها عبر batch_number)."""

    def __init__(self, order, session, parent=None):
        super().__init__(parent)
        self.order = order
        self.session = session
        self.setWindowTitle(f"تفاصيل فاتورة شراء #{order.id}")
        # ملاحظة: ما نضبط setWindowModality(Qt.ApplicationModal) هنا صراحة
        # عمدًا - هذي النافذة تنفتح دايمًا عن طريق .exec()، وهذا لحاله كافي
        # يخليها modal بشكل صحيح. وبما إنها تنفتح غالبًا "متداخلة" (كنافذة
        # فرعية من نافذة أخرى مفتوحة أصلاً بـ .exec()، مثل كشف الحساب أو
        # تسديد دفعة أو وصولات الدفع)، ضبط العلامة صراحة هنا فوق NESTED
        # .exec() يسبب تضارب بترتيب النوافذ المشروطة (modal stack) بنسخ
        # ويندوز معينة - وهذا كان السبب الحقيقي وراء "فتح فاتورة وسدها يطلعني
        # من كشف الحساب". .exec() لحاله كافي وآمن بكل الحالات (متداخلة أو لا).
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        supplier = session.query(Supplier).get(order.supplier_id) if order.supplier_id else None
        summary = purchase_order_summary(session, order)
        status_line = summary["status_display"] or "—"
        # ملخص واضح فوق الجدول: المورد، الحالة، والمرتجع (لو أكو) - التاريخ
        # ورقم الوصل صاروا حقلين قابلين للتعديل تحت (مو نص ثابت هنا) حتى
        # يقدر المستخدم يصحح أي منهم بعد الإدخال (تاريخ خاطئ أو رقم وصل
        # نسي يسجله أو غلط فيه وقت الإدخال الأول).
        summary_lines = [
            f"المورد: {supplier.name if supplier else '— بدون مورد محدد —'}",
            f"الحالة: {status_line}",
        ]
        if summary["returned"] > 0:
            summary_lines.append(
                f"إجمالي الفاتورة الأصلي: {summary['net_total'] + summary['returned']:,.0f}   |   "
                f"المرتجع: {summary['returned']:,.0f}   |   الصافي المستحق: {summary['net_total']:,.0f}   |   "
                f"المتبقي غير المسدد: {summary['remaining']:,.0f}"
            )
        header = QLabel("\n".join(summary_lines))
        header.setStyleSheet("color:#6B7280;margin-bottom:8px;")
        layout.addWidget(header)

        # --- تعديل التاريخ ورقم الوصل - أي نافذة تعديل فاتورة بالنظام
        # (تفتح من هنا بالضبط بكل الأماكن: كشف الحساب، وصل الدفع، تفاصيل
        # الوصولات، شاشة المشتريات مباشرة) صار فيها هذين الحقلين قابلين
        # للتعديل، مو بس الكمية/السعر بالجدول تحت. ---
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("التاريخ:"))
        self.order_date_input = QDateEdit(QDate(order.order_date) if order.order_date else QDate.currentDate())
        self.order_date_input.setCalendarPopup(True)
        self.order_date_input.setDisplayFormat("yyyy-MM-dd")
        edit_row.addWidget(self.order_date_input)
        edit_row.addWidget(QLabel("رقم الوصل:"))
        self.receipt_number_edit = QLineEdit(order.receipt_number or "")
        self.receipt_number_edit.setPlaceholderText("رقم الوصل (اختياري)...")
        edit_row.addWidget(self.receipt_number_edit, stretch=1)
        layout.addLayout(edit_row)

        # --- تغيير المورد: ينقل الفاتورة كاملة (والمبلغ المستحق وياها) من
        # حساب المورد الحالي لحساب المورد الجديد - مو مجرد تسمية. أرصدة
        # الموردين تُحسب دايمًا لحظيًا من (فواتير الشراء + المرتجعات +
        # الوصولات) المرتبطة بكل مورد (ماكو رصيد محفوظ منفصل يحتاج تعديل
        # يدوي) - فتغيير supplier_id هنا وبس كافي وآمن، النقل يصير صحيح
        # تلقائيًا بأول تحديث لكشف حساب أي من المورَدين. راجع save_edits()
        # لتفاصيل تحديث الدفعات المرتبطة بنفس المورد الجديد كمان.
        supplier_row = QHBoxLayout()
        supplier_row.addWidget(QLabel("المورد:"))
        self.edit_supplier_combo = QComboBox()
        self.edit_supplier_combo.setEditable(True)
        self.edit_supplier_combo.setInsertPolicy(QComboBox.NoInsert)
        edit_supplier_completer = QCompleter(self.edit_supplier_combo.model(), self.edit_supplier_combo)
        edit_supplier_completer.setCaseSensitivity(Qt.CaseInsensitive)
        edit_supplier_completer.setFilterMode(Qt.MatchContains)
        edit_supplier_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.edit_supplier_combo.setCompleter(edit_supplier_completer)
        self.edit_supplier_combo.addItem("— بدون مورد محدد —", None)
        for s in session.query(Supplier).order_by(Supplier.name).all():
            self.edit_supplier_combo.addItem(s.name, s.id)
        idx = self.edit_supplier_combo.findData(order.supplier_id)
        if idx >= 0:
            self.edit_supplier_combo.setCurrentIndex(idx)
        disable_scroll(self.edit_supplier_combo)
        supplier_row.addWidget(self.edit_supplier_combo, stretch=1)
        layout.addLayout(supplier_row)

        # كمية كل صنف سبق إرجاعها من هذي الفاتورة تحديدًا (لعرضها كعمود
        # إعلامي بس - ما تُعدَّل، والكمية الأصلية بعمود "الكمية" تضل زي
        # ما هي دايمًا لأنها أساس حساب الدفعة المرتبطة بالمخزون).
        returned_qty_by_product = {}
        for pr in order.returns:
            for it in pr.items:
                returned_qty_by_product[it.product_id] = returned_qty_by_product.get(it.product_id, 0) + it.quantity

        self.table = QTableWidget()
        enable_touch_scroll(self.table)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["الدواء", "سعر شراء الباكيت", "الكمية (باكيت)", "مرتجع منها", "الإجمالي", ""])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setRowCount(len(order.items))
        self._rows = []  # [{"item_id","product_id","qty_input","cost_input"}, ...]
        for row, item in enumerate(order.items):
            self._build_item_row(row, item, returned_qty_by_product)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table)

        note = QLabel(
            "تغيير الكمية أو السعر يصحح المخزون والتكلفة تلقائيًا بالدفعة المرتبطة. "
            "لو جزء من الكمية انباع أصلاً، ما نقدر ننزلها تحت المتبقي الفعلي بالمخزون."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#6B7280;font-size:11px;")
        layout.addWidget(note)

        save_btn = QPushButton("حفظ التعديلات")
        save_btn.setIcon(icon("save", color="white", size=15))
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:10px;font-weight:bold;")
        save_btn.clicked.connect(self.save_edits)
        layout.addWidget(save_btn)

        delete_btn = QPushButton("حذف فاتورة الشراء (يصحح المخزون تلقائيًا)")
        delete_btn.setIcon(icon("trash", color="white", size=15))
        delete_btn.setStyleSheet("background:#DC2626;color:white;border-radius:8px;padding:10px;font-weight:bold;")
        delete_btn.clicked.connect(self.delete_order)
        layout.addWidget(delete_btn)

    def _build_item_row(self, row, item, returned_qty_by_product):
        """يبني صف صنف وحد بجدول تفاصيل الفاتورة (دواء/سعر/كمية/مرتجع/
        إجمالي/زر حذف) - دالة منفصلة حتى تنستخدم وقت الإنشاء الأول ووقت
        إعادة بناء الجدول بعد حذف صنف (self._rebuild_table)."""
        product = self.session.query(Product).get(item.product_id) if item.product_id else None
        name_text = product.name if product else "— دواء محذوف —"
        # الهدية/البونص (لو أكو) تبين مكتوبة صريح بعمود الدواء نفسه - مو
        # بس تلميح (tooltip) مخفي - بالضبط الطلب: "بالجدول مكتوب الهدية".
        if item.bonus_quantity:
            name_text += f"  (هدية: {item.bonus_quantity:g})"
        name_item = QTableWidgetItem(name_text)
        if item.bonus_quantity:
            name_item.setForeground(QColor(TEAL_700))
            original_qty = item.quantity - item.bonus_quantity
            # نعيد اشتقاق السعر الاسمي الأصلي (اللي اتفق عليه فعليًا مع
            # المورد قبل توزيع الهدية) من unit_cost المخزّن - ما نخزّنه
            # لحاله بقاعدة البيانات (بس bonus_quantity وunit_cost الفعلي
            # بعد التوزيع)، فنحسبه عكسيًا هنا وقت العرض بس، حتى السعر
            # بعمود "سعر شراء الباكيت" (909 مثلًا) ما يبين رقم غريب بدون
            # تفسير - نوضح بالتلميح إنه فعلي بعد توزيع الهدية، وشنو كان
            # السعر الأصلي المتفق عليه قبلها.
            # إجمالي الفاتورة يبقى نفسه (الكمية المشتراة × السعر الاسمي،
            # بدون طرح شي) - موزّع بس على الكمية الكلية (مشتراة + هدية):
            # nominal_price = (quantity × unit_cost) ÷ original_qty
            nominal_price = (item.quantity * item.unit_cost) / original_qty if original_qty > 0 else item.unit_cost
            name_item.setToolTip(
                f"الكمية الكلية {item.quantity:g} تتضمن هدية {item.bonus_quantity:g} "
                f"(الكمية المشتراة فعليًا: {original_qty:g})\n"
                f"سعر شراء الباكيت المعروض ({item.unit_cost:,.2f}) هو السعر الفعلي بعد توزيع "
                f"الهدية على الكمية الكلية - السعر الاسمي المتفق عليه كان تقريبًا "
                f"{nominal_price:,.0f} للباكيت، وإجمالي الفاتورة لهذا الصنف ضل نفسه "
                f"({original_qty:g} × {nominal_price:,.0f})."
            )
        self.table.setItem(row, 0, name_item)
        cost_input = NumberLineEdit()
        cost_input.set_value(item.unit_cost)
        self.table.setCellWidget(row, 1, cost_input)
        qty_input = NumberLineEdit(decimals=2)
        qty_input.set_value(item.quantity)
        self.table.setCellWidget(row, 2, qty_input)
        returned_qty = returned_qty_by_product.get(item.product_id, 0)
        returned_item = QTableWidgetItem(str(returned_qty) if returned_qty else "—")
        if returned_qty:
            returned_item.setForeground(QColor("#DC2626"))
        self.table.setItem(row, 3, returned_item)
        self.table.setItem(row, 4, QTableWidgetItem(f"{item.quantity * item.unit_cost:,.0f}"))
        del_btn = QPushButton()
        del_btn.setIcon(icon("trash", color="#DC2626", size=14))
        del_btn.setToolTip("حذف هذا الصنف كامل من الفاتورة (مو بس تصفير الكمية)")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet("background:transparent;border:none;padding:4px;")
        del_btn.clicked.connect(lambda checked=False, iid=item.id: self._delete_single_item(iid))
        self.table.setCellWidget(row, 5, del_btn)
        self._rows.append({"item_id": item.id, "product_id": item.product_id, "qty_input": qty_input, "cost_input": cost_input})

    def _delete_single_item(self, item_id):
        """حذف صنف كامل من الفاتورة (مو بس تعديل كميته لـ 0) - يصحح
        المخزون فورًا (نفس منطق حذف الفاتورة الكاملة بس لعنصر وحد)، يحذف
        الصنف من قاعدة البيانات، ويعيد بناء الجدول مباشرة."""
        item = self.session.query(PurchaseOrderItem).get(item_id)
        if not item:
            return
        if len(self.order.items) <= 1:
            QMessageBox.warning(
                self, "تنبيه",
                "هذا آخر صنف بالفاتورة - لو تريد تصفر الفاتورة كاملة استخدم زر \"حذف فاتورة الشراء\" بالأسفل."
            )
            return
        product = self.session.query(Product).get(item.product_id) if item.product_id else None
        product_name = product.name if product else "الصنف"
        confirm = QMessageBox.question(
            self, "تأكيد الحذف",
            f"متأكد تريد تحذف \"{product_name}\" كامل من هذي الفاتورة؟ راح يتصحح المخزون تلقائيًا حسب المتبقي الفعلي.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        spc = (product.strips_per_carton or 3) if product else 3
        batch = self._find_batch(item.product_id) if item.product_id else None
        # نفس احتياط delete_order - نطرح الكمية المرتجعة مسبقًا من هذا
        # الصنف بالذات (لو أكو) قبل تصحيح المخزون، حتى ما نسحب منه مرتين.
        already_returned = sum(
            it.quantity for pr in self.order.returns for it in pr.items if it.product_id == item.product_id
        )
        net_qty = max(item.quantity - already_returned, 0)
        base_qty = _strips_from_cartons(net_qty, spc)
        partial_sold_warning = False
        if batch and base_qty > 0:
            if batch.quantity_available < base_qty:
                partial_sold_warning = True
                batch.quantity_available = 0
            else:
                batch.quantity_available -= base_qty
            self.session.add(StockMovement(
                batch_id=batch.id, movement_type="حذف صنف من فاتورة شراء", quantity=base_qty,
                note=f"حذف صنف \"{product_name}\" من فاتورة شراء #{self.order.id}",
            ))

        self.session.delete(item)
        self.session.flush()  # حتى order.items تنعكس فورًا بدون حاجة نعيد الاستعلام
        self.order.total_amount = sum(i.quantity * i.unit_cost for i in self.order.items)
        self.session.commit()

        if partial_sold_warning:
            QMessageBox.information(
                self, "تنبيه",
                f"تم حذف \"{product_name}\"، لكن جزء منه كان انباع أصلاً فصار مخزونه صفر بدل ما ينزل بالسالب."
            )

        self._rebuild_table()

    def _rebuild_table(self):
        """يعيد بناء جدول الأصناف من جديد من order.items الحالية - يُستخدم
        بعد حذف صنف كامل حتى يختفي صفه من الجدول فورًا بدون قفل النافذة."""
        self.session.refresh(self.order)
        returned_qty_by_product = {}
        for pr in self.order.returns:
            for it in pr.items:
                returned_qty_by_product[it.product_id] = returned_qty_by_product.get(it.product_id, 0) + it.quantity
        self._rows = []
        self.table.setRowCount(len(self.order.items))
        for row, item in enumerate(self.order.items):
            self._build_item_row(row, item, returned_qty_by_product)
        self.table.resizeRowsToContents()

    def _find_batch(self, product_id):
        return (
            self.session.query(Batch)
            .filter(Batch.batch_number == f"PO-{self.order.id}-{product_id}")
            .first()
        )

    def save_edits(self):
        new_total = 0.0
        for row_data in self._rows:
            item_id, product_id = row_data["item_id"], row_data["product_id"]
            qty_input, cost_input = row_data["qty_input"], row_data["cost_input"]
            item = self.session.query(PurchaseOrderItem).get(item_id)
            new_qty = qty_input.value()
            new_cost = cost_input.value()
            if new_qty <= 0:
                QMessageBox.warning(self, "تنبيه", "الكمية لازم تكون أكبر من صفر (احذف الصنف بزر الحذف لو تريد تشيله كامل).")
                return

            product = self.session.query(Product).get(product_id) if product_id else None
            spc = (product.strips_per_carton or 3) if product else 3
            batch = self._find_batch(product_id) if product_id else None

            old_base_qty = _strips_from_cartons(item.quantity, spc)
            new_base_qty = _strips_from_cartons(new_qty, spc)
            delta = new_base_qty - old_base_qty

            if batch and delta != 0:
                if batch.quantity_available + delta < 0:
                    QMessageBox.warning(
                        self, "تنبيه مخزون",
                        f"ماكو مجال تنزل الكمية هالقد - أكو {batch.quantity_available} شريط بس متبقي بالمخزون "
                        f"(يعني جزء انباع أصلاً من هذي الدفعة)."
                    )
                    return
                batch.quantity_available += delta
                batch.quantity_received += delta
                self.session.add(StockMovement(
                    batch_id=batch.id, movement_type="تعديل شراء", quantity=abs(delta),
                    note=f"تعديل فاتورة شراء #{self.order.id} ({'زيادة' if delta > 0 else 'تنقيص'})",
                ))
            if batch:
                batch.purchase_price = (new_cost / spc) if spc else 0
                batch.carton_purchase_price = new_cost
                batch.carton_strips_per_carton = spc

            item.quantity = new_qty
            item.unit_cost = new_cost
            new_total += new_qty * new_cost

        self.order.total_amount = new_total
        self.order.order_date = self.order_date_input.date().toPython()
        self.order.receipt_number = self.receipt_number_edit.text().strip() or None

        # --- تغيير المورد (لو تغيّر فعلاً) - ينقل الفاتورة والدفعات
        # المرتبطة بيها كاملة لحساب المورد الجديد. راجع تعليق
        # self.edit_supplier_combo بالأعلى لتفاصيل ليش هذا كافي وآمن
        # لنقل المبلغ المستحق تلقائيًا. الدفعات (Batch) عندها supplier_id
        # منفصل خاص بيها (يُستخدم بعرض "دفعات المخزون" بشاشة المخزون) -
        # لازم نحدّثها هي الثانية حتى تنسجم مع المورد الجديد، وإلا تضل
        # تبين المورد القديم بشاشة المخزون رغم إن الفاتورة انتقلت.
        new_supplier_id = self.edit_supplier_combo.currentData()
        if new_supplier_id != self.order.supplier_id:
            self.order.supplier_id = new_supplier_id
            linked_batches = (
                self.session.query(Batch)
                .filter(Batch.batch_number.like(f"PO-{self.order.id}-%"))
                .all()
            )
            for b in linked_batches:
                b.supplier_id = new_supplier_id

        self.session.commit()
        QMessageBox.information(self, "تم", "تم حفظ تعديلات فاتورة الشراء.")
        self.accept()

    def delete_order(self):
        has_returns = len(self.order.returns) > 0
        warning_extra = "\n\nتنبيه: هذي الفاتورة عليها مرتجع مسجّل - راح ينحذف المرتجع وياها تلقائيًا (مو بس الفاتورة)." if has_returns else ""
        confirm = QMessageBox.question(
            self, "تأكيد الحذف",
            f"متأكد تريد تحذف فاتورة الشراء هذي؟ راح يتصحح المخزون تلقائيًا حسب المتبقي الفعلي.{warning_extra}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        # كمية كل صنف سبق إرجاعها من هذي الفاتورة (عبر PurchaseReturn) - لازم
        # تُطرح من الكمية الأصلية قبل ما نصحح المخزون، لأنه هذا الجزء أصلاً
        # طلع من المخزون وقت تسجيل المرتجع (راجع PurchaseReturnDialog.save)
        # - لو ما طرحناها، حذف فاتورة عليها مرتجع كان راح يسحب من المخزون
        # مرتين لنفس الكمية (مرة وقت المرتجع، ومرة ثانية هنا وقت الحذف).
        returned_qty_by_product = {}
        for pr in self.order.returns:
            for it in pr.items:
                returned_qty_by_product[it.product_id] = returned_qty_by_product.get(it.product_id, 0) + it.quantity

        partial_sold_warning = False
        for item in self.order.items:
            if not item.product_id:
                continue
            product = self.session.query(Product).get(item.product_id)
            spc = (product.strips_per_carton or 3) if product else 3
            batch = self._find_batch(item.product_id)
            already_returned = returned_qty_by_product.get(item.product_id, 0)
            net_qty = max(item.quantity - already_returned, 0)
            base_qty = _strips_from_cartons(net_qty, spc)
            if batch and base_qty > 0:
                if batch.quantity_available < base_qty:
                    partial_sold_warning = True
                    batch.quantity_available = 0
                else:
                    batch.quantity_available -= base_qty
                self.session.add(StockMovement(
                    batch_id=batch.id, movement_type="حذف فاتورة شراء", quantity=base_qty,
                    note=f"حذف فاتورة شراء #{self.order.id}",
                ))

        self.session.delete(self.order)  # حذف الفاتورة يحذف وياها مرتجعاتها المرتبطة تلقائيًا (cascade بـ models.py)
        self.session.commit()
        if partial_sold_warning:
            QMessageBox.information(
                self, "تم مع تنبيه",
                "تم حذف الفاتورة، بس جزء من كميتها كان انباع أصلاً - المخزون المرتبط صفّرناه بس ما قدرنا ننزله تحت الصفر."
            )
        else:
            QMessageBox.information(self, "تم", "تم حذف فاتورة الشراء وتصحيح المخزون.")
        self.accept()
