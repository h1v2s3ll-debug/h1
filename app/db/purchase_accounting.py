"""دوال حساب مركزية لحالة تسديد فواتير المشتريات (مسدد/تسديد) وحالة
المرتجع (مرتجع/مرتجع جزئي) - كل الحسابات هنا محسوبة مباشرة (live) من
جداول PaymentReceiptAllocation وPurchaseReturn، ما نخزن حالة جاهزة بأي
عمود، تفاديًا لأي عدم تطابق لو تغيّرت عملية دفع أو مرتجع بعدين.

مستخدمة من app/ui/supplier_accounts_view.py وapp/ui/purchase_view.py معًا
حتى يضلّ المنطق موحّد بمكان واحد بدل ما يتكرر وينفرق بمرور الوقت.
"""
from sqlalchemy import func


def purchase_order_paid_amount(session, order_id):
    from app.db.models import PaymentReceiptAllocation
    return (
        session.query(func.coalesce(func.sum(PaymentReceiptAllocation.amount_applied), 0))
        .filter(PaymentReceiptAllocation.purchase_order_id == order_id)
        .scalar() or 0
    )


def purchase_order_returned_amount(session, order_id):
    from app.db.models import PurchaseReturn
    return (
        session.query(func.coalesce(func.sum(PurchaseReturn.total_amount), 0))
        .filter(PurchaseReturn.purchase_order_id == order_id)
        .scalar() or 0
    )


def purchase_order_net_total(order, returned_amount):
    """إجمالي الفاتورة الفعلي المستحق بعد طرح أي مرتجع - هذا الأساس لحساب
    المتبقي والحالة، مو total_amount الخام (اللي يضل يمثل الفاتورة الأصلية
    قبل أي مرتجع)."""
    return max((order.total_amount or 0) - returned_amount, 0)


def purchase_order_remaining(order, paid_amount, returned_amount):
    return purchase_order_net_total(order, returned_amount) - paid_amount


def purchase_order_payment_status(order, paid_amount, returned_amount):
    """يرجع 'مسدد' أو 'تسديد' - أو None لو الفاتورة انترجعت بالكامل (ماكو
    مبلغ مستحق أصلاً يُحسب له حالة تسديد)."""
    net = purchase_order_net_total(order, returned_amount)
    if net <= 0.01:
        return None
    remaining = net - paid_amount
    return "مسدد" if remaining <= 0.01 else "تسديد"


def purchase_order_return_status(order, returned_amount):
    """يرجع 'مرتجع' (كامل) أو 'مرتجع جزئي' أو None لو ماكو مرتجع إطلاقًا."""
    if returned_amount <= 0.01:
        return None
    if returned_amount >= (order.total_amount or 0) - 0.01:
        return "مرتجع"
    return "مرتجع جزئي"


def purchase_order_status_display(order, paid_amount, returned_amount):
    """نص الحالة المعروض للمستخدم بكل شاشات الفواتير - يجمع حالة التسديد
    مع حالة المرتجع الجزئي بخانة وحدة بدل ما يستبدلها بالكامل.

    مثال: فاتورة عليها مرتجع جزئي وباقي منها مبلغ غير مسدد، تظهر
    "تسديد (مرتجع جزئي)" مو "مرتجع جزئي" لحالها (كان يختفي فيها إنها لسا
    مو مسددة بالكامل). لو الفاتورة انترجعت بالكامل، تظهر "مرتجع" لحالها
    لأنه ماكو مبلغ مستحق أصلاً بعد الإرجاع الكامل."""
    return_status = purchase_order_return_status(order, returned_amount)
    if return_status == "مرتجع":
        return "مرتجع"
    payment_status = purchase_order_payment_status(order, paid_amount, returned_amount)
    if return_status == "مرتجع جزئي":
        return f"{payment_status or 'مسدد'} (مرتجع جزئي)"
    return payment_status or ""


def purchase_order_display_number(order):
    """هوية الفاتورة المعروضة للمستخدم بكل الشاشات - رقم الوصل بدل الرقم
    الداخلي المتسلسل (order.id)، لأن رقم الوصل هو الاعتماد الفعلي وقت
    الاستخدام، مو ترتيب الإدخال الداخلي بقاعدة البيانات.

    احتياط: لو الفاتورة ماكو إلها رقم وصل مسجّل (اختياري أصلاً)، نرجع
    للرقم الداخلي مسبوق بعلامة # حتى يضل فيه معرّف مميز نقدر نستخدمه
    بالعرض، لكنه يبين واضح إنه رقم داخلي مو رقم وصل."""
    return order.receipt_number if order.receipt_number else f"#{order.id}"


