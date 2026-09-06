"""
سيرفر محلي مصغر (بدون إنترنت/بدون استضافة خارجية) يشتغل تلقائيًا مع فتح
البرنامج، ويوفر صفحة ويب بسيطة تفتحها من متصفح الموبايل وانت على نفس شبكة
الواي فاي تبع الصيدلية، فيها فورمتين مطابقتين تمامًا لنفس شاشات سطح المكتب:
  1) إضافة دواء جديد (نفس حقول AddProductDialog بالضبط)
  2) تحديث/شراء لدواء موجود (نفس فكرة الإضافة اليدوية بشاشة المشتريات)

كل البيانات المرسلة تنكتب مباشرة بنفس قاعدة بيانات البرنامج - نفس النتيجة
تمامًا كأنك دخلتها من سطح المكتب.
"""
import random
import socket
from datetime import date, datetime


def _strips_from_cartons(qty_cartons, strips_per_carton):
    """يحوّل كمية بالباكيت (تقدر تكون كسرية - 0.25، 0.5... لأدوية غالية
    تُشترى بجزء من الباكيت) للكمية الفعلية بالشريط - نفس الدالة
    المستخدمة بشاشة المخزون (app/ui/inventory_view.py) بالضبط، لكن مكررة
    هنا محليًا حتى ملف السيرفر يضل مستقل بدون استيراد وحدات واجهة Qt.
    نقرّب لأقرب شريط كامل (round half up) بدل int() المباشر اللي كان
    يقطع الكسر نزولًا للصفر دائمًا - يفقد قيمة حقيقية بصمت (باكيت 3
    أشرطة، شريت ربعه = 0.75 شريط، int() يصفّرها بالكامل)."""
    return int(qty_cartons * strips_per_carton + 0.5)


from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_
import uvicorn

from app.db.database import SessionLocal
from app.db.models import Product, ProductUnit, Batch, StockMovement, PurchaseOrder, PurchaseOrderItem, Supplier, InvoiceTextMapping
from app.db.settings_helper import get_setting, set_setting
from app.text_match import rank_by_similarity, normalize_arabic

PORT = 8899
PIN_KEY = "mobile_pin"

app = FastAPI()


# ---------------------------------------------------------------- أدوات عامة
def get_or_create_pin():
    session = SessionLocal()
    try:
        pin = get_setting(session, PIN_KEY, "")
        if not pin:
            pin = f"{random.randint(0, 9999):04d}"
            set_setting(session, PIN_KEY, pin)
        return pin
    finally:
        # ملاحظة إصلاح حرج: SessionLocal صارت scoped_session مشتركة بكل
        # البرنامج (نفس الجلسة يستخدمها سطح المكتب وميزات الموبايل) - سكرها
        # هنا كان يفصل كل كائن محمّل بأي مكان ثاني بالبرنامج عن الجلسة
        # (DetachedInstanceError)، بما فيها المستخدم المسجّل دخوله بشاشة
        # البيع - يعني أول استخدام لأي ميزة بالموبايل كان يكسر زر "إتمام
        # البيع" بسطح المكتب فورًا. ما نسكر الجلسة المشتركة هذي أبدًا.
        pass


def regenerate_pin():
    session = SessionLocal()
    try:
        pin = f"{random.randint(0, 9999):04d}"
        set_setting(session, PIN_KEY, pin)
        return pin
    finally:
        # ملاحظة إصلاح حرج: SessionLocal صارت scoped_session مشتركة بكل
        # البرنامج (نفس الجلسة يستخدمها سطح المكتب وميزات الموبايل) - سكرها
        # هنا كان يفصل كل كائن محمّل بأي مكان ثاني بالبرنامج عن الجلسة
        # (DetachedInstanceError)، بما فيها المستخدم المسجّل دخوله بشاشة
        # البيع - يعني أول استخدام لأي ميزة بالموبايل كان يكسر زر "إتمام
        # البيع" بسطح المكتب فورًا. ما نسكر الجلسة المشتركة هذي أبدًا.
        pass


def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_all_lan_ips():
    """بعض أجهزة الويندوز عندها أكثر من كارت شبكة (واي فاي + إيثرنت + VPN
    وهمي...)، فنرجع كل العناوين المحتملة حتى المستخدم يجرب الصحيح لو الأول
    ما اشتغل معاه. المهم: نحط بالأول العنوان اللي get_lan_ip() لقاه (طريقة
    موثوقة تعتمد على مسار الشبكة الفعلي للإنترنت)، مو ترتيب أبجدي عشوائي -
    لأن الترتيب الأبجدي ممكن يخلي عنوان وهمي (Hyper-V / VPN / WSL) يطلع قبل
    عنوان الواي فاي الحقيقي، وهذا كان يخلي رمز QR يترمّز بعنوان ميت."""
    primary = None
    try:
        primary = get_lan_ip()
        if primary == "127.0.0.1":
            primary = None
    except Exception:
        pass

    others = set()
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                others.add(ip)
    except Exception:
        pass
    others.discard(primary)

    ordered = ([primary] if primary else []) + sorted(others)
    return ordered or ["127.0.0.1"]


