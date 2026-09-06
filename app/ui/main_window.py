"""
النافذة الرئيسية: شريط علوي بنفس تسلسل التبويبات اللي اتفقنا عليه بالتصميم،
مع منطقة محتوى تتبدل حسب التبويب المختار (QStackedWidget).

تحديث: (1) شارة حمراء بعدد التنبيهات الجديدة فوق تبويب "التقارير" - نفس منطق
حساب النواقص/قرب انتهاء الصلاحية المستخدم بشاشة التقارير نفسها، بس هنا فقط
للعدّ لا لعرض التفاصيل. (2) استبدال شارة "متصل" الثابتة باسم المستخدم الحالي
+ أيقونة صورة شخصية مجهولة، ونقل زر "خروج" ليصير أقصى اليسار بعده. ولا شي من
منطق تسجيل الدخول/الصلاحيات أو باقي الشاشات تغيّر.
"""
from datetime import date, timedelta
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QButtonGroup, QGridLayout, QApplication,
    QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer
from sqlalchemy import func, case, and_

from app.db.database import get_session
from app.db.models import Product, Batch
from app.db.approved_helper import is_approved_filter_enabled, approved_clause
from app.db.settings_helper import get_expiry_alert_days
from app.ui.icons import icon
from app.ui.widgets import enable_touch_scroll
from app.ui.pos_view import POSView
from app.ui.inventory_view import InventoryView
from app.ui.dosage_view import DosageView
from app.ui.purchase_view import PurchaseView
from app.ui.settings_view import SettingsView
from app.ui.advisor_view import AdvisorView
from app.ui.dashboard_view import DashboardView
from app.ui.debts_view import DebtsView
from app.ui.reports_view import ReportsView
from app.ui.backup_view import BackupView


class _CurrentPageStackedWidget(QStackedWidget):
    """QStackedWidget افتراضيًا يطلب حجمه المفضّل (sizeHint/minimumSizeHint)
    بناءً على أكبر صفحة بين كل الصفحات المضافة له (حتى المخفية)، مو الصفحة
    الظاهرة حاليًا فقط - هذا موثّق بسلوك Qt نفسه. بما إن هذا الـ stack ملفوف
    بـ QScrollArea واحد مشترك لكل الصفحات (outer.stack_scroll)، زيارة صفحة
    طويلة (زي المشتريات/التقارير) تخلي منطقة العرض المحسوبة للصفحة التالية
    (زي البيع) أكبر من محتواها الفعلي - فيختفي جزء من أسفلها (زر إتمام
    البيع مثلاً) رغم وجوده فعليًا، بس خارج حدود ما يحسبه شريط التمرير
    كـ"الصفحة الحالية". هنا نرجّع حجم الصفحة الظاهرة حاليًا بس، فيحسب شريط
    التمرير الخارجي بدقة حسب المحتوى الفعلي المعروض، بغض النظر عن أطول
    صفحة زارها المستخدم سابقًا."""

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()


