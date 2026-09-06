"""تبويب "الموردون والحسابات" - جزء من شاشة المشتريات.

نظام تسديد مرتبط بفواتير محددة (وصل دفع واحد يغطي عدة فواتير، مع خصم
اختياري)، ونظام مرتجع مرتبط إجباريًا بفاتورة شراء محددة (كامل أو جزئي،
صنف بصنف)، وحالة تسديد/مرتجع تُحسب تلقائيًا لكل فاتورة (بدون تخزين حالة
جاهزة - محسوبة مباشرة من app.db.purchase_accounting بكل مرة، فتبقى دقيقة
دائمًا حتى لو تغيّرت عملية دفع أو مرتجع بعدين).

ولا سطر من منطق شاشة "فاتورة شراء جديدة" الأصلية تغيّر - هذا ملف مستقل
يُستورد كتبويب ثاني بس.
"""
from datetime import datetime

from sqlalchemy import func

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QDialog, QFormLayout, QMessageBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QListWidget,
    QListWidgetItem, QAbstractItemView, QDateEdit, QTableView,
)
from PySide6.QtCore import Qt, QDate, QAbstractTableModel, QModelIndex, QTimer
from PySide6.QtGui import QColor, QFont, QBrush

from app.db.database import get_session
from app.db.models import (
    Supplier, PurchaseOrder, PurchaseOrderItem, SupplierPayment, SupplierReturn,
    PaymentReceipt, PaymentReceiptAllocation, PurchaseReturn, PurchaseReturnItem,
    Product, Batch, StockMovement,
)
from app.db.purchase_accounting import (
    purchase_order_paid_amount, purchase_order_returned_amount,
    purchase_order_net_total, purchase_order_remaining,
    purchase_order_payment_status, purchase_order_return_status,
    purchase_order_summary, purchase_order_display_number,
    purchase_return_display_number,
    bulk_order_summaries, bulk_supplier_totals,
)
from app.ui.widgets import NumberLineEdit, enable_touch_scroll
from app.ui.inventory_view import _strips_from_cartons
from app.ui.icons import icon
from app.ui.theme import (
    TEAL_400, TEAL_600, TEAL_700, TEAL_800, RED_500, COLOR_SURFACE,
    COLOR_SURFACE_SUBTLE, COLOR_BORDER, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY,
    FONT_H1, FONT_H3, SPACE_8, SPACE_12, SPACE_16, SPACE_20, SPACE_24,
    RADIUS_BUTTON, RADIUS_CARD, RADIUS_INPUT,
)


def fmt_money(n):
    return f"{n:,.0f} د.ع"


