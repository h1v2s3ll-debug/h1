"""
شاشة البيع (POS).

تحديث (H1 Design System / Task: إعادة تصميم شاشة البيع - نسخة 2): إعادة
بناء بصرية كاملة لتطابق مواصفة التصميم المرفقة (بطاقات منتج مضغوطة حديثة،
شريط بحث/باركود ونصف تصنيفات كـ chips بدل القائمة المنسدلة، صفوف فاتورة
مدمجة بعمود واحد، لوحة إجمالي ودفع بارزة، وأيقونات موحّدة بدل الإيموجي).

**ولا سطر واحد من منطق قاعدة البيانات أو الحسابات أو سحب المخزون أو الطباعة
تغيّر** - كل الاستعلامات، التحقق من المخزون، حساب السعر/الربح، وبناء
الفاتورة نفسها بالضبط زي قبل. التغيير هنا بصري بحت + تبديل عنصر التحكم
بالتصنيف من QComboBox إلى شرائح (chips) قابلة للنقر، مع الحفاظ على نفس
شرط الفلترة بالضبط (مطابقة اسم التصنيف).

ملاحظة نطاق: هذا الملف فقط. الشريط العلوي والقائمة الجانبية (H1، الإشعارات،
التاريخ...) جزء من MainWindow المشترك بين كل الشاشات ولم يُمسّ إطلاقًا.
"""
from datetime import datetime
import re
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy import func
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox, QSizePolicy,
    QDialog, QListWidget, QListWidgetItem, QApplication,
)
from PySide6.QtCore import Qt, QSize, QTimer, QEvent
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from app.db.database import get_session
from app.db.models import (
    Product, ProductUnit, Batch, ProductAlternative, Invoice, InvoiceItem,
    Payment, StockMovement, DrugInteraction, Customer,
)
from app.db.settings_helper import get_setting
from app.ui.widgets import (
    NumberLineEdit, add_shadow, toggle_chip_stylesheet, enable_touch_scroll,
)
from app.ui.icons import icon
from app.ui.theme import (
    TEAL_400, TEAL_500, TEAL_600, TEAL_700, TEAL_50, RED_500,
    COLOR_SURFACE, COLOR_SURFACE_SUBTLE, COLOR_BORDER,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY,
    COLOR_SUCCESS_TEXT, COLOR_WARNING_TEXT,
    COLOR_DANGER_BG, COLOR_DANGER_BORDER, COLOR_DANGER_TEXT,
    FONT_H2, FONT_H3, FONT_BODY, FONT_BODY_STRONG, FONT_CAPTION, FONT_LABEL,
    SPACE_4, SPACE_8, SPACE_12, SPACE_16, SPACE_20,
    RADIUS_BUTTON, RADIUS_CARD, RADIUS_PILL, RADIUS_INPUT,
    SHADOW_MEDIUM, SHADOW_LARGE,
)


