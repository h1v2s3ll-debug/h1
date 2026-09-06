"""بطاقة صغيرة (تُضمّن داخل شاشة المشتريات) تعرض رابط ورمز الدخول لصفحة
إضافة/تحديث الأدوية من الموبايل، مع تشخيص فعلي لحالة السيرفر."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from app.ui.widgets import add_shadow
from app.ui.icons import icon, pixmap
from app.ui.theme import PANEL, LINE, INK, INK_2, TEAL_600, TEAL_800, RED_500

try:
    from app.mobile_server import get_or_create_pin, regenerate_pin, get_all_lan_ips, is_server_running, PORT
    MOBILE_SERVER_AVAILABLE = True
except ImportError:
    MOBILE_SERVER_AVAILABLE = False

try:
    import qrcode
    import io
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False


class MobileLinkCard(QWidget):
    """أضفها داخل أي شاشة (مثلاً المشتريات) عن طريق: layout.addWidget(MobileLinkCard())"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not MOBILE_SERVER_AVAILABLE:
            warn = QFrame()
            warn.setStyleSheet("background:#FFFBEB;border:1px solid #F59E0B;border-radius:10px;padding:14px;")
            warn_layout = QVBoxLayout(warn)
            warn_lbl = QLabel(
                "⚠️ ميزة \"إضافة من الموبايل\" تحتاج مكتبات مو منصبة عندك بعد.\n"
                "نفذ بالـ CMD: pip install fastapi uvicorn pydantic\n"
                "وسكر البرنامج وافتحه من جديد."
            )
            warn_lbl.setStyleSheet("color:#92400E;font-size:12px;")
            warn_lbl.setWordWrap(True)
            warn_layout.addWidget(warn_lbl)
            layout.addWidget(warn)
            return

        card = QFrame()
        card.setStyleSheet(f"background:{PANEL};border:1px solid {LINE};border-radius:14px;padding:16px;")
        add_shadow(card, blur=14, color="#16A34A", alpha=16, y_offset=2)
        card_layout = QVBoxLayout(card)

        header_row = QHBoxLayout()
        title_icon_lbl = QLabel()
        title_icon_lbl.setStyleSheet("background:transparent;border:none;")
        title_icon_lbl.setPixmap(pixmap("smartphone", color=TEAL_800, size=15))
        header_row.addWidget(title_icon_lbl)
        title = QLabel("إضافة/تحديث الأدوية من الموبايل")
        title.setStyleSheet(f"font-weight:800;font-size:14px;color:{TEAL_800};background:transparent;border:none;")
        header_row.addWidget(title)
        header_row.addStretch()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-size:12px;font-weight:bold;")
        header_row.addWidget(self.status_lbl)
        check_btn = QPushButton("تحقق الآن")
        check_btn.setIcon(icon("refresh", color=TEAL_600, size=13))
        check_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:4px 10px;font-size:12px;")
        check_btn.clicked.connect(self.refresh)
        header_row.addWidget(check_btn)
        card_layout.addLayout(header_row)

        links_caption = QLabel("امسح الباركود تحت مباشرة بكاميرا الموبايل. لو ما اشتغل، اضغط عنوان ثاني من القائمة يمين حتى يتغيّر الباركود له:")
        links_caption.setStyleSheet(f"color:{INK_2};font-size:12px;margin-top:6px;")
        links_caption.setWordWrap(True)
        card_layout.addWidget(links_caption)

        content_row = QHBoxLayout()
        self.links_box = QVBoxLayout()
        content_row.addLayout(self.links_box, stretch=1)

        self.qr_label = QLabel()
        self.qr_label.setFixedSize(180, 180)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setStyleSheet(f"background:white;border:1px solid {LINE};border-radius:8px;")
        content_row.addWidget(self.qr_label)
        card_layout.addLayout(content_row)

        pin_row = QHBoxLayout()
        pin_box = QVBoxLayout()
        pin_caption = QLabel("رمز الدخول (PIN):")
        pin_caption.setStyleSheet(f"color:{INK_2};font-size:12px;")
        self.pin_value = QLabel("")
        self.pin_value.setStyleSheet(f"color:{INK};font-weight:800;font-size:22px;letter-spacing:5px;")
        pin_box.addWidget(pin_caption)
        pin_box.addWidget(self.pin_value)
        pin_row.addLayout(pin_box)
        pin_row.addStretch()
        regen_btn = QPushButton("رمز جديد")
        regen_btn.setIcon(icon("refresh", color="white", size=14))
        regen_btn.setStyleSheet(f"background:{TEAL_600};color:white;border-radius:8px;padding:8px 14px;")
        regen_btn.clicked.connect(self.regenerate)
        pin_row.addWidget(regen_btn)
        card_layout.addLayout(pin_row)

        note = QLabel(
            "⚠️ لازم اللابتوب مفتوح والبرنامج شغال. لو ماكو استجابة بالموبايل، تأكد إن "
            "\"جدار حماية ويندوز\" (Windows Defender Firewall) مو حاظر البرنامج - "
            "لازم يطلعلك نافذة \"السماح بالوصول / Allow access\" أول مرة تفتح البرنامج، اضغط سماح."
        )
        note.setStyleSheet(f"color:{INK_2};font-size:11px;margin-top:8px;")
        note.setWordWrap(True)
        card_layout.addWidget(note)

        layout.addWidget(card)
        self._current_ip = None
        self.refresh()

    def refresh(self):
        running = is_server_running()
        if running:
            self.status_lbl.setText("● السيرفر شغال")
            self.status_lbl.setStyleSheet(f"color:{TEAL_800};font-size:12px;font-weight:bold;")
        else:
            self.status_lbl.setText("● السيرفر متوقف")
            self.status_lbl.setStyleSheet(f"color:{RED_500};font-size:12px;font-weight:bold;")

        while self.links_box.count():
            child = self.links_box.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        ips = get_all_lan_ips()
        if self._current_ip not in ips:
            self._current_ip = ips[0] if ips else "127.0.0.1"
        for ip in ips:
            link_btn = QPushButton(f"http://{ip}:{PORT}" + ("  ✓ مُستخدم بالباركود" if ip == self._current_ip else ""))
            link_btn.setStyleSheet(
                f"text-align:right;color:{TEAL_800};font-weight:bold;font-size:13px;"
                f"background:transparent;border:none;padding:2px;"
            )
            link_btn.setCursor(Qt.PointingHandCursor)
            link_btn.clicked.connect(lambda _, i=ip: self._select_ip(i))
            self.links_box.addWidget(link_btn)

        if QR_AVAILABLE and ips:
            try:
                pin = get_or_create_pin()
                primary_link = f"http://{self._current_ip}:{PORT}/?pin={pin}"
                # border=4 (بدل 2) يعطي منطقة سكون أوسع حول الكود، يخلي القراءة أضمن.
                img = qrcode.make(primary_link, box_size=8, border=4)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                pixmap = QPixmap()
                pixmap.loadFromData(buf.getvalue())
                # نصغّر الصورة تناسبيًا لتنحصر بالكامل داخل المربع - قبل هذا التصحيح
                # كانت الصورة أكبر من المربع (150×150) فتنقص أطرافها بدل ما تتصغّر،
                # وباركود منقوص ما ينقرا بأي كاميرا حتى لو الرابط جواه صحيح.
                # QR_PADDING: نترك هامش داخل المربع (بدل ما نملأه بالكامل حافة-لحافة)
                # لأن qr_label نفسه عنده border-radius:8px - لو الصورة تلامس حواف
                # المربع بالضبط، الزوايا الدائرية تقص أطراف الباركود (مربعات التموضع
                # بزواياه) وتقلل مساحة البيانات الفعلية، فبعض الكاميرات ما تقدر تقرأه.
                QR_PADDING = 14
                target_size = min(self.qr_label.width(), self.qr_label.height()) - QR_PADDING
                pixmap = pixmap.scaled(
                    target_size, target_size,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.qr_label.setPixmap(pixmap)
            except Exception:
                self.qr_label.setText("تعذر توليد الباركود\nتأكد من تنصيب:\nPillow")
                self.qr_label.setStyleSheet(f"background:white;border:1px solid {LINE};border-radius:8px;color:{INK_2};font-size:10px;")
        elif not QR_AVAILABLE:
            self.qr_label.setText("ثبت مكتبة\nqrcode و Pillow\nحتى يبين الباركود")
            self.qr_label.setStyleSheet(f"background:white;border:1px solid {LINE};border-radius:8px;color:{INK_2};font-size:10px;")

        self.pin_value.setText(get_or_create_pin())

    def _select_ip(self, ip):
        self._current_ip = ip
        self.refresh()

    def regenerate(self):
        confirm = QMessageBox.question(
            self, "تأكيد",
            "توليد رمز جديد راح يلغي الرمز القديم فورًا. متأكد؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            regenerate_pin()
            self.refresh()
