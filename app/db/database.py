"""
إعداد الاتصال بقاعدة البيانات المحلية (SQLite).
ملاحظة أمان: بالإصدار النهائي المفروض نستخدم SQLCipher بدل SQLite العادي
عشان نشفر ملف قاعدة البيانات (راجع نقاش حماية البيانات المحلية).
هذا الملف يستخدم SQLite عادي حاليًا حتى يسهل التطوير والاختبار.
"""
import os
from sqlalchemy import create_engine, text, inspect, event
from sqlalchemy.orm import sessionmaker, scoped_session, Session as SASession
from .models import Base

DB_DIR = os.path.join(os.path.expanduser("~"), ".olivia_pharmacy")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "olivia.db")

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
# ملاحظة أداء: كانت get_session() تفتح Session/اتصال جديد بكل استدعاء بدون
# إغلاقه أبدًا (مثلاً _compute_alerts_count بـ main_window.py يستدعيها بكل
# تنقل بين الصفحات) - هذا كان يراكم مئات الجلسات المفتوحة خلال نفس جلسة
# البرنامج الواحدة ويسبب تباطؤ تدريجي كلما اشتغل المستخدم أكثر. scoped_session
# يرجّع نفس الـ Session لكل نداء بنفس الخيط (البرنامج واجهة رسومية بخيط واحد)
# بدل ما يفتح واحدة جديدة كل مرة - يحل التسريب من دون تغيير أي منطق أعمال.
SessionLocal = scoped_session(sessionmaker(bind=engine))

# أعمدة أضيفت بعد إصدارات سابقة - create_all ما يضيفها لقاعدة بيانات موجودة مسبقًا
# (يضيف جداول جديدة بس، مو أعمدة على جدول قائم أصلاً)، فنضيفها يدويًا هنا لو ناقصة.
_NEW_COLUMNS = {
    "products": [
        ("strips_per_carton", "INTEGER DEFAULT 3"),
        ("carton_purchase_price", "FLOAT DEFAULT 0"),
        ("is_active", "BOOLEAN DEFAULT 1"),
    ],
    "invoice_items": [("unit_cost", "FLOAT DEFAULT 0")],
    "users": [("must_change_password", "BOOLEAN DEFAULT 0")],
    "batches": [
        ("supplier_id", "INTEGER"),
        ("receipt_number", "VARCHAR(80)"),
        # هذولا كانوا موجودين بـ models.py (Batch.carton_purchase_price و
        # Batch.carton_strips_per_carton) بس ناقصين هنا بقائمة الترحيل -
        # فأي قاعدة بيانات موجودة مسبقًا (أُنشئت قبل إضافة هذين العمودين
        # للنموذج) تضل بدونهم فعليًا بالجدول، وأي استعلام يحاول يقراهم يطيح
        # بخطأ "no such column: batches.carton_purchase_price". قواعد
        # البيانات الجديدة (create_all) ما تتأثر لأنها أصلاً تُنشأ فيهم.
        ("carton_purchase_price", "FLOAT DEFAULT 0"),
        ("carton_strips_per_carton", "INTEGER DEFAULT 0"),
    ],
    "purchase_orders": [
        ("receipt_number", "VARCHAR(80)"),
    ],
    "purchase_returns": [
        ("receipt_number", "VARCHAR(80)"),
        ("settled_in_receipt_id", "INTEGER"),
    ],
    "purchase_order_items": [
        ("bonus_quantity", "FLOAT"),
    ],
    "batches": [
        ("bonus_quantity", "INTEGER"),
    ],
}