class AddSupplierDialog(QDialog):
    """نافذة إضافة مورد جديد - نفس محتوى النافذة الأصلية بشاشة المشتريات
    بالضبط (اسم/هاتف/عنوان)، هنا حتى تشتغل هذي الصفحة لحالها بدون استيراد
    دائري من purchase_view.py (اللي يستورد هو منها بدل العكس)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة مورد جديد")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(320)
        layout = QFormLayout(self)
        self.name_input = QLineEdit()
        self.phone_input = QLineEdit()
        self.address_input = QLineEdit()
        layout.addRow("اسم المورد:", self.name_input)
        layout.addRow("رقم الهاتف:", self.phone_input)
        layout.addRow("العنوان:", self.address_input)
        save_btn = QPushButton("حفظ")
        save_btn.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);"
            "color:white;border-radius:8px;padding:8px;"
        )
        save_btn.clicked.connect(self.accept)
        layout.addRow(save_btn)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "phone": self.phone_input.text().strip(),
            "address": self.address_input.text().strip(),
        }


def _status_item(text, color):
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    return item


class SupplierInvoicePickerDialog(QDialog):
    """اختيار فاتورة شراء وحدة من فواتير هذا المورد - أول خطوة بمسار
    "المورد → مرتجع شراء" (بند 12 بالمواصفات: المرتجع لازم يرتبط دايمًا
    بفاتورة محددة، مو مبلغ حر)."""

    def __init__(self, session, supplier, parent=None):
        super().__init__(parent)
        self.session = session
        self.supplier = supplier
        self.selected_order_id = None
        self.setWindowTitle(f"اختر فاتورة - {supplier.name}")
        self.setMinimumSize(480, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("اختر فاتورة الشراء اللي تريد تسوي منها مرتجع:"))

        self.list_widget = QListWidget()
        enable_touch_scroll(self.list_widget)
        orders = (
            session.query(PurchaseOrder)
            .filter(PurchaseOrder.supplier_id == supplier.id, PurchaseOrder.status == "confirmed")
            .order_by(PurchaseOrder.order_date.desc())
            .all()
        )
        summaries = bulk_order_summaries(session, orders)
        self._orders_by_row = []
        for o in orders:
            summary = summaries[o.id]
            date_str = o.order_date.strftime("%Y-%m-%d") if o.order_date else "-"
            ret_status = summary["return_status"]
            suffix = f"  [{ret_status}]" if ret_status else ""
            label = f"فاتورة {purchase_order_display_number(o)} - {date_str} - {fmt_money(o.total_amount)}{suffix}"
            list_item = QListWidgetItem(label)
            if ret_status == "مرتجع":
                list_item.setForeground(QColor(COLOR_TEXT_SECONDARY))
            self.list_widget.addItem(list_item)
            self._orders_by_row.append(o.id)
        layout.addWidget(self.list_widget, stretch=1)

        if not orders:
            layout.addWidget(QLabel("ماكو فواتير شراء لهذا المورد."))

        btn_row = QHBoxLayout()
        next_btn = QPushButton("التالي")
        next_btn.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:{RADIUS_BUTTON}px;padding:8px 16px;font-weight:800;border:none;"
        )
        next_btn.clicked.connect(self._confirm)
        btn_row.addStretch()
        btn_row.addWidget(next_btn)
        layout.addLayout(btn_row)

    def _confirm(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self._orders_by_row):
            QMessageBox.warning(self, "تنبيه", "اختر فاتورة أول.")
            return
        self.selected_order_id = self._orders_by_row[row]
        self.accept()


class PurchaseReturnDialog(QDialog):
    """نافذة مرتجع شراء مرتبطة بفاتورة محددة - تحديد الكل أو صنف صنف،
    بالكمية (باكيت، نفس وحدة الشراء الأصلية)، مع منع إدخال أكبر من
    الكمية الأصلية بالفاتورة."""

    def __init__(self, session, order, parent=None):
        super().__init__(parent)
        self.session = session
        self.order = order
        self.setWindowTitle(f"مرتجع شراء - فاتورة {purchase_order_display_number(order)}")
        self.setMinimumSize(560, 440)
        layout = QVBoxLayout(self)

        supplier = session.query(Supplier).get(order.supplier_id) if order.supplier_id else None
        header = QLabel(f"المورد: {supplier.name if supplier else '—'}   |   فاتورة {purchase_order_display_number(order)}")
        header.setStyleSheet("font-weight:700;")
        layout.addWidget(header)

        select_all_row = QHBoxLayout()
        self.select_all_cb = QCheckBox("تحديد الكل (إرجاع كامل الفاتورة)")
        self.select_all_cb.stateChanged.connect(self._toggle_select_all)
        select_all_row.addWidget(self.select_all_cb)
        select_all_row.addStretch()
        layout.addLayout(select_all_row)

        # --- رقم وصل الإرجاع (يختلف عن رقم وصل الفاتورة الأصلية) + تاريخ
        # الوصل (تلقائي بتاريخ اليوم، قابل للتعديل) ---
        return_receipt_row = QHBoxLayout()
        return_receipt_row.addWidget(QLabel("رقم وصل الإرجاع:"))
        self.receipt_number_input = QLineEdit()
        self.receipt_number_input.setPlaceholderText("رقم وصل الإرجاع (اختياري)...")
        return_receipt_row.addWidget(self.receipt_number_input, stretch=1)
        return_receipt_row.addWidget(QLabel("تاريخ الوصل:"))
        self.return_date_input = QDateEdit(QDate.currentDate())
        self.return_date_input.setCalendarPopup(True)
        self.return_date_input.setDisplayFormat("yyyy-MM-dd")
        return_receipt_row.addWidget(self.return_date_input)
        layout.addLayout(return_receipt_row)

        self.table = QTableWidget()
        enable_touch_scroll(self.table)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["إرجاع", "الصنف", "الكمية الأصلية", "الكمية المرتجعة", "السعر", "قيمة المرتجع"]
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

        self._rows = []  # (item, checkbox, qty_input, product_name)
        already_returned_by_product = self._already_returned_by_product()
        self.table.setRowCount(len(order.items))
        for row, oi in enumerate(order.items):
            product = session.query(Product).get(oi.product_id) if oi.product_id else None
            name = product.name if product else (oi.raw_ocr_text or "صنف محذوف")
            already = already_returned_by_product.get(oi.product_id, 0)
            available_to_return = max(oi.quantity - already, 0)

            cb = QCheckBox()
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.addWidget(cb)
            self.table.setCellWidget(row, 0, cb_widget)

            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(str(available_to_return)))

            qty_input = NumberLineEdit(decimals=2)
            self.table.setCellWidget(row, 3, qty_input)

            self.table.setItem(row, 4, QTableWidgetItem(fmt_money(oi.unit_cost)))
            self.table.setItem(row, 5, QTableWidgetItem(fmt_money(0)))

            cb.stateChanged.connect(lambda _, r=row: self._on_check_changed(r))
            qty_input.editingFinished.connect(lambda r=row: self._recalc_row(r))

            self._rows.append({
                "item": oi, "checkbox": cb, "qty_input": qty_input,
                "max_qty": available_to_return, "name": name,
            })
        self.table.resizeRowsToContents()

        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("ملاحظة:"))
        self.note_input = QLineEdit()
        note_row.addWidget(self.note_input, stretch=1)
        layout.addLayout(note_row)

        self.total_label = QLabel("إجمالي المرتجع: 0 د.ع")
        self.total_label.setStyleSheet(f"font-weight:800;color:{RED_500};font-size:14px;")
        layout.addWidget(self.total_label)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("حفظ المرتجع")
        save_btn.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:{RADIUS_BUTTON}px;padding:10px;font-weight:800;border:none;"
        )
        save_btn.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _already_returned_by_product(self):
        """كمية كل صنف سبق إرجاعها بمرتجعات سابقة لنفس الفاتورة - حتى ما
        نسمح نرجّع أكثر من المتبقي فعليًا لو صار مرتجع جزئي قبل."""
        result = {}
        prior_returns = (
            self.session.query(PurchaseReturn)
            .filter(PurchaseReturn.purchase_order_id == self.order.id)
            .all()
        )
        for pr in prior_returns:
            for it in pr.items:
                result[it.product_id] = result.get(it.product_id, 0) + it.quantity
        return result

    def _toggle_select_all(self, state):
        checked = self.select_all_cb.isChecked()
        for r in self._rows:
            r["checkbox"].setChecked(checked)
            if checked:
                r["qty_input"].set_value(r["max_qty"])
            self._recalc_row(self._rows.index(r))

    def _on_check_changed(self, row):
        r = self._rows[row]
        if r["checkbox"].isChecked() and r["qty_input"].value() == 0:
            r["qty_input"].set_value(r["max_qty"])
        self._recalc_row(row)

    def _recalc_row(self, row):
        r = self._rows[row]
        qty = r["qty_input"].value()
        if qty > r["max_qty"]:
            qty = r["max_qty"]
            r["qty_input"].set_value(qty)
        if qty < 0:
            qty = 0
            r["qty_input"].set_value(qty)
        subtotal = qty * r["item"].unit_cost
        self.table.setItem(row, 5, QTableWidgetItem(fmt_money(subtotal)))
        self._recalc_total()

    def _recalc_total(self):
        total = 0
        for i, r in enumerate(self._rows):
            qty = r["qty_input"].value()
            total += qty * r["item"].unit_cost
        self.total_label.setText(f"إجمالي المرتجع: {fmt_money(total)}")

    def _save(self):
        selected = [r for r in self._rows if r["checkbox"].isChecked() and r["qty_input"].value() > 0]
        if not selected:
            QMessageBox.warning(self, "تنبيه", "حدد صنف واحد على الأقل بكمية أكبر من صفر.")
            return

        total_amount = 0
        return_items = []
        for r in selected:
            qty = r["qty_input"].value()
            if qty > r["max_qty"]:
                QMessageBox.warning(self, "تنبيه", f"الكمية المرتجعة لـ {r['name']} أكبر من المتاح.")
                return
            subtotal = qty * r["item"].unit_cost
            total_amount += subtotal
            return_items.append((r["item"], qty, subtotal))

        purchase_return = PurchaseReturn(
            purchase_order_id=self.order.id,
            total_amount=total_amount,
            note=self.note_input.text().strip() or None,
            receipt_number=self.receipt_number_input.text().strip() or None,
            return_date=self.return_date_input.date().toPython(),
        )
        self.session.add(purchase_return)
        self.session.flush()

        for oi, qty, subtotal in return_items:
            self.session.add(PurchaseReturnItem(
                purchase_return_id=purchase_return.id, product_id=oi.product_id,
                quantity=qty, unit_price=oi.unit_cost, subtotal=subtotal,
            ))
            # تحديث المخزون: نرجع الكمية من نفس دفعة هذي الفاتورة (batch_number
            # المولّد وقت التأكيد: PO-{order_id}-{product_id}) - نفس منطق ربط
            # الدفعة بالفاتورة المستخدم بكل مكان ثاني بالمشروع.
            if oi.product_id:
                product = self.session.query(Product).get(oi.product_id)
                spc = (product.strips_per_carton or 3) if product else 3
                strip_qty = _strips_from_cartons(qty, spc)
                batch = (
                    self.session.query(Batch)
                    .filter(Batch.batch_number == f"PO-{self.order.id}-{oi.product_id}")
                    .first()
                )
                if batch:
                    batch.quantity_available = max(batch.quantity_available - strip_qty, 0)
                    self.session.add(StockMovement(
                        batch_id=batch.id, movement_type="مرتجع للمورد", quantity=-strip_qty,
                        note=f"مرتجع شراء #{purchase_return.id} - فاتورة {purchase_order_display_number(self.order)}",
                    ))
        self.session.commit()
        QMessageBox.information(self, "تم", "تم حفظ المرتجع وتحديث المخزون بنجاح.")
        self.accept()


class PaymentReceiptDialog(QDialog):
    """نافذة تسجيل وصل دفع - اختيار فواتير غير مسددة/مسددة جزئيًا لهذا
    المورد، خصم اختياري (مبلغ ثابت أو نسبة %)، ملاحظة. الخصم يوزّع
    تناسبيًا على الفواتير المحددة حسب حصة كل وحدة من الإجمالي قبل الخصم،
    حتى مجموع المبالغ المطبّقة = الصافي المدفوع بالضبط.

    نفس النافذة تُستخدم لإنشاء وصل جديد ولتعديل وصل موجود (مرّر
    existing_receipt): بالتعديل، تنحمّل بيانات الوصل الحالية (رقمه،
    تاريخه، الفواتير المحددة فيه، الخصم، الملاحظة) جاهزة، وتقدر تضيف
    فواتير جديدة أو تشيل فواتير كانت محددة (بالتأشير/إلغاء التأشير
    بنفس الجدول)، وتعدّل رقم الوصل والتاريخ - الحفظ يحذف تخصيصات الوصل
    القديمة ويعيد بناءها من التحديد الحالي بدل ما يسوي وصل جديد منفصل."""

    def __init__(self, session, supplier, parent=None, existing_receipt=None):
        super().__init__(parent)
        self.session = session
        self.supplier = supplier
        self.existing_receipt = existing_receipt
        self.is_percent = bool(existing_receipt and existing_receipt.discount_type == "percent")
        self.setWindowTitle(f"{'تعديل وصل دفع' if existing_receipt else 'تسديد دفعة'} - {supplier.name}")
        self.setMinimumSize(600, 520)
        layout = QVBoxLayout(self)

        receipt_row = QHBoxLayout()
        receipt_row.addWidget(QLabel("رقم وصل الدفع:"))
        self.receipt_number_input = QLineEdit(existing_receipt.receipt_number if existing_receipt else "")
        self.receipt_number_input.setPlaceholderText("رقم وصل الدفع...")
        receipt_row.addWidget(self.receipt_number_input, stretch=1)
        receipt_row.addWidget(QLabel("تاريخ الوصل:"))
        initial_date = QDate(existing_receipt.payment_date) if existing_receipt and existing_receipt.payment_date else QDate.currentDate()
        self.payment_date_input = QDateEdit(initial_date)
        self.payment_date_input.setCalendarPopup(True)
        self.payment_date_input.setDisplayFormat("yyyy-MM-dd")
        receipt_row.addWidget(self.payment_date_input)
        layout.addLayout(receipt_row)

        layout.addWidget(QLabel("الفواتير غير المسددة أو المسددة جزئيًا (اضغط على رقم أي فاتورة لفتحها وعرض/تعديل أصنافها):"))

        # خانة بحث صغيرة عن فاتورة/مرتجع بكتابة رقم وصله - بمجرد ما تكتب،
        # الجدول ينتقل تلقائيًا للصف المطابق ويضلله بخلفية صفراء (نفس فكرة
        # خانات البحث الحي الثانية بالنظام - كشف الحساب وواجهة الموردين
        # العامة)، بدون زر أو نافذة منبثقة منفصلة.
        search_row = QHBoxLayout()
        self.invoice_search_input = QLineEdit()
        self.invoice_search_input.setPlaceholderText("بحث برقم الوصل ضمن الجدول تحت...")
        self.invoice_search_input.textChanged.connect(self._live_search_invoice)
        search_row.addWidget(self.invoice_search_input)
        layout.addLayout(search_row)

        self.table = QTableWidget()
        enable_touch_scroll(self.table)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["تحديد", "رقم الفاتورة", "التاريخ", "إجمالي الفاتورة", "المتبقي"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        # ما نخلي الجدول قابل للتعديل المباشر (كان يفتح وضع تعديل نص الخلية
        # بالضغط المزدوج على أي عمود بالغلط، منها عمود رقم الفاتورة اللي
        # المفروض يفتح نافذة الفاتورة بدل ما يصير حقل نص قابل للكتابة).
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table, stretch=1)

        self._no_invoices_label = QLabel("ماكو فواتير غير مسددة لهذا المورد.")
        self._no_invoices_label.setVisible(False)
        layout.addWidget(self._no_invoices_label)

        self._rows = []
        # بوضع التعديل، الفواتير المدرجة أصلًا بهذا الوصل لازم تنحدد
        # (checked) تلقائيًا فور فتح النافذة - يمثّل الحالة الحالية قبل
        # أي تغيير يسويه المستخدم.
        initial_selected_ids = (
            {a.purchase_order_id for a in existing_receipt.allocations} if existing_receipt else None
        )
        self._reload_table(preserve_selected_ids=initial_selected_ids)

        totals_row = QHBoxLayout()
        self.subtotal_label = QLabel("إجمالي الفواتير المحددة: 0 د.ع")
        totals_row.addWidget(self.subtotal_label)
        layout.addLayout(totals_row)

        discount_row = QHBoxLayout()
        discount_row.addWidget(QLabel("الخصم:"))
        self.discount_input = NumberLineEdit(placeholder="قيمة الخصم")
        if existing_receipt:
            self.discount_input.set_value(existing_receipt.discount_value)
        self.discount_input.editingFinished.connect(self._recalc)
        discount_row.addWidget(self.discount_input)
        self.percent_btn = QPushButton("%")
        self.percent_btn.setCheckable(True)
        self.percent_btn.setChecked(self.is_percent)
        self.percent_btn.setFixedWidth(40)
        self.percent_btn.setStyleSheet(
            "QPushButton{background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;font-weight:800;}"
            f"QPushButton:checked{{background:{TEAL_600};color:white;border:1px solid {TEAL_600};}}"
        )
        self.percent_btn.toggled.connect(self._on_percent_toggled)
        discount_row.addWidget(self.percent_btn)
        discount_row.addStretch()
        layout.addLayout(discount_row)

        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("ملاحظة:"))
        self.note_input = QLineEdit(existing_receipt.note if existing_receipt and existing_receipt.note else "")
        note_row.addWidget(self.note_input, stretch=1)
        layout.addLayout(note_row)

        self.final_label = QLabel("الصافي المدفوع: 0 د.ع")
        self.final_label.setStyleSheet(f"font-weight:800;color:{TEAL_700};font-size:15px;")
        layout.addWidget(self.final_label)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("حفظ التعديلات" if existing_receipt else "حفظ / تسديد الدفعة")
        save_btn.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:{RADIUS_BUTTON}px;padding:10px;font-weight:800;border:none;"
        )
        save_btn.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self._recalc()

    def _reload_table(self, preserve_selected_ids=None):
        """يبني/يعيد بناء جدول الفواتير من قاعدة البيانات من جديد - يُستخدم
        عند فتح النافذة أول مرة، وبعد الرجوع من فتح فاتورة للتعديل.

        كل فاتورة عليها مرتجع (كامل أو جزئي) تظهر بسطرين منفصلين تمامًا،
        مو سطر وحد مدموج:
        1. سطر "الفاتورة الأصلية" - بمبلغها الصافي المتبقي فعلاً بعد طرح
           المرتجع (لو فاتورة أصلها 5 وانرجع منها 2، هذا السطر يبين
           المتبقي الحقيقي المستحق منها - 3 مثلًا لو ما انسدد شي).
        2. سطر "المرتجع" لحاله - برقم وصل الإرجاع الخاص فيه (لا رقم وصل
           الفاتورة الأصلية)، بمبلغه هو بالذات بالسالب، ملوّن بالأحمر.
           لو نفس الفاتورة عليها أكثر من مرتجع (إرجاع جزئي أكثر من مرة)،
           كل مرتجع ياخذ سطره المستقل الخاص فيه.

        فواتير المرتجع تنضاف دائمًا آخر شي بالجدول (بعد كل الفواتير
        العادية) بما إنها تُبنى بحلقة منفصلة تُضاف بعد حلقة الفواتير."""
        preserve_selected_ids = preserve_selected_ids or set()
        # بوضع التعديل: تخصيصات هذا الوصل نفسه (existing_receipt) لازم
        # "تترجّع" مؤقتًا لحساب "المتبقي" الحقيقي للفواتير العادية - وإلا
        # فاتورة انسددت بالكامل بهذا الوصل بالذات كانت راح تختفي من
        # القائمة تمامًا وقت التعديل.
        existing_alloc_by_order = (
            {a.purchase_order_id: a.amount_applied for a in self.existing_receipt.allocations}
            if self.existing_receipt else {}
        )
        self._rows = []
        orders = (
            self.session.query(PurchaseOrder)
            .filter(PurchaseOrder.supplier_id == self.supplier.id, PurchaseOrder.status == "confirmed")
            .order_by(PurchaseOrder.order_date.asc())
            .all()
        )
        summaries = bulk_order_summaries(self.session, orders)

        # --- 1) سطور الفواتير العادية (صافي المتبقي بعد طرح أي مرتجع منها،
        # زي ما كان دائمًا - المرتجع نفسه ما يظهر بهذا السطر، له سطره لحاله
        # بالأسفل) ---
        order_rows = []
        for o in orders:
            summary = summaries[o.id]
            raw_remaining = summary["net_total"] - summary["paid"] + existing_alloc_by_order.get(o.id, 0)
            if summary["payment_status"] == "تسديد" or o.id in existing_alloc_by_order:
                order_rows.append((o, raw_remaining))

        # --- 2) سطور المرتجعات - كل PurchaseReturn سطر مستقل لحاله، برقم
        # وصله الخاص. ما نعرض مرتجع مسجّل (settled) بوصل دفع ثاني غير هذا
        # (تجنّب التكرار/الاحتساب المضاعف عبر أكثر من وصل بنفس الوقت) - إلا
        # لو هو نفسه مسجّل بهذا الوصل اللي نعدّله حاليًا (existing_receipt)،
        # وقتها لازم يبين محدد (checked) زي حالته الحالية بالضبط. ---
        return_rows = []
        order_ids = [o.id for o in orders]
        if order_ids:
            order_by_id = {o.id: o for o in orders}
            all_returns = (
                self.session.query(PurchaseReturn)
                .filter(PurchaseReturn.purchase_order_id.in_(order_ids))
                .order_by(PurchaseReturn.return_date.asc())
                .all()
            )
            editing_receipt_id = self.existing_receipt.id if self.existing_receipt else None
            for pr in all_returns:
                if pr.settled_in_receipt_id is not None and pr.settled_in_receipt_id != editing_receipt_id:
                    continue  # مسجّل أصلًا بوصل دفع ثاني - ما يتكرر هنا
                return_rows.append((pr, order_by_id.get(pr.purchase_order_id)))

        self.table.setRowCount(len(order_rows) + len(return_rows))
        row_idx = 0
        for o, raw_remaining in order_rows:
            cb = QCheckBox()
            cb.setChecked(o.id in preserve_selected_ids)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.addWidget(cb)
            self.table.setCellWidget(row_idx, 0, cb_widget)
            cb.stateChanged.connect(self._recalc)

            date_str = o.order_date.strftime("%Y-%m-%d") if o.order_date else "-"
            # عمود رقم الفاتورة يبين كرابط قابل للضغط (لون مميز + خط تحت) -
            # الضغط عليه (بأي مكان بنفس الصف ما عدا خانة التحديد) يفتح نافذة
            # الفاتورة كاملة بأصنافها وكمياتها للعرض/التعديل مباشرة.
            invoice_item = QTableWidgetItem(purchase_order_display_number(o))
            invoice_item.setForeground(QColor(TEAL_700))
            font = invoice_item.font()
            font.setBold(True)
            font.setUnderline(True)
            invoice_item.setFont(font)
            invoice_item.setToolTip("اضغط لفتح تفاصيل الفاتورة")
            self.table.setItem(row_idx, 1, invoice_item)
            self.table.setItem(row_idx, 2, QTableWidgetItem(date_str))
            self.table.setItem(row_idx, 3, QTableWidgetItem(fmt_money(o.total_amount)))
            remaining_item = QTableWidgetItem(fmt_money(raw_remaining))
            if raw_remaining < 0:
                remaining_item.setForeground(QColor(RED_500))
            self.table.setItem(row_idx, 4, remaining_item)
            self._rows.append({"kind": "order", "order": o, "checkbox": cb, "remaining": raw_remaining})
            row_idx += 1

        for pr, o in return_rows:
            cb = QCheckBox()
            cb.setChecked(self.existing_receipt is not None and pr.settled_in_receipt_id == self.existing_receipt.id)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.addWidget(cb)
            self.table.setCellWidget(row_idx, 0, cb_widget)
            cb.stateChanged.connect(self._recalc)

            date_str = pr.return_date.strftime("%Y-%m-%d") if pr.return_date else "-"
            # سطر المرتجع مستقل تمامًا عن سطر فاتورته الأصلية - رقم الوصل
            # المعروض هو رقم وصل الإرجاع نفسه (اللي كتبه المستخدم وقت
            # تسجيل المرتجع)، لا رقم وصل الفاتورة الأصلية، حتى يقدر يلقاه
            # بسهولة بالظبط بالرقم اللي يدوّر عليه.
            label = purchase_return_display_number(pr, o)
            return_item = QTableWidgetItem(label)
            return_item.setForeground(QColor(RED_500))
            font = return_item.font()
            font.setBold(True)
            font.setUnderline(True)
            return_item.setFont(font)
            return_item.setToolTip("مرتجع شراء - سطر توثيقي منفصل، ما يُحاسب عليه بالصافي المدفوع")
            self.table.setItem(row_idx, 1, return_item)
            self.table.setItem(row_idx, 2, QTableWidgetItem(date_str))
            self.table.setItem(row_idx, 3, QTableWidgetItem(fmt_money(-pr.total_amount)))
            remaining_item = QTableWidgetItem(fmt_money(-pr.total_amount))
            remaining_item.setForeground(QColor(RED_500))
            self.table.setItem(row_idx, 4, remaining_item)
            self._rows.append({"kind": "return", "purchase_return": pr, "order": o, "checkbox": cb, "remaining": -pr.total_amount})
            row_idx += 1

        self.table.resizeRowsToContents()
        self._no_invoices_label.setVisible(row_idx == 0)

    def _on_cell_clicked(self, row, col):
        # حماية من الضغط بمنطقة فاضية بالجدول (Qt يرسل row=-1 أحيانًا) - وأي
        # عمود غير عمود رقم الفاتورة (1) ما يسوي شي (خصوصًا عمود "تحديد"
        # اللي له widget/checkbox خاص فيه).
        if col != 1 or row < 0 or row >= len(self._rows) or self.table.item(row, col) is None:
            return
        try:
            row_data = self._rows[row]
            selected_order_ids = {r["order"].id for r in self._selected_rows() if r["kind"] == "order"}
            if row_data["kind"] == "order":
                # استيراد متأخر (lazy) - purchase_view.py يستورد من هذا الملف
                # أصلًا (SupplierStatementDialog وغيرها)، فاستيراد عكسي بأعلى
                # الملف يسبب circular import.
                from app.ui.purchase_view import PurchaseOrderDetailDialog
                dialog = PurchaseOrderDetailDialog(row_data["order"], self.session, self)
                dialog.exec()
            else:
                dialog = PurchaseReturnDetailDialog(self.session, row_data["purchase_return"], self)
                dialog.exec()
            # نعيد بناء الجدول بعد الرجوع - يحدّث "إجمالي الفاتورة"/"المتبقي" لو
            # تغيّرت الكمية أو السعر، ويحافظ على تحديد نفس الفواتير العادية
            # اللي كانت محددة سابقًا (بغض النظر عن الفاتورة اللي انفتحت وانسكرت).
            # ملاحظة: لو المرتجع المفتوح انحذف من نافذته، بيختفي هو تلقائيًا
            # من هذا الجدول بعد إعادة البناء (ما يظهر إلا لو موجود فعليًا).
            self._reload_table(preserve_selected_ids=selected_order_ids)
            self._recalc()
        except Exception as exc:
            QMessageBox.warning(self, "تنبيه", f"ماكو فتح للسطر المحدد.\n({exc})")

    def _live_search_invoice(self, text):
        """بحث حي عن فاتورة/مرتجع بكتابة رقم وصله ضمن جدول هذا الوصل بس -
        بمجرد ما تكتب، الجدول ينتقل تلقائيًا للصف المطابق ويضلله."""
        # نمسح تظليل بحث سابق (لو أكو) قبل لا نضلل الصف الجديد.
        old_row = getattr(self, "_search_highlighted_row", None)
        if old_row is not None and 0 <= old_row < self.table.rowCount():
            for col in range(1, self.table.columnCount()):
                item = self.table.item(old_row, col)
                if item:
                    item.setBackground(QBrush())
        self._search_highlighted_row = None

        text = text.strip()
        if not text:
            return
        for row, r in enumerate(self._rows):
            receipt_no = (r["order"].receipt_number if r["kind"] == "order" else r["purchase_return"].receipt_number) or ""
            if receipt_no and text in receipt_no:
                self.table.selectRow(row)
                anchor_item = self.table.item(row, 1)
                if anchor_item:
                    self.table.scrollToItem(anchor_item, QTableWidget.PositionAtCenter)
                for col in range(1, self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(QColor("#FEF3C7"))
                self._search_highlighted_row = row
                return

    def _on_percent_toggled(self, checked):
        self.is_percent = checked
        self._recalc()

    def _selected_rows(self):
        return [r for r in self._rows if r["checkbox"].isChecked()]

    def _payable_selected(self):
        """الفواتير العادية المحددة اللي فعلاً عليها مبلغ مستحق (متبقي >
        0) - هذي بس اللي تدخل بحساب الإجمالي/الخصم/الصافي المدفوع فعليًا."""
        return [r for r in self._selected_rows() if r["kind"] == "order" and r["remaining"] > 0]

    def _credit_selected(self):
        """سطور المرتجعات المحددة - تنضاف لنفس وصل الدفع للتوثيق فقط (تظهر
        بقائمة فواتير الوصل، ملوّنة بالأحمر، بمبلغها الحقيقي بالسالب)،
        بدون ما تأثر على الإجمالي/الخصم/الصافي المدفوع إطلاقًا - "ما راح
        تحاسب عليها" بالضبط متل ما طلب."""
        return [r for r in self._selected_rows() if r["kind"] == "return"]

    def _recalc(self):
        payable = self._payable_selected()
        subtotal = sum(r["remaining"] for r in payable)
        self.subtotal_label.setText(f"إجمالي الفواتير المحددة: {fmt_money(subtotal)}")

        discount_value = self.discount_input.value()
        if self.is_percent:
            discount_amount = subtotal * (discount_value / 100)
        else:
            discount_amount = discount_value
        discount_amount = min(max(discount_amount, 0), subtotal)
        final = subtotal - discount_amount
        self.final_label.setText(f"الصافي المدفوع: {fmt_money(final)}")
        return subtotal, discount_amount, final

    def _save(self):
        payable = self._payable_selected()
        credit_only = self._credit_selected()
        if not payable and not credit_only:
            QMessageBox.warning(self, "تنبيه", "حدد فاتورة واحدة على الأقل.")
            return
        if not payable:
            QMessageBox.warning(
                self, "تنبيه",
                "حدد فاتورة واحدة على الأقل عليها مبلغ مستحق فعلي للتسديد - فاتورة المرتجع بروحها ما تكفي لتسجيل وصل دفع."
            )
            return
        subtotal, discount_amount, final = self._recalc()
        if final <= 0:
            QMessageBox.warning(self, "تنبيه", "الصافي المدفوع لازم يكون أكبر من صفر.")
            return

        if self.existing_receipt:
            # وضع التعديل: نحدّث نفس سجل الوصل الموجود (مو ننشئ وصل جديد)،
            # ونحذف كل تخصيصاته القديمة لنعيد بناءها من جديد حسب التحديد
            # الحالي بالجدول - أبسط وأضمن من محاولة "مطابقة الفروقات" فاتورة
            # فاتورة، خصوصًا إنه ممكن تنضاف أو تنشال فواتير كاملة من التحديد.
            receipt = self.existing_receipt
            receipt.receipt_number = self.receipt_number_input.text().strip() or None
            receipt.payment_date = self.payment_date_input.date().toPython()
            receipt.discount_type = "percent" if self.is_percent else "fixed"
            receipt.discount_value = self.discount_input.value()
            receipt.total_before_discount = subtotal
            receipt.total_after_discount = final
            receipt.note = self.note_input.text().strip() or None
            for old_alloc in list(receipt.allocations):
                self.session.delete(old_alloc)
            self.session.flush()
        else:
            receipt = PaymentReceipt(
                supplier_id=self.supplier.id,
                receipt_number=self.receipt_number_input.text().strip() or None,
                payment_date=self.payment_date_input.date().toPython(),
                discount_type="percent" if self.is_percent else "fixed",
                discount_value=self.discount_input.value(),
                total_before_discount=subtotal,
                total_after_discount=final,
                note=self.note_input.text().strip() or None,
            )
            self.session.add(receipt)
            self.session.flush()

        # توزيع الصافي تناسبيًا على الفواتير المستحقة فعليًا (payable) حسب
        # حصة كل وحدة من الإجمالي قبل الخصم - حتى مجموع المبالغ المطبّقة =
        # الصافي بالضبط. فواتير المرتجع (credit_only) ما تدخل هذا التوزيع
        # إطلاقًا - تنضاف بعده بمبلغها الحقيقي (راجع الحلقة تحت).
        remaining_to_allocate = final
        for i, r in enumerate(payable):
            if i == len(payable) - 1:
                amount = remaining_to_allocate  # آخر وحدة تاخذ الباقي (يتلافى فروقات التقريب)
            else:
                share = (r["remaining"] / subtotal) if subtotal else 0
                amount = round(final * share, 0)
                remaining_to_allocate -= amount
            self.session.add(PaymentReceiptAllocation(
                receipt_id=receipt.id, purchase_order_id=r["order"].id, amount_applied=amount,
            ))

        # سطور المرتجعات (credit_only) - ما تُنشئ PaymentReceiptAllocation
        # إطلاقًا (لأنه هذا كان يدخل بحساب "المدفوع" لنفس الفاتورة الأصلية
        # فيصير احتساب مضاعف مع net_total اللي أصلًا طارح قيمة المرتجع مرة
        # وحدة). بدل هذا، نعلّم على المرتجع نفسه إنه "انسجّل" بهذا الوصل عبر
        # settled_in_receipt_id - علامة توثيقية بس، منفصلة تمامًا عن أي
        # حساب مالي (راجع تعليق العمود بـ models.py لتفاصيل السبب).
        #
        # أول شي: أي مرتجع كان مسجّل بهذا الوصل قبل التعديل ولكن المستخدم
        # ألغى تحديده الحين - نرجّعه "غير مسجّل" (يصير متاح يظهر بوصولات
        # ثانية بعدين).
        if self.existing_receipt:
            previously_settled = (
                self.session.query(PurchaseReturn)
                .filter(PurchaseReturn.settled_in_receipt_id == receipt.id)
                .all()
            )
            still_selected_ids = {r["purchase_return"].id for r in credit_only}
            for pr in previously_settled:
                if pr.id not in still_selected_ids:
                    pr.settled_in_receipt_id = None

        for r in credit_only:
            r["purchase_return"].settled_in_receipt_id = receipt.id

        self.session.commit()
        QMessageBox.information(self, "تم", "تم تحديث وصل الدفع بنجاح." if self.existing_receipt else "تم تسجيل وصل الدفع بنجاح.")
        self.accept()


