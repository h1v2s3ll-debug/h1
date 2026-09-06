"""
قراءة صورة فاتورة شراء عبر الذكاء الاصطناعي (Gemini أو Anthropic Claude)
واستخراج بنودها (اسم الصنف، الكمية، السعر) تلقائيًا - يستخدم نفس مفتاح
الـAPI ونفس المزوّد المحفوظين بشاشة الإعدادات لصفحة "المستشار الذكي"
(app/ui/advisor_view.py يستخدم نفس الإعدادات: ai_api_key / ai_provider) -
ما يحتاج إعداد منفصل، إعداد واحد يخدم الميزتين.

هذا يستخدمه سيرفر الموبايل (app/mobile_server.py) لميزة "تصوير فاتورة"
اللي تشتغل من متصفح الموبايل - مقابل ميزة OCR المحلية الموجودة أصلًا
بشاشة المشتريات بسطح المكتب (بدون نت، Tesseract محلي). هذي هنا تحتاج نت
فعلي لأنها ترسل الصورة لخدمة ذكاء اصطناعي خارجية.

⚠️ ملاحظات مهمة:
- يحتاج انترنت شغّال وقت الاستخدام، ومفتاح API صحيح، وقد يترتب عليه تكلفة
  استخدام حسب سياسة المزوّد المختار (نفس تحذير صفحة المستشار بالضبط).
- القراءة الآلية تخمين غير مضمون 100% (جودة الصورة، خط اليد، تصميم
  الفاتورة كلها تأثر على الدقة) - لازم مراجعة كل صنف قبل التأكيد الفعلي،
  تمامًا زي ميزة تصوير الفاتورة المحلية بشاشة المشتريات.
"""
import json
import re
import time
import urllib.request
import urllib.error

EXTRACTION_PROMPT = (
    "هذي صورة فاتورة شراء أدوية من صيدلية عراقية. اقرأ كل الأصناف المكتوبة "
    "بالفاتورة واطلع لي قائمة JSON فقط (بدون أي نص إضافي قبلها أو بعدها ولا "
    "حتى ```json) بهذا الشكل بالضبط:\n"
    '[{"name": "اسم الصنف كما هو مكتوب بالفاتورة", "quantity": الكمية كرقم, '
    '"unit_price": سعر الوحدة كرقم}]\n'
    "لو ما قدرت تقرأ رقم معين بوضوح، حط 0 بداله. لا تكتب أي شرح أو ملاحظات "
    "أو مقدمة، رجّع مصفوفة JSON بس ولا شي غيرها."
)

# أكواد HTTP تعتبر "مشكلة مؤقتة بخادم مزوّد الذكاء الاصطناعي نفسه" (الموديل
# مشغول/زحمة مؤقتة/الخادم متعثر لحظيًا) - مو خطأ بالصورة ولا بمفتاح الـAPI
# ولا بالبرنامج، لذا نعيد المحاولة تلقائيًا كم مرة بدل ما نفشل من أول مرة:
#   429 = طلبات كثيرة بوقت قصير (rate limit)
#   500/502/503/504 = خطأ أو ازدحام مؤقت بخادم المزوّد (بالضبط حالة
#   "UNAVAILABLE - the model is currently experiencing high demand" اللي
#   تجيها أحيانًا من Gemini)
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_RETRY_DELAYS_SECONDS = [2, 5]  # بين المحاولة الأولى والثانية، وبين الثانية والثالثة


class TransientAIError(Exception):
    """خطأ مؤقت من خادم مزوّد الذكاء الاصطناعي (ازدحام/تحميل زايد) - صار
    بعد استنفاذ كل محاولات إعادة المحاولة. نميّزه عن أخطاء ثانية (مفتاح
    خاطئ، صورة غير مفهومة...) حتى الموبايل يقدر يبيّن رسالة أوضح ويقترح
    "جرب مرة ثانية بعد لحظات" بدل رسالة عامة مربكة."""
    pass