class PlaceholderView(QWidget):
    """شاشة مؤقتة للأجزاء اللي لسا ما بنيناها بالتفصيل (الديون، المشتريات، التقارير...)."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("background:transparent;border:none;")
        icon_lbl.setPixmap(icon("loader", color="#6B7280", size=32).pixmap(32, 32))
        layout.addWidget(icon_lbl)
        lbl = QLabel(f"{title}\n\n(قيد التطوير - هذا الجزء نبنيه بمرحلة لاحقة)")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#6B7280;font-size:15px;font-weight:600;background:transparent;border:none;")
        layout.addWidget(lbl)


class MainWindow(QMainWindow):
    def __init__(self, current_user):
        super().__init__()
        self.current_user = current_user
        self.setWindowTitle("H1 - نظام إدارة الصيدليات المتكامل")
        self._apply_adaptive_window_size()
        self.setLayoutDirection(Qt.RightToLeft)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_topbar())

        self.stack = _CurrentPageStackedWidget()

        # ---- إصلاح تجاوز النافذة لحدود الشاشة عموديًا ----
        # هذا هو السبب الحقيقي وراء رسالة "Unable to set geometry" وتضرر
        # الواجهة عندك: أي صفحة (خصوصًا صفحة "البيع" اللي تُبنى فورًا عند
        # فتح البرنامج) تحتاج حدًا أدنى من الارتفاع أكبر من شاشتك الفعلية
        # (خصوصًا مع تكبير DPI بويندوز أعلى من 100%)، فكان Qt يجبر MainWindow
        # كامل يطلب ارتفاعًا (1475-1891px) يفوق الشاشة بمرات، فويندوز يرفض
        # ويضغط النافذة قسريًا، وهذا يفسّر التقطيع/التداخل اللي شفته بالصورة.
        # الحل: نغلّف الـ stack كامل بـ QScrollArea عمودي واحد - هيك مهما
        # طالت أي صفحة مستقبلًا (بأي مقياس DPI)، أسوأ حالة ممكنة هي تمرير
        # عمودي بسيط داخل الصفحة نفسها، مو تجاوز النافذة كلها لحدود الشاشة.
        self.stack_scroll = QScrollArea()
        self.stack_scroll.setWidgetResizable(True)
        self.stack_scroll.setFrameShape(QFrame.NoFrame)
        self.stack_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stack_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.stack_scroll.setWidget(self.stack)
        enable_touch_scroll(self.stack_scroll)
        outer.addWidget(self.stack_scroll, stretch=1)

        # ملاحظة أداء مهمة: كانت كل الصفحات العشرة تُبنى فورًا هنا عند فتح
        # البرنامج (كل وحدة فيها استعلامات قاعدة بيانات واستدعاء refresh()
        # داخلي) - يعني قبل ما تظهر النافذة أصلًا، البرنامج يستنى ثانية كاملة
        # تقريبًا يبني كل شي حتى الصفحات اللي المستخدم ممكن ما يفتحها أبدًا
        # بهالجلسة. هذا يزيد وزن البرنامج العام ويزيد احتمال أي تهنيج/ومضة
        # بأي مكان. الحل: نبني كل صفحة "بالكسل" (lazy) - أول مرة بس ينتقل
        # لها المستخدم فعليًا، وبعدها تنحفظ وتُستخدم من الكاش زي القديم.
        self._page_factories = {
            "البيع": lambda: POSView(current_user),
            "المخزون": lambda: InventoryView(),
            "المشتريات": lambda: PurchaseView(),
            "المستشار": lambda: AdvisorView(),
            "الجرعة والتداخلات": lambda: DosageView(),
            "الديون": lambda: DebtsView(),
            "التقارير": lambda: ReportsView(on_navigate=self._navigate_to),
            "النسخ الاحتياطي": lambda: BackupView(),
            "الإعدادات": lambda: SettingsView(),
            "الرئيسية": lambda: DashboardView(on_navigate=self._navigate_to),
        }
        self.pages = {}

        self._show_page("البيع")
        # نبني صفحة الرئيسية بالخلفية فورًا (رغم إنها "كسولة" بالمبدأ) - لأنها
        # أكثر صفحة يرجعلها المستخدم بشكل متكرر. لو تركناها كسولة بالكامل، أول
        # نقرة عليها بكل جلسة تشتغل تكلفة "أول بناء" (تخطيط + ظلال البطاقات +
        # تنسيق الأنماط) وهي ظاهرة فعليًا بلحظة الضغط، وهذا يشبه بالضبط الومضة
        # اللي وصفها المستخدم تحديدًا بصفحة الرئيسية. نبنيها هنا فوق صفحة
        # البيع (قبل أي تفاعل من المستخدم) عشان أي "كلفة أول ظهور" تصير وهي
        # مخفية بمرحلة التحميل الأولي، مو وهي ظاهرة أمام المستخدم لاحقًا.
        if "الرئيسية" not in self.pages:
            home_page = self._page_factories["الرئيسية"]()
            self.pages["الرئيسية"] = home_page
            self.stack.addWidget(home_page)

        # ---- نسخ احتياطي تلقائي دوري (مو بس عند إغلاق البرنامج) ----
        # قبل هذا الإصلاح، النسخة الاحتياطية التلقائية الوحيدة كانت تصير عند
        # إغلاق البرنامج - يعني لو صار عطل مفاجئ أو انقطاع كهرباء أثناء يوم
        # شغل كامل، تخسر كل بيانات ذاك اليوم لأن آخر نسخة كانت من اليوم اللي
        # قبله. هذا التايمر يسوي نسخة كل 30 دقيقة تلقائيًا بالخلفية بدون ما
        # يوقف شغل المستخدم أو يزعجه برسائل، طالما فيه مجلد نسخ احتياطي محدد
        # ومفعّل من الإعدادات.
        self._backup_timer = QTimer(self)
        self._backup_timer.setInterval(30 * 60 * 1000)  # 30 دقيقة
        self._backup_timer.timeout.connect(self._auto_backup_tick)
        self._backup_timer.start()

    def _auto_backup_tick(self):
        try:
            from app.db.database import get_session
            from app.db import backup_helper
            session = get_session()
            if backup_helper.get_backup_folder(session) and backup_helper.is_auto_backup_enabled(session):
                # ملف واحد ثابت يتحدث كل تِك (30 دقيقة) - مو نسخة جديدة كل
                # مرة (راجع تعليق perform_periodic_backup لتفاصيل سبب الفصل
                # عن perform_backup اليدوي).
                backup_helper.perform_periodic_backup(session)
        except Exception:
            pass  # النسخ التلقائي بالخلفية ما يجوز يقاطع شغل المستخدم لو فشل

    def _apply_adaptive_window_size(self):
        """كانت النافذة تفتح دائمًا بحجم ثابت 1280x800 بغض النظر عن حجم
        شاشة المستخدم الفعلي - على شاشات أصغر أو بمقياس تكبير/تصغير مختلف
        (DPI scaling) هذا يخلي النافذة تظهر أكبر من الشاشة نفسها أو خارج
        حدودها. هنا نعتمد على المساحة المتاحة الفعلية للشاشة (availableGeometry)
        ونحسب حجم مناسب لا يتجاوزها أبدًا، مع حد أدنى معقول، ونوسّط النافذة."""
        target_w, target_h = 1280, 800
        min_w, min_h = 1024, 640
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(target_w, available.width())
            height = min(target_h, available.height())
            # الحد الأدنى يُطبّق فقط لو الشاشة تتحمله فعليًا - عشان النافذة
            # ما تتجاوز المساحة المتاحة أبدًا حتى على شاشات صغيرة جدًا.
            if width < min_w <= available.width():
                width = min_w
            if height < min_h <= available.height():
                height = min_h
            self.resize(width, height)
            # توسيط النافذة داخل المساحة المتاحة بدل ما تفتح بموقع افتراضي
            # قد يكون خارج حدود الشاشة.
            x = available.x() + (available.width() - width) // 2
            y = available.y() + (available.height() - height) // 2
            self.move(x, y)
        else:
            self.resize(target_w, target_h)

    def _build_topbar(self):
        bar = QFrame()
        bar.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #15803D,stop:1 #14532D);"
        )
        bar.setFixedHeight(64)

        # ملاحظة إصلاح: كان شريط التنقل (من "الرئيسية" لين "البيع") يمتد
        # بالكامل لعرض النافذة مباشرة - على شاشة عريضة أو نافذة مكبّرة
        # (Maximize) هذا يخلي فجوة فارغة كبيرة وغير متوازنة بين مجموعة
        # الأزرار وبطاقة المستخدم بالجهة الثانية. نحدّ أقصى عرض معقول
        # لمحتوى الشريط (الأزرار + بطاقة المستخدم) بدل ما يمتد بالكامل -
        # خلفية الشريط الملوّنة نفسها تضل ممتدة لعرض النافذة، بس محتواه
        # الفعلي يتوسط بعرض متناسق.
        outer_layout = QHBoxLayout(bar)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        content = QWidget()
        content.setMaximumWidth(1400)
        outer_layout.addWidget(content)

        layout = QHBoxLayout(content)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        brand_icon = QLabel()
        brand_icon.setStyleSheet("background:transparent;border:none;")
        brand_icon.setPixmap(icon("store", color="white", size=20).pixmap(20, 20))
        brand_row.addWidget(brand_icon)
        brand = QLabel("H1")
        brand.setStyleSheet("color:white;font-size:18px;font-weight:800;background:transparent;border:none;")
        brand_row.addWidget(brand)
        layout.addLayout(brand_row)
        layout.addSpacing(20)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        # "خروج" انتقل لآخر الشريط (أقصى اليسار، بعد بطاقة المستخدم) - شوف الأسفل.
        nav_order = ["الرئيسية", "المستشار", "الجرعة والتداخلات", "الإعدادات",
                     "النسخ الاحتياطي", "الديون", "التقارير", "المخزون", "المشتريات", "البيع"]
        nav_icons = {
            "الرئيسية": "layout_dashboard", "المستشار": "brain", "الجرعة والتداخلات": "calculator",
            "الإعدادات": "settings", "النسخ الاحتياطي": "backup", "الديون": "wallet",
            "التقارير": "chart", "المخزون": "box", "المشتريات": "truck", "البيع": "cart",
        }
        # ---- إصلاح تمدد النافذة خارج حدود الشاشة ----
        # المشكلة: كانت كل أزرار التنقل (10 أزرار بنص عربي + أيقونة) تنضاف
        # مباشرة لـ layout الرئيسي بدون أي إمكانية انكماش. مجموع عرضها
        # الطبيعي يتجاوز عرض شاشات اللابتوب الفعلي (خصوصًا مع مقياس DPI
        # أعلى من 100%)، فكان Qt يجبر MainWindow كامل يكبر عن حدود الشاشة
        # عشان يستوعب الحد الأدنى المطلوب لهذا الشريط بالذات - هذا بالضبط
        # سبب تمدد الشاشة كلها وظهور شريط تمرير أفقي بالأسفل حتى قبل
        # التحويل لـ exe (المشكلة بالتخطيط نفسه، ما إلها علاقة بالتحزيم).
        # الحل: نحط الأزرار جوا QScrollArea أفقي مستقل - أقصى شي يصير هو
        # تمرير أفقي صغير جوا الشريط نفسه (نادر جدًا)، بدل ما تتمدد النافذة
        # كاملة خارج الشاشة. قلّلنا كمان الحشوة (padding) وحجم الخط شوي
        # عشان الأزرار العشرة تنلم بعرض طبيعي بمعظم الشاشات بدون تمرير أصلًا.
        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:horizontal{height:6px;background:transparent;}"
            "QScrollBar::handle:horizontal{background:rgba(255,255,255,0.25);border-radius:3px;}"
        )
        nav_scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        nav_container = QWidget()
        nav_container.setStyleSheet("background:transparent;")
        nav_layout = QHBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(2)

        self.reports_badge = None
        for name in nav_order:
            btn = QPushButton(f" {name}")
            btn.setIcon(icon(nav_icons.get(name, "dot"), color="#DCFCE7", size=15))
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{color:#DCFCE7;background:transparent;border:none;padding:8px 10px;"
                "border-radius:10px;font-weight:700;font-size:12px;}"
                "QPushButton:hover{background-color:rgba(255,255,255,0.10);}"
                "QPushButton:checked{background-color:rgba(255,255,255,0.18);font-weight:800;color:white;}"
            )
            btn.clicked.connect(lambda _, n=name: self._show_page(n))
            self.nav_group.addButton(btn)
            if name == "التقارير":
                nav_layout.addWidget(self._wrap_with_alert_badge(btn))
            else:
                nav_layout.addWidget(btn)

        nav_layout.addStretch()
        nav_scroll.setWidget(nav_container)
        enable_touch_scroll(nav_scroll)
        layout.addWidget(nav_scroll, stretch=1)

        # ---- بطاقة المستخدم: صورة مجهولة + الاسم (بدل شارة "متصل" الثابتة) ----
        user_box = QFrame()
        user_box.setStyleSheet("background:rgba(255,255,255,0.10);border-radius:10px;")
        user_row = QHBoxLayout(user_box)
        user_row.setContentsMargins(6, 4, 12, 4)
        user_row.setSpacing(8)

        avatar = QLabel()
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background:#DCFCE7;border-radius:15px;")
        avatar.setPixmap(icon("user", color="#15803D", size=16).pixmap(16, 16))
        user_row.addWidget(avatar)

        user_name = getattr(self.current_user, "username", None) or "مستخدم"
        name_lbl = QLabel(user_name)
        name_lbl.setStyleSheet("color:white;font-weight:700;font-size:13px;background:transparent;border:none;")
        user_row.addWidget(name_lbl)

        layout.addWidget(user_box)

        # ---- زر الخروج: أقصى اليسار، مباشرة بعد بطاقة المستخدم ----
        logout_btn = QPushButton("  خروج")
        logout_btn.setIcon(icon("logout", color="#DCFCE7", size=14))
        logout_btn.setCursor(Qt.PointingHandCursor)
        logout_btn.setStyleSheet(
            "QPushButton{color:#DCFCE7;background:transparent;border:none;padding:10px 14px;border-radius:8px;}"
            "QPushButton:hover{background-color:rgba(255,255,255,0.16);color:white;}"
        )
        logout_btn.clicked.connect(self.close)
        layout.addWidget(logout_btn)

        return bar

    def _wrap_with_alert_badge(self, btn):
        """يلف زر تبويب "التقارير" بحاوية صغيرة وتحط فوقه شارة حمراء دائرية
        بعدد التنبيهات الجديدة (نواقص مخزون + قرب/انتهاء صلاحية) - نفس معايير
        شاشة التقارير بالضبط. الشارة تظهر بس لو العدد أكبر من صفر."""
        container = QFrame()
        container.setStyleSheet("background:transparent;border:none;")
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(btn, 0, 0)

        badge = QLabel()
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(18, 18)
        badge.setStyleSheet(
            "background:#DC2626;color:white;border-radius:9px;font-size:10px;font-weight:800;"
        )
        grid.addWidget(badge, 0, 0, alignment=Qt.AlignTop | Qt.AlignRight)
        self.reports_badge = badge
        self._refresh_reports_badge()
        return container

    def _compute_alerts_count(self):
        """عدد التنبيهات الجديدة لعرضها بالشارة: منتجات وصلت/تحت الحد الأدنى
        للمخزون + منتجات قربت أو انتهت صلاحيتها - نفس شروط قسم التنبيهات
        بشاشة التقارير (Product.min_stock_threshold والدفعات القريبة من
        الانتهاء خلال 90 يوم)، بس هنا فقط للعدّ الإجمالي بدون تفاصيل.

        ⚠️ إصلاح أداء مهم (راجع تقرير التدقيق): كانت هذي الدالة تجيب *كل*
        منتج فعّال مع كل دفعاته كاملة (joinedload(Product.batches).all())
        وتحسب المجموع/الأقرب صلاحية بحلقة بايثون - وتتكرر عند كل تنقل بين
        أي تبويبين بكامل البرنامج (_refresh_reports_badge تُستدعى بنهاية
        كل _show_page، مو بس عند فتح المخزون)، فيتراكم بطء محسوس بكل نقرة
        تنقل مع نمو الكتالوج. الحين نفس المعايير بالضبط (نفس threshold،
        نفس expiry_alert_days، نفس فلتر "الأدوية المعتمدة")، بس محسوبة
        بتجميع SQL (SUM/MIN مع GROUP BY) بدل تحميل كل كائنات
        المنتجات/الدفعات وحسابها بايثونيًا."""
        try:
            session = get_session()
            today = date.today()
            expiry_alert_days = get_expiry_alert_days(session)

            product_query = (
                session.query(Product.id, Product.min_stock_threshold)
                .filter(Product.is_active == True)
            )
            # نفس إعداد "الاعتماد على الأدوية المعتمدة" - يخلي عدّاد الشارة
            # مطابق لنفس التنبيهات المعروضة بالتقارير بالضبط. approved_clause
            # نفس الشرط المستخدم بشاشة المخزون بالضبط (Product.is_custom أو
            # له دفعة شراء واحدة على الأقل)، بس هنا مطبّق مباشرة بالاستعلام.
            if is_approved_filter_enabled(session):
                product_query = product_query.filter(approved_clause(session))
            products = product_query.all()
            if not products:
                return 0
            product_ids = [p.id for p in products]

            # مجموع الكمية المتاحة + أقرب تاريخ صلاحية (لدفعات فيها كمية >
            # 0 فقط) لكل منتج، بتجميع SQL وحد بدل تحميل كل صفوف الدفعات.
            stats_rows = (
                session.query(
                    Batch.product_id,
                    func.coalesce(func.sum(Batch.quantity_available), 0),
                    func.min(
                        case(
                            (and_(Batch.expiry_date.isnot(None), Batch.quantity_available > 0), Batch.expiry_date),
                            else_=None,
                        )
                    ),
                )
                .filter(Batch.product_id.in_(product_ids))
                .group_by(Batch.product_id)
                .all()
            )
            stats_by_product = {row[0]: (row[1], row[2]) for row in stats_rows}

            expiry_cutoff = today + timedelta(days=expiry_alert_days)
            count = 0
            for product_id, min_stock_threshold in products:
                stock, nearest = stats_by_product.get(product_id, (0, None))
                threshold = min_stock_threshold or 10
                if stock <= threshold:
                    count += 1
                if nearest and nearest <= expiry_cutoff:
                    count += 1
            return count
        except Exception:
            return 0

    def _refresh_reports_badge(self):
        if self.reports_badge is None:
            return
        count = self._compute_alerts_count()
        if count > 0:
            self.reports_badge.setText(str(count) if count <= 99 else "99+")
            self.reports_badge.show()
        else:
            self.reports_badge.hide()

    def _navigate_to(self, page_name, filter_status=None):
        """يُمرَّر كـ on_navigate لصفحتي الرئيسية والتقارير - يفتح الصفحة
        المطلوبة (نفس مفاتيح self._page_factories)، وإذا انمرر filter_status
        وكانت الصفحة تدعمه (زي المخزون عبر set_status_filter)، يطبّقه فورًا
        عشان المستخدم يوصل مباشرة لنفس المجموعة اللي كان يشوفها بدل ما
        يفلتر يدويًا من جديد."""
        self._show_page(page_name)
        if filter_status:
            page = self.pages.get(page_name)
            if page is not None and hasattr(page, "set_status_filter"):
                page.set_status_filter(filter_status)

    def _show_page(self, name):
        """ملاحظة أداء/عرض: كانت setCurrentWidget (تُظهر الصفحة) تُستدعى قبل
        refresh() - فيعرض المستخدم الصفحة وهي لسا بمحتواها القديم لحظة، وبعدين
        refresh() يحذف كل البطاقات القديمة (deleteLater) ويبني بطاقات جديدة
        من الصفر وهي ظاهرة على الشاشة فعليًا - هذا اللي يسبب "ومضة" واجهة غير
        مكتملة/غير مُنسّقة لجزء من الثانية عند فتح أي تبويب (خصوصًا الرئيسية).
        الحل: نبني/نحدّث محتوى الصفحة أولًا وهي مخفية بعد، وبعدين نظهرها دفعة
        وحدة بعد ما تكون جاهزة بالكامل. setUpdatesEnabled(False) إضافيًا يمنع
        أي رسم جزئي للصفحة الحالية أثناء إعادة البناء."""
        page = self.pages.get(name)
        just_built = False
        if page is None:
            factory = self._page_factories.get(name)
            if factory is None:
                return
            page = factory()
            self.pages[name] = page
            self.stack.addWidget(page)
            just_built = True
        self.setUpdatesEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # كل صفحة أصلًا تسوي refresh() تلقائي بآخر سطر من __init__ تبعها -
            # يعني نداء refresh() هنا كان يكرر نفس العمل الثقيل مرتين بأول
            # فتح لأي صفحة (خصوصًا صفحة البيع اللي تبني عشرات البطاقات).
            # هنا فقط لو الصفحة كانت موجودة مسبقًا (تنقل لاحق، مو أول بناء).
            if not just_built and hasattr(page, "refresh"):
                page.refresh()
            self.stack.setCurrentWidget(page)
            self.stack.updateGeometry()
        finally:
            self.setUpdatesEnabled(True)
            QApplication.restoreOverrideCursor()
        # إصلاح مهم: stack_scroll (التمرير العمودي الخارجي) مشترك بين كل
        # الصفحات لأنه يلف الـ QStackedWidget كامل - لو المستخدم تمرّر لتحت
        # بصفحة أطول (المشتريات مثلاً) وبعدها بدّل لصفحة ثانية (البيع)، موقع
        # التمرير القديم يضل كما هو، فتفتح الصفحة الجديدة وهي "مقصوصة" من
        # فوق (يختفي منها الجزء العلوي المعروض فعليًا تحت الحافة، زي لوحة
        # الفاتورة وزر إتمام البيع بصفحة البيع). نرجّع التمرير للأعلى فورًا
        # كل مرة تُعرض صفحة، جديدة كانت أو محفوظة بالكاش.
        self.stack_scroll.verticalScrollBar().setValue(0)
        self._refresh_reports_badge()

    def closeEvent(self, event):
        try:
            from app.db.database import get_session
            from app.db import backup_helper
            session = get_session()
            if backup_helper.get_backup_folder(session):
                # نفس الملف الثابت الواحد المستخدم بالتِك الدوري - عند
                # الإغلاق نحدّثه بآخر حالة، مو نسخة جديدة منفصلة.
                backup_helper.perform_periodic_backup(session)
        except Exception:
            pass  # ما نريد نمنع إغلاق البرنامج لو صار خطأ بالنسخ الاحتياطي
        super().closeEvent(event)
        # بعد ما عطّلنا الإغلاق التلقائي (quitOnLastWindowClosed=False) بـ
        # main.py حتى ما ينسكر البرنامج بالغلط من إغلاق نافذة فرعية، لازم
        # نسكر التطبيق يدويًا وبشكل صريح هنا بالضبط - إغلاق النافذة الرئيسية
        # فعليًا (مو أي نافذة فرعية ثانية) هو الوحيد المفروض يسكر البرنامج
        # كامل.
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()
