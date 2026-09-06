"""
عناصر واجهة قابلة لإعادة الاستخدام.

NumberLineEdit: حقل رقمي يبدأ فارغ (بدون صفر مزعج تحتاج تمسحه قبل ما تكتب
رقمك) - بدل QSpinBox/QDoubleSpinBox العادية اللي تظهر "0" دائمًا بالحقل.

NoScrollFilter: يمنع تغيير قيمة أي حقل (تاريخ، قائمة منسدلة...) بالخطأ لو
المستخدم بس يمرر الماوس (scroll) فوقه بدون قصد تغييره - مشكلة شائعة بـ Qt.
"""
from PySide6.QtWidgets import (
    QLineEdit, QGraphicsDropShadowEffect, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QScroller, QAbstractItemView, QWidget,
)
from PySide6.QtGui import QDoubleValidator, QColor
from PySide6.QtCore import Qt, QObject, QEvent


def enable_touch_scroll(widget):
    """يفعّل السحب باللمس (kinetic scrolling) على أي QScrollArea أو
    QTableWidget/QTableView أو أي عنصر منحدر من QAbstractScrollArea.

    بدون هذا، المستخدم مجبر يمسك شريط التمرير الرفيع بدقة عشان يتنقل.
    بعد التفعيل، يقدر يسحب بإصبعه بأي مكان داخل الجدول/المنطقة وهي
    تتحرك بسلاسة (مع تمايل طبيعي عند التوقف)، وشريط التمرير يضل موجود
    كخيار احتياطي بس مو الطريقة الوحيدة.

    آمنة الاستدعاء على أي widget عنده viewport (QScrollArea, QTableWidget,
    QTableView, QListWidget...) - تُستدعى مرة وحدة بعد إنشاء العنصر.
    """
    target = widget.viewport() if hasattr(widget, "viewport") else widget
    target.setAttribute(Qt.WA_AcceptTouchEvents, True)
    QScroller.grabGesture(target, QScroller.LeftMouseButtonGesture)
    return widget

from app.ui.theme import (
    COLOR_SURFACE, COLOR_BORDER, COLOR_TEXT_SECONDARY, COLOR_TEXT_PRIMARY,
    COLOR_SURFACE_SUBTLE, COLOR_SUCCESS_BG, COLOR_SUCCESS_TEXT,
    COLOR_WARNING_BG, COLOR_WARNING_TEXT, COLOR_DANGER_BG, COLOR_DANGER_TEXT,
    TEAL_400, TEAL_700,
    FONT_H2, FONT_H3, FONT_CAPTION, FONT_BODY_STRONG,
    SPACE_4, SPACE_8, SPACE_12, SPACE_16,
    RADIUS_CARD, RADIUS_BUTTON, RADIUS_PILL, SHADOW_SMALL,
)


