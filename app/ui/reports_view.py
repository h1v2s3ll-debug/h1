"""شاشة التقارير: إحصائيات المبيعات والأرباح حسب فترة زمنية، أفضل الأدوية مبيعًا، وآخر الفواتير."""
from app.ui.widgets import add_shadow
from datetime import date, datetime, timedelta
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit, QPushButton,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog, QMessageBox,
    QLineEdit, QDialog, QScrollArea, QAbstractItemView, QTabWidget
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from app.db.database import get_session
from app.db.models import Invoice, InvoiceItem, Batch, Product, ProductUnit, StockMovement, Expense, Payment, Customer
from app.db.approved_helper import is_product_approved, is_approved_filter_enabled
from app.db.settings_helper import get_expiry_alert_days
from app.ui.widgets import disable_scroll, NumberLineEdit, enable_touch_scroll
from app.ui.icons import icon, pixmap
from app.ui.theme import PANEL, PANEL_2, LINE, INK, INK_2, TEAL_800, TEAL_600, TEAL_500, TEAL_400, RED_500, AMBER_500


def fmt_money(n):
    return f"{n:,.0f} د.ع"


class ReportsView(QWidget):
    # on_navigate: دالة اختيارية توخذ (اسم_الصفحة, حالة_فلترة_اختيارية) وتنقل
    # المستخدم إليها - نفس آلية DashboardView.on_navigate بالضبط، مستخدمة هنا
    # بأزرار "عرض الكل بالمخزون" تحت كل قسم تنبيهات مختصر.
    def __init__(self, parent=None, on_navigate=None):
        super().__init__(parent)
        self.session = get_session()
        self.on_navigate = on_navigate

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        enable_touch_scroll(scroll)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)

        # تبويب ثاني منفصل: "التنبيهات والفواتير" - فصلناهم عن باقي
        # صفحة التقارير (بطاقات الإحصائيات/أفضل الأدوية/تقارير المخزون...)
        # نفس فكرة تبويب "الموردون والحسابات" بشاشة المشتريات بالضبط.
        scroll2 = QScrollArea()
        enable_touch_scroll(scroll2)
        scroll2.setWidgetResizable(True)
        scroll2.setFrameShape(QFrame.NoFrame)
        content2 = QWidget()
        layout2 = QVBoxLayout(content2)
        scroll2.setWidget(content2)
        alerts_invoices_title = QLabel("التنبيهات والفواتير")
        alerts_invoices_title.setStyleSheet("font-size:18px;font-weight:bold;")
        layout2.addWidget(alerts_invoices_title)

        title = QLabel("التقارير")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        layout.addWidget(title)

        # --- تنبيهات استباقية: نواقص قبل الحد الأدنى + قرب انتهاء الصلاحية ---
        self.alerts_frame = QFrame()
        self.alerts_frame.setStyleSheet("background:#FFFBEB;border:1px solid #F59E0B;border-radius:10px;padding:10px;")
        alerts_outer_layout = QVBoxLayout(self.alerts_frame)

        alerts_header = QHBoxLayout()
        alerts_title = QLabel("التنبيهات")
        alerts_title.setStyleSheet(f"font-weight:800;font-size:14px;color:{TEAL_800};")
        alerts_header.addWidget(alerts_title)
        alerts_header.addStretch()
        self.alerts_toggle_btn = QPushButton("طي ˄")
        self.alerts_toggle_btn.setStyleSheet(f"background:{PANEL_2};border:1px solid {LINE};border-radius:8px;padding:5px 12px;color:{TEAL_800};")
        self.alerts_toggle_btn.clicked.connect(self._toggle_alerts_section)
        alerts_header.addWidget(self.alerts_toggle_btn)
        alerts_outer_layout.addLayout(alerts_header)

        self.alerts_body = QWidget()
        self.alerts_layout = QVBoxLayout(self.alerts_body)
        self.alerts_layout.setContentsMargins(0, 8, 0, 0)
        alerts_outer_layout.addWidget(self.alerts_body)

        layout2.addWidget(self.alerts_frame)

        # --- فترة زمنية ---
        range_frame = QFrame()
        range_frame.setStyleSheet("background:white;border:1px solid #E5E7EB;border-radius:10px;padding:10px;")
        range_layout = QHBoxLayout(range_frame)
        self.from_input = QDateEdit(QDate.currentDate().addDays(-60))
        self.from_input.setCalendarPopup(True)
        disable_scroll(self.from_input)
        self.from_input.dateChanged.connect(self._clear_quick_range_selection)
        self.to_input = QDateEdit(QDate.currentDate())
        self.to_input.setCalendarPopup(True)
        disable_scroll(self.to_input)
        self.to_input.dateChanged.connect(self._clear_quick_range_selection)
        range_layout.addWidget(QLabel("من:"))
        range_layout.addWidget(self.from_input)
        range_layout.addWidget(QLabel("إلى:"))
        range_layout.addWidget(self.to_input)

        # أزرار الفترة السريعة (اليوم/أسبوع/شهر/سنة) - قابلة للتحديد (checkable)
        # حتى يتلون الزر المختار حاليًا ويبقى ملوّنًا لغاية ما تضغط زر ثاني،
        # فيعرف المستخدم بنظرة وحدة أي فترة مفعّلة الآن بدل ما يخمّن. الأزرار
        # تتصرف كمجموعة راديو - ضغط وحدة يفك تحديد الباقي تلقائيًا.
        self._range_buttons = []
        for label, days in [("اليوم", 0), ("أسبوع", 7), ("شهر", 30), ("سنة", 365)]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:#F1F5F9;color:#111827;border:1px solid #E5E7EB;"
                "border-radius:8px;padding:6px 12px;}"
                "QPushButton:checked{background:#16A34A;color:white;border:1px solid #16A34A;"
                "font-weight:700;}"
            )
            btn.clicked.connect(lambda _, d=days, b=btn: self._quick_range(d, b))
            range_layout.addWidget(btn)
            self._range_buttons.append(btn)

        apply_btn = QPushButton("تطبيق")
        apply_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:6px 16px;")
        apply_btn.clicked.connect(self.refresh)
        range_layout.addWidget(apply_btn)

        withdraw_btn = QPushButton("سحب من الصندوق")
        withdraw_btn.setIcon(icon("cash", color="white", size=15))
        withdraw_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 14px;")
        withdraw_btn.clicked.connect(self.withdraw_cash)
        range_layout.addWidget(withdraw_btn)

        list_withdrawals_btn = QPushButton("كل السحوبات")
        list_withdrawals_btn.setIcon(icon("clipboard", color=TEAL_600, size=14))
        list_withdrawals_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 14px;")
        list_withdrawals_btn.clicked.connect(self.show_withdrawals_list)
        range_layout.addWidget(list_withdrawals_btn)

        range_layout.addStretch()
        layout.addWidget(range_frame)

        # --- بطاقات الإحصائيات ---
        self.stats_row = QHBoxLayout()
        layout.addLayout(self.stats_row)

        # --- أفضل الأدوية مبيعًا ---
        top_title = QLabel("أفضل الأدوية مبيعًا بالفترة")
        top_title.setStyleSheet("font-weight:bold;font-size:14px;margin-top:10px;")
        layout.addWidget(top_title)
        self.top_table = QTableWidget()
        enable_touch_scroll(self.top_table)
        self.top_table.setAlternatingRowColors(True)
        self.top_table.setColumnCount(3)
        self.top_table.setHorizontalHeaderLabels(["الدواء", "الكمية المباعة", "الإيراد"])
        self.top_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.top_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.top_table.setMaximumHeight(200)
        layout.addWidget(self.top_table)

        # --- آخر الفواتير ---
        invoices_card = QFrame()
        invoices_card.setStyleSheet(f"background:{PANEL};border:1px solid {LINE};border-radius:14px;padding:14px;margin-top:14px;")
        add_shadow(invoices_card, blur=16, color="#16A34A", alpha=18, y_offset=3)
        invoices_card_layout = QVBoxLayout(invoices_card)

        recent_header = QHBoxLayout()
        recent_title_box = QVBoxLayout()
        recent_title = QLabel("آخر الفواتير بالفترة")
        recent_title.setStyleSheet(f"font-weight:800;font-size:16px;color:{TEAL_800};")
        recent_subtitle = QLabel("كل فواتير البيع والإرجاع بالفترة المحددة بالأعلى")
        recent_subtitle.setStyleSheet(f"color:{INK_2};font-size:12px;")
        recent_title_box.addWidget(recent_title)
        recent_title_box.addWidget(recent_subtitle)
        recent_header.addLayout(recent_title_box)
        recent_header.addStretch()
        self.invoice_search_input = QLineEdit()
        self.invoice_search_input.setPlaceholderText("ابحث برقم الفاتورة...")
        self.invoice_search_input.setMaximumWidth(220)
        self.invoice_search_input.textChanged.connect(self._filter_invoice_table)
        recent_header.addWidget(self.invoice_search_input)
        self.show_all_btn = QPushButton("عرض كل الفواتير")
        self.show_all_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 12px;")
        self.show_all_btn.clicked.connect(self._toggle_show_all)
        recent_header.addWidget(self.show_all_btn)
        self.invoices_toggle_btn = QPushButton("طي ˄")
        self.invoices_toggle_btn.setStyleSheet(f"background:{PANEL_2};border:1px solid {LINE};border-radius:8px;padding:5px 12px;color:{TEAL_800};")
        self.invoices_toggle_btn.clicked.connect(self._toggle_invoices_section)
        recent_header.addWidget(self.invoices_toggle_btn)
        invoices_card_layout.addLayout(recent_header)

        self.invoices_body = QWidget()
        invoices_body_layout = QVBoxLayout(self.invoices_body)
        invoices_body_layout.setContentsMargins(0, 8, 0, 0)
        invoices_card_layout.addWidget(self.invoices_body)

        self.recent_table = QTableWidget()
        enable_touch_scroll(self.recent_table)
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.setColumnCount(4)
        self.recent_table.setHorizontalHeaderLabels(["رقم الفاتورة", "التاريخ", "طريقة الدفع", "المبلغ"])
        self.recent_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.recent_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.recent_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.recent_table.cellClicked.connect(self._open_invoice_detail)
        # ارتفاع محدد + سكرول داخلي شغال دائمًا حتى ما تنقطع ولا فاتورة عن العرض
        self.recent_table.setMinimumHeight(320)
        self.recent_table.setMaximumHeight(320)
        self.recent_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        invoices_body_layout.addWidget(self.recent_table)

        layout2.addWidget(invoices_card)

        # --- كشف الهدر ---
        waste_card = QFrame()
        waste_card.setStyleSheet(f"background:{PANEL};border:1px solid {LINE};border-radius:14px;padding:14px;margin-top:14px;")
        add_shadow(waste_card, blur=16, color="#16A34A", alpha=18, y_offset=3)
        waste_card_layout = QVBoxLayout(waste_card)

        waste_header = QHBoxLayout()
        waste_title_box = QVBoxLayout()
        waste_title = QLabel("كشف الهدر")
        waste_title.setStyleSheet(f"font-weight:800;font-size:16px;color:{TEAL_800};")
        waste_subtitle = QLabel("التالف/منتهي الصلاحية المسحوب من المخزون خارج البيع، بقيمته التقديرية")
        waste_subtitle.setStyleSheet(f"color:{INK_2};font-size:12px;")
        waste_title_box.addWidget(waste_title)
        waste_title_box.addWidget(waste_subtitle)
        waste_header.addLayout(waste_title_box)
        waste_header.addStretch()
        self.waste_toggle_btn = QPushButton("طي ˄")
        self.waste_toggle_btn.setStyleSheet(f"background:{PANEL_2};border:1px solid {LINE};border-radius:8px;padding:5px 12px;color:{TEAL_800};")
        self.waste_toggle_btn.clicked.connect(self._toggle_waste_section)
        waste_header.addWidget(self.waste_toggle_btn)
        waste_card_layout.addLayout(waste_header)

        self.waste_body = QWidget()
        waste_body_layout = QVBoxLayout(self.waste_body)
        waste_body_layout.setContentsMargins(0, 8, 0, 0)
        waste_card_layout.addWidget(self.waste_body)

        self.waste_stats_row = QHBoxLayout()
        waste_body_layout.addLayout(self.waste_stats_row)

        self.waste_scroll = QScrollArea()
        enable_touch_scroll(self.waste_scroll)
        self.waste_scroll.setWidgetResizable(True)
        self.waste_scroll.setFrameShape(QFrame.NoFrame)
        # ارتفاع يكفي لعرض 3 صفوف هدر مباشرة بدون سكرول (كل صف تقريبًا
        # 78-85px بالتصميم الحالي) - أي صفوف زيادة عن كذا تنعرض بالتمرير
        # عبر شريط تمرير واضح بدل ما تنقطع بعد صف وحد بس.
        self.waste_scroll.setMinimumHeight(260)
        self.waste_scroll.setMaximumHeight(420)
        self.waste_scroll.setStyleSheet(f"""
            QScrollBar:vertical {{
                width:12px; background:{PANEL_2}; border-radius:6px;
            }}
            QScrollBar::handle:vertical {{
                background:{RED_500}; border-radius:6px; min-height:24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height:0px;
            }}
        """)
        self.waste_list_container = QWidget()
        self.waste_list_layout = QVBoxLayout(self.waste_list_container)
        self.waste_list_layout.setContentsMargins(0, 0, 0, 0)
        self.waste_list_layout.setSpacing(4)
        self.waste_scroll.setWidget(self.waste_list_container)
        waste_body_layout.addWidget(self.waste_scroll)
        layout.addWidget(waste_card)

        # ملاحظة: بطاقة "رأس المال والربح المتوقع" انتقلت للصفحة الرئيسية
        # بناءً على الطلب - عرضها هنا انحذف بدل التكرار بصفحتين.

        scroll3 = QScrollArea()
        enable_touch_scroll(scroll3)
        scroll3.setWidgetResizable(True)
        scroll3.setFrameShape(QFrame.NoFrame)
        content3 = QWidget()
        layout3 = QVBoxLayout(content3)
        scroll3.setWidget(content3)

        # --- تقارير المخزون: نفس تصميم قسم التنبيهات بالصفحة الرئيسية بالضبط ---
        inv_card = QFrame()
        inv_card.setStyleSheet(f"background:{PANEL};border:1px solid {LINE};border-radius:14px;padding:14px;margin-top:14px;")
        add_shadow(inv_card, blur=16, color="#16A34A", alpha=18, y_offset=3)
        inv_card_layout = QVBoxLayout(inv_card)

        inv_header = QHBoxLayout()
        inv_title_box = QVBoxLayout()
        inv_title = QLabel("تقارير المخزون")
        inv_title.setStyleSheet(f"font-weight:800;font-size:16px;color:{TEAL_800};")
        inv_subtitle = QLabel("تنبيهات وصلاحيات وحركة المخزون")
        inv_subtitle.setStyleSheet(f"color:{INK_2};font-size:12px;")
        inv_title_box.addWidget(inv_title)
        inv_title_box.addWidget(inv_subtitle)
        inv_header.addLayout(inv_title_box)
        inv_header.addStretch()
        self.inv_toggle_btn = QPushButton("طي ˄")
        self.inv_toggle_btn.setStyleSheet(f"background:{PANEL_2};border:1px solid {LINE};border-radius:8px;padding:5px 12px;color:{TEAL_800};")
        self.inv_toggle_btn.clicked.connect(self._toggle_inventory_section)
        inv_header.addWidget(self.inv_toggle_btn)
        inv_card_layout.addLayout(inv_header)

        self.inv_body = QWidget()
        inv_body_layout = QVBoxLayout(self.inv_body)
        inv_body_layout.setContentsMargins(0, 8, 0, 0)
        inv_card_layout.addWidget(self.inv_body)

        self.inv_stats_row = QHBoxLayout()
        inv_body_layout.addLayout(self.inv_stats_row)

        self.inv_list_container = QWidget()
        self.inv_list_layout = QVBoxLayout(self.inv_list_container)
        self.inv_list_layout.setContentsMargins(0, 8, 0, 0)
        inv_body_layout.addWidget(self.inv_list_container)

        layout3.addWidget(inv_card)
        layout3.addStretch()

        # --- الأدوية الراكدة (ما انباعت من 6 أشهر فما فوق) ---
        stagnant_card = QFrame()
        stagnant_card.setStyleSheet(f"background:{PANEL};border:1px solid {LINE};border-radius:14px;padding:14px;margin-top:14px;")
        add_shadow(stagnant_card, blur=16, color="#F59E0B", alpha=18, y_offset=3)
        stagnant_card_layout = QVBoxLayout(stagnant_card)

        stagnant_header = QHBoxLayout()
        stagnant_title_box = QVBoxLayout()
        stagnant_title = QLabel("الأدوية الراكدة")
        stagnant_title.setStyleSheet(f"font-weight:800;font-size:16px;color:{TEAL_800};")
        stagnant_subtitle = QLabel("أدوية ما انباعت من 6 أشهر فما فوق - رأس مال متجمّد بالمخزون")
        stagnant_subtitle.setStyleSheet(f"color:{INK_2};font-size:12px;")
        stagnant_title_box.addWidget(stagnant_title)
        stagnant_title_box.addWidget(stagnant_subtitle)
        stagnant_header.addLayout(stagnant_title_box)
        stagnant_header.addStretch()
        self.stagnant_toggle_btn = QPushButton("طي ˄")
        self.stagnant_toggle_btn.setStyleSheet(f"background:{PANEL_2};border:1px solid {LINE};border-radius:8px;padding:5px 12px;color:{TEAL_800};")
        self.stagnant_toggle_btn.clicked.connect(self._toggle_stagnant_section)
        stagnant_header.addWidget(self.stagnant_toggle_btn)
        stagnant_card_layout.addLayout(stagnant_header)

        self.stagnant_body = QWidget()
        stagnant_body_layout = QVBoxLayout(self.stagnant_body)
        stagnant_body_layout.setContentsMargins(0, 8, 0, 0)
        stagnant_card_layout.addWidget(self.stagnant_body)

        self.stagnant_list_layout = QVBoxLayout()
        stagnant_body_layout.addLayout(self.stagnant_list_layout)

        layout.addWidget(stagnant_card)

        layout2.addStretch()

        self.tabs = QTabWidget()
        self.tabs.addTab(scroll, "التقارير")
        self.tabs.addTab(scroll2, "التنبيهات والفواتير")
        self.tabs.addTab(scroll3, "تقارير المخزون")
        outer.addWidget(self.tabs)

        self._show_all_invoices = False
        self._all_invoices = []
        self.refresh()

    def _toggle_stagnant_section(self):
        visible = not self.stagnant_body.isVisible()
        self.stagnant_body.setVisible(visible)
        self.stagnant_toggle_btn.setText("طي ˄" if visible else "فتح ˅")

    def _refresh_stagnant_report(self):
        while self.stagnant_list_layout.count():
            child = self.stagnant_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        today = date.today()
        cutoff = datetime.now() - timedelta(days=180)

        # آخر تاريخ بيع لكل دواء - عبر جوين من InvoiceItem->Batch للحصول
        # على product_id، ومطابقة أقصى تاريخ فاتورة لكل صنف بنداء واحد
        # مجمّع (GROUP BY) بدل استعلام منفصل لكل دواء (يفادي مشكلة N+1).
        last_sale_rows = (
            self.session.query(Batch.product_id, func.max(Invoice.invoice_date))
            .join(InvoiceItem, InvoiceItem.batch_id == Batch.id)
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .filter(Invoice.payment_status != "مرتجع")
            .group_by(Batch.product_id)
            .all()
        )
        last_sale_by_product = {pid: last_date for pid, last_date in last_sale_rows}

        products = (
            self.session.query(Product)
            .options(joinedload(Product.batches))
            .filter(Product.is_active == True)
            .all()
        )
        # لو إعداد "الاعتماد على الأدوية المعتمدة" مفعّل، نقصر تقرير الراكد
        # على الأدوية المعتمدة بس - راجع app/db/approved_helper.py.
        if is_approved_filter_enabled(self.session):
            products = [p for p in products if is_product_approved(p)]

        stagnant = []
        for p in products:
            stock = sum(b.quantity_available for b in p.batches)
            if stock <= 0:
                continue  # ماكو مخزون أصلًا - ماكو رأس مال متجمّد نتحدث عنه
            last_sale = last_sale_by_product.get(p.id)
            if last_sale is None or last_sale < cutoff:
                # نستبعد الدفعات المنتهية الصلاحية من حساب المخزون/القيمة
                # المتجمّدة هنا - دواء منتهي مكانه الطبيعي قسم "منتهية
                # الصلاحية"، مو "راكد" (راكد = رأس مال قابل للتحرك لو تحرك
                # الطلب، بينما المنتهي خسارة مؤكدة بغض النظر عن الطلب).
                usable_batches = [b for b in p.batches if not (b.expiry_date and b.expiry_date <= today)]
                usable_stock = sum(b.quantity_available for b in usable_batches)
                if usable_stock <= 0:
                    continue  # كل المخزون المتبقي منتهي فعلاً - يظهر بقسم "منتهية الصلاحية" بدل هذا القسم
                frozen_value = sum((b.purchase_price or 0) * b.quantity_available for b in usable_batches)
                stagnant.append((p, last_sale, usable_stock, frozen_value))

        # الأدوية الأقل مبيعًا (أو اللي ما انباعت إطلاقًا) بآخر 6 أشهر تطلع
        # فوق - نفس منطق قسم التنبيهات بالأعلى، بس بالاتجاه المعاكس (هنا نبي
        # الأقل طلبًا لأنها هي "الراكدة" فعلاً، مو الأكثر طلبًا).
        sales_map = self._sales_qty_map(months_back=6)
        stagnant.sort(key=lambda x: (sales_map.get(x[0].id, 0), x[1] or datetime.min))

        if not stagnant:
            ok_wrap = QFrame()
            ok_wrap.setStyleSheet("background:transparent;border:none;")
            ok_row = QHBoxLayout(ok_wrap)
            ok_row.setContentsMargins(0, 16, 0, 16)
            ok_row.setSpacing(8)
            ok_row.addStretch()
            ok_icon_lbl = QLabel()
            ok_icon_lbl.setStyleSheet("background:transparent;border:none;")
            ok_icon_lbl.setPixmap(icon("check", color="#16A34A", size=16).pixmap(16, 16))
            ok_row.addWidget(ok_icon_lbl)
            ok_text = QLabel("ماكو أدوية راكدة حاليًا - كل المخزون يتحرك بشكل طبيعي.")
            ok_text.setStyleSheet(f"color:{INK_2};font-size:13px;")
            ok_row.addWidget(ok_text)
            ok_row.addStretch()
            self.stagnant_list_layout.addWidget(ok_wrap)
            return

        total_frozen = sum(x[3] for x in stagnant)
        summary_lbl = QLabel(f"{len(stagnant)} دواء راكد - رأس مال متجمّد: {fmt_money(total_frozen)}")
        summary_lbl.setStyleSheet(f"color:{AMBER_500};font-weight:700;font-size:13px;margin-bottom:6px;")
        self.stagnant_list_layout.addWidget(summary_lbl)

        LIMIT = 10
        for p, last_sale, stock, frozen_value in stagnant[:LIMIT]:
            row = QFrame()
            row.setStyleSheet(f"background:{PANEL_2};border:1px solid {LINE};border-radius:10px;padding:8px 12px;margin-bottom:4px;")
            row_h = QHBoxLayout(row)
            name_lbl = QLabel(p.name)
            name_lbl.setStyleSheet(f"color:{INK};font-weight:700;font-size:13px;")
            row_h.addWidget(name_lbl)
            row_h.addStretch()
            last_sale_text = "لم يُبع أبدًا" if last_sale is None else f"آخر بيع: {last_sale.strftime('%Y-%m-%d')}"
            detail_lbl = QLabel(f"{last_sale_text} - مخزون: {stock} شريط - قيمة متجمّدة: {fmt_money(frozen_value)}")
            detail_lbl.setStyleSheet(f"color:{INK_2};font-size:11px;")
            row_h.addWidget(detail_lbl)
            self.stagnant_list_layout.addWidget(row)

        if len(stagnant) > LIMIT:
            self.stagnant_list_layout.addWidget(self._view_all_button(len(stagnant), "راكد"))

    def _toggle_invoices_section(self):
        visible = not self.invoices_body.isVisible()
        self.invoices_body.setVisible(visible)
        self.invoices_toggle_btn.setText("طي ˄" if visible else "فتح ˅")

    def _toggle_alerts_section(self):
        visible = not self.alerts_body.isVisible()
        self.alerts_body.setVisible(visible)
        self.alerts_toggle_btn.setText("طي ˄" if visible else "فتح ˅")

    def _toggle_waste_section(self):
        visible = not self.waste_body.isVisible()
        self.waste_body.setVisible(visible)
        self.waste_toggle_btn.setText("طي ˄" if visible else "فتح ˅")

    def _toggle_inventory_section(self):
        visible = not self.inv_body.isVisible()
        self.inv_body.setVisible(visible)
        self.inv_toggle_btn.setText("طي ˄" if visible else "فتح ˅")

    def _refresh_inventory_report(self):
        for row_layout in (self.inv_stats_row,):
            while row_layout.count():
                child = row_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
        while self.inv_list_layout.count():
            child = self.inv_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        today = date.today()
        # joinedload(Product.batches) يجيب المنتجات ودفعاتها باستعلام واحد بدل
        # ما تفتح Batch استعلام منفصل لكل منتج (N+1) - هذا كان أحد أسباب بطء
        # فتح صفحة التقارير كلما زاد عدد الأدوية بالمخزون.
        products = (
            self.session.query(Product)
            .options(joinedload(Product.batches))
            .filter(Product.is_active == True)
            .all()
        )
        # لو إعداد "الاعتماد على الأدوية المعتمدة" مفعّل، نقصر تقرير المخزون
        # (نقص/منخفض/منتهي/قرب الانتهاء) على الأدوية المعتمدة بس.
        if is_approved_filter_enabled(self.session):
            products = [p for p in products if is_product_approved(p)]

        out_of_stock, low_stock, near_expiry, expired = [], [], [], []
        expiry_alert_days = get_expiry_alert_days(self.session)

        for p in products:
            stock = sum(b.quantity_available for b in p.batches)
            threshold = p.min_stock_threshold or 10
            if stock <= 0:
                out_of_stock.append(p)
            elif stock <= threshold:
                low_stock.append(p)

            nearest = min(
                (b.expiry_date for b in p.batches if b.expiry_date and b.quantity_available > 0),
                default=None,
            )
            if nearest:
                if nearest < today:
                    expired.append((p, nearest))
                elif nearest <= today + timedelta(days=expiry_alert_days):
                    near_expiry.append((p, nearest))

        # --- نفس تصميم قسم التنبيهات بالصفحة الرئيسية بالضبط ---
        self.inv_stats_row.addWidget(self._stat_card(len(out_of_stock), "أدوية نافذة", RED_500))
        self.inv_stats_row.addWidget(self._stat_card(len(low_stock), "مخزون منخفض", AMBER_500))
        self.inv_stats_row.addWidget(self._stat_card(len(expired), "منتهية الصلاحية", RED_500))
        self.inv_stats_row.addWidget(self._stat_card(len(near_expiry), "قرب انتهاء الصلاحية", AMBER_500))

        if not out_of_stock and not low_stock and not near_expiry and not expired:
            ok_wrap = QFrame()
            ok_wrap.setStyleSheet("background:transparent;border:none;")
            ok_row = QHBoxLayout(ok_wrap)
            ok_row.setContentsMargins(0, 20, 0, 20)
            ok_row.setSpacing(8)
            ok_row.addStretch()
            ok_icon_lbl = QLabel()
            ok_icon_lbl.setStyleSheet("background:transparent;border:none;")
            ok_icon_lbl.setPixmap(pixmap("check", color=TEAL_500, size=16))
            ok_row.addWidget(ok_icon_lbl)
            ok_lbl = QLabel("ماكو تنبيهات حاليًا - كل شي زين بالمخزون.")
            ok_lbl.setStyleSheet("color:#16A34A;font-weight:bold;background:transparent;border:none;")
            ok_row.addWidget(ok_lbl)
            ok_row.addStretch()
            self.inv_list_layout.addWidget(ok_wrap)
            return

        # نرتب كل قائمة حسب الأدوية الأكثر طلبًا (مبيعات آخر 6 أشهر) أولاً -
        # عشان أول 10 عناصر تُعرض تكون فعلاً الأهم للصيدلية (أدوية عليها بيع
        # وتعامل فعلي)، مو مجرد أول 10 بترتيب عشوائي/الاسم بين آلاف الأدوية.
        # الأدوية اللي ما إلها أي مبيعات بالفترة تنزل لتحت القائمة (مو تختفي -
        # تظهر لو ضغط "عرض الكل").
        sales_map = self._sales_qty_map(months_back=6)
        LIMIT = 10

        if out_of_stock:
            out_of_stock.sort(key=lambda p: -sales_map.get(p.id, 0))
            total = len(out_of_stock)
            self.inv_list_layout.addWidget(self._section_title("نافذة من المخزون", icon_name="dot", icon_color=RED_500))
            for p in out_of_stock[:LIMIT]:
                self.inv_list_layout.addWidget(self._alert_row(p.name, "الكمية: 0", RED_500))
            if total > LIMIT:
                self.inv_list_layout.addWidget(self._view_all_button(total, "نقص"))

        if expired:
            expired.sort(key=lambda x: (-sales_map.get(x[0].id, 0), x[1]))
            total = len(expired)
            self.inv_list_layout.addWidget(self._section_title("منتهية الصلاحية بالفعل", icon_name="dot", icon_color=RED_500))
            for p, exp_date in expired[:LIMIT]:
                days_ago = (today - exp_date).days
                self.inv_list_layout.addWidget(self._alert_row(p.name, f"انتهت من {days_ago} يوم ({exp_date.isoformat()})", RED_500))
            if total > LIMIT:
                self.inv_list_layout.addWidget(self._view_all_button(total, "منتهي"))

        if low_stock:
            low_stock.sort(key=lambda p: (-sales_map.get(p.id, 0), sum(b.quantity_available for b in p.batches)))
            total = len(low_stock)
            self.inv_list_layout.addWidget(self._section_title("مخزون منخفض", icon_name="dot", icon_color=AMBER_500))
            for p in low_stock[:LIMIT]:
                stock = sum(b.quantity_available for b in p.batches)
                self.inv_list_layout.addWidget(self._alert_row(p.name, f"الكمية المتبقية: {stock}", AMBER_500))
            if total > LIMIT:
                self.inv_list_layout.addWidget(self._view_all_button(total, "منخفض"))

        if near_expiry:
            near_expiry.sort(key=lambda x: (-sales_map.get(x[0].id, 0), x[1]))
            total = len(near_expiry)
            self.inv_list_layout.addWidget(self._section_title(f"قرب انتهاء الصلاحية (خلال {expiry_alert_days} يوم)", icon_name="dot", icon_color=AMBER_500))
            for p, exp_date in near_expiry[:LIMIT]:
                days_left = (exp_date - today).days
                self.inv_list_layout.addWidget(self._alert_row(p.name, f"تنتهي بعد {days_left} يوم ({exp_date.isoformat()})", AMBER_500))
            if total > LIMIT:
                self.inv_list_layout.addWidget(self._view_all_button(total, "قريب الانتهاء"))

    def _section_title(self, text, icon_name=None, icon_color=None):
        if icon_name:
            wrap = QFrame()
            wrap.setStyleSheet("background:transparent;border:none;")
            row = QHBoxLayout(wrap)
            row.setContentsMargins(0, 10, 0, 0)
            row.setSpacing(8)
            icon_lbl = QLabel()
            icon_lbl.setStyleSheet("background:transparent;border:none;")
            icon_lbl.setPixmap(pixmap(icon_name, color=icon_color or INK, size=15))
            row.addWidget(icon_lbl)
            text_lbl = QLabel(text)
            text_lbl.setStyleSheet(f"font-weight:bold;font-size:14px;color:{INK};background:transparent;border:none;")
            row.addWidget(text_lbl)
            row.addStretch()
            return wrap
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-weight:bold;font-size:14px;margin-top:10px;color:{INK};")
        return lbl

    def _navigate(self, page_name, filter_status=None):
        if self.on_navigate:
            self.on_navigate(page_name, filter_status)

    def _sales_qty_map(self, months_back=6):
        """يرجّع {product_id: مجموع الكمية المباعة} خلال آخر عدد أشهر معطى -
        نستخدمها لترتيب أي قائمة تنبيهات طويلة بحيث الأدوية الأكثر طلبًا
        (اللي فعلاً تُباع) تطلع فوق، بدل قائمة عشوائية قد تكون أغلبها أدوية
        ما بيعت أبدًا (زي أدوية مضافة حديثًا بكمية كبيرة دفعة وحدة)."""
        cutoff = datetime.now() - timedelta(days=months_back * 30)
        rows = (
            self.session.query(Batch.product_id, func.sum(InvoiceItem.quantity))
            .join(InvoiceItem, InvoiceItem.batch_id == Batch.id)
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .filter(Invoice.invoice_date >= cutoff)
            .filter(Invoice.payment_status != "مرتجع")
            .group_by(Batch.product_id)
            .all()
        )
        return {pid: qty or 0 for pid, qty in rows}

    def _view_all_button(self, count, filter_status):
        wrap = QFrame()
        wrap.setStyleSheet("background:transparent;border:none;")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 6, 0, 4)
        row.addStretch()
        btn = QPushButton(f"عرض الكل ({count}) بالمخزون")
        btn.setStyleSheet(f"background:{PANEL_2};border:1px solid {LINE};border-radius:8px;padding:6px 14px;color:{TEAL_800};font-weight:700;")
        btn.clicked.connect(lambda: self._navigate("المخزون", filter_status))
        row.addWidget(btn)
        return wrap

    def _waste_row(self, name, barcode, date_str, qty, reason, cost):
        frame = QFrame()
        # لون أحمر واضح بدل الوردي الفاتح السابق - خلفية حمراء فاتحة لكن
        # بتشبّع أعلى (Tailwind red-100 تقريبًا) + حدّ أحمر قوي بالجهة
        # اليمنى (شريط تمييز) يخلي الصف يبين "هدر/خسارة" بشكل أوضح من أول
        # نظرة، بدل ما يبين كأنه مجرد لون خفيف مزخرف.
        frame.setStyleSheet(f"""
            QFrame {{
                background:#FEE2E2;
                border:1px solid #FCA5A5;
                border-right:4px solid {RED_500};
                border-radius:8px;
                padding:10px 14px;
                margin:3px 2px;
            }}
        """)
        v = QVBoxLayout(frame)
        v.setSpacing(4)

        top_row = QHBoxLayout()
        name_lbl = QLabel(name if not barcode else f"{name}  •  {barcode}")
        name_lbl.setStyleSheet(f"color:{INK};font-weight:800;font-size:13px;")
        top_row.addWidget(name_lbl)
        top_row.addStretch()
        cost_lbl = QLabel(fmt_money(cost))
        cost_lbl.setStyleSheet(f"color:{RED_500};font-weight:800;font-size:15px;")
        top_row.addWidget(cost_lbl)
        v.addLayout(top_row)

        detail_row = QHBoxLayout()
        detail_lbl = QLabel(f"الكمية: {qty} شريط    •    السبب: {reason}")
        detail_lbl.setStyleSheet(f"color:#991B1B;font-size:12px;")
        detail_row.addWidget(detail_lbl)
        detail_row.addStretch()
        date_lbl = QLabel(date_str)
        date_lbl.setStyleSheet(f"color:#991B1B;font-size:12px;font-weight:600;")
        detail_row.addWidget(date_lbl)
        v.addLayout(detail_row)

        return frame

    def _alert_row(self, name, detail, color=INK_2):
        bg = "#FEF2F2" if color == RED_500 else ("#FFFBEB" if color == AMBER_500 else "#F1F5F9")
        border = "#FECACA" if color == RED_500 else ("#FDE68A" if color == AMBER_500 else LINE)
        frame = QFrame()
        frame.setStyleSheet(f"background:{bg};border:1px solid {border};border-radius:8px;padding:8px 12px;margin:2px 0;")
        h = QHBoxLayout(frame)
        h.addWidget(QLabel(name))
        h.addStretch()
        detail_lbl = QLabel(detail)
        detail_lbl.setStyleSheet(f"color:{color};font-weight:bold;")
        h.addWidget(detail_lbl)
        return frame

    def _quick_range(self, days, active_btn=None):
        self._programmatic_date_change = True
        self.to_input.setDate(QDate.currentDate())
        self.from_input.setDate(QDate.currentDate().addDays(-days))
        self._programmatic_date_change = False
        # نفك تحديد كل الأزرار الثانية ونخلي المضغوط بس ملوّن، حتى لو ضغط
        # المستخدم نفس الزر مرتين (setCheckable يخليه يفك تحديده لحاله) -
        # نرجعه نحدده يدويًا لأن هذا الزر هو الفترة الفعلية المعروضة دائمًا.
        for b in self._range_buttons:
            b.setChecked(b is active_btn)
        self.refresh()

    def _clear_quick_range_selection(self):
        """يفك تحديد كل أزرار الفترة السريعة (اليوم/أسبوع/شهر/سنة) لما
        المستخدم يعدّل التاريخ يدويًا - حتى ما يضل زر ملوّن وهو ما عاد
        يمثّل الفترة المعروضة فعليًا. ما يشتغل أثناء الضغط على نفس الأزرار
        (اللي تغيّر التاريخ برمجيًا هي نفسها)."""
        if getattr(self, "_programmatic_date_change", False):
            return
        if not hasattr(self, "_range_buttons"):
            return
        for b in self._range_buttons:
            b.setChecked(False)

    def withdraw_cash(self):
        amount, ok = QInputDialog.getDouble(self, "سحب من الصندوق", "المبلغ المسحوب:", 0, 0, 1_000_000_000, 0)
        if not ok or amount <= 0:
            return
        reason, ok2 = QInputDialog.getText(self, "سبب السحب", "ملاحظة (اختياري):")
        self.session.add(Expense(category="سحب من الصندوق", amount=amount, description=reason or ""))
        self.session.commit()
        QMessageBox.information(self, "تم", f"تم تسجيل سحب {fmt_money(amount)} من الصندوق.")
        self.refresh()

    def show_withdrawals_list(self):
        dialog = WithdrawalsListDialog(self.session, self)
        dialog.exec()
        self.refresh()

    def _render_invoice_table(self, invoices):
        self.recent_table.setRowCount(len(invoices))
        for row, inv in enumerate(invoices):
            self.recent_table.setItem(row, 0, QTableWidgetItem(inv.invoice_number))
            self.recent_table.setItem(row, 1, QTableWidgetItem(inv.invoice_date.strftime("%Y-%m-%d %H:%M")))
            self.recent_table.setItem(row, 2, QTableWidgetItem(inv.payment_status))
            self.recent_table.setItem(row, 3, QTableWidgetItem(fmt_money(inv.final_amount)))
            self.recent_table.item(row, 0).setData(Qt.UserRole, inv.id)
        self.recent_table.resizeRowsToContents()

    def _filter_invoice_table(self, text):
        text = text.strip()
        source = self._all_invoices if self._show_all_invoices else self._all_invoices[:30]
        if text:
            filtered = [inv for inv in self._all_invoices if text in inv.invoice_number]
            self._render_invoice_table(filtered)
        else:
            self._render_invoice_table(source)

    def _toggle_show_all(self):
        self._show_all_invoices = not self._show_all_invoices
        self.show_all_btn.setText("عرض آخر 30 بس" if self._show_all_invoices else "عرض كل الفواتير")
        self._render_invoice_table(self._all_invoices if self._show_all_invoices else self._all_invoices[:30])

    def _open_invoice_detail(self, row, col):
        invoice_id = self.recent_table.item(row, 0).data(Qt.UserRole)
        invoice = self.session.query(Invoice).get(invoice_id)
        if not invoice:
            return
        dialog = InvoiceDetailDialog(invoice, self.session, self)
        dialog.raise_()
        dialog.activateWindow()
        dialog.exec()
        self.refresh()  # الحذف ممكن يكون غيّر الأرقام، نحدّث كل شي

    def _stat_card(self, number, label, color, on_click=None):
        frame = QFrame()
        frame.setStyleSheet(f"background:white;border:1px solid #E5E7EB;border-right:4px solid {color};border-radius:10px;padding:12px;")
        add_shadow(frame, blur=14, color=color, alpha=30, y_offset=3)
        v = QVBoxLayout(frame)
        n = QLabel(str(number))
        n.setStyleSheet(f"font-size:20px;font-weight:bold;color:{color};")
        l = QLabel(label)
        l.setStyleSheet("color:#6B7280;font-size:12px;")
        l.setWordWrap(True)
        v.addWidget(n)
        v.addWidget(l)
        if on_click:
            frame.setCursor(Qt.PointingHandCursor)
            frame.mousePressEvent = lambda event: on_click()
        return frame

    def refresh(self):
        while self.stats_row.count():
            child = self.stats_row.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        try:
            self._do_refresh()
        except Exception as e:
            err_wrap = QFrame()
            err_wrap.setStyleSheet("background:transparent;border:none;")
            err_row = QHBoxLayout(err_wrap)
            err_row.setContentsMargins(10, 10, 10, 10)
            err_row.setSpacing(8)
            err_icon_lbl = QLabel()
            err_icon_lbl.setStyleSheet("background:transparent;border:none;")
            err_icon_lbl.setPixmap(pixmap("warning", color=RED_500, size=15))
            err_row.addWidget(err_icon_lbl)
            err = QLabel(f"صار خطأ بحساب التقارير: {e}")
            err.setStyleSheet("color:#DC2626;font-weight:bold;background:transparent;border:none;")
            err.setWordWrap(True)
            err_row.addWidget(err)
            self.stats_row.addWidget(err_wrap)

    def _do_refresh(self):
        start = datetime.combine(self.from_input.date().toPython(), datetime.min.time())
        end = datetime.combine(self.to_input.date().toPython(), datetime.max.time())

        invoices = (
            self.session.query(Invoice)
            .options(joinedload(Invoice.items))
            .filter(Invoice.invoice_date >= start, Invoice.invoice_date <= end)
            .order_by(Invoice.invoice_date.desc())
            .all()
        )

        revenue = sum(inv.final_amount for inv in invoices)
        count = len(invoices)

        # كان يفتح استعلام Batch وProductUnit وProduct منفصل لكل بند فاتورة
        # (N+1 يتضاعف مع عدد المبيعات بالفترة المختارة) - نجيبهم دفعة وحدة
        # بنداءات IN(...) قليلة بدل نداء لكل بند، بنفس حساب الربح بالضبط.
        all_items = [item for inv in invoices for item in inv.items]
        batch_ids = {item.batch_id for item in all_items if item.batch_id}
        unit_ids = {item.unit_id for item in all_items if item.unit_id}
        batches_by_id = (
            {b.id: b for b in self.session.query(Batch).filter(Batch.id.in_(batch_ids)).all()}
            if batch_ids else {}
        )
        units_by_id = (
            {u.id: u for u in self.session.query(ProductUnit).filter(ProductUnit.id.in_(unit_ids)).all()}
            if unit_ids else {}
        )
        product_ids = {b.product_id for b in batches_by_id.values() if b.product_id}
        products_by_id = (
            {p.id: p for p in self.session.query(Product).filter(Product.id.in_(product_ids)).all()}
            if product_ids else {}
        )

        profit = 0
        product_stats = {}  # product_id -> [name, qty_base_units, revenue]
        for inv in invoices:
            is_return = inv.payment_status == "مرتجع"
            for item in inv.items:
                batch = batches_by_id.get(item.batch_id)
                unit = units_by_id.get(item.unit_id) if item.unit_id else None
                if item.unit_cost:
                    # القيمة المحفوظة وقت البيع/الإرجاع نفسه - الأدق، وما تتأثر
                    # بتغيّر أسعار الدفعات لاحقًا أو باختلاف الدفعة المستخدمة بالإرجاع.
                    cost = item.unit_cost * item.quantity
                else:
                    # فواتير قديمة من قبل إضافة unit_cost - نرجع لنفس الطريقة السابقة كتقدير احتياطي
                    cost = (batch.purchase_price or 0) * (unit.conversion_factor if unit else 1) * item.quantity if batch else 0
                if is_return:
                    # الإرجاع: نخصم الإيراد كامل (item.subtotal سالب أصلاً) ونرجّع الكلفة
                    # حتى ما تنخصم مرتين - النتيجة صافيها خصم هامش الربح بس، مو الإيراد+الكلفة
                    profit += item.subtotal + cost
                else:
                    profit += item.subtotal - cost

                product = products_by_id.get(batch.product_id) if batch else None
                if product:
                    if product.id not in product_stats:
                        product_stats[product.id] = [product.name, 0, 0]
                    product_stats[product.id][1] += item.quantity
                    product_stats[product.id][2] += item.subtotal

            # الخصم بمستوى الفاتورة كاملة (مبلغ ثابت واحد)، مو لكل صنف بداخلها:
            # - عند البيع: الخصم يقلّل الربح الفعلي (الزبون دفع أقل من السعر الكامل).
            # - عند الإرجاع: نضيف نفس الخصم بدل ما نتجاهله، لأنه لازم يعاكس بالضبط
            #   أثر الخصم اللي انسجّل بالبيع الأصلي. لو ما سوينا هذا، إرجاع صنف
            #   انباع بخصم كان يطرح الربح الكامل (قبل الخصم) بدل صافي الربح
            #   الفعلي اللي كان مسجّل، فيصير المجموع بالسالب حتى لو رجّعت
            #   بالضبط نفس اللي بعته.
            if not is_return:
                profit -= (inv.discount or 0)
            else:
                profit += (inv.discount or 0)

        wallet_amount = (
            self.session.query(Payment)
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .filter(Invoice.invoice_date >= start, Invoice.invoice_date <= end, Payment.payment_method == "محفظة")
            .with_entities(Payment.amount)
            .all()
        )
        wallet_total = sum(a[0] for a in wallet_amount)

        expenses_total = (
            self.session.query(Expense)
            .filter(Expense.date >= start.date(), Expense.date <= end.date())
            .all()
        )
        expenses_sum = sum(e.amount for e in expenses_total)
        net_revenue = revenue - expenses_sum
        net_profit = profit - expenses_sum

        net_revenue_label = "صافي الوارد (بعد السحوبات)"
        if wallet_total:
            net_revenue_label += f"\n(يتضمن: المبلغ المدفوع عن طريق المحفظة {fmt_money(wallet_total)})"

        self.stats_row.addWidget(self._stat_card(count, "عدد الفواتير", "#16A34A"))
        self.stats_row.addWidget(self._stat_card(fmt_money(net_revenue), net_revenue_label, "#16A34A"))
        self.stats_row.addWidget(self._stat_card(fmt_money(net_profit), "صافي الربح (بعد السحوبات)", "#22C55E"))
        self.stats_row.addWidget(self._stat_card(fmt_money(expenses_sum), "المصاريف والسحوبات (اضغط للتفاصيل)", "#DC2626", on_click=self.show_withdrawals_list))

        top = sorted(product_stats.values(), key=lambda x: x[1], reverse=True)[:10]
        self.top_table.setRowCount(len(top))
        for row, (name, qty, rev) in enumerate(top):
            self.top_table.setItem(row, 0, QTableWidgetItem(name))
            self.top_table.setItem(row, 1, QTableWidgetItem(str(qty)))
            self.top_table.setItem(row, 2, QTableWidgetItem(fmt_money(rev)))
        self.top_table.resizeRowsToContents()

        self._all_invoices = invoices
        self._render_invoice_table(invoices if self._show_all_invoices else invoices[:30])

        self._refresh_alerts()
        self._refresh_waste_report(start, end)
        self._refresh_inventory_report()
        self._refresh_stagnant_report()

    def _refresh_alerts(self):
        while self.alerts_layout.count():
            child = self.alerts_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        today = date.today()
        expiry_alert_days = get_expiry_alert_days(self.session)
        low, near_exp = [], []
        products = (
            self.session.query(Product)
            .options(joinedload(Product.batches))
            .filter(Product.is_active == True)
            .all()
        )
        # لو إعداد "الاعتماد على الأدوية المعتمدة" مفعّل، نقصر قسم التنبيهات
        # بأعلى شاشة التقارير على الأدوية المعتمدة بس.
        if is_approved_filter_enabled(self.session):
            products = [p for p in products if is_product_approved(p)]
        for p in products:
            stock = sum(b.quantity_available for b in p.batches)
            threshold = p.min_stock_threshold or 10
            if stock <= threshold:
                low.append((p.name, stock, threshold))
            nearest = min(
                (b.expiry_date for b in p.batches if b.expiry_date and b.quantity_available > 0),
                default=None,
            )
            if nearest and today < nearest <= today + timedelta(days=expiry_alert_days):
                near_exp.append((p.name, nearest))

        if not low and not near_exp:
            ok_wrap = QFrame()
            ok_wrap.setStyleSheet("background:transparent;border:none;")
            ok_row = QHBoxLayout(ok_wrap)
            ok_row.setContentsMargins(0, 0, 0, 0)
            ok_row.setSpacing(8)
            ok_icon_lbl = QLabel()
            ok_icon_lbl.setStyleSheet("background:transparent;border:none;")
            ok_icon_lbl.setPixmap(pixmap("check", color=TEAL_500, size=15))
            ok_row.addWidget(ok_icon_lbl)
            lbl = QLabel("ماكو نواقص قريبة أو أدوية قرب انتهاء الصلاحية حاليًا.")
            lbl.setStyleSheet("color:#16A34A;font-weight:bold;background:transparent;border:none;")
            ok_row.addWidget(lbl)
            ok_row.addStretch()
            self.alerts_layout.addWidget(ok_wrap)
            return

        header_wrap = QFrame()
        header_wrap.setStyleSheet("background:transparent;border:none;")
        header_row = QHBoxLayout(header_wrap)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        header_icon_lbl = QLabel()
        header_icon_lbl.setStyleSheet("background:transparent;border:none;")
        header_icon_lbl.setPixmap(pixmap("warning", color=AMBER_500, size=15))
        header_row.addWidget(header_icon_lbl)
        header = QLabel("تنبيهات استباقية - قبل ما توصل لمخزون صفر أو صلاحية منتهية")
        header.setStyleSheet("font-weight:bold;background:transparent;border:none;")
        header_row.addWidget(header)
        header_row.addStretch()
        self.alerts_layout.addWidget(header_wrap)
        for name, stock, threshold in low[:10]:
            self.alerts_layout.addWidget(QLabel(f"• {name}: الكمية {stock} (الحد الأدنى {threshold})"))
        for name, exp in sorted(near_exp, key=lambda x: x[1])[:10]:
            days_left = (exp - today).days
            self.alerts_layout.addWidget(QLabel(f"• {name}: تنتهي صلاحيته بعد {days_left} يوم"))

    def _refresh_waste_report(self, start, end):
        while self.waste_stats_row.count():
            child = self.waste_stats_row.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        movements = (
            self.session.query(StockMovement)
            .filter(StockMovement.movement_type == "تالف")
            .filter(StockMovement.moved_at >= start, StockMovement.moved_at <= end)
            .order_by(StockMovement.moved_at.desc())
            .all()
        )

        # تجميع الحركات اللي تعود لنفس عملية حفظ هدر وحدة - لما كمية هدر
        # وحدة (مثلاً 100 شريط) توزّعت تلقائيًا على أكثر من دفعة (لأن دفعة
        # وحدة ما كانت تكفي)، النظام يسجّلها كحركة منفصلة لكل دفعة (بنفس
        # الثانية تقريبًا، نفس الدواء، نفس السبب). بدون التجميع هذا، المستخدم
        # يشوفها كأنها عدة عمليات هدر متفرقة بكميات غريبة بدل عملية وحدة
        # بكميتها الصحيحة الكاملة - وهذا كان سبب اللبس واللبس بالكمية المعروضة.
        grouped = {}
        order = []
        for m in movements:
            batch = self.session.query(Batch).get(m.batch_id)
            product = self.session.query(Product).get(batch.product_id) if batch else None
            cost = (batch.purchase_price or 0) * m.quantity if batch else 0
            # مفتاح التجميع: نفس الدواء + نفس السبب + نفس الدقيقة (الحركات
            # الناتجة من نفس عملية حفظ تصير كلها بنفس اللحظة تقريبًا).
            key = (
                product.id if product else None,
                m.note,
                m.moved_at.strftime("%Y-%m-%d %H:%M"),
            )
            if key not in grouped:
                grouped[key] = {
                    "date": m.moved_at, "product": product, "qty": 0, "cost": 0, "note": m.note,
                }
                order.append(key)
            grouped[key]["qty"] += m.quantity
            grouped[key]["cost"] += cost

        waste_cost = sum(g["cost"] for g in grouped.values())
        while self.waste_list_layout.count():
            child = self.waste_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        if not order:
            empty_lbl = QLabel("ما فيه عمليات هدر مسجّلة بهذي الفترة.")
            empty_lbl.setStyleSheet(f"color:{INK_2};padding:12px;")
            self.waste_list_layout.addWidget(empty_lbl)
        for key in order:
            g = grouped[key]
            product = g["product"]
            self.waste_list_layout.addWidget(self._waste_row(
                name=product.name if product else "دواء محذوف",
                barcode=(product.barcode if product and product.barcode else None),
                date_str=g["date"].strftime("%Y-%m-%d"),
                qty=g["qty"],
                reason=g["note"] or "بدون سبب محدد",
                cost=g["cost"],
            ))
        self.waste_list_layout.addStretch()

        # قيمة الدفعات المنتهية الصلاحية حاليًا (لسه بالمخزون، ما انسحبت كهدر بعد)
        today = date.today()
        expired_batches = (
            self.session.query(Batch)
            .filter(Batch.expiry_date.isnot(None), Batch.expiry_date < today, Batch.quantity_available > 0)
            .all()
        )
        expired_qty = sum(b.quantity_available for b in expired_batches)
        expired_value = sum((b.purchase_price or 0) * b.quantity_available for b in expired_batches)

        total_estimate = waste_cost + expired_value

        self.waste_stats_row.addWidget(self._stat_card(
            fmt_money(waste_cost), f"هدر تعديلات ({len(order)} عملية)", "#DC2626"))
        self.waste_stats_row.addWidget(self._stat_card(
            fmt_money(expired_value), f"منتهي صلاحية (حالي) - {expired_qty} قطعة", "#16A34A"))
        self.waste_stats_row.addWidget(self._stat_card(
            fmt_money(total_estimate), "الإجمالي التقديري", "#16A34A"))



