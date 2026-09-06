"""شاشة الديون: قائمة الزباين المدينين، إضافة دين يدوي، وتسجيل تسديد.

تحديث (H1 Design System): إعادة تصميم بصري بحت ليطابق لغة التصميم المعتمدة
بشاشة البيع (بطاقات موحّدة، أيقونات Lucide، تباعد وألوان من app.ui.theme).
ولا سطر واحد من منطق الاستعلامات أو حساب الديون أو التسديد تغيّر.
"""
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QMessageBox, QInputDialog,
)
from PySide6.QtCore import Qt

from app.db.database import get_session
from app.db.models import Customer, Invoice, Payment
from app.ui.widgets import NumberLineEdit, create_stat_card, create_section_title, enable_touch_scroll
from app.ui.icons import icon
from app.ui.theme import (
    TEAL_400, TEAL_600, TEAL_700, RED_500, COLOR_SURFACE, COLOR_SURFACE_SUBTLE,
    COLOR_BORDER, COLOR_TEXT_PRIMARY, FONT_H1,
    SPACE_8, SPACE_12, SPACE_16, SPACE_20, SPACE_24,
    RADIUS_BUTTON, RADIUS_CARD, RADIUS_INPUT,
)


def fmt_money(n):
    return f"{n:,.0f} د.ع"


class DebtsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = get_session()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_24, SPACE_20, SPACE_24, SPACE_20)
        layout.setSpacing(SPACE_16)

        title = QLabel("الديون")
        title.setStyleSheet(f"font-size:{FONT_H1[0]}px;font-weight:{FONT_H1[1]};background:transparent;border:none;")
        layout.addWidget(title)

        self.summary_row = QHBoxLayout()
        self.summary_row.setSpacing(SPACE_16)
        layout.addLayout(self.summary_row)

        layout.addWidget(create_section_title("إضافة دين يدوي"))
        add_frame = QFrame()
        add_frame.setStyleSheet(
            f"QFrame{{background:{COLOR_SURFACE};border:1px solid {COLOR_BORDER};"
            f"border-radius:{RADIUS_CARD}px;}}"
        )
        add_layout = QHBoxLayout(add_frame)
        add_layout.setContentsMargins(SPACE_16, SPACE_12, SPACE_16, SPACE_12)
        add_layout.setSpacing(SPACE_12)
        input_style = (
            f"border:1.5px solid {COLOR_BORDER};border-radius:{RADIUS_INPUT}px;"
            f"padding:{SPACE_8}px {SPACE_12}px;background-color:{COLOR_SURFACE};"
        )
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("اسم الزبون")
        self.name_input.setStyleSheet(input_style)
        self.name_input.setMinimumHeight(38)
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("رقم الهاتف")
        self.phone_input.setStyleSheet(input_style)
        self.phone_input.setMinimumHeight(38)
        self.amount_input = NumberLineEdit(placeholder="المبلغ")
        self.amount_input.setStyleSheet(input_style)
        self.amount_input.setMinimumHeight(38)
        add_btn = QPushButton("إضافة دين يدوي")
        add_btn.setIcon(icon("plus", color="white", size=15))
        add_btn.setMinimumHeight(42)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});"
            f"color:white;border-radius:{RADIUS_BUTTON}px;padding:8px 16px;font-weight:800;border:none;}}"
        )
        add_btn.clicked.connect(self.add_manual_debt)
        add_layout.addWidget(self.name_input)
        add_layout.addWidget(self.phone_input)
        add_layout.addWidget(self.amount_input)
        add_layout.addWidget(add_btn)
        layout.addWidget(add_frame)

        layout.addWidget(create_section_title("الزبائن المدينون"))
        self.table = QTableWidget()
        enable_touch_scroll(self.table)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["اسم الزبون", "الهاتف", "المبلغ المتبقي", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.refresh()

    def _stat_card(self, number, label, color):
        # يعيد استخدام مكوّن البطاقة الموحّد بدل ستايل خاص هنا - نفس التوقيع بالضبط.
        return create_stat_card(number, label, color)

    def refresh(self):
        while self.summary_row.count():
            child = self.summary_row.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        customers = self.session.query(Customer).filter(Customer.current_balance > 0).order_by(Customer.name).all()
        total = sum(c.current_balance for c in customers)
        self.summary_row.addWidget(self._stat_card(str(len(customers)), "عدد الزبائن المدينين", TEAL_600))
        self.summary_row.addWidget(self._stat_card(fmt_money(total), "إجمالي الديون المتبقية", RED_500))

        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setRowCount(len(customers))
        for row, c in enumerate(customers):
            self.table.setItem(row, 0, QTableWidgetItem(c.name))
            self.table.setItem(row, 1, QTableWidgetItem(c.phone or "-"))
            self.table.setItem(row, 2, QTableWidgetItem(fmt_money(c.current_balance)))
            pay_btn = QPushButton("تسجيل تسديد")
            pay_btn.setIcon(icon("cash", color=TEAL_600, size=13))
            pay_btn.setCursor(Qt.PointingHandCursor)
            pay_btn.setMinimumHeight(38)
            pay_btn.setStyleSheet(
                f"background:{COLOR_SURFACE_SUBTLE};color:{COLOR_TEXT_PRIMARY};border:1px solid {COLOR_BORDER};"
                f"border-radius:{RADIUS_BUTTON}px;padding:4px 12px;font-weight:700;"
            )
            pay_btn.clicked.connect(lambda _, cid=c.id: self.record_payment(cid))
            self.table.setCellWidget(row, 3, pay_btn)
        self.table.resizeRowsToContents()

    def add_manual_debt(self):
        name = self.name_input.text().strip()
        phone = self.phone_input.text().strip()
        amount = self.amount_input.value()
        if not name or amount <= 0:
            QMessageBox.warning(self, "تنبيه", "لازم تدخل اسم الزبون ومبلغ أكبر من صفر.")
            return
        customer = self.session.query(Customer).filter_by(name=name, phone=phone).first()
        if not customer:
            customer = Customer(name=name, phone=phone, current_balance=0)
            self.session.add(customer)
            self.session.flush()
        customer.current_balance = (customer.current_balance or 0) + amount
        self.session.commit()
        self.name_input.clear()
        self.phone_input.clear()
        self.amount_input.setText("")
        self.refresh()

    def record_payment(self, customer_id):
        customer = self.session.query(Customer).get(customer_id)
        amount, ok = QInputDialog.getDouble(
            self, f"تسديد دين {customer.name}",
            f"الرصيد الحالي: {fmt_money(customer.current_balance)}\nأدخل مبلغ التسديد:",
            0, 0, 100_000_000, 0,
        )
        if not ok or amount <= 0:
            return
        customer.current_balance = max((customer.current_balance or 0) - amount, 0)
        self.session.commit()
        QMessageBox.information(self, "تم", f"تم تسجيل تسديد {fmt_money(amount)} لحساب {customer.name}.")
        self.refresh()