class _HTTPCallError(Exception):
    """يغلّف urllib.error.HTTPError الأصلي مع كوده ونص رد الخادم.

    ⚠️ سبب وجود هذا الصف تحديدًا: _call_gemini_vision و
    _call_anthropic_vision كانوا (قبل هذا الإصلاح) يمسكون HTTPError
    ويحولونه فورًا لـ Exception عامة (`raise Exception(f"HTTP {e.code}...")`)
    - وهذا كان يخلي _call_with_retries تحته ما يشوف كود الخطأ (503 مثلًا)
    إطلاقًا، لأنه يفحص `isinstance(err, urllib.error.HTTPError)` بس، وبهذا
    الوقت يكون الخطأ صار Exception عادية مو HTTPError - فإعادة المحاولة ما
    كانت تشتغل أبدًا رغم وجود الكود! (بالضبط سبب "مازال ما يقرا" حتى بعد
    إضافة إعادة المحاولة). الحل: نحافظ على كود الحالة (.code) بصف مخصص
    بدل ما نحوله لـException عامة تفقد هذي المعلومة."""
    def __init__(self, code, body):
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}: {body}")


def _is_retryable_http_error(err):
    return isinstance(err, _HTTPCallError) and err.code in _RETRYABLE_HTTP_CODES


def _call_with_retries(call_fn):
    """يسوي call_fn() لين تنجح، وإذا فشلت بخطأ مؤقت (503 ازدحام الموديل
    مثلًا) يعيد المحاولة تلقائيًا (حتى 3 محاولات بالمجموع) قبل ما يستسلم -
    أخطاء ثانية (مفتاح خاطئ 401/403، طلب غلط 400) ما تنعاد محاولتها لأنها
    ما راح تنحل بإعادة المحاولة."""
    last_error = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return call_fn()
        except _HTTPCallError as e:
            last_error = e
            if not _is_retryable_http_error(e) or attempt == _MAX_ATTEMPTS - 1:
                break
            time.sleep(_RETRY_DELAYS_SECONDS[min(attempt, len(_RETRY_DELAYS_SECONDS) - 1)])
    if isinstance(last_error, _HTTPCallError) and _is_retryable_http_error(last_error):
        raise TransientAIError(
            "خدمة الذكاء الاصطناعي مزدحمة مؤقتًا حاليًا (الموديل تحت ضغط طلبات "
            "كثيرة بنفس الوقت من كل مستخدميه حول العالم) - جربنا 3 مرات وما "
            "زبطت. هذا مو خطأ بصورتك ولا بإعداداتك، جرب بعد دقيقة أو دقيقتين "
            "وراح تشتغل عادي."
        )
    raise last_error


def _call_gemini_text(api_key, prompt):
    """نفس _call_gemini_vision بس بدون صورة - نداء نصي بس (أرخص وأسرع)،
    نستخدمه للتحقق النهائي من تطابق الأدوية الغامضة (راجع
    verify_matches_with_ai)."""
    model = "gemini-3.6-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise _HTTPCallError(e.code, body) from e
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise Exception(f"رد غير متوقع من Gemini: {data}")