class PaymentReceiptDetailDialog(QDialog):
    """تفاصيل وصل دفع - جدول الفواتير المرتبطة به مع المبلغ المطبّق على
    كل وحدة، ورقم كل فاتورة قابل للضغط لفتحها مباشرة للعرض/التعديل. زر
    "تعديل الوصل" يفتح نفس نافذة تسجيل الدفعة (PaymentReceiptDialog) بوضع
    التعديل - يقدر المستخدم يضيف فواتير جديدة، يشيل فواتير كانت محددة،
    ويعدّل رقم الوصل والتاريخ، والجدول هنا ينحدّث فورًا بعد الحفظ."""

    def __init__(self, session, receipt, parent=None):
        super().__init__(parent)
        self.session = session
        self.receipt = receipt
        self.setMinimumSize(560, 420)
        layout = QVBoxLayout(self)

        self.header = QLabel()
        layout.addWidget(self.header)

        edit_row = QHBoxLayout()
        edit_row.addStretch()
        edit_btn = QPushButton("تعديل الوصل")
        edit_btn.setIcon(icon("edit", color=COLOR_TEXT_PRIMARY, size=14))
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.clicked.connect(self._edit_receipt)
        edit_row.addWidget(edit_btn)
        layout.addLayout(edit_row)

        self.table = QTableWidget()
        table = self.table
        enable_touch_scroll(table)
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["رقم الفاتورة", "التاريخ", "المستحق قبل الدفع", "المدفوع بهذا الوصل", "المتبقي"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.cellClicked.connect(self._open_invoice)
        layout.addWidget(table, stretch=1)

        self.refresh()

    def refresh(self):
        """يعيد بناء الترويسة والجدول من بيانات الوصل الحالية - يُستدعى
        عند الفتح أول مرة، وبعد الرجوع من "تعديل الوصل" مباشرة حتى تنعرض
        القيم الجديدة (رقم الوصل، التاريخ، الفواتير...) فورًا بدون
        الحاجة تسكر وتفتح النافذة من جديد."""
        self.session.refresh(self.receipt)
        receipt = self.receipt
        self.setWindowTitle(f"تفاصيل وصل دفع #{receipt.id}" + (f" - {receipt.receipt_number}" if receipt.receipt_number else ""))
        date_str = receipt.payment_date.strftime("%Y-%m-%d %H:%M") if receipt.payment_date else "-"
        self.header.setText(
            f"تاريخ الدفع: {date_str}\n"
            f"الإجمالي قبل الخصم: {fmt_money(receipt.total_before_discount)}\n"
            f"الخصم: {receipt.discount_value:g}{'%' if receipt.discount_type == 'percent' else ' د.ع'}\n"
            f"الصافي المدفوع: {fmt_money(receipt.total_after_discount)}"
            + (f"\nملاحظة: {receipt.note}" if receipt.note else "")
        )

        # المرتجعات المسجّلة بهذا الوصل - ما تظهر ضمن receipt.allocations
        # إطلاقًا (راجع تعليق settled_in_receipt_id بـ models.py وتعليق
        # PaymentReceiptDialog._save لتفاصيل السبب)، فنجيبها بشكل منفصل
        # هنا حتى تظهر بنفس الجدول كسطور توثيقية إضافية.
        settled_returns = (
            self.session.query(PurchaseReturn)
            .filter(PurchaseReturn.settled_in_receipt_id == receipt.id)
            .all()
        )

        table = self.table
        table.setRowCount(len(receipt.allocations) + len(settled_returns))
        self._rows_meta = []  # [{"kind": "order"/"return", "ref_id": ...}, ...] - بنفس ترتيب صفوف الجدول
        row = 0
        for alloc in receipt.allocations:
            order = self.session.query(PurchaseOrder).get(alloc.purchase_order_id)
            summary = purchase_order_summary(self.session, order) if order else None
            date_str = order.order_date.strftime("%Y-%m-%d") if order and order.order_date else "-"
            # رقم الفاتورة يبين كرابط قابل للضغط (نفس أسلوب الجداول الثانية
            # بهذا الملف) - الضغط عليه يفتح الفاتورة كاملة للعرض/التعديل.
            invoice_item = QTableWidgetItem(purchase_order_display_number(order) if order else "-")
            if order:
                invoice_item.setForeground(QColor(TEAL_700))
                font = invoice_item.font()
                font.setBold(True)
                font.setUnderline(True)
                invoice_item.setFont(font)
                invoice_item.setToolTip("اضغط لفتح تفاصيل الفاتورة")
            table.setItem(row, 0, invoice_item)
            table.setItem(row, 1, QTableWidgetItem(date_str))
            table.setItem(row, 2, QTableWidgetItem(fmt_money((summary["remaining"] + alloc.amount_applied)) if summary else "-"))
            table.setItem(row, 3, QTableWidgetItem(fmt_money(alloc.amount_applied)))
            table.setItem(row, 4, QTableWidgetItem(fmt_money(summary["remaining"]) if summary else "-"))
            self._rows_meta.append({"kind": "order", "ref_id": order.id if order else None})
            row += 1

        for pr in settled_returns:
            order = self.session.query(PurchaseOrder).get(pr.purchase_order_id)
            date_str = pr.return_date.strftime("%Y-%m-%d") if pr.return_date else "-"
            # سطر مرتجع - رقم وصل الإرجاع نفسه (لا رقم الفاتورة الأصلية)،
            # ملوّن بالأحمر دائمًا، والمبلغ (مستحق/مدفوع) = قيمة المرتجع
            # بالسالب، والمتبقي = صفر (سطر توثيقي مقفول بالكامل).
            return_item = QTableWidgetItem(purchase_return_display_number(pr, order))
            return_item.setForeground(QColor(RED_500))
            font = return_item.font()
            font.setBold(True)
            font.setUnderline(True)
            return_item.setFont(font)
            return_item.setToolTip("مرتجع شراء - سطر توثيقي، ما احتُسب بالصافي المدفوع")
            table.setItem(row, 0, return_item)
            table.setItem(row, 1, QTableWidgetItem(date_str))
            due_item = QTableWidgetItem(fmt_money(-pr.total_amount))
            paid_item = QTableWidgetItem(fmt_money(-pr.total_amount))
            remaining_item = QTableWidgetItem(fmt_money(0))
            for it in (due_item, paid_item, remaining_item):
                it.setForeground(QColor(RED_500))
            table.setItem(row, 2, due_item)
            table.setItem(row, 3, paid_item)
            table.setItem(row, 4, remaining_item)
            self._rows_meta.append({"kind": "return", "ref_id": pr.id})
            row += 1

        table.resizeRowsToContents()

    def _edit_receipt(self):
        supplier = self.session.query(Supplier).get(self.receipt.supplier_id)
        if not supplier:
            return
        dialog = PaymentReceiptDialog(self.session, supplier, self, existing_receipt=self.receipt)
        dialog.exec()
        self.refresh()  # ينعكس التعديل (لو صار) بالترويسة والجدول فورًا

    def _open_invoice(self, row, col):
        if row < 0 or row >= len(self._rows_meta) or self.table.item(row, 0) is None:
            return
        meta = self._rows_meta[row]
        if not meta["ref_id"]:
            return
        try:
            if meta["kind"] == "order":
                # استيراد متأخر (lazy) - نفس سبب باقي الاستيرادات المؤجلة
                # بهذا الملف (تفادي circular import مع purchase_view.py).
                from app.ui.purchase_view import PurchaseOrderDetailDialog
                order = self.session.query(PurchaseOrder).get(meta["ref_id"])
                if order:
                    dialog = PurchaseOrderDetailDialog(order, self.session, self)
                    dialog.exec()
            else:
                purchase_return = self.session.query(PurchaseReturn).get(meta["ref_id"])
                if purchase_return:
                    dialog = PurchaseReturnDetailDialog(self.session, purchase_return, self)
                    dialog.exec()
            self.refresh()  # لو انحذف المرتجع من نافذته، يختفي سطره هنا فورًا
        except Exception as exc:
            QMessageBox.warning(self, "تنبيه", f"ماكو فتح للسطر المحدد.\n({exc})")


class PaymentReceiptListDialog(QDialog):
    """وصولات الدفع - كل وصولات الدفع الخاصة بهذا المورد."""

    def __init__(self, session, supplier, parent=None):
        super().__init__(parent)
        self.session = session
        self.supplier = supplier
        self.setWindowTitle(f"وصولات الدفع - {supplier.name}")
        self.setMinimumSize(640, 420)
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        table = self.table
        enable_touch_scroll(table)
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["رقم الوصل", "التاريخ", "الفواتير", "الخصم", "الصافي المدفوع", "الملاحظة"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.cellClicked.connect(self._open_detail)
        layout.addWidget(table, stretch=1)

        self._empty_label = QLabel("ماكو وصولات دفع مسجّلة لهذا المورد.")
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        self.refresh()

    def refresh(self):
        """يعيد بناء الجدول من قاعدة البيانات من جديد - يُستدعى عند الفتح
        أول مرة، وبعد الرجوع من "تعديل الوصل" (PaymentReceiptDetailDialog)
        حتى تنعكس التعديلات (رقم الوصل، الخصم، الصافي...) بالجدول فورًا."""
        receipts = (
            self.session.query(PaymentReceipt)
            .filter(PaymentReceipt.supplier_id == self.supplier.id)
            .order_by(PaymentReceipt.payment_date.desc())
            .all()
        )
        self._receipts = receipts
        self.table.setRowCount(len(receipts))
        for row, r in enumerate(receipts):
            date_str = r.payment_date.strftime("%Y-%m-%d") if r.payment_date else "-"
            discount_str = f"{r.discount_value:g}%" if r.discount_type == "percent" else fmt_money(r.discount_value)
            self.table.setItem(row, 0, QTableWidgetItem(r.receipt_number or "—"))
            self.table.setItem(row, 1, QTableWidgetItem(date_str))

            # أرقام الفواتير المرتبطة بهذا الوصل، مفصولة بفاصلة، وكل رقم
            # قابل للضغط لحاله - يفتح فاتورة الشراء كاملة للتعديل، بنفس
            # طريقة الضغط عليها من كشف الحساب مباشرة. النص المعروض هو رقم
            # الوصل الخاص بتلك الفاتورة (لا الرقم الداخلي) - الرابط (href)
            # يضل يحمل الرقم الداخلي الحقيقي لأنه ضروري لتحديد الفاتورة
            # الصحيحة عند الفتح، بس هذا ما يظهر للمستخدم.
            # المرتجعات المسجّلة بهذا الوصل (settled_in_receipt_id) تنضاف
            # لنفس القائمة، ملوّنة بالأحمر، برقم وصل المرتجع نفسه (لا رقم
            # الفاتورة الأصلية) - راجع تعليق settled_in_receipt_id بـ
            # models.py لسبب انفصالها عن r.allocations.
            related_order_ids = [alloc.purchase_order_id for alloc in r.allocations]
            related_orders = {
                o.id: o for o in self.session.query(PurchaseOrder).filter(PurchaseOrder.id.in_(related_order_ids))
            } if related_order_ids else {}
            links = [
                f'<a href="order:{alloc.purchase_order_id}" style="color:{TEAL_700};text-decoration:none;font-weight:700;">'
                f'{purchase_order_display_number(related_orders[alloc.purchase_order_id])}</a>'
                for alloc in r.allocations if alloc.purchase_order_id in related_orders
            ]
            settled_returns = (
                self.session.query(PurchaseReturn).filter(PurchaseReturn.settled_in_receipt_id == r.id).all()
            )
            links += [
                f'<a href="return:{pr.id}" style="color:{RED_500};text-decoration:none;font-weight:700;">'
                f'{purchase_return_display_number(pr)}</a>'
                for pr in settled_returns
            ]
            invoices_lbl = QLabel("، ".join(links) or "—")
            invoices_lbl.setOpenExternalLinks(False)
            invoices_lbl.linkActivated.connect(self._open_invoice)
            self.table.setCellWidget(row, 2, invoices_lbl)

            self.table.setItem(row, 3, QTableWidgetItem(discount_str))
            self.table.setItem(row, 4, QTableWidgetItem(fmt_money(r.total_after_discount)))
            self.table.setItem(row, 5, QTableWidgetItem(r.note or ""))
        self.table.resizeRowsToContents()
        self._empty_label.setVisible(not receipts)

    def _open_detail(self, row, col):
        # نفس فحص الحماية المطبّق بكل جداول هذا الملف - بدونه، الضغط بمنطقة
        # فاضية (Qt يرسل row=-1 أحيانًا) كان يفتح آخر وصل بالقائمة غلط
        # (بايثون تفسّر [-1] كـ"آخر عنصر") بدل ما يتجاهل الضغطة.
        if row < 0 or row >= len(self._receipts) or self.table.item(row, 0) is None:
            return
        try:
            dialog = PaymentReceiptDetailDialog(self.session, self._receipts[row], self)
            dialog.exec()
            self.refresh()  # ينعكس أي تعديل صار جوة نافذة التفاصيل هنا فورًا
        except Exception as exc:
            QMessageBox.warning(self, "تنبيه", f"ماكو فتح للوصل المحدد.\n({exc})")

    def _open_invoice(self, href):
        kind, _, ref_id_str = href.partition(":")
        ref_id = int(ref_id_str)
        if kind == "order":
            # استيراد متأخر (lazy) - نفس سبب الاستيراد المؤجل بـ
            # SupplierStatementDialog._open_row (تفادي circular import مع
            # purchase_view.py).
            from app.ui.purchase_view import PurchaseOrderDetailDialog
            order = self.session.query(PurchaseOrder).get(ref_id)
            if order:
                dialog = PurchaseOrderDetailDialog(order, self.session, self)
                dialog.exec()
        else:
            purchase_return = self.session.query(PurchaseReturn).get(ref_id)
            if purchase_return:
                dialog = PurchaseReturnDetailDialog(self.session, purchase_return, self)
                dialog.exec()
        self.refresh()  # لو انحذف المرتجع أو تغيّرت الفاتورة، ينعكس هنا فورًا


_RECEIPT_QUERY_STRIP_CHARS = (" ", "-", "_", "/", "\\", ".")
_ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def _normalize_receipt_text(text):
    """يوحّد شكل نص رقم الوصل عشان البحث ما يفشل بسبب فرق كتابة بسيط
    (مسافة، شرطة، حرف كبير/صغير لو الرقم فيه حروف) - يشيل الفواصل الشائعة
    (مسافة/شرطة/سلاش/نقطة) ويحوّل الأرقام العربية أو الفارسية لأرقام
    إنكليزية عادية، ويوحّد حالة الأحرف. مثلًا '٢٠٢٤-٠٠١' و '2024 001' و
    '2024/001' كلهن يصيرن نفس النص الموحّد بعد هذي الدالة."""
    if not text:
        return ""
    out = []
    for ch in text.strip():
        if ch in _ARABIC_INDIC_DIGITS:
            out.append(str(_ARABIC_INDIC_DIGITS.index(ch)))
        elif ch in _PERSIAN_DIGITS:
            out.append(str(_PERSIAN_DIGITS.index(ch)))
        elif ch in _RECEIPT_QUERY_STRIP_CHARS:
            continue
        else:
            out.append(ch.lower())
    return "".join(out)


def _sql_normalized_receipt_column(column):
    """نفس تطبيع _normalize_receipt_text بس مبني داخل استعلام SQL نفسه
    (بدل ما نسحب كل الصفوف لبايثون أول) - يشيل نفس الفواصل ويوحّد حالة
    الأحرف، عبر تسلسل REPLACE()/LOWER() على عمود رقم الوصل مباشرة. هذا
    يخلي المطابقة المتسامحة سريعة حتى لو عند مورد آلاف الفواتير (نفس
    فلسفة bulk_order_summaries بهذا الملف: نخلي قاعدة البيانات تسوي الشغل
    الثقيل بدل بايثون)."""
    expr = func.lower(column)
    for ch in _RECEIPT_QUERY_STRIP_CHARS:
        expr = func.replace(expr, ch, "")
    return expr


def search_by_receipt_number(session, query_text):
    """يبحث عن رقم وصل (فاتورة شراء / مرتجع شراء / وصل دفع) عبر كل
    الموردين دفعة وحدة - يرجع قائمة نتائج (نوع الوصل، المورد، رقمه...)
    الأحدث أولًا. يُستخدم من خانة البحث الجديدة بأعلى شاشة الموردين
    وبزر البحث داخل كشف حساب مورد وحد.

    البحث متسامح مع فرق الكتابة البسيط (مسافة/شرطة زايدة أو ناقصة، حالة
    الأحرف، أرقام عربية بدل إنكليزية) - راجع _normalize_receipt_text -
    عشان "ماكو وصل مطابق" ما تطلع غلط لمجرد فرق تنسيق بسيط عن الرقم
    المسجّل فعليًا.

    كل نتيجة فيها "kind"/"ref_id"/"receipt_no" بنفس الصيغة المستخدمة
    بـ SupplierStatementDialog._row_meta تمامًا - حتى تنمرر مباشرة
    لتظليل الصف الصحيح بكشف الحساب بعد الانتقال إليه (highlight param)."""
    query_text = (query_text or "").strip()
    if not query_text:
        return []
    norm_query = _normalize_receipt_text(query_text)
    if not norm_query:
        return []
    results = []

    orders = (
        session.query(PurchaseOrder)
        .filter(
            PurchaseOrder.receipt_number.isnot(None),
            _sql_normalized_receipt_column(PurchaseOrder.receipt_number).contains(norm_query),
        )
        .all()
    )
    for o in orders:
        supplier = session.query(Supplier).get(o.supplier_id) if o.supplier_id else None
        if not supplier:
            continue
        results.append({
            "kind": "order", "ref_id": o.id, "receipt_no": o.receipt_number or "",
            "label": f"فاتورة شراء - وصل {o.receipt_number}", "supplier": supplier,
            "date": o.order_date,
        })

    returns = (
        session.query(PurchaseReturn)
        .filter(
            PurchaseReturn.receipt_number.isnot(None),
            _sql_normalized_receipt_column(PurchaseReturn.receipt_number).contains(norm_query),
        )
        .all()
    )
    for r in returns:
        order = session.query(PurchaseOrder).get(r.purchase_order_id)
        supplier = session.query(Supplier).get(order.supplier_id) if order and order.supplier_id else None
        if not supplier:
            continue
        results.append({
            "kind": "return", "ref_id": r.id, "receipt_no": r.receipt_number or "",
            "label": f"مرتجع شراء - وصل {r.receipt_number} (فاتورة {purchase_order_display_number(order)})",
            "supplier": supplier, "date": r.return_date,
        })

    receipts = (
        session.query(PaymentReceipt)
        .filter(
            PaymentReceipt.receipt_number.isnot(None),
            _sql_normalized_receipt_column(PaymentReceipt.receipt_number).contains(norm_query),
        )
        .all()
    )
    for pr in receipts:
        supplier = session.query(Supplier).get(pr.supplier_id) if pr.supplier_id else None
        if not supplier:
            continue
        results.append({
            "kind": "receipt", "ref_id": pr.id, "receipt_no": pr.receipt_number or "",
            "label": f"وصل دفع {pr.receipt_number}", "supplier": supplier,
            "date": pr.payment_date,
        })

    results.sort(key=lambda r: r["date"] or datetime.min, reverse=True)
    return results


class _StatementTableModel(QAbstractTableModel):
    """موديل بيانات خفيف لجدول كشف الحساب - هذا هو الإصلاح الجذري (مو
    ترقيعي) لتجمد/انغلاق البرنامج عند إغلاق كشف حساب مورد عنده آلاف
    الفواتير.

    السبب الحقيقي: QTableWidget (اللي كان مستخدم قبل) يبني ويملك جسم
    C++/Python مستقل (QTableWidgetItem) لكل خلية على حدة - مورد عنده
    5000 صف × 6 أعمدة يعني 30,000 جسم فعلي محفوظ بالذاكرة تبع الجدول
    طول ما النافذة مفتوحة. فتح النافذة صار سريع بعد إصلاح سابق
    (resizeRowsToContents)، لكن *إغلاق* النافذة يحتاج Qt يهدم كل هالـ
    30,000 جسم واحد وحد على الخيط الرئيسي (GUI thread) وقت تدمير
    الـ QTableWidget - وهذا التدمير المتزامن الثقيل هو اللي يجمّد
    البرنامج فعليًا لثواني طويلة، وبالأجهزة الأضعف/قواعد بيانات أكبر
    يوصل يطيح البرنامج كامل (نظام التشغيل يعتبره "توقف عن الاستجابة"
    فيقفله قسريًا).

    الحل الجذري: بدل ما نبني عنصر Qt لكل خلية مسبقًا، نستخدم نمط
    Model/View الأصلي بـ Qt - QTableView يعرض البيانات مباشرة من قائمة
    بايثون خفيفة (self._rows، مجرد tuples عادية) عبر دالة data()، وما
    يبني أي جسم Qt فعلي إلا للصفوف الظاهرة فعليًا بالشاشة وقت الرسم
    (virtualized rendering، نفس مبدأ عمل أي جدول احترافي بكميات بيانات
    كبيرة). فتح/إغلاق الجدول يصير فوري بغض النظر عن عدد الصفوف (5 أو
    50 ألف فرق ما يذكر عمليًا) لأنه ماكو أي جسم يتبنى أو يتهدم لكل خلية
    إطلاقًا - بس قائمة بايثون وحدة تُحذف مرة وحدة."""

    HEADERS = ["التاريخ", "رقم الوصل", "العملية", "المبلغ", "الحالة", "الملاحظة"]

    def __init__(self, rows=None, parent=None):
        super().__init__(parent)
        self._rows = rows or []
        self._highlight_row = None

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = rows
        self._highlight_row = None
        self.endResetModel()

    def set_highlight(self, row):
        """يضلل صف وحد بخلفية صفراء (بحث عن وصل) - يبلّغ الواجهة تتحدث
        بس للصفين المتأثرين (القديم والجديد)، مو الجدول كامل."""
        old_row = self._highlight_row
        self._highlight_row = row
        for r in (old_row, row):
            if r is not None and 0 <= r < len(self._rows):
                self.dataChanged.emit(self.index(r, 0), self.index(r, self.columnCount() - 1))

    def row_meta(self, row):
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        dt, label, amount, status_text, status_color, kind, ref_id, note, receipt_no = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return dt.strftime("%Y-%m-%d") if dt else "-"
            if col == 1:
                return receipt_no or "—"
            if col == 2:
                return label
            if col == 3:
                return fmt_money(amount)
            if col == 4:
                return status_text or ""
            if col == 5:
                return note or ""
        elif role == Qt.ForegroundRole:
            if col == 3 and amount < 0:
                return QColor(TEAL_700)
            if col == 4 and status_text:
                return QColor(status_color)
        elif role == Qt.FontRole:
            if col == 4 and status_text:
                font = QFont()
                font.setBold(True)
                return font
        elif role == Qt.BackgroundRole:
            if self._highlight_row is not None and index.row() == self._highlight_row:
                return QColor("#FEF3C7")
        return None


class PurchaseReturnDetailDialog(QDialog):
    """تفاصيل مرتجع شراء وحد - الأصناف المرتجعة، تاريخ ورقم وصل الإرجاع،
    وزر حذف المرتجع نفسه بالكامل.

    حذف المرتجع من هنا يرجّع المخزون المتأثر (يعكس بالضبط العملية اللي
    صارت وقت تسجيل المرتجع بـ PurchaseReturnDialog._save)، ويحذف سجل
    المرتجع نفسه بس - ما يلمس الفاتورة الأصلية (PurchaseOrder) إطلاقًا.
    بما إن حالة/مبلغ الفاتورة الأصلية (مسدد/تسديد/مرتجع...) ما تُخزّن
    بحقل جاهز، وإنما تُحسب مباشرة من app.db.purchase_accounting كل مرة
    اعتمادًا على سجلات المرتجع الموجودة فعليًا - بمجرد حذف هذا السجل،
    الفاتورة الأصلية ترجع لحالتها الطبيعية (كأنه المرتجع ما صار) من
    تلقاء نفسها تلقائيًا، بدون أي لمسة إضافية لها."""

    def __init__(self, session, purchase_return, parent=None):
        super().__init__(parent)
        self.session = session
        self.purchase_return = purchase_return
        self.setWindowTitle(f"تفاصيل مرتجع شراء #{purchase_return.id}")
        self.setMinimumSize(520, 400)
        layout = QVBoxLayout(self)

        order = session.query(PurchaseOrder).get(purchase_return.purchase_order_id)
        date_str = purchase_return.return_date.strftime("%Y-%m-%d") if purchase_return.return_date else "-"
        header = QLabel(
            f"فاتورة الشراء الأصلية: {purchase_order_display_number(order) if order else '— محذوفة —'}\n"
            f"رقم وصل الإرجاع: {purchase_return.receipt_number or '—'}\n"
            f"تاريخ الوصل: {date_str}\n"
            f"إجمالي المرتجع: {fmt_money(purchase_return.total_amount)}"
            + (f"\nملاحظة: {purchase_return.note}" if purchase_return.note else "")
        )
        layout.addWidget(header)

        table = QTableWidget()
        enable_touch_scroll(table)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["الدواء", "الكمية المرتجعة", "الإجمالي"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setRowCount(len(purchase_return.items))
        for row, it in enumerate(purchase_return.items):
            product = session.query(Product).get(it.product_id) if it.product_id else None
            table.setItem(row, 0, QTableWidgetItem(product.name if product else "— دواء محذوف —"))
            table.setItem(row, 1, QTableWidgetItem(str(it.quantity)))
            table.setItem(row, 2, QTableWidgetItem(fmt_money(it.subtotal)))
        table.resizeRowsToContents()
        layout.addWidget(table, stretch=1)

        delete_btn = QPushButton("حذف المرتجع (ترجيع الفاتورة الأصلية لوضعها الطبيعي)")
        delete_btn.setStyleSheet("background:#FEE2E2;color:#B91C1C;border-radius:8px;padding:10px;font-weight:800;")
        delete_btn.clicked.connect(self._delete_return)
        layout.addWidget(delete_btn)

    def _delete_return(self):
        warning_extra = ""
        if self.purchase_return.settled_in_receipt_id:
            warning_extra = "\n\nتنبيه: هذا المرتجع مسجّل ضمن وصل دفع - حذفه هنا يشيله من ذاك الوصل تلقائيًا."
        confirm = QMessageBox.question(
            self, "تأكيد الحذف",
            f"متأكد تريد تحذف هذا المرتجع؟ راح يترجّع المخزون المتأثر تلقائيًا، والفاتورة الأصلية ترجع لحالتها الطبيعية (بدون ما تنحذف هي نفسها).{warning_extra}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        for it in list(self.purchase_return.items):
            if not it.product_id:
                continue
            product = self.session.query(Product).get(it.product_id)
            spc = (product.strips_per_carton or 3) if product else 3
            strip_qty = _strips_from_cartons(it.quantity, spc)
            # نفس batch_number المستخدم بكل مكان ثاني بالمشروع لربط الدفعة
            # بالفاتورة الأصلية (راجع PurchaseReturnDialog._save).
            batch = (
                self.session.query(Batch)
                .filter(Batch.batch_number == f"PO-{self.purchase_return.purchase_order_id}-{it.product_id}")
                .first()
            )
            if batch:
                batch.quantity_available += strip_qty
                self.session.add(StockMovement(
                    batch_id=batch.id, movement_type="إلغاء مرتجع شراء", quantity=strip_qty,
                    note=f"حذف مرتجع شراء #{self.purchase_return.id}",
                ))

        self.session.delete(self.purchase_return)  # يحذف أصناف المرتجع تلقائيًا (cascade) - الفاتورة الأصلية ما تُلمس إطلاقًا
        self.session.commit()
        QMessageBox.information(self, "تم", "تم حذف المرتجع، والفاتورة الأصلية رجعت لحالتها الطبيعية.")
        self.accept()


class SupplierStatementDialog(QDialog):
    """كشف حساب مورد: كل فواتير الشراء + الدفعات + المرتجعات مرتبة بالتاريخ،
    مع عمود "الحالة" (مسدد/تسديد) محسوب تلقائيًا لكل فاتورة، وفتح الفاتورة
    للتعديل بالضغط عليها، وأزرار تسديد دفعة / تسجيل مرتجع / وصولات الدفع."""

    def __init__(self, session, supplier, on_change=None, parent=None, highlight=None):
        super().__init__(parent)
        self.session = session
        self.supplier = supplier
        self.on_change = on_change  # يُستدعى بعد أي تعديل حتى تنحدّث البطاقات بالخلف
        # (kind, ref_id, receipt_no) لصف معين لازم ينضلل ويتحدد تلقائيًا فور
        # فتح كشف الحساب - يوصل من نتيجة "بحث عن وصل" (إما من الخانة العامة
        # بأعلى شاشة الموردين أو من زر البحث بالأسفل بهذي النافذة نفسها).
        self._pending_highlight = highlight
        self.setWindowTitle(f"كشف حساب - {supplier.name}")
        self.setMinimumSize(700, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_20, SPACE_16, SPACE_20, SPACE_16)
        layout.setSpacing(SPACE_12)

        title = QLabel(supplier.name)
        title.setStyleSheet(f"font-size:{FONT_H1[0]}px;font-weight:{FONT_H1[1]};background:transparent;border:none;")
        layout.addWidget(title)

        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("background:transparent;border:none;color:#374151;")
        layout.addWidget(self.summary_label)

        # --- بحث حي داخل كشف الحساب (برقم الوصل أو بالتاريخ) - بنفس فكرة
        # خانة "بحث عن وصل" العامة بواجهة الموردين: تكتب وتلقائيًا (بدون
        # زر أو نافذة منبثقة منفصلة) ينتقل الجدول للصف المطابق ويضلله. بالأعلى
        # مباشرة تحت الملخص، قبل الجدول - نفس مكان خانة البحث بالشاشة العامة. ---
        search_row = QHBoxLayout()
        self.search_receipt_input = QLineEdit()
        self.search_receipt_input.setPlaceholderText("بحث برقم الوصل...")
        self.search_receipt_input.textChanged.connect(self._live_search_receipt)
        search_row.addWidget(self.search_receipt_input, stretch=1)
        self.search_date_input = QLineEdit()
        self.search_date_input.setPlaceholderText("بحث بالتاريخ (مثلًا 2025-06 أو 2025-06-15)...")
        self.search_date_input.textChanged.connect(self._live_search_date)
        search_row.addWidget(self.search_date_input, stretch=1)
        layout.addLayout(search_row)

        self.table = QTableView()
        enable_touch_scroll(self.table)
        self.model = _StatementTableModel()
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.clicked.connect(self._on_table_clicked)
        layout.addWidget(self.table, stretch=1)

        actions_row = QHBoxLayout()
        return_btn = QPushButton("+ تسجيل مرتجع")
        return_btn.setIcon(icon("recycle", color=TEAL_700, size=14))
        return_btn.setCursor(Qt.PointingHandCursor)
        return_btn.clicked.connect(self._record_return)
        receipts_btn = QPushButton("وصولات الدفع")
        receipts_btn.setIcon(icon("file_text", color=COLOR_TEXT_PRIMARY, size=14))
        receipts_btn.setCursor(Qt.PointingHandCursor)
        receipts_btn.clicked.connect(self._show_receipts)
        pay_btn = QPushButton("تسديد دفعة")
        pay_btn.setIcon(icon("cash", color="white", size=14))
        pay_btn.setCursor(Qt.PointingHandCursor)
        pay_btn.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:{RADIUS_BUTTON}px;padding:8px 14px;font-weight:800;border:none;"
        )
        pay_btn.clicked.connect(self._record_payment)
        actions_row.addWidget(return_btn)
        actions_row.addWidget(receipts_btn)
        actions_row.addWidget(pay_btn)
        actions_row.addStretch()
        layout.addLayout(actions_row)

        self.refresh()

    def refresh(self):
        purchases, returns, payments, debt = bulk_supplier_totals(self.session, [self.supplier.id]).get(
            self.supplier.id, (0, 0, 0, 0)
        )
        self.summary_label.setText(
            f"إجمالي المشتريات: {fmt_money(purchases)}   |   إجمالي المرتجعات: {fmt_money(returns)}   |   "
            f"إجمالي المدفوعات: {fmt_money(payments)}   |   الدين الحالي: {fmt_money(debt)}"
        )

        rows = []  # (date, label, amount, status_text, status_color, kind, ref_id, note, receipt_no)
        orders = (
            self.session.query(PurchaseOrder)
            .filter(PurchaseOrder.supplier_id == self.supplier.id, PurchaseOrder.status == "confirmed")
            .all()
        )
        # حساب مجمّع لكل فواتير هذا المورد دفعة وحدة (استعلامين بس بغض
        # النظر عن عدد الفواتير) بدل استعلامين منفصلين لكل فاتورة لحالها -
        # هذا كان السبب الرئيسي لبطء فتح كشف حساب مورد عنده فواتير كثيرة.
        summaries = bulk_order_summaries(self.session, orders)
        for o in orders:
            summary = summaries[o.id]
            status_text = summary["status_display"]
            # لون الحالة يعتمد على أول كلمة بالنص (مسدد/تسديد) حتى لو
            # انضاف لها لاحقة "(مرتجع جزئي)" - النص الحين ممكن يصير
            # "تسديد (مرتجع جزئي)" مثلاً، مو تطابق تام زي قبل.
            if status_text.startswith("مسدد"):
                status_color = TEAL_700
            elif status_text.startswith("مرتجع"):
                status_color = COLOR_TEXT_SECONDARY
            else:
                status_color = RED_500
            # الاعتماد على رقم الوصل بعرض اسم العملية بدل رقم الفاتورة
            # الداخلي المتسلسل (طلب صريح: الاعتماد الفعلي وقت الاستخدام
            # على رقم الوصل مو ترتيب الإدخال الداخلي بقاعدة البيانات).
            rows.append((
                o.order_date, f"فاتورة شراء {purchase_order_display_number(o)}", o.total_amount,
                status_text, status_color, "order", o.id, "", o.receipt_number or "",
            ))
        for p in self.session.query(SupplierPayment).filter(SupplierPayment.supplier_id == self.supplier.id).all():
            rows.append((p.payment_date, "دفعة", -p.amount, "", None, "old_payment", None, p.notes or "", ""))
        for r in self.session.query(PaymentReceipt).filter(PaymentReceipt.supplier_id == self.supplier.id).all():
            rows.append((r.payment_date, "وصل دفع", -r.total_after_discount, "", None, "receipt", r.id, r.note or "", r.receipt_number or ""))
        for r in self.session.query(SupplierReturn).filter(SupplierReturn.supplier_id == self.supplier.id).all():
            rows.append((r.return_date, "مرتجع", -r.amount, "", None, "old_return", None, r.description or "", ""))
        # مرتجعات المشتريات الحديثة (PurchaseReturn، مرتبطة بفاتورة محددة عبر
        # "+ تسجيل مرتجع") - كل مرتجع يظهر سطر لحاله (kind="return")، والضغط
        # عليه يفتح تفاصيل المرتجع نفسه (PurchaseReturnDetailDialog) - فيها
        # زر حذف يرجّع المخزون ويرجّع الفاتورة الأصلية لحالتها الطبيعية بدون
        # ما يحذفها هي (راجع تعليق PurchaseReturnDetailDialog لتفاصيل السبب).
        order_by_id = {o.id: o for o in orders}
        for pr in (
            self.session.query(PurchaseReturn)
            .join(PurchaseOrder, PurchaseReturn.purchase_order_id == PurchaseOrder.id)
            .filter(PurchaseOrder.supplier_id == self.supplier.id)
            .all()
        ):
            related_order = order_by_id.get(pr.purchase_order_id) or self.session.query(PurchaseOrder).get(pr.purchase_order_id)
            label = f"مرتجع شراء - فاتورة {purchase_order_display_number(related_order)}" if related_order else "مرتجع شراء"
            # رقم وصل الإرجاع نفسه (مسجّل بمرتجع الشراء) يختلف عن رقم وصل
            # الفاتورة الأصلية - نعرضه هو بهذا السطر، ونرجع لرقم وصل الفاتورة
            # الأصلية بس لو ما انسجل رقم وصل خاص بالمرتجع (حالة قديمة/اختيارية).
            # kind="return" (لا "order") + ref_id=pr.id (لا purchase_order_id):
            # هذا اللي يميّز سطر المرتجع عن سطر الفاتورة الأصلية نفسها (كان
            # الاثنين يشتركون بنفس kind/ref_id قبل هذا التعديل، فيفتح نفس
            # الفاتورة الأصلية بغض النظر أي سطر تضغط) - الحين الضغط على سطر
            # المرتجع يفتح تفاصيله هو بالذات (PurchaseReturnDetailDialog).
            rows.append((
                pr.return_date, label, -pr.total_amount, "", None,
                "return", pr.id, pr.note or "",
                pr.receipt_number or (related_order.receipt_number if related_order else "") or "",
            ))
        rows.sort(key=lambda x: x[0] or datetime.min, reverse=True)

        self._row_meta = rows
        # ولا سطر لبناء عناصر Qt هنا - المعلومات كلها تروح مباشرة للموديل
        # (self.model.set_rows)، وQTableView يرسم بس الصفوف الظاهرة فعليًا
        # بالشاشة (راجع تعليق _StatementTableModel لتفاصيل السبب/الحل).
        # هذا اللي يخلي فتح وإغلاق الجدول فوريين بغض النظر عن عدد الصفوف.
        self.model.set_rows(rows)
        # ⚠️ إصلاح مهم: refresh() هذي تنادى مباشرة من __init__، يعني *قبل*
        # ما تنفتح النافذة فعليًا على الشاشة (الفاتحة .exec() تصير بعد ما
        # __init__ يخلص بالكامل). سكرول جدول لسا ما انرسم/ماله حجم فعلي
        # بالشاشة غالبًا ما يسوي شي ملموس - نأجل التنفيذ لأول Tick بحلقة
        # الأحداث بعد ما النافذة تكون انفتحت وترسمت فعليًا، حتى السكرول
        # يشتغل صحيح فعلًا مو بس نظريًا.
        QTimer.singleShot(0, self._apply_pending_highlight)

    def _highlight_and_scroll(self, row):
        """يحدد الصف، يسكرول له بحيث يبين بأعلى الجدول مباشرة (مو بس
        "يظهر بمكان ما" بالمنتصف - المستخدم يريدها تبين فورًا بأول ما
        يفتح كشف الحساب، بدون حاجة تدوّرين عليها بالسكرول)، ويضلله بخلفية
        صفراء واضحة - دالة موحّدة يستخدمها التظليل المعلّق (قادم من نتيجة
        بحث بشاشة الموردين العامة) والبحث الحي داخل هذي النافذة نفسها
        (برقم الوصل أو بالتاريخ)."""
        self.table.selectRow(row)
        self.table.scrollTo(self.model.index(row, 0), QAbstractItemView.PositionAtTop)
        self.model.set_highlight(row)

    def _apply_pending_highlight(self):
        """يضلل ويحدد الصف المطلوب لو فيه هايلايت معلّق (جاي من نتيجة بحث
        عن وصل بشاشة الموردين العامة) - يقارن (kind, ref_id, receipt_no)
        بالضبط حتى ينتقي الصف الصحيح بالتحديد لو نفس الفاتورة عندها أكثر
        من سطر بكشف الحساب (فاتورة الشراء نفسها + مرتجع مرتبط فيها مثلًا)."""
        target = self._pending_highlight
        if not target:
            return
        target_kind, target_ref_id, target_receipt_no = target
        for row, (_, _, _, _, _, kind, ref_id, _, receipt_no) in enumerate(self._row_meta):
            if kind == target_kind and ref_id == target_ref_id and receipt_no == target_receipt_no:
                self._highlight_and_scroll(row)
                break
        self._pending_highlight = None  # ما ينطبق إلا أول refresh بعد الفتح

    def _live_search_receipt(self, text):
        """بحث حي برقم الوصل داخل كشف الحساب - بمجرد ما تكتب، ينتقل الجدول
        تلقائيًا لأول صف مطابق ويضلله (بدون زر أو نافذة منبثقة منفصلة)،
        بنفس فكرة خانة "بحث عن وصل" العامة بواجهة الموردين بالضبط.

        متسامح مع فرق الكتابة البسيط (مسافة/شرطة زايدة، حالة الأحرف، أرقام
        عربية) بنفس منطق search_by_receipt_number بالضبط - راجع
        _normalize_receipt_text."""
        norm_text = _normalize_receipt_text(text)
        if not norm_text:
            return
        for row, (_, _, _, _, _, _, _, _, receipt_no) in enumerate(self._row_meta):
            if receipt_no and norm_text in _normalize_receipt_text(receipt_no):
                self._highlight_and_scroll(row)
                return

    def _live_search_date(self, text):
        """بحث حي بالتاريخ داخل كشف الحساب - نفس فكرة البحث برقم الوصل
        بالضبط، بس المطابقة على نص التاريخ (yyyy-MM-dd) بدل رقم الوصل.
        يقبل بحث جزئي (مثلًا "2025-06" يودّي لأول عملية بذاك الشهر)."""
        text = text.strip()
        if not text:
            return
        for row, (dt, _, _, _, _, _, _, _, _) in enumerate(self._row_meta):
            date_str = dt.strftime("%Y-%m-%d") if dt else ""
            if date_str and text in date_str:
                self._highlight_and_scroll(row)
                return

    def _on_table_clicked(self, index):
        self._open_row(index.row(), index.column())

    def _open_row(self, row, col):
        # حماية من فهرس غير صالح (خارج حدود القائمة).
        if row < 0 or row >= len(self._row_meta):
            return
        try:
            _, _, _, _, _, kind, ref_id, _, _ = self._row_meta[row]
            if kind == "order":
                # استيراد متأخر (lazy) - purchase_view.py يستورد من هذا الملف
                # أصلًا، فاستيراد عكسي بأعلى الملف يسبب circular import.
                from app.ui.purchase_view import PurchaseOrderDetailDialog
                order = self.session.query(PurchaseOrder).get(ref_id)
                if order:
                    dialog = PurchaseOrderDetailDialog(order, self.session, self)
                    dialog.exec()
                    self.refresh()
                    if self.on_change:
                        self.on_change()
            elif kind == "return":
                purchase_return = self.session.query(PurchaseReturn).get(ref_id)
                if purchase_return:
                    dialog = PurchaseReturnDetailDialog(self.session, purchase_return, self)
                    dialog.exec()
                    self.refresh()
                    if self.on_change:
                        self.on_change()
            elif kind == "receipt":
                receipt = self.session.query(PaymentReceipt).get(ref_id)
                if receipt:
                    dialog = PaymentReceiptDetailDialog(self.session, receipt, self)
                    dialog.exec()
        except Exception as exc:
            # أي خطأ غير متوقع هنا ما نخليه يسكّر كشف الحساب بصمت بدون تفسير
            # (كان هذا يبين للمستخدم وكأن النافذة "خرجت" لوحدها) - نبين رسالة
            # واضحة ونبقى بنفس كشف الحساب مفتوح.
            QMessageBox.warning(self, "تنبيه", f"ماكو فتح للعنصر المحدد.\n({exc})")

    def _record_return(self):
        picker = SupplierInvoicePickerDialog(self.session, self.supplier, self)
        if picker.exec() != QDialog.Accepted or not picker.selected_order_id:
            return
        order = self.session.query(PurchaseOrder).get(picker.selected_order_id)
        if not order:
            return
        dialog = PurchaseReturnDialog(self.session, order, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()
            if self.on_change:
                self.on_change()

    def _record_payment(self):
        dialog = PaymentReceiptDialog(self.session, self.supplier, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()
            if self.on_change:
                self.on_change()

    def _show_receipts(self):
        dialog = PaymentReceiptListDialog(self.session, self.supplier, self)
        dialog.exec()
        self.refresh()  # ينعكس أي تعديل على وصل دفع (رقم/تاريخ/فواتير) بالجدول فورًا
        if self.on_change:
            self.on_change()


def _supplier_totals(session, supplier_id):
    purchases = (
        session.query(func.coalesce(func.sum(PurchaseOrder.total_amount), 0))
        .filter(PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.status == "confirmed")
        .scalar() or 0
    )
    old_payments = (
        session.query(func.coalesce(func.sum(SupplierPayment.amount), 0))
        .filter(SupplierPayment.supplier_id == supplier_id)
        .scalar() or 0
    )
    new_payments = (
        session.query(func.coalesce(func.sum(PaymentReceipt.total_after_discount), 0))
        .filter(PaymentReceipt.supplier_id == supplier_id)
        .scalar() or 0
    )
    payments = old_payments + new_payments
    old_returns = (
        session.query(func.coalesce(func.sum(SupplierReturn.amount), 0))
        .filter(SupplierReturn.supplier_id == supplier_id)
        .scalar() or 0
    )
    order_ids = [o.id for o in session.query(PurchaseOrder.id).filter(PurchaseOrder.supplier_id == supplier_id)]
    new_returns = 0
    if order_ids:
        new_returns = (
            session.query(func.coalesce(func.sum(PurchaseReturn.total_amount), 0))
            .filter(PurchaseReturn.purchase_order_id.in_(order_ids))
            .scalar() or 0
        )
    returns = old_returns + new_returns
    debt = purchases - payments - returns
    return purchases, returns, payments, debt


class SupplierCard(QFrame):
    def __init__(self, session, supplier, totals, on_change=None, parent=None):
        super().__init__(parent)
        self.session = session
        self.supplier = supplier
        self.on_change = on_change
        self.setStyleSheet(
            f"QFrame{{background:{COLOR_SURFACE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_CARD}px;}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_16, SPACE_16, SPACE_16, SPACE_16)
        layout.setSpacing(SPACE_8)

        name_label = QLabel(supplier.name)
        name_label.setStyleSheet(f"font-size:{FONT_H3[0]}px;font-weight:{FONT_H3[1]};background:transparent;border:none;")
        layout.addWidget(name_label)

        contact_label = QLabel(supplier.phone or "لا يوجد جهة اتصال")
        contact_label.setStyleSheet(f"color:{COLOR_TEXT_SECONDARY};background:transparent;border:none;font-size:12px;")
        layout.addWidget(contact_label)

        layout.addSpacing(SPACE_8)

        # الأرقام تجي جاهزة محسوبة مسبقًا (bulk_supplier_totals) بدل ما
        # نحسبها هنا لحالنا بكل بطاقة - أساس حل مشكلة بطء الشاشة لما يكثر
        # عدد الموردين (كان كل بطاقة تسوي 4-5 استعلامات منفصلة).
        purchases_row, self._purchases_value = self._stat_row("إجمالي المشتريات:", fmt_money(0))
        returns_row, self._returns_value = self._stat_row("إجمالي المرتجعات:", fmt_money(0))
        payments_row, self._payments_value = self._stat_row("إجمالي المدفوعات:", fmt_money(0))
        debt_row, self._debt_value = self._stat_row("إجمالي الدين:", fmt_money(0))
        layout.addWidget(purchases_row)
        layout.addWidget(returns_row)
        layout.addWidget(payments_row)
        layout.addWidget(debt_row)
        self.set_totals(totals)

        layout.addSpacing(SPACE_8)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(SPACE_8)
        pay_btn = QPushButton("تسديد دفعة")
        pay_btn.setIcon(icon("cash", color="white", size=14))
        pay_btn.setCursor(Qt.PointingHandCursor)
        pay_btn.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:{RADIUS_BUTTON}px;padding:8px;font-weight:800;border:none;"
        )
        pay_btn.clicked.connect(self._pay)
        statement_btn = QPushButton("كشف حساب")
        statement_btn.setIcon(icon("file_text", color=COLOR_TEXT_PRIMARY, size=14))
        statement_btn.setCursor(Qt.PointingHandCursor)
        statement_btn.setStyleSheet(
            f"background:{COLOR_SURFACE_SUBTLE};color:{COLOR_TEXT_PRIMARY};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_BUTTON}px;padding:8px;font-weight:700;"
        )
        statement_btn.clicked.connect(self._open_statement)
        btn_row.addWidget(pay_btn)
        btn_row.addWidget(statement_btn)
        layout.addLayout(btn_row)

    def _stat_row(self, label_text, value_text):
        """يرجع (row_widget, value_label) - نحتفظ بمرجع لـ value_label حتى
        set_totals() تقدر تحدّث الرقم بمكانه مباشرة بدون ما تهدم/تبني
        البطاقة كلها من جديد (لازم لإصلاح إغلاق كشف الحساب التلقائي تحت)."""
        row = QWidget()
        row.setStyleSheet("background:transparent;border:none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setStyleSheet(f"color:{COLOR_TEXT_SECONDARY};background:transparent;border:none;font-size:13px;")
        value = QLabel(value_text)
        value.setStyleSheet(f"color:{COLOR_TEXT_PRIMARY};background:transparent;border:none;font-weight:800;font-size:13px;")
        h.addWidget(label)
        h.addStretch()
        h.addWidget(value)
        return row, value

    def set_totals(self, totals):
        """يحدّث أرقام البطاقة بمكانها (بدون إعادة إنشاء أي widget) - تُستخدم
        من SupplierAccountsTab.refresh_supplier() عشان تحديث بطاقة مورد وحد
        بعد دفعة/مرتجع/تعديل فاتورة ما يحتاج يهدم بقية بطاقات الشبكة."""
        purchases, returns, payments, debt = totals
        self._purchases_value.setText(fmt_money(purchases))
        self._returns_value.setText(fmt_money(returns))
        self._payments_value.setText(fmt_money(payments))
        self._debt_value.setText(fmt_money(debt))
        debt_color = RED_500 if debt > 0 else TEAL_700
        self._debt_value.setStyleSheet(
            f"color:{debt_color};background:transparent;border:none;font-weight:800;font-size:13px;"
        )

    def _pay(self):
        # الأب هنا لازم يكون النافذة الرئيسية (self.window()) مو البطاقة
        # نفسها (self) - شوف تعليق _open_statement تحت لتفاصيل السبب.
        dialog = PaymentReceiptDialog(self.session, self.supplier, self.window())
        if dialog.exec() == QDialog.Accepted:
            if self.on_change:
                self.on_change()

    def _open_statement(self):
        # مهم: الأب لازم يكون النافذة الرئيسية (self.window()) مو بطاقة
        # المورد (self) نفسها. كشف الحساب نافذة modal طويلة العمر (تنفتح
        # منها فواتير فرعية)، وبطاقة المورد ممكن تنهدم وتنبني من جديد
        # بأي لحظة (لو انضاف مورد جديد أو تغيّر البحث بينما كشف الحساب
        # مفتوح) - وبما إن Qt يحذف تلقائيًا كل نافذة أبوها انحذف، كشف
        # الحساب كان ينسكر لحاله فجأة بلا أي فعل من المستخدم. هذا كان
        # السبب الحقيقي وراء "افتح فاتورة وأسكرها يسكرلي كشف الحساب".
        dialog = SupplierStatementDialog(self.session, self.supplier, on_change=self.on_change, parent=self.window())
        dialog.exec()


class SupplierAccountsTab(QWidget):
    """التبويب الكامل: عنوان + بحث + زر إضافة مورد + شبكة بطاقات الموردين."""

    # عدد بطاقات الموردين المبنية فعليًا بكل صفحة - هذا هو الإصلاح الجذري
    # الثاني لبطء الشاشة (بعد تجميع استعلامات bulk_supplier_totals): حتى لو
    # الاستعلامات صارت سريعة، بناء مئات/آلاف QFrame (كل وحدة فيها عدة
    # QLabel وQPushButton وتدرجات لونية) بمرة وحدة يبقى بطيء بحد ذاته على
    # مستوى واجهة Qt نفسها لما يكثر عدد الموردين. بدل ما نبني بطاقة لكل
    # مورد بقاعدة البيانات، نبني بس صفحة وحدة (30 مورد) بأي لحظة - نفس مبدأ
    # الصفحات المستخدم أصلًا بشاشة المخزون (app/ui/inventory_view.py).
    PAGE_SIZE = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = get_session()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE_24, SPACE_20, SPACE_24, SPACE_20)
        outer.setSpacing(SPACE_16)

        header_row = QHBoxLayout()
        title = QLabel("الموردون والحسابات")
        title.setStyleSheet(f"font-size:{FONT_H1[0]}px;font-weight:{FONT_H1[1]};background:transparent;border:none;")
        header_row.addWidget(title)
        header_row.addStretch()
        add_btn = QPushButton("+ إضافة مورد جديد")
        add_btn.setIcon(icon("plus", color="white", size=14))
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:{RADIUS_BUTTON}px;padding:9px 16px;font-weight:800;border:none;"
        )
        add_btn.clicked.connect(self.add_supplier)
        header_row.addWidget(add_btn)
        outer.addLayout(header_row)

        # --- بحث عن وصل (فاتورة شراء / مرتجع / وصل دفع) عبر كل الموردين -
        # فوق خانة البحث عن مورد بالاسم. يظهر نتائج من عدة موردين ممكنين،
        # والضغط على أي نتيجة يفتح كشف حساب ذاك المورد مباشرة مع تظليل
        # الصف المطابق تلقائيًا (راجع SupplierStatementDialog._apply_pending_highlight). ---
        receipt_search_row = QHBoxLayout()
        self.receipt_search_input = QLineEdit()
        self.receipt_search_input.setPlaceholderText("ابحث عن وصل برقمه (فاتورة شراء / مرتجع / وصل دفع)...")
        self.receipt_search_input.setStyleSheet(
            f"border:1.5px solid {COLOR_BORDER};border-radius:{RADIUS_INPUT}px;"
            f"padding:{SPACE_8}px {SPACE_12}px;background-color:{COLOR_SURFACE};"
        )
        self.receipt_search_input.setMinimumHeight(38)
        self.receipt_search_input.returnPressed.connect(self._search_receipt)
        # بحث حي (بدون ما تحتاج تضغط إنتر أو زر "بحث") - بنفس فكرة بقية
        # خانات البحث الحي بالبرنامج (بحث مورد، بحث برقم الوصل داخل كشف
        # الحساب نفسه...). قبل هذا كانت الخانة تنتظر إنتر/ضغط الزر بس، وهذا
        # كان يبين وكأن البحث "ما يشتغل" لأول وهلة (ماكو أي رد فعل وأنت
        # تكتب) - نستخدم مؤقّت قصير (300ms) حتى ما نبحث بقاعدة البيانات
        # بكل ضغطة حرف وحدها.
        self._receipt_search_timer = QTimer(self)
        self._receipt_search_timer.setSingleShot(True)
        self._receipt_search_timer.setInterval(300)
        self._receipt_search_timer.timeout.connect(self._search_receipt)
        self.receipt_search_input.textChanged.connect(lambda: self._receipt_search_timer.start())
        receipt_search_row.addWidget(self.receipt_search_input, stretch=1)
        receipt_search_btn = QPushButton("بحث")
        receipt_search_btn.setIcon(icon("search", color=COLOR_TEXT_PRIMARY, size=14))
        receipt_search_btn.setCursor(Qt.PointingHandCursor)
        receipt_search_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:8px 14px;")
        receipt_search_btn.clicked.connect(self._search_receipt)
        receipt_search_row.addWidget(receipt_search_btn)
        outer.addLayout(receipt_search_row)

        self._receipt_results = []
        self.receipt_results_list = QListWidget()
        enable_touch_scroll(self.receipt_results_list)
        self.receipt_results_list.setMaximumHeight(170)
        self.receipt_results_list.setStyleSheet(
            f"border:1.5px solid {COLOR_BORDER};border-radius:{RADIUS_INPUT}px;background-color:{COLOR_SURFACE};"
        )
        self.receipt_results_list.itemClicked.connect(self._open_receipt_result)
        self.receipt_results_list.hide()
        outer.addWidget(self.receipt_results_list)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("ابحث عن مورد...")
        self.search_input.setStyleSheet(
            f"border:1.5px solid {COLOR_BORDER};border-radius:{RADIUS_INPUT}px;"
            f"padding:{SPACE_8}px {SPACE_12}px;background-color:{COLOR_SURFACE};"
        )
        self.search_input.setMinimumHeight(38)
        self.search_input.textChanged.connect(lambda: self._apply_filter(reset_page=True))
        outer.addWidget(self.search_input)
        scroll = QScrollArea()
        enable_touch_scroll(scroll)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        grid_container = QWidget()
        self.grid_layout = QGridLayout(grid_container)
        self.grid_layout.setSpacing(SPACE_16)
        self.grid_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(grid_container)
        outer.addWidget(scroll, stretch=1)

        self.empty_label = QLabel("ماكو موردين مضافين لحد الآن.")
        self.empty_label.setStyleSheet(f"color:{COLOR_TEXT_SECONDARY};background:transparent;border:none;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_label)
        self.empty_label.hide()

        # شريط تنقّل الصفحات - نفس تصميم شاشة المخزون بالضبط (زر سابق/تالي
        # + تسمية "صفحة X من Y - إجمالي Z مورد").
        pagination_row = QHBoxLayout()
        self.prev_page_btn = QPushButton("◀ السابق")
        self.prev_page_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 14px;")
        self.prev_page_btn.clicked.connect(self._go_prev_page)
        self.page_info_label = QLabel("")
        self.page_info_label.setAlignment(Qt.AlignCenter)
        self.page_info_label.setStyleSheet("color:#374151;font-weight:600;")
        self.next_page_btn = QPushButton("التالي ▶")
        self.next_page_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 14px;")
        self.next_page_btn.clicked.connect(self._go_next_page)
        pagination_row.addWidget(self.prev_page_btn)
        pagination_row.addWidget(self.page_info_label, stretch=1)
        pagination_row.addWidget(self.next_page_btn)
        outer.addLayout(pagination_row)

        self._all_suppliers = []
        self._cards_by_supplier = {}
        self._current_page = 1
        self._total_pages = 1
        self.refresh()

    def refresh(self, jump_to_last=False):
        # ترتيب حسب المعرّف (تاريخ الإضافة) حتى المورد الجديد يطلع بآخر
        # القائمة (بالأسفل) - نفس الطلب الأصلي.
        self._all_suppliers = self.session.query(Supplier).order_by(Supplier.id.asc()).all()
        self._apply_filter(jump_to_last=jump_to_last)

    def _go_prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._apply_filter()

    def _go_next_page(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._apply_filter()

    def _apply_filter(self, reset_page=False, jump_to_last=False):
        query_text = self.search_input.text().strip()
        if query_text:
            suppliers = [s for s in self._all_suppliers if query_text in (s.name or "")]
        else:
            suppliers = self._all_suppliers

        total_count = len(suppliers)
        self._total_pages = max(1, -(-total_count // self.PAGE_SIZE))
        if reset_page:
            self._current_page = 1
        if jump_to_last:
            self._current_page = self._total_pages
        self._current_page = max(1, min(self._current_page, self._total_pages))

        start = (self._current_page - 1) * self.PAGE_SIZE
        page_suppliers = suppliers[start:start + self.PAGE_SIZE]

        self.page_info_label.setText(
            f"صفحة {self._current_page} من {self._total_pages} - إجمالي {total_count} مورد"
        )
        self.prev_page_btn.setEnabled(self._current_page > 1)
        self.next_page_btn.setEnabled(self._current_page < self._total_pages)

        self._populate_grid(page_suppliers)

    def _populate_grid(self, suppliers):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._cards_by_supplier = {}

        self.empty_label.setVisible(len(suppliers) == 0)

        # نحسب أرقام كل الموردين المعروضين بهذي الصفحة بس (30 كحد أقصى)
        # دفعة وحدة - استعلامات مجمّعة ثابتة العدد بغض النظر عن عدد
        # الموردين بالصفحة، وبدون أي حاجة لحساب أرقام موردين مو معروضين
        # حاليًا أصلًا (باقي الصفحات).
        totals_by_supplier = bulk_supplier_totals(self.session, [s.id for s in suppliers])

        col_count = 3
        for col in range(col_count):
            self.grid_layout.setColumnStretch(col, 1)
        for i, supplier in enumerate(suppliers):
            totals = totals_by_supplier.get(supplier.id, (0, 0, 0, 0))
            # on_change لأي بطاقة يحدّث أرقام هذا المورد بس (refresh_supplier)
            # بدل ما يهدم شبكة البطاقات كلها ويبنيها من جديد (self.refresh) -
            # هذا كان يسوي بطء واضح كل ما يكثر عدد الموردين (كل دفعة/مرتجع/
            # تعديل فاتورة كان يعيد بناء *كل* البطاقات، مو بطاقة المورد
            # المتأثر بس)، وبنفس الوقت كان يهدم بطاقة المورد اللي فاتحة عليها
            # نافذة كشف حساب مفتوحة حاليًا فتنسكر وياها تلقائيًا (شوف تعليق
            # SupplierCard._open_statement لتفاصيل هذا الجزء بالذات).
            card = SupplierCard(
                self.session, supplier, totals,
                on_change=lambda sid=supplier.id: self.refresh_supplier(sid),
            )
            self._cards_by_supplier[supplier.id] = card
            self.grid_layout.addWidget(card, i // col_count, i % col_count)

    def refresh_supplier(self, supplier_id):
        """يحدّث أرقام بطاقة مورد وحد بس مباشرة بمكانها - بدون لمس بقية
        بطاقات الشبكة إطلاقًا. يُستدعى بعد أي دفعة/مرتجع/تعديل فاتورة لهذا
        المورد (من كشف الحساب أو زر "تسديد دفعة" مباشرة). لو المورد مو
        بالصفحة المعروضة حاليًا (بطاقته مو مبنية أصلًا)، ما نسوي شي - أرقامه
        تنعرض صحيحة أول ما يوصلها الدور بالتصفح."""
        card = self._cards_by_supplier.get(supplier_id)
        if not card:
            return
        totals = bulk_supplier_totals(self.session, [supplier_id]).get(supplier_id, (0, 0, 0, 0))
        card.set_totals(totals)

    def _search_receipt(self):
        """يبحث عن رقم الوصل المكتوب بخانة "بحث عن وصل" عبر كل الموردين
        (مو بس المورد المفتوحة بطاقته حاليًا)، ويعرض النتائج بقائمة تحت
        الخانة - كل نتيجة فيها نوع الوصل والمورد."""
        query_text = self.receipt_search_input.text().strip()
        self.receipt_results_list.clear()
        if not query_text:
            self.receipt_results_list.hide()
            return
        self._receipt_results = search_by_receipt_number(self.session, query_text)
        if not self._receipt_results:
            self.receipt_results_list.addItem("ماكو وصل مطابق لهذا الرقم.")
            self.receipt_results_list.show()
            return
        for r in self._receipt_results:
            self.receipt_results_list.addItem(f"{r['label']}   —   المورد: {r['supplier'].name}")
        self.receipt_results_list.show()

    def _open_receipt_result(self, item):
        """الضغط على نتيجة بحث عن وصل - يفتح كشف حساب المورد صاحب هذا
        الوصل مباشرة، مع تظليل الصف المطابق تلقائيًا فور الفتح."""
        row = self.receipt_results_list.row(item)
        if row < 0 or row >= len(self._receipt_results):
            return
        result = self._receipt_results[row]
        supplier = result["supplier"]
        dialog = SupplierStatementDialog(
            self.session, supplier,
            on_change=lambda sid=supplier.id: self.refresh_supplier(sid),
            parent=self,
            highlight=(result["kind"], result["ref_id"], result["receipt_no"]),
        )
        dialog.exec()
        self.receipt_results_list.hide()
        self.receipt_search_input.clear()

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
            # نروح لآخر صفحة بعد الإضافة - المورد الجديد يطلع بآخر القائمة
            # (راجع تعليق refresh() فوق)، فلازم نفتح آخر صفحة حتى يبين مباشرة
            # بدل ما يضل مخفي بصفحة ما يشوفها المستخدم تلقائيًا.
            self.refresh(jump_to_last=True)