def normalize_arabic(text):
    """يوحّد أشكال الألف والهمزة والتاء المربوطة عشان البحث ما يفشل بسبب اختلاف الكتابة."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"[ًٌٍَُِّْ]", "", text)  # إزالة التشكيل
    return text.lower()


def fmt_money(n):
    return f"{n:,.0f} د.ع"


def unit_sale_price(product, unit):
    """
    سعر البيع الصحيح للوحدة المختارة.
    مهم: ما نحسبه بضرب سعر الشريط × معامل التحويل (هذا كان يعطي دائمًا 10 أضعاف
    سعر الشريط للعلبة بغض النظر عن سعر العلبة الحقيقي اللي أدخله المستخدم).
    اللي نسويه هنا: لو الوحدة هي الوحدة الأساس (شريط، معامل=1) نرجع سعر الشريط،
    ولو وحدة أكبر (علبة/كرتون) نرجع سعر الكرتون المُدخل فعليًا بالمخزون.
    """
    if unit is None or unit.conversion_factor == 1:
        return product.sale_price or 0
    return product.carton_price or 0


def unit_purchase_cost(product, unit):
    """
    تكلفة الشراء الحالية للوحدة المختارة - تُستخدم وقت الإرجاع لتقدير هامش
    الربح المُرتجَع، بالاعتماد على متوسط سعر شراء الشريط بالدفعات المتوفرة
    حاليًا (أدق تقدير متاح لأن الإرجاع ما يرتبط بفاتورة بيع أصلية محددة).
    """
    factor = unit.conversion_factor if unit else 1
    batches = [b for b in product.batches if b.quantity_available > 0]
    if batches:
        total_qty = sum(b.quantity_available for b in batches)
        avg_strip_cost = sum((b.purchase_price or 0) * b.quantity_available for b in batches) / total_qty
    elif product.batches:
        avg_strip_cost = sum(b.purchase_price or 0 for b in product.batches) / len(product.batches)
    elif product.carton_purchase_price and product.strips_per_carton:
        avg_strip_cost = product.carton_purchase_price / product.strips_per_carton
    else:
        avg_strip_cost = 0
    return avg_strip_cost * factor


def _icon_button(icon_name, size=32, icon_size=17, color=COLOR_TEXT_PRIMARY,
                  bg="transparent", border="none", hover_bg=COLOR_SURFACE_SUBTLE,
                  radius=None):
    """زر دائري/مربّع بأيقونة موحّدة بس (بدون نص) - يُستخدم بكثرة بالتصميم
    الجديد بدل أزرار النص/الإيموجي القديمة (حذف صنف، تصغير/تكبير الكمية...).
    ملاحظة: لازم نضبط setIconSize صراحة، لأن QPushButton بدونها يعرض أي
    أيقونة مررناها بحجم افتراضي صغير من الـ style بغض النظر عن حجم الـ
    pixmap الفعلي - وهذا سبب ظهور الأيقونات أصغر من المطلوب رغم تمرير size."""
    radius = radius if radius is not None else size // 2
    btn = QPushButton()
    btn.setIcon(icon(icon_name, color=color, size=icon_size))
    btn.setIconSize(QSize(icon_size, icon_size))
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton{{background:{bg};border:{border};border-radius:{radius}px;padding:0;}}"
        f"QPushButton:hover{{background:{hover_bg};}}"
    )
    return btn


class ProductCard(QFrame):
    def __init__(self, product, units, on_add, on_show_alt, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("class", "Card")
        self.product = product
        self.units = units
        self.selected_unit = units[0] if units else None
        self.on_add = on_add
        self.on_show_alt = on_show_alt

        self.setMinimumWidth(280)
        self.setMinimumHeight(176)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            f"QFrame#Card{{background:{COLOR_SURFACE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_CARD}px;}}"
            f"QFrame#Card:hover{{border:1.5px solid {TEAL_400};}}"
        )
        add_shadow(self, blur=SHADOW_MEDIUM["blur"], color=TEAL_700,
                   alpha=SHADOW_MEDIUM["alpha"], y_offset=SHADOW_MEDIUM["y_offset"])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_16, SPACE_12, SPACE_16, SPACE_12)
        layout.setSpacing(SPACE_8)

        # ---- اسم الدواء (العنصر الأهم بالبطاقة) + السعر (عنصر ثانوي) ----
        top = QHBoxLayout()
        top.setSpacing(SPACE_8)
        name_lbl = QLabel(product.name)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            f"background:transparent;border:none;font-weight:800;"
            f"font-size:15px;color:{COLOR_TEXT_PRIMARY};"
        )
        name_lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.price_lbl = QLabel("")
        self.price_lbl.setAlignment(Qt.AlignTop)
        self.price_lbl.setStyleSheet(
            f"background:transparent;border:none;color:{TEAL_700};"
            f"font-weight:800;font-size:14px;"
        )
        top.addWidget(name_lbl, stretch=1)
        top.addWidget(self.price_lbl, alignment=Qt.AlignTop)
        layout.addLayout(top)

        # ---- سطر معلومات مختصر: المخزون (+ التصنيف إن وُجد) ----
        meta_row = QHBoxLayout()
        meta_row.setSpacing(SPACE_8)
        stock_color, stock_text = self._stock_display(product)
        self.stock_lbl = QLabel(stock_text)
        self.stock_lbl.setStyleSheet(
            f"background:transparent;border:none;color:{stock_color};"
            f"font-size:{FONT_CAPTION[0]}px;font-weight:{FONT_CAPTION[1]};"
        )
        meta_row.addWidget(self.stock_lbl)
        meta_row.addStretch()
        if product.category:
            cat_lbl = QLabel(product.category)
            cat_lbl.setStyleSheet(
                f"background:transparent;border:none;color:{COLOR_TEXT_SECONDARY};"
                f"font-size:{FONT_CAPTION[0]}px;font-weight:600;"
            )
            meta_row.addWidget(cat_lbl)
        layout.addLayout(meta_row)

        layout.addStretch()

        # ---- اختيار وحدة القياس (شرائح Segmented مضغوطة) ----
        self.unit_buttons = []
        if len(self.units) > 1:
            unit_row = QHBoxLayout()
            unit_row.setSpacing(SPACE_4)
            for u in self.units:
                btn = QPushButton(u.unit_name)
                btn.setCheckable(True)
                btn.setChecked(u is self.selected_unit)
                btn.setMinimumHeight(34)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                btn.setStyleSheet(self._unit_btn_style(u is self.selected_unit) + "font-size:12px;padding:2px 6px;")
                btn.clicked.connect(lambda _, uu=u: self._select_unit(uu))
                unit_row.addWidget(btn)
                self.unit_buttons.append(btn)
            layout.addLayout(unit_row)

        # ---- سطر الإجراءات: زر بدائل (يظهر دائمًا، أصغر) + زر إضافة كبير رئيسي ----
        actions = QHBoxLayout()
        actions.setSpacing(SPACE_8)

        has_alt = len(product.alt_ids) > 0 if hasattr(product, "alt_ids") else False
        alt_btn = QPushButton()
        alt_btn.setObjectName("AltButton")
        alt_btn.setText("  بدائل")
        alt_btn.setMinimumHeight(42)
        alt_btn.setCursor(Qt.PointingHandCursor)
        # الزر يظهر ويشتغل دائمًا لكل المنتجات: لو فيه بدائل مسجلة يفتح نافذة
        # عرض/تعديل (حذف)، ولو ماكو بدائل يفتح نفس النافذة بس بوضع "إضافة بديل
        # جديد" مباشرة - ما نعطّل الزر بأي حالة.
        if has_alt:
            alt_btn.setIcon(icon("swap", color=TEAL_700, size=18))
            alt_btn.setIconSize(QSize(18, 18))
            alt_btn.setToolTip("عرض/تعديل البدائل")
            alt_btn.setStyleSheet(
                f"QPushButton{{background:{COLOR_SURFACE_SUBTLE};color:{TEAL_700};"
                f"border:1px solid {COLOR_BORDER};border-radius:{RADIUS_BUTTON}px;"
                f"padding:6px 10px;font-size:12px;font-weight:700;}}"
                f"QPushButton:hover{{background:{TEAL_50};}}"
            )
        else:
            alt_btn.setIcon(icon("swap", color=COLOR_TEXT_SECONDARY, size=18))
            alt_btn.setIconSize(QSize(18, 18))
            alt_btn.setToolTip("إضافة بديل لهذا الدواء")
            alt_btn.setStyleSheet(
                f"QPushButton{{background:{COLOR_SURFACE_SUBTLE};color:{COLOR_TEXT_SECONDARY};"
                f"border:1px solid {COLOR_BORDER};border-radius:{RADIUS_BUTTON}px;"
                f"padding:6px 10px;font-size:12px;font-weight:700;}}"
                f"QPushButton:hover{{background:{COLOR_BORDER};}}"
            )
        alt_btn.clicked.connect(lambda: self.on_show_alt(self.product))
        actions.addWidget(alt_btn)
        self.alt_btn = alt_btn

        add_btn = QPushButton()
        add_btn.setObjectName("AddButton")
        add_btn.setIcon(icon("cart", color="white", size=22))
        add_btn.setIconSize(QSize(22, 22))
        add_btn.setText("  أضف")
        add_btn.setMinimumHeight(46)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        add_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:{RADIUS_BUTTON}px;padding:8px 16px;font-size:14px;"
            f"font-weight:800;border:none;text-align:center;}}"
            f"QPushButton:hover{{background:{TEAL_500};}}"
        )
        add_btn.clicked.connect(lambda: self.on_add(self.product, self.selected_unit))
        actions.addWidget(add_btn, stretch=1)
        layout.addLayout(actions)

        self._update_price()

    def _unit_btn_style(self, selected):
        # يعيد استخدام ستايل الـ chip الموحّد بدل تكرار التدرّج اللوني هنا.
        return toggle_chip_stylesheet(selected)

    def _select_unit(self, unit):
        self.selected_unit = unit
        for btn in self.unit_buttons:
            btn.setChecked(btn.text() == unit.unit_name)
            btn.setStyleSheet(self._unit_btn_style(btn.text() == unit.unit_name) + "font-size:12px;padding:2px 6px;")
        self._update_price()

    def _update_price(self):
        self.price_lbl.setText(fmt_money(unit_sale_price(self.product, self.selected_unit)))

    @staticmethod
    def _stock_display(product):
        stock = sum(b.quantity_available for b in product.batches)
        threshold = product.min_stock_threshold or 10
        if stock <= 0:
            return COLOR_DANGER_TEXT, "نفذ المخزون"
        elif stock <= threshold:
            return COLOR_WARNING_TEXT, f"متبقي {stock}"
        return COLOR_SUCCESS_TEXT, f"المخزون: {stock}"

    def refresh_alt_button(self, has_alt):
        """يحدّث مظهر زر 'بدائل' بس (بدون لمس باقي البطاقة) - يُستخدم بعد
        إغلاق نافذة إدارة البدائل لو صار تغيير فعلي، بدل إعادة بناء شبكة
        المنتجات كاملة (اللي كانت تسبب ومضة/بياض مؤقت بكل مرة تفتح وتسكر
        النافذة حتى لو ما صار أي تعديل)."""
        if has_alt:
            self.alt_btn.setIcon(icon("swap", color=TEAL_700, size=18))
            self.alt_btn.setIconSize(QSize(18, 18))
            self.alt_btn.setToolTip("عرض/تعديل البدائل")
            self.alt_btn.setStyleSheet(
                f"QPushButton{{background:{COLOR_SURFACE_SUBTLE};color:{TEAL_700};"
                f"border:1px solid {COLOR_BORDER};border-radius:{RADIUS_BUTTON}px;"
                f"padding:6px 10px;font-size:12px;font-weight:700;}}"
                f"QPushButton:hover{{background:{TEAL_50};}}"
            )
        else:
            self.alt_btn.setIcon(icon("swap", color=COLOR_TEXT_SECONDARY, size=18))
            self.alt_btn.setIconSize(QSize(18, 18))
            self.alt_btn.setToolTip("إضافة بديل لهذا الدواء")
            self.alt_btn.setStyleSheet(
                f"QPushButton{{background:{COLOR_SURFACE_SUBTLE};color:{COLOR_TEXT_SECONDARY};"
                f"border:1px solid {COLOR_BORDER};border-radius:{RADIUS_BUTTON}px;"
                f"padding:6px 10px;font-size:12px;font-weight:700;}}"
                f"QPushButton:hover{{background:{COLOR_BORDER};}}"
            )

    def refresh_stock(self):
        """يحدّث رقم/لون المخزون بس على نفس البطاقة الموجودة، بدون أي تغيير
        بمكانها أو حجمها بالشبكة - يُستخدم بعد إتمام بيع بدل إعادة بناء
        الشبكة كاملة (اللي كانت تسبب ومضة/تمدد مؤقت بكل عملية بيع)."""
        stock_color, stock_text = self._stock_display(self.product)
        self.stock_lbl.setText(stock_text)
        self.stock_lbl.setStyleSheet(
            f"background:transparent;border:none;color:{stock_color};"
            f"font-size:{FONT_CAPTION[0]}px;font-weight:{FONT_CAPTION[1]};"
        )


class AlternativesDialog(QDialog):
    """نافذة إدارة بدائل دواء معيّن.

    تعرض: (1) البدائل التلقائية (نفس المادة الفعالة) للعلم فقط - مو قابلة
    للحذف لأنها مو صف فعلي بجدول product_alternatives أصلاً، و(2) البدائل
    المسجلة يدويًا مع إمكانية حذف أي وحدة منها (= "تعديل"). وفيها حقل بحث
    باسم الدواء + زر حفظ يضيف صف جديد بجدول product_alternatives - هذا هو كل
    التعديل على قاعدة البيانات المرتبط بهذي الميزة، ما يمس أي جدول أو حساب
    ثاني إطلاقًا."""

    def __init__(self, session, product, parent=None):
        super().__init__(parent)
        self.session = session
        self.product = product
        self.changed = False  # يصير True بس لو انضاف أو انحذف بديل فعليًا
        self.setWindowTitle(f"بدائل {product.name}")
        self.setMinimumWidth(440)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(f"QDialog{{background:{COLOR_SURFACE};}}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_20, SPACE_20, SPACE_20, SPACE_20)
        layout.setSpacing(SPACE_12)

        title = QLabel(f"إدارة بدائل: {product.name}")
        title.setWordWrap(True)
        title.setStyleSheet(
            f"font-weight:800;font-size:{FONT_H3[0]}px;color:{COLOR_TEXT_PRIMARY};background:transparent;border:none;"
        )
        layout.addWidget(title)

        # ---- بدائل تلقائية (نفس المادة الفعالة) - عرض فقط ----
        auto_alts = []
        if product.generic_name:
            auto_alts = (
                self.session.query(Product)
                .filter(Product.generic_name == product.generic_name, Product.id != product.id)
                .all()
            )
        if auto_alts:
            auto_lbl = QLabel("بدائل تلقائية (نفس المادة الفعالة):")
            auto_lbl.setStyleSheet(
                f"color:{COLOR_TEXT_SECONDARY};font-weight:700;font-size:12px;background:transparent;border:none;"
            )
            layout.addWidget(auto_lbl)
            for a in auto_alts:
                lbl = QLabel(f"• {a.name}")
                lbl.setStyleSheet(
                    f"color:{COLOR_TEXT_PRIMARY};font-size:13px;background:transparent;border:none;padding-right:4px;"
                )
                layout.addWidget(lbl)

        # ---- بدائل مسجلة يدويًا - قابلة للحذف (تعديل) ----
        manual_lbl = QLabel("البدائل المضافة يدويًا:")
        manual_lbl.setStyleSheet(
            f"color:{COLOR_TEXT_SECONDARY};font-weight:700;font-size:12px;background:transparent;border:none;"
        )
        layout.addWidget(manual_lbl)

        self.manual_list_layout = QVBoxLayout()
        self.manual_list_layout.setSpacing(SPACE_4)
        layout.addLayout(self.manual_list_layout)
        self._refresh_manual_list()

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background:{COLOR_BORDER};border:none;")
        layout.addWidget(divider)

        # ---- إضافة بديل جديد بكتابة اسمه والحفظ ----
        add_lbl = QLabel("إضافة بديل جديد:")
        add_lbl.setStyleSheet(
            f"color:{COLOR_TEXT_SECONDARY};font-weight:700;font-size:12px;background:transparent;border:none;"
        )
        layout.addWidget(add_lbl)

        input_style = (
            f"border:1.5px solid {COLOR_BORDER};border-radius:{RADIUS_INPUT}px;"
            f"padding:{SPACE_8}px {SPACE_12}px;background-color:{COLOR_SURFACE};"
        )
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("اكتب اسم الدواء البديل...")
        self.search_input.setStyleSheet(input_style)
        self.search_input.setMinimumHeight(38)
        self.search_input.textChanged.connect(self._search_products)
        layout.addWidget(self.search_input)

        self.results_list = QListWidget()
        self.results_list.setMaximumHeight(120)
        self.results_list.setStyleSheet(
            f"QListWidget{{border:1px solid {COLOR_BORDER};border-radius:{RADIUS_INPUT}px;background:{COLOR_SURFACE};}}"
        )
        layout.addWidget(self.results_list)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("ملاحظة (اختياري)")
        self.note_input.setStyleSheet(input_style)
        self.note_input.setMinimumHeight(36)
        layout.addWidget(self.note_input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(SPACE_8)
        save_btn = QPushButton("  حفظ البديل")
        save_btn.setIcon(icon("check", color="white", size=20))
        save_btn.setIconSize(QSize(20, 20))
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setMinimumHeight(44)
        save_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:{RADIUS_BUTTON}px;padding:8px 16px;font-size:13px;"
            f"font-weight:800;border:none;}}"
            f"QPushButton:hover{{background:{TEAL_500};}}"
        )
        save_btn.clicked.connect(self._save_alternative)
        close_btn = QPushButton("إغلاق")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setMinimumHeight(44)
        close_btn.setStyleSheet(
            f"QPushButton{{background:{COLOR_SURFACE_SUBTLE};color:{COLOR_TEXT_PRIMARY};"
            f"border:1px solid {COLOR_BORDER};border-radius:{RADIUS_BUTTON}px;padding:8px 16px;font-weight:700;font-size:13px;}}"
        )
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn, stretch=1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _refresh_manual_list(self):
        while self.manual_list_layout.count():
            child = self.manual_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        manual = self.session.query(ProductAlternative).filter_by(product_id=self.product.id).all()
        if not manual:
            empty = QLabel("لا توجد بدائل مضافة يدويًا بعد - أضف واحد بالأسفل.")
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color:{COLOR_TEXT_SECONDARY};font-size:12px;background:transparent;border:none;"
            )
            self.manual_list_layout.addWidget(empty)
            return

        for alt in manual:
            alt_product = self.session.query(Product).get(alt.alternative_product_id)
            if not alt_product:
                continue
            row_wrapper = QFrame()
            row_wrapper.setStyleSheet(
                f"QFrame{{background:{COLOR_SURFACE_SUBTLE};border:1px solid {COLOR_BORDER};"
                f"border-radius:{RADIUS_BUTTON}px;}}"
            )
            row = QHBoxLayout(row_wrapper)
            row.setContentsMargins(SPACE_12, SPACE_8, SPACE_8, SPACE_8)
            name_txt = alt_product.name + (f"  -  {alt.note}" if alt.note else "")
            lbl = QLabel(name_txt)
            lbl.setStyleSheet(
                f"color:{COLOR_TEXT_PRIMARY};font-size:13px;font-weight:700;background:transparent;border:none;"
            )
            row.addWidget(lbl, 1)
            del_btn = _icon_button(
                "trash", size=34, icon_size=16, color=RED_500, hover_bg=COLOR_DANGER_BG,
            )
            del_btn.setToolTip("حذف هذا البديل")
            del_btn.clicked.connect(lambda _, aid=alt.id: self._delete_alternative(aid))
            row.addWidget(del_btn)
            self.manual_list_layout.addWidget(row_wrapper)

    def _delete_alternative(self, alt_id):
        alt = self.session.query(ProductAlternative).get(alt_id)
        if alt:
            self.session.delete(alt)
            self.session.commit()
            self.changed = True
        self._refresh_manual_list()

    def _search_products(self, text):
        self.results_list.clear()
        text = text.strip()
        if not text:
            return
        norm_text = normalize_arabic(text)
        existing_ids = {
            a.alternative_product_id for a in
            self.session.query(ProductAlternative).filter_by(product_id=self.product.id).all()
        }
        matches = [
            p for p in self.session.query(Product).filter(Product.is_active == True).all()
            if p.id != self.product.id
            and p.id not in existing_ids
            and norm_text in normalize_arabic(p.name)
        ][:15]
        for p in matches:
            item = QListWidgetItem(p.name)
            item.setData(Qt.UserRole, p.id)
            self.results_list.addItem(item)

    def _save_alternative(self):
        selected = self.results_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "تنبيه", "اكتب اسم الدواء البديل واختره من نتائج البحث أول.")
            return
        alt_id = selected.data(Qt.UserRole)
        note = self.note_input.text().strip() or None
        self.session.add(ProductAlternative(
            product_id=self.product.id, alternative_product_id=alt_id, note=note,
        ))
        self.session.commit()
        self.changed = True
        self.search_input.clear()
        self.note_input.clear()
        self.results_list.clear()
        self._refresh_manual_list()


class InvoicePanel(QFrame):
    def __init__(self, on_checkout, stock_checker=None, unit_toggle_provider=None,
                 available_base_checker=None, parent=None):
        super().__init__(parent)
        self.on_checkout = on_checkout
        self.stock_checker = stock_checker  # (product_id, unit_id) -> أقصى كمية متوفرة بهذي الوحدة
        # (product_id, current_unit_id) -> (unit_id, unit_name, unit_price, conversion_factor)
        # للوحدة البديلة، أو None لو ماكو أكثر من وحدة قياس معرّفة لهذا الدواء
        self.unit_toggle_provider = unit_toggle_provider
        # (product_id) -> مجموع الكمية المتوفرة بوحدة الأساس (شريط) بقاعدة
        # البيانات، بدون أي علم بمحتوى السلة. نستخدمها هنا (مو stock_checker
        # لحاله) عشان نقدر نحسب "المتبقي الحقيقي" مع طرح أي كمية محجوزة
        # أصلًا بأسطر ثانية بالسلة لنفس الدواء بوحدة مختلفة (شريط/علبة) -
        # قبل هذا كان كل سطر يتحقق من المخزون الكلي بالقاعدة لحاله بدون ما
        # يعرف إن سطر ثاني بنفس السلة حاجز جزء منه أصلًا.
        self.available_base_checker = available_base_checker
        self.cart = []  # list of dicts
        self.setStyleSheet(
            f"QFrame{{background:{COLOR_SURFACE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_CARD}px;}}"
        )
        add_shadow(self, blur=SHADOW_LARGE["blur"], color=TEAL_700,
                   alpha=SHADOW_LARGE["alpha"], y_offset=SHADOW_LARGE["y_offset"])
        self.setFixedWidth(392)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_20, SPACE_20, SPACE_20, SPACE_16)
        layout.setSpacing(SPACE_12)

        # ---- رأس اللوحة: أيقونة + عنوان + شارة عدد الأصناف + مسح الكل ----
        header = QHBoxLayout()
        header.setSpacing(SPACE_8)

        self.count_badge = QLabel("0")
        self.count_badge.setAlignment(Qt.AlignCenter)
        self.count_badge.setFixedSize(26, 26)
        self.count_badge.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:13px;font-size:12px;font-weight:800;"
        )
        header.addWidget(self.count_badge)

        title = QLabel("الفاتورة الحالية")
        title.setStyleSheet(
            f"font-size:{FONT_H2[0]}px;font-weight:{FONT_H2[1]};background:transparent;border:none;"
        )
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("مسح الكل")
        clear_btn.setIcon(icon("trash", color=RED_500, size=19))
        clear_btn.setIconSize(QSize(19, 19))
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(
            f"QPushButton{{background:{COLOR_DANGER_BG};color:{RED_500};border:1px solid {COLOR_DANGER_BORDER};"
            f"border-radius:{RADIUS_BUTTON}px;padding:6px 12px;font-weight:800;font-size:12px;}}"
            f"QPushButton:hover{{background:{COLOR_DANGER_BORDER};}}"
        )
        clear_btn.clicked.connect(self.clear_cart)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        # ---- تنبيه التداخل الدوائي ----
        self.warning_lbl = QLabel()
        self.warning_lbl.setWordWrap(True)
        self.warning_lbl.setStyleSheet(
            f"background:{COLOR_DANGER_BG};color:{COLOR_DANGER_TEXT};border:1px solid {COLOR_DANGER_BORDER};"
            f"border-radius:{RADIUS_BUTTON}px;padding:{SPACE_12}px;font-size:{FONT_CAPTION[0]}px;"
            f"font-weight:{FONT_BODY_STRONG[1]};"
        )
        self.warning_lbl.hide()
        layout.addWidget(self.warning_lbl)

        # ---- قائمة السلة ----
        # (شُطب عنوان الأعمدة الزخرفي "المنتج/الكمية/الإجمالي" اللي كان هنا -
        # كان بس تسمية عمودية غير ضرورية فوق الصفوف، وحذفه ما يمس أي بيانات
        # أو منطق؛ كل صف بالسلة يوضّح بياناته بنفسه).
        self.cart_area = QVBoxLayout()
        self.cart_area.setSpacing(SPACE_4)
        cart_widget = QWidget()
        cart_widget.setLayout(self.cart_area)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(cart_widget)
        enable_touch_scroll(scroll)
        layout.addWidget(scroll, stretch=1)

        self.empty_lbl = self._build_empty_label()
        self.cart_area.addWidget(self.empty_lbl)

        # ---- لوحة الإجمالي المميزة ----
        totals_frame = QFrame()
        totals_frame.setStyleSheet(
            f"QFrame{{background:{COLOR_SURFACE_SUBTLE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_CARD}px;}}"
        )
        totals = QVBoxLayout(totals_frame)
        totals.setContentsMargins(SPACE_16, SPACE_16, SPACE_16, SPACE_16)
        totals.setSpacing(SPACE_8)

        sub_row = QHBoxLayout()
        sub_caption = QLabel("الإجمالي الفرعي")
        sub_caption.setStyleSheet(
            f"color:{COLOR_TEXT_SECONDARY};font-size:{FONT_BODY[0]}px;font-weight:600;background:transparent;border:none;"
        )
        self.subtotal_lbl = QLabel(fmt_money(0))
        self.subtotal_lbl.setStyleSheet(
            f"color:{COLOR_TEXT_PRIMARY};font-size:{FONT_BODY[0]}px;font-weight:800;background:transparent;border:none;"
        )
        sub_row.addWidget(sub_caption)
        sub_row.addStretch()
        sub_row.addWidget(self.subtotal_lbl)
        totals.addLayout(sub_row)

        disc_row = QHBoxLayout()
        disc_row.setSpacing(SPACE_8)
        disc_label = QLabel("الخصم (دينار)")
        disc_label.setStyleSheet(
            f"background:transparent;border:none;color:{COLOR_TEXT_SECONDARY};font-size:{FONT_BODY[0]}px;font-weight:600;"
        )
        disc_row.addWidget(disc_label)
        disc_row.addStretch()
        self.discount_input = NumberLineEdit(decimals=0, placeholder="0")
        self.discount_input.setAlignment(Qt.AlignCenter)
        self.discount_input.setFixedWidth(110)
        self.discount_input.setStyleSheet(
            f"border:1.5px solid {COLOR_BORDER};border-radius:{RADIUS_INPUT}px;"
            f"padding:{SPACE_8}px {SPACE_12}px;background-color:{COLOR_SURFACE};font-weight:800;"
        )
        self.discount_input.setMinimumHeight(36)
        self.discount_input.textChanged.connect(self.refresh_totals)
        disc_row.addWidget(self.discount_input)
        totals.addLayout(disc_row)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background:{COLOR_BORDER};border:none;")
        totals.addWidget(divider)

        net_row = QHBoxLayout()
        net_caption = QLabel("الصافي")
        net_caption.setStyleSheet(
            f"font-weight:800;font-size:{FONT_H3[0]}px;color:{COLOR_TEXT_PRIMARY};background:transparent;border:none;"
        )
        self.net_lbl = QLabel(fmt_money(0))
        self.net_lbl.setStyleSheet(
            f"font-weight:{FONT_H2[1]};font-size:{FONT_H2[0] + 2}px;color:{TEAL_700};background:transparent;border:none;"
        )
        net_row.addWidget(net_caption)
        net_row.addStretch()
        net_row.addWidget(self.net_lbl)
        totals.addLayout(net_row)

        # --- طريقة الدفع: كاش / دين / محفظة / إرجاع ---
        pay_method_row = QHBoxLayout()
        pay_method_row.setSpacing(SPACE_8)
        self.cash_btn = self._payment_chip("كاش", "cash")
        self.credit_btn = self._payment_chip("دين", "credit_card")
        self.wallet_btn = self._payment_chip("محفظة", "wallet")
        self.return_btn = self._payment_chip("إرجاع", "undo")
        self.cash_btn.setChecked(True)
        self.cash_btn.clicked.connect(lambda: self._set_payment_method("كاش"))
        self.credit_btn.clicked.connect(lambda: self._set_payment_method("دين"))
        self.wallet_btn.clicked.connect(lambda: self._set_payment_method("محفظة"))
        self.return_btn.clicked.connect(lambda: self._set_payment_method("إرجاع"))
        pay_method_row.addWidget(self.cash_btn, 1)
        pay_method_row.addWidget(self.credit_btn, 1)
        pay_method_row.addWidget(self.wallet_btn, 1)
        pay_method_row.addWidget(self.return_btn, 1)
        totals.addLayout(pay_method_row)
        self._apply_payment_btn_styles()

        self.debtor_frame = QFrame()
        debtor_layout = QVBoxLayout(self.debtor_frame)
        debtor_layout.setContentsMargins(0, SPACE_8, 0, 0)
        debtor_layout.setSpacing(SPACE_8)
        input_style = (
            f"border:1.5px solid {COLOR_BORDER};border-radius:{RADIUS_INPUT}px;"
            f"padding:{SPACE_8}px {SPACE_12}px;background-color:{COLOR_SURFACE};"
        )
        self.debtor_name_input = QLineEdit()
        self.debtor_name_input.setPlaceholderText("اسم الزبون (المدين)")
        self.debtor_name_input.setStyleSheet(input_style)
        self.debtor_name_input.setMinimumHeight(38)
        self.debtor_phone_input = QLineEdit()
        self.debtor_phone_input.setPlaceholderText("رقم الهاتف")
        self.debtor_phone_input.setStyleSheet(input_style)
        self.debtor_phone_input.setMinimumHeight(38)
        debtor_layout.addWidget(self.debtor_name_input)
        debtor_layout.addWidget(self.debtor_phone_input)
        self.debtor_frame.hide()
        totals.addWidget(self.debtor_frame)

        pay_btn = QPushButton("  إتمام البيع")
        pay_btn.setObjectName("PayButton")
        pay_btn.setIcon(icon("check", color="white", size=18))
        pay_btn.setIconSize(QSize(18, 18))
        pay_btn.setCursor(Qt.PointingHandCursor)
        pay_btn.setMinimumHeight(56)
        pay_btn.setStyleSheet(self._pay_btn_style(danger=False))
        add_shadow(pay_btn, blur=SHADOW_MEDIUM["blur"], color=TEAL_700,
                   alpha=32, y_offset=SHADOW_MEDIUM["y_offset"])
        pay_btn.clicked.connect(self._checkout)
        self.pay_btn = pay_btn
        totals.addWidget(pay_btn)

        layout.addWidget(totals_frame)
        self.payment_method = "كاش"
        self.render_cart()

    def _build_empty_label(self):
        lbl = QLabel()
        lbl.setPixmap(icon("cart", color=COLOR_TEXT_SECONDARY, size=30).pixmap(30, 30))
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"background:transparent;border:none;padding:{SPACE_20}px;")
        wrapper = QFrame()
        wrapper.setStyleSheet("background:transparent;border:none;")
        v = QVBoxLayout(wrapper)
        v.setSpacing(SPACE_8)
        v.addWidget(lbl)
        text_lbl = QLabel("السلة فارغة")
        text_lbl.setAlignment(Qt.AlignCenter)
        text_lbl.setStyleSheet(
            f"color:{COLOR_TEXT_SECONDARY};background:transparent;border:none;font-weight:700;"
        )
        v.addWidget(text_lbl)
        return wrapper

    def _payment_chip(self, text, icon_name):
        btn = QPushButton(text)
        btn.setIcon(icon(icon_name, color=COLOR_TEXT_PRIMARY, size=19))
        btn.setIconSize(QSize(19, 19))
        btn.setCheckable(True)
        btn.setMinimumHeight(44)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _pay_btn_style(self, danger):
        if danger:
            return (
                f"QPushButton{{background:{RED_500};color:white;font-weight:{FONT_H3[1]};"
                f"font-size:{FONT_H3[0]}px;border-radius:{RADIUS_BUTTON + 4}px;padding:12px;border:none;}}"
                f"QPushButton:hover{{background:#D9483A;}}"
            )
        return (
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;font-weight:800;font-size:{FONT_H3[0] + 1}px;"
            f"border-radius:{RADIUS_BUTTON + 4}px;padding:12px;border:none;}}"
            f"QPushButton:hover{{background:{TEAL_500};}}"
        )

    def _set_payment_method(self, method):
        self.payment_method = method
        self.cash_btn.setChecked(method == "كاش")
        self.credit_btn.setChecked(method == "دين")
        self.wallet_btn.setChecked(method == "محفظة")
        self.return_btn.setChecked(method == "إرجاع")
        self.debtor_frame.setVisible(method == "دين")
        if method == "إرجاع":
            self.pay_btn.setText("  تأكيد الإرجاع")
            self.pay_btn.setIcon(icon("undo", color="white", size=18))
            self.pay_btn.setIconSize(QSize(18, 18))
            self.pay_btn.setStyleSheet(self._pay_btn_style(danger=True))
        else:
            self.pay_btn.setText("  إتمام البيع")
            self.pay_btn.setIcon(icon("check", color="white", size=18))
            self.pay_btn.setIconSize(QSize(18, 18))
            self.pay_btn.setStyleSheet(self._pay_btn_style(danger=False))
        self._apply_payment_btn_styles()

    def _apply_payment_btn_styles(self):
        # حجم أيقونة موحّد لكل شرائح الدفع (كاش/دين/محفظة/إرجاع) - قبل هذا
        # التعديل كانت كل شريحة تاخذ نفس الحجم أصلاً بالكود بس الحجم كان
        # صغير (14px)، هنا كبّرناه شوي (16px) مع حشوة أوسع لمحاذاة أفضل،
        # ومحافظين على "كاش" كخيار مميز بصريًا بالتحديد الافتراضي + التدرّج
        # اللوني البارز اللي توفره toggle_chip_stylesheet لأي شريحة محددة.
        for btn, icon_name in (
            (self.cash_btn, "cash"), (self.credit_btn, "credit_card"),
            (self.wallet_btn, "wallet"), (self.return_btn, "undo"),
        ):
            btn.setStyleSheet(toggle_chip_stylesheet(btn.isChecked()) + "font-size:12px;padding:6px 8px;")
            btn.setIcon(icon(icon_name, color="white" if btn.isChecked() else COLOR_TEXT_SECONDARY, size=16))
            btn.setIconSize(QSize(16, 16))

    def _max_qty_for_line(self, product_id, conversion_factor, exclude_idx=None, extra_exclude_idx=None):
        """أقصى كمية ممكنة (بوحدة الـconversion_factor المعطاة) لسطر معيّن
        بالسلة، مع مراعاة أي كمية محجوزة أصلًا بأسطر ثانية بالسلة لنفس
        الدواء بوحدة مختلفة (شريط/علبة سوا).

        إصلاح: قبل هذا كل سطر كان يتحقق من المخزون الكلي المتوفر بالقاعدة
        لحاله (عبر stock_checker) بدون ما يطرح الكمية المحجوزة أصلًا بسطر
        ثاني لنفس الدواء بوحدة أخرى - مثال: 10 أشرطة متوفرة، تضيف علبة
        (=10 أشرطة) بسطر، وبعدها تقدر "تضيف" شريط لحاله بسطر ثاني لأن
        الفحص القديم ما يعرف إن الـ10 محجوزة أصلًا. الفحص النهائي بـ
        checkout() كان يمنع البيع أخيرًا، بس بعد ما المستخدم يحس إن
        الإضافة "نجحت" - تجربة استخدام مربكة. الحين الفحص هنا يحسب المتبقي
        الحقيقي فعليًا من أول خطوة.

        exclude_idx / extra_exclude_idx: انديكسات أسطر تُستثنى من حساب
        "المحجوز بأسطر ثانية" (السطر نفسه اللي نحسب أقصى كمية له، وأي سطر
        هدف دمج محتمل عند تبديل الوحدة)."""
        if not self.available_base_checker or not conversion_factor:
            return None
        total_base = self.available_base_checker(product_id)
        excluded = {i for i in (exclude_idx, extra_exclude_idx) if i is not None}
        reserved_base = sum(
            item["qty"] * item.get("conversion_factor", 1)
            for i, item in enumerate(self.cart)
            if item["product_id"] == product_id and i not in excluded
        )
        remaining_base = max(total_base - reserved_base, 0)
        return remaining_base // conversion_factor

    def add_item(self, product, unit, unit_price):
        for idx, item in enumerate(self.cart):
            if item["product_id"] == product.id and item["unit_id"] == unit.id:
                max_qty = self._max_qty_for_line(product.id, unit.conversion_factor, exclude_idx=idx)
                if max_qty is not None and item["qty"] + 1 > max_qty:
                    QMessageBox.warning(
                        self, "نفذت الكمية",
                        f"نفذت الكمية المتوفرة من {product.name} ({unit.unit_name}).\n"
                        f"أقصى كمية متوفرة حاليًا: {max_qty}."
                    )
                    return
                item["qty"] += 1
                self.render_cart()
                return
        max_qty = self._max_qty_for_line(product.id, unit.conversion_factor)
        if max_qty is not None and max_qty < 1:
            QMessageBox.warning(self, "نفذت الكمية", f"نفذت الكمية المتوفرة من {product.name} ({unit.unit_name}).")
            return
        self.cart.append({
            "product_id": product.id, "name": product.name,
            "unit_id": unit.id, "unit_name": unit.unit_name,
            "unit_price": unit_price, "qty": 1,
            "conversion_factor": unit.conversion_factor,
        })
        self.render_cart()

    def clear_cart(self):
        self.cart = []
        self.discount_input.setText("")
        self.set_warning(None)
        self.debtor_name_input.clear()
        self.debtor_phone_input.clear()
        self._set_payment_method("كاش")
        self.render_cart()

    def set_warning(self, text):
        if text:
            self.warning_lbl.setText(text)
            self.warning_lbl.show()
        else:
            self.warning_lbl.hide()

    def render_cart(self):
        while self.cart_area.count():
            child = self.cart_area.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.count_badge.setText(str(len(self.cart)))

        if not self.cart:
            self.cart_area.addWidget(self._build_empty_label())
        else:
            for idx, item in enumerate(self.cart):
                self.cart_area.addWidget(self._build_cart_row(idx, item))
            # نضيف مساحة مرنة بآخر القائمة بدل ما تاخذ الصفوف نفسها الفراغ الزائد -
            # بذا يبقى ارتفاع الصف نفسه ثابت مضغوط سواء كان بالسلة صنف وحد أو أكثر
            # من 4، وأي فراغ إضافي بالمساحة يروح تحت آخر صف مو داخل الصفوف.
            self.cart_area.addStretch(1)

        self.refresh_totals()

    def _build_cart_row(self, idx, item):
        """صف فاتورة بسطرين: السطر الأول اسم الدواء + زر الحذف، والسطر الثاني
        الوحدة + الكمية (-1+) + الإجمالي.

        (إصلاح جذري: قبل كان كل شي بسطر واحد - اسم+وحدة+كمية+سعر+حذف - وهذا
        رياضيًا ما يتسع بعرض لوحة الفاتورة الثابت (392px) إذا كان الاسم
        طويل أو السعر كبير (6+ أرقام)، مهما عدّلنا عرض كل عنصر لحاله. أي
        محاولة "ترقيع" بتصغير عنصر أو تكبير عنصر ثاني كانت تحل مكان وتخرب
        مكان ثاني (يختفي السعر أو يختفي زر الحذف). بتوزيع العناصر على
        سطرين، كل سطر عنده مساحة أكثر من كافية دايمًا - المشكلة تنحل من
        جذرها بدل ما تنرقّع.)"""
        row = QFrame()
        # مطلوب صراحة حتى Qt يرسم خلفية الإطار المصمّمة بالستايل شيت (حواف
        # مستديرة + لون خلفية) بشكل صحيح من أول لحظة إنشاء الـ widget. بدون
        # هذي الخاصية، QFrame يقدر "يومض" بشكله الافتراضي (غامق/أسود) للحظة
        # قبل ما يترسم الستايل فعليًا - وهذا بالضبط سبب المستطيلات السوداء
        # اللي تظهر لثوان، خصوصًا إن كل ضغطة (+/-/حذف) تعيد بناء كل صفوف
        # السلة من الصفر (render_cart يمسح ويعيد إنشاء كل شي في كل مرة).
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setStyleSheet(
            f"QFrame{{background:{COLOR_SURFACE_SUBTLE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_BUTTON}px;}}"
        )
        row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        outer = QVBoxLayout(row)
        outer.setContentsMargins(SPACE_8, 6, SPACE_8, 6)
        outer.setSpacing(4)

        # --- السطر الأول: اسم الدواء (يتمدد كامل العرض المتاح) + حذف ---
        top_row = QHBoxLayout()
        top_row.setSpacing(SPACE_8)
        name_lbl = QLabel(item['name'])
        name_lbl.setWordWrap(False)
        name_lbl.setStyleSheet(
            f"background:transparent;border:none;font-size:12px;"
            f"font-weight:800;color:{COLOR_TEXT_PRIMARY};"
        )
        name_lbl.setToolTip(item['name'])
        remove_btn = _icon_button(
            "trash", size=32, icon_size=15, color=RED_500,
            hover_bg=COLOR_DANGER_BG,
        )
        remove_btn.clicked.connect(lambda _, i=idx: self._remove_item(i))
        top_row.addWidget(name_lbl, 1)
        top_row.addWidget(remove_btn)
        outer.addLayout(top_row)

        # --- السطر الثاني: الوحدة + الكمية + الإجمالي ---
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(SPACE_8)

        # الوحدة كزر صغير قابل للضغط - يبدّل بين الوحدات المتوفرة لنفس الدواء
        # (شريط ↔ علبة عادة) مع إعادة حساب السعر تلقائيًا حسب الوحدة الجديدة.
        # لو الدواء ما إله إلا وحدة وحدة، الزر يبقى معطّل (ماكو شي يتبدّل له).
        unit_btn = QPushButton(f"{item['unit_name']} ▾")
        unit_btn.setCursor(Qt.PointingHandCursor)
        unit_btn.setMinimumHeight(34)
        unit_btn.setStyleSheet(
            f"QPushButton{{background:{COLOR_SURFACE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_PILL}px;padding:4px 12px;font-size:12px;font-weight:700;"
            f"color:{TEAL_700};}}"
            f"QPushButton:hover{{background:{TEAL_50};}}"
            f"QPushButton:disabled{{color:{COLOR_TEXT_SECONDARY};}}"
        )
        unit_btn.setToolTip("اضغط لتبديل وحدة القياس (شريط/علبة)")
        if not self.unit_toggle_provider:
            unit_btn.setEnabled(False)
        unit_btn.clicked.connect(lambda _, i=idx: self._toggle_unit(i))

        # الكمية +/- كشريحة مدوّرة مصغّرة
        qty_pill = QFrame()
        qty_pill.setAttribute(Qt.WA_StyledBackground, True)
        qty_pill.setFixedWidth(104)
        qty_pill.setFixedHeight(38)
        qty_pill.setStyleSheet(
            f"QFrame{{background:{COLOR_SURFACE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_PILL}px;}}"
        )
        qty_pill_layout = QHBoxLayout(qty_pill)
        qty_pill_layout.setContentsMargins(2, 2, 2, 2)
        qty_pill_layout.setSpacing(0)
        minus_btn = _icon_button("minus", size=32, icon_size=16, color=RED_500)
        qty_lbl = QLabel(str(item["qty"]))
        qty_lbl.setFixedWidth(28)
        qty_lbl.setAlignment(Qt.AlignCenter)
        qty_lbl.setStyleSheet(
            "background:transparent;border:none;font-weight:800;font-size:13px;"
        )
        plus_btn = _icon_button("plus", size=32, icon_size=16, color=TEAL_600)
        minus_btn.clicked.connect(lambda _, i=idx: self._change_qty(i, -1))
        plus_btn.clicked.connect(lambda _, i=idx: self._change_qty(i, 1))
        qty_pill_layout.addWidget(minus_btn)
        qty_pill_layout.addWidget(qty_lbl)
        qty_pill_layout.addWidget(plus_btn)

        # الإجمالي - بسطره الخاص لحاله الآن، فله كل المساحة المتبقية بالسطر
        # الثاني (بعد الوحدة والكمية) بدون أي منازعة مع الاسم أو زر الحذف -
        # يعرض أي رقم مهما كبر (حتى 6-7 أرقام) بدون أي احتمال طفح أو اختفاء.
        total_lbl = QLabel(fmt_money(item['unit_price'] * item['qty']))
        total_lbl.setStyleSheet(
            f"background:transparent;border:none;font-weight:800;"
            f"color:{COLOR_TEXT_PRIMARY};font-size:13px;"
        )
        total_lbl.setAlignment(Qt.AlignCenter)

        bottom_row.addWidget(unit_btn)
        bottom_row.addWidget(qty_pill)
        bottom_row.addStretch(1)
        bottom_row.addWidget(total_lbl)
        outer.addLayout(bottom_row)

        return row

    def _toggle_unit(self, idx):
        if not self.unit_toggle_provider:
            return
        item = self.cart[idx]
        result = self.unit_toggle_provider(item["product_id"], item["unit_id"])
        if not result:
            return  # ماكو وحدة قياس بديلة معرّفة لهذا الدواء
        new_unit_id, new_unit_name, new_unit_price, new_conversion_factor = result

        # لو فيه صف ثاني بالسلة لنفس الدواء بنفس الوحدة الجديدة أصلاً، راح
        # ندمج الكميتين بصف وحد - نحدده هنا مسبقًا (مو بس وقت الدمج الفعلي
        # بالأسفل) عشان نقدر نتحقق من المخزون على "الكمية النهائية بعد
        # الدمج" مباشرة، مو كمية السطر الحالي لحاله فقط.
        merge_idx = next(
            (i for i, other in enumerate(self.cart)
             if i != idx and other["product_id"] == item["product_id"] and other["unit_id"] == new_unit_id),
            None
        )
        combined_qty = item["qty"] + (self.cart[merge_idx]["qty"] if merge_idx is not None else 0)

        # إصلاح: قبل هذا الفحص كان يتحقق من كمية السطر الحالي لحاله بس ضد
        # المخزون الكلي بالقاعدة - لو راح يندمج مع سطر موجود أصلًا بنفس
        # الوحدة الجديدة، ما كان يراعي كميته هو، فيصير مجموع نهائي بعد
        # الدمج أكبر من المتوفر فعليًا بدون ما يوقفه شي هنا (بس checkout()
        # النهائي كان يمسكه). الحين نتحقق من combined_qty (الكمية بعد
        # الدمج) مباشرة، ونستثني كل من السطر الحالي وسطر الدمج المحتمل من
        # حساب "المحجوز بأسطر ثانية" لأنهم بالنتيجة راح يصيرون سطر وحد.
        max_qty = self._max_qty_for_line(
            item["product_id"], new_conversion_factor,
            exclude_idx=idx, extra_exclude_idx=merge_idx,
        )
        if max_qty is not None and combined_qty > max_qty:
            QMessageBox.warning(
                self, "تنبيه",
                f"الكمية الإجمالية بعد التبديل ({combined_qty}) أكبر من المتوفر بوحدة {new_unit_name} ({max_qty})."
            )
            return

        if merge_idx is not None:
            self.cart[merge_idx]["qty"] = combined_qty
            del self.cart[idx]
            self.render_cart()
            return
        item["unit_id"] = new_unit_id
        item["unit_name"] = new_unit_name
        item["unit_price"] = new_unit_price
        item["conversion_factor"] = new_conversion_factor
        self.render_cart()

    def _change_qty(self, idx, delta):
        item = self.cart[idx]
        new_qty = item["qty"] + delta
        if delta > 0:
            max_qty = self._max_qty_for_line(
                item["product_id"], item.get("conversion_factor", 1), exclude_idx=idx
            )
            if max_qty is not None and new_qty > max_qty:
                QMessageBox.warning(
                    self, "نفذت الكمية",
                    f"نفذت الكمية المتوفرة من {item['name']} ({item['unit_name']}).\n"
                    f"أقصى كمية متوفرة حاليًا: {max_qty}."
                )
                return
        item["qty"] = max(1, new_qty)
        self.render_cart()

    def _remove_item(self, idx):
        del self.cart[idx]
        self.render_cart()

    def refresh_totals(self):
        subtotal = sum(i["unit_price"] * i["qty"] for i in self.cart)
        discount = self.discount_input.value()
        net = max(subtotal - discount, 0)
        self.subtotal_lbl.setText(fmt_money(subtotal))
        self.net_lbl.setText(fmt_money(net))

    def _checkout(self):
        if not self.cart:
            QMessageBox.warning(self, "تنبيه", "السلة فارغة، ضيف منتج أول.")
            return
        debtor_name = self.debtor_name_input.text().strip()
        debtor_phone = self.debtor_phone_input.text().strip()
        if self.payment_method == "دين" and not debtor_name:
            QMessageBox.warning(self, "تنبيه", "لازم تدخل اسم الزبون المدين.")
            return
        success = self.on_checkout(self.cart, self.discount_input.value(), self.payment_method, debtor_name, debtor_phone)
        # إصلاح: قبل كنا نفرّغ السلة هنا بشكل أعمى بكل الحالات - حتى لو
        # فشلت عملية الدفع فعليًا (نقص مخزون تم اكتشافه لحظة التأكيد، خطأ
        # قاعدة بيانات...) وما انحفظت أي فاتورة، كان الكاشير يخسر كل الأصناف
        # اللي أضافها للسلة بدون ما يصير أي بيع حقيقي. الحين ما نفرّغ السلة
        # إلا لو on_checkout رجع True (نجحت العملية وانحفظت فعليًا).
        if success:
            self.clear_cart()


class POSView(QWidget):
    def __init__(self, current_user, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.session = get_session()
        self._current_cards = []
        self._grid_col_count = None
        self._grid_stretch_row = None
        self.selected_category = "الكل"
        self.category_buttons = {}

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(SPACE_20, SPACE_20, SPACE_20, SPACE_20)
        main_layout.setSpacing(SPACE_20)

        self.invoice_panel = InvoicePanel(
            on_checkout=self.checkout, stock_checker=self._max_addable,
            unit_toggle_provider=self._get_alt_unit, available_base_checker=self._available_base,
        )
        main_layout.addWidget(self.invoice_panel)

        right = QVBoxLayout()
        right.setSpacing(SPACE_12)

        # ---- شريط بحث/باركود كبير + شرائح التصنيفات ----
        toolbar = QFrame()
        toolbar.setStyleSheet(
            f"QFrame{{background:{COLOR_SURFACE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_CARD}px;}}"
        )
        add_shadow(toolbar, blur=SHADOW_MEDIUM["blur"], color=TEAL_700,
                   alpha=SHADOW_MEDIUM["alpha"], y_offset=SHADOW_MEDIUM["y_offset"])
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(SPACE_16, SPACE_12, SPACE_16, SPACE_12)
        toolbar_layout.setSpacing(SPACE_12)

        search_row = QHBoxLayout()
        search_row.setSpacing(SPACE_12)

        search_icon_lbl = QLabel()
        search_icon_lbl.setPixmap(icon("search", color=COLOR_TEXT_SECONDARY, size=18).pixmap(18, 18))
        search_icon_lbl.setStyleSheet("background:transparent;border:none;")
        search_row.addWidget(search_icon_lbl)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("ابحث بالباركود أو اسم الدواء...")
        self.search_input.setStyleSheet(
            f"QLineEdit{{border:none;background:transparent;font-size:16px;"
            f"font-weight:{FONT_BODY_STRONG[1]};padding:{SPACE_8}px 0;}}"
        )
        self.search_input.setMinimumHeight(44)

        # قائمة اقتراحات طافية خفيفة (أقرب 5 أدوية) بدل فلترة شبكة المنتجات
        # كاملة (لغاية 200 بطاقة) بكل حرف - هذا كان يسبب بطء/تشوّه بصري حتى
        # مع مؤقّت التأخير، لأن حجم إعادة البناء نفسه ثقيل بغض النظر عن
        # توقيته. الحين شبكة المنتجات ما تنلمس إطلاقًا أثناء البحث - تتغيّر
        # بس لما تبدّل تصنيف. القائمة المنسدلة نص خفيف بس (بدون بطاقات)،
        # فإعادة بنائها رخيصة جدًا ومافيها أي تشوّه مهما كانت سرعة الكتابة.
        self.suggestions_popup = QListWidget(self)
        self.suggestions_popup.setWindowFlags(Qt.ToolTip)
        self.suggestions_popup.setAttribute(Qt.WA_ShowWithoutActivating)
        self.suggestions_popup.setFocusPolicy(Qt.NoFocus)
        self.suggestions_popup.setStyleSheet(
            f"QListWidget{{border:1px solid {COLOR_BORDER};border-radius:{RADIUS_INPUT}px;"
            f"background:{COLOR_SURFACE};font-size:13px;padding:2px;}}"
            f"QListWidget::item{{padding:8px 10px;border-radius:6px;}}"
            f"QListWidget::item:selected{{background:{TEAL_50};color:{TEAL_700};font-weight:700;}}"
        )
        self.suggestions_popup.itemClicked.connect(self._on_suggestion_clicked)
        self.suggestions_popup.hide()
        self._current_suggestions = []

        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.timeout.connect(self._update_suggestions)

        # مؤقّت منفصل عشان اكتشاف الباركود تلقائيًا - يشتغل بعد ما الكتابة
        # تتوقف لمدة قصيرة (130 ملي ثانية). قارئ الباركود يكتب كل الأرقام
        # بسرعة عالية جدًا (فرق أقل من عشرة ملي ثانية بين كل رقم)، فبمجرد ما
        # يخلص من إرسال الرقم الأخير، هذا المؤقّت يفصل ويشتغل - نفحص وقتها
        # هل النص يطابق باركود دواء موجود بالضبط، ولو نعم نضيفه للفاتورة
        # ونفرّغ الحقل فورًا، بدون أي حاجة لضغط Enter. هذا ما يتعارض مع
        # الكتابة اليدوية لاسم دواء لأن التطابق ما يصير إلا لو كتب الباركود
        # كامل بالضبط - أي نص جزئي أو اسم ما يفعّله.
        self._barcode_debounce_timer = QTimer(self)
        self._barcode_debounce_timer.setSingleShot(True)
        self._barcode_debounce_timer.timeout.connect(self._try_auto_add_barcode)

        self.search_input.textChanged.connect(lambda: self._search_debounce_timer.start(200))
        self.search_input.textChanged.connect(lambda: self._barcode_debounce_timer.start(130))
        self.search_input.installEventFilter(self)
        # الماسح الضوئي يكتب أرقام الباركود وبعدها يبعث Enter تلقائيًا. لما
        # يكون فيه تطابق باركود بالضبط، نضيف الدواء للسلة فورًا ونفرّغ الحقل
        # على طول - عشان الكاشير يقدر يمسح الباركود التالي مباشرة من دون ما
        # يندمج نصه مع بقايا الباركود السابق (هذا كان يسبب دمج/خطأ بالبحث).
        # ملاحظة: لو قائمة الاقتراحات ظاهرة، eventFilter يلتقط Enter قبل ما
        # توصل هذا الاتصال، فيختار الاقتراح المظلّل بدل منطق الباركود.
        self.search_input.returnPressed.connect(self._on_search_enter)
        search_row.addWidget(self.search_input, stretch=1)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background:{COLOR_BORDER};border:none;")
        search_row.addWidget(divider)

        barcode_btn = _icon_button(
            "barcode", size=40, icon_size=20, color=TEAL_700,
            bg=COLOR_SURFACE_SUBTLE, border=f"1px solid {COLOR_BORDER}",
            hover_bg=TEAL_50, radius=RADIUS_BUTTON,
        )
        barcode_btn.setToolTip("مسح باركود - ضع المؤشر بمربع البحث وامسح (اختصار: F3)")
        barcode_btn.clicked.connect(self.search_input.setFocus)
        search_row.addWidget(barcode_btn)
        toolbar_layout.addLayout(search_row)

        # ---- صف شرائح التصنيفات (قابل للتمرير أفقيًا) ----
        # الارتفاع كافي لصف الشرائح (34px) + هامش + شريط تمرير رفيع تحتها بدون
        # ما يتراكب فوق النص ويخفي حروف اسم التصنيف.
        self.category_scroll = QScrollArea()
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setFrameShape(QFrame.NoFrame)
        self.category_scroll.setFixedHeight(58)
        self.category_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.category_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.category_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:horizontal{height:8px;background:transparent;margin:4px 0 0 0;}"
            f"QScrollBar::handle:horizontal{{background:{COLOR_BORDER};border-radius:4px;min-width:24px;}}"
            f"QScrollBar::handle:horizontal:hover{{background:{TEAL_400};}}"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal{width:0;border:none;background:none;}"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal{background:none;}"
        )
        cat_container = QWidget()
        cat_container.setStyleSheet("background:transparent;")
        cat_container.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.category_row = QHBoxLayout(cat_container)
        self.category_row.setContentsMargins(0, 0, 0, 0)
        self.category_row.setSpacing(SPACE_8)
        self.category_scroll.setWidget(cat_container)
        enable_touch_scroll(self.category_scroll)
        toolbar_layout.addWidget(self.category_scroll)

        right.addWidget(toolbar)

        # ---- شبكة المنتجات ----
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(SPACE_16)
        self.grid_layout.setAlignment(Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.grid_container)
        enable_touch_scroll(scroll)
        right.addWidget(scroll, stretch=1)

        main_layout.addLayout(right, stretch=1)

        self._load_categories()
        self.refresh_products()
        self.search_input.setFocus()

    def refresh(self):
        self.refresh_products()
        self.search_input.setFocus()

    def _safe_user_id(self):
        """يرجّع id المستخدم الحالي بأمان.

        إصلاح دفاعي: self.current_user ممكن يوصل هذي الشاشة وهو "منفصل"
        (Detached) عن أي جلسة SQLAlchemy - يصير هذا لو الجلسة اللي جابته
        أصلًا (مثلًا بشاشة تسجيل الدخول) انسكرت أو صار عليها commit/expire
        بمكان ثاني بالبرنامج قبل ما توصل شاشة البيع. بهذي الحالة حتى قراءة
        .id البسيطة تحاول تعيد التحميل من القاعدة وتنكسر بـ
        DetachedInstanceError - وهذا كان يوقف "إتمام البيع" بالكامل بصمت
        (الاستثناء يصير أول سطر بـ checkout() قبل أي إنشاء فاتورة، فما
        ينحفظ شي وما تطلع أي رسالة للمستخدم).

        ملاحظة نطاق: هذا حل احتياطي هنا بس - السبب الجذري (ليش current_user
        يوصل منفصل أصلًا) موجود بمكان ثاني بالبرنامج (غالبًا إدارة الجلسة
        بشاشة تسجيل الدخول/النافذة الرئيسية) ولازم يتصلح هناك كحل نهائي."""
        if not self.current_user:
            return None
        try:
            return self.current_user.id
        except DetachedInstanceError:
            return None

    def _load_categories(self):
        """يبني شرائح التصنيفات (يحل محل QComboBox القديم) - نفس الاستعلام
        بالضبط، بس معروض كأزرار قابلة للنقر بدل قائمة منسدلة."""
        while self.category_row.count():
            child = self.category_row.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.category_buttons = {}

        cats = sorted({p.category for p in self.session.query(Product).filter(Product.is_active == True).all() if p.category})
        for name in ["الكل"] + cats:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(name == self.selected_category)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(40)
            # Fixed أفقيًا (مو Preferred) حتى ما يقدر الـ layout يضغط الزر أبدًا
            # تحت عرض نصّه الطبيعي (كان هذا سبب قصّ/اختصار أسماء التصنيفات
            # الطويلة سابقًا) - أي زيادة بعرض التصنيفات كلها عن عرض الشاشة
            # يمتصّها التمرير الأفقي بالـ QScrollArea المحيطة، مو ضغط الأزرار.
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setStyleSheet(toggle_chip_stylesheet(name == self.selected_category) + "padding:7px 18px;font-size:13px;")
            btn.clicked.connect(lambda _, n=name: self._select_category(n))
            self.category_row.addWidget(btn)
            self.category_buttons[name] = btn
        self.category_row.addStretch()

    def _select_category(self, name):
        self.selected_category = name
        for cat_name, btn in self.category_buttons.items():
            checked = cat_name == name
            btn.setChecked(checked)
            btn.setStyleSheet(toggle_chip_stylesheet(checked) + "padding:7px 18px;font-size:13px;")
        self.refresh_products()

    def refresh_products(self):
        # setUpdatesEnabled(False) يمنع أي رسم جزئي (ومضة) للشبكة وهي قيد
        # الهدم/إعادة البناء - يبني كل شي أولًا وهو مخفي عن إعادة الرسم،
        # وبعدين يرسمه دفعة وحدة لما يخلص تمامًا. مؤشر الانتظار (ساعة رملية)
        # يعطي إشارة بصرية واضحة إن البرنامج يشتغل، مو متجمّد - خصوصًا
        # بالمخزون الكبير اللي فيه مئات الأدوية.
        self.grid_container.setUpdatesEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._refresh_products_inner()
        finally:
            self.grid_container.setUpdatesEnabled(True)
            QApplication.restoreOverrideCursor()

    def _refresh_products_inner(self):
        # إصلاح "الشاشة البيضة": قبل هذا كنا نفضّي الشبكة المعروضة (grid_layout)
        # هنا مباشرة بأول سطر - قبل حتى ما نعرف شنو المنتجات الجديدة أو نبدأ
        # ببنائها. يعني الشبكة تضل فاضية بصريًا طول فترة البناء التدريجي
        # بالخلفية (ممكن ياخذ عدة "دفعات" لو المعروض قريب من 200 بطاقة) -
        # وهذا بالضبط سبب الشاشة البيضة المؤقتة بكل فتحة لصفحة البيع أو
        # تبديل تصنيف. الحين ما نلمس الشبكة المعروضة إطلاقًا بهذا الموضع -
        # البطاقات القديمة تضل ظاهرة زي ماهي بالضبط لحد ما البطاقات الجديدة
        # تخلص بناء كامل بالخلفية، وبعدين نبدّلها بخطوة وحدة أخيرة (بآخر
        # _build_next_batch) تمسح القديم وتضيف الجديد بنفس اللحظة - فما فيه
        # أي لحظة وسيطة "فاضية" يشوفها المستخدم إطلاقًا.

        # عدّاد "جيل البناء" - لو المستخدم بدّل تصنيف أو تغيّر البحث أثناء
        # ما لسه دفعة بطاقات سابقة قيد البناء التدريجي (batching بالأسفل)،
        # هذا يضمن الدفعة القديمة توقف نفسها فورًا بدل ما تكمل تبني بطاقات
        # لمنتجات ما عادت مطلوبة وتتعارض مع البناء الجديد.
        self._build_generation = getattr(self, "_build_generation", 0) + 1

        cat = self.selected_category
        text = self.search_input.text().strip()

        # ملاحظة أداء مهمة (السبب الحقيقي وراء بطء فتح صفحة البيع بعد إضافة
        # آلاف الأدوية): الكود القديم كان يجيب كل الأدوية النشطة (query.all())
        # مع كل الدفعات المرتبطة (joinedload batches) للكتالوج كامل، يرتبها
        # بالذاكرة، وبعدين يقصّها لأول 200 - يعني تكلفة الجلب والفرز كانت
        # تكبر مع حجم الكتالوج الكامل (12-18 ألف دواء)، رغم إن المعروض فعليًا
        # ثابت دائمًا عند 200 كحد أقصى. الحين نحدد أول الـ(id) المطلوبين فقط
        # بقاعدة البيانات نفسها (ترتيب + حد أقصى)، ونجيب النسخة الكاملة (مع
        # الدفعات) بس لهذي المجموعة المحدودة - فتكلفة الجلب تضل ثابتة عند
        # ≤200 بغض النظر عن حجم الكتالوج الكامل.
        if text:
            # فرع بحث نادر التفعيل (يصير بس لو تصنيف تغيّر وفيه نص متبقي
            # بمربع البحث، بما إن الكتابة العادية صارت تستخدم قائمة اقتراحات
            # منفصلة ما تلمس هذي الشبكة). نجيب أعمدة خفيفة بس (بدون دفعات)
            # للفلترة بالذاكرة - أخف بكثير من جلب المنتج كامل لكل الكتالوج.
            light_query = self.session.query(Product.id, Product.name, Product.generic_name, Product.barcode).filter(Product.is_active == True)
            if cat and cat not in ("الكل", "كل التصنيفات"):
                light_query = light_query.filter(Product.category == cat)
            light_rows = light_query.all()
            norm_text = normalize_arabic(text)
            matched_ids = [
                pid for pid, name, generic, barcode in light_rows
                if norm_text in normalize_arabic(name)
                or (generic and norm_text in normalize_arabic(generic))
                or (barcode and text in barcode)
            ]
            exact_barcode_ids = [pid for pid, name, generic, barcode in light_rows if barcode == text]
            if exact_barcode_ids:
                matched_ids = exact_barcode_ids
            selected_ids = matched_ids[:200]
        else:
            # الوضع الافتراضي (الأكثر تفعيلًا - أي فتحة لصفحة البيع أو تبديل
            # تصنيف): نرتب حسب الأكثر مبيعًا مباشرة بقاعدة البيانات (LEFT
            # JOIN مع مجموع مبيعات كل دواء)، ونجيب أول 200 (id) بس - قلّلناها
            # من 500 لـ200 لتسريع فتح الصفحة أكثر (كل دواء إضافي بالشبكة
            # يعني بطاقة Qt كاملة لازم تُبنى وتُرسم).
            sales_totals_sq = (
                self.session.query(
                    Batch.product_id.label("product_id"),
                    func.sum(InvoiceItem.quantity).label("qty"),
                )
                .join(InvoiceItem, InvoiceItem.batch_id == Batch.id)
                .group_by(Batch.product_id)
                .subquery()
            )
            ranked_query = self.session.query(Product.id).filter(Product.is_active == True)
            if cat and cat not in ("الكل", "كل التصنيفات"):
                ranked_query = ranked_query.filter(Product.category == cat)
            ranked_query = (
                ranked_query
                .outerjoin(sales_totals_sq, sales_totals_sq.c.product_id == Product.id)
                .order_by(func.coalesce(sales_totals_sq.c.qty, 0).desc(), Product.name)
                .limit(200)
            )
            selected_ids = [row[0] for row in ranked_query.all()]

        # الجلب الكامل (مع الدفعات) يصير بس لهذي المجموعة المحدودة (≤200) -
        # هذا الجزء الوحيد اللي يدفع تكلفة joinedload(batches)، بغض النظر
        # عن حجم الكتالوج الكامل.
        if selected_ids:
            fetched = (
                self.session.query(Product)
                .options(joinedload(Product.batches))
                .filter(Product.id.in_(selected_ids))
                .all()
            )
            products_by_id = {p.id: p for p in fetched}
            products = [products_by_id[pid] for pid in selected_ids if pid in products_by_id]
        else:
            products = []

        # كان يفتح استعلام ProductUnit + استعلامي بدائل (يدوي وبنفس المادة
        # الفعالة) منفصلين لكل منتج - يعني لغاية ~180 استعلام بكل فتح/فلترة
        # لصفحة البيع مع 60 دواء! هذا كان السبب الأساسي لبطء التنقل من/إلى
        # صفحة البيع. نجيب كل شي دفعة وحدة بنداءات IN(...) قليلة بدل ذلك،
        # بنفس منطق الوحدات والبدائل بالضبط (نفس الترتيب، نفس إزالة التكرار).
        product_ids = [p.id for p in products]
        units_by_product = {}
        if product_ids:
            all_units = (
                self.session.query(ProductUnit)
                .filter(ProductUnit.product_id.in_(product_ids))
                .order_by(ProductUnit.conversion_factor)
                .all()
            )
            for u in all_units:
                units_by_product.setdefault(u.product_id, []).append(u)

        manual_alt_by_product = {}
        if product_ids:
            manual_alts = (
                self.session.query(ProductAlternative)
                .filter(ProductAlternative.product_id.in_(product_ids))
                .all()
            )
            for a in manual_alts:
                manual_alt_by_product.setdefault(a.product_id, []).append(a.alternative_product_id)

        generic_names = {p.generic_name for p in products if p.generic_name}
        same_generic_by_name = {}
        if generic_names:
            same_generic_products = (
                self.session.query(Product)
                .filter(Product.generic_name.in_(generic_names))
                .all()
            )
            for gp in same_generic_products:
                same_generic_by_name.setdefault(gp.generic_name, []).append(gp)

        if not products:
            # حالة فارغة: ماكو بطاقات جديدة قادمة تبدّل القديمة، فهذا الفرع
            # الوحيد اللي لازم يمسح الشبكة المعروضة صراحة هنا (قبل ما يعرض
            # رسالة "ماكو نتائج") - عكس الفرع الطبيعي (فيه منتجات) اللي
            # يأجّل أي مسح للشبكة لحد ما تكون البطاقات الجديدة جاهزة بالكامل.
            self._clear_grid()
            self._current_cards = []
            self._grid_col_count = None
            if self._grid_stretch_row is not None:
                self.grid_layout.setRowStretch(self._grid_stretch_row, 0)
            self._grid_stretch_row = None
            empty_frame = QFrame()
            empty_frame.setStyleSheet("background:transparent;border:none;")
            empty_layout = QVBoxLayout(empty_frame)
            empty_layout.setContentsMargins(0, 40, 0, 40)
            empty_layout.setSpacing(SPACE_8)
            icon_lbl = QLabel()
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setStyleSheet("background:transparent;border:none;")
            icon_lbl.setPixmap(icon("search", color=COLOR_TEXT_SECONDARY, size=32).pixmap(32, 32))
            empty_layout.addWidget(icon_lbl)
            msg_lbl = QLabel("ماكو أدوية مطابقة للبحث." if self.search_input.text().strip()
                              else "ماكو أدوية بهذا التصنيف حاليًا.")
            msg_lbl.setAlignment(Qt.AlignCenter)
            msg_lbl.setStyleSheet(f"color:{COLOR_TEXT_SECONDARY};font-size:14px;font-weight:600;background:transparent;border:none;")
            empty_layout.addWidget(msg_lbl)
            hint_lbl = QLabel("جرّب كلمة بحث ثانية أو تأكد من الباركود.")
            hint_lbl.setAlignment(Qt.AlignCenter)
            hint_lbl.setStyleSheet(f"color:{COLOR_TEXT_SECONDARY};font-size:12px;background:transparent;border:none;")
            empty_layout.addWidget(hint_lbl)
            self.grid_layout.addWidget(empty_frame, 0, 0)
            return

        # حل جذري: نبني كل البطاقات بالخلفية على دفعات (عشان الواجهة تضل
        # مستجيبة وما "تتجمد" أثناء البناء)، بس ما نضيف ولا وحدة منها
        # للشبكة الفعلية (grid_layout) إلا بعد ما تخلص كل البطاقات. بهذي
        # الطريقة ما فيه أي حالة "نص مبنية" تنعرض للمستخدم إطلاقًا - والشبكة
        # تنتقل من محتواها القديم لمحتواها النهائي الجديد بخطوة وحدة نهائية،
        # فما فيه أي تمدد أو تداخل أو قفز ممكن يصير أصلاً (لأنه ما فيه "قبل"
        # يشوفه المستخدم بينهم).
        self._pending_build_products = products
        self._pending_build_index = 0
        self._pending_build_units = units_by_product
        self._pending_build_manual_alt = manual_alt_by_product
        self._pending_build_generic = same_generic_by_name
        self._pending_build_generation = self._build_generation
        # بطاقات الجيل الجديد تتجمّع هنا وهي "غير مرئية" (مو مضافة لأي
        # تخطيط) - self._current_cards يضل يشاور على بطاقات الجيل *القديم*
        # (المعروضة فعليًا بالشبكة حاليًا) لحد ما نبدّلها دفعة وحدة بآخر
        # _build_next_batch.
        self._pending_build_cards = []
        self._build_next_batch()

    def _clear_grid(self):
        """يمسح كل عناصر الشبكة المعروضة حاليًا (بطاقات أو رسالة 'ماكو
        نتائج'). نستدعيها بس باللحظة اللي عندنا فيها بديل جاهز فعليًا -
        عشان الشبكة ما تضل فاضية بصريًا بأي لحظة وسيطة."""
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _build_next_batch(self, batch_size=40):
        if self._pending_build_generation != self._build_generation:
            return  # صار refresh جديد أثناء البناء - نلغي إكمال الدفعة القديمة

        products = self._pending_build_products
        start = self._pending_build_index
        end = min(start + batch_size, len(products))

        for p in products[start:end]:
            units = self._pending_build_units.get(p.id, [])
            manual_ids = self._pending_build_manual_alt.get(p.id, [])
            auto_ids = (
                [gp.id for gp in self._pending_build_generic.get(p.generic_name, []) if gp.id != p.id]
                if p.generic_name else []
            )
            p.alt_ids = list(dict.fromkeys(manual_ids + auto_ids))  # إزالة التكرار مع الحفاظ على الترتيب
            card = ProductCard(p, units, on_add=self._add_to_cart, on_show_alt=self._show_alternatives)
            # ملاحظة مهمة: البطاقة تُبنى بس هنا (كائن Qt بالذاكرة) - ما تُضاف
            # لأي تخطيط (layout) مرئي إطلاقًا لين تخلص كل الدفعات. هذا هو
            # جوهر الحل الجذري. تنضاف لـ_pending_build_cards (الجيل الجديد)
            # مو لـ_current_cards - عشان self._current_cards يضل يشاور على
            # بطاقات الجيل القديم المعروضة فعليًا بالشبكة، وتضل ظاهرة زي
            # ماهي للمستخدم طول فترة البناء بالخلفية.
            self._pending_build_cards.append(card)

        self._pending_build_index = end

        if end < len(products):
            QTimer.singleShot(0, self._build_next_batch)
        else:
            # خلصت كل الدفعات - الحين وبس الحين نمسح بطاقات الجيل القديم
            # (المعروضة لحد هذي اللحظة) ونعرض الجديد، بخطوتين متتاليتين
            # فوريتين بدون رجوع لحلقة الأحداث بينهم - فما فيه أي لحظة وسيطة
            # "فاضية" يقدر المستخدم يشوفها، وينتقل العرض من القديم للجديد
            # بشكل يبدو فوري ودفعة وحدة.
            self._clear_grid()
            self._current_cards = self._pending_build_cards
            self._populate_grid(self._current_cards)

    def _populate_grid(self, cards, min_card_width=300):
        """يوزّع بطاقات المنتجات على شبكة بعدد أعمدة يتلاءم مع عرض النافذة
        الحالي (أساس الاستجابة/Responsive). تُستدعى مرة وحدة بس بعد ما تخلص
        كل البطاقات (من _build_next_batch)، أو من resizeEvent عند تغيّر
        حجم النافذة فعليًا."""
        if not cards:
            return
        available_width = max(self.grid_container.width(), min_card_width)
        self._grid_col_count = max(1, available_width // min_card_width)
        col_count = self._grid_col_count
        for i, card in enumerate(cards):
            self.grid_layout.addWidget(card, i // col_count, i % col_count)
        # تأكيد إضافي فوق setAlignment(Qt.AlignTop): نعطي "صف" وهمي فاضي بعد
        # آخر صف فعلي كل المساحة الإضافية (stretch factor) - يمنع Qt من
        # توزيع أي مساحة فاضية على صفوف البطاقات الحقيقية.
        if self._grid_stretch_row is not None:
            self.grid_layout.setRowStretch(self._grid_stretch_row, 0)
        last_row = (len(cards) - 1) // col_count
        self.grid_layout.setRowStretch(last_row + 1, 1)
        self._grid_stretch_row = last_row + 1

    def hideEvent(self, event):
        super().hideEvent(event)
        # قائمة الاقتراحات (suggestions_popup) نافذة طافية مستقلة (Qt.ToolTip)
        # عن قصد (عشان ما تسرق التركيز من مربع البحث) - بس هذا يعني إنها ما
        # تنقفل تلقائيًا لما تتنقل لصفحة ثانية زي أي عنصر عادي تابع للصفحة.
        # هذا الحدث يشتغل تلقائيًا أي وقت صفحة البيع تختفي (تبديل لصفحة
        # ثانية)، فنسكر القائمة يدويًا بنفس اللحظة.
        self._hide_suggestions()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_cards:
            min_card_width = 300
            available_width = max(self.grid_container.width(), min_card_width)
            new_col_count = max(1, available_width // min_card_width)
            # نعيد توزيع البطاقات بس لو عدد الأعمدة فعليًا تغيّر - تغيّر بسيط
            # بالعرض (زي ظهور/اختفاء شريط تمرير أثناء زيادة الارتفاع) ما
            # يغيّر النتيجة النهائية غالبًا، فما داعي نحرّك شي بلا داعي.
            if new_col_count != self._grid_col_count:
                self._populate_grid(self._current_cards)

    def _alternative_ids_for(self, product):
        """يرجع كل البدائل الممكنة: المسجلة يدويًا + أي دواء ثاني بنفس المادة الفعالة."""
        manual_ids = [a.alternative_product_id for a in
                      self.session.query(ProductAlternative).filter_by(product_id=product.id).all()]
        auto_ids = []
        if product.generic_name:
            same_generic = (
                self.session.query(Product)
                .filter(Product.generic_name == product.generic_name, Product.id != product.id)
                .all()
            )
            auto_ids = [p.id for p in same_generic]
        return list(dict.fromkeys(manual_ids + auto_ids))  # إزالة التكرار مع الحفاظ على الترتيب

    def _get_alt_unit(self, product_id, current_unit_id):
        """يرجّع (unit_id, unit_name, unit_price, conversion_factor) للوحدة
        البديلة التالية لنفس الدواء (يدور بينهم لو أكثر من وحدتين)، أو None
        لو ماكو إلا وحدة وحدة معرّفة له. تُستخدم من زر تبديل الوحدة
        (شريط ↔ علبة) بالفاتورة. conversion_factor مضافة عشان InvoicePanel
        يقدر يحسب فحص المخزون الدقيق مراعيًا الأسطر الثانية بالسلة."""
        units = (
            self.session.query(ProductUnit)
            .filter_by(product_id=product_id)
            .order_by(ProductUnit.conversion_factor)
            .all()
        )
        if len(units) < 2:
            return None
        idx = next((i for i, u in enumerate(units) if u.id == current_unit_id), None)
        if idx is None:
            return None
        next_unit = units[(idx + 1) % len(units)]
        product = self.session.query(Product).get(product_id)
        price = unit_sale_price(product, next_unit)
        return (next_unit.id, next_unit.unit_name, price, next_unit.conversion_factor)

    def _refresh_cards_stock(self, cart_items):
        """يحدّث رقم المخزون بس على البطاقات المتأثرة بعملية بيع/إرجاع، بدون
        أي إعادة بناء لباقي الشبكة - قبل هذا كنا نستدعي refresh_products()
        بعد كل عملية بيع، وهذا كان يعيد بناء الـ200 بطاقة كاملة من الصفر
        (تفريغ الشبكة ثم بناء تدريجي من جديد) بس عشان نحدّث أرقام مخزون
        قليلة - وهذا يسبب ومضة/تمدد بصري مؤقت بعد كل عملية بيع رغم إصلاحات
        الاستقرار بالبناء التدريجي، لأنه فعليًا "يفرّغ ويعيد" الشبكة أمام
        عين المستخدم كل مرة."""
        affected_ids = {item["product_id"] for item in cart_items}
        for card in self._current_cards:
            if card.product.id in affected_ids:
                self.session.refresh(card.product)  # يجيب كمية الدفعات المحدّثة من قاعدة البيانات
                card.refresh_stock()

    def _available_base(self, product_id):
        """مجموع الكمية المتوفرة الحالية بوحدة الأساس (شريط) لهذا الدواء عبر
        كل الدفعات بقاعدة البيانات - بدون أي علم بمحتوى السلة. يُستخدم من
        InvoicePanel (available_base_checker) عشان يحسب المتبقي الحقيقي مع
        طرح أي كمية محجوزة أصلًا بأسطر ثانية بالسلة لنفس الدواء بوحدة
        مختلفة (شريط/علبة سوا)."""
        product = self.session.query(Product).get(product_id)
        if not product:
            return 0
        return sum(b.quantity_available for b in product.batches)

    def _max_addable(self, product_id, unit_id):
        """أقصى كمية تقدر تضيفها بهذي الوحدة حسب المخزون الفعلي المتوفر
        بالقاعدة (بدون مراعاة السلة - هذا الجزء يصير بمستوى InvoicePanel
        عبر available_base_checker/_max_qty_for_line)."""
        unit = self.session.query(ProductUnit).get(unit_id)
        if not unit:
            return 0
        return self._available_base(product_id) // unit.conversion_factor

    def _on_search_enter(self):
        """يشتغل لما يضغط Enter بمربع البحث (بعض قارئات الباركود تسويها
        تلقائيًا بعد ما تكتب رقم الباركود). لو النص يطابق باركود دواء موجود
        بالضبط، نضيفه للسلة مباشرة بوحدته الأساسية ونفرّغ الحقل - عشان يصير
        جاهز لمسح الباركود التالي على طول من دون أي دمج بين الباركودات.

        لو الحقل فاضي وضغط Enter وفيه أصناف بالسلة فعلاً، نعتبرها نية
        إتمام البيع (خلص من مسح كل الباركودات) ونضغط زر "إتمام البيع"
        تلقائيًا. ملاحظة إصلاح: هذا نستخدم فيه نفس معالج Enter الموجود
        أصلًا لمربع البحث (مجرد امتداد لمنطقه) - بدون أي QShortcut جديد،
        لأن محاولة سابقة بربط Enter كاختصار منفصل بكل صفحة البيع كانت
        تتفعّل بالغلط أثناء الكتابة بحقول ثانية (الخصم، بيانات الزبون
        بالدين) وتُتمم البيع قبل ما يخلص المستخدم فعلاً - هذا الأسلوب أدق
        وما يتعارض مع أي حقل ثاني، لأنه مربوط بمربع البحث/الباركود تحديدًا.

        قارئات الباركود اللي *ما* ترسل Enter تلقائيًا يغطّيها مؤقّت
        _try_auto_add_barcode بدل هذا (يشتغل بمجرد توقف الكتابة)."""
        # لو مؤقّت اكتشاف الباركود التلقائي سبق وأضاف الدواء وفرّغ الحقل
        # (يصير أسرع من وصول Enter أحيانًا)، ما فيه شي نسويه هنا - الحقل
        # فاضي فعلاً فراح تنفّذ منطق "إتمام البيع" تحت لو فيه سلة، وهذا
        # سلوك مقصود ومطابق تمامًا لما لو ضغط المستخدم Enter بحقل فاضي عمدًا.
        text = self.search_input.text().strip()
        if not text:
            if self.invoice_panel.cart:
                self.invoice_panel._checkout()
            return
        self._try_add_by_barcode(text)

    def _try_auto_add_barcode(self):
        """يشتغل بعد ما الكتابة بمربع البحث تتوقف لمدة قصيرة (130ms) -
        يغطّي قارئات الباركود اللي ما ترسل Enter تلقائيًا بعد رقم الباركود.
        لو النص يطابق باركود دواء بالضبط، يضيفه للسلة ويفرّغ الحقل فورًا،
        بدون أي حاجة لضغط Enter يدويًا."""
        text = self.search_input.text().strip()
        if not text:
            return
        self._try_add_by_barcode(text)

    def _try_add_by_barcode(self, text):
        """يفحص هل النص المُعطى يطابق باركود دواء موجود بالضبط، ولو نعم
        يضيفه للسلة بوحدته الأساسية ويفرّغ مربع البحث. يرجع True لو انضاف
        الدواء، و False لو ما فيه تطابق (يمكن المستخدم يكتب اسم دواء)."""
        product = (
            self.session.query(Product)
            .filter(Product.barcode == text, Product.is_active == True)
            .first()
        )
        if not product:
            # مافي تطابق باركود بالضبط - المستخدم يمكن يكتب اسم دواء بعد
            # (بحث نصي عادي)، فما نسوي أي إضافة تلقائية أو نفرّغ الحقل.
            return False
        units = (
            self.session.query(ProductUnit)
            .filter_by(product_id=product.id)
            .order_by(ProductUnit.conversion_factor)
            .all()
        )
        if not units:
            QMessageBox.warning(self, "تنبيه", f"لا توجد وحدة قياس معرّفة لدواء {product.name}.")
            return False
        base_unit = units[0]  # أصغر معامل تحويل = الوحدة الأساسية (عادة "شريط")
        self._add_to_cart(product, base_unit)
        return True

    def eventFilter(self, obj, event):
        """يلتقط أسهم ↑↓ وEnter وEsc بمربع البحث لما تكون قائمة الاقتراحات
        ظاهرة، ويتحكم فيها مباشرة - بدون ما ينقل التركيز (focus) من مربع
        البحث للقائمة نفسها، عشان المستخدم يقدر يكمل يكتب أو يتنقل بالأسهم
        بنفس اللحظة براحته، تمامًا زي أي قائمة اقتراحات بحث معتادة."""
        if obj is self.search_input and self.suggestions_popup.isVisible():
            if event.type() == QEvent.KeyPress:
                key = event.key()
                if key == Qt.Key_Down:
                    row = self.suggestions_popup.currentRow()
                    self.suggestions_popup.setCurrentRow(min(row + 1, self.suggestions_popup.count() - 1))
                    return True
                if key == Qt.Key_Up:
                    row = self.suggestions_popup.currentRow()
                    self.suggestions_popup.setCurrentRow(max(row - 1, 0))
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    row = self.suggestions_popup.currentRow()
                    if row >= 0:
                        self._select_suggestion(row)
                        return True
                if key == Qt.Key_Escape:
                    self._hide_suggestions()
                    return True
        return super().eventFilter(obj, event)

    def _update_suggestions(self):
        """استعلام خفيف (حد أقصى 5 نتائج) يشتغل بعد توقف قصير عن الكتابة -
        هذا رخيص جدًا مقارنة بإعادة بناء شبكة المنتجات (لغاية 200 بطاقة)،
        فما يسبب أي بطء أو تشوّه بصري مهما كانت سرعة الكتابة أو الحذف."""
        text = self.search_input.text().strip()
        if len(text) < 2:
            self._hide_suggestions()
            return
        norm_text = normalize_arabic(text)
        candidates = (
            self.session.query(Product)
            .filter(Product.is_active == True)
            .filter(Product.name.ilike(f"%{text}%"))
            .order_by(Product.name)
            .limit(5)
            .all()
        )
        if not candidates:
            # fallback بسيط للأسماء اللي فيها همزات/تشكيل مختلف
            wider = (
                self.session.query(Product)
                .filter(Product.is_active == True)
                .order_by(Product.name)
                .limit(500)
                .all()
            )
            candidates = [p for p in wider if norm_text in normalize_arabic(p.name)][:5]
        self._show_suggestions(candidates)

    def _show_suggestions(self, products):
        self._current_suggestions = products
        self.suggestions_popup.clear()
        if not products:
            self._hide_suggestions()
            return
        for p in products:
            stock = sum(b.quantity_available for b in p.batches)
            price = p.sale_price or 0
            item = QListWidgetItem(f"{p.name}   -   {fmt_money(price)}   -   متوفر: {stock}")
            self.suggestions_popup.addItem(item)
        self.suggestions_popup.setCurrentRow(0)
        self._position_suggestions_popup()
        self.suggestions_popup.show()

    def _position_suggestions_popup(self):
        pos = self.search_input.mapToGlobal(self.search_input.rect().bottomLeft())
        self.suggestions_popup.move(pos)
        row_h = 36
        self.suggestions_popup.resize(
            max(self.search_input.width(), 260),
            min(row_h * len(self._current_suggestions) + 8, row_h * 5 + 8),
        )

    def _hide_suggestions(self):
        self.suggestions_popup.hide()
        self._current_suggestions = []

    def _on_suggestion_clicked(self, item):
        self._select_suggestion(self.suggestions_popup.row(item))

    def _select_suggestion(self, row):
        if row < 0 or row >= len(self._current_suggestions):
            return
        product = self._current_suggestions[row]
        units = (
            self.session.query(ProductUnit)
            .filter_by(product_id=product.id)
            .order_by(ProductUnit.conversion_factor)
            .all()
        )
        if not units:
            QMessageBox.warning(self, "تنبيه", f"لا توجد وحدة قياس معرّفة لدواء {product.name}.")
            return
        self._hide_suggestions()
        self._add_to_cart(product, units[0])

    def _add_to_cart(self, product, unit):
        if self._max_addable(product.id, unit.id) < 1:
            QMessageBox.warning(self, "تنبيه", f"المخزون منتهي لدواء {product.name}.")
            return
        sale_price = unit_sale_price(product, unit)
        self.invoice_panel.add_item(product, unit, sale_price)
        self._check_interactions()
        # نفرّغ مربع البحث تلقائيًا بعد أي إضافة ناجحة للفاتورة (سواء بالضغط
        # على بطاقة منتج من نتائج البحث، أو بمسح باركود) - عشان المستخدم
        # يصير جاهز يدور عن الدواء التالي فورًا بدون ما يمسح يدويًا.
        self.search_input.clear()
        self.search_input.setFocus()

    def _check_interactions(self):
        product_ids = {item["product_id"] for item in self.invoice_panel.cart}
        if len(product_ids) < 2:
            self.invoice_panel.set_warning(None)
            return
        interactions = self.session.query(DrugInteraction).filter(
            DrugInteraction.product_id_a.in_(product_ids),
            DrugInteraction.product_id_b.in_(product_ids),
        ).all()
        if not interactions:
            self.invoice_panel.set_warning(None)
            return
        lines = []
        for it in interactions:
            a = self.session.query(Product).get(it.product_id_a)
            b = self.session.query(Product).get(it.product_id_b)
            lines.append(f"⚠️ تداخل دوائي ({it.severity}): {a.name} + {b.name}\n{it.description}")
        self.invoice_panel.set_warning("\n\n".join(lines))

    def _show_alternatives(self, product):
        dialog = AlternativesDialog(self.session, product, parent=self)
        dialog.exec()
        # إصلاح: قبل كان يعيد بناء شبكة المنتجات كاملة (لغاية 200 بطاقة) بكل
        # مرة تُسكر فيها هذي النافذة - حتى لو المستخدم بس تفرّج وما عدّل أي
        # شي - وهذا يفرّغ الشبكة ويبنيها من جديد تدريجيًا، فتظهر ومضة/بياض
        # مؤقت بالواجهة بكل مرة.
        # الحين: (1) ما نسوي أي شي لو ماكو تعديل فعلي (dialog.changed=False)،
        # و(2) حتى لو صار تعديل، نحدّث زر "بدائل" بس بنفس البطاقة المتأثرة
        # (نفس أسلوب تحديث المخزون بعد البيع بـ_refresh_cards_stock) بدل
        # هدم/بناء الشبكة بالكامل - فما يصير أي بياض إطلاقًا بأي الحالتين.
        if not dialog.changed:
            return
        product.alt_ids = self._alternative_ids_for(product)
        for card in self._current_cards:
            if card.product.id == product.id:
                card.refresh_alt_button(len(product.alt_ids) > 0)
                break

    def checkout(self, cart_items, discount, payment_method="كاش", debtor_name="", debtor_phone=""):
        """نقطة الدخول الوحيدة لإتمام البيع/الإرجاع من InvoicePanel. ترجع
        True لو نجحت العملية وانحفظت فعليًا بقاعدة البيانات، أو False لو
        فشلت لأي سبب (السلة تضل كما هي عند المستخدم بالحالتين).

        إصلاح مهم: قبل هذا ماكان فيه أي حماية حول عملية البيع - أي استثناء
        غير متوقع (مشكلة اتصال بقاعدة البيانات، تعارض قيد فريد برقم
        الفاتورة، صنف انحذف بلحظة الدفع، جلسة مستخدم منفصلة detached...)
        كان يطيح بصمت من نص العملية، والفاتورة تضل "معلّقة" بالجلسة (غير
        محفوظة وغير متراجع عنها بـ rollback) - أي عملية بيع تالية بنفس
        الجلسة ممكن تتلخبط بسبب هذا الشي المعلّق. وبنفس الوقت InvoicePanel
        كان يفرّغ سلة المستخدم بشكل أعمى بكل الحالات (حتى لو فشلت العملية)،
        فيخسر كل الأصناف اللي أضافها بدون ما يصير بيع فعلي.

        الحل: نلف كل منطق البيع الفعلي بـ try/except هنا. لو صار أي خطأ:
        نتراجع فورًا عن أي تغيير معلّق بالجلسة (session.rollback())، نعرض
        رسالة واضحة للكاشير بدل الصمت، ونرجع False - وInvoicePanel (اللي
        عدّلناه بالمقابل) ما يفرّغ السلة إلا لو رجعت True."""
        try:
            return self._checkout_inner(cart_items, discount, payment_method, debtor_name, debtor_phone)
        except Exception as e:
            self.session.rollback()
            QMessageBox.critical(
                self, "تعذّر إتمام البيع",
                "صار خطأ غير متوقع أثناء إتمام البيع، وما انحفظ أي شي "
                "بقاعدة البيانات. جرّب مرة ثانية، ولو تكرر الخطأ راجع "
                "الدعم الفني.\n\n"
                f"تفاصيل تقنية: {e}"
            )
            return False

    def _checkout_inner(self, cart_items, discount, payment_method="كاش", debtor_name="", debtor_phone=""):
        """ينشئ الفاتورة فعليًا بقاعدة البيانات. لو طريقة الدفع "إرجاع": يرجّع المخزون ويخصم القيمة من الإيراد."""
        subtotal = sum(i["unit_price"] * i["qty"] for i in cart_items)
        final_amount = max(subtotal - discount, 0)

        if payment_method == "إرجاع":
            invoice = Invoice(
                user_id=self._safe_user_id(),
                invoice_number=f"RET-{int(datetime.utcnow().timestamp())}",
                payment_status="مرتجع",
                total_amount=-subtotal, discount=discount, final_amount=-final_amount,
            )
            self.session.add(invoice)
            self.session.flush()
            for item in cart_items:
                product = self.session.query(Product).get(item["product_id"])
                unit = self.session.query(ProductUnit).get(item["unit_id"])
                base_qty = item["qty"] * unit.conversion_factor
                # نحسب تكلفة الوحدة *قبل* ما نضيف الكمية المرتجعة للدفعات، حتى المعدل
                # يعكس تكلفة الشراء الفعلية اللي كانت موجودة وقت البيع الأصلي، مو
                # التكلفة بعد ما ترجع الكمية (اللي ممكن تغيّر المعدل المرجّح).
                item_unit_cost = unit_purchase_cost(product, unit)
                batches = sorted(product.batches, key=lambda b: (b.expiry_date or datetime.max.date()), reverse=True)
                if batches:
                    batch = batches[0]
                    batch.quantity_available += base_qty
                else:
                    batch = Batch(product_id=product.id, batch_number="RETURN", quantity_received=0,
                                   quantity_available=base_qty, purchase_price=item_unit_cost)
                    self.session.add(batch)
                    self.session.flush()
                self.session.add(StockMovement(
                    batch_id=batch.id, unit_id=item["unit_id"], movement_type="إرجاع",
                    quantity=base_qty, note=f"إرجاع {invoice.invoice_number}",
                ))
                self.session.add(InvoiceItem(
                    invoice_id=invoice.id, batch_id=batch.id, unit_id=item["unit_id"],
                    quantity=item["qty"], unit_price=item["unit_price"], subtotal=-(item["unit_price"] * item["qty"]),
                    unit_cost=item_unit_cost,
                ))
            self.session.add(Payment(invoice_id=invoice.id, amount=-final_amount, payment_method="كاش"))
            self.session.commit()
            self._auto_print_invoice(invoice)
            QMessageBox.information(self, "تم الإرجاع",
                                     f"تم إرجاع المنتجات للمخزون وخصم {fmt_money(final_amount)} من الإيراد.")
            self._refresh_cards_stock(cart_items)
            return True

        customer = None
        if payment_method == "دين":
            customer = self.session.query(Customer).filter_by(name=debtor_name, phone=debtor_phone).first()
            if not customer:
                customer = Customer(name=debtor_name, phone=debtor_phone, current_balance=0)
                self.session.add(customer)
                self.session.flush()

        # ---- إصلاح مهم: منع البيع بمخزون ناقص فعليًا (مو بس تحذير) ----
        # قبل هذا الإصلاح، لو المخزون ما يكفي أثناء تنفيذ البيع، النظام كان
        # يحذّر بس **يكمل** إنشاء الفاتورة وسحب المخزون لحد ما يخلص (احتمال
        # يوصل المخزون لسالب أو يبيع كمية وهمية غير موجودة فعليًا). هنا نتحقق
        # **قبل** أي كتابة بقاعدة البيانات (قبل حتى إنشاء الفاتورة) من إن كل
        # صنف بالسلة عنده مخزون كافي فعليًا - نجمع الكمية المطلوبة من كل صنف
        # عبر كل أسطر السلة (لو نفس الدواء تكرر بوحدات مختلفة)، ونقارنها
        # بالمخزون الحقيقي الحالي. لو فيه أي نقص، نوقف البيع بالكامل ولا
        # ننشئ فاتورة ولا نلمس أي دفعة - يرجع المستخدم يعدّل السلة بدل ما
        # يصير بيع جزئي أو مخزون سالب.
        needed_by_product = {}
        for item in cart_items:
            unit = self.session.query(ProductUnit).get(item["unit_id"])
            base_qty = item["qty"] * (unit.conversion_factor if unit else 1)
            needed_by_product[item["product_id"]] = needed_by_product.get(item["product_id"], 0) + base_qty

        shortages = []
        for product_id, needed in needed_by_product.items():
            product = self.session.query(Product).get(product_id)
            if not product:
                continue
            available = sum(b.quantity_available for b in product.batches)
            if needed > available:
                shortages.append(f"• {product.name}: مطلوب {needed:.0f} شريط، المتوفر {available:.0f} بس")

        if shortages:
            QMessageBox.critical(
                self, "تعذّر إتمام البيع - مخزون غير كافٍ",
                "ما فيه مخزون كافي لإتمام هذا البيع. عدّل الكمية أو احذف الصنف من السلة:\n\n"
                + "\n".join(shortages),
            )
            return False

        invoice = Invoice(
            user_id=self._safe_user_id(),
            customer_id=customer.id if customer else None,
            invoice_number=f"INV-{int(datetime.utcnow().timestamp())}",
            payment_status="آجل" if payment_method == "دين" else "نقدي",
            total_amount=subtotal,
            discount=discount,
            final_amount=final_amount,
        )
        self.session.add(invoice)
        self.session.flush()

        for item in cart_items:
            product = self.session.query(Product).get(item["product_id"])
            unit = self.session.query(ProductUnit).get(item["unit_id"])
            needed = item["qty"] * unit.conversion_factor  # بوحدة الأساس

            batches = sorted(
                [b for b in product.batches if b.quantity_available > 0],
                key=lambda b: (b.expiry_date or datetime.max.date())
            )
            remaining = needed
            total_base_cost = 0   # مجموع تكلفة كل الوحدات الأساس اللي انسحبت، عبر كل الدفعات
            first_batch = None
            for batch in batches:
                if remaining <= 0:
                    break
                take = min(batch.quantity_available, remaining)
                batch.quantity_available -= take
                remaining -= take
                total_base_cost += (batch.purchase_price or 0) * take
                if first_batch is None:
                    first_batch = batch
                self.session.add(StockMovement(
                    batch_id=batch.id, unit_id=unit.id, movement_type="بيع",
                    quantity=take, note=f"فاتورة {invoice.invoice_number}",
                ))
            if remaining > 0:
                # هذا الآن سطر دفاعي احتياطي بس - المفروض ما يوصلها الكود
                # أبدًا لأن التحقق الأساسي صار *قبل* إنشاء الفاتورة بالكامل
                # (يوقف البيع كليًا لو المخزون ناقص). لو وصلنا هنا رغم ذلك
                # (حالة نادرة جدًا)، لازم يكمل يحذّر بدل ما يفشل بصمت.
                QMessageBox.warning(self, "تنبيه مخزون",
                                     f"الكمية المتوفرة من {product.name} أقل من المطلوب.")

            # سطر واحد بس بالفاتورة لكل صنف بالسلة - حتى لو انسحبت الكمية من أكثر من
            # دفعة بأسعار مختلفة. قبل هذا التصحيح، كل دفعة تنسحب منها الكمية كانت
            # تولّد سطر مكرر بكامل الكمية الأصلية (مو بس الجزء المسحوب منها)، وهذا كان
            # يضاعف الإيراد والتكلفة المحسوبة بالتقارير أي مرة يصير البيع موزّع على أكثر
            # من دفعة (يصير خصوصًا بالمنتجات اللي تنشترى مرة ثانية بعد قرب نفاذها).
            taken_base = needed - remaining
            if first_batch is not None and taken_base > 0:
                unit_cost = (total_base_cost / taken_base) * unit.conversion_factor
                self.session.add(InvoiceItem(
                    invoice_id=invoice.id, batch_id=first_batch.id, unit_id=unit.id,
                    quantity=item["qty"], unit_price=item["unit_price"],
                    subtotal=item["unit_price"] * item["qty"],
                    unit_cost=unit_cost,
                ))

        if payment_method == "دين":
            customer.current_balance = (customer.current_balance or 0) + final_amount
        else:
            self.session.add(Payment(invoice_id=invoice.id, amount=final_amount, payment_method=payment_method))

        self.session.commit()
        self._auto_print_invoice(invoice)
        self._refresh_cards_stock(cart_items)
        return True

    def _auto_print_invoice(self, invoice):
        """يطبع الفاتورة تلقائيًا وبصمت مباشرة بعد تأكيد البيع - بدون أي نافذة
        طباعة أو رسالة تظهر للكاشير. تشتغل بس لو:
        1) الطباعة التلقائية مفعّلة من شاشة الإعدادات (تقدر تطفيها من هناك)، و
        2) فيه اسم طابعة محفوظ بشاشة الإعدادات، و
        3) هذي الطابعة فعليًا متصلة/متوفرة بالجهاز حاليًا.
        لو أي شرط ناقص، ما تسوي أي شي إطلاقًا - ولا تفتح أي نافذة أو رسالة خطأ."""
        if get_setting(self.session, "auto_print_enabled", "1") == "0":
            return  # الطباعة التلقائية مطفية يدويًا من شاشة الإعدادات

        printer_name = get_setting(self.session, "printer_name", "").strip()
        if not printer_name:
            return

        matching_info = None
        for info in QPrinterInfo.availablePrinters():
            if info.printerName().strip().lower() == printer_name.lower():
                matching_info = info
                break
        if matching_info is None:
            return  # الاسم المحفوظ ما يطابق أي طابعة متصلة حاليًا - تجاهل بصمت

        try:
            printer = QPrinter(matching_info)
            doc = QTextDocument()
            doc.setHtml(self._build_receipt_html(invoice))
            doc.print_(printer)
        except Exception:
            pass  # أي خطأ بالطباعة نتجاهله بصمت - ما نوقف تدفق البيع ولا نزعج الكاشير

    def _build_receipt_html(self, invoice):
        date_text = invoice.invoice_date.strftime("%Y-%m-%d %H:%M") if invoice.invoice_date else ""
        header_row = (
            "<tr style='border-bottom:1px solid #000;font-weight:bold;'>"
            "<td style='padding:2px 0;'>الصنف</td>"
            "<td style='padding:2px 0;text-align:center;'>الكمية</td>"
            "<td style='padding:2px 0;text-align:left;'>السعر</td>"
            "</tr>"
        )
        rows = header_row + "".join(self._item_row_html(item) for item in invoice.items)

        # بيانات الصيدلية (اسم/هاتف/عنوان) - من شاشة الإعدادات (بيانات
        # الفاتورة). كل حقل اختياري - لو فاضي ما يطبع سطره إطلاقًا.
        pharmacy_name = get_setting(self.session, "pharmacy_name", "").strip()
        pharmacy_phone = get_setting(self.session, "pharmacy_phone", "").strip()
        pharmacy_address = get_setting(self.session, "pharmacy_address", "").strip()

        header_html = ""
        if pharmacy_name:
            header_html += f"<h2 style='margin:0 0 2px 0;text-align:center;'>{pharmacy_name}</h2>"
        if pharmacy_phone:
            header_html += f"<p style='margin:0 0 2px 0;text-align:center;'>{pharmacy_phone}</p>"
        if pharmacy_address:
            header_html += f"<p style='margin:0 0 8px 0;text-align:center;'>{pharmacy_address}</p>"
        if header_html:
            header_html += "<hr>"

        return f"""
        <div style="font-family:Tahoma,Arial;direction:rtl;text-align:right;font-size:12px;">
            {header_html}
            <h3 style="margin:0 0 4px 0;">فاتورة {invoice.invoice_number}</h3>
            <p style="margin:0 0 8px 0;">التاريخ: {date_text}</p>
            <table style="width:100%;border-collapse:collapse;">{rows}</table>
            <hr>
            <p><b>الإجمالي: {fmt_money(invoice.final_amount)}</b></p>
            <hr>
            <p style="text-align:center;">شكراً لزيارتكم</p>
        </div>
        """

    def _item_row_html(self, item):
        product = self.session.query(Product).get(
            self.session.query(Batch).get(item.batch_id).product_id
        )
        unit = self.session.query(ProductUnit).get(item.unit_id) if item.unit_id else None
        unit_name = unit.unit_name if unit else ""
        return (
            "<tr>"
            f"<td style='padding:2px 0;'>{product.name}</td>"
            f"<td style='padding:2px 0;text-align:center;'>{item.quantity} {unit_name}</td>"
            f"<td style='padding:2px 0;text-align:left;'>{fmt_money(item.subtotal)}</td>"
            "</tr>"
        )
