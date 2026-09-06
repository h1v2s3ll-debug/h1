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
        ("carton_purchase_price", "FLOAT DEFAULT 0"),
        ("carton_strips_per_carton", "INTEGER DEFAULT 0"),
    ],
}


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


# فهارس أضيفت لاحقًا لتسريع البحث/الترتيب مع مخزون كبير (آلاف الأدوية) -
# Base.metadata.create_all() يضيفها تلقائيًا لقاعدة بيانات جديدة بالكامل،
# بس ما يلمس قاعدة بيانات موجودة مسبقًا (نفس سبب _NEW_COLUMNS بالأعلى بالضبط).
# CREATE INDEX IF NOT EXISTS آمنة 100% - ما تغيّر ولا تلمس أي صف بيانات
# موجود، تضيف بس فهرس فوق العمود لتسريع القراءة، وتتجاهل نفسها لو الفهرس
# أصلاً موجود (بقاعدة بيانات جديدة أنشأها create_all مسبقًا).
_NEW_INDEXES = [
    ("ix_products_name", "products", "name"),
    ("ix_products_barcode", "products", "barcode"),
    ("ix_products_category", "products", "category"),
    ("ix_batches_product_id", "batches", "product_id"),
    ("ix_batches_expiry_date", "batches", "expiry_date"),
    ("ix_invoices_invoice_date", "invoices", "invoice_date"),
    ("ix_invoice_items_invoice_id", "invoice_items", "invoice_id"),
    ("ix_invoice_items_batch_id", "invoice_items", "batch_id"),
]


def _run_index_migrations():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for index_name, table, column in _NEW_INDEXES:
            if table not in existing_tables:
                continue
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


def init_db():
    """ينشئ كل الجداول لو ماكانت موجودة (أول تشغيل للبرنامج)، ويحدّث الجداول القديمة بالأعمدة الجديدة."""
    Base.metadata.create_all(engine)
    _run_light_migrations()
    _run_index_migrations()
    _repair_broken_catalog_pricing()
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
