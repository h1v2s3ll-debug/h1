"""شاشة الإعدادات: الطابعة وحجم الورق، القارئ الضوئي (السكانر)، الحساب، المستشار الذكي، والدعم."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QFrame, QMessageBox, QScrollArea, QSizePolicy, QCheckBox
)
from PySide6.QtGui import QDesktopServices, QTextDocument
from PySide6.QtCore import QUrl
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

from app.db.database import get_session
from app.db.settings_helper import (
    get_setting, set_setting, get_usd_rate, set_usd_rate,
    get_expiry_alert_days, set_expiry_alert_days,
)
from app.db.approved_helper import is_approved_filter_enabled, set_approved_filter_enabled
from app.db.models import User
from app.ui.widgets import NumberLineEdit, disable_scroll, enable_touch_scroll
from app.ui.icons import icon
from app.db.auth_helper import hash_password, verify_password

SUPPORT_WHATSAPP_NUMBER = "07774605020"
PAPER_SIZES = ["57mm حراري", "58mm حراري", "72mm حراري", "76mm حراري", "80mm حراري", "110mm حراري", "A5", "A4"]


class SettingsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = get_session()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        enable_touch_scroll(scroll)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        # حاوية بعرض محدود وممركزة - تمنع تمدد الحقول والخط بشكل غريب لما تكبّر الشاشة
        centering_row = QHBoxLayout()
        centering_row.addStretch()

        content = QWidget()
        content.setMaximumWidth(650)
        content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout = QVBoxLayout(content)

        title = QLabel("الإعدادات")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        layout.addWidget(title)

        layout.addWidget(self._printer_section())
        layout.addWidget(self._receipt_info_section())
        layout.addWidget(self._general_settings_section())
        layout.addWidget(self._scanner_section())
        layout.addWidget(self._approved_drugs_section())
        layout.addWidget(self._account_section())
        layout.addWidget(self._advisor_section())
        layout.addWidget(self._support_section())
        layout.addStretch()

        centering_row.addWidget(content)
        centering_row.addStretch()

        scroll_content = QWidget()
        scroll_content.setLayout(centering_row)
        scroll.setWidget(scroll_content)

    def _card(self, title_text):
        frame = QFrame()
        frame.setStyleSheet("background:white;border:1px solid #E5E7EB;border-radius:12px;padding:14px;")
        v = QVBoxLayout(frame)
        t = QLabel(title_text)
        t.setStyleSheet("font-weight:bold;font-size:14px;margin-bottom:8px;")
        v.addWidget(t)
        return frame, v

    def _printer_section(self):
        frame, v = self._card("إعدادات الطابعة")

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("اسم الطابعة:"))
        self.printer_name_input = QLineEdit(get_setting(self.session, "printer_name", ""))
        self.printer_name_input.setPlaceholderText("مثلاً: XP-58 أو HP LaserJet")
        row1.addWidget(self.printer_name_input)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("حجم الورق:"))
        self.paper_size_combo = QComboBox()
        disable_scroll(self.paper_size_combo)
        self.paper_size_combo.addItems(PAPER_SIZES)
        current = get_setting(self.session, "paper_size", "80mm حراري")
        idx = self.paper_size_combo.findText(current)
        if idx >= 0:
            self.paper_size_combo.setCurrentIndex(idx)
        row2.addWidget(self.paper_size_combo)
        v.addLayout(row2)

        # تشغيل/إطفاء الطباعة التلقائية بعد كل عملية بيع - الطباعة التلقائية
        # كانت تشتغل دائمًا بدون أي طريقة لإيقافها لو فيه اسم طابعة محفوظ.
        self.auto_print_checkbox = QCheckBox("تفعيل الطباعة التلقائية بعد كل عملية بيع")
        auto_print_enabled = get_setting(self.session, "auto_print_enabled", "1") != "0"
        self.auto_print_checkbox.setChecked(auto_print_enabled)
        v.addWidget(self.auto_print_checkbox)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("حفظ إعدادات الطابعة")
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px;")
        save_btn.clicked.connect(self._save_printer)
        btn_row.addWidget(save_btn)
        test_btn = QPushButton("طباعة صفحة تجريبية")
        test_btn.setIcon(icon("printer", color="#15803D", size=15))
        test_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:8px;")
        test_btn.clicked.connect(self._test_print)
        btn_row.addWidget(test_btn)
        v.addLayout(btn_row)
        return frame

    def _test_print(self):
        printer = QPrinter()
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.Accepted:
            return
        doc = QTextDocument()
        doc.setHtml(
            "<h2>H1 - اختبار الطابعة</h2>"
            "<p>لو تشوف هذي الصفحة مطبوعة، فالطابعة شغّالة ومربوطة صح بالبرنامج.</p>"
            f"<p>حجم الورق المختار: {self.paper_size_combo.currentText()}</p>"
        )
        doc.print_(printer)
        QMessageBox.information(self, "تم", "تم إرسال صفحة تجريبية للطابعة.")

    def _save_printer(self):
        set_setting(self.session, "printer_name", self.printer_name_input.text().strip())
        set_setting(self.session, "paper_size", self.paper_size_combo.currentText())
        set_setting(self.session, "auto_print_enabled", "1" if self.auto_print_checkbox.isChecked() else "0")
        QMessageBox.information(self, "تم", "تم حفظ إعدادات الطابعة.")

    def _receipt_info_section(self):
        """بيانات الصيدلية اللي تنطبع بأعلى كل فاتورة - اسم الصيدلية، الهاتف،
        والعنوان. أسفل الفاتورة تنطبع دائمًا عبارة ثابتة "شكراً لزيارتكم"."""
        frame, v = self._card("بيانات الفاتورة")

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("اسم الصيدلية:"))
        self.pharmacy_name_input = QLineEdit(get_setting(self.session, "pharmacy_name", ""))
        self.pharmacy_name_input.setPlaceholderText("مثلاً: صيدلية الشفاء")
        row1.addWidget(self.pharmacy_name_input)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("رقم الهاتف/واتساب:"))
        self.pharmacy_phone_input = QLineEdit(get_setting(self.session, "pharmacy_phone", ""))
        self.pharmacy_phone_input.setPlaceholderText("اختياري")
        row2.addWidget(self.pharmacy_phone_input)
        v.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("العنوان:"))
        self.pharmacy_address_input = QLineEdit(get_setting(self.session, "pharmacy_address", ""))
        self.pharmacy_address_input.setPlaceholderText("اختياري")
        row3.addWidget(self.pharmacy_address_input)
        v.addLayout(row3)

        save_btn = QPushButton("حفظ بيانات الفاتورة")
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px;")
        save_btn.clicked.connect(self._save_receipt_info)
        v.addWidget(save_btn)
        return frame

    def _save_receipt_info(self):
        set_setting(self.session, "pharmacy_name", self.pharmacy_name_input.text().strip())
        set_setting(self.session, "pharmacy_phone", self.pharmacy_phone_input.text().strip())
        set_setting(self.session, "pharmacy_address", self.pharmacy_address_input.text().strip())
        QMessageBox.information(self, "تم", "تم حفظ بيانات الفاتورة.")

    def _general_settings_section(self):
        """سعر صرف الدولار (يُدخله المستخدم يدويًا، مثلاً 1500 لكل دولار) -
        يُستخدم بشاشة المخزون لتحويل سعر شراء مُدخل بالدولار لسعر بالدينار
        تلقائيًا وقت الإدخال (التخزين الفعلي بقاعدة البيانات يضل بالدينار
        دائمًا، هذا فقط يريح إدخال أسعار الأدوية المستوردة بالدولار ويمنع
        خطأ تحويل يدوي من المستخدم).

        وعدد أيام التنبيه لقرب انتهاء الصلاحية (كان ثابت 90 يوم بكل شاشات
        البرنامج - دشبورد، تقارير، مخزون - صار الحين قابل للتعديل من هنا)."""
        frame, v = self._card("سعر الدولار وتنبيه انتهاء الصلاحية")

        rate_note = QLabel(
            "سعر صرف الدولار مقابل الدينار العراقي - تدخله يدويًا وتحدّثه كلما "
            "تغيّر السعر بالسوق. لما تدخل سعر شراء دواء بالدولار بشاشة المخزون، "
            "البرنامج يحوّله تلقائيًا لسعر بالدينار حسب هذا الرقم وقت الإدخال."
        )
        rate_note.setWordWrap(True)
        rate_note.setStyleSheet("color:#6B7280;font-size:12px;margin-bottom:6px;")
        v.addWidget(rate_note)

        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("سعر الدولار الواحد (بالدينار):"))
        self.usd_rate_input = NumberLineEdit(decimals=2, placeholder="مثلاً: 1500")
        current_rate = get_usd_rate(self.session)
        if current_rate:
            self.usd_rate_input.set_value(current_rate)
        rate_row.addWidget(self.usd_rate_input)
        v.addLayout(rate_row)

        days_row = QHBoxLayout()
        days_row.addWidget(QLabel("التنبيه لقرب انتهاء الصلاحية قبل (بالأيام):"))
        self.expiry_days_input = NumberLineEdit(decimals=0, placeholder="90")
        self.expiry_days_input.set_value(get_expiry_alert_days(self.session))
        days_row.addWidget(self.expiry_days_input)
        v.addLayout(days_row)

        save_btn = QPushButton("حفظ")
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px;")
        save_btn.clicked.connect(self._save_general_settings)
        v.addWidget(save_btn)
        return frame

    def _save_general_settings(self):
        set_usd_rate(self.session, self.usd_rate_input.value())
        set_expiry_alert_days(self.session, int(self.expiry_days_input.value() or 90))
        QMessageBox.information(self, "تم", "تم حفظ الإعدادات.")

    def _scanner_section(self):
        frame, v = self._card("إعدادات القارئ الضوئي (الباركود)")

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("نوع الاتصال:"))
        self.scanner_type_combo = QComboBox()
        disable_scroll(self.scanner_type_combo)
        self.scanner_type_combo.addItems(["USB (لوحة مفاتيح افتراضية)", "Bluetooth", "كاميرا الجهاز"])
        current = get_setting(self.session, "scanner_type", "USB (لوحة مفاتيح افتراضية)")
        idx = self.scanner_type_combo.findText(current)
        if idx >= 0:
            self.scanner_type_combo.setCurrentIndex(idx)
        row1.addWidget(self.scanner_type_combo)
        v.addLayout(row1)

        note = QLabel("ملاحظة: أغلب قارئات الباركود تشتغل مباشرة كأنها لوحة مفاتيح - "
                       "يعني تقدر تستخدمها بخانة البحث بشاشة البيع بدون أي إعداد إضافي.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6B7280;font-size:12px;")
        v.addWidget(note)

        test_row = QHBoxLayout()
        test_row.addWidget(QLabel("اختبار الماسح:"))
        self.scanner_test_input = QLineEdit()
        self.scanner_test_input.setPlaceholderText("امسح أي باركود هنا - لو ظهرت الأرقام، الماسح شغّال")
        test_row.addWidget(self.scanner_test_input)
        v.addLayout(test_row)

        save_btn = QPushButton("حفظ إعدادات السكانر")
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px;")
        save_btn.clicked.connect(self._save_scanner)
        v.addWidget(save_btn)
        return frame

    def _save_scanner(self):
        set_setting(self.session, "scanner_type", self.scanner_type_combo.currentText())
        QMessageBox.information(self, "تم", "تم حفظ إعدادات القارئ الضوئي.")

    def _approved_drugs_section(self):
        """اعتماد الأدوية المعتمدة: إعداد عام لو فعّلته، التنبيهات والتقارير
        (نقص المخزون، قرب انتهاء الصلاحية، الأدوية الراكدة...الخ) تصير تشمل
        بس الأدوية "المعتمدة" - أي دواء مضاف يدويًا أو انشرى فعليًا للصيدلية
        ولو مرة وحدة - وتتجاهل أدوية الكتالوج الجاهز اللي مجرد اسم وباركود
        ولم تُشترَ أبدًا (راجع app/db/approved_helper.py)."""
        frame, v = self._card("اعتماد الأدوية المعتمدة")

        note = QLabel(
            "لو فعّلت هذا الخيار، التنبيهات والتقارير بالبرنامج (نقص المخزون، "
            "قرب انتهاء الصلاحية، المنتهي، الأدوية الراكدة، وغيرها) راح تشمل "
            "فقط \"الأدوية المعتمدة\" - يعني الأدوية اللي فعلاً موجودة بالصيدلية "
            "وإلها أسعار وكميات حقيقية تم التعامل معها، وتتجاهل أدوية الكتالوج "
            "الجاهز اللي مجرد اسم وباركود بدون ما تكون مشترية أو محتاجتها أصلاً.\n"
            "هذا لا يحذف أو يخفي أي دواء بشكل دائم - يقدر تعرض كل الأدوية بأي "
            "وقت من شاشة المخزون بزر \"عرض الأدوية المعتمدة فقط\"."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#6B7280;font-size:12px;margin-bottom:8px;")
        v.addWidget(note)

        self.approved_filter_checkbox = QCheckBox("الاعتماد على الأدوية المعتمدة فقط بالتنبيهات والتقارير")
        self.approved_filter_checkbox.setChecked(is_approved_filter_enabled(self.session))
        v.addWidget(self.approved_filter_checkbox)

        save_btn = QPushButton("حفظ")
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px;")
        save_btn.clicked.connect(self._save_approved_filter)
        v.addWidget(save_btn)
        return frame

    def _save_approved_filter(self):
        set_approved_filter_enabled(self.session, self.approved_filter_checkbox.isChecked())
        QMessageBox.information(self, "تم", "تم حفظ إعداد الأدوية المعتمدة.")

    def _account_section(self):
        frame, v = self._card("الحساب - اسم المستخدم وكلمة المرور")

        user = self.session.query(User).first()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("اسم المستخدم:"))
        self.username_input = QLineEdit(user.username if user else "")
        row1.addWidget(self.username_input)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("كلمة مرور جديدة:"))
        self.new_password_input = QLineEdit()
        self.new_password_input.setEchoMode(QLineEdit.Password)
        self.new_password_input.setPlaceholderText("اتركه فاضي لو ما تريد تغييرها")
        row2.addWidget(self.new_password_input)
        v.addLayout(row2)

        row3 = QHBoxLayout()
        current_pw_lbl = QLabel("كلمة المرور الحالية:")
        row3.addWidget(current_pw_lbl)
        self.current_password_input = QLineEdit()
        self.current_password_input.setEchoMode(QLineEdit.Password)
        self.current_password_input.setPlaceholderText("لازم تكتبها عشان تقدر تعدّل الاسم أو كلمة المرور")
        row3.addWidget(self.current_password_input)
        v.addLayout(row3)

        note = QLabel("لأسباب أمان، لازم تدخل كلمة المرور الحالية قبل ما تقدر تغيّر اسم المستخدم أو كلمة المرور.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6B7280;font-size:12px;")
        v.addWidget(note)

        save_btn = QPushButton("حفظ بيانات الحساب")
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px;")
        save_btn.clicked.connect(self._save_account)
        v.addWidget(save_btn)
        return frame

    def _save_account(self):
        user = self.session.query(User).first()
        if not user:
            QMessageBox.warning(self, "خطأ", "ماكو حساب مستخدم موجود.")
            return

        current_password = self.current_password_input.text().strip()
        if not current_password or not verify_password(current_password, user.password_hash):
            QMessageBox.warning(self, "تنبيه", "كلمة المرور الحالية غلط أو ما كتبتها. لازم تكتبها صح قبل أي تعديل.")
            return

        new_username = self.username_input.text().strip()
        if not new_username:
            QMessageBox.warning(self, "تنبيه", "اسم المستخدم ما يصير فاضي.")
            return
        user.username = new_username
        new_password = self.new_password_input.text().strip()
        if new_password:
            if len(new_password) < 6:
                QMessageBox.warning(self, "تنبيه", "كلمة المرور الجديدة لازم تكون 6 أحرف/أرقام على الأقل.")
                return
            user.password_hash = hash_password(new_password)
            user.must_change_password = False
        self.session.commit()
        self.new_password_input.clear()
        self.current_password_input.clear()
        QMessageBox.information(self, "تم", "تم تحديث بيانات الحساب. استخدمها بتسجيل الدخول الجاي.")

    def _advisor_section(self):
        frame, v = self._card("المستشار الذكي (AI)")

        note = QLabel(
            "اختار المزوّد حسب نوع المفتاح اللي عندك، والصق المفتاح تحت. "
            "هذا يكلّف حسب استخدامك عند المزوّد، ويحتاج انترنت شغّال بجهاز الصيدلية."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#6B7280;font-size:12px;margin-bottom:6px;")
        v.addWidget(note)

        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("المزوّد:"))
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Google Gemini", "gemini")
        self.provider_combo.addItem("Anthropic Claude", "anthropic")
        disable_scroll(self.provider_combo)
        current_provider = get_setting(self.session, "ai_provider", "gemini")
        idx = self.provider_combo.findData(current_provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        provider_row.addWidget(self.provider_combo)
        v.addLayout(provider_row)

        row = QHBoxLayout()
        row.addWidget(QLabel("مفتاح API:"))
        self.api_key_input = QLineEdit(get_setting(self.session, "ai_api_key", ""))
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("مفتاح Gemini أو sk-ant-... حسب المزوّد المختار")
        row.addWidget(self.api_key_input)
        v.addLayout(row)

        save_btn = QPushButton("حفظ إعدادات المستشار")
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px;")
        save_btn.clicked.connect(self._save_advisor)
        v.addWidget(save_btn)
        return frame

    def _save_advisor(self):
        set_setting(self.session, "ai_api_key", self.api_key_input.text().strip())
        set_setting(self.session, "ai_provider", self.provider_combo.currentData())
        QMessageBox.information(self, "تم", "تم حفظ إعدادات المستشار الذكي.")

    def _support_section(self):
        frame, v = self._card("الدعم الفني")

        info = QLabel(f"لأي استفسار أو مشكلة بالبرنامج، تواصل معنا مباشرة:\n{SUPPORT_WHATSAPP_NUMBER}")
        info.setWordWrap(True)
        info.setStyleSheet("color:#6B7280;font-size:13px;margin-bottom:8px;")
        v.addWidget(info)

        wa_btn = QPushButton("تواصل معنا عبر واتساب")
        wa_btn.setIcon(icon("chat", color="white", size=15))
        wa_btn.setStyleSheet(
            "background:#25D366;color:white;border-radius:8px;padding:10px;font-weight:bold;font-size:13px;"
        )
        wa_btn.clicked.connect(self._open_whatsapp)
        v.addWidget(wa_btn)
        return frame

    def _open_whatsapp(self):
        # تحويل الرقم المحلي (07...) لصيغة دولية عراقية (964...) اللي يحتاجها رابط واتساب
        international = "964" + SUPPORT_WHATSAPP_NUMBER.lstrip("0")
        QDesktopServices.openUrl(QUrl(f"https://wa.me/{international}"))

    def refresh(self):
        pass
