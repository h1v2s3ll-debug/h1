"""
نماذج قاعدة البيانات المحلية لنظام H1
كل جدول هنا يطابق المخطط اللي اتفقنا عليه بالنقاش.
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, Boolean, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    generic_name = Column(String(200))
    manufacturer = Column(String(150))
    category = Column(String(100), index=True)
    base_unit = Column(String(30), default="شريط")
    is_custom = Column(Boolean, default=True)   # False = من القائمة الجاهزة
    master_ref_id = Column(Integer, nullable=True)
    barcode = Column(String(60), nullable=True, unique=False, index=True)
    is_active = Column(Boolean, default=True)  # False = مؤرشف/محذوف منطقيًا (بيع منه سابقًا فما نقدر نحذفه فعليًا)

    # أسعار البيع (بوحدة الأساس "شريط") - منفصلة عن سعر الشراء اللي بالدفعة
    sale_price = Column(Float, default=0)       # سعر بيع المفرد (شريط)
    wholesale_price = Column(Float, default=0)  # سعر الجملة (شريط)
    carton_price = Column(Float, default=0)     # سعر بيع الكارتون/الباكيت الكامل
    min_stock_threshold = Column(Integer, default=10)  # الحد الأدنى قبل ما يعتبر "مخزون منخفض" (بوحدة الشريط)
    strips_per_carton = Column(Integer, default=3)  # كم شريط بالباكيت/الكارتون الواحد - يستخدم لتحويل كمية/سعر الشراء
    carton_purchase_price = Column(Float, default=0)  # آخر/الحالي سعر شراء الباكيت المعروف - مرجع لحساب تكلفة الشريط تلقائيًا، بغض النظر عن إضافة كمية جديدة

    units = relationship("ProductUnit", back_populates="product", cascade="all, delete-orphan")
    batches = relationship("Batch", back_populates="product", cascade="all, delete-orphan")


class ProductUnit(Base):
    __tablename__ = "product_units"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    unit_name = Column(String(30), nullable=False)      # شريط / علبة
    conversion_factor = Column(Integer, nullable=False)  # كم "شريط" تعادل هذي الوحدة

    product = relationship("Product", back_populates="units")


class Batch(Base):
    __tablename__ = "batches"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    batch_number = Column(String(80))
    expiry_date = Column(Date, index=True)
    purchase_price = Column(Float, default=0)
    quantity_received = Column(Integer, default=0)
    quantity_available = Column(Integer, default=0)  # بوحدة الأساس (شريط)

    # هوية الدفعة للعرض للمستخدم: مورد + رقم وصل الاستلام (اختياري) - بدل
    # batch_number العشوائي غير المفيد. منفصلين عن التاريخ وسعر الشراء
    # (expiry_date/purchase_price فوق) - ما ندمجهم بنص واحد، كل وحدة تُعرض
    # بحقلها لحالها بواجهة المخزون.
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    receipt_number = Column(String(80), nullable=True)  # رقم وصل الاستلام - اختياري

    # سعر شراء الباكيت الفعلي المُدخل وقت شراء هذي الدفعة بالذات، مع عدد
    # الأشرطة بالباكيت وقتها - نخزنهم منفصلين عن purchase_price (سعر الشريط)
    # عشان نعرض "سعر شراء الباكيت" لهذي الدفعة بالضبط لاحقًا بدون ما نعيد
    # حسابه بضرب purchase_price × strips_per_carton الحالي للدواء (اللي ممكن
    # يكون تغيّر بعد شراء هذي الدفعة ويطلع رقم غلط). carton_strips_per_carton=0
    # يعني دفعة قديمة قبل هذا التحديث - نرجع للحساب التقريبي القديم كبديل.
    carton_purchase_price = Column(Float, default=0)
    carton_strips_per_carton = Column(Integer, default=0)
    # كمية الهدية/البونص (بوحدة الأساس - شريط، نفس وحدة quantity_received)
    # المتضمنة أصلًا بـ quantity_received - عمود إعلامي بس للعرض ("الكمية
    # الأصلية + هدية N")، ما يُستخدم بأي حساب مخزون أو مبلغ (القيمة المالية
    # للهدية أصلًا منعكسة بـ carton_purchase_price المخفّض - راجع تعليق
    # PurchaseOrderItem.bonus_quantity لتفاصيل المعادلة الكاملة).
    bonus_quantity = Column(Integer, default=0, nullable=True)

    product = relationship("Product", back_populates="batches")
    supplier = relationship("Supplier")
    movements = relationship("StockMovement", back_populates="batch", cascade="all, delete-orphan")


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False)
    unit_id = Column(Integer, ForeignKey("product_units.id"), nullable=True)
    movement_type = Column(String(30))  # شراء / بيع / تالف / إرجاع
    quantity = Column(Integer)          # بوحدة الأساس
    moved_at = Column(DateTime, default=datetime.now)
    note = Column(String(200))

    batch = relationship("Batch", back_populates="movements")


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    phone = Column(String(30))
    credit_limit = Column(Float, default=0)
    current_balance = Column(Float, default=0)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    username = Column(String(60), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(30), default="cashier")  # owner / manager / cashier
    # يُجبر المستخدم يغيّر كلمة المرور بأول تسجيل دخول - نستخدمه خصوصًا مع
    # حساب "admin" الافتراضي (كلمة مروره الأولية معروفة/موثّقة بدليل
    # الاستخدام: admin123) عشان ما تضل هي كلمة المرور الفعلية بأي صيدلية حقيقية.
    must_change_password = Column(Boolean, default=False)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    invoice_number = Column(String(40), unique=True)
    # ملاحظة إصلاح مهمة: كان الوقت الافتراضي هنا datetime.utcnow (توقيت
    # عالمي UTC)، بينما كل فلاتر "اليوم/الشهر الحالي" بالرئيسية والتقارير
    # تعتمد على تاريخ الجهاز المحلي (date.today()). ببلد بفارق توقيت +3 عن UTC
    # مثل العراق، أي فاتورة تنعمل بأول 3 ساعات من اليوم أو الشهر المحلي كانت
    # تنحفظ بتاريخ UTC لليوم/الشهر السابق - فما تظهر أبدًا بواردات/أرباح
    # "اليوم" أو "الشهر الحالي"، وتبين وكأن الواردات ما تتحدث. datetime.now
    # يستخدم نفس توقيت الجهاز المحلي المستخدم بكل الفلاتر، فيصير الاثنين متطابقين.
    invoice_date = Column(DateTime, default=datetime.now, index=True)
    payment_status = Column(String(20), default="نقدي")  # نقدي / آجل / جزئي
    due_date = Column(Date, nullable=True)
    total_amount = Column(Float, default=0)
    discount = Column(Float, default=0)   # مبلغ ثابت
    final_amount = Column(Float, default=0)

    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False, index=True)
    unit_id = Column(Integer, ForeignKey("product_units.id"), nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, default=0)
    subtotal = Column(Float, default=0)
    unit_cost = Column(Float, default=0)  # تكلفة الوحدة (بسعر البيع، مثلاً للعلبة) وقت البيع/الإرجاع - تُستخدم لحساب الربح بدقة حتى لو تغيّرت أسعار الدفعات لاحقًا

    invoice = relationship("Invoice", back_populates="items")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    amount = Column(Float, default=0)
    payment_date = Column(DateTime, default=datetime.now)
    payment_method = Column(String(30), default="كاش")

    invoice = relationship("Invoice", back_populates="payments")


class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    phone = Column(String(30))
    address = Column(String(200))
    notes = Column(Text)


class SupplierPayment(Base):
    """تسديد دفعة فعلية لمورد - يُستخدم لحساب دين المورد بشاشة (الموردون والحسابات)."""
    __tablename__ = "supplier_payments"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    amount = Column(Float, default=0)
    payment_date = Column(DateTime, default=datetime.now)
    notes = Column(String(300), nullable=True)


class SupplierReturn(Base):
    """مرتجع بضاعة لمورد - إدخال يدوي من الصيدلي (وصف + مبلغ)، ينزّل دين المورد متل الدفعة."""
    __tablename__ = "supplier_returns"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    amount = Column(Float, default=0)
    description = Column(String(300), nullable=True)
    return_date = Column(DateTime, default=datetime.now)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    order_date = Column(DateTime, default=datetime.now)
    status = Column(String(20), default="pending_review")  # pending_review/confirmed/rejected
    total_amount = Column(Float, default=0)
    source = Column(String(20), default="يدوي")  # يدوي / تصوير_فاتورة
    receipt_image_path = Column(String(300), nullable=True)
    receipt_number = Column(String(80), nullable=True)  # رقم وصل استلام البضاعة من المورد - اختياري، يغطي الطلبية كاملة

    items = relationship("PurchaseOrderItem", back_populates="order", cascade="all, delete-orphan")
    # علاقة ORM حقيقية للمورد (بدل ما تبقى supplier_id عمود خام بس) - هذا
    # اللي يخلّي joinedload(PurchaseOrder.supplier) ممكن، فيصير جلب المورد
    # مع الفاتورة باستعلام واحد (JOIN) بدل استعلام Supplier منفصل لكل صف
    # بجدول الفواتير (كان هذا السبب الحقيقي وراء بطء شاشة المشتريات مع كثرة
    # الفواتير - N+1: استعلام مورد + استعلام أصناف منفصلين لكل فاتورة).
    supplier = relationship("Supplier")
    # cascade="all, delete-orphan" هنا إجباري - purchase_returns.purchase_order_id
    # عمود NOT NULL (المرتجع لازم يكون مرتبط بفاتورة، ماكو معنى لمرتجع
    # بدون فاتورة أصلية). بدون هذا الـ cascade، حذف فاتورة عليها مرتجع كان
    # يخلي SQLAlchemy يحاول يصفّر purchase_order_id بسجل المرتجع قبل حذف
    # الفاتورة (سلوكه الافتراضي)، فينكسر قيد NOT NULL ويطيح البرنامج
    # (IntegrityError) - الحل الصحيح إنه لما تنحذف الفاتورة، مرتجعاتها
    # المرتبطة فيها تنحذف وياها تلقائيًا (وأصناف كل مرتجع كذلك، عبر
    # cascade المعرّف أصلاً بـ PurchaseReturn.items).
    returns = relationship("PurchaseReturn", back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    # quantity هنا هي الكمية الكلية الفعلية المستلمة (المشتراة + الهدية
    # مع بعض، بالباكيت) - و unit_cost هو السعر الفعلي بعد توزيع إجمالي
    # الفاتورة (بدون أي طرح) على هذي الكمية الكلية (مو السعر الاسمي
    # المتفق عليه مع المورد). هذا يخلي quantity × unit_cost = المبلغ
    # الصحيح للفاتورة تلقائيًا بكل مكان بالمشروع يحسبها (مجموع الفاتورة،
    # كشف الحساب، التعديل...) بدون أي حالة خاصة إضافية لازم نضيفها بكل مكان.
    #
    # مثال: سعر الوحدة 1000، كمية مشتراة 10، هدية 1 →
    #   الكمية الكلية المستلمة = 10 + 1 = 11 (quantity)
    #   المبلغ الإجمالي = 10 × 1000 = 10000 (يبقى نفسه - بدون أي طرح،
    #     الهدية بلاش فوق الكمية المشتراة، مو خصم من سعرها)
    #   unit_cost الفعلي المخزّن = 10000 ÷ 11 ≈ 909.09
    # bonus_quantity (تحت) تخزن الرقم الأصلي (1) للعرض بس ("10 + هدية 1")
    # - ما تدخل أي معادلة مبلغ، لأن أثرها أصلًا منعكس بتوزيع unit_cost.
    quantity = Column(Float, default=0)  # بالباكيت - كسري (0.25، 0.5...) لأدوية غالية تُشترى بجزء من الباكيت
    unit_cost = Column(Float, default=0)
    bonus_quantity = Column(Float, default=0, nullable=True)  # جزء من quantity - إعلامي بس للعرض
    raw_ocr_text = Column(String(300), nullable=True)
    matched_product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    match_confidence = Column(Float, nullable=True)

    order = relationship("PurchaseOrder", back_populates="items")


class PaymentReceipt(Base):
    """وصل دفع - عملية تسديد واحدة للمورد، ممكن تغطي أكثر من فاتورة شراء
    بنفس الوقت (عبر PaymentReceiptAllocation)، مع خصم اختياري (مبلغ ثابت
    أو نسبة مئوية) ينطبق على إجمالي الوصل كامل."""
    __tablename__ = "payment_receipts"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    receipt_number = Column(String(80), nullable=True)
    payment_date = Column(DateTime, default=datetime.now)
    discount_type = Column(String(10), default="fixed")  # fixed / percent
    discount_value = Column(Float, default=0)
    total_before_discount = Column(Float, default=0)  # مجموع المبالغ المطبّقة على الفواتير المحددة قبل الخصم
    total_after_discount = Column(Float, default=0)   # الصافي الفعلي المدفوع بعد الخصم
    note = Column(String(300), nullable=True)

    supplier = relationship("Supplier")
    allocations = relationship("PaymentReceiptAllocation", back_populates="receipt", cascade="all, delete-orphan")


class PaymentReceiptAllocation(Base):
    """كم من مبلغ وصل دفع معيّن انطبّق بالضبط على فاتورة شراء محددة - وصل
    وحد ممكن يغطي عدة فواتير، كل وحدة بمبلغها الخاص (المتبقي عليها أو جزء
    منه)."""
    __tablename__ = "payment_receipt_allocations"
    id = Column(Integer, primary_key=True)
    receipt_id = Column(Integer, ForeignKey("payment_receipts.id"), nullable=False)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    amount_applied = Column(Float, default=0)

    receipt = relationship("PaymentReceipt", back_populates="allocations")
    purchase_order = relationship("PurchaseOrder")


class PurchaseReturn(Base):
    """مرتجع شراء مرتبط إجباريًا بفاتورة شراء محددة (مو مبلغ حر بدون ربط) -
    كامل أو جزئي حسب الأصناف/الكميات المُرجعة بـ PurchaseReturnItem."""
    __tablename__ = "purchase_returns"
    id = Column(Integer, primary_key=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    return_date = Column(DateTime, default=datetime.now)
    total_amount = Column(Float, default=0)
    note = Column(String(300), nullable=True)
    receipt_number = Column(String(80), nullable=True)  # رقم وصل الإرجاع - يختلف عن رقم وصل الفاتورة الأصلية
    # لو المرتجع تم تضمينه بوصل دفع معيّن (كسطر توثيقي منفصل بالضبط، راجع
    # PaymentReceiptDialog) - مقصودة تكون منفصلة تمامًا عن paid_amount
    # (PaymentReceiptAllocation) الخاص بالفاتورة الأصلية، حتى ما يصير احتساب
    # مضاعف: net_total أصلًا يطرح total_amount هذا المرتجع مرة وحدة، فتضمين
    # المرتجع بوصل دفع ما يجوز يأثر على "المدفوع" الفعلي للفاتورة الأصلية
    # إطلاقًا - بس نعلّم إنه "انسجّل/تذكّر" بهذا الوصل بالذات، للعرض فقط.
    settled_in_receipt_id = Column(Integer, ForeignKey("payment_receipts.id"), nullable=True)

    purchase_order = relationship("PurchaseOrder", back_populates="returns")
    items = relationship("PurchaseReturnItem", back_populates="purchase_return", cascade="all, delete-orphan")


class PurchaseReturnItem(Base):
    __tablename__ = "purchase_return_items"
    id = Column(Integer, primary_key=True)
    purchase_return_id = Column(Integer, ForeignKey("purchase_returns.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    quantity = Column(Float, default=0)  # بوحدة الأساس (شريط) - كسري لنفس سبب PurchaseOrderItem.quantity
    unit_price = Column(Float, default=0)
    subtotal = Column(Float, default=0)

    purchase_return = relationship("PurchaseReturn", back_populates="items")
    product = relationship("Product")


class DosageGuideline(Base):
    __tablename__ = "dosage_guidelines"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    min_age = Column(Float, nullable=True)
    max_age = Column(Float, nullable=True)
    min_weight = Column(Float, nullable=True)
    max_weight = Column(Float, nullable=True)
    dose_per_kg = Column(Float, nullable=True)
    max_daily_dose = Column(Float, nullable=True)
    unit = Column(String(20), default="mg")
    standard_dose_note = Column(String(300), nullable=True)
    notes = Column(Text, nullable=True)


class ProductAlternative(Base):
    __tablename__ = "product_alternatives"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    alternative_product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    note = Column(String(200), nullable=True)


class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True)
    category = Column(String(80))
    amount = Column(Float, default=0)
    date = Column(Date, default=date.today)
    description = Column(String(200))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)


class CashRegister(Base):
    __tablename__ = "cash_register"
    id = Column(Integer, primary_key=True)
    date = Column(Date, default=date.today, unique=True)
    opening_balance = Column(Float, default=0)
    closing_balance = Column(Float, default=0)
    total_sales = Column(Float, default=0)
    total_expenses = Column(Float, default=0)
    net_profit = Column(Float, default=0)


class AlertOccurrence(Base):
    """يتتبّع أول ظهور لكل تنبيه بالرئيسية (نوعه + الدواء المرتبط) عشان
    نقدر نخفيه تلقائيًا بعد أسبوع من ظهوره الأول، حتى لو السبب الأساسي
    (نقص المخزون مثلاً) لسا مستمر - يمنع تراكم نفس التنبيهات لأسابيع
    وشهور بدون داعي. لو الحالة انصلحت وبعدين رجعت صارت من جديد، يُحتسب
    كتنبيه جديد بأسبوع جديد (يُحذف السجل القديم لما تنحل الحالة)."""
    __tablename__ = "alert_occurrences"
    id = Column(Integer, primary_key=True)
    alert_type = Column(String(30), nullable=False)  # out_of_stock / low_stock / expired / near_expiry
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    first_seen = Column(Date, default=date.today)


class DrugInteraction(Base):
    """تداخلات دوائية معروفة بين صنفين - يُتحقق منها وقت البيع لو الاثنين بنفس الفاتورة."""
    __tablename__ = "drug_interactions"
    id = Column(Integer, primary_key=True)
    product_id_a = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_id_b = Column(Integer, ForeignKey("products.id"), nullable=False)
    severity = Column(String(20), default="متوسط")  # خفيف / متوسط / خطير
    description = Column(String(300))


class AppSetting(Base):
    """إعدادات عامة للبرنامج (طابعة، سكانر، مفتاح API...) بشكل key-value بسيط."""
    __tablename__ = "app_settings"
    key = Column(String(80), primary_key=True)
    value = Column(Text, nullable=True)


class InvoiceTextMapping(Base):
    """"ذاكرة" مطابقة تصوير الفاتورة - تخزن (النص المستخرج من فاتورة ↔
    الدواء الصحيح فعليًا بمخزونك) بعد ما تصحح المطابقة يدويًا مرة وحدة
    (سواء بشاشة المشتريات بالحاسوب أو الموبايل، تصوير أو تحديث/شراء).

    الفايدة: نفس المورد يستخدم عادةً نفس صيغة الفاتورة (نفس الاختصارات
    ونفس طريقة كتابة الجرعة) كل مرة يبعتلك بضاعة - فبمجرد ما تصحح صنف
    مرة وحدة، أي مرة جاية يطلع فيها نفس النص **بالضبط** ينطابق فورًا
    بثقة 100% بدون أي تخمين نصي ولا حتى نداء ذكاء اصطناعي إطلاقًا. البرنامج
    "يتعلم" فواتير مورديك المتكررة تدريجيًا كل ما تستخدمينه أكثر - عكس
    التخمين النصي (مهما حسّناه) اللي يضل بنفس المستوى للأبد.

    نطابق على normalized_text (بعد توحيد الأحرف - راجع
    app.text_match.normalize_arabic) مو النص الخام كما هو، حتى فرق بسيط
    بالتشكيل أو حالة الأحرف ما يمنع الاستفادة من نفس الذاكرة."""
    __tablename__ = "invoice_text_mappings"
    id = Column(Integer, primary_key=True)
    normalized_text = Column(String(300), nullable=False, unique=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
