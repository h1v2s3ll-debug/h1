"""
شاشة تسجيل الدخول.

مهم جدًا تقرأ هذي الملاحظة:
هذا الإصدار يسوي تحقق محلي بس (يوزر/باسورد مخزنين بقاعدة البيانات المحلية).
نظام "الموافقة عبر الإيميل عند أول تفعيل" و"ربط الترخيص بالجهاز" اللي اتفقنا
عليه بالنقاش يحتاج سيرفر مركزي منفصل (شوف مجلد server/) وتوصيل حقيقي بحساب
جيميلك - هذا شي ما أقدر أفعّله تلقائيًا لأنه يحتاج بيانات اعتماد حساسة منك
(App Password من جوجل) ونشر السيرفر على استضافة فعلية. التفاصيل بملف README.md.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton, QLabel, QMessageBox, QFrame
)
from PySide6.QtCore import Qt

from app.db.database import get_session
from app.db.models import User
from app.db.auth_helper import hash_password, verify_password, is_legacy_hash
from app.db.recovery_helper import verify_recovery_code
from app.licensing.license_manager import get_device_id
from app.ui.icons import icon
from app.ui.widgets import add_shadow
from app.ui.theme import (
    TEAL_400, TEAL_700, TEAL_800, COLOR_TEXT_SECONDARY, COLOR_SURFACE, COLOR_BORDER,
    SPACE_8, SPACE_12, SPACE_16, SPACE_20, SPACE_24, RADIUS_CARD, SHADOW_LARGE,
)


def ensure_default_admin():
    session = get_session()
    if session.query(User).count() == 0:
        # must_change_password=True يجبر صاحب الصيدلية يغيّر "admin123" فور
        # أول دخول - قبل هذا الإصلاح كانت مجرد نصيحة نصية بشاشة الدخول
        # (يقدر يتجاهلها للأبد)، والآن صار إجراء إجباري فعلي.
        session.add(User(
            name="صاحب الصيدلية", username="admin",
            password_hash=hash_password("admin123"), role="owner",
            must_change_password=True,
        ))
        session.commit()
    # ملاحظة: ما نسكر الجلسة المشتركة (scoped_session) هنا أبدًا - سكرها كان
    # يفصل أي كائن يتحمّل لاحقًا بالبرنامج (مثل المستخدم المسجّل دخوله) عن
    # الجلسة (DetachedInstanceError) بمجرد أول استخدام لأي شي يشارك نفس الجلسة.


class ForceChangePasswordDialog(QDialog):
    """نافذة إجبارية تظهر فور تسجيل الدخول لأول مرة (أو لأي حساب لسا
    مضبوط عليه must_change_password) - ما يقدر يدخل للبرنامج قبل ما يغيّر
    كلمة المرور الافتراضية/الضعيفة بوحدة جديدة يختارها بنفسه."""
    def __init__(self, user, session, parent=None):
        super().__init__(parent)
        self.user = user
        self.session = session
        self.setWindowTitle("لازم تغيّر كلمة المرور")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(380)
        self.setModal(True)

        layout = QVBoxLayout(self)
        warn_lbl = QLabel("⚠️ هذا حساب بكلمة مرور افتراضية/قديمة. لازم تحط كلمة مرور جديدة الآن قبل ما تكمل.")
        warn_lbl.setWordWrap(True)
        warn_lbl.setStyleSheet(f"color:{TEAL_800};font-weight:700;")
        layout.addWidget(warn_lbl)

        form = QFormLayout()
        self.new_pass = QLineEdit()
        self.new_pass.setEchoMode(QLineEdit.Password)
        self.confirm_pass = QLineEdit()
        self.confirm_pass.setEchoMode(QLineEdit.Password)
        form.addRow("كلمة المرور الجديدة:", self.new_pass)
        form.addRow("تأكيد كلمة المرور:", self.confirm_pass)
        layout.addLayout(form)

        save_btn = QPushButton("حفظ والمتابعة")
        save_btn.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:8px;padding:10px;font-weight:700;"
        )
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

    def _save(self):
        new_pass = self.new_pass.text()
        if len(new_pass) < 6:
            QMessageBox.warning(self, "تنبيه", "كلمة المرور لازم تكون 6 أحرف/أرقام على الأقل.")
            return
        if new_pass != self.confirm_pass.text():
            QMessageBox.warning(self, "تنبيه", "كلمة المرور وتأكيدها غير متطابقين.")
            return
        if new_pass == "admin123":
            QMessageBox.warning(self, "تنبيه", "لازم تختار كلمة مرور غير الافتراضية.")
            return
        self.user.password_hash = hash_password(new_pass)
        self.user.must_change_password = False
        self.session.commit()
        self.accept()


class ForgotPasswordDialog(QDialog):
    """نافذة استرجاع الوصول: تعرض بصمة الجهاز (Device ID) للعميل يعطيها
    للدعم الفني، ويدخل الرمز اللي يرجعله. الرمز مرتبط بهذا الجهاز تحديدًا
    - ما يشتغل بجهاز عميل ثاني حتى لو تسرب. راجع app/db/recovery_helper.py
    لتفاصيل أوسع عن التصميم وقيوده."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("استرجاع الوصول")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(420)
        self.setModal(True)
        self.recovered_user = None

        layout = QVBoxLayout(self)
        info_lbl = QLabel("تواصل مع الدعم الفني وأعطهم بصمة الجهاز اللي تحت، وهم راح يعطونك رمز استرجاع خاص بجهازك تحطه هنا.")
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        self.device_id = get_device_id()
        device_row = QHBoxLayout()
        device_value = QLineEdit(self.device_id)
        device_value.setReadOnly(True)
        device_row.addWidget(device_value)
        copy_btn = QPushButton("نسخ")
        copy_btn.clicked.connect(self._copy_device_id)
        device_row.addWidget(copy_btn)
        layout.addLayout(device_row)

        form = QFormLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("رمز الاسترجاع اللي عطاك ياه الدعم الفني")
        form.addRow("رمز الاسترجاع:", self.code_input)
        layout.addLayout(form)

        confirm_btn = QPushButton("تأكيد")
        confirm_btn.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:8px;padding:10px;font-weight:700;"
        )
        confirm_btn.clicked.connect(self._try_recover)
        layout.addWidget(confirm_btn)

    def _copy_device_id(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.device_id)

    def _try_recover(self):
        if not verify_recovery_code(self.device_id, self.code_input.text()):
            QMessageBox.warning(self, "خطأ", "رمز الاسترجاع غلط. تأكد إنك نسخت الرمز صح من الدعم الفني.")
            return
        session = get_session()
        admin = session.query(User).filter_by(role="owner").first() or session.query(User).first()
        if not admin:
            QMessageBox.warning(self, "خطأ", "ماكو حساب مستخدم موجود بالأساس.")
            return
        # نعطيه كلمة مرور مؤقتة عشوائية ونجبره يغيّرها فورًا - ما نرجّع
        # كلمة المرور القديمة ونعرضها (حتى لو كانت معروفة قبل الاسترجاع).
        import secrets
        temp_password = secrets.token_hex(4)
        admin.password_hash = hash_password(temp_password)
        admin.must_change_password = True
        session.commit()
        QMessageBox.information(
            self, "تم الاسترجاع",
            f"كلمة مرور مؤقتة لحساب {admin.username}: {temp_password}\n\n"
            "سجّل دخول فيها الآن - راح يطلب منك تحط كلمة مرور جديدة فورًا."
        )
        self.recovered_user = admin
        self.accept()


class LoginWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("تسجيل الدخول - H1")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedWidth(400)
        self.authenticated_user = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE_20, SPACE_20, SPACE_20, SPACE_20)

        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{COLOR_SURFACE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_CARD + 4}px;}}"
        )
        add_shadow(card, blur=SHADOW_LARGE["blur"], color=TEAL_700,
                   alpha=SHADOW_LARGE["alpha"], y_offset=SHADOW_LARGE["y_offset"])
        layout = QVBoxLayout(card)
        layout.setContentsMargins(SPACE_24, SPACE_24, SPACE_24, SPACE_24)
        layout.setSpacing(SPACE_12)

        brand_icon = QLabel()
        brand_icon.setAlignment(Qt.AlignCenter)
        brand_icon.setStyleSheet("background:transparent;border:none;")
        brand_icon.setPixmap(icon("store", color=TEAL_700, size=34).pixmap(34, 34))
        layout.addWidget(brand_icon)

        title = QLabel("H1")
        title.setStyleSheet(f"font-size:24px;font-weight:800;color:{TEAL_800};background:transparent;border:none;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        sub = QLabel("نظام إدارة الصيدليات المتكامل")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color:{COLOR_TEXT_SECONDARY};background:transparent;border:none;margin-bottom:{SPACE_8}px;")
        layout.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(SPACE_12)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("admin")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("••••••••")
        form.addRow("اسم المستخدم:", self.username_input)
        form.addRow("كلمة المرور:", self.password_input)
        layout.addLayout(form)

        hint = QLabel("(الافتراضي أول تشغيل: admin / admin123 - راح يطلب منك تغييرها فورًا بأول دخول)")
        hint.setStyleSheet(f"color:{COLOR_TEXT_SECONDARY};font-size:11px;background:transparent;border:none;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        forgot_btn = QPushButton("نسيت كلمة المرور؟")
        forgot_btn.setCursor(Qt.PointingHandCursor)
        forgot_btn.setStyleSheet(
            f"background:transparent;border:none;color:{TEAL_700};font-size:12px;text-decoration:underline;"
        )
        forgot_btn.clicked.connect(self._open_forgot_password)
        layout.addWidget(forgot_btn, alignment=Qt.AlignCenter)

        login_btn = QPushButton("دخول")
        login_btn.setIcon(icon("check", color="white", size=16))
        login_btn.setMinimumHeight(44)
        login_btn.setCursor(Qt.PointingHandCursor)
        login_btn.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:10px;padding:10px;font-weight:800;font-size:14px;border:none;"
        )
        login_btn.clicked.connect(self.try_login)
        layout.addWidget(login_btn)

        outer.addWidget(card)
        self.password_input.returnPressed.connect(self.try_login)

    def _open_forgot_password(self):
        dialog = ForgotPasswordDialog(parent=self)
        if dialog.exec() == QDialog.Accepted and dialog.recovered_user:
            QMessageBox.information(
                self, "تم",
                "استخدم اسم المستخدم وكلمة المرور المؤقتة اللي ظهرت لك عشان تسجّل دخول الآن."
            )

    def try_login(self):
        session = get_session()
        user = session.query(User).filter_by(username=self.username_input.text().strip()).first()
        raw_password = self.password_input.text()
        if not user or not verify_password(raw_password, user.password_hash):
            QMessageBox.warning(self, "خطأ", "اسم المستخدم أو كلمة المرور غير صحيحة.")
            return

        if is_legacy_hash(user.password_hash):
            # ترقية شفافة: أول تسجيل دخول ناجح بكلمة مرور محفوظة بالصيغة
            # القديمة الضعيفة (SHA-256 بدون ملح) يعيد تشفيرها بالصيغة
            # الجديدة الأقوى فورًا - بدون ما يحتاج المستخدم يسوي أي شي إضافي.
            user.password_hash = hash_password(raw_password)
            session.commit()

        if user.must_change_password:
            dialog = ForceChangePasswordDialog(user, session, parent=self)
            if dialog.exec() != QDialog.Accepted:
                return  # ما غيّر كلمة المرور - ما يدخل للبرنامج

        self.authenticated_user = user
        self.accept()
