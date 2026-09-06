"""
الشاشة الرئيسية / لوحة التحكم - تعرض تنبيهات النواقص والأدوية قريبة الانتهاء.

ملاحظة صادقة: هذي تنبيهات تظهر جوا البرنامج (تتحدث كل ما تفتح الشاشة أو تسجل
دخول)، مو إشعارات فعلية توصل للموبايل أو الإيميل خارج البرنامج - هذا الأخير
يحتاج سيرفر مركزي شغّال (نفس النقطة اللي حكينا عنها بموضوع الترخيص) يرسل
تنبيهات push أو إيميل يومي، ونقدر نبنيها بمرحلة لاحقة بعد ما ينشر السيرفر.

تحديث (H1 Design System / Task 1): إعادة تصميم بصري بحت للداشبورد - بطاقات
إحصائية موحّدة، تباعد/طباعة/ألوان من app.ui.theme، أزرار إجراءات سريعة،
أماكن محجوزة للرسوم البيانية المستقبلية، وشبكة بطاقات تتجاوب مع عرض
النافذة. ما تغيّر أي استعلام قاعدة بيانات ولا أي حساب مالي/مخزوني - نفس
المنطق بالضبط، بس عرضه تغيّر.
"""
from datetime import date, timedelta, datetime
from types import SimpleNamespace
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QScrollArea, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt
from sqlalchemy.orm import joinedload

from app.db.database import get_session
from app.db.models import Product, Invoice, InvoiceItem, Batch, ProductUnit, Expense, AlertOccurrence
from app.db.approved_helper import approved_clause, is_approved_filter_enabled
from app.db.settings_helper import get_expiry_alert_days
from sqlalchemy import func
from app.ui.widgets import (
    create_stat_card, create_section_title,
    create_quick_action_button, add_shadow, enable_touch_scroll,
)
from app.ui.icons import icon
from app.ui.theme import (
    TEAL_500, TEAL_400, TEAL_700, RED_500, AMBER_500,
    COLOR_TEXT_SECONDARY, COLOR_DANGER_BG, COLOR_DANGER_BORDER,
    COLOR_WARNING_BG, COLOR_WARNING_BORDER,
    COLOR_SURFACE, COLOR_SURFACE_SUBTLE, COLOR_BORDER, COLOR_TEXT_PRIMARY,
    FONT_H1, FONT_H2, FONT_BODY_STRONG,
    SPACE_8, SPACE_12, SPACE_16, SPACE_20, SPACE_24,
    RADIUS_BUTTON, RADIUS_CARD, SHADOW_MEDIUM,
)


def fmt_money(n):
    return f"{n:,.0f} د.ع"


