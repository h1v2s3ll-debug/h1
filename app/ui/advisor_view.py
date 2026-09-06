"""
شاشة المستشار الذكي - محادثة تفاعلية تستخدم مفتاح API اللي تحفظه بالإعدادات.
يدعم مزوّدين: Google Gemini (افتراضي) و Anthropic Claude - تختار المزوّد
من شاشة الإعدادات حسب نوع المفتاح اللي عندك.

⚠️ يحتاج انترنت شغّال بجهاز الصيدلية وقت الاستخدام، ويحتاج مفتاح API صحيح
محفوظ من شاشة الإعدادات، وقد يترتب عليه تكلفة استخدام حسب سياسة المزوّد.
"""
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QPushButton, QLabel
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QTextCursor

from app.db.database import get_session
from app.db.settings_helper import get_setting
from app.db.models import Product, Batch


class AdvisorWorker(QThread):
    """يشغّل طلب الـAPI بخيط منفصل حتى ما يجمّد واجهة البرنامج وقت الانتظار."""
    finished_ok = Signal(str)
    finished_error = Signal(str)

    def __init__(self, advisor_view, api_key, user_text):
        super().__init__()
        self.advisor_view = advisor_view
        self.api_key = api_key
        self.user_text = user_text

    def run(self):
        try:
            reply = self.advisor_view.call_ai(self.api_key, self.user_text)
            self.finished_ok.emit(reply)
        except Exception as e:
            self.finished_error.emit(str(e))


class AdvisorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = get_session()
        self.history = []

        layout = QVBoxLayout(self)
        title = QLabel("المستشار الذكي")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        layout.addWidget(title)

        hint = QLabel("اسأله مثلاً: شنو الأدوية اللي مخزونها منخفض؟ أو: اعطني نصيحة لتقليل الهدر بالمخزون.")
        hint.setStyleSheet("color:#6B7280;font-size:12px;")
        layout.addWidget(hint)

        self.chat_box = QTextEdit()
        self.chat_box.setReadOnly(True)
        self.chat_box.setStyleSheet("background:white;border:1px solid #E5E7EB;border-radius:10px;padding:8px;")
        layout.addWidget(self.chat_box, stretch=1)

        input_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("اكتب سؤالك هنا...")
        self.input_field.returnPressed.connect(self.send_message)
        send_btn = QPushButton("إرسال")
        send_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px 16px;")
        send_btn.clicked.connect(self.send_message)
        self.send_btn = send_btn
        input_row.addWidget(self.input_field, stretch=1)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

    def send_message(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.input_field.clear()
        self._append("أنت", text)

        api_key = get_setting(self.session, "ai_api_key", "")
        if not api_key:
            self._append("المستشار", "ماكو مفتاح API محفوظ بعد - روح لشاشة الإعدادات وضيفه أول.")
            return

        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.send_btn.setText("...جاري الإرسال")
        self._show_typing_indicator()

        self._worker = AdvisorWorker(self, api_key, text)
        self._worker.finished_ok.connect(self._on_reply_ok)
        self._worker.finished_error.connect(self._on_reply_error)
        self._worker.start()

    def _show_typing_indicator(self):
        """يضيف سطر "المستشار يكتب..." مؤقت بآخر صندوق المحادثة، ويشغّل مؤقّت
        يبدّل عدد النقاط (. .. ...) كل نص ثانية عشان يبان متحرك زي أي شات
        ذكاء اصطناعي معتاد - يُشال تلقائيًا لما يوصل الرد الفعلي (نجاح أو خطأ)."""
        self.chat_box.append('<span style="color:#9CA3AF;"><b>المستشار:</b> <i id="typing">يكتب</i></span>')
        self._typing_dots = 0
        self._typing_timer = QTimer(self)
        self._typing_timer.timeout.connect(self._animate_typing_indicator)
        self._typing_timer.start(500)

    def _animate_typing_indicator(self):
        self._typing_dots = (self._typing_dots + 1) % 4
        dots = "." * self._typing_dots
        cursor = self.chat_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.BlockUnderCursor)
        cursor.removeSelectedText()
        cursor.deletePreviousChar()
        self.chat_box.append(f'<span style="color:#9CA3AF;"><b>المستشار:</b> <i>يكتب{dots}</i></span>')

    def _remove_typing_indicator(self):
        if getattr(self, "_typing_timer", None) is not None:
            self._typing_timer.stop()
            self._typing_timer = None
        cursor = self.chat_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.BlockUnderCursor)
        cursor.removeSelectedText()
        cursor.deletePreviousChar()

    def _on_reply_ok(self, reply):
        self._remove_typing_indicator()
        self._append("المستشار", reply)
        self._reset_input_state()

    def _on_reply_error(self, msg):
        if "HTTP 401" in msg or "HTTP 400" in msg or "authentication" in msg.lower() or "UNAUTHENTICATED" in msg or "API_KEY_INVALID" in msg or "API key not valid" in msg:
            reply = f"❌ المفتاح غير صحيح أو منتهي.\n{msg}"
        elif "HTTP 404" in msg or "not_found" in msg.lower():
            reply = f"❌ خطأ بإعدادات الموديل (مشكلة بالكود، خبرني وأصلحها).\n{msg}"
        elif "getaddrinfo" in msg or "Network is unreachable" in msg or "timed out" in msg:
            reply = (
                "❌ ماكو اتصال بالانترنت من داخل البرنامج.\n"
                "جرب تتأكد: (1) عندك نت شغّال بهذا الجهاز، (2) جدار حماية ويندوز "
                "(Windows Defender Firewall) ما يكون حاظر بايثون - لو طلعت نافذة "
                "\"Windows requires your permission\" أول مرة شغّلت البرنامج، تأكد ضغطت "
                "\"Allow access\" مو \"Cancel\"."
            )
        else:
            reply = f"صار خطأ غير متوقع: {msg}"
        self._remove_typing_indicator()
        self._append("المستشار", reply)
        self._reset_input_state()

    def _reset_input_state(self):
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.send_btn.setText("إرسال")
        self.input_field.setFocus()

    def call_ai(self, api_key, user_text):
        provider = get_setting(self.session, "ai_provider", "gemini")
        if provider == "gemini":
            return self._call_gemini(api_key, user_text)
        return self._call_anthropic(api_key, user_text)

    def _call_gemini(self, api_key, user_text):
        import urllib.request
        import urllib.error

        context = self._safe_context()
        model = "gemini-flash-latest"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": user_text}]}],
            "systemInstruction": {
                "parts": [{"text": f"انت مستشار ذكي لصيدلية عراقية اسمها H1. جاوب بالعربي بإيجاز ووضوح. {context}"}]
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            raise Exception(f"HTTP {e.code}: {body}") from e
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            return f"(رد غير متوقع من Gemini): {data}"

    def _call_anthropic(self, api_key, user_text):
        import urllib.request
        import urllib.error

        context = self._safe_context()
        payload = {
            "model": "claude-sonnet-5",
            "max_tokens": 500,
            "system": f"انت مستشار ذكي لصيدلية عراقية اسمها H1. جاوب بالعربي بإيجاز ووضوح. {context}",
            "messages": [{"role": "user", "content": user_text}],
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            raise Exception(f"HTTP {e.code}: {body}") from e
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return "\n".join(parts) if parts else "(ماكو رد نصي من المستشار)"

    def _safe_context(self):
        try:
            products = self.session.query(Product).all()
            low = [p.name for p in products if sum(b.quantity_available for b in p.batches) <= 10]
            return f"معلومة سياقية: أدوية مخزونها منخفض حاليًا: {', '.join(low[:15]) if low else 'ماكو'}."
        except Exception:
            return ""

    def _append(self, sender, text):
        self.history.append((sender, text))
        self.chat_box.append(f"<b>{sender}:</b> {text}<br>")

    def refresh(self):
        pass