def _call_anthropic_text(api_key, prompt):
    """نفس _call_anthropic_vision بس بدون صورة - نص فقط."""
    payload = {
        "model": "claude-sonnet-5",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise _HTTPCallError(e.code, body) from e
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    if not parts:
        raise Exception(f"ماكو رد نصي من Claude: {data}")
    return "\n".join(parts)


_VERIFY_MATCHES_PROMPT_HEADER = (
    "انت مساعد صيدلي خبير. تحت قائمة مرقّمة: كل رقم فيه اسم دواء مستخرج من "
    "فاتورة شراء صيدلية، ومعه قائمة أدوية \"مرشحة\" من مخزون الصيدلية (كل "
    "مرشح له رقم تعريف id). لكل رقم بالقائمة، حدد: هل أي وحد من المرشحين "
    "هو نفس الدواء بالضبط - يعني نفس المادة الفعالة، ونفس التركيز/الجرعة، "
    "ونفس الشكل الصيدلاني (قرص/شراب/حقنة...)؟ اعتبرهم نفس الدواء حتى لو "
    "اختلفت طريقة كتابة الاسم (عربي مقابل إنكليزي، اختصار، ترتيب كلمات، "
    "خطأ إملائي بسيط). لو الجرعة أو الشكل الصيدلاني مختلفين فعلاً عن أي "
    "مرشح، أو ماكو مرشح يطابق أصلًا، اختر null - لا تخمّن.\n\n"
    "رجّع مصفوفة JSON فقط (بدون أي نص أو شرح إضافي قبلها أو بعدها ولا حتى "
    "```json)، فيها بالضبط نفس عدد العناصر بنفس الترتيب المعطى تحت، كل "
    'عنصر بهذا الشكل: {"chosen_id": رقم id المرشح المطابق, أو null}\n\n'
    "القائمة:\n"
)


def verify_matches_with_ai(api_key, provider, batch):
    """يتحقق من تطابق كل عنصر بـ batch مع مرشحيه عبر سؤال الذكاء الاصطناعي
    مباشرة (فهم لغوي حقيقي، مو تشابه شكل حروف) - يُستخدم بس للحالات
    "الغامضة" اللي المطابقة النصية المحلية (app/text_match.py) ما وصلت
    فيها لقرار مؤكد لحاله.

    batch: [{"query": "الاسم المستخرج من الفاتورة", "candidates":
             [{"id": 1, "name": "..."}, ...]}, ...]
    يرجع قائمة بنفس طول batch بالضبط: [chosen_id أو None, ...].

    نداء نصي واحد يغطي كل العناصر الغامضة دفعة وحدة (batch) بدل نداء
    منفصل لكل صنف - أسرع وأرخص، وأهم شي يقلل عدد نداءات الـAPI (وبالتالي
    احتمال الاصطدام بازدحام 503 يتكرر لكل صنف لحاله).

    لو فشل الاتصال بالكامل (حتى بعد إعادة المحاولة التلقائية) أو رد
    بشكل غير مفهوم، نرجّع None لكل العناصر (يعني "ماكو تطابق مؤكد، راجعه
    يدويًا") بدل ما نوقف كل عملية قراءة الفاتورة بسبب خطوة تحقق إضافية
    فشلت - الأصناف الواضحة أصلًا (تطابق شبه أكيد أو ماكو تشابه إطلاقًا)
    ما تحتاج هذا النداء أصلًا ووصلت لقرارها قبل لا نوصل هنا."""
    if not batch:
        return []
    lines = []
    for i, entry in enumerate(batch):
        cands = "، ".join(f'{c["id"]}) {c["name"]}' for c in entry["candidates"])
        lines.append(f'{i + 1}. الاسم بالفاتورة: "{entry["query"]}"\n   المرشحون: {cands}')
    prompt = _VERIFY_MATCHES_PROMPT_HEADER + "\n".join(lines)

    try:
        if provider == "gemini":
            raw_text = _call_with_retries(lambda: _call_gemini_text(api_key, prompt))
        else:
            raw_text = _call_with_retries(lambda: _call_anthropic_text(api_key, prompt))
    except Exception:
        return [None] * len(batch)

    try:
        cleaned = raw_text.strip()
        cleaned = re.sub(r"^```(json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(0)
        data = json.loads(cleaned)
        if not isinstance(data, list):
            return [None] * len(batch)
    except Exception:
        return [None] * len(batch)

    results = []
    for i in range(len(batch)):
        chosen_id = None
        if i < len(data) and isinstance(data[i], dict):
            raw_id = data[i].get("chosen_id")
            valid_ids = {c["id"] for c in batch[i]["candidates"]}
            try:
                candidate_id = int(raw_id) if raw_id is not None else None
            except (TypeError, ValueError):
                candidate_id = None
            # نتأكد إن الـid اللي رجعه فعلاً من ضمن مرشحي نفس العنصر - أي
            # قيمة ثانية (هلوسة أو رقم مو موجود بالقائمة) تعتبر "ماكو
            # تطابق" أوضح وأسلم من اعتمادها بشكل أعمى.
            if candidate_id in valid_ids:
                chosen_id = candidate_id
        results.append(chosen_id)
    return results


def extract_invoice_items(api_key, provider, image_base64, media_type="image/jpeg"):
    """يرجع قائمة dict: [{"name":..., "quantity":..., "unit_price":...}, ...]

    يعيد المحاولة تلقائيًا لو الخطأ مؤقت (ازدحام بخادم المزوّد - راجع
    TransientAIError) قبل ما يفشل نهائيًا."""
    if provider == "gemini":
        raw_text = _call_with_retries(lambda: _call_gemini_vision(api_key, image_base64, media_type))
    else:
        raw_text = _call_with_retries(lambda: _call_anthropic_vision(api_key, image_base64, media_type))
    return _parse_json_items(raw_text)


def _call_gemini_vision(api_key, image_base64, media_type, prompt=EXTRACTION_PROMPT):
    # ⚠️ إصلاح مهم: كان مكتوب "gemini-flash-latest" (alias يشاور تلقائيًا
    # لأحدث إصدار موديل عند Google، بدون سيطرة منا) - جوجل نفسها ما توصي
    # باستخدامه بالإنتاج بالضبط لهذا السبب: أي إصدار جديد يطلعوه (تجريبي/
    # preview) ينضغط عليه فورًا بكل مستخدميه حول العالم لحظة إطلاقه، فيصير
    # بالضبط سبب "الموديل مزدحم" اللي كانت تواجهه. ثبّتنا هنا موديل مستقر
    # (GA - عام ومستقر رسميًا من جوجل، مو تجريبي) بدل الـalias المتقلب،
    # حتى نتجنب هذا الازدحام الزايد المرتبط بالإصدارات الجديدة تحديدًا.
    model = "gemini-3.6-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": media_type, "data": image_base64}},
            ]
        }],
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise _HTTPCallError(e.code, body) from e
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise Exception(f"رد غير متوقع من Gemini: {data}")


