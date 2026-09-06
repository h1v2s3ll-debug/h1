"""
أدوات مطابقة أسماء أدوية عربية/إنكليزية بشكل متسامح - تتجاوز:
  - اختلاف أشكال الألف/الهمزة والتاء المربوطة (أموكسيسيلين / اموكسيسيلين).
  - أخطاء إملائية بسيطة أو حروف ناقصة/زايدة (خطأ كتابة عادي).
  - اختلاف ترتيب الكلمات (اكسترا بندول / بندول اكسترا).
  - اسم مكتوب بالإنكليزي بينما هو مسجّل بالعربي بالمخزون (تحويل صوتي تقريبي).

هذا هو نفس منطق المطابقة المستخدم أصلًا بشاشة المشتريات (قراءة فاتورة
بالذكاء الاصطناعي) - نقلناه لملف مستقل هنا حتى يصير قابل الاستخدام من
سيرفر الموبايل (app/mobile_server.py) بدون ما يحتاج السيرفر يستورد وحدات
واجهة Qt (PySide6) اللي مالها داعي بملف سيرفر مفروض يضل خفيف ومستقل - نفس
سبب وجود app/ai_vision_helper.py بملف مستقل تمامًا.

الاستخدام الأساسي: بدل ما بحث اسم الدواء (بشاشة المشتريات بالموبايل، سواء
خانة "تحديث/شراء لدواء موجود" أو تصحيح صنف بمراجعة فاتورة مصوّرة) يفشل
تمامًا لمجرد فرق بسيط بالكتابة عن الاسم المسجّل بالضبط، نرجّع دائمًا أقرب
النتائج الموجودة فعليًا مرتبة حسب التشابه - حتى لو مو تطابق كامل.
"""
import re
import difflib