def purchase_return_display_number(purchase_return, order=None):
    """هوية المرتجع المعروضة للمستخدم - رقم وصل الإرجاع نفسه (يختلف عن
    رقم وصل الفاتورة الأصلية عمدًا)، لا رقم الفاتورة الأصلية إطلاقًا،
    حتى يقدر المستخدم يلقى بالضبط الرقم اللي كتبه بنفسه وقت تسجيل
    المرتجع. لو ماكو رقم وصل مسجّل للمرتجع (اختياري)، نرجع لمعرّف داخلي
    مميز مسبوق بـ "مرتجع #" مع الإشارة لرقم الفاتورة الأصلية للسياق."""
    if purchase_return.receipt_number:
        return f"مرتجع {purchase_return.receipt_number}"
    order_label = purchase_order_display_number(order) if order else "?"
    return f"مرتجع #{purchase_return.id} (فاتورة {order_label})"


def purchase_order_summary(session, order):
    """ملخص كامل لفاتورة شراء وحدة - دالة واحدة تجيب كل الأرقام المطلوبة
    مرة وحدة، لتفادي تكرار نفس الاستعلامات بكل مكان.

    ملاحظة أداء: هذي الدالة تسوي استعلامين لكل فاتورة (مدفوع + مرتجع). لو
    عندك قائمة فواتير (أكثر من وحدة)، استخدم bulk_paid_and_returned تحت
    بدلها - نفس النتيجة بس بعدد استعلامات ثابت بغض النظر عن عدد الفواتير."""
    paid = purchase_order_paid_amount(session, order.id)
    returned = purchase_order_returned_amount(session, order.id)
    net = purchase_order_net_total(order, returned)
    remaining = purchase_order_remaining(order, paid, returned)
    return {
        "paid": paid,
        "returned": returned,
        "net_total": net,
        "remaining": max(remaining, 0),
        "payment_status": purchase_order_payment_status(order, paid, returned),
        "return_status": purchase_order_return_status(order, returned),
        "status_display": purchase_order_status_display(order, paid, returned),
    }


def bulk_paid_and_returned(session, order_ids):
    """نفس بيانات purchase_order_paid_amount/returned_amount، بس لعدة فواتير
    مرة وحدة بدل استعلام منفصل لكل وحدة (مشكلة N+1) - هذا السبب الرئيسي
    لبطء شاشة المشتريات/الموردين لما يكثر عدد الفواتير: فتح كشف حساب مورد
    عنده 200 فاتورة كان يسوي 400 استعلام (اثنين لكل فاتورة)، صار الحين
    استعلامين بس بغض النظر عن العدد.

    يرجع (paid_by_order: dict, returned_by_order: dict) - القيمة صفر
    افتراضيًا لأي فاتورة ماكو إلها سجل دفع/مرتجع أصلاً."""
    from app.db.models import PaymentReceiptAllocation, PurchaseReturn

    order_ids = list(order_ids)
    paid_by_order = {oid: 0 for oid in order_ids}
    returned_by_order = {oid: 0 for oid in order_ids}
    if not order_ids:
        return paid_by_order, returned_by_order

    paid_rows = (
        session.query(PaymentReceiptAllocation.purchase_order_id, func.sum(PaymentReceiptAllocation.amount_applied))
        .filter(PaymentReceiptAllocation.purchase_order_id.in_(order_ids))
        .group_by(PaymentReceiptAllocation.purchase_order_id)
        .all()
    )
    for oid, total in paid_rows:
        paid_by_order[oid] = total or 0

    returned_rows = (
        session.query(PurchaseReturn.purchase_order_id, func.sum(PurchaseReturn.total_amount))
        .filter(PurchaseReturn.purchase_order_id.in_(order_ids))
        .group_by(PurchaseReturn.purchase_order_id)
        .all()
    )
    for oid, total in returned_rows:
        returned_by_order[oid] = total or 0

    return paid_by_order, returned_by_order


