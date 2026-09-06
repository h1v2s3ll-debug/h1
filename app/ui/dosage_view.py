"""
شاشة حاسبة الجرعة الدوائية.
حسب اتفاقنا: حقلي العمر والوزن اختياريين تمامًا - الحساب يشتغل بأي حالة،
بس دقة النتيجة تعتمد على شكد معلومات متوفرة.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFrame, QCheckBox, QDialog, QFormLayout, QLineEdit, QMessageBox,
    QScrollArea
)
from PySide6.QtCore import Qt

from app.db.database import get_session
from app.db.models import Product, DosageGuideline, DrugInteraction
from app.ui.widgets import NumberLineEdit, enable_touch_scroll
from app.ui.icons import icon


class AddDosageDialog(QDialog):
    """إضافة دواء جديد للحاسبة أو تعيين جرعة لدواء موجود أصلاً."""
    def __init__(self, all_products, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة دواء وجرعته")
        self.setMinimumWidth(380)
        layout = QFormLayout(self)

        self.product_combo = QComboBox()
        self.product_combo.setEditable(True)
        self.product_combo.addItem("— دواء جديد بالاسم المكتوب —", None)
        for p in all_products:
            self.product_combo.addItem(p.name, p.id)

        self.dose_per_kg_input = NumberLineEdit(decimals=2)
        self.max_daily_input = NumberLineEdit(decimals=2)
        self.unit_input = QLineEdit("mg")
        self.min_age_input = NumberLineEdit(decimals=1)
        self.max_age_input = NumberLineEdit(decimals=1)
        self.min_weight_input = NumberLineEdit(decimals=1)
        self.max_weight_input = NumberLineEdit(decimals=1)
        self.standard_note_input = QLineEdit()
        self.standard_note_input.setPlaceholderText("تظهر لو ما توفر عمر/وزن، مثلاً: قرص كل 8 ساعات")
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("تحذيرات إضافية (اختياري)")

        layout.addRow("الدواء (اختر أو اكتب اسم جديد):", self.product_combo)
        layout.addRow("الجرعة لكل كيلوغرام:", self.dose_per_kg_input)
        layout.addRow("أقصى جرعة يومية:", self.max_daily_input)
        layout.addRow("الوحدة:", self.unit_input)
        layout.addRow("أقل عمر (سنة):", self.min_age_input)
        layout.addRow("أعلى عمر (سنة):", self.max_age_input)
        layout.addRow("أقل وزن (كغم):", self.min_weight_input)
        layout.addRow("أعلى وزن (كغم):", self.max_weight_input)
        layout.addRow("الجرعة القياسية (نص):", self.standard_note_input)
        layout.addRow("ملاحظات:", self.notes_input)

        save_btn = QPushButton("حفظ")
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px;")
        save_btn.clicked.connect(self.accept)
        layout.addRow(save_btn)

    def get_data(self):
        return {
            "product_id": self.product_combo.currentData(),
            "product_name": self.product_combo.currentText().strip(),
            "dose_per_kg": self.dose_per_kg_input.value(),
            "max_daily_dose": self.max_daily_input.value(),
            "unit": self.unit_input.text().strip() or "mg",
            "min_age": self.min_age_input.value() or None,
            "max_age": self.max_age_input.value() or None,
            "min_weight": self.min_weight_input.value() or None,
            "max_weight": self.max_weight_input.value() or None,
            "standard_dose_note": self.standard_note_input.text().strip(),
            "notes": self.notes_input.text().strip(),
        }


class AddDrugInteractionDialog(QDialog):
    """تسجيل تداخل دوائي بين علاجين - يُتحقق منه تلقائيًا وقت البيع لو
    الاثنين انضافوا بنفس الفاتورة (يظهر تحذير بشاشة البيع)."""
    def __init__(self, all_products, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إضافة تداخل دوائي")
        self.setMinimumWidth(420)
        layout = QFormLayout(self)

        self.drug_a_combo = QComboBox()
        self.drug_a_combo.setEditable(True)
        for p in all_products:
            self.drug_a_combo.addItem(p.name, p.id)
        self.drug_a_combo.setCurrentIndex(-1)
        self.drug_a_combo.lineEdit().clear()
        self.drug_a_combo.lineEdit().setPlaceholderText("اكتب اسم العلاج الأول...")
        self._make_searchable(self.drug_a_combo)

        self.drug_b_combo = QComboBox()
        self.drug_b_combo.setEditable(True)
        for p in all_products:
            self.drug_b_combo.addItem(p.name, p.id)
        self.drug_b_combo.setCurrentIndex(-1)
        self.drug_b_combo.lineEdit().clear()
        self.drug_b_combo.lineEdit().setPlaceholderText("اكتب اسم العلاج الثاني...")
        self._make_searchable(self.drug_b_combo)

        self.severity_combo = QComboBox()
        self.severity_combo.addItems(["خفيف", "متوسط", "خطير"])
        self.severity_combo.setCurrentText("متوسط")

        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("سبب التداخل، مثلاً: يزيد خطر النزيف عند الاستخدام المشترك")

        layout.addRow("العلاج الأول (ابحث بالاسم):", self.drug_a_combo)
        layout.addRow("العلاج الثاني (ابحث بالاسم):", self.drug_b_combo)
        layout.addRow("شدة التداخل:", self.severity_combo)
        layout.addRow("سبب التداخل:", self.reason_input)

        save_btn = QPushButton("حفظ")
        save_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:8px;")
        save_btn.clicked.connect(self._try_accept)
        layout.addRow(save_btn)

    def _make_searchable(self, combo):
        """يخلي الكومبو يفلتر بالبحث بأي جزء من اسم الدواء (مو بس أول حرف) -
        هذا اللي يحقق طلب "اختيار العلاج عن طريق البحث"."""
        completer = combo.completer()
        if completer:
            completer.setFilterMode(Qt.MatchContains)
            completer.setCaseSensitivity(Qt.CaseInsensitive)

    def _try_accept(self):
        drug_a_id = self.drug_a_combo.currentData()
        drug_b_id = self.drug_b_combo.currentData()
        if not drug_a_id or not drug_b_id:
            QMessageBox.warning(self, "تنبيه", "لازم تختار العلاج الأول والثاني من القائمة (بالبحث بالاسم).")
            return
        if drug_a_id == drug_b_id:
            QMessageBox.warning(self, "تنبيه", "لازم يكون العلاجين مختلفين عن بعض.")
            return
        if not self.reason_input.text().strip():
            QMessageBox.warning(self, "تنبيه", "لازم تكتب سبب التداخل.")
            return
        self.accept()

    def get_data(self):
        return {
            "product_id_a": self.drug_a_combo.currentData(),
            "product_id_b": self.drug_b_combo.currentData(),
            "severity": self.severity_combo.currentText(),
            "description": self.reason_input.text().strip(),
        }


class DosageView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = get_session()

        # ملاحظة إصلاح مهمة: الصفحة قبل كانت تحط كل محتواها مباشرة بدون أي
        # مساحة تمرير (QScrollArea) - كان مقبول لما المحتوى بس حاسبة الجرعة،
        # بس بعد ما ضفنا قسم التداخلات الدوائية زاد المحتوى الكلي عن المساحة
        # المرئية، فصارت كل العناصر تنعصر بمساحة أصغر من اللازم وتبين غير
        # واضحة. الحل: نحط كل شي جوا QScrollArea (نفس أسلوب باقي الصفحات
        # المشابهة بالبرنامج) عشان كل قسم ياخذ حجمه الطبيعي الكامل وتقدر
        # تتمرّر بالصفحة عادي لو المحتوى زاد عن الشاشة.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        enable_touch_scroll(scroll)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        page_content = QWidget()
        scroll.setWidget(page_content)
        layout = QVBoxLayout(page_content)

        title = QLabel("الجرعة والتداخلات")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        layout.addWidget(title)

        calc_title = QLabel("حاسبة الجرعة الدوائية")
        calc_title.setStyleSheet("font-size:15px;font-weight:700;color:#15803D;margin-top:4px;")
        layout.addWidget(calc_title)

        form = QFrame()
        form.setStyleSheet("background:white;border:1px solid #E5E7EB;border-radius:12px;padding:16px;")
        form_layout = QVBoxLayout(form)

        drug_row = QHBoxLayout()
        drug_row.addWidget(QLabel("الدواء:"))
        self.drug_combo = QComboBox()
        self._load_drugs()
        drug_row.addWidget(self.drug_combo, stretch=1)
        add_dosage_btn = QPushButton("+ إضافة دواء وجرعته")
        add_dosage_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 12px;")
        add_dosage_btn.clicked.connect(self.add_dosage)
        drug_row.addWidget(add_dosage_btn)
        form_layout.addLayout(drug_row)

        age_row = QHBoxLayout()
        self.age_check = QCheckBox("تحديد العمر")
        self.age_input = NumberLineEdit(decimals=1, placeholder="بالسنوات")
        self.age_input.setMaximumWidth(120)
        self.age_input.setEnabled(False)
        self.age_check.toggled.connect(self.age_input.setEnabled)
        age_row.addWidget(self.age_check)
        age_row.addWidget(self.age_input)
        form_layout.addLayout(age_row)

        weight_row = QHBoxLayout()
        self.weight_check = QCheckBox("تحديد الوزن")
        self.weight_input = NumberLineEdit(decimals=1, placeholder="بالكيلوغرام")
        self.weight_input.setMaximumWidth(120)
        self.weight_input.setEnabled(False)
        self.weight_check.toggled.connect(self.weight_input.setEnabled)
        weight_row.addWidget(self.weight_check)
        weight_row.addWidget(self.weight_input)
        form_layout.addLayout(weight_row)

        note = QLabel("ملاحظة: تقدر تتجاهل العمر والوزن تمامًا وتضغط احسب - راح تطلع جرعة عامة بدالها.")
        note.setStyleSheet("color:#6B7280;font-size:12px;")
        note.setWordWrap(True)
        form_layout.addWidget(note)

        calc_btn = QPushButton("احسب الجرعة")
        calc_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:10px;font-weight:bold;")
        calc_btn.clicked.connect(self.calculate)
        form_layout.addWidget(calc_btn)

        layout.addWidget(form)

        self.result_frame = QFrame()
        self.result_frame.setStyleSheet("background:#F0FDF4;border:1px dashed #22C55E;border-radius:10px;padding:16px;")
        self.result_layout = QVBoxLayout(self.result_frame)
        self.result_label = QLabel("النتيجة راح تظهر هنا بعد الحساب.")
        self.result_label.setWordWrap(True)
        self.result_layout.addWidget(self.result_label)
        layout.addWidget(self.result_frame)

        # ---- التداخلات الدوائية ----
        # تسجيل تداخل بين علاجين هنا يخلي شاشة البيع تحذّر تلقائيًا لو
        # الاثنين انضافوا بنفس الفاتورة (نفس آلية self._check_interactions
        # الموجودة أصلًا بشاشة البيع - هذا فقط يضيف واجهة لتسجيل التداخلات).
        interactions_title_row = QHBoxLayout()
        interactions_title = QLabel("التداخلات الدوائية")
        interactions_title.setStyleSheet("font-size:15px;font-weight:700;color:#15803D;margin-top:16px;")
        interactions_title_row.addWidget(interactions_title)
        interactions_title_row.addStretch()
        add_interaction_btn = QPushButton("+ إضافة تداخل دوائي")
        add_interaction_btn.setStyleSheet("background:#F1F5F9;border:1px solid #E5E7EB;border-radius:8px;padding:6px 12px;")
        add_interaction_btn.clicked.connect(self.add_interaction)
        interactions_title_row.addWidget(add_interaction_btn)
        layout.addLayout(interactions_title_row)

        interactions_note = QLabel("لما تسجّل تداخل هنا، شاشة البيع تحذّر تلقائيًا لو الكاشير أضاف العلاجين الاثنين بنفس الفاتورة.")
        interactions_note.setStyleSheet("color:#6B7280;font-size:12px;")
        interactions_note.setWordWrap(True)
        layout.addWidget(interactions_note)

        self.interactions_search = QLineEdit()
        self.interactions_search.setPlaceholderText("ابحث باسم دواء لعرض تداخلاته (اكتب حرفين على الأقل)...")
        self.interactions_search.setStyleSheet("padding:8px;border:1px solid #E5E7EB;border-radius:8px;margin-top:6px;")
        self.interactions_search.textChanged.connect(self._load_interactions)
        layout.addWidget(self.interactions_search)

        self.interactions_summary_label = QLabel("")
        self.interactions_summary_label.setStyleSheet("color:#6B7280;font-size:11px;margin-top:2px;")
        layout.addWidget(self.interactions_summary_label)

        self.interactions_list_layout = QVBoxLayout()
        self.interactions_list_layout.setSpacing(8)
        layout.addLayout(self.interactions_list_layout)
        self._load_interactions()

        layout.addStretch()

    def _load_drugs(self):
        self.drug_combo.clear()
        products = (
            self.session.query(Product)
            .join(DosageGuideline, DosageGuideline.product_id == Product.id)
            .all()
        )
        for p in products:
            self.drug_combo.addItem(p.name, p.id)
        if not products:
            self.drug_combo.addItem("لا يوجد أدوية إلها إرشادات جرعة مسجّلة بعد", None)

    def add_dosage(self):
        all_products = self.session.query(Product).order_by(Product.name).all()
        dialog = AddDosageDialog(all_products, self)
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.get_data()

        product_id = data["product_id"]
        if not product_id:
            name = data["product_name"]
            if not name or name.startswith("—"):
                QMessageBox.warning(self, "تنبيه", "لازم تختار دواء أو تكتب اسم دواء جديد.")
                return
            existing = self.session.query(Product).filter_by(name=name).first()
            if existing:
                product_id = existing.id
            else:
                new_product = Product(name=name, base_unit="شريط", is_custom=True)
                self.session.add(new_product)
                self.session.flush()
                product_id = new_product.id

        existing_guideline = self.session.query(DosageGuideline).filter_by(product_id=product_id).first()
        if existing_guideline:
            guideline = existing_guideline
        else:
            guideline = DosageGuideline(product_id=product_id)
            self.session.add(guideline)

        guideline.dose_per_kg = data["dose_per_kg"] or None
        guideline.max_daily_dose = data["max_daily_dose"] or None
        guideline.unit = data["unit"]
        guideline.min_age = data["min_age"]
        guideline.max_age = data["max_age"]
        guideline.min_weight = data["min_weight"]
        guideline.max_weight = data["max_weight"]
        guideline.standard_dose_note = data["standard_dose_note"]
        guideline.notes = data["notes"]
        self.session.commit()

        self._load_drugs()
        QMessageBox.information(self, "تم", "تم حفظ بيانات الجرعة بنجاح.")

    def calculate(self):
        product_id = self.drug_combo.currentData()
        if not product_id:
            self.result_label.setText("ما اخترت دواء إله إرشادات جرعة مسجّلة.")
            return

        guideline = self.session.query(DosageGuideline).filter_by(product_id=product_id).first()
        if not guideline:
            self.result_label.setText("ماكو إرشادات جرعة مسجّلة لهذا الدواء.")
            return

        has_age = self.age_check.isChecked()
        has_weight = self.weight_check.isChecked()
        age = self.age_input.value() if has_age else None
        weight = self.weight_input.value() if has_weight else None

        lines = []
        if has_weight and guideline.dose_per_kg:
            dose = weight * guideline.dose_per_kg
            if guideline.max_daily_dose:
                dose = min(dose, guideline.max_daily_dose)
            lines.append(f"✅ الجرعة المحسوبة حسب الوزن: {dose:.0f} {guideline.unit} للجرعة الواحدة")
            if not has_age:
                lines.append("⚠️ لم يُحدد العمر - النتيجة معتمدة على الوزن فقط.")
        elif has_age and not has_weight:
            lines.append(f"ℹ️ لم يُحدد الوزن - إليك الجرعة الاعتيادية لهذا العمر:")
            lines.append(guideline.standard_dose_note or "ماكو جرعة قياسية مسجّلة لهذا العمر.")
        else:
            lines.append("ℹ️ ماكو عمر أو وزن محدد - هذي الجرعة الاعتيادية العامة:")
            lines.append(guideline.standard_dose_note or "ماكو جرعة قياسية عامة مسجّلة لهذا الدواء.")

        if guideline.notes:
            lines.append(f"\n⚠️ ملاحظة: {guideline.notes}")

        self.result_label.setText("\n".join(lines))

    MAX_INTERACTION_ROWS = 150  # حد أقصى للصفوف المعروضة دفعة وحدة - حماية للواجهة من التجمد

    def _load_interactions(self, *_args):
        while self.interactions_list_layout.count():
            child = self.interactions_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        total_count = self.session.query(DrugInteraction).count()
        if total_count == 0:
            self.interactions_summary_label.setText("")
            empty_lbl = QLabel("ماكو تداخلات دوائية مسجّلة لحد الآن.")
            empty_lbl.setStyleSheet("color:#9CA3AF;font-size:12px;padding:8px 0;")
            self.interactions_list_layout.addWidget(empty_lbl)
            return

        search_text = (self.interactions_search.text() or "").strip().lower()

        # نجيب كل الأدوية دفعة وحدة بدل استعلام لكل صف (كان هذا سبب تجمد
        # الشاشة لما صار عدد التداخلات كبير) - ونبنيها بقاموس للوصول السريع.
        products_by_id = {p.id: p for p in self.session.query(Product).all()}

        if search_text and len(search_text) >= 2:
            # بحث: نفحص كل التداخلات (استعلام واحد فقط) ونصفّي بذاكرة
            # بايثون على أساس اسم الدواء - أسرع بكثير من استعلام لكل صف.
            candidates = self.session.query(DrugInteraction).all()
            matched = []
            for it in candidates:
                drug_a = products_by_id.get(it.product_id_a)
                drug_b = products_by_id.get(it.product_id_b)
                if not drug_a or not drug_b:
                    continue
                if search_text in drug_a.name.lower() or search_text in drug_b.name.lower():
                    matched.append((it, drug_a, drug_b))
            interactions_to_show = matched[: self.MAX_INTERACTION_ROWS]
            if not matched:
                self.interactions_summary_label.setText(f"ماكو نتائج مطابقة لـ«{search_text}» من أصل {total_count} تداخل مسجّل.")
                empty_lbl = QLabel("ماكو تداخلات مطابقة لبحثك.")
                empty_lbl.setStyleSheet("color:#9CA3AF;font-size:12px;padding:8px 0;")
                self.interactions_list_layout.addWidget(empty_lbl)
                return
            elif len(matched) > self.MAX_INTERACTION_ROWS:
                self.interactions_summary_label.setText(
                    f"عم نعرض أول {self.MAX_INTERACTION_ROWS} نتيجة من أصل {len(matched)} - دقّق أكثر بالبحث لتضييق النتائج."
                )
            else:
                self.interactions_summary_label.setText(f"{len(matched)} نتيجة مطابقة لـ«{search_text}».")
        else:
            # ماكو بحث: نعرض أول دفعة بس (مرتّبة حسب الأخطر أولاً) ونطلب
            # من المستخدم يبحث لو يريد يشوف أكثر - بدل ما نحمّل الشاشة
            # بآلاف الصفوف بمرة وحدة.
            severity_order = {"خطير": 0, "متوسط": 1, "خفيف": 2}
            page = (
                self.session.query(DrugInteraction)
                .limit(self.MAX_INTERACTION_ROWS * 3)  # هامش إضافي عشان نرتب بعدها ونقص الصفوف المحذوف دواءها
                .all()
            )
            rows = []
            for it in page:
                drug_a = products_by_id.get(it.product_id_a)
                drug_b = products_by_id.get(it.product_id_b)
                if not drug_a or not drug_b:
                    continue
                rows.append((it, drug_a, drug_b))
            rows.sort(key=lambda r: severity_order.get(r[0].severity, 9))
            interactions_to_show = rows[: self.MAX_INTERACTION_ROWS]

            if total_count > self.MAX_INTERACTION_ROWS:
                self.interactions_summary_label.setText(
                    f"عندك {total_count} تداخل مسجّل بالمجموع - عم نعرض أهم {len(interactions_to_show)} (الأخطر أولاً)."
                    " استخدم البحث فوق لتشوف تداخلات دواء معيّن."
                )
            else:
                self.interactions_summary_label.setText(f"{total_count} تداخل مسجّل بالمجموع.")

        severity_colors = {"خفيف": "#F59E0B", "متوسط": "#F59E0B", "خطير": "#DC2626"}
        for it, drug_a, drug_b in interactions_to_show:
            row = QFrame()
            row.setStyleSheet("background:#FFFFFF;border:1px solid #E5E7EB;border-radius:10px;padding:10px;")
            row_layout = QHBoxLayout(row)

            text_box = QVBoxLayout()
            title_lbl = QLabel(f"{drug_a.name}  ⚠️  {drug_b.name}")
            title_lbl.setStyleSheet("font-weight:700;font-size:13px;")
            text_box.addWidget(title_lbl)

            color = severity_colors.get(it.severity, "#F59E0B")
            detail_lbl = QLabel(f"الشدة: {it.severity} — {it.description or 'بدون سبب مكتوب'}")
            detail_lbl.setStyleSheet(f"color:{color};font-size:12px;")
            detail_lbl.setWordWrap(True)
            text_box.addWidget(detail_lbl)
            row_layout.addLayout(text_box, stretch=1)

            delete_btn = QPushButton()
            delete_btn.setIcon(icon("trash", color="#DC2626", size=14))
            delete_btn.setStyleSheet("background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;padding:6px 10px;")
            delete_btn.setToolTip("حذف هذا التداخل")
            delete_btn.clicked.connect(lambda _, iid=it.id: self.delete_interaction(iid))
            row_layout.addWidget(delete_btn)

            self.interactions_list_layout.addWidget(row)

    def add_interaction(self):
        all_products = self.session.query(Product).filter(Product.is_active == True).order_by(Product.name).all()
        if len(all_products) < 2:
            QMessageBox.warning(self, "تنبيه", "لازم يكون عندك على الأقل دوائين مسجّلين بالمخزون.")
            return
        dialog = AddDrugInteractionDialog(all_products, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.get_data()

        # نتأكد ما فيه نفس التداخل مسجّل مسبقًا (بأي اتجاه) قبل ما نكرره
        existing = self.session.query(DrugInteraction).filter(
            ((DrugInteraction.product_id_a == data["product_id_a"]) & (DrugInteraction.product_id_b == data["product_id_b"]))
            | ((DrugInteraction.product_id_a == data["product_id_b"]) & (DrugInteraction.product_id_b == data["product_id_a"]))
        ).first()
        if existing:
            QMessageBox.warning(self, "تنبيه", "هذا التداخل مسجّل مسبقًا بين نفس العلاجين.")
            return

        interaction = DrugInteraction(
            product_id_a=data["product_id_a"],
            product_id_b=data["product_id_b"],
            severity=data["severity"],
            description=data["description"],
        )
        self.session.add(interaction)
        self.session.commit()
        self._load_interactions()
        QMessageBox.information(self, "تم", "تم حفظ التداخل الدوائي بنجاح.")

    def delete_interaction(self, interaction_id):
        confirm = QMessageBox.question(
            self, "تأكيد الحذف", "متأكد تريد تحذف هذا التداخل الدوائي؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        interaction = self.session.query(DrugInteraction).get(interaction_id)
        if interaction:
            self.session.delete(interaction)
            self.session.commit()
        self._load_interactions()

    def refresh(self):
        self._load_drugs()
        self._load_interactions()