def add_shadow(widget, blur=18, color="#16A34A", alpha=35, y_offset=4):
    """يضيف ظل ناعم تحت أي بطاقة/عنصر - يعطي إحساس عمق وبريق بدل الشكل المسطح."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    c = QColor(color)
    c.setAlpha(alpha)
    effect.setColor(c)
    effect.setOffset(0, y_offset)
    widget.setGraphicsEffect(effect)
    return widget


class NoScrollFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            return True  # نتجاهل السكرول بالكامل على هذا العنصر
        return False


def disable_scroll(widget):
    """يمنع أي تغيير غير مقصود بقيمة العنصر بسبب تمرير عجلة الماوس فوقه."""
    f = NoScrollFilter(widget)
    widget.installEventFilter(f)
    widget._no_scroll_filter = f  # نحتفظ بمرجع حتى ما يُحذف الفلتر بجمع القمامة
    return widget


class NumberLineEdit(QLineEdit):
    def __init__(self, decimals=0, placeholder="0", parent=None):
        super().__init__(parent)
        validator = QDoubleValidator(0, 999_999_999, decimals)
        validator.setNotation(QDoubleValidator.StandardNotation)
        self.setValidator(validator)
        self.setPlaceholderText(placeholder)
        self.setAlignment(Qt.AlignLeft)

    def value(self):
        text = self.text().strip()
        if not text:
            return 0
        try:
            return float(text)
        except ValueError:
            return 0

    def set_value(self, v):
        if v in (None, 0):
            self.setText("")
        else:
            # يعرض بدون كسور لو الرقم صحيح، وبكسور لو فيه
            self.setText(str(int(v)) if float(v).is_integer() else str(v))


def create_usd_price_row(iqd_input, rate, usd_placeholder="بالدولار مثلاً 1.5"):
    """يبني حقل سعر شراء إضافي بالدولار مرتبط بحقل سعر بالدينار موجود
    مسبقًا (iqd_input) - لتسهيل إدخال أسعار الأدوية المستوردة (غالبًا
    تُشترى بالدولار) بدل ما يحسبها المستخدم يدويًا بالدينار.

    كتابة رقم هنا (يقبل كسور، مثل 1.5) تحوّله تلقائيًا لسعر بالدينار حسب
    سعر الصرف المحفوظ بالإعدادات (rate) وتعبّي iqd_input بالنتيجة مباشرة -
    فـ iqd_input يبقى هو نفسه الحقل المستخدم بكل حسابات الباكيت/الشريط/
    الأرباح الموجودة أصلًا (ما تغيّر أي منطق عمل أو تخزين، السعر يُخزّن
    بالدينار دائمًا زي ما كان). تفريغ حقل الدولار يرجّع حقل الدينار قابل
    للتعديل اليدوي المباشر زي الوضع الأصلي قبل هذا التعديل بالضبط.

    لو ماكو سعر صرف محفوظ بالإعدادات أصلًا (rate<=0)، الحقل ينعطل مع رسالة
    توضح للمستخدم يضبطه من الإعدادات أول - أفضل من حساب خاطئ بسعر صفر.

    يرجع (row_widget, usd_input)."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(SPACE_8)

    usd_input = NumberLineEdit(decimals=2, placeholder=usd_placeholder)
    preview = QLabel("")
    preview.setWordWrap(True)
    preview.setStyleSheet(f"color:{COLOR_TEXT_SECONDARY};font-size:11px;")

    if rate and rate > 0:
        def _on_usd_changed(_text):
            usd_value = usd_input.value()
            if usd_value > 0:
                iqd_value = round(usd_value * rate)
                iqd_input.setReadOnly(True)
                iqd_input.setStyleSheet(f"background:{COLOR_SURFACE_SUBTLE};color:{COLOR_TEXT_SECONDARY};")
                iqd_input.set_value(iqd_value)
                preview.setText(f"= {iqd_value:,.0f} د.ع (بسعر {rate:,.0f} د.ع للدولار الواحد)")
            else:
                iqd_input.setReadOnly(False)
                iqd_input.setStyleSheet("")
                preview.setText("")
        usd_input.textChanged.connect(_on_usd_changed)
    else:
        usd_input.setEnabled(False)
        usd_input.setPlaceholderText("اضبط سعر الدولار من الإعدادات أولاً")
        preview.setText("لازم تضبط سعر صرف الدولار من الإعدادات حتى تقدر تستخدم هذا الحقل")
        preview.setStyleSheet("color:#DC2626;font-size:11px;")

    h.addWidget(usd_input)
    h.addWidget(preview, stretch=1)
    return row, usd_input


# ============================================================
# H1 Design System — مكوّنات مشتركة (Phase 1 / Task 1: Dashboard)
# بطاقات/أزرار موحّدة تستخدم رموز app.ui.theme بدل ما كل شاشة تسوي نسختها
# الخاصة (زي _stat_card اللي كانت مكررة بأكثر من شاشة). ما فيه أي منطق
# أعمال هنا - بس عناصر عرض بصرية بحتة.
# ============================================================