def _call_anthropic_vision(api_key, image_base64, media_type, prompt=EXTRACTION_PROMPT):
    payload = {
        "model": "claude-sonnet-5",
        "max_tokens": 2000,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_base64}},
                {"type": "text", "text": prompt},
            ],
        }],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise _HTTPCallError(e.code, body) from e
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    if not parts:
        raise Exception(f"ماكو رد نصي من Claude: {data}")
    return "\n".join(parts)


def _parse_json_items(raw_text):
    """يحاول يستخرج مصفوفة JSON من رد النموذج، حتى لو حط نص إضافي حواليها
    (أو حتى ```json code fences) رغم التعليمات - نماذج الذكاء الاصطناعي
    أحيانًا ما تلتزم بالتنسيق المطلوب 100%."""
    cleaned_text = raw_text.strip()
    cleaned_text = re.sub(r"^```(json)?|```$", "", cleaned_text, flags=re.MULTILINE).strip()
    match = re.search(r"\[.*\]", cleaned_text, re.DOTALL)
    json_text = match.group(0) if match else cleaned_text
    try:
        items = json.loads(json_text)
    except json.JSONDecodeError:
        raise Exception(f"ما قدرت أفهم رد الذكاء الاصطناعي كقائمة JSON صحيحة: {raw_text[:300]}")
    if not isinstance(items, list):
        raise Exception("رد الذكاء الاصطناعي مو بشكل قائمة متوقع.")

    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            quantity = float(item.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            quantity = 0
        try:
            unit_price = float(item.get("unit_price", 0) or 0)
        except (TypeError, ValueError):
            unit_price = 0
        cleaned.append({"name": name, "quantity": quantity, "unit_price": unit_price})
    return cleaned