# فهارس أضيفت بعد إصدارات سابقة (راجع تقرير التدقيق، قسم 7) - تفيد فرز/فلترة
# سجل فواتير الشراء بعد ترقيم الصفحات (PurchaseView._refresh_invoices_table)
# وتفيد JOIN عناصر كل فاتورة بشاشة تفاصيل الفاتورة. CREATE INDEX IF NOT
# EXISTS آمن 100% لقاعدة بيانات جديدة أو قديمة على حدٍ سواء - ما يغيّر أي
# بيانات، بس يبني فهرس إضافي على عمود موجود أصلًا.
_NEW_INDEXES = [
    ("ix_purchase_orders_supplier_id", "purchase_orders", "supplier_id"),
    ("ix_purchase_orders_order_date", "purchase_orders", "order_date"),
    ("ix_purchase_order_items_purchase_order_id", "purchase_order_items", "purchase_order_id"),
]


def _run_light_migrations():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _NEW_COLUMNS.items():
            if table not in existing_tables:
                continue  # الجدول نفسه راح ينشئه create_all لو جديد بالكامل
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for col_name, col_def in columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"))
        for index_name, table, column in _NEW_INDEXES:
            if table not in existing_tables:
                continue  # الجدول نفسه راح ينشئه create_all (مع فهرسه) لو جديد بالكامل
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"))


def _repair_broken_catalog_pricing():
    """يصحح أدوية القائمة الأولية (is_custom=False) اللي انزرعت بنسخة قديمة
    من seed_data.py كان فيها خطأ - ما كان يعبّي سعر شراء الباكيت (carton_purchase_price)
    أبدًا، فيضل صفر دائمًا لهذي الأدوية رغم وجود بيانات أسعار ثانية. أي منتج
    من القائمة الأولية (مو دواء مضاف يدويًا) وسعر شراء الباكيت تبعه لسا صفر
    هو علامة أكيدة إنه من النسخة القديمة المكسورة، فنعيد ضبط أسعاره بالكامل
    بنفس الأسعار الموحدة الجديدة (1000 شراء الباكيت / 3000 بيع الباكيت) وكأنه
    انضاف من جديد - بدون ما نلمس الدفعات (الكميات الفعلية وتواريخ الصلاحية
    المسجلة تبقى كما هي، نصحح فقط أساس التكلفة/السعر)."""
    from .models import Product, Batch

    session = SessionLocal()
    try:
        broken = (
            session.query(Product)
            .filter(Product.is_custom == False, Product.carton_purchase_price == 0)
            .all()
        )
        if not broken:
            return
        for p in broken:
            spc = p.strips_per_carton or 3
            p.strips_per_carton = spc
            p.carton_purchase_price = 1000
            p.carton_price = 3000
            p.sale_price = round(3000 / spc, -1) or (3000 / spc)
            strip_cost = p.carton_purchase_price / spc
            for b in session.query(Batch).filter(Batch.product_id == p.id).all():
                b.purchase_price = strip_cost
        session.commit()
        print(f"تم تصحيح أسعار {len(broken)} دواء من القائمة الأولية (سعر باكيت 1000/بيع 3000).")
    finally:
        pass  # ما نسكر الجلسة المشتركة (scoped_session) هنا أبدًا - راجع نفس الملاحظة بمكان ثاني