def create_stat_card(number, label, color):
    """بطاقة إحصائية موحّدة: رقم كبير + تسمية + شريط لوني جانبي حسب دلالة
    اللون (نجاح/تحذير/خطر) - نفس النمط اللي كان مكرر بعدة شاشات، هنا بمكان
    واحد فقط."""
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame{{background:{COLOR_SURFACE};border:1px solid {COLOR_BORDER};"
        f"border-right:4px solid {color};border-radius:{RADIUS_CARD}px;}}"
    )
    add_shadow(frame, blur=SHADOW_SMALL["blur"], color=color,
               alpha=SHADOW_SMALL["alpha"], y_offset=SHADOW_SMALL["y_offset"])
    v = QVBoxLayout(frame)
    v.setContentsMargins(SPACE_16, SPACE_12, SPACE_16, SPACE_12)
    v.setSpacing(SPACE_4)

    n = QLabel(str(number))
    n.setStyleSheet(
        f"font-size:{FONT_H2[0]}px;font-weight:{FONT_H2[1]};"
        f"color:{color};background:transparent;border:none;"
    )
    n.setWordWrap(True)
    v.addWidget(n)

    l = QLabel(label)
    l.setStyleSheet(
        f"color:{COLOR_TEXT_SECONDARY};font-size:{FONT_CAPTION[0]}px;"
        f"font-weight:{FONT_CAPTION[1]};background:transparent;border:none;"
    )
    l.setWordWrap(True)
    v.addWidget(l)

    # ملاحظة إصلاح: 200px كانت تجبر عرض أدنى كبير جدًا للنافذة كلها لما
    # صار عدد أعمدة الشبكة بالرئيسية ثابت (4 أعمدة × 200 = 800px بس
    # للبطاقات، قبل حتى الشريط الجانبي) - يمنع المستخدم من تصغير النافذة
    # لحجم معقول. 150px يعطي هامش تصغير حقيقي مع بقاء البطاقة مقروءة.
    frame.setMinimumWidth(150)
    frame.setMinimumHeight(90)
    frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    # يسمح لمن يستخدم البطاقة بتحديث الرقم/التسمية لاحقًا بمكانهما بدون
    # حذف وإعادة بناء QFrame كامل (وبالتالي بدون إعادة حساب ظل الإطار
    # QGraphicsDropShadowEffect المكلف) - يفيد بالشاشات اللي تحدّث نفس
    # البطاقات بشكل متكرر (مثل الرئيسية بكل تنقل لها).
    def _update_values(new_number, new_label=None):
        n.setText(str(new_number))
        if new_label is not None:
            l.setText(new_label)
    frame.update_values = _update_values
    frame.number_label = n
    frame.caption_label = l
    return frame


def create_section_title(text, icon_name=None, icon_color=None):
    """عنوان قسم موحّد (H3) - يحل محل تكرار setStyleSheet لعناوين الأقسام
    بكل شاشة. لو انمرر icon_name، يرجّع QWidget فيه أيقونة من icon_manager
    (خط Lucide الحقيقي) + النص، بدل الإيموجي القديم اللي كان يتحط جوا
    النص مباشرة."""
    if icon_name:
        from app.ui.icons import pixmap
        wrap = QFrame()
        wrap.setStyleSheet("background:transparent;border:none;")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, SPACE_8, 0, 0)
        row.setSpacing(SPACE_8)
        icon_lbl = QLabel()
        icon_lbl.setStyleSheet("background:transparent;border:none;")
        icon_lbl.setPixmap(pixmap(icon_name, color=icon_color or COLOR_TEXT_PRIMARY, size=FONT_H3[0]))
        row.addWidget(icon_lbl)
        text_lbl = QLabel(text)
        text_lbl.setStyleSheet(
            f"font-size:{FONT_H3[0]}px;font-weight:{FONT_H3[1]};"
            f"color:{COLOR_TEXT_PRIMARY};background:transparent;border:none;"
        )
        row.addWidget(text_lbl)
        row.addStretch()
        return wrap

    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size:{FONT_H3[0]}px;font-weight:{FONT_H3[1]};"
        f"color:{COLOR_TEXT_PRIMARY};background:transparent;border:none;"
        f"margin-top:{SPACE_8}px;"
    )
    return lbl