def bulk_order_summaries(session, orders):
    """نسخة مجمّعة من purchase_order_summary لعدة فواتير مرة وحدة - يرجع
    dict مفتاحه order.id وقيمته نفس شكل قاموس purchase_order_summary."""
    order_ids = [o.id for o in orders]
    paid_by_order, returned_by_order = bulk_paid_and_returned(session, order_ids)
    result = {}
    for o in orders:
        paid = paid_by_order.get(o.id, 0)
        returned = returned_by_order.get(o.id, 0)
        net = purchase_order_net_total(o, returned)
        remaining = purchase_order_remaining(o, paid, returned)
        result[o.id] = {
            "paid": paid,
            "returned": returned,
            "net_total": net,
            "remaining": max(remaining, 0),
            "payment_status": purchase_order_payment_status(o, paid, returned),
            "return_status": purchase_order_return_status(o, returned),
            "status_display": purchase_order_status_display(o, paid, returned),
        }
    return result


def bulk_supplier_totals(session, supplier_ids):
    """أرقام "إجمالي المشتريات/المرتجعات/المدفوعات" لكل الموردين المطلوبين
    دفعة وحدة (5 استعلامات مجمّعة إجمالاً، بغض النظر عن عدد الموردين) -
    بدل استعلام منفصل لكل مورد لحاله (كان السبب الرئيسي لبطء شبكة بطاقات
    الموردين لما يكثر عددهم).

    يرجع dict مفتاحه supplier_id وقيمته (purchases, returns, payments, debt)."""
    from app.db.models import PurchaseOrder, SupplierPayment, SupplierReturn, PaymentReceipt

    supplier_ids = list(supplier_ids)
    result = {sid: {"purchases": 0, "returns": 0, "payments": 0} for sid in supplier_ids}
    if not supplier_ids:
        return {}

    purchases_rows = (
        session.query(PurchaseOrder.supplier_id, func.sum(PurchaseOrder.total_amount))
        .filter(PurchaseOrder.supplier_id.in_(supplier_ids), PurchaseOrder.status == "confirmed")
        .group_by(PurchaseOrder.supplier_id)
        .all()
    )
    for sid, total in purchases_rows:
        result[sid]["purchases"] = total or 0

    # جميع فواتير الموردين المطلوبين - لازم لحساب مجموع المرتجعات
    # (PurchaseReturn مربوطة بالفاتورة، مو بالمورد مباشرة).
    order_rows = (
        session.query(PurchaseOrder.id, PurchaseOrder.supplier_id)
        .filter(PurchaseOrder.supplier_id.in_(supplier_ids))
        .all()
    )
    supplier_by_order = {oid: sid for oid, sid in order_rows}
    order_ids = list(supplier_by_order.keys())

    if order_ids:
        from app.db.models import PurchaseReturn
        return_rows = (
            session.query(PurchaseReturn.purchase_order_id, func.sum(PurchaseReturn.total_amount))
            .filter(PurchaseReturn.purchase_order_id.in_(order_ids))
            .group_by(PurchaseReturn.purchase_order_id)
            .all()
        )
        for oid, total in return_rows:
            sid = supplier_by_order.get(oid)
            if sid is not None:
                result[sid]["returns"] += (total or 0)

    old_returns_rows = (
        session.query(SupplierReturn.supplier_id, func.sum(SupplierReturn.amount))
        .filter(SupplierReturn.supplier_id.in_(supplier_ids))
        .group_by(SupplierReturn.supplier_id)
        .all()
    )
    for sid, total in old_returns_rows:
        result[sid]["returns"] += (total or 0)

    old_payments_rows = (
        session.query(SupplierPayment.supplier_id, func.sum(SupplierPayment.amount))
        .filter(SupplierPayment.supplier_id.in_(supplier_ids))
        .group_by(SupplierPayment.supplier_id)
        .all()
    )
    for sid, total in old_payments_rows:
        result[sid]["payments"] += (total or 0)

    new_payments_rows = (
        session.query(PaymentReceipt.supplier_id, func.sum(PaymentReceipt.total_after_discount))
        .filter(PaymentReceipt.supplier_id.in_(supplier_ids))
        .group_by(PaymentReceipt.supplier_id)
        .all()
    )
    for sid, total in new_payments_rows:
        result[sid]["payments"] += (total or 0)

    final = {}
    for sid in supplier_ids:
        r = result[sid]
        debt = r["purchases"] - r["payments"] - r["returns"]
        final[sid] = (r["purchases"], r["returns"], r["payments"], debt)
    return final