class DashboardView(QWidget):
    # on_navigate: دالة اختيارية توخذ اسم الصفحة (نفس مفاتيح self.pages
    # بـ main_window.py) وتنقل المستخدم إليها - تُستخدم بأزرار "إجراءات
    # سريعة". لو ما انمررت (الحالة الافتراضية)، الأزرار تظهر بس ما تسوي
    # شي عند الضغط - ما فيه أي كسر لأي طريقة إنشاء حالية لـ DashboardView().
    def __init__(self, parent=None, on_navigate=None):
        super().__init__(parent)
        self.session = get_session()
        self.on_navigate = on_navigate
        self._finance_cards = []
        self._summary_cards = []
        self._capital_cards = []
        self._finance_error_frame = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- الصفحة كاملة تصير قابلة للتمرير (نزول للأسفل) بدل ما تنحصر
        # فقط بقائمة التنبيهات بالأسفل ----
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(page_scroll)

        page_content = QWidget()
        page_scroll.setWidget(page_content)
        enable_touch_scroll(page_scroll)

        self.layout_ = QVBoxLayout(page_content)
        self.layout_.setContentsMargins(SPACE_24, SPACE_20, SPACE_24, SPACE_20)
        self.layout_.setSpacing(SPACE_8)

        # ---- عنوان الصفحة + إجراءات سريعة ----
        header_row = QHBoxLayout()
        title = QLabel("الرئيسية")
        title.setStyleSheet(
            f"font-size:{FONT_H1[0]}px;font-weight:{FONT_H1[1]};background:transparent;border:none;"
        )
        header_row.addWidget(title)
        header_row.addStretch()
        header_row.addLayout(self._build_quick_actions())
        self.layout_.addLayout(header_row)

        # ---- الوارد اليومي (بطاقة بارزة بالأعلى) ----
        self.daily_income_card = self._build_daily_income_card()
        self.layout_.addWidget(self.daily_income_card)

        # ---- ملخص الشهر الحالي ----
        self.layout_.addWidget(create_section_title("ملخص الشهر الحالي"))
        self.finance_row = QGridLayout()
        self.finance_row.setHorizontalSpacing(SPACE_16)
        self.finance_row.setVerticalSpacing(SPACE_16)
        self.layout_.addLayout(self.finance_row)

        # ---- رأس المال والربح المتوقع (منقولة من شاشة التقارير) ----
        self.layout_.addWidget(create_section_title("رأس المال والربح المتوقع"))
        self.capital_row = QGridLayout()
        self.capital_row.setHorizontalSpacing(SPACE_16)
        self.capital_row.setVerticalSpacing(SPACE_16)
        self.layout_.addLayout(self.capital_row)

        # ---- تنبيهات المخزون (بطاقات الملخص) ----
        self.layout_.addWidget(create_section_title("تنبيهات المخزون"))
        self.summary_row = QGridLayout()
        self.summary_row.setHorizontalSpacing(SPACE_16)
        self.summary_row.setVerticalSpacing(SPACE_16)
        self.layout_.addLayout(self.summary_row)

        # ملاحظة أداء مهمة: هذي البطاقات (ملخص الشهر، رأس المال، تنبيهات
        # المخزون) عددها ثابت دائمًا - فنبنيها مرة وحدة بس هنا، وrefresh()
        # بعدين يحدّث نصوصها بمكانها (update_values) بدل ما يحذفها ويبنيها
        # من الصفر بكل تنقل للصفحة. حذف/بناء QFrame + ظل QGraphicsDropShadowEffect
        # لعشرة بطاقات بكل ضغطة كان جزء كبير من "الومضة"/التهنيج المحسوس عند
        # فتح الرئيسية بشكل متكرر - هذا يلغيه تمامًا بدون أي تغيير بالحسابات.
        self._finance_cards = [
            self._stat_card("-", "الواردات (بعد السحوبات)", TEAL_500),
            self._stat_card("-", "الأرباح (بعد السحوبات)", TEAL_400),
            self._stat_card("-", "الاستقطاعات الشهرية", RED_500),
        ]
        self._populate_grid(self.finance_row, self._finance_cards)

        self._capital_cards = [
            self._stat_card("-", "رأس المال (تكلفة الشراء)", TEAL_500),
            self._stat_card("-", "قيمة البيع المتوقعة", TEAL_400),
            self._stat_card("-", "الربح المتوقع", TEAL_700),
        ]
        self._populate_grid(self.capital_row, self._capital_cards)

        self._summary_cards = [
            self._stat_card(0, "أدوية نافذة", RED_500),
            self._stat_card(0, "مخزون منخفض", AMBER_500),
            self._stat_card(0, "منتهية الصلاحية", RED_500),
            self._stat_card(0, "قرب انتهاء الصلاحية", AMBER_500),
        ]
        self._populate_grid(self.summary_row, self._summary_cards, col_count=4)

        # ---- قائمة التنبيهات التفصيلية (أقسام قابلة للطي - اضغط على أي
        # مكان بعنوان القسم يفتحه أو يطويه) ----
        self.layout_.addWidget(create_section_title("تفاصيل التنبيهات"))
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(SPACE_8)
        self.layout_.addLayout(self.list_layout)
        self.layout_.addStretch()

        self.refresh()

    def _build_quick_actions(self):
        """صف أزرار إجراءات سريعة - تنقل لصفحات موجودة فعليًا بالتطبيق
        (نفس مفاتيح self.pages بـ main_window.py) عبر on_navigate. لا تضيف
        أي منطق أعمال جديد - كل زر يفتح شاشة موجودة أصلاً."""
        row = QHBoxLayout()
        row.setSpacing(SPACE_12)
        actions = [
            ("بيع جديد", "البيع", "primary"),
            ("إضافة مخزون", "المخزون", "outline"),
            ("فاتورة شراء", "المشتريات", "outline"),
            ("التقارير", "التقارير", "outline"),
        ]
        for text, page_name, variant in actions:
            btn = create_quick_action_button(
                text,
                on_click=(lambda _, n=page_name: self._navigate(n)),
                variant=variant,
            )
            row.addWidget(btn)
        return row

    def _navigate(self, page_name, filter_status=None):
        if self.on_navigate:
            self.on_navigate(page_name, filter_status)

    def _sales_qty_map(self, months_back=6):
        """يرجّع {product_id: مجموع الكمية المباعة} خلال آخر عدد أشهر معطى -
        نفس الاستعلام المستخدم بشاشة التقارير، مكرر هنا عشان الرئيسية تقدر
        ترتب تنبيهاتها بنفس المنطق (الأدوية الأكثر طلبًا فعليًا أولاً) بدون
        اعتماد بين الشاشتين."""
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

    def _view_all_row(self, count, filter_status):
        wrap = QFrame()
        wrap.setStyleSheet("background:transparent;border:none;")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 4, 0, 0)
        row.addStretch()
        btn = QPushButton(f"عرض الكل ({count}) بالمخزون")
        btn.setStyleSheet(
            f"background:{COLOR_SURFACE_SUBTLE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_BUTTON}px;padding:6px 14px;color:{COLOR_TEXT_PRIMARY};font-weight:{FONT_BODY_STRONG[1]};"
        )
        btn.clicked.connect(lambda: self._navigate("المخزون", filter_status))
        row.addWidget(btn)
        return wrap

    def _build_daily_income_card(self):
        """بطاقة بارزة أعلى الصفحة تعرض الوارد اليومي (إجمالي فواتير اليوم
        الحالي) - القيمة نفسها تُحسب وتتحدث ضمن _render_finance_summary
        بنفس منطق حساب الواردات الشهرية بالضبط، بس مُقيّد على اليوم الحالي."""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"border-radius:{RADIUS_CARD + 4}px;}}"
        )
        add_shadow(frame, blur=SHADOW_MEDIUM["blur"], color=TEAL_700,
                   alpha=SHADOW_MEDIUM["alpha"], y_offset=SHADOW_MEDIUM["y_offset"])
        row = QHBoxLayout(frame)
        row.setContentsMargins(SPACE_24, SPACE_20, SPACE_24, SPACE_20)
        row.setSpacing(SPACE_16)

        icon_box = QLabel()
        icon_box.setFixedSize(48, 48)
        icon_box.setAlignment(Qt.AlignCenter)
        icon_box.setStyleSheet("background:rgba(255,255,255,0.18);border-radius:12px;")
        icon_box.setPixmap(icon("cash", color="white", size=24).pixmap(24, 24))
        row.addWidget(icon_box)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.daily_income_value_lbl = QLabel("٠ د.ع")
        self.daily_income_value_lbl.setStyleSheet(
            f"color:white;font-size:26px;font-weight:800;background:transparent;border:none;"
        )
        text_col.addWidget(self.daily_income_value_lbl)
        caption = QLabel("الوارد اليومي")
        caption.setStyleSheet(
            "color:rgba(255,255,255,0.85);font-size:13px;font-weight:700;background:transparent;border:none;"
        )
        text_col.addWidget(caption)
        row.addLayout(text_col)
        row.addStretch()
        return frame

    def _render_finance_summary(self):
        try:
            today = date.today()
            month_start = datetime(today.year, today.month, 1)
            month_end = datetime.combine(today, datetime.max.time())

            invoices = (
                self.session.query(Invoice)
                .options(joinedload(Invoice.items))
                .filter(Invoice.invoice_date >= month_start, Invoice.invoice_date <= month_end)
                .all()
            )
            revenue = sum(inv.final_amount for inv in invoices)

            # الوارد اليومي: نفس منطق الواردات الشهرية بالضبط، بس مُقيّد على
            # فواتير اليوم الحالي فقط (بدون خصم السحوبات - رقم إجمالي خام).
            today_start = datetime.combine(today, datetime.min.time())
            daily_invoices = [inv for inv in invoices if inv.invoice_date and inv.invoice_date >= today_start]
            daily_revenue = sum(inv.final_amount for inv in daily_invoices)
            if hasattr(self, "daily_income_value_lbl"):
                self.daily_income_value_lbl.setText(fmt_money(daily_revenue))

            # كان يفتح استعلام Batch واستعلام ProductUnit منفصلين لكل بند فاتورة
            # (N+1 يتضاعف مع عدد المبيعات بالشهر) - نجيبهم كلهم دفعة وحدة بنداءين
            # فقط عبر IN(...) بدل نداء لكل بند، ونفس حساب الربح بالضبط بدون تغيير.
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

            profit = 0
            for inv in invoices:
                is_return = inv.payment_status == "مرتجع"
                for item in inv.items:
                    batch = batches_by_id.get(item.batch_id)
                    unit = units_by_id.get(item.unit_id) if item.unit_id else None
                    if item.unit_cost:
                        cost = item.unit_cost * item.quantity
                    else:
                        # فواتير قديمة من قبل إضافة unit_cost - تقدير احتياطي بنفس الطريقة السابقة
                        cost = (batch.purchase_price or 0) * (unit.conversion_factor if unit else 1) * item.quantity if batch else 0
                    profit += (item.subtotal + cost) if is_return else (item.subtotal - cost)
                # نفس إصلاح التقارير بالضبط: الخصم بمستوى الفاتورة كاملة لازم
                # ينطرح من الربح عند البيع، وينضاف (يُعاكَس) عند الإرجاع - وإلا
                # صافي الربح المعروض هنا يطلع مبالغ فيه (ما يحسب الخصومات
                # اللي انعطت فعليًا للزباين)، ويختلف عن الرقم الصحيح بالتقارير.
                if not is_return:
                    profit -= (inv.discount or 0)
                else:
                    profit += (inv.discount or 0)

            expenses = (
                self.session.query(Expense)
                .filter(Expense.date >= month_start.date(), Expense.date <= today)
                .all()
            )
            withdrawals = sum(e.amount for e in expenses)

            values = [
                (fmt_money(revenue - withdrawals), "الواردات (بعد السحوبات)"),
                (fmt_money(profit - withdrawals), "الأرباح (بعد السحوبات)"),
                (fmt_money(withdrawals), "الاستقطاعات الشهرية"),
            ]
            for card, (number, label) in zip(self._finance_cards, values):
                card.update_values(number, label)
                card.setVisible(True)
            if self._finance_error_frame is not None:
                self._finance_error_frame.setVisible(False)
        except Exception as e:
            for card in self._finance_cards:
                card.setVisible(False)
            if self._finance_error_frame is None:
                err_wrap = QFrame()
                err_wrap.setStyleSheet("background:transparent;border:none;")
                err_row = QHBoxLayout(err_wrap)
                err_row.setContentsMargins(0, 0, 0, 0)
                err_row.setSpacing(SPACE_8)
                err_icon_lbl = QLabel()
                err_icon_lbl.setStyleSheet("background:transparent;border:none;")
                err_icon_lbl.setPixmap(icon("warning", color=RED_500, size=15).pixmap(15, 15))
                err_row.addWidget(err_icon_lbl)
                self._finance_error_text = QLabel()
                self._finance_error_text.setStyleSheet(f"color:{RED_500};background:transparent;border:none;")
                err_row.addWidget(self._finance_error_text)
                err_row.addStretch()
                self._finance_error_frame = err_wrap
                self.finance_row.addWidget(err_wrap, 0, 0, 1, 4)
            self._finance_error_text.setText(f"صار خطأ بحساب الملخص المالي: {e}")
            self._finance_error_frame.setVisible(True)

    def _stat_card(self, number, label, color):
        # يعيد استخدام مكوّن البطاقة الموحّد بدل ما يبني ستايل خاص به هنا -
        # نفس التوقيع (number, label, color) بالضبط عشان كل الاستدعاءات
        # الحالية تستمر تشتغل بدون أي تعديل.
        frame = create_stat_card(number, label, color)
        return frame

    def _populate_grid(self, grid, items, col_count=3):
        """يوزّع البطاقات على شبكة بعدد أعمدة ثابت (مو حسب عرض النافذة).

        ملاحظة إصلاح مهمة: كان عدد الأعمدة يُحسب ديناميكيًا حسب عرض النافذة
        عبر resizeEvent - وهذي كانت الصفحة الوحيدة بالبرنامج اللي عندها هذي
        الآلية. المشكلة: أثناء تبديل الصفحات (QStackedWidget)، عرض الصفحة
        المقروء أحيانًا ما يكون العرض الحقيقي النهائي بعد (الصفحة لسا مو
        ظاهرة فعليًا)، فيصير حساب خاطئ لعدد الأعمدة يليه تصحيح فوري لما
        تظهر الصفحة فعليًا - وهذا التصحيح المفاجئ هو "ومضة" الواجهة اللي
        تصير بالضبط بالرئيسية بس (الصفحة الوحيدة المعتمدة على العرض).
        الحل: عدد أعمدة ثابت دائمًا، بدون أي اعتماد على قياس العرض - يلغي
        احتمال هذا الخلل بالكامل من جذوره، مو بس تخفيفه."""
        if not items:
            return
        for col in range(col_count):
            grid.setColumnStretch(col, 1)
        for index, widget in enumerate(items):
            grid.addWidget(widget, index // col_count, index % col_count)

    def _filter_alerts_by_age(self, alert_type, items, get_product_id, today, window_days=7):
        """يفلتر قائمة تنبيهات حسب أول ظهور مسجّل لكل عنصر - أول ظهور
        لعنصر جديد يسجَّل تلقائيًا ويبين فورًا، وأي عنصر عدى عليه أكثر من
        أسبوع من أول ظهور له يُستبعد من العرض (حتى لو الشرط الأساسي -
        نقص المخزون مثلاً - لسا مستمر)، عشان التنبيهات ما تتراكم بلا نهاية.
        لو الحالة انصلحت (العنصر ماعاد موجود بالقائمة الحالية)، نحذف
        تسجيله القديم - فلو رجعت المشكلة لاحقًا تُحتسب تنبيه جديد بنافذة
        أسبوع جديدة من الصفر."""
        current_ids = {get_product_id(item) for item in items}
        existing = self.session.query(AlertOccurrence).filter_by(alert_type=alert_type).all()
        existing_by_pid = {occ.product_id: occ for occ in existing}

        stale_ids = set(existing_by_pid) - current_ids
        for pid in stale_ids:
            self.session.delete(existing_by_pid[pid])

        kept = []
        for item in items:
            pid = get_product_id(item)
            occ = existing_by_pid.get(pid)
            if occ is None:
                self.session.add(AlertOccurrence(alert_type=alert_type, product_id=pid, first_seen=today))
                kept.append(item)  # تنبيه جديد - يبين فورًا
            elif (today - occ.first_seen).days < window_days:
                kept.append(item)
            # وإلا (عدى عليه أسبوع): يُستبعد من العرض، بس سجله يبقى بقاعدة
            # البيانات (ما نحذفه) عشان ما يرجع يبين من جديد بالغلط طالما
            # نفس الحالة مستمرة - يتنظف تلقائيًا بس لما تنحل الحالة فعليًا.
        self.session.commit()
        return kept

    def refresh(self):
        # ملاحظة: بطاقات ملخص الشهر/رأس المال/التنبيهات صارت ثابتة (تنبني مرة
        # وحدة بـ __init__) وتُحدَّث بمكانها بالأسفل - ما نحذفها/نبنيها من جديد
        # هنا بعد. تفاصيل التنبيهات (القائمة بالأسفل) لسا متغيّرة الحجم حسب
        # البيانات فعليًا، فهذي وحدها لسا تنحذف وتنبنى من جديد كل refresh.
        while self.list_layout.count():
            child = self.list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self._render_finance_summary()

        today = date.today()
        expiry_alert_days = get_expiry_alert_days(self.session)
        near_expiry_cutoff = today + timedelta(days=expiry_alert_days)

        # ملاحظة أداء جذرية: كان الكود يجيب كل الأدوية النشطة ككائنات كاملة
        # (مع كل دفعاتها - joinedload batches) لحساب الحالة والمجاميع
        # بالذاكرة ببايثون - مع كتالوج كبير (آلاف الأدوية)، هذا يعني تحميل
        # كل شي لبايثون كل مرة تفتح الرئيسية. الحين قاعدة البيانات نفسها
        # تسوي التجميع (GROUP BY) عبر 3 استعلامات خفيفة، وبايثون يصنّف بس
        # (مقارنات ودمج قواميس - رخيص جدًا)، مو يعيد جمع أرقام دفعات آلاف
        # الأدوية يدويًا.

        # إجمالي المخزون لكل دواء (بدون أي فلترة) - يحدد ناقص/منخفض
        total_stock_by_product = {
            pid: qty or 0 for pid, qty in
            self.session.query(Batch.product_id, func.sum(Batch.quantity_available))
            .group_by(Batch.product_id).all()
        }

        # رأس المال + المخزون الموجب (دفعات فيها كمية فعلية بس، نفس شرط
        # الكود القديم بالضبط) - نداء واحد للاثنين مع بعض
        positive_stock_by_product = {}
        capital_by_product = {}
        for pid, pos_qty, cap in (
            self.session.query(
                Batch.product_id,
                func.sum(Batch.quantity_available),
                func.sum(Batch.purchase_price * Batch.quantity_available),
            )
            .filter(Batch.quantity_available > 0)
            .group_by(Batch.product_id).all()
        ):
            positive_stock_by_product[pid] = pos_qty or 0
            capital_by_product[pid] = cap or 0

        # أقرب تاريخ انتهاء لكل دواء (دفعات فيها كمية فعلية + تاريخ انتهاء
        # محدد) - يستفيد من فهرسة Batch.expiry_date المضافة سابقًا
        nearest_expiry_by_product = {
            pid: exp for pid, exp in
            self.session.query(Batch.product_id, func.min(Batch.expiry_date))
            .filter(Batch.quantity_available > 0, Batch.expiry_date.isnot(None))
            .group_by(Batch.product_id).all()
        }

        # استعلام خفيف بس (3 أعمدة، بدون جلب الدفعات) - هذا الفرق الجوهري:
        # قبل كنا نجيب كائن Product كامل مع كل دفعاته لكل دواء، الحين نجيب
        # بس id/name/سعر البيع/الحد الأدنى - وباقي الحساب جاهز من القواميس
        # أعلاه.
        products_light_query = (
            self.session.query(Product.id, Product.name, Product.sale_price, Product.min_stock_threshold)
            .filter(Product.is_active == True)
        )
        # لو إعداد "الاعتماد على الأدوية المعتمدة" مفعّل بالإعدادات، نقصر
        # التنبيهات (نقص/منخفض/منتهي/قرب الانتهاء) على الأدوية المعتمدة بس -
        # راجع app/db/approved_helper.py.
        if is_approved_filter_enabled(self.session):
            products_light_query = products_light_query.filter(approved_clause(self.session))
        products_light = products_light_query.all()

        out_of_stock, low_stock, near_expiry, expired = [], [], [], []
        capital = 0.0
        expected_sale_value = 0.0

        for pid, name, sale_price, min_threshold in products_light:
            stock = total_stock_by_product.get(pid, 0)
            threshold = min_threshold or 10
            pos_stock = positive_stock_by_product.get(pid, 0)
            capital += capital_by_product.get(pid, 0)
            expected_sale_value += (sale_price or 0) * pos_stock

            if stock <= 0:
                out_of_stock.append(SimpleNamespace(id=pid, name=name, stock=stock))
            elif stock <= threshold:
                low_stock.append(SimpleNamespace(id=pid, name=name, stock=stock))

            nearest = nearest_expiry_by_product.get(pid)
            if nearest:
                if nearest < today:
                    expired.append((SimpleNamespace(id=pid, name=name), nearest))
                elif nearest <= near_expiry_cutoff:
                    near_expiry.append((SimpleNamespace(id=pid, name=name), nearest))

        expected_profit = expected_sale_value - capital
        margin_pct = (expected_profit / expected_sale_value * 100) if expected_sale_value else 0

        # فلترة التنبيهات حسب عمرها (أسبوع كحد أقصى) - تطبّق قبل حساب
        # بطاقات الملخص والقائمة التفصيلية بالأسفل عشان الاثنين يتطابقون
        # (نفس العدد المعروض بالبطاقة ونفس العناصر بالقائمة).
        out_of_stock = self._filter_alerts_by_age("out_of_stock", out_of_stock, lambda p: p.id, today)
        low_stock = self._filter_alerts_by_age("low_stock", low_stock, lambda p: p.id, today)
        expired = self._filter_alerts_by_age("expired", expired, lambda t: t[0].id, today)
        near_expiry = self._filter_alerts_by_age("near_expiry", near_expiry, lambda t: t[0].id, today)

        capital_values = [
            (fmt_money(capital), "رأس المال (تكلفة الشراء)"),
            (fmt_money(expected_sale_value), "قيمة البيع المتوقعة"),
            (fmt_money(expected_profit), f"الربح المتوقع - هامش {margin_pct:.1f}%"),
        ]
        for card, (number, label) in zip(self._capital_cards, capital_values):
            card.update_values(number, label)

        summary_values = [
            (len(out_of_stock), "أدوية نافذة"),
            (len(low_stock), "مخزون منخفض"),
            (len(expired), "منتهية الصلاحية"),
            (len(near_expiry), "قرب انتهاء الصلاحية"),
        ]
        for card, (number, label) in zip(self._summary_cards, summary_values):
            card.update_values(number, label)

        if not out_of_stock and not low_stock and not near_expiry and not expired:
            ok_wrap = QFrame()
            ok_wrap.setStyleSheet("background:transparent;border:none;")
            ok_row = QHBoxLayout(ok_wrap)
            ok_row.setContentsMargins(0, SPACE_20, 0, SPACE_20)
            ok_row.setSpacing(SPACE_8)
            ok_row.addStretch()
            ok_icon_lbl = QLabel()
            ok_icon_lbl.setStyleSheet("background:transparent;border:none;")
            ok_icon_lbl.setPixmap(icon("check", color=TEAL_500, size=16).pixmap(16, 16))
            ok_row.addWidget(ok_icon_lbl)
            ok_lbl = QLabel("ماكو تنبيهات حاليًا - كل شي زين بالمخزون.")
            ok_lbl.setStyleSheet(
                f"color:{TEAL_500};font-weight:{FONT_BODY_STRONG[1]};"
                f"background:transparent;border:none;"
            )
            ok_row.addWidget(ok_lbl)
            ok_row.addStretch()
            self.list_layout.addWidget(ok_wrap)
            return

        sales_map = self._sales_qty_map(months_back=6)
        LIMIT = 10

        if out_of_stock:
            out_of_stock.sort(key=lambda p: -sales_map.get(p.id, 0))
            total = len(out_of_stock)
            rows = [self._alert_row(p.name, "الكمية: 0", RED_500) for p in out_of_stock[:LIMIT]]
            if total > LIMIT:
                rows.append(self._view_all_row(total, "نقص"))
            self.list_layout.addWidget(self._build_collapsible_section("نافذة من المخزون", RED_500, rows, total_count=total))

        if expired:
            expired.sort(key=lambda x: (-sales_map.get(x[0].id, 0), x[1]))
            total = len(expired)
            rows = []
            for p, exp_date in expired[:LIMIT]:
                days_ago = (today - exp_date).days
                rows.append(self._alert_row(p.name, f"انتهت من {days_ago} يوم ({exp_date.isoformat()})", RED_500))
            if total > LIMIT:
                rows.append(self._view_all_row(total, "منتهي"))
            self.list_layout.addWidget(self._build_collapsible_section("منتهية الصلاحية بالفعل", RED_500, rows, total_count=total))

        if low_stock:
            low_stock.sort(key=lambda p: (-sales_map.get(p.id, 0), p.stock))
            total = len(low_stock)
            rows = []
            for p in low_stock[:LIMIT]:
                rows.append(self._alert_row(p.name, f"الكمية المتبقية: {p.stock}", AMBER_500))
            if total > LIMIT:
                rows.append(self._view_all_row(total, "منخفض"))
            self.list_layout.addWidget(self._build_collapsible_section("مخزون منخفض (10 أو أقل)", AMBER_500, rows, total_count=total))

        if near_expiry:
            near_expiry.sort(key=lambda x: (-sales_map.get(x[0].id, 0), x[1]))
            total = len(near_expiry)
            rows = []
            for p, exp_date in near_expiry[:LIMIT]:
                days_left = (exp_date - today).days
                rows.append(self._alert_row(p.name, f"تنتهي بعد {days_left} يوم ({exp_date.isoformat()})", AMBER_500))
            if total > LIMIT:
                rows.append(self._view_all_row(total, "قريب الانتهاء"))
            self.list_layout.addWidget(self._build_collapsible_section(f"قرب انتهاء الصلاحية (خلال {expiry_alert_days} يوم)", AMBER_500, rows, total_count=total))

    def _section_title(self, text, icon_name=None, icon_color=None):
        # يعيد استخدام مكوّن عنوان القسم الموحّد - صار يدعم تمرير أيقونة من
        # icon_manager بدل الإيموجي القديم بالنص.
        return create_section_title(text, icon_name=icon_name, icon_color=icon_color)

    def _build_collapsible_section(self, title, icon_color, row_widgets, expanded=True, total_count=None):
        """قسم قابل للطي: الضغط بأي مكان على شريط العنوان كامل (مو بس على
        زر صغير منفصل) يفتح أو يطوي محتوى القسم. البيانات المعروضة (row_widgets)
        نفسها محسوبة مسبقًا بنفس منطق refresh() القديم بالضبط - هذا التابع
        بصري بحت، بس يلمّ الصفوف داخل حاوية قابلة للإخفاء.
        total_count: العدد الحقيقي الكامل (قبل أي اقتصاص لأول 10 عناصر) -
        يُعرض بعنوان القسم حتى لو row_widgets نفسها أقل (لأنها مقتصرة + فيها
        صف "عرض الكل" إضافي). لو ما انمرر، نستخدم len(row_widgets) زي القديم."""
        container = QFrame()
        container.setStyleSheet("background:transparent;border:none;")
        outer_v = QVBoxLayout(container)
        outer_v.setContentsMargins(0, 0, 0, 0)
        outer_v.setSpacing(SPACE_8)

        display_count = total_count if total_count is not None else len(row_widgets)
        header_btn = QPushButton(f"  {title} ({display_count})")
        header_btn.setIcon(icon("dot", color=icon_color, size=14))
        header_btn.setCheckable(True)
        header_btn.setChecked(expanded)
        header_btn.setCursor(Qt.PointingHandCursor)
        header_btn.setLayoutDirection(Qt.RightToLeft)
        header_btn.setStyleSheet(
            f"QPushButton{{background:{COLOR_SURFACE_SUBTLE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_BUTTON}px;padding:{SPACE_8}px {SPACE_12}px;text-align:right;"
            f"font-weight:{FONT_BODY_STRONG[1]};color:{COLOR_TEXT_PRIMARY};}}"
            f"QPushButton:hover{{background:{COLOR_BORDER};}}"
        )
        outer_v.addWidget(header_btn)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(SPACE_8)
        for w in row_widgets:
            body_layout.addWidget(w)
        # ---- إصلاح النافذة السريعة اللي تفتح وتختفي ----
        # كان السطر التالي (setVisible) ينفّذ قبل ما ينضاف body لأي تخطيط،
        # يعني بلا أب - و widget بدون أب لما تناديله setVisible(True)، Qt
        # يعتبره نافذة مستقلة كاملة بنظام التشغيل تنفتح فعليًا على الشاشة
        # (لهذا كان حجمها يطلع ضخم وغريب متل 777x6934 بالسجل التشخيصي) قبل
        # ما ينضاف للتخطيط ويرجع widget عادي مدمج بالصفحة. الحل: نضيفه
        # لتخطيط القسم outer_v أولًا (يصير عنده أب)، وبعدها بس نطبّق
        # setVisible - فما يقدر يصير نافذة مستقلة إطلاقًا بأي لحظة.
        outer_v.addWidget(body)
        body.setVisible(expanded)

        header_btn.clicked.connect(lambda checked: body.setVisible(checked))
        return container

    def _alert_row(self, name, detail, color=COLOR_TEXT_SECONDARY):
        # خلفيات فاتحة جاهزة حسب لون الخطورة (أحمر=حرج، برتقالي=تحذير) -
        # نفس منطق الاختيار السابق بالضبط، بس القيم الآن من app.ui.theme
        # بدل تكرار الهكس يدويًا.
        if color == RED_500:
            bg, border = COLOR_DANGER_BG, COLOR_DANGER_BORDER
        elif color == AMBER_500:
            bg, border = COLOR_WARNING_BG, COLOR_WARNING_BORDER
        else:
            bg, border = COLOR_SURFACE_SUBTLE, COLOR_BORDER
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame{{background:{bg};border:1px solid {border};"
            f"border-radius:{RADIUS_BUTTON}px;padding:{SPACE_8}px {SPACE_12}px;}}"
        )
        h = QHBoxLayout(frame)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("background:transparent;border:none;")
        h.addWidget(name_lbl)
        h.addStretch()
        detail_lbl = QLabel(detail)
        detail_lbl.setStyleSheet(
            f"color:{color};font-weight:{FONT_BODY_STRONG[1]};background:transparent;border:none;"
        )
        h.addWidget(detail_lbl)
        return frame