def create_quick_action_button(text, on_click=None, variant="primary"):
    """زر إجراء سريع موحّد. variant: 'primary' أو 'outline' - يعتمد على
    نفس أنماط QSS الموجودة بـ theme.py (AddButton/OutlineButton) بدل ما
    نعرّف ستايل جديد لكل زر."""
    btn = QPushButton(text)
    btn.setObjectName("AddButton" if variant == "primary" else "OutlineButton")
    btn.setMinimumHeight(42)
    btn.setCursor(Qt.PointingHandCursor)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def create_chart_placeholder(title, note="قريبًا - قيد التطوير"):
    """بطاقة مكان محجوز لرسم بياني مستقبلي - عرض بصري فقط، بدون أي بيانات
    أو مكتبة رسوم بيانية بعد."""
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame{{background:{COLOR_SURFACE};border:1.5px dashed {COLOR_BORDER};"
        f"border-radius:{RADIUS_CARD}px;}}"
    )
    v = QVBoxLayout(frame)
    v.setContentsMargins(SPACE_16, SPACE_16, SPACE_16, SPACE_16)
    v.setAlignment(Qt.AlignCenter)

    t = QLabel(title)
    t.setAlignment(Qt.AlignCenter)
    t.setStyleSheet(
        f"font-size:{FONT_H3[0]}px;font-weight:{FONT_H3[1]};"
        f"color:{COLOR_TEXT_PRIMARY};background:transparent;border:none;"
    )
    v.addWidget(t)

    n = QLabel(note)
    n.setAlignment(Qt.AlignCenter)
    n.setStyleSheet(
        f"color:{COLOR_TEXT_SECONDARY};font-size:{FONT_CAPTION[0]}px;"
        f"background:transparent;border:none;margin-top:{SPACE_4}px;"
    )
    v.addWidget(n)

    frame.setMinimumHeight(160)
    frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return frame


def create_badge(text, variant="neutral"):
    """شارة صغيرة دائرية الحواف (pill) - تُستخدم لحالة المخزون، التصنيف،
    عدد أصناف بالسلة... إلخ بدل ما كل شاشة تسوي نسختها الخاصة من الشارة.
    variant: success / warning / danger / neutral."""
    palette = {
        "success": (COLOR_SUCCESS_BG, COLOR_SUCCESS_TEXT),
        "warning": (COLOR_WARNING_BG, COLOR_WARNING_TEXT),
        "danger": (COLOR_DANGER_BG, COLOR_DANGER_TEXT),
        "neutral": (COLOR_SURFACE_SUBTLE, COLOR_TEXT_SECONDARY),
    }
    bg, fg = palette.get(variant, palette["neutral"])
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background:{bg};color:{fg};border-radius:{RADIUS_PILL}px;"
        f"padding:{SPACE_4}px {SPACE_12}px;font-size:{FONT_CAPTION[0]}px;"
        f"font-weight:{FONT_CAPTION[1]};border:none;"
    )
    return lbl


def toggle_chip_stylesheet(selected):
    """ستايل موحّد لأي زر يشتغل كـ chip/tab قابل للاختيار (وحدة القياس
    بكرت المنتج، طريقة الدفع بالفاتورة...) - بدل ما كل مكان يكرر نفس
    تدرّج اللون يدويًا. يرجّع نص QSS جاهز للاستخدام مباشرة بـ setStyleSheet."""
    if selected:
        return (
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border:none;border-radius:{RADIUS_BUTTON}px;"
            f"font-weight:{FONT_BODY_STRONG[1]};"
        )
    return (
        f"background:{COLOR_SURFACE_SUBTLE};color:{COLOR_TEXT_SECONDARY};border:none;"
        f"border-radius:{RADIUS_BUTTON}px;font-weight:{FONT_BODY_STRONG[1]};"
    )
