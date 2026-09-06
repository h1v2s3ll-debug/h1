"""شاشة النسخ الاحتياطي: اختيار مجلد الحفظ، نسخ تلقائية دورية أثناء الشغل +
عند إغلاق البرنامج (أرشيف متعدد النسخ، مو نسخة وحدة تنمحى)، واستعادة أي
نسخة قديمة يدويًا. + قسم تحديثات البرنامج (فحص + تحديث جزئي/كامل)."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QFileDialog, QMessageBox, QCheckBox, QDialog, QProgressDialog,
    QApplication
)
from PySide6.QtCore import Qt, QUrl, QThread, Signal
from PySide6.QtGui import QDesktopServices

from app.ui.widgets import add_shadow
from app.ui.icons import icon, pixmap
from app.ui.theme import PANEL, LINE, INK, INK_2, TEAL_600, TEAL_800, RED_500
from app.db.database import get_session
from app.db import backup_helper
from app.update_checker import check_for_update
from app.version import APP_VERSION
from app import partial_updater


class _PartialUpdateDownloadWorker(QThread):
    """يحمّل ملفات التحديث الجزئي بخيط منفصل حتى ما تعلّق الواجهة أثناء
    التحميل - نفس أسلوب worker استيراد الإكسل الموجود بـ inventory_view.py
    بالضبط (QThread + إشارات progress/finished_ok/finished_error)."""
    progress = Signal(int, int, str)
    finished_ok = Signal(str)
    finished_error = Signal(str)

    def __init__(self, manifest, to_download):
        super().__init__()
        self.manifest = manifest
        self.to_download = to_download

    def run(self):
        try:
            staging_dir = partial_updater.download_update_files(
                self.manifest, self.to_download,
                progress_callback=lambda done, total, path: self.progress.emit(done, total, path),
            )
            self.finished_ok.emit(staging_dir)
        except partial_updater.UpdateDownloadError as e:
            self.finished_error.emit(str(e))
        except Exception as e:
            self.finished_error.emit(str(e))


class BackupView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = get_session()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        title_wrap = QFrame()
        title_wrap.setStyleSheet("background:transparent;border:none;")
        title_row = QHBoxLayout(title_wrap)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_icon_lbl = QLabel()
        title_icon_lbl.setStyleSheet("background:transparent;border:none;")
        title_icon_lbl.setPixmap(pixmap("database", color=INK, size=18))
        title_row.addWidget(title_icon_lbl)
        title = QLabel("النسخ الاحتياطي")
        title.setStyleSheet("font-size:18px;font-weight:bold;background:transparent;border:none;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addWidget(title_wrap)

        subtitle = QLabel("نسخة احتياطية تلقائية كل 30 دقيقة أثناء الشغل + عند إغلاق البرنامج - يحتفظ بآخر 10 نسخ (مو نسخة وحدة تنمحى وتنكتب فوقها).")
        subtitle.setStyleSheet(f"color:{INK_2};font-size:12px;margin-bottom:10px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setStyleSheet(f"background:{PANEL};border:1px solid {LINE};border-radius:14px;padding:18px;")
        add_shadow(card, blur=16, color="#16A34A", alpha=18, y_offset=3)
        card_layout = QVBoxLayout(card)

        folder_row = QHBoxLayout()
        folder_label_box = QVBoxLayout()
        folder_caption = QLabel("مجلد الحفظ:")
        folder_caption.setStyleSheet(f"color:{INK_2};font-size:12px;")
        self.folder_value = QLabel("")
        self.folder_value.setStyleSheet(f"color:{INK};font-weight:bold;font-size:14px;")
        self.folder_value.setWordWrap(True)
        folder_label_box.addWidget(folder_caption)
        folder_label_box.addWidget(self.folder_value)
        folder_row.addLayout(folder_label_box, stretch=1)

        choose_btn = QPushButton("اختيار مجلد الحفظ")
        choose_btn.setIcon(icon("folder", color="white", size=15))
        choose_btn.setStyleSheet(f"background:{TEAL_600};color:white;border-radius:8px;padding:10px 16px;")
        choose_btn.clicked.connect(self.choose_folder)
        folder_row.addWidget(choose_btn)
        card_layout.addLayout(folder_row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{LINE};margin:14px 0;")
        card_layout.addWidget(line)

        last_row = QHBoxLayout()
        last_caption = QLabel("آخر نسخة محفوظة:")
        last_caption.setStyleSheet(f"color:{INK_2};font-size:12px;")
        self.last_backup_value = QLabel("")
        self.last_backup_value.setStyleSheet(f"color:{TEAL_800};font-weight:bold;")
        last_row.addWidget(last_caption)
        last_row.addWidget(self.last_backup_value)
        last_row.addStretch()
        card_layout.addLayout(last_row)

        toggle_row = QHBoxLayout()
        self.auto_backup_check = QCheckBox("تفعيل النسخ الاحتياطي التلقائي كل 30 دقيقة")
        self.auto_backup_check.toggled.connect(self._on_auto_toggle)
        toggle_row.addWidget(self.auto_backup_check)
        toggle_row.addStretch()
        card_layout.addLayout(toggle_row)

        btn_row = QHBoxLayout()
        backup_now_btn = QPushButton("خذ نسخة الآن")
        backup_now_btn.setIcon(icon("save", color="white", size=15))
        backup_now_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:10px 16px;")
        backup_now_btn.clicked.connect(self.backup_now)
        btn_row.addWidget(backup_now_btn)

        # ---- إصلاح مهم: ماكو أي قائمة نسخ ظاهرة بأزرار استعادة جنب كل
        # وحدة - كان هذا خطر حقيقي (موظف يضغط "استعادة" بالغلط على نسخة
        # قديمة يخرب المخزون والدخل الحالي بدون قصد). الحين الاستعادة بس
        # عن طريق زر واحد يفتح نافذة اختيار ملف من نظام التشغيل نفسها -
        # لازم المستخدم يدور بنفسه ويختار الملف بوعي، ما فيه ولا احتمال
        # ضغطة غلط عرضية.
        restore_btn = QPushButton("استعادة من ملف")
        restore_btn.setIcon(icon("recycle", color=RED_500, size=15))
        restore_btn.setStyleSheet(f"background:white;border:1px solid {RED_500};color:{RED_500};border-radius:8px;padding:10px 16px;")
        restore_btn.clicked.connect(self.restore_from_file)
        btn_row.addWidget(restore_btn)

        btn_row.addStretch()
        card_layout.addLayout(btn_row)

        layout.addWidget(card)

        # ---- قسم منفصل: تحديثات البرنامج (فحص يدوي بس، ماكو فحص تلقائي) ----
        update_card = QFrame()
        update_card.setStyleSheet(f"background:{PANEL};border:1px solid {LINE};border-radius:14px;padding:18px;margin-top:14px;")
        add_shadow(update_card, blur=16, color="#0E8F6E", alpha=18, y_offset=3)
        update_card_layout = QVBoxLayout(update_card)

        update_title_row = QHBoxLayout()
        update_title = QLabel("تحديثات البرنامج")
        update_title.setStyleSheet("font-size:15px;font-weight:bold;")
        update_title_row.addWidget(update_title)
        update_title_row.addStretch()
        version_lbl = QLabel(f"نسختك الحالية: {APP_VERSION}")
        version_lbl.setStyleSheet(f"color:{INK_2};font-size:12px;")
        update_title_row.addWidget(version_lbl)
        update_card_layout.addLayout(update_title_row)

        check_update_btn = QPushButton("التأكد من وجود تحديثات")
        check_update_btn.setIcon(icon("refresh", color="white", size=15))
        check_update_btn.setStyleSheet(f"background:{TEAL_600};color:white;border-radius:8px;padding:10px 16px;")
        check_update_btn.clicked.connect(self.check_for_updates)
        update_card_layout.addWidget(check_update_btn)

        layout.addWidget(update_card)

        self.refresh()

    def check_for_updates(self):
        status, info = check_for_update()
        if status == "error":
            QMessageBox.warning(self, "تنبيه", "تعذّر التحقق من وجود تحديثات - تأكد من الاتصال بالإنترنت وحاول مرة ثانية.")
        elif status == "up_to_date":
            QMessageBox.information(self, "محدّث", "✓ برنامجك محدّث لآخر نسخة.")
        elif status == "update_available":
            self._show_update_dialog(info)

    def _show_update_dialog(self, info):
        dlg = QDialog(self)
        dlg.setWindowTitle("تحديث جديد متوفر")
        dlg.setMinimumWidth(360)
        dlg_layout = QVBoxLayout(dlg)

        title = QLabel(f"🆕 فيه نسخة جديدة (النسخة {info['version']})")
        title.setStyleSheet("font-size:15px;font-weight:bold;margin-bottom:6px;")
        dlg_layout.addWidget(title)

        if info.get("notes"):
            notes_lbl = QLabel(info["notes"])
            notes_lbl.setWordWrap(True)
            notes_lbl.setStyleSheet(f"color:{INK_2};margin-bottom:10px;")
            dlg_layout.addWidget(notes_lbl)

        btn_row = QHBoxLayout()
        later_btn = QPushButton("التحديث لاحقًا")
        later_btn.setStyleSheet(f"background:white;border:1px solid {LINE};color:{INK};border-radius:8px;padding:10px 16px;")
        later_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(later_btn)

        def do_update():
            dlg.accept()
            self._start_partial_update_flow(info)

        update_now_btn = QPushButton("حدّث الآن")
        update_now_btn.setIcon(icon("download", color="white", size=15))
        update_now_btn.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #16A34A,stop:1 #15803D);color:white;border-radius:8px;padding:10px 16px;font-weight:bold;")
        update_now_btn.clicked.connect(do_update)
        btn_row.addWidget(update_now_btn)

        dlg_layout.addLayout(btn_row)
        dlg.exec()

    def _open_full_update_link(self, info):
        """التحديث الكامل التقليدي (فتح رابط تحميل المثبّت بالمتصفح) -
        نفس السلوك الأصلي بدون أي تغيير، يُستخدم كـfallback لما التحديث
        الجزئي مو ممكن أو فشل."""
        url = info.get("url", "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _start_partial_update_flow(self, info):
        """يحاول التحديث الجزئي أولًا (تحميل ملفات app/*.py المتغيّرة
        بس)، ويرجع تلقائيًا للتحديث الكامل (فتح رابط المتصفح) لو:
        - ماكو اتصال بمانفست التحديث الجزئي أصلًا، أو
        - نسختنا الحالية قديمة جدًا (is_partial_update_possible == False)، أو
        - رقم نسخة المانفست ما يطابق رقم النسخة اللي check_for_update()
          شافها (حماية بسيطة من عدم تطابق بين السيرفرين)."""
        manifest = partial_updater.fetch_manifest()
        if (
            not manifest
            or not partial_updater.is_partial_update_possible(manifest)
            or str(manifest.get("version")) != str(info.get("version"))
        ):
            self._open_full_update_link(info)
            return

        to_download, to_delete = partial_updater.compute_diff(manifest)
        if not to_download and not to_delete:
            QMessageBox.information(self, "محدّث", "برنامجك محدّث فعليًا لآخر نسخة.")
            return

        progress = QProgressDialog("جاري تحميل ملفات التحديث...", "إلغاء", 0, max(len(to_download), 1), self)
        progress.setWindowTitle("تحديث جاري")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        worker = _PartialUpdateDownloadWorker(manifest, to_download)
        self._update_worker = worker  # مرجع نحتفظ فيه حتى ما يُجمع (garbage collect) وهو شغّال
        worker.progress.connect(lambda done, total, name: progress.setValue(done))
        worker.finished_ok.connect(lambda staging_dir: self._on_partial_update_downloaded(progress, staging_dir, to_delete))
        worker.finished_error.connect(lambda msg: self._on_partial_update_failed(progress, msg, info))
        progress.canceled.connect(lambda: self._cancel_partial_update(worker))
        worker.start()

    def _cancel_partial_update(self, worker):
        worker.terminate()
        worker.wait(1000)
        partial_updater.discard_staged_update(partial_updater.staging_dir_path())

    def _on_partial_update_downloaded(self, progress, staging_dir, to_delete):
        progress.close()
        confirm = QMessageBox.question(
            self, "التحديث جاهز",
            "تم تحميل التحديث والتحقق من سلامته بنجاح.\n"
            "لازم يسكّر البرنامج الآن حتى يطبّق التحديث، وبعدها يفتح نفسه تلقائيًا من جديد.\n\n"
            "هل تريد المتابعة الآن؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if confirm != QMessageBox.Yes:
            # المستخدم أجّل - نحذف الـstaging حتى ما يضل ملفات معلّقة على
            # القرص للأبد (يقدر يضغط "حدّث الآن" من جديد لاحقًا بيوم ثاني).
            partial_updater.discard_staged_update(staging_dir)
            return
        partial_updater.apply_update_and_relaunch(staging_dir, to_delete)
        QApplication.quit()

    def _on_partial_update_failed(self, progress, message, info):
        progress.close()
        QMessageBox.warning(
            self, "تعذّر التحديث الجزئي",
            f"صار خطأ أثناء تحميل التحديث:\n{message}\n\n"
            "راح نفتح رابط تحميل النسخة الكاملة بدالها."
        )
        self._open_full_update_link(info)

    def _on_auto_toggle(self, checked):
        backup_helper.set_auto_backup_enabled(self.session, checked)

    def refresh(self):
        folder = backup_helper.get_backup_folder(self.session)
        self.folder_value.setText(folder if folder else "ماكو مجلد محدد بعد - اختار وحدة حتى تشتغل النسخة التلقائية")
        last = backup_helper.get_last_backup_at(self.session)
        self.last_backup_value.setText(last if last else "لا توجد نسخة بعد")
        self.auto_backup_check.blockSignals(True)
        self.auto_backup_check.setChecked(backup_helper.is_auto_backup_enabled(self.session))
        self.auto_backup_check.blockSignals(False)

    def restore_from_file(self):
        # نبدأ البحث من مجلد النسخ الاحتياطي المحدد (إذا موجود) عشان
        # يسهّل على المستخدم يوصله بسرعة، بدون ما نعرض له أي قائمة جاهزة.
        start_dir = backup_helper.get_backup_folder(self.session) or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "اختار ملف النسخة الاحتياطية اللي تريد تستعيدها",
            start_dir, "ملفات النسخ الاحتياطي (*.db)"
        )
        if not path:
            return
        self.restore_specific(path)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "اختار مجلد حفظ النسخة الاحتياطية")
        if not folder:
            return
        backup_helper.set_backup_folder(self.session, folder)
        self.refresh()
        QMessageBox.information(self, "تم", "تم تحديد مجلد النسخ الاحتياطي بنجاح.")

    def backup_now(self):
        ok, result = backup_helper.perform_backup(self.session)
        if ok:
            self.refresh()
            QMessageBox.information(self, "تم", "تم حفظ نسخة احتياطية بنجاح.")
        else:
            QMessageBox.warning(self, "تنبيه", result)

    def restore_specific(self, backup_path):
        confirm = QMessageBox.warning(
            self, "تأكيد الاستعادة",
            f"متأكد تريد تستعيد النسخة: {backup_helper.backup_display_name(backup_path)}؟\n\n"
            "هذا الإجراء راح يستبدل كل بياناتك الحالية بهذي النسخة ولا يمكن التراجع عنه.\n"
            "لازم تسكر البرنامج وتفتحه من جديد بعد الاستعادة حتى تنطبق التغييرات.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        ok, err = backup_helper.restore_backup(self.session, backup_path)
        if ok:
            QMessageBox.information(
                self, "تمت الاستعادة",
                "تم استرجاع بياناتك بنجاح.\nسكر البرنامج الآن وافتحه من جديد حتى تشوف البيانات المستعادة."
            )
        else:
            QMessageBox.warning(self, "تنبيه", err)
            self.session = get_session()