def is_server_running():
    """يتحقق فعليًا (مو تخمين) إذا السيرفر المحلي شغال ومسموع على البورت."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", PORT))
        return True
    except Exception:
        return False
    finally:
        s.close()


def _check_pin(pin):
    if pin != get_or_create_pin():
        raise HTTPException(status_code=403, detail="رمز الدخول غلط")


# --------------------------------------------------------------------- بحث
@app.get("/api/products-search")
def products_search(q: str = "", pin: str = ""):
    """يبحث عن دواء بالاسم (يستخدمها خانة \"تحديث/شراء لدواء موجود\" وخانة
    تصحيح الدواء المطابق بمراجعة فاتورة مصوّرة بالذكاء الاصطناعي).

    قبل هذا التعديل كان البحث يعتمد بالكامل على تطابق حرفي جزئي (LIKE) باسم
    الدواء التجاري بس - أي فرق بسيط بالكتابة (همزة/ألف، تاء مربوطة، حرف
    ناقص أو زايد، أو حتى كتابة الاسم بالإنكليزي بينما هو مسجّل بالعربي)
    كان يرجّع قائمة فاضية بالكامل، فيبين للمستخدم وكأن "القراءة فشلت" رغم
    إن الدواء موجود فعليًا بالمخزون باسم قريب.

    الحين: نجرّب أول تطابق حرفي مباشر (بالاسم التجاري أو الاسم العلمي -
    أسرع طريقة وتغطي أغلب الحالات)، وإذا كانت النتائج قليلة (أقل من 5) أو
    ماكو نتائج إطلاقًا، نكمّل بمطابقة ذكية متسامحة (نفس منطق قراءة فاتورة
    الذكاء الاصطناعي بالضبط - راجع app/text_match.py) على بقية الأدوية
    المفعّلة، حتى نضمن رجوع أقرب 5 اقتراحات موجودة فعليًا دائمًا بدل قائمة
    فاضية، مرتبة من الأقرب للأبعد."""
    _check_pin(pin)
    session = SessionLocal()
    try:
        query_text = (q or "").strip()
        if not query_text:
            # نفس سلوك النسخة الأصلية بالضبط لخانة بحث فاضية: أول 15 دواء
            # مفعّل أبجديًا (يُستخدم أيضًا كفحص بسيط لصحة رمز PIN عند فتح
            # الصفحة - checkPinValid() بالأسفل تسوي نفس هذا الطلب بـ q فاضية
            # وتتأكد بس من status الرد، بس نرجّع نفس شكل البيانات المتوقع
            # زيادة أمان حتى لو استخدمها كود ثاني بالمستقبل).
            products = (
                session.query(Product)
                .filter(Product.is_active == True)
                .order_by(Product.name)
                .limit(15)
                .all()
            )
            return [{"id": p.id, "name": p.name, "strips_per_carton": p.strips_per_carton or 3} for p in products]

        SUGGESTIONS_LIMIT = 5
        like = f"%{query_text}%"
        direct_matches = (
            session.query(Product)
            .filter(
                Product.is_active == True,
                or_(Product.name.ilike(like), Product.generic_name.ilike(like)),
            )
            .order_by(Product.name)
            .limit(30)
            .all()
        )

        ranked = [(p.id, p.name, p.strips_per_carton) for p in direct_matches]

        if len(ranked) < SUGGESTIONS_LIMIT:
            # نكمّل بمطابقة متسامحة (اختلاف كتابة/إملاء) على بقية الأدوية
            # المفعّلة اللي ما طلعت أصلًا بالتطابق الحرفي المباشر فوق - نجيب
            # بس (id, name, generic_name) خفيفة بدل الكائن الكامل حتى تضل
            # سريعة حتى مع كتالوج أدوية كبير.
            already_ids = {pid for pid, _, _ in ranked}
            pool_query = session.query(Product.id, Product.name, Product.generic_name, Product.strips_per_carton).filter(
                Product.is_active == True
            )
            if already_ids:
                pool_query = pool_query.filter(~Product.id.in_(already_ids))
            pool = pool_query.all()
            spc_by_id = {pid: spc for pid, _, _, spc in pool}
            fuzzy_candidates = [(pid, name, generic) for pid, name, generic, _ in pool]
            fuzzy_ranked = rank_by_similarity(query_text, fuzzy_candidates, limit=SUGGESTIONS_LIMIT * 3)
            for pid, name, ratio in fuzzy_ranked:
                if ratio <= 0:
                    continue
                ranked.append((pid, name, spc_by_id.get(pid, 3)))

        return [
            {"id": pid, "name": name, "strips_per_carton": spc or 3}
            for pid, name, spc in ranked[:SUGGESTIONS_LIMIT]
        ]
    finally:
        # ملاحظة إصلاح حرج: SessionLocal صارت scoped_session مشتركة بكل
        # البرنامج (نفس الجلسة يستخدمها سطح المكتب وميزات الموبايل) - سكرها
        # هنا كان يفصل كل كائن محمّل بأي مكان ثاني بالبرنامج عن الجلسة
        # (DetachedInstanceError)، بما فيها المستخدم المسجّل دخوله بشاشة
        # البيع - يعني أول استخدام لأي ميزة بالموبايل كان يكسر زر "إتمام
        # البيع" بسطح المكتب فورًا. ما نسكر الجلسة المشتركة هذي أبدًا.
        pass


# ------------------------------------------------------------- إضافة دواء جديد
class NewProductPayload(BaseModel):
    pin: str
    name: str
    generic_name: str = ""
    manufacturer: str = ""
    category: str = ""
    barcode: str = ""
    strips_per_carton: float = 3
    carton_cost: float = 0
    sale_price: float = 0
    carton_price: float = 0
    qty_cartons: float = 0
    bonus_cartons: float = 0  # هدية/بونص بالباكيت (اختياري) - نفس معادلة restock()
    min_threshold: float = 10
    expiry: str = ""  # YYYY-MM-DD
    supplier_name: str = ""
    receipt_number: str = ""
    receipt_date: str = ""  # YYYY-MM-DD - تاريخ الوصل (تلقائي بتاريخ اليوم من الواجهة، قابل للتعديل)


@app.post("/api/add-product")
def add_product(payload: NewProductPayload):
    _check_pin(payload.pin)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="لازم تدخل اسم الدواء.")
    session = SessionLocal()
    try:
        # نفس منطق شاشة إضافة دواء بالحاسوب: لو ما دخل سعر بيع الشريط، نعتبر
        # المنتج "علبة وحدة بس" (بدون أشرطة) - عدد الأشرطة = 1 تلقائيًا، ونوحّد
        # سعر بيع الشريط مع سعر بيع العلبة (أي وحد فيهم مُدخل ينعبّي بالثاني)،
        # حتى قائمة البيع تعرض نفس السعر لأي وحدة يبيعها الكاشير.
        spc = payload.strips_per_carton or 3
        sale_price = payload.sale_price
        carton_price = payload.carton_price
        if sale_price == 0:
            spc = 1
        if spc == 1:
            sale_price = sale_price or carton_price
            carton_price = carton_price or sale_price
        original_qty = payload.qty_cartons or 0
        bonus_qty = payload.bonus_cartons or 0
        total_qty = original_qty + bonus_qty
        qty = _strips_from_cartons(total_qty, spc)

        product = Product(
            name=payload.name.strip(), generic_name=payload.generic_name.strip(),
            manufacturer=payload.manufacturer.strip(), category=payload.category.strip(),
            barcode=payload.barcode.strip(), base_unit="شريط", is_custom=True,
            sale_price=sale_price, wholesale_price=0,
            carton_price=carton_price, min_stock_threshold=payload.min_threshold,
            strips_per_carton=spc, carton_purchase_price=payload.carton_cost,
        )
        session.add(product)
        session.flush()
        for unit_name, factor in [("شريط", 1), ("علبة", spc)]:
            session.add(ProductUnit(product_id=product.id, unit_name=unit_name, conversion_factor=factor))
        if qty > 0:
            # المورد (اختياري) - نفس منطق تبويب "تحديث/شراء": نبحث عن مورد
            # بنفس الاسم، ولو ما موجود ننشئه تلقائيًا (يغني عن زر "مورد جديد"
            # منفصل). لو ماكو اسم مدخل، الكمية المستلمة تنسجل بدون مورد
            # محدد (متل ما كان يصير قبل هذا التعديل).
            supplier_id = None
            supplier_name = payload.supplier_name.strip()
            if supplier_name:
                supplier = session.query(Supplier).filter(Supplier.name.ilike(supplier_name)).first()
                if not supplier:
                    supplier = Supplier(name=supplier_name)
                    session.add(supplier)
                    session.flush()
                supplier_id = supplier.id

            # فاتورة شراء بسيطة لهذا الاستلام الأولي - عشان يظهر بإجمالي
            # مشتريات المورد بشاشة "الموردون والحسابات" بالمشتريات، تمامًا
            # متل أي إضافة عن طريق تبويب "تحديث/شراء".
            #
            # دعم الهدية/البونص (bonus_qty): نفس معادلة restock() بالضبط -
            # إجمالي الفاتورة يبقى original_qty × carton_cost (بدون طرح)،
            # ويتوزّع على الكمية الكلية المستلمة (original_qty + bonus_qty).
            net_total = original_qty * payload.carton_cost
            effective_unit_cost = (net_total / total_qty) if total_qty else payload.carton_cost
            effective_strip_cost = (effective_unit_cost / spc) if spc else 0
            bonus_strip_qty = _strips_from_cartons(bonus_qty, spc) if bonus_qty else 0

            receipt_number = payload.receipt_number.strip() or None
            order_date = date.fromisoformat(payload.receipt_date) if payload.receipt_date else None
            order = PurchaseOrder(
                supplier_id=supplier_id, status="confirmed", source="موبايل",
                total_amount=net_total,
                receipt_number=receipt_number, order_date=order_date or datetime.now(),
            )
            session.add(order)
            session.flush()
            session.add(PurchaseOrderItem(
                purchase_order_id=order.id, product_id=product.id,
                quantity=total_qty, unit_cost=effective_unit_cost, bonus_quantity=bonus_qty,
            ))

            expiry_date = date.fromisoformat(payload.expiry) if payload.expiry else None
            session.add(Batch(
                product_id=product.id, batch_number=f"PO-{order.id}-{product.id}",
                expiry_date=expiry_date, purchase_price=effective_strip_cost,
                quantity_received=qty, quantity_available=qty,
                supplier_id=supplier_id, receipt_number=receipt_number,
                carton_purchase_price=effective_unit_cost, carton_strips_per_carton=spc,
                bonus_quantity=bonus_strip_qty,
            ))
        session.commit()
        return {
            "ok": True, "message": f"تمت إضافة \"{product.name}\" بنجاح.",
            "product_id": product.id, "product_name": product.name,
            "strips_per_carton": product.strips_per_carton,
        }
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # ملاحظة إصلاح حرج: SessionLocal صارت scoped_session مشتركة بكل
        # البرنامج (نفس الجلسة يستخدمها سطح المكتب وميزات الموبايل) - سكرها
        # هنا كان يفصل كل كائن محمّل بأي مكان ثاني بالبرنامج عن الجلسة
        # (DetachedInstanceError)، بما فيها المستخدم المسجّل دخوله بشاشة
        # البيع - يعني أول استخدام لأي ميزة بالموبايل كان يكسر زر "إتمام
        # البيع" بسطح المكتب فورًا. ما نسكر الجلسة المشتركة هذي أبدًا.
        pass


# ---------------------------------------------------------- تحديث/شراء دواء موجود
class RestockBatchItemPayload(BaseModel):
    """صنف وحد ضمن استلام دفعة (راجع RestockBatchPayload تحت)."""
    product_id: int
    qty_cartons: float
    bonus_cartons: float = 0
    carton_cost: float
    expiry: str = ""
    source_extracted_name: str = ""


class RestockBatchPayload(BaseModel):
    """استلام عدة أصناف مع بعض بنفس فاتورة الشراء (مورد/رقم وصل/تاريخ
    مشترك) - راجع /api/restock-batch. هذا يحل خلل كان موجود سابقًا: كل
    صنف كان يطلع فاتورة شراء منفصلة بدل فاتورة وحدة فيها كل الأصناف."""
    pin: str
    supplier_name: str = ""
    receipt_number: str = ""
    receipt_date: str = ""
    items: list[RestockBatchItemPayload]


class RestockPayload(BaseModel):
    pin: str
    product_id: int
    qty_cartons: float
    bonus_cartons: float = 0  # هدية/بونص بالباكيت (اختياري) - راجع شرح المعادلة بدالة restock()
    carton_cost: float
    expiry: str = ""
    supplier_name: str = ""
    receipt_number: str = ""
    receipt_date: str = ""  # YYYY-MM-DD
    # النص الخام كما استخرجه الذكاء الاصطناعي من صورة الفاتورة (لو الاستلام
    # هذا جاي من تأكيد تصوير فاتورة، مو تحديث/شراء يدوي) - لو موجود، نحفظ
    # "ذاكرة" (النص ↔ هذا الدواء) حتى المرة الجاية نفس النص ينطابق فورًا
    # بدون تخمين. راجع app.db.models.InvoiceTextMapping.
    source_extracted_name: str = ""


@app.get("/api/suppliers-search")
def suppliers_search(q: str = "", pin: str = ""):
    _check_pin(pin)
    session = SessionLocal()
    try:
        like = f"%{q}%"
        suppliers = (
            session.query(Supplier)
            .filter(Supplier.name.ilike(like))
            .order_by(Supplier.name)
            .limit(10)
            .all()
        )
        return [{"id": s.id, "name": s.name} for s in suppliers]
    finally:
        # ملاحظة إصلاح حرج: SessionLocal صارت scoped_session مشتركة بكل
        # البرنامج (نفس الجلسة يستخدمها سطح المكتب وميزات الموبايل) - سكرها
        # هنا كان يفصل كل كائن محمّل بأي مكان ثاني بالبرنامج عن الجلسة
        # (DetachedInstanceError)، بما فيها المستخدم المسجّل دخوله بشاشة
        # البيع - يعني أول استخدام لأي ميزة بالموبايل كان يكسر زر "إتمام
        # البيع" بسطح المكتب فورًا. ما نسكر الجلسة المشتركة هذي أبدًا.
        pass


@app.post("/api/restock-batch")
def restock_batch(payload: RestockBatchPayload):
    """يستلم عدة أصناف مع بعض بضغطة وحدة، وينشئ لهن **فاتورة شراء وحدة**
    (PurchaseOrder وحد فيه عدة PurchaseOrderItem) - بدل ما ينشئ فاتورة شراء
    منفصلة لكل صنف لحاله.

    ⚠️ إصلاح خلل حقيقي: /api/restock (فوق) يُستدعى مرة لكل صنف - فتأكيد
    فاتورة مصوّرة فيها 8 أصناف كان يطلع 8 فواتير شراء منفصلة بسجل
    المشتريات (كل وحدة برقم فاتورة مختلف، رغم نفس المورد ونفس رقم الوصل
    ونفس التاريخ!) بدل فاتورة وحدة فيها 8 أصناف - بالضبط زي فاتورة شراء
    حقيقية عندها عدة أصناف. هذا الـendpoint يصلحها: كل الأصناف يرتبطون
    بنفس PurchaseOrder وحد، ومبلغ الفاتورة الإجمالي = مجموع كل الأصناف.

    يشتغل من: تأكيد تصوير الفاتورة (confirmScanResults)، وتبويب
    "تحديث/شراء" (لما تضيفين أكثر من دواء لنفس الجلسة قبل التأكيد)."""
    _check_pin(payload.pin)
    if not payload.items:
        raise HTTPException(status_code=400, detail="ماكو أصناف للتحديث.")
    session = SessionLocal()
    try:
        supplier_id = None
        supplier_name = payload.supplier_name.strip()
        if supplier_name:
            supplier = session.query(Supplier).filter(Supplier.name.ilike(supplier_name)).first()
            if not supplier:
                supplier = Supplier(name=supplier_name)
                session.add(supplier)
                session.flush()
            supplier_id = supplier.id

        receipt_number = payload.receipt_number.strip() or None
        order_date = date.fromisoformat(payload.receipt_date) if payload.receipt_date else None

        order = PurchaseOrder(
            supplier_id=supplier_id, status="confirmed", source="موبايل",
            total_amount=0,  # نحدّثه بالنهاية بعد ما نجمع كل الأصناف
            receipt_number=receipt_number, order_date=order_date or datetime.now(),
        )
        session.add(order)
        session.flush()

        total_amount = 0.0
        added_count = 0
        errors = []
        for item in payload.items:
            product = session.query(Product).get(item.product_id)
            if not product:
                errors.append(f"دواء #{item.product_id} مو موجود")
                continue
            spc = product.strips_per_carton or 3
            original_qty = item.qty_cartons or 0
            bonus_qty = item.bonus_cartons or 0
            total_qty = original_qty + bonus_qty
            nominal_price = item.carton_cost
            net_total = original_qty * nominal_price
            effective_unit_cost = (net_total / total_qty) if total_qty else nominal_price
            base_qty = _strips_from_cartons(total_qty, spc)
            bonus_strip_qty = _strips_from_cartons(bonus_qty, spc) if bonus_qty else 0
            strip_cost = (effective_unit_cost / spc) if spc else 0

            session.add(PurchaseOrderItem(
                purchase_order_id=order.id, product_id=product.id,
                quantity=total_qty, unit_cost=effective_unit_cost, bonus_quantity=bonus_qty,
            ))
            expiry_date = date.fromisoformat(item.expiry) if item.expiry else None
            batch = Batch(
                product_id=product.id, batch_number=f"PO-{order.id}-{product.id}",
                expiry_date=expiry_date, purchase_price=strip_cost,
                quantity_received=base_qty, quantity_available=base_qty,
                supplier_id=supplier_id, receipt_number=receipt_number,
                carton_purchase_price=effective_unit_cost, carton_strips_per_carton=spc,
                bonus_quantity=bonus_strip_qty,
            )
            session.add(batch)
            session.flush()
            movement_note = f"استلام من الموبايل ({original_qty:g} باكيت × {spc} شريط)"
            if bonus_qty:
                movement_note = f"استلام من الموبايل ({original_qty:g} + هدية {bonus_qty:g} باكيت × {spc} شريط)"
            session.add(StockMovement(
                batch_id=batch.id, movement_type="شراء", quantity=base_qty,
                note=movement_note,
            ))
            total_amount += net_total
            added_count += 1

            raw_text = item.source_extracted_name.strip()
            if raw_text:
                norm = normalize_arabic(raw_text)
                if norm:
                    existing = session.query(InvoiceTextMapping).filter_by(normalized_text=norm).first()
                    if existing:
                        existing.product_id = product.id
                    else:
                        session.add(InvoiceTextMapping(normalized_text=norm, product_id=product.id))

        if added_count == 0:
            session.rollback()
            raise HTTPException(status_code=400, detail="ماكو أصناف صحيحة انضافت: " + "، ".join(errors))

        order.total_amount = total_amount
        session.commit()
        msg = f"تم تحديث المخزون بفاتورة واحدة تحتوي {added_count} صنف."
        if errors:
            msg += " (تعذّر: " + "، ".join(errors) + ")"
        return {"ok": True, "message": msg, "added_count": added_count, "errors": errors}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        pass


@app.post("/api/restock")
def restock(payload: RestockPayload):
    """يستلم دفعة جديدة لدواء موجود بالمخزون (نفس منطق الإضافة اليدوية
    بشاشة المشتريات بسطح المكتب، راجع PurchaseOrderItem.bonus_quantity
    بملف models.py للمعادلة الكاملة بمثال).

    دعم الهدية/البونص: لو bonus_cartons أكبر من صفر، إجمالي الفاتورة يبقى
    نفسه دائمًا (qty_cartons × carton_cost - بدون أي طرح)، ويتوزّع على
    الكمية الكلية المستلمة فعليًا (qty_cartons + bonus_cartons) - فيصير
    السعر الفعلي للوحدة أقل تلقائيًا كل ما زادت الهدية، بنفس معادلة زر
    \"إضافة للفاتورة\" بشاشة المشتريات بالحاسوب بالضبط."""
    _check_pin(payload.pin)
    session = SessionLocal()
    try:
        product = session.query(Product).get(payload.product_id)
        if not product:
            raise HTTPException(status_code=404, detail="الدواء مو موجود.")
        spc = product.strips_per_carton or 3

        original_qty = payload.qty_cartons or 0
        bonus_qty = payload.bonus_cartons or 0
        total_qty = original_qty + bonus_qty
        nominal_price = payload.carton_cost
        net_total = original_qty * nominal_price
        effective_unit_cost = (net_total / total_qty) if total_qty else nominal_price

        base_qty = _strips_from_cartons(total_qty, spc)
        bonus_strip_qty = _strips_from_cartons(bonus_qty, spc) if bonus_qty else 0
        strip_cost = (effective_unit_cost / spc) if spc else 0

        supplier_id = None
        supplier_name = payload.supplier_name.strip()
        if supplier_name:
            supplier = session.query(Supplier).filter(Supplier.name.ilike(supplier_name)).first()
            if not supplier:
                supplier = Supplier(name=supplier_name)
                session.add(supplier)
                session.flush()
            supplier_id = supplier.id

        receipt_number = payload.receipt_number.strip() or None
        order_date = date.fromisoformat(payload.receipt_date) if payload.receipt_date else None
        order = PurchaseOrder(
            supplier_id=supplier_id, status="confirmed", source="موبايل",
            total_amount=net_total,
            receipt_number=receipt_number, order_date=order_date or datetime.now(),
        )
        session.add(order)
        session.flush()
        session.add(PurchaseOrderItem(
            purchase_order_id=order.id, product_id=product.id,
            quantity=total_qty, unit_cost=effective_unit_cost, bonus_quantity=bonus_qty,
        ))
        expiry_date = date.fromisoformat(payload.expiry) if payload.expiry else None
        batch = Batch(
            product_id=product.id, batch_number=f"PO-{order.id}-{product.id}",
            expiry_date=expiry_date, purchase_price=strip_cost,
            quantity_received=base_qty, quantity_available=base_qty,
            supplier_id=supplier_id, receipt_number=receipt_number,
            carton_purchase_price=effective_unit_cost, carton_strips_per_carton=spc,
            bonus_quantity=bonus_strip_qty,
        )
        session.add(batch)
        session.flush()
        movement_note = f"استلام من الموبايل ({original_qty:g} باكيت × {spc} شريط)"
        if bonus_qty:
            movement_note = f"استلام من الموبايل ({original_qty:g} + هدية {bonus_qty:g} باكيت × {spc} شريط)"
        session.add(StockMovement(
            batch_id=batch.id, movement_type="شراء", quantity=base_qty,
            note=movement_note,
        ))

        # نحفظ/نحدّث "ذاكرة" المطابقة لو هذا الاستلام جاي من تأكيد تصوير
        # فاتورة (source_extracted_name موجود) - راجع تعليق الحقل بـ
        # RestockPayload فوق.
        raw_text = payload.source_extracted_name.strip()
        if raw_text:
            norm = normalize_arabic(raw_text)
            if norm:
                existing = session.query(InvoiceTextMapping).filter_by(normalized_text=norm).first()
                if existing:
                    existing.product_id = product.id
                else:
                    session.add(InvoiceTextMapping(normalized_text=norm, product_id=product.id))

        session.commit()
        return {"ok": True, "message": f"تم تحديث مخزون \"{product.name}\" بنجاح."}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # ملاحظة إصلاح حرج: SessionLocal صارت scoped_session مشتركة بكل
        # البرنامج (نفس الجلسة يستخدمها سطح المكتب وميزات الموبايل) - سكرها
        # هنا كان يفصل كل كائن محمّل بأي مكان ثاني بالبرنامج عن الجلسة
        # (DetachedInstanceError)، بما فيها المستخدم المسجّل دخوله بشاشة
        # البيع - يعني أول استخدام لأي ميزة بالموبايل كان يكسر زر "إتمام
        # البيع" بسطح المكتب فورًا. ما نسكر الجلسة المشتركة هذي أبدًا.
        pass