class WithdrawalsListDialog(QDialog):
    """قائمة كل عمليات السحب من الصندوق مع أسبابها - وتقدر تعدل أو تحذف أي سحب."""
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("كل السحوبات من الصندوق")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)

        layout = QVBoxLayout(self)
        title = QLabel("كل عمليات السحب من الصندوق")
        title.setStyleSheet("font-size:15px;font-weight:bold;margin-bottom:6px;")
        layout.addWidget(title)

        self.table = QTableWidget()
        enable_touch_scroll(self.table)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["التاريخ", "المبلغ", "السبب", "تعديل", "حذف"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        total_lbl = QLabel()
        total_lbl.setStyleSheet("font-weight:bold;color:#DC2626;margin-top:6px;")
        layout.addWidget(total_lbl)
        self.total_lbl = total_lbl

        self._load()

    def _load(self):
        withdrawals = (
            self.session.query(Expense)
            .filter(Expense.category == "سحب من الصندوق")
            .order_by(Expense.date.desc())
            .all()
        )
        self.table.setRowCount(len(withdrawals))
        for row, w in enumerate(withdrawals):
            self.table.setItem(row, 0, QTableWidgetItem(w.date.strftime("%Y-%m-%d %H:%M") if w.date else "-"))
            self.table.setItem(row, 1, QTableWidgetItem(fmt_money(w.amount)))
            self.table.setItem(row, 2, QTableWidgetItem(w.description or "-"))

            edit_btn = QPushButton("تعديل")
            edit_btn.setIcon(icon("edit", color=TEAL_600, size=13))
            edit_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:6px;padding:4px 10px;")
            edit_btn.clicked.connect(lambda _, wid=w.id: self._edit(wid))
            self.table.setCellWidget(row, 3, edit_btn)

            delete_btn = QPushButton("حذف")
            delete_btn.setIcon(icon("trash", color=RED_500, size=13))
            delete_btn.setStyleSheet("background:#DC2626;color:white;border-radius:6px;padding:4px 10px;")
            delete_btn.clicked.connect(lambda _, wid=w.id: self._delete(wid))
            self.table.setCellWidget(row, 4, delete_btn)
        self.table.resizeRowsToContents()

        self.total_lbl.setText(f"إجمالي كل السحوبات: {fmt_money(sum(w.amount for w in withdrawals))}")

    def _edit(self, withdrawal_id):
        w = self.session.query(Expense).get(withdrawal_id)
        if not w:
            return
        amount, ok = QInputDialog.getDouble(self, "تعديل السحب", "المبلغ:", w.amount, 0, 1_000_000_000, 0)
        if not ok:
            return
        reason, ok2 = QInputDialog.getText(self, "تعديل السبب", "ملاحظة:", QLineEdit.Normal, w.description or "")
        if not ok2:
            return
        w.amount = amount
        w.description = reason
        self.session.commit()
        self._load()

    def _delete(self, withdrawal_id):
        confirm = QMessageBox.question(
            self, "تأكيد الحذف", "متأكد تريد تحذف هذا السحب؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        w = self.session.query(Expense).get(withdrawal_id)
        if w:
            self.session.delete(w)
            self.session.commit()
        self._load()


class InvoiceDetailDialog(QDialog):
    """تفاصيل فاتورة: عرض الأصناف وتعديل الكمية/الخصم، وحذف الفاتورة (يرجّع المخزون ويصحح الديون تلقائيًا)."""
    def __init__(self, invoice, session, parent=None):
        super().__init__(parent)
        self.invoice = invoice
        self.session = session
        self.setWindowTitle(f"تفاصيل الفاتورة {invoice.invoice_number}")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        header = QLabel(f"طريقة الدفع: {invoice.payment_status}")
        header.setStyleSheet("color:#6B7280;margin-bottom:8px;")
        layout.addWidget(header)

        # تعديل التاريخ - نفس التعميم المطبّق بنافذة تعديل فاتورة الشراء
        # (أي نافذة تعديل فاتورة بالنظام صار فيها هذا الحقل قابل للتعديل).
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("التاريخ:"))
        self.date_input = QDateEdit(QDate(invoice.invoice_date) if invoice.invoice_date else QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.date_input)
        date_row.addStretch()
        layout.addLayout(date_row)

        self.table = QTableWidget()
        enable_touch_scroll(self.table)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["الدواء", "سعر الوحدة", "الكمية", "الإجمالي", ""])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setRowCount(len(invoice.items))
        self._qty_inputs = []  # [(item_id, batch_id, unit_id, unit_price, QLineEdit), ...]
        for row, item in enumerate(invoice.items):
            self._build_item_row(row, item)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table)

        discount_row = QHBoxLayout()
        discount_row.addWidget(QLabel("الخصم:"))
        self.discount_input = NumberLineEdit()
        self.discount_input.set_value(invoice.discount)
        discount_row.addWidget(self.discount_input)
        layout.addLayout(discount_row)

        self.final_lbl = QLabel(f"الصافي: {fmt_money(invoice.final_amount)}")
        self.final_lbl.setStyleSheet("font-weight:bold;color:#16A34A;")
        layout.addWidget(self.final_lbl)

        note = QLabel("تغيير الكمية يعدّل المخزون تلقائيًا بالفرق (زيادة الكمية تسحب مخزون إضافي، تنقيصها يرجّع مخزون).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6B7280;font-size:11px;")
        layout.addWidget(note)

        save_btn = QPushButton("حفظ التعديلات")
        save_btn.setIcon(icon("save", color="white", size=15))
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:10px;font-weight:bold;")
        save_btn.clicked.connect(self.save_edits)
        layout.addWidget(save_btn)

        delete_btn = QPushButton("حذف الفاتورة (يرجّع المخزون تلقائيًا)")
        delete_btn.setIcon(icon("trash", color=RED_500, size=15))
        delete_btn.setStyleSheet("background:#DC2626;color:white;border-radius:8px;padding:10px;font-weight:bold;")
        delete_btn.clicked.connect(self.delete_invoice)
        layout.addWidget(delete_btn)

    def _build_item_row(self, row, item):
        """يبني صف صنف وحد بجدول الفاتورة (دواء/سعر/كمية/إجمالي/زر حذف)."""
        batch = self.session.query(Batch).get(item.batch_id)
        product = self.session.query(Product).get(batch.product_id) if batch else None
        unit = self.session.query(ProductUnit).get(item.unit_id) if item.unit_id else None
        self.table.setItem(row, 0, QTableWidgetItem(f"{product.name if product else '-'} ({unit.unit_name if unit else ''})"))
        self.table.setItem(row, 1, QTableWidgetItem(fmt_money(item.unit_price)))
        qty_input = NumberLineEdit()
        qty_input.set_value(item.quantity)
        self.table.setCellWidget(row, 2, qty_input)
        self.table.setItem(row, 3, QTableWidgetItem(fmt_money(item.subtotal)))
        del_btn = QPushButton()
        del_btn.setIcon(icon("trash", color="#DC2626", size=14))
        del_btn.setToolTip("حذف هذا الصنف كامل من الفاتورة (مو بس تصفير الكمية)")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet("background:transparent;border:none;padding:4px;")
        del_btn.clicked.connect(lambda checked=False, iid=item.id: self._delete_single_item(iid))
        self.table.setCellWidget(row, 4, del_btn)
        self._qty_inputs.append((item.id, item.unit_price, qty_input))

    def _delete_single_item(self, item_id):
        """حذف صنف كامل من الفاتورة (مو بس تصفير كميته) - يرجّع المخزون
        فورًا ويصحح دين الزبون لو الفاتورة آجلة، ثم يعيد بناء الجدول."""
        item = self.session.query(InvoiceItem).get(item_id)
        if not item:
            return
        if len(self.invoice.items) <= 1:
            QMessageBox.warning(
                self, "تنبيه",
                "هذا آخر صنف بالفاتورة - لو تريد تصفر الفاتورة كاملة استخدم زر \"حذف الفاتورة\" بالأسفل."
            )
            return
        batch = self.session.query(Batch).get(item.batch_id)
        product = self.session.query(Product).get(batch.product_id) if batch else None
        product_name = product.name if product else "الصنف"
        confirm = QMessageBox.question(
            self, "تأكيد الحذف",
            f"متأكد تريد تحذف \"{product_name}\" كامل من هذي الفاتورة؟ راح يرجع المخزون تلقائيًا ويصحح الدين لو الفاتورة آجلة.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        invoice = self.session.query(Invoice).get(self.invoice.id)
        unit = self.session.query(ProductUnit).get(item.unit_id) if item.unit_id else None
        if batch:
            base_qty = item.quantity * (unit.conversion_factor if unit else 1)
            batch.quantity_available += base_qty
            self.session.add(StockMovement(
                batch_id=batch.id, unit_id=item.unit_id, movement_type="إرجاع",
                quantity=base_qty, note=f"حذف صنف \"{product_name}\" من فاتورة {invoice.invoice_number}",
            ))

        if invoice.customer_id:
            customer = self.session.query(Customer).get(invoice.customer_id)
            if customer:
                customer.current_balance = max((customer.current_balance or 0) - item.subtotal, 0)

        self.session.delete(item)
        self.session.flush()
        invoice.total_amount = sum(i.subtotal for i in invoice.items)
        invoice.final_amount = invoice.total_amount - (invoice.discount or 0)
        self.session.commit()

        self._rebuild_table()

    def _rebuild_table(self):
        """يعيد بناء جدول الأصناف من جديد بعد حذف صنف كامل."""
        self.session.refresh(self.invoice)
        self._qty_inputs = []
        self.table.setRowCount(len(self.invoice.items))
        for row, item in enumerate(self.invoice.items):
            self._build_item_row(row, item)
        self.table.resizeRowsToContents()
        self.final_lbl.setText(f"الصافي: {fmt_money(self.invoice.final_amount)}")

    def save_edits(self):
        invoice = self.session.query(Invoice).get(self.invoice.id)
        new_final = 0.0
        for item_id, unit_price, qty_input in self._qty_inputs:
            new_qty = int(qty_input.value())
            if new_qty <= 0:
                QMessageBox.warning(self, "تنبيه", "الكمية لازم تكون أكبر من صفر (احذف الصنف بزر الحذف لو تريد تشيله كامل).")
                return
            item = self.session.query(InvoiceItem).get(item_id)
            batch = self.session.query(Batch).get(item.batch_id)
            unit = self.session.query(ProductUnit).get(item.unit_id) if item.unit_id else None
            factor = unit.conversion_factor if unit else 1

            delta_qty = new_qty - item.quantity  # موجب = زيادة (نسحب مخزون إضافي)، سالب = نقصان (نرجّع مخزون)
            if batch:
                base_delta = delta_qty * factor
                if base_delta > 0 and batch.quantity_available < base_delta:
                    QMessageBox.warning(self, "تنبيه مخزون", "الكمية المتوفرة بالمخزون أقل من الزيادة المطلوبة.")
                    return
                batch.quantity_available -= base_delta
                self.session.add(StockMovement(
                    batch_id=batch.id, unit_id=item.unit_id,
                    movement_type="بيع" if base_delta > 0 else "إرجاع",
                    quantity=abs(base_delta), note=f"تعديل فاتورة {invoice.invoice_number}",
                ))

            item.quantity = new_qty
            sign = -1 if invoice.payment_status == "مرتجع" else 1
            item.subtotal = sign * unit_price * new_qty
            new_final += item.subtotal

        discount = self.discount_input.value()
        invoice.discount = discount
        invoice.invoice_date = self.date_input.date().toPython()
        invoice.final_amount = new_final - discount
        self.session.commit()
        self.final_lbl.setText(f"الصافي: {fmt_money(invoice.final_amount)}")
        QMessageBox.information(self, "تم", "تم حفظ تعديلات الفاتورة.")
        self.accept()

    def delete_invoice(self):
        confirm = QMessageBox.question(
            self, "تأكيد الحذف",
            "متأكد تريد تحذف هذي الفاتورة؟ راح يرجع المخزون تلقائيًا ويصحح الديون لو كانت آجلة.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        invoice = self.invoice
        # إرجاع المخزون لكل صنف بالفاتورة
        for item in invoice.items:
            batch = self.session.query(Batch).get(item.batch_id)
            unit = self.session.query(ProductUnit).get(item.unit_id) if item.unit_id else None
            if batch:
                base_qty = item.quantity * (unit.conversion_factor if unit else 1)
                batch.quantity_available += base_qty
                self.session.add(StockMovement(
                    batch_id=batch.id, unit_id=item.unit_id, movement_type="إرجاع",
                    quantity=base_qty, note=f"حذف فاتورة {invoice.invoice_number}",
                ))

        # تصحيح دين الزبون لو الفاتورة كانت آجلة
        if invoice.customer_id:
            customer = self.session.query(Customer).get(invoice.customer_id)
            if customer:
                customer.current_balance = max((customer.current_balance or 0) - invoice.final_amount, 0)

        self.session.delete(invoice)
        self.session.commit()
        QMessageBox.information(self, "تم", "تم حذف الفاتورة وإرجاع المخزون.")
        self.accept()