def _repair_broken_return_batch_pricing():
    """يصحح دفعات الإرجاع (batch_number='RETURN') اللي اتسجلت بسعر شراء = صفر
    بالغلط بسبب باغ سابق (كان يهمل تكلفة الشراء المحسوبة فعليًا وقت إنشاء
    الدفعة). هذا يخص فقط الحالة النادرة: زبون رجّع دواء نفذ مخزونه بالكامل
    قبلها، فينشئ البرنامج دفعة جديدة لاستقبال الكمية المرتجعة.

    محصور عمدًا بـ batch_number == 'RETURN' فقط (مو أي دفعة صفرية السعر
    بشكل عام) حتى ما يلمس أي بيانات شرعية ثانية سعرها صفر لسبب حقيقي."""
    from .models import Batch, Product

    session = SessionLocal()
    try:
        broken = (
            session.query(Batch)
            .filter(Batch.batch_number == "RETURN", Batch.purchase_price == 0, Batch.quantity_available > 0)
            .all()
        )
        if not broken:
            return
        for b in broken:
            product = session.query(Product).get(b.product_id)
            if not product:
                continue
            # نفس منطق أفضل تقدير متاح: متوسط سعر شراء دفعات ثانية للمنتج
            # نفسه (لو موجودة)، وإلا سعر شراء الباكيت الحالي مقسوم على عدد
            # الأشرطة بالباكيت.
            other_batches = [
                ob for ob in product.batches
                if ob.id != b.id and ob.quantity_available > 0 and (ob.purchase_price or 0) > 0
            ]
            if other_batches:
                total_qty = sum(ob.quantity_available for ob in other_batches)
                estimate = sum((ob.purchase_price or 0) * ob.quantity_available for ob in other_batches) / total_qty
            elif product.carton_purchase_price and product.strips_per_carton:
                estimate = product.carton_purchase_price / product.strips_per_carton
            else:
                estimate = 0
            b.purchase_price = estimate
        session.commit()
        print(f"تم تصحيح سعر شراء {len(broken)} دفعة إرجاع كانت مسجّلة بالغلط بسعر صفر.")
    finally:
        pass  # ما نسكر الجلسة المشتركة (scoped_session) هنا أبدًا


def init_db():
    """ينشئ كل الجداول لو ماكانت موجودة (أول تشغيل للبرنامج)، ويحدّث الجداول القديمة بالأعمدة الجديدة."""
    Base.metadata.create_all(engine)
    _run_light_migrations()
    # ملاحظة: _repair_broken_catalog_pricing() صارت معطّلة عمدًا - كانت
    # تصحيح لمرة وحدة لخطأ بنسخة قديمة من seed_data.py (سعر شراء الباكيت
    # يضل صفر للقائمة الأولية القديمة الـ85 حتى لو موجود سعر فعلي). بما إن
    # القائمة الأولية الحالية صارت كتالوجك الحقيقي (starter_catalog.xlsx)،
    # فيه أصناف فيه سعر شراء الباكيت = 0 بشكل شرعي وصحيح (مو خطأ) - تشغيل
    # هذا التصحيح كان يبدّل هذي الأسعار الحقيقية تلقائيًا كل ما يفتح البرنامج
    # بأسعار وهمية (1000/3000)، فعطّلناه حتى ما يلمس بياناتك الحقيقية.
    # _repair_broken_catalog_pricing()
    _repair_broken_return_batch_pricing()
    _register_instant_backup_hook()


_instant_backup_registered = False


def _on_session_commit(session):
    """يشتغل تلقائيًا فور أي commit ناجح بأي جلسة بكل البرنامج (بيع، إرجاع،
    إضافة دواء، تعديل مخزون، أي عملية) - يحدّث نسخة احتياطية لحظية واحدة
    (نفس الملف، مو ملف جديد كل مرة). مسجّل هنا (مو بملف backup_helper.py
    نفسه) لتفادي استيراد دائري، لأن backup_helper.py أصلًا يستورد من هذا
    الملف (DB_PATH)."""
    try:
        from .backup_helper import perform_instant_backup
        perform_instant_backup(session)
    except Exception:
        pass  # النسخ اللحظي بالخلفية ما يجوز يقاطع أي عملية بالبرنامج لو فشل


def _register_instant_backup_hook():
    """يسجّل معالج after_commit مرة وحدة بس لكل تشغيل للبرنامج - لو سجّلناه
    بكل استدعاء لـ init_db() (تصير أحيانًا أكثر من مرة، مثلاً بالاختبارات)
    كان بيتكرر نفس المعالج عدة مرات ويشتغل النسخ اللحظي مرات مضاعفة لكل
    عملية وحدة."""
    global _instant_backup_registered
    if _instant_backup_registered:
        return
    event.listens_for(SASession, "after_commit")(_on_session_commit)
    _instant_backup_registered = True


def get_session():
    return SessionLocal()