# ------------------------------------------------------- تصوير فاتورة بالذكاء الاصطناعي
class ScanInvoiceRequest(BaseModel):
    pin: str
    image_base64: str  # بدون البادئة "data:image/...;base64,"
    media_type: str = "image/jpeg"


@app.post("/api/scan-invoice")
def scan_invoice(payload: ScanInvoiceRequest):
    """يقرأ صورة فاتورة شراء بالذكاء الاصطناعي (Gemini/Anthropic حسب
    الإعدادات) ويستخرج بنودها، ثم يطابق كل صنف مع المخزون الحالي (نفس
    منطق مطابقة الأسماء المستخدم بميزة OCR المحلية بسطح المكتب) قبل ما
    يرجّعها للموبايل للمراجعة النهائية من المستخدم."""
    _check_pin(payload.pin)
    session = SessionLocal()
    try:
        api_key = get_setting(session, "ai_api_key", "")
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="ماكو مفتاح API محفوظ للذكاء الاصطناعي. روح لشاشة الإعدادات بالحاسوب وضيفه أول (نفس مفتاح المستشار الذكي).",
            )
        provider = get_setting(session, "ai_provider", "gemini")

        from app.ai_vision_helper import extract_invoice_items, TransientAIError
        try:
            items = extract_invoice_items(api_key, provider, payload.image_base64, payload.media_type)
        except TransientAIError as e:
            # ازدحام مؤقت بخادم المزوّد (503 وما شابه) - رسالة واضحة إنه
            # مو خطأ بالصورة، وإنه جرّب تلقائيًا كم مرة قبل ما يوصل لهذا.
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"صار خطأ بقراءة الفاتورة بالذكاء الاصطناعي: {e}")

        if not items:
            raise HTTPException(status_code=400, detail="ما قدر الذكاء الاصطناعي يلقى أي صنف واضح بالصورة. جرب صورة أوضح.")

        # مطابقة كل صنف مع المخزون: قاعدة صارمة تمنع خلط جرعات/أشكال
        # صيدلانية مختلفة (مثلًا "أوجمنتين 625" ما ينخلط بـ"أوجمنتين 1
        # غم")، وتحقق إضافي من الذكاء الاصطناعي نفسه (فهم لغوي حقيقي، مو
        # تشابه شكل حروف بس) للحالات الغامضة - راجع
        # _match_items_with_ai_verification بملف purchase_view.py (نفس
        # المنطق بالضبط المستخدم بميزة التصوير بسطح المكتب، حتى النتيجة
        # تكون متسقة بين الموبايل والحاسوب).
        from app.ui.purchase_view import _match_items_with_ai_verification
        products_for_matching = [
            (p.id, p.name, p.generic_name)
            for p in session.query(Product).filter(Product.is_active == True).all()
        ]
        # ذاكرة تصحيحات سابقة (راجع app.db.models.InvoiceTextMapping) - أي
        # نص اتصحح يدويًا قبل كذا (من الموبايل أو الحاسوب، ما يفرق) ينطابق
        # فورًا هنا بدون أي تخمين.
        memory_lookup = {
            m.normalized_text: m.product_id
            for m in session.query(InvoiceTextMapping).all()
        }
        matched_lines = _match_items_with_ai_verification(
            api_key, provider, items, products_for_matching, memory_lookup,
        )

        results = []
        for line in matched_lines:
            pid = line["matched_id"]
            matched_product = session.query(Product).get(pid) if pid else None
            results.append({
                "extracted_name": line["raw"],
                "matched_product_id": pid,
                "matched_product_name": matched_product.name if matched_product else None,
                "match_confidence": round(line["confidence"], 2),
                "ai_verified": line["ai_verified"],
                "from_memory": line.get("from_memory", False),
                "quantity": line["qty"],
                "unit_price": line["price"],
                "strips_per_carton": (matched_product.strips_per_carton if matched_product else 3) or 3,
            })
        return {"ok": True, "items": results}
    except HTTPException:
        raise
    finally:
        # ملاحظة إصلاح حرج: SessionLocal صارت scoped_session مشتركة بكل
        # البرنامج (نفس الجلسة يستخدمها سطح المكتب وميزات الموبايل) - سكرها
        # هنا كان يفصل كل كائن محمّل بأي مكان ثاني بالبرنامج عن الجلسة
        # (DetachedInstanceError)، بما فيها المستخدم المسجّل دخوله بشاشة
        # البيع - يعني أول استخدام لأي ميزة بالموبايل كان يكسر زر "إتمام
        # البيع" بسطح المكتب فورًا. ما نسكر الجلسة المشتركة هذي أبدًا.
        pass


