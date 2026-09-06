"""
نوافذ التفعيل - تظهر بس أول مرة، أو أثناء التجربة (تنبيه بسيط)، أو لو انحظر
البرنامج. باقي الوقت (بعد التفعيل والتحقق الناجح) ما تظهر هذي النوافذ إطلاقًا.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QLabel,
)
from PySide6.QtCore import Qt

from app.licensing.config import APP_DISPLAY_NAME, SUPPORT_WHATSAPP_NUMBER

GREEN_BTN = (
    "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);"
    "color:white;border-radius:8px;padding:10px;font-weight:bold;"
)
RED_BTN = (
    "background:#D9483A;color:white;border-radius:8px;padding:10px;font-weight:bold;"
)


class ActivationWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(380)
        self._layout = QVBoxLayout(self)
        self.result_data = None

    # ---------- تسجيل + خيار "تجربة بدون تسجيل" (تظهر كل فتحة لين يسجل فعليًا) ----------
    @staticmethod
    def ask_registration_or_trial(parent=None, days_left=None):
        dlg = ActivationWindow(parent)
        dlg.setWindowTitle(f"تسجيل الصيدلية - {APP_DISPLAY_NAME}")

        title = QLabel(f"مرحبًا بك في {APP_DISPLAY_NAME}")
        title.setStyleSheet("font-size:16px;font-weight:bold;margin-bottom:6px;")
        dlg._layout.addWidget(title)

        if days_left is not None:
            trial_lbl = QLabel(f"باقيلك {days_left} يوم من التجربة المجانية.")
            trial_lbl.setStyleSheet("color:#6B7280;margin-bottom:6px;")
            dlg._layout.addWidget(trial_lbl)

        subtitle = QLabel("سجّل بيانات الصيدلية الحين لإرسال طلب التفعيل، أو تقدر تكمل تجربة بدون تسجيل وترجع تسجل بأي وقت.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#6B7280;margin-bottom:10px;")
        dlg._layout.addWidget(subtitle)

        contact_lbl = QLabel(f"لإتمام التسجيل تواصل معنا على الواتساب: {SUPPORT_WHATSAPP_NUMBER}")
        contact_lbl.setWordWrap(True)
        contact_lbl.setStyleSheet("color:#16A34A;font-weight:bold;margin-bottom:10px;")
        dlg._layout.addWidget(contact_lbl)

        form = QFormLayout()
        name_input = QLineEdit()
        phone_input = QLineEdit()
        form.addRow("اسم الصيدلية:", name_input)
        form.addRow("رقم الهاتف:", phone_input)
        dlg._layout.addLayout(form)

        error_lbl = QLabel("")
        error_lbl.setStyleSheet("color:#D9483A;")
        dlg._layout.addWidget(error_lbl)

        register_btn = QPushButton("إرسال طلب التفعيل الآن")
        register_btn.setStyleSheet(GREEN_BTN)
        dlg._layout.addWidget(register_btn)

        trial_btn = QPushButton("متابعة تجربة بدون تسجيل")
        trial_btn.setStyleSheet("background:transparent;color:#6B7280;border:1px solid #D8DEDB;border-radius:8px;padding:8px;")
        dlg._layout.addWidget(trial_btn)

        def on_register():
            name = name_input.text().strip()
            phone = phone_input.text().strip()
            if not name or not phone:
                error_lbl.setText("لازم تعبي اسم الصيدلية ورقم الهاتف عشان ترسل طلب التفعيل")
                return
            dlg.result_data = {"action": "register", "name": name, "phone": phone}
            dlg.accept()

        def on_trial():
            dlg.result_data = {"action": "trial"}
            dlg.accept()

        register_btn.clicked.connect(on_register)
        trial_btn.clicked.connect(on_trial)
        dlg.exec()
        # لو سكّر النافذة بـ X بدون ما يضغط أي زر، نعتبرها "متابعة تجربة" حتى ما يعلّق البرنامج
        return dlg.result_data or {"action": "trial"}

    # ---------- تسجيل أول مرة (تبقى موجودة للاستخدام المباشر لو احتجناها لاحقًا) ----------
    @staticmethod
    def ask_registration(parent=None):
        result = ActivationWindow.ask_registration_or_trial(parent)
        if result.get("action") == "register":
            return {"name": result["name"], "phone": result["phone"]}
        return None

    # ---------- عرض/تعديل بيانات التسجيل المحفوظة قبل إعادة الإرسال ----------
    @staticmethod
    def _ask_resend_details(parent, current_name, current_phone):
        dlg = ActivationWindow(parent)
        dlg.setWindowTitle("مراجعة بيانات التسجيل")

        title = QLabel("بيانات الصيدلية المحفوظة")
        title.setStyleSheet("font-size:14px;font-weight:bold;margin-bottom:6px;")
        subtitle = QLabel("راجع البيانات وعدّلها إذا لازم قبل إعادة إرسال طلب التفعيل.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#6B7280;margin-bottom:8px;")
        dlg._layout.addWidget(title)
        dlg._layout.addWidget(subtitle)

        form = QFormLayout()
        name_input = QLineEdit(current_name or "")
        phone_input = QLineEdit(current_phone or "")
        form.addRow("اسم الصيدلية:", name_input)
        form.addRow("رقم الهاتف:", phone_input)
        dlg._layout.addLayout(form)

        error_lbl = QLabel("")
        error_lbl.setStyleSheet("color:#D9483A;")
        dlg._layout.addWidget(error_lbl)

        send_btn = QPushButton("إعادة إرسال الطلب")
        send_btn.setStyleSheet(GREEN_BTN)
        dlg._layout.addWidget(send_btn)

        def on_send():
            name = name_input.text().strip()
            phone = phone_input.text().strip()
            if not name or not phone:
                error_lbl.setText("لازم تعبي اسم الصيدلية ورقم الهاتف عشان ترسل طلب التفعيل")
                return
            dlg.result_data = {"name": name, "phone": phone}
            dlg.accept()

        send_btn.clicked.connect(on_send)
        dlg.exec()
        return dlg.result_data

    # ---------- تنبيه أثناء فترة التجربة ----------
    @staticmethod
    def show_trial_notice(parent, days_left, resend_callback=None, current_name=None, current_phone=None):
        dlg = ActivationWindow(parent)
        dlg.setWindowTitle("نسخة تجريبية")

        title = QLabel("نسخة تجريبية")
        title.setStyleSheet("font-size:16px;font-weight:bold;")
        msg = QLabel(
            f"بعدك بفترة التجربة المجانية - تبقى {days_left} يوم.\n"
            "طلب التفعيل عندنا وننتظر الموافقة، وراح يشتغل البرنامج تلقائيًا بمجرد ما توافق."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("color:#6B7280;margin:8px 0;")
        dlg._layout.addWidget(title)
        dlg._layout.addWidget(msg)

        status_lbl = QLabel("")
        status_lbl.setStyleSheet("color:#16A34A;font-size:12px;")
        status_lbl.setWordWrap(True)
        dlg._layout.addWidget(status_lbl)

        if resend_callback:
            resend_btn = QPushButton("🔄 أعد إرسال الطلب (لو تشك إنه ما وصل)")
            resend_btn.setStyleSheet(
                "background:transparent;color:#16A34A;border:1px solid #16A34A;"
                "border-radius:8px;padding:8px;"
            )

            def on_resend():
                # نفتح نافذة تعرض الاسم/الرقم المحفوظين حاليًا حتى يقدر المستخدم
                # يطّلع عليهم أو يعدّلهم (مثلاً لو دخل رقم غلط أول مرة) قبل إعادة الإرسال.
                details = ActivationWindow._ask_resend_details(dlg, current_name, current_phone)
                if not details:
                    return  # ألغى النافذة بدون إرسال
                ok = resend_callback(details["name"], details["phone"])
                status_lbl.setText("✓ تم إعادة إرسال الطلب." if ok else "تعذر الإرسال - تأكد من الاتصال بالإنترنت وحاول مرة ثانية.")

            resend_btn.clicked.connect(on_resend)
            dlg._layout.addWidget(resend_btn)

        ok_btn = QPushButton("متابعة")
        ok_btn.setStyleSheet(GREEN_BTN)
        ok_btn.clicked.connect(dlg.accept)
        dlg._layout.addWidget(ok_btn)
        dlg.exec()

    # ---------- حظر كامل (رفض/إلغاء/انتهاء التجربة/انقطاع اتصال طويل) ----------
    @staticmethod
    def show_blocked(parent, message):
        dlg = ActivationWindow(parent)
        dlg.setWindowTitle("البرنامج متوقف")

        title = QLabel("⚠ البرنامج متوقف مؤقتًا")
        title.setStyleSheet("font-size:16px;font-weight:bold;color:#D9483A;")
        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet("color:#6B7280;margin:8px 0;")
        dlg._layout.addWidget(title)
        dlg._layout.addWidget(msg)

        contact_lbl = QLabel(f"للتفعيل تواصل معنا على الواتساب: {SUPPORT_WHATSAPP_NUMBER}")
        contact_lbl.setWordWrap(True)
        contact_lbl.setStyleSheet("color:#16A34A;font-weight:bold;margin-bottom:8px;")
        dlg._layout.addWidget(contact_lbl)

        exit_btn = QPushButton("إغلاق")
        exit_btn.setStyleSheet(RED_BTN)
        exit_btn.clicked.connect(dlg.accept)
        dlg._layout.addWidget(exit_btn)
        dlg.exec()