def normalize_arabic(text):
    """يوحّد أشكال الألف والهمزة والتاء المربوطة عشان البحث ما يفشل بسبب
    اختلاف الكتابة - نفس دالة normalize_arabic المستخدمة بشاشة نقطة البيع
    وشاشة المشتريات بالضبط (منطق مطابق تمامًا، منسوخ هنا حتى هذا الملف يضل
    مستقل بدون أي استيراد لوحدات Qt).

    ⚠️ لازم تضل معرّفة هنا (قبل _FORM_GROUP_PATTERNS تحت) - أول الملف، مو
    بعده - لأنها تُستخدم وقت *تحميل الملف نفسه* (module-level) لبناء أنماط
    regex الشكل الصيدلاني مرة وحدة، مو بس داخل دوال تنستدعى لاحقًا."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"[ًٌٍَُِّْ]", "", text)  # إزالة التشكيل
    return text.lower()


_LATIN_DIGRAPHS = [
    ("sh", "ش"), ("ch", "تش"), ("th", "ث"), ("kh", "خ"), ("gh", "غ"),
    ("ph", "ف"), ("qu", "ك"), ("ck", "ك"), ("oo", "و"), ("ee", "ي"),
    ("ea", "ي"), ("ou", "او"), ("ay", "اي"), ("ey", "اي"), ("oy", "وي"),
    ("ie", "اي"),
]
_LATIN_SINGLE = {
    "a": "ا", "b": "ب", "c": "ك", "d": "د", "e": "ي", "f": "ف", "g": "ج",
    "h": "ه", "i": "ي", "j": "ج", "k": "ك", "l": "ل", "m": "م", "n": "ن",
    "o": "و", "p": "ب", "q": "ك", "r": "ر", "s": "س", "t": "ت", "u": "و",
    "v": "ف", "w": "و", "x": "كس", "y": "ي", "z": "ز",
}

# نسبة تشابه أقل من هذا الحد تعتبر "غير موثوقة" (ما نأشرها كتطابق مؤكد
# تلقائي) - بس تضل تنعرض كاقتراح ضمن أقرب النتائج، لأن اقتراح ضعيف أفضل من
# قائمة فاضية تخلي المستخدم يحس إن البحث "فاشل" بالكامل.
CONFIDENT_MATCH_THRESHOLD = 0.35


# نسبة تشابه أقل من هذا الحد تعتبر "غير موثوقة" (ما نأشرها كتطابق مؤكد
# تلقائي) - بس تضل تنعرض كاقتراح ضمن أقرب النتائج، لأن اقتراح ضعيف أفضل من
# قائمة فاضية تخلي المستخدم يحس إن البحث "فاشل" بالكامل.
CONFIDENT_MATCH_THRESHOLD = 0.35

# نسبة تشابه فوق هذا الحد تعتبر "شبه مؤكدة" - ما تحتاج تأكيد إضافي من
# الذكاء الاصطناعي (راجع app/ai_vision_helper.verify_matches_with_ai)،
# توفير لعدد نداءات الـAPI للحالات الواضحة أصلًا.
STRONG_MATCH_THRESHOLD = 0.90


# ------------------------------------------------------------------
# كشف تعارض الجرعة/التركيز والشكل الصيدلاني - قاعدة صارمة (مو تخمين)
# تمنع اعتبار اسمين "نفس الدواء" لمجرد تشابه نصي عالي، إذا كانت الجرعة أو
# الشكل الصيدلاني مختلفين فعلاً وبوضوح بين الاثنين. مثلًا "أوجمنتين 625
# ملغم" و"أوجمنتين 1 غم" يشبهون بعض نصيًا لدرجة عالية جدًا (نفس الاسم،
# يختلفون برقم بس) - بس هذا قاعدة صارمة تمنع اعتبارهم نفس الصنف أبدًا.
# ------------------------------------------------------------------

# وحدات الكتلة (كلها تتحول لـ mg للمقارنة الموحّدة)
_DOSE_UNIT_MG = {
    "ملغم": 1, "ملغ": 1, "مجم": 1, "ميليغرام": 1,
    "مكغ": 0.001, "ميكروغرام": 0.001, "ميكروجرام": 0.001,
    "غم": 1000, "غرام": 1000, "غ": 1000,
    "كغم": 1_000_000, "كيلوغرام": 1_000_000,
    "mg": 1, "milligram": 1, "milligrams": 1,
    "mcg": 0.001, "ug": 0.001, "microgram": 0.001,
    "g": 1000, "gm": 1000, "gram": 1000, "grams": 1000,
    "kg": 1_000_000,
}
# وحدات الحجم (تتحول لـ ml)
_DOSE_UNIT_ML = {
    "مل": 1, "مليلتر": 1, "سم3": 1, "سي سي": 1,
    "لتر": 1000,
    "ml": 1, "milliliter": 1, "milliliters": 1, "cc": 1,
    "l": 1000, "liter": 1000, "litre": 1000,
}
# وحدات ثانية ما تتحول (كل وحدة فئة لحالها - نقارن بس داخل نفس الفئة)
_DOSE_UNIT_OTHER = {
    "وحدة": "iu", "وحدة دولية": "iu", "iu": "iu",
    "%": "percent",
}

_ALL_DOSE_UNITS = sorted(
    set(_DOSE_UNIT_MG) | set(_DOSE_UNIT_ML) | set(_DOSE_UNIT_OTHER),
    key=len, reverse=True,  # الأطول أول حتى "وحدة دولية" تسبق "وحدة" بالمطابقة
)
_DOSE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(" + "|".join(re.escape(u) for u in _ALL_DOSE_UNITS) + r")\b",
    re.IGNORECASE,
)


def extract_doses(text):
    """يرجع قائمة (فئة_الوحدة, القيمة_الموحّدة) من كل جرعة/تركيز مذكور
    صراحة بالنص (رقم ملاصق لوحدة معروفة) - مثلًا 'أوجمنتين 625 ملغم' ترجع
    [('mg', 625.0)]. نص بدون أي وحدة معروفة يرجع قائمة فاضية (يعني: ماكو
    معلومة جرعة مذكورة، مو دليل تعارض مع أي شي)."""
    if not text:
        return []
    doses = []
    for m in _DOSE_RE.finditer(text.lower()):
        value_str, unit = m.group(1).replace(",", "."), m.group(2).lower()
        try:
            value = float(value_str)
        except ValueError:
            continue
        if unit in _DOSE_UNIT_MG:
            doses.append(("mg", round(value * _DOSE_UNIT_MG[unit], 3)))
        elif unit in _DOSE_UNIT_ML:
            doses.append(("ml", round(value * _DOSE_UNIT_ML[unit], 3)))
        elif unit in _DOSE_UNIT_OTHER:
            doses.append((_DOSE_UNIT_OTHER[unit], value))
    return doses


# مجموعات الشكل الصيدلاني - كل مجموعة مرادفات لنفس الشكل (عربي وإنكليزي)
_FORM_GROUPS = [
    {"قرص", "اقراص", "أقراص", "tablet", "tablets", "tab", "tabs"},
    {"كبسول", "كبسولة", "كبسولات", "capsule", "capsules", "cap", "caps"},
    {"شراب", "syrup"},
    {"حقنة", "حقن", "حقنه", "امبول", "أمبول", "امبولة", "أمبولة", "فيال",
     "injection", "ampoule", "ampoules", "ampule", "ampules", "vial", "vials"},
    {"مرهم", "ointment"},
    {"كريم", "cream"},
    {"نقط", "نقطة", "قطرة", "قطرات", "drops", "drop"},
    {"تحاميل", "تحميلة", "suppository", "suppositories"},
    {"بخاخ", "بخاخة", "spray"},
    {"فوار", "effervescent"},
    {"جل", "gel"},
    {"لصقة", "لاصقة", "patch"},
    {"غسول", "lotion"},
    {"مضمضة", "mouthwash"},
]

# ⚠️ تحسين أداء مهم: نبني أنماط regex كل مجموعة **مرة وحدة بس عند تحميل
# الملف** (مو بكل استدعاء لـextract_forms) - كانت تبني نص النمط (escape +
# تجميع) من جديد بكل مرة، لكل كلمة بكل مجموعة (~45 مرة!) لكل مرشح واحد.
# مع كتالوج كبير (آلاف الأدوية) وعدة أصناف بفاتورة وحدة، هذا كان يصير آلاف
# عمليات regex غير ضرورية - سبب حقيقي لبطء شديد (شبه تجمّد) بتصوير الفاتورة.
_FORM_GROUP_PATTERNS = [
    re.compile(r"\b(?:" + "|".join(re.escape(normalize_arabic(w)) for w in group) + r")\b")
    for group in _FORM_GROUPS
]


def extract_forms(text):
    """يرجع مجموعة أرقام (فهرس المجموعة بـ_FORM_GROUPS) لكل شكل صيدلاني
    مذكور صراحة بالنص. نص بدون أي كلمة شكل معروفة يرجع مجموعة فاضية (يعني
    ماكو معلومة شكل مذكورة، مو دليل تعارض)."""
    if not text:
        return set()
    norm = normalize_arabic(text)
    return {i for i, pattern in enumerate(_FORM_GROUP_PATTERNS) if pattern.search(norm)}


def dosage_form_conflicts(name_a, name_b):
    """يرجع True لو فيه تعارض واضح بالجرعة/التركيز أو الشكل الصيدلاني بين
    اسمين - نستخدمها كقاعدة صارمة تلغي المطابقة نهائيًا حتى لو تشابه الاسم
    نصيًا عالي جدًا (مثلًا 'أوجمنتين 625' و'أوجمنتين 1 غم').

    ما نعتبره تعارض إلا لو الاثنين مذكور فيهم جرعة/شكل صريح ومختلف فعلاً -
    غياب المعلومة بجانب وحد (مثلاً الاسم المستخرج من الفاتورة ما فيه رقم
    جرعة واضح بالصورة) مو دليل تعارض، لأنه ببساطة ماكو معلومة نقارنها.

    ⚠️ إصلاح مهم: أدوية كثيرة عندها أكثر من رقم بنفس الاسم (تركيز + حجم،
    مثلاً "80 ملغم / 2 مل") - المقارنة القديمة كانت تجمع كل الأرقام (مهما
    كانت فئتها) بقائمة وحدة وتتأكد "فيه أي رقم متطابق" - فلو الحجم يتطابق
    (2 مل = 2 مل) بس التركيز يختلف كليًا (80 ملغم مقابل 20 ملغم)، كانت
    تعتبرهم "متوافقين" غلط لمجرد تطابق الحجم! الصح: نقارن **كل فئة لحالها**
    (كل أرقام mg مع بعض، كل أرقام ml مع بعض...) - وأي فئة مشتركة بين
    الاثنين وما فيها ولا رقم متطابق تعتبر تعارض قاطع، حتى لو فئة ثانية
    تصادف تطابقها."""
    doses_a, doses_b = extract_doses(name_a), extract_doses(name_b)
    if doses_a and doses_b:
        cats_a, cats_b = {}, {}
        for cat, val in doses_a:
            cats_a.setdefault(cat, []).append(val)
        for cat, val in doses_b:
            cats_b.setdefault(cat, []).append(val)
        for cat in set(cats_a) & set(cats_b):
            if not any(abs(va - vb) < 0.001 for va in cats_a[cat] for vb in cats_b[cat]):
                return True

    forms_a, forms_b = extract_forms(name_a), extract_forms(name_b)
    if forms_a and forms_b and not (forms_a & forms_b):
        return True

    return False


def transliterate_latin_to_arabic(text_val):
    """تحويل صوتي تقريبي (مو ترجمة!) لكلمة إنكليزية لصيغتها العربية
    المتوقعة (Augmentin → اوجمنتين تقريبًا) - مصدر إضافي للمطابقة فقط."""
    s = text_val.lower()
    out = []
    i = 0
    while i < len(s):
        matched = False
        for latin, arabic in _LATIN_DIGRAPHS:
            if s[i:i + len(latin)] == latin:
                out.append(arabic)
                i += len(latin)
                matched = True
                break
        if matched:
            continue
        ch = s[i]
        out.append(_LATIN_SINGLE.get(ch, ch if not ch.isalpha() else ""))
        i += 1
    return "".join(out)


def _tokenize(normalized_text):
    """يقسّم النص لكلمات مقارنة (بعد normalize_arabic) بشكل يتحمّل فروقات
    التنسيق الشائعة بفواتير الأدوية - مو بس مسافات عادية.

    ⚠️ سبب وجودها: نص مستخرج من فاتورة زي "80MG/2ML" (بدون مسافات) ينكتب
    بمخزونك عادةً بمسافات "80 MG / 2 ML" - لو استخدمنا .split() العادي
    (يقسّم على مسافة بس)، "80MG/2ML" يضل كلمة وحدة كاملة بينما "80 MG / 2
    ML" تنقسم لأربع كلمات منفصلة - فمقارنة الكلمات لحالها (token_match_ratio)
    تفشل تمامًا بالمطابقة رغم إنهم نفس المعلومة بالضبط. نفصل هنا عند علامات
    الترقيم الشائعة (/ * - , ( ) |) وعند حدود رقم↔حرف (80mg → 80 mg) حتى
    يصير التقسيم متسق بين الاثنين."""
    if not normalized_text:
        return []
    spaced = re.sub(r"[/*\-,()|]", " ", normalized_text)
    spaced = re.sub(r"(\d)([a-z%])", r"\1 \2", spaced)
    spaced = re.sub(r"([a-z])(\d)", r"\1 \2", spaced)
    return spaced.split()


def token_match_ratio(tokens_a, tokens_b):
    """متوسط أفضل تشابه لكل كلمة من الاسم الأول مع أقرب كلمة بالاسم الثاني -
    يحل مشكلة اختلاف ترتيب الكلمات اللي مقارنة السلسلة الكاملة بترتيبها
    الأصلي تفشل بيها."""
    if not tokens_a or not tokens_b:
        return 0.0
    scores = []
    for ta in tokens_a:
        best = max(
            (difflib.SequenceMatcher(None, ta, tb).ratio() for tb in tokens_b),
            default=0.0,
        )
        scores.append(best)
    return sum(scores) / len(scores)


def fuzzy_ratio(query_text, *candidate_texts):
    """أعلى نسبة تشابه (من 0 إلى 1) بين نص البحث وأي نص من candidate_texts
    (مثلًا اسم الدواء التجاري + اسمه العلمي) بعد توحيد الأحرف، وبعد تحويل
    صوتي لو نص البحث فيه حروف إنكليزية، وبعد مقارنة بالكلمات لحالها (مو بس
    السلسلة كاملة بترتيبها الأصلي)."""
    target = normalize_arabic(query_text)
    if not target:
        return 0.0
    target_tokens = _tokenize(target)

    has_latin = bool(re.search(r"[A-Za-z]", query_text))
    target_translit = normalize_arabic(transliterate_latin_to_arabic(query_text)) if has_latin else ""
    translit_tokens = _tokenize(target_translit) if target_translit else []

    best = 0.0
    for candidate in candidate_texts:
        if not candidate:
            continue
        cand_norm = normalize_arabic(candidate)
        if not cand_norm:
            continue
        cand_tokens = _tokenize(cand_norm)

        ratios = [
            difflib.SequenceMatcher(None, target, cand_norm).ratio(),
            token_match_ratio(target_tokens, cand_tokens),
        ]
        if target_translit:
            ratios.append(difflib.SequenceMatcher(None, target_translit, cand_norm).ratio())
            ratios.append(token_match_ratio(translit_tokens, cand_tokens))

        best = max(best, max(ratios))
    return best


def rank_by_similarity(query_text, candidates, limit=5, strict_dosage_form=False):
    """candidates: [(id, name, generic_name_or_None), ...]
    يرجع أقرب `limit` نتيجة موجودة فعليًا مرتبة تنازليًا حسب نسبة التشابه:
    [(id, name, ratio), ...]. يرجّع دائمًا أقرب الموجود (حتى لو النسبة
    واطية) طالما فيه مرشحين أصلًا وسؤال بحث فعلي - قائمة فاضية تعني فقط
    "ماكو أي دواء مسجل إطلاقًا" أو "خانة البحث فاضية"، مو "ماكو تطابق جيد"،
    حتى صندوق الاقتراحات ما يضل فاضي بالغلط لمجرد فرق بسيط بالكتابة.

    strict_dosage_form=True: يستبعد أي مرشح فيه تعارض جرعة/شكل صيدلاني
    واضح مع نص البحث (راجع dosage_form_conflicts) - مهما كان تشابهه
    النصي عالي. نتركها False افتراضيًا لأنها مناسبة بس لحالة "أبحث عن
    الدواء المطابق بالضبط لصنف فاتورة" (مطابقة تلقائية)، مو لحالة "أبحث
    وأتصفح دوائي يدويًا" (خانة بحث المستخدم) اللي ممكن يكتب اسم بدون
    جرعة عمدًا حتى يشوف كل الجرعات المتوفرة عنده."""
    query_text = (query_text or "").strip()
    if not query_text or not candidates:
        return []
    scored = []
    for pid, name, generic in candidates:
        if strict_dosage_form:
            conflicts_name = dosage_form_conflicts(query_text, name)
            conflicts_generic = dosage_form_conflicts(query_text, generic) if generic else True
            if conflicts_name and conflicts_generic:
                continue
        scored.append((pid, name, fuzzy_ratio(query_text, name, generic)))
    scored.sort(key=lambda row: row[2], reverse=True)
    return scored[:limit]