# ------------------------------------------------------------------- الصفحة
@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_PAGE


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>إضافة دواء - H1</title>
<style>
  :root{--teal-800:#15803D;--teal-600:#16A34A;--panel:#FFFFFF;--line:#E5E7EB;--ink:#111827;--ink2:#6B7280;--bg:#F8FAFC;}
  *{box-sizing:border-box;}
  body{font-family:'Segoe UI',Tahoma,sans-serif;background:var(--bg);color:var(--ink);margin:0;padding:0;}
  .topbar{background:linear-gradient(180deg,#15803D,#166534);color:#fff;padding:16px 18px;font-weight:800;font-size:18px;}
  .wrap{max-width:520px;margin:0 auto;padding:14px;}
  .tabs{display:flex;gap:8px;margin-bottom:14px;}
  .tab-btn{flex:1;padding:12px;border-radius:10px;border:1px solid var(--line);background:#fff;color:var(--ink2);font-weight:700;font-size:14px;}
  .tab-btn.active{background:linear-gradient(180deg,#16A34A,#15803D);color:#fff;border-color:transparent;}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px;}
  .section-label{font-weight:800;color:var(--teal-800);font-size:13px;margin:14px 0 8px;}
  label{display:block;font-size:13px;color:var(--ink2);margin-bottom:5px;margin-top:12px;}
  input, select{width:100%;padding:11px;border:1px solid var(--line);border-radius:9px;font-size:15px;background:#fff;color:var(--ink);}
  input:focus, select:focus{outline:2px solid var(--teal-600);}
  .preview{color:var(--ink2);font-size:12px;margin-top:4px;}
  .save-btn{width:100%;padding:14px;margin-top:18px;border:none;border-radius:10px;background:linear-gradient(180deg,#16A34A,#15803D);color:#fff;font-weight:800;font-size:16px;}
  .save-btn:active{opacity:.85;}
  .msg{padding:12px;border-radius:10px;margin-bottom:14px;font-size:14px;display:none;}
  .msg.ok{background:#DCFCE7;color:#15803D;border:1px solid #DCFCE7;}
  .msg.err{background:#FEF2F2;color:#DC2626;border:1px solid #FECACA;}
  #pinGate{position:fixed;inset:0;background:var(--bg);display:flex;align-items:center;justify-content:center;padding:20px;z-index:99;}
  #pinGate .card{width:100%;max-width:340px;text-align:center;}
  .hidden{display:none !important;}
  datalist{}
  .autocomplete-wrap{position:relative;}
  .ac-list{position:absolute;top:100%;right:0;left:0;background:#fff;border:1px solid var(--line);border-radius:9px;max-height:200px;overflow-y:auto;z-index:10;display:none;}
  .ac-item{padding:10px;font-size:14px;border-bottom:1px solid #F0F0F0;}
  .ac-item:active{background:#DCFCE7;}
</style>
</head>
<body>

<div id="pinGate">
  <div class="card">
    <div class="section-label" style="font-size:16px;margin-top:0;">🔒 رمز الدخول</div>
    <p style="color:var(--ink2);font-size:13px;">أدخل رمز الـPIN المعروض ببرنامج H1 (تبويب المشتريات)</p>
    <input id="pinInput" inputmode="numeric" placeholder="0000" style="text-align:center;font-size:22px;letter-spacing:6px;">
    <button class="save-btn" onclick="submitPin()">دخول</button>
    <div id="pinErr" style="color:#DC2626;font-size:13px;margin-top:10px;"></div>
  </div>
</div>

<div id="mainApp" class="hidden">
  <div class="topbar">💊 H1 - إضافة وتحديث الأدوية</div>
  <div class="wrap">
    <div class="msg" id="msgBox"></div>
    <div class="tabs">
      <button class="tab-btn active" id="tabNewBtn" onclick="showTab('new')">➕ دواء جديد</button>
      <button class="tab-btn" id="tabRestockBtn" onclick="showTab('restock')">🔄 تحديث / شراء</button>
      <button class="tab-btn" id="tabScanBtn" onclick="showTab('scan')">📷 فاتورة</button>
    </div>

    <!-- ===== فورمة دواء جديد (نفس حقول شاشة إضافة دواء بسطح المكتب) ===== -->
    <div class="card" id="tabNew">
      <label>الاسم التجاري</label>
      <input id="n_name" placeholder="مثال: بانادول">
      <label>الاسم العلمي</label>
      <input id="n_generic" placeholder="مثال: باراسيتامول">
      <label>الشركة المصنعة</label>
      <input id="n_manufacturer">
      <label>التصنيف</label>
      <input id="n_category">
      <label>الباركود</label>
      <input id="n_barcode" placeholder="مسح أو إدخال يدوي">

      <div class="section-label">— الشراء (دائمًا بالباكيت) —</div>
      <label>عدد الأشرطة بالباكيت</label>
      <input id="n_spc" type="number" value="3">
      <label>سعر شراء الباكيت</label>
      <input id="n_carton_cost" type="number" value="0">
      <div class="preview" id="n_strip_cost_preview">سعر شراء الشريط (تلقائي): 0 د.ع</div>

      <div class="section-label">— أسعار البيع —</div>
      <label>سعر بيع الشريط</label>
      <input id="n_sale_price" type="number" value="0">
      <label>سعر بيع الباكيت/العلبة</label>
      <input id="n_carton_price" type="number" value="0">

      <div class="section-label">— الكمية المستلمة الآن —</div>
      <label>المورد (اختياري)</label>
      <div class="autocomplete-wrap">
        <input id="n_supplier" placeholder="اكتب اسم المورد... (لو جديد راح ينضاف تلقائيًا)" autocomplete="off">
        <div class="ac-list" id="n_supplier_ac_list"></div>
      </div>
      <label>رقم الوصل (اختياري)</label>
      <input id="n_receipt_number" placeholder="رقم وصل الاستلام من المورد إن وجد...">
      <label>تاريخ الوصل</label>
      <input id="n_receipt_date" type="date">
      <label>الكمية (بالباكيت)</label>
      <input id="n_qty_cartons" type="number" step="0.01" min="0" value="0">
      <div class="preview" id="n_qty_strips_preview">الكمية بالشريط (تلقائي): 0</div>
      <label>هدية/بونص (بالباكيت - اختياري)</label>
      <input id="n_bonus" type="number" step="0.01" min="0" value="0" placeholder="0">
      <div class="preview" id="n_bonus_preview"></div>

      <label>الحد الأدنى للتنبيه (بالشريط)</label>
      <input id="n_min_threshold" type="number" value="10">
      <label>تاريخ الصلاحية</label>
      <input id="n_expiry" type="date">

      <button class="save-btn" onclick="submitNewProduct()">💾 حفظ الدواء الجديد</button>
    </div>

    <!-- ===== فورمة تحديث/شراء (نفس فكرة الإضافة اليدوية بشاشة المشتريات) ===== -->
    <div class="card hidden" id="tabRestock">
      <label>المورد (اختياري)</label>
      <div class="autocomplete-wrap">
        <input id="r_supplier" placeholder="اكتب اسم المورد..." autocomplete="off">
        <div class="ac-list" id="r_supplier_ac_list"></div>
      </div>
      <label>رقم الوصل (اختياري)</label>
      <input id="r_receipt_number" placeholder="رقم وصل الاستلام من المورد إن وجد...">
      <label>تاريخ الوصل</label>
      <input id="r_receipt_date" type="date">

      <hr style="margin:16px 0;border:none;border-top:1px solid var(--line);">

      <!-- ⚠️ إعادة تصميم: قبل هذا كانت الخانة تسمح بإضافة دواء واحد بس
      لكل عملية حفظ (كل ضغطة "أضف للمخزون" تنشئ فاتورة شراء منفصلة كاملة).
      الحين نفس فلسفة "تصوير الفاتورة" بالضبط: تضيفين دواء لقائمة الفاتورة
      (زر "أضف للفاتورة")، وتكررين لباقي الأدوية، وبالنهاية "تأكيد" وحدة
      تنشئ فاتورة شراء واحدة فيها كل الأصناف مع بعض - نفس شاشة الحاسوب. -->
      <label>الدواء</label>
      <div class="autocomplete-wrap">
        <input id="r_search" placeholder="اكتب اسم الدواء..." autocomplete="off">
        <div class="ac-list" id="r_ac_list"></div>
      </div>
      <input type="hidden" id="r_product_id">
      <button type="button" style="width:100%;margin-top:6px;padding:8px;border:1px solid #DC2626;border-radius:9px;background:#FEF2F2;color:#DC2626;font-weight:700;font-size:13px;"
        onclick="goAddNewProductFromRestock()">➕ ماكو هذا الدواء بمخزونك؟ أضفه كدواء جديد</button>

      <label>الكمية (بالباكيت)</label>
      <input id="r_qty" type="number" step="0.01" min="0" value="0">
      <label>هدية/بونص (بالباكيت - اختياري)</label>
      <input id="r_bonus" type="number" step="0.01" min="0" value="0" placeholder="0">
      <label>سعر شراء الباكيت (الجديد)</label>
      <input id="r_cost" type="number" value="0">
      <label>تاريخ الصلاحية لهذي الدفعة</label>
      <input id="r_expiry" type="date">

      <button class="save-btn" onclick="addToRestockCart()">➕ أضف للفاتورة</button>

      <div id="restock_cart_wrap" class="hidden" style="margin-top:16px;">
        <label style="margin-top:0;">الأصناف المضافة لهذي الفاتورة</label>
        <div id="restock_cart_list"></div>
        <button class="save-btn" style="margin-top:10px;background:#16A34A;" onclick="confirmRestockCart()">✅ تأكيد وتحديث المخزون</button>
      </div>
    </div>

    <!-- ===== فورمة تصوير فاتورة بالذكاء الاصطناعي ===== -->
    <div class="card hidden" id="tabScan">
      <div class="section-label" style="margin-top:0;">📷 صوّر فاتورة الشراء</div>
      <p style="color:var(--ink2);font-size:12px;margin:0 0 12px;line-height:1.6;">
        صوّر أو ارفع صورة فاتورة الشراء الورقية، والذكاء الاصطناعي راح يحاول
        يقرأ أسماء الأصناف والكميات والأسعار تلقائيًا ويطابقها مع مخزونك.
        هذا تخمين آلي غير مضمون 100% (جودة الصورة، خط اليد، تصميم الفاتورة
        كلها تأثر) - راجع كل صنف بالأسفل قبل ما تأكد الإضافة.
        <br><br>⚠️ يحتاج انترنت شغّال بجهازك الآن، ومفتاح API محفوظ من قبل
        بشاشة الإعدادات بالحاسوب (نفس مفتاح "المستشار الذكي").
      </p>
      <input type="file" id="scan_file_input" accept="image/*" capture="environment"
             style="display:none;" onchange="onInvoiceFileSelected(event)">
      <button class="save-btn" style="margin-top:0;background:linear-gradient(180deg,#2563EB,#1D4ED8);"
              onclick="document.getElementById('scan_file_input').click()">📷 اختر / صوّر الفاتورة</button>

      <div id="scan_preview_wrap" class="hidden" style="margin-top:12px;">
        <img id="scan_preview_img" style="width:100%;border-radius:10px;border:1px solid var(--line);">
        <button class="save-btn" id="scan_read_btn" onclick="readInvoiceWithAI()">🤖 اقرأ الفاتورة بالذكاء الاصطناعي</button>
      </div>

      <div id="scan_loading" class="hidden" style="text-align:center;padding:24px;color:var(--ink2);">
        ⏳ جاري قراءة الفاتورة، ممكن تاخذ لحظات...
      </div>

      <div id="scan_results_wrap" class="hidden" style="margin-top:14px;">
        <div class="section-label">الأصناف المستخرجة - راجعها وعدّل أي غلط قبل التأكيد</div>
        <div id="scan_results_list"></div>
        <label>المورد (اختياري - ينطبق على كل أصناف هذي الفاتورة)</label>
        <div class="autocomplete-wrap">
          <input id="scan_supplier" placeholder="اكتب اسم المورد... (لو جديد راح ينضاف تلقائيًا)" autocomplete="off">
          <div class="ac-list" id="scan_supplier_ac_list"></div>
        </div>
        <label>رقم الوصل (اختياري - ينطبق على كل أصناف هذي الفاتورة)</label>
        <input id="scan_receipt_number" placeholder="رقم وصل الاستلام من المورد إن وجد...">
        <label>تاريخ الوصل (ينطبق على كل أصناف هذي الفاتورة)</label>
        <input id="scan_receipt_date" type="date">
        <button class="save-btn" onclick="confirmScanResults()">✅ تأكيد وإضافة المحدّد للمخزون</button>
      </div>
    </div>
  </div>
</div>

<script>
let PIN = localStorage.getItem('h1_pin') || '';

function todayStr(){
  // تاريخ اليوم بصيغة YYYY-MM-DD المطلوبة لـ <input type="date"> - بالتوقيت
  // المحلي للجهاز (مو UTC، حتى ما ينزاح يوم كامل لبعض المناطق الزمنية لو
  // استخدمنا toISOString() مباشرة).
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return d.getFullYear() + '-' + mm + '-' + dd;
}
// تاريخ الوصل بكل الفورمات الثلاثة (دواء جديد / تحديث وشراء / تصوير) يبدأ
// تلقائيًا بتاريخ اليوم لحظة فتح الصفحة، وتقدر تعدله يدويًا بأي وقت.
['n_receipt_date', 'r_receipt_date', 'scan_receipt_date'].forEach(id => {
  document.getElementById(id).value = todayStr();
});

function submitPin(){
  const v = document.getElementById('pinInput').value.trim();
  if(!v){ return; }
  PIN = v;
  localStorage.setItem('h1_pin', v);
  checkPinValid();
}

async function checkPinValid(){
  try{
    const res = await fetch('/api/products-search?q=&pin=' + encodeURIComponent(PIN));
    if(res.status === 403){
      document.getElementById('pinErr').innerText = 'رمز غلط، جرب مرة ثانية.';
      return;
    }
    document.getElementById('pinGate').classList.add('hidden');
    document.getElementById('mainApp').classList.remove('hidden');
  }catch(e){
    document.getElementById('pinErr').innerText = 'ماكو اتصال بالسيرفر.';
  }
}
// لو الرابط جاي من مسح باركود وفيه رمز الدخول جاهز (?pin=XXXX)، نستخدمه تلقائيًا
const urlParams = new URLSearchParams(window.location.search);
const urlPin = urlParams.get('pin');
if(urlPin){ PIN = urlPin; localStorage.setItem('h1_pin', urlPin); }
if(PIN){ checkPinValid(); }

function showTab(name){
  document.getElementById('tabNew').classList.toggle('hidden', name !== 'new');
  document.getElementById('tabRestock').classList.toggle('hidden', name !== 'restock');
  document.getElementById('tabScan').classList.toggle('hidden', name !== 'scan');
  document.getElementById('tabNewBtn').classList.toggle('active', name === 'new');
  document.getElementById('tabRestockBtn').classList.toggle('active', name === 'restock');
  document.getElementById('tabScanBtn').classList.toggle('active', name === 'scan');
}

function showMsg(text, ok){
  const box = document.getElementById('msgBox');
  box.innerText = text;
  box.className = 'msg ' + (ok ? 'ok' : 'err');
  box.style.display = 'block';
  window.scrollTo(0,0);
  setTimeout(() => { box.style.display = 'none'; }, 4000);
}

// --- معاينات فورمة الدواء الجديد (نفس حسابات سطح المكتب) ---
function updateNewPreviews(){
  const salePrice = parseFloat(document.getElementById('n_sale_price').value) || 0;
  // نفس منطق الحاسوب: لو ما دخل سعر بيع الشريط، نعتبره منتج "علبة وحدة بس"
  // وعدد الأشرطة = 1 تلقائيًا، بغض النظر عن الرقم المكتوب بخانة عدد الأشرطة.
  const spc = salePrice === 0 ? 1 : (parseFloat(document.getElementById('n_spc').value) || 3);
  const cartonCost = parseFloat(document.getElementById('n_carton_cost').value) || 0;
  const stripCost = spc ? (cartonCost / spc) : 0;
  const previewEl = document.getElementById('n_strip_cost_preview');
  if(spc === 1){
    previewEl.innerText = '✓ منتج "علبة وحدة بس" (بدون أشرطة) - سعر الشريط والعلبة نفس الشي تلقائيًا';
  } else {
    previewEl.innerText = 'سعر شراء الشريط (تلقائي): ' + stripCost.toLocaleString('en-US',{maximumFractionDigits:0}) + ' د.ع';
  }
  const qtyCartons = parseFloat(document.getElementById('n_qty_cartons').value) || 0;
  const bonusQty = parseFloat(document.getElementById('n_bonus').value) || 0;
  const totalQty = qtyCartons + bonusQty;
  document.getElementById('n_qty_strips_preview').innerText = 'الكمية بالشريط (تلقائي): ' + Math.round(totalQty * spc);
  const bonusPreviewEl = document.getElementById('n_bonus_preview');
  if(bonusQty > 0 && qtyCartons > 0){
    const effectiveCost = (qtyCartons * cartonCost) / totalQty;
    bonusPreviewEl.innerText = 'الكمية الكلية المستلمة: ' + totalQty.toLocaleString('en-US',{maximumFractionDigits:2}) +
      ' باكيت (' + qtyCartons.toLocaleString('en-US',{maximumFractionDigits:2}) + ' + هدية ' +
      bonusQty.toLocaleString('en-US',{maximumFractionDigits:2}) + ') - السعر الفعلي للباكيت بعد توزيع الهدية: ' +
      effectiveCost.toLocaleString('en-US',{maximumFractionDigits:0}) + ' د.ع';
  } else {
    bonusPreviewEl.innerText = '';
  }
}
['n_spc','n_carton_cost','n_qty_cartons','n_sale_price','n_bonus'].forEach(id => {
  document.getElementById(id).addEventListener('input', updateNewPreviews);
});

async function submitNewProduct(){
  const payload = {
    pin: PIN,
    name: document.getElementById('n_name').value,
    generic_name: document.getElementById('n_generic').value,
    manufacturer: document.getElementById('n_manufacturer').value,
    category: document.getElementById('n_category').value,
    barcode: document.getElementById('n_barcode').value,
    strips_per_carton: parseFloat(document.getElementById('n_spc').value) || 3,
    carton_cost: parseFloat(document.getElementById('n_carton_cost').value) || 0,
    sale_price: parseFloat(document.getElementById('n_sale_price').value) || 0,
    carton_price: parseFloat(document.getElementById('n_carton_price').value) || 0,
    qty_cartons: parseFloat(document.getElementById('n_qty_cartons').value) || 0,
    bonus_cartons: parseFloat(document.getElementById('n_bonus').value) || 0,
    min_threshold: parseFloat(document.getElementById('n_min_threshold').value) || 10,
    expiry: document.getElementById('n_expiry').value,
    supplier_name: document.getElementById('n_supplier').value.trim(),
    receipt_number: document.getElementById('n_receipt_number').value.trim(),
    receipt_date: document.getElementById('n_receipt_date').value,
  };
  if(!payload.name.trim()){ showMsg('لازم تدخل اسم الدواء.', false); return; }
  // ⚠️ لو جايين من "أضفه كدواء جديد" بصف مراجعة فاتورة مصوّرة
  // (goAddNewProductFromScan) أو من تبويب "تحديث/شراء" (goAddNewProductFromRestock)
  // - ننشئ الدواء بدون كمية أولية عمدًا (حتى لو كتبتِ كمية/سعر بالفورمة،
  // نتجاهلهم هنا). السبب: الكمية والسعر الحقيقيين يروحون له لاحقًا مع
  // باقي أصناف نفس الفاتورة بضغطة التأكيد الوحدة - لو تركناهم هنا كمان
  // راح تنضاف الكمية مرتين.
  if(scanPendingRowIndex !== null || restockPendingNewProduct){
    payload.qty_cartons = 0;
    payload.bonus_cartons = 0;
  }
  try{
    const res = await fetch('/api/add-product', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const data = await res.json();
    if(res.ok){
      if(scanPendingRowIndex !== null){
        const idx = scanPendingRowIndex;
        scanPendingRowIndex = null;
        scanResultsData[idx].matched_product_id = data.product_id;
        scanResultsData[idx].matched_product_name = data.product_name;
        scanResultsData[idx].strips_per_carton = data.strips_per_carton;
        scanResultsData[idx].ai_verified = false;
        scanResultsData[idx].from_memory = false;
        ['n_name','n_generic','n_manufacturer','n_category','n_barcode','n_carton_cost','n_sale_price','n_carton_price','n_qty_cartons','n_bonus','n_supplier','n_receipt_number'].forEach(id => document.getElementById(id).value = '');
        document.getElementById('n_spc').value = 3;
        document.getElementById('n_min_threshold').value = 10;
        document.getElementById('n_receipt_date').value = todayStr();
        updateNewPreviews();
        showTab('scan');
        renderScanResults();
        showMsg('تمت إضافة "' + data.product_name + '" - رجعتِ لمراجعة الفاتورة.', true);
        return;
      }
      if(restockPendingNewProduct){
        restockPendingNewProduct = false;
        document.getElementById('r_product_id').value = data.product_id;
        document.getElementById('r_search').value = data.product_name;
        ['n_name','n_generic','n_manufacturer','n_category','n_barcode','n_carton_cost','n_sale_price','n_carton_price','n_qty_cartons','n_bonus','n_supplier','n_receipt_number'].forEach(id => document.getElementById(id).value = '');
        document.getElementById('n_spc').value = 3;
        document.getElementById('n_min_threshold').value = 10;
        document.getElementById('n_receipt_date').value = todayStr();
        updateNewPreviews();
        showTab('restock');
        showMsg('تمت إضافة "' + data.product_name + '" - أدخلي الكمية والسعر واضغطي "أضف للفاتورة".', true);
        return;
      }
      showMsg(data.message, true);
      ['n_name','n_generic','n_manufacturer','n_category','n_barcode','n_carton_cost','n_sale_price','n_carton_price','n_qty_cartons','n_bonus','n_supplier','n_receipt_number'].forEach(id => document.getElementById(id).value = '');
      document.getElementById('n_spc').value = 3;
      document.getElementById('n_min_threshold').value = 10;
      document.getElementById('n_receipt_date').value = todayStr();
      updateNewPreviews();
    } else {
      showMsg(data.detail || 'صار خطأ.', false);
    }
  }catch(e){ showMsg('ماكو اتصال بالسيرفر.', false); }
}

// --- بحث الدواء بفورمة التحديث/الشراء ---
let searchTimer = null;
document.getElementById('r_search').addEventListener('input', function(){
  clearTimeout(searchTimer);
  const q = this.value.trim();
  document.getElementById('r_product_id').value = '';
  if(!q){ document.getElementById('r_ac_list').style.display = 'none'; return; }
  searchTimer = setTimeout(async () => {
    const res = await fetch('/api/products-search?q=' + encodeURIComponent(q) + '&pin=' + encodeURIComponent(PIN));
    const items = await res.json();
    const list = document.getElementById('r_ac_list');
    list.innerHTML = '';
    items.forEach(p => {
      const div = document.createElement('div');
      div.className = 'ac-item';
      div.innerText = p.name;
      div.onclick = () => {
        document.getElementById('r_search').value = p.name;
        document.getElementById('r_product_id').value = p.id;
        list.style.display = 'none';
      };
      list.appendChild(div);
    });
    list.style.display = items.length ? 'block' : 'none';
  }, 250);
});

function wireSupplierAutocomplete(inputId, listId){
  // مربوطة بحقل مورد واحد - نفس فكرة اقتراحات الأدوية، تنستخدم بثلاث حقول
  // مختلفة (تحديث/شراء، دواء جديد، تصوير فاتورة) بدون تكرار الكود.
  let timer = null;
  const input = document.getElementById(inputId);
  input.addEventListener('input', function(){
    clearTimeout(timer);
    const q = this.value.trim();
    const list = document.getElementById(listId);
    if(!q){ list.style.display = 'none'; return; }
    timer = setTimeout(async () => {
      const res = await fetch('/api/suppliers-search?q=' + encodeURIComponent(q) + '&pin=' + encodeURIComponent(PIN));
      const items = await res.json();
      list.innerHTML = '';
      items.forEach(s => {
        const div = document.createElement('div');
        div.className = 'ac-item';
        div.innerText = s.name;
        div.onclick = () => {
          input.value = s.name;
          list.style.display = 'none';
        };
        list.appendChild(div);
      });
      list.style.display = items.length ? 'block' : 'none';
    }, 250);
  });
}
wireSupplierAutocomplete('r_supplier', 'r_supplier_ac_list');
wireSupplierAutocomplete('n_supplier', 'n_supplier_ac_list');
wireSupplierAutocomplete('scan_supplier', 'scan_supplier_ac_list');

let restockCartItems = [];
let restockPendingNewProduct = false;

function addToRestockCart(){
  const productId = document.getElementById('r_product_id').value;
  const productName = document.getElementById('r_search').value.trim();
  if(!productId){ showMsg('اختاري الدواء من قائمة الاقتراحات أول (اكتب اسمه واضغطي عليه).', false); return; }
  const qty = parseFloat(document.getElementById('r_qty').value) || 0;
  if(qty <= 0){ showMsg('لازم تدخلي كمية أكبر من صفر.', false); return; }
  restockCartItems.push({
    product_id: parseInt(productId), product_name: productName,
    qty_cartons: qty, bonus_cartons: parseFloat(document.getElementById('r_bonus').value) || 0,
    carton_cost: parseFloat(document.getElementById('r_cost').value) || 0,
    expiry: document.getElementById('r_expiry').value,
  });
  // نصفّر حقول الدواء بس - المورد ورقم ووتاريخ الوصل يبقون لباقي أصناف
  // نفس الفاتورة (نفس فكرة تصوير الفاتورة بالضبط).
  document.getElementById('r_search').value = '';
  document.getElementById('r_product_id').value = '';
  document.getElementById('r_qty').value = '';
  document.getElementById('r_bonus').value = '';
  document.getElementById('r_cost').value = '';
  document.getElementById('r_expiry').value = '';
  renderRestockCart();
  showMsg('انضاف "' + productName + '" للفاتورة - أضيفي دواء ثاني، أو اضغطي "تأكيد وتحديث المخزون".', true);
}

function removeFromRestockCart(idx){
  restockCartItems.splice(idx, 1);
  renderRestockCart();
}

function renderRestockCart(){
  const wrap = document.getElementById('restock_cart_wrap');
  const list = document.getElementById('restock_cart_list');
  if(restockCartItems.length === 0){ wrap.classList.add('hidden'); return; }
  wrap.classList.remove('hidden');
  list.innerHTML = '';
  restockCartItems.forEach((item, idx) => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:8px;border:1px solid var(--line);border-radius:8px;margin-bottom:6px;background:#F8FAFC;';
    row.innerHTML =
      '<span>' + item.product_name + ' - ' + item.qty_cartons + ' باكيت' +
        (item.bonus_cartons ? ' + هدية ' + item.bonus_cartons : '') + '</span>' +
      '<button type="button" style="background:#FEF2F2;color:#DC2626;border:1px solid #FCA5A5;border-radius:6px;padding:4px 10px;" ' +
        'onclick="removeFromRestockCart(' + idx + ')">حذف</button>';
    list.appendChild(row);
  });
}

async function confirmRestockCart(){
  if(restockCartItems.length === 0){ showMsg('ماكو أصناف بالفاتورة بعد - أضيفي دواء أول.', false); return; }
  const supplierName = document.getElementById('r_supplier').value.trim();
  const receiptNumber = document.getElementById('r_receipt_number').value.trim();
  const receiptDate = document.getElementById('r_receipt_date').value;
  try{
    const res = await fetch('/api/restock-batch', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        pin: PIN, supplier_name: supplierName, receipt_number: receiptNumber, receipt_date: receiptDate,
        items: restockCartItems.map(item => ({
          product_id: item.product_id, qty_cartons: item.qty_cartons,
          bonus_cartons: item.bonus_cartons, carton_cost: item.carton_cost, expiry: item.expiry,
        })),
      })
    });
    const data = await res.json();
    if(res.ok && data.ok){
      showMsg(data.message, true);
      restockCartItems = [];
      renderRestockCart();
      document.getElementById('r_supplier').value = '';
      document.getElementById('r_receipt_number').value = '';
      document.getElementById('r_receipt_date').value = todayStr();
    } else {
      showMsg(data.detail || 'صار خطأ.', false);
    }
  }catch(e){ showMsg('ماكو اتصال بالسيرفر.', false); }
}

function goAddNewProductFromRestock(){
  const typedName = document.getElementById('r_search').value.trim();
  restockPendingNewProduct = true;
  document.getElementById('n_name').value = typedName;
  document.getElementById('n_generic').value = '';
  document.getElementById('n_manufacturer').value = '';
  document.getElementById('n_category').value = '';
  document.getElementById('n_barcode').value = '';
  document.getElementById('n_carton_cost').value = '';
  document.getElementById('n_qty_cartons').value = '';
  document.getElementById('n_bonus').value = '';
  document.getElementById('n_supplier').value = document.getElementById('r_supplier').value.trim();
  document.getElementById('n_receipt_number').value = document.getElementById('r_receipt_number').value.trim();
  if(document.getElementById('r_receipt_date').value){ document.getElementById('n_receipt_date').value = document.getElementById('r_receipt_date').value; }
  updateNewPreviews();
  showTab('new');
  showMsg('عبّي بيانات "' + (typedName || 'الدواء الجديد') + '" وبعدين اضغطي "أضف الدواء" - راح ترجعك تلقائيًا لتحديث/شراء.', true);
}


// --- تصوير فاتورة بالذكاء الاصطناعي ---
let scanImageBase64 = null;
let scanImageMediaType = 'image/jpeg';
let scanResultsData = [];

function onInvoiceFileSelected(event){
  const file = event.target.files[0];
  if(!file) return;
  scanImageMediaType = file.type || 'image/jpeg';
  const reader = new FileReader();
  reader.onload = function(e){
    const dataUrl = e.target.result;
    scanImageBase64 = dataUrl.split(',')[1]; // نشيل البادئة "data:image/...;base64,"
    document.getElementById('scan_preview_img').src = dataUrl;
    document.getElementById('scan_preview_wrap').classList.remove('hidden');
    document.getElementById('scan_results_wrap').classList.add('hidden');
  };
  reader.readAsDataURL(file);
}

async function readInvoiceWithAI(){
  if(!scanImageBase64){ showMsg('اختار صورة أول.', false); return; }
  document.getElementById('scan_read_btn').disabled = true;
  document.getElementById('scan_loading').classList.remove('hidden');
  document.getElementById('scan_results_wrap').classList.add('hidden');
  try{
    const res = await fetch('/api/scan-invoice', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pin: PIN, image_base64: scanImageBase64, media_type: scanImageMediaType})
    });
    const data = await res.json();
    document.getElementById('scan_loading').classList.add('hidden');
    document.getElementById('scan_read_btn').disabled = false;
    if(!res.ok){ showMsg(data.detail || 'صار خطأ بقراءة الفاتورة.', false); return; }
    scanResultsData = data.items.map(it => ({...it, include: true}));
    renderScanResults();
  }catch(e){
    document.getElementById('scan_loading').classList.add('hidden');
    document.getElementById('scan_read_btn').disabled = false;
    showMsg('ماكو اتصال بالسيرفر.', false);
  }
}

let scanSearchTimers = {};

function renderScanResults(){
  const wrap = document.getElementById('scan_results_list');
  wrap.innerHTML = '';
  scanResultsData.forEach((item, idx) => {
    const row = document.createElement('div');
    row.id = 'scan_row_' + idx;
    row.style.cssText = 'border:1px solid var(--line);border-radius:10px;padding:10px;margin-bottom:8px;background:#fff;';
    // ✅ متطابق مع رسالتين مختلفتين حسب مصدر الثقة: تطابق نصي حاسم محليًا
    // (مثلًا نفس الاسم ونفس الجرعة بالضبط)، أو تأكيد فعلي من الذكاء
    // الاصطناعي نفسه للحالات الغامضة (اسم بدون جرعة، أو تشابه بين أكثر
    // من دواء) - نبين مصدر الثقة صراحة حتى ما يبين كل اقتراح بنفس القوة.
    let matchLabel, matchColor;
    if(item.matched_product_id){
      matchLabel = item.from_memory
        ? '🧠 معروف من قبل: ' + item.matched_product_name
        : item.ai_verified
          ? '✅ تأكد الذكاء الاصطناعي: ' + item.matched_product_name
          : '✅ متطابق مع: ' + item.matched_product_name;
      matchColor = '#15803D';
    } else {
      matchLabel = '⚠️ ماكو تطابق مؤكد - ابحث عن الدواء الصحيح، أو أضفه كدواء جديد';
      matchColor = '#DC2626';
    }
    row.innerHTML =
      '<div style="font-weight:700;margin-bottom:6px;">النص المستخرج من الفاتورة: «' + item.extracted_name + '»</div>' +
      '<label style="margin-top:0;">الدواء بمخزونك (ابحث وعدّل لو المطابقة غلط)</label>' +
      '<div class="autocomplete-wrap">' +
        '<input type="text" id="scan_search_' + idx + '" value="' + (item.matched_product_name || '') + '" ' +
          'placeholder="اكتب اسم الدواء الصحيح..." autocomplete="off" ' +
          'oninput="searchMatchForRow(' + idx + ', this.value)">' +
        '<div class="ac-list" id="scan_ac_list_' + idx + '"></div>' +
      '</div>' +
      '<div id="scan_match_status_' + idx + '" style="font-size:12px;color:' + matchColor + ';margin:4px 0 8px;">' + matchLabel + '</div>' +
      '<label>الكمية (بالباكيت)</label>' +
      '<input type="number" value="' + item.quantity + '" ' +
        'onchange="scanResultsData[' + idx + '].quantity=parseFloat(this.value)||0">' +
      '<label>هدية/بونص (بالباكيت - اختياري)</label>' +
      '<input type="number" step="0.01" min="0" value="' + (item.bonus_qty || 0) + '" ' +
        'onchange="scanResultsData[' + idx + '].bonus_qty=parseFloat(this.value)||0">' +
      '<label>سعر شراء الباكيت</label>' +
      '<input type="number" value="' + item.unit_price + '" ' +
        'onchange="scanResultsData[' + idx + '].unit_price=parseFloat(this.value)||0">' +
      '<label>تاريخ انتهاء الصلاحية (اختياري)</label>' +
      '<input type="date" value="' + (item.expiry || '') + '" ' +
        'onchange="scanResultsData[' + idx + '].expiry=this.value">' +
      '<label style="display:flex;align-items:center;gap:8px;margin-top:12px;">' +
        '<input type="checkbox" ' + (item.include ? 'checked' : '') + ' style="width:auto;" ' +
          'onchange="scanResultsData[' + idx + '].include=this.checked">' +
        '<span>حدّث المخزون لهذا الصنف عند التأكيد</span>' +
      '</label>' +
      // ⚠️ إضافة دواء غير موجود بالمخزون تصير الحين بتبويب "➕ دواء جديد"
      // الأصلي نفسه (تبويب منفصل بأعلى الشاشة، دائم الظهور بدون فتح/طي -
      // بنفس فكرة تبويب الموردين بسطح الحاسوب بالضبط) - مو فورمة مدمجة
      // بداخل صف المراجعة. الضغط يعبّي التبويب بالاسم المستخرج + مورد/رقم
      // وصل نفس الفاتورة تلقائيًا، وبعد الحفظ يرجعك تلقائيًا لهذا الصف بس
      // مطابق. راجع goAddNewProductFromScan و submitNewProduct.
      '<button type="button" style="width:100%;margin-top:10px;padding:10px;border:1px solid #DC2626;border-radius:9px;background:#FEF2F2;color:#DC2626;font-weight:700;" ' +
        'onclick="goAddNewProductFromScan(' + idx + ')">➕ ماكو هذا الدواء بمخزونك؟ أضفه كدواء جديد</button>';
    wrap.appendChild(row);
  });
  document.getElementById('scan_results_wrap').classList.remove('hidden');
}

let scanPendingRowIndex = null;

function goAddNewProductFromScan(idx){
  const item = scanResultsData[idx];
  scanPendingRowIndex = idx;
  document.getElementById('n_name').value = item.extracted_name || '';
  document.getElementById('n_generic').value = '';
  document.getElementById('n_manufacturer').value = '';
  document.getElementById('n_category').value = '';
  document.getElementById('n_barcode').value = '';
  document.getElementById('n_carton_cost').value = '';
  document.getElementById('n_qty_cartons').value = '';
  document.getElementById('n_bonus').value = '';
  // نفس مورد ورقم ووصل تاريخ نفس الفاتورة تلقائيًا - حتى الدواء الجديد
  // يرتبط صح بنفس الفاتورة لو أكملتِ الحفظ من هذا المسار.
  document.getElementById('n_supplier').value = scanSupplierName || '';
  document.getElementById('n_receipt_number').value = scanReceiptNumber || '';
  if(scanReceiptDate){ document.getElementById('n_receipt_date').value = scanReceiptDate; }
  updateNewPreviews();
  showTab('new');
  showMsg('عبّي بيانات "' + (item.extracted_name || '') + '" وبعدين اضغطي "أضف الدواء" - راح ترجعك تلقائيًا لمراجعة الفاتورة.', true);
}

function searchMatchForRow(idx, query){
  scanResultsData[idx].matched_product_id = null;
  scanResultsData[idx].matched_product_name = null;
  document.getElementById('scan_match_status_' + idx).innerText = '⚠️ ماكو تطابق مؤكد - اختار من القائمة أو أضفه كدواء جديد';
  document.getElementById('scan_match_status_' + idx).style.color = '#DC2626';
  clearTimeout(scanSearchTimers[idx]);
  const list = document.getElementById('scan_ac_list_' + idx);
  if(!query.trim()){ list.style.display = 'none'; return; }
  scanSearchTimers[idx] = setTimeout(async () => {
    const res = await fetch('/api/products-search?q=' + encodeURIComponent(query) + '&pin=' + encodeURIComponent(PIN));
    const items = await res.json();
    list.innerHTML = '';
    items.forEach(p => {
      const div = document.createElement('div');
      div.className = 'ac-item';
      div.innerText = p.name;
      div.onclick = () => {
        scanResultsData[idx].matched_product_id = p.id;
        scanResultsData[idx].matched_product_name = p.name;
        scanResultsData[idx].strips_per_carton = p.strips_per_carton;
        document.getElementById('scan_search_' + idx).value = p.name;
        const statusEl = document.getElementById('scan_match_status_' + idx);
        statusEl.innerText = '✅ متطابق مع: ' + p.name;
        statusEl.style.color = '#15803D';
        list.style.display = 'none';
      };
      list.appendChild(div);
    });
    list.style.display = items.length ? 'block' : 'none';
  }, 250);
}



async function confirmScanResults(){
  const toAdd = scanResultsData.filter(i => i.include);
  if(toAdd.length === 0){ showMsg('ماكو أي صنف محدد للتحديث. استخدم البحث فوق كل صنف لتأكيد الدواء الصحيح أولًا.', false); return; }
  const notMatched = toAdd.filter(i => !i.matched_product_id);
  if(notMatched.length > 0){
    showMsg('فيه ' + notMatched.length + ' صنف محدد بدون تطابق مؤكد - ابحث عن الدواء الصحيح، أو استخدم زر "أضفه كدواء جديد" له قبل التأكيد.', false);
    return;
  }
  const scanSupplierName = document.getElementById('scan_supplier').value.trim();
  const scanReceiptNumber = document.getElementById('scan_receipt_number').value.trim();
  const scanReceiptDate = document.getElementById('scan_receipt_date').value;
  // ⚠️ إصلاح خلل: كنا نستدعي /api/restock مرة لكل صنف - فتأكيد فاتورة
  // فيها 8 أصناف كان يطلع 8 فواتير شراء منفصلة بسجل المشتريات (نفس
  // المورد ونفس رقم الوصل، بس 8 أرقام فاتورة مختلفة!) بدل فاتورة وحدة.
  // الحين نبعت كل الأصناف مع بعض بنداء واحد لـ/api/restock-batch، يخليهم
  // كلهم بنفس الفاتورة الوحدة - بالضبط زي فاتورة شراء حقيقية بعدة أصناف.
  let successCount = 0, failCount = 0;
  try{
    const res = await fetch('/api/restock-batch', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        pin: PIN, supplier_name: scanSupplierName,
        receipt_number: scanReceiptNumber, receipt_date: scanReceiptDate,
        items: toAdd.map(item => ({
          product_id: item.matched_product_id,
          qty_cartons: item.quantity, bonus_cartons: item.bonus_qty || 0, carton_cost: item.unit_price,
          expiry: item.expiry || '', source_extracted_name: item.extracted_name || '',
        })),
      })
    });
    const data = await res.json();
    if(res.ok && data.ok){
      successCount = data.added_count;
      failCount = (data.errors || []).length;
    } else {
      failCount = toAdd.length;
      showMsg(data.detail || 'صار خطأ.', false);
    }
  }catch(e){
    failCount = toAdd.length;
    showMsg('ماكو اتصال بالسيرفر.', false);
  }
  let msg = 'تم تحديث مخزون ' + successCount + ' صنف بنجاح (بفاتورة واحدة)';
  if(failCount) msg += ' (فشل ' + failCount + ')';
  showMsg(msg, failCount === 0);
  scanResultsData = scanResultsData.filter(i => !i.include);  // نبقي بس اللي ما تأكدت (لو موجودة) لمراجعة لاحقة
  if(scanResultsData.length === 0){
    scanImageBase64 = null;
    document.getElementById('scan_results_wrap').classList.add('hidden');
    document.getElementById('scan_preview_wrap').classList.add('hidden');
    document.getElementById('scan_file_input').value = '';
    document.getElementById('scan_supplier').value = '';
    document.getElementById('scan_receipt_number').value = '';
    document.getElementById('scan_receipt_date').value = todayStr();
  } else {
    renderScanResults();
  }
}
</script>
</body>
</html>
"""


def start_server():
    """يشتغل بخيط منفصل بالخلفية طول ما البرنامج مفتوح.

    ملاحظة مهمة: uvicorn.run() افتراضيًا يحاول يسجل معالجات إشارات
    (signal handlers) للإيقاف الآمن (Ctrl+C وغيرها) - وهذا الشي بايثون
    يمنعه تمامًا إلا من الخيط الرئيسي (Main Thread). بما إن السيرفر هذا
    يشتغل بخيط ثانوي بالخلفية، لازم نعطل هذي الميزة صراحة (install_signal_handlers=False)
    وإلا السيرفر يفشل بالتشغيل فورًا وبصمت من غير أي رسالة توضح السبب.
    """
    try:
        # log_config=None: نمنع uvicorn من بناء إعدادات التلوين الافتراضية
        # اللي تحتاج تسأل sys.stdout.isatty() - هذا السؤال ينهار بخطأ
        # AttributeError لو sys.stdout كانت None (يصير هذا بالضبط لما البرنامج
        # يشتغل كـ exe بوضعية "بدون كونسول" اللي استخدمناها بالبناء النهائي،
        # لأن ويندوز وقتها ما يعطي البرنامج أي مخرج قياسي إطلاقًا).
        config = uvicorn.Config(
            app, host="0.0.0.0", port=PORT, log_level="warning", log_config=None
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = False
        server.run()
    except Exception:
        import traceback
        import os
        log_dir = os.path.expanduser("~/.olivia_pharmacy")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "mobile_server_error.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
