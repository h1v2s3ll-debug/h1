"""ألوان وستايل موحّد للتطبيق - H1 Design System v1 (أخضر أساسي #16A34A).

تحديث (H1 Design System v1): استبدال الباليت بالكامل بالألوان الرسمية
الجديدة المعتمدة (انظر التعليقات جنب كل قيمة). أسماء المتغيرات ما تغيّرت
عشان كل الملفات اللي تستورد منها تستمر تشتغل بدون أي تعديل إضافي - بس
القيم (الهيكس) تغيّرت لتطابق النظام الجديد. ما فيه أي تغيير بمنطق العرض
أو الحسابات هنا، بس ألوان."""

# --- التدرج الأخضر الأساسي (Primary: #16A34A / Primary Hover: #15803D /
# Primary Light: #DCFCE7) - بقية الدرجات امتداد طبيعي لنفس السلم اللوني
# حتى تبقى التبايُنات (تدرّجات، حالات hover/pressed) متناسقة كما كانت. ---
TEAL_900 = "#14532D"
TEAL_800 = "#166534"
TEAL_700 = "#15803D"   # Primary Hover
TEAL_600 = "#16A34A"   # Primary
TEAL_500 = "#16A34A"   # Primary (اللون الأساسي بمعظم الاستخدامات بالتطبيق)
TEAL_400 = "#22C55E"   # درجة أفتح للتدرجات/البريق (تطابق لون Success بالحالات)
TEAL_100 = "#DCFCE7"   # Primary Light
TEAL_50 = "#F0FDF4"
RED_500 = "#DC2626"    # Error
RED_100 = "#FEE2E2"
AMBER_500 = "#F59E0B"  # Warning
BG = "#F8FAFC"          # Main Background
PANEL = "#FFFFFF"       # Surface
PANEL_2 = "#F1F5F9"     # Secondary Surface
INK = "#111827"         # Primary Text
INK_2 = "#6B7280"       # Secondary Text
LINE = "#E5E7EB"        # Default Border

# --- ألوان ثانوية جديدة من النظام (زرقاء للعناصر المعلوماتية) ---
BLUE_600 = "#2563EB"    # Secondary
BLUE_100 = "#DBEAFE"    # Secondary Light
ACCENT_TEAL = "#0EA5A4"  # Accent
EMERALD_600 = "#059669"  # درجة زمردية مميزة لبطاقات "الربح" تحديدًا عن باقي البطاقات الخضراء


# ============================================================
# H1 Design System — رموز إضافية (Phase 1 / Task 1: Dashboard)
# لا تُغيّر أي قيمة موجودة أعلاه - هذي أسماء دلالية ومقاسات موحّدة تُستخدم
# بالشاشات اللي يُعاد تصميمها (تبدأ بالداشبورد)، حتى ما تتكرر القيم حرفيًا
# بكل ملف. الشاشات القديمة اللي لسه ما انتقلت لهذا النظام تستمر تشتغل بدون
# أي تغيير لأن ولا سطر قديم انحذف أو تغيّر.
# ============================================================

# --- ألوان دلالية (تشير لنفس قيم الباليت أعلاه بأسماء حسب الغرض) ---
COLOR_PRIMARY = TEAL_500
COLOR_PRIMARY_HOVER = TEAL_400
COLOR_SUCCESS_TEXT = TEAL_800
COLOR_SUCCESS_BG = TEAL_50
COLOR_WARNING_BG = "#FFFBEB"
COLOR_WARNING_BORDER = "#FDE68A"
COLOR_WARNING_TEXT = "#92400E"
COLOR_DANGER_BG = "#FEF2F2"
COLOR_DANGER_BORDER = "#FECACA"
COLOR_DANGER_TEXT = "#991B1B"
COLOR_SURFACE = PANEL
COLOR_SURFACE_SUBTLE = PANEL_2
COLOR_TEXT_PRIMARY = INK
COLOR_TEXT_SECONDARY = INK_2
COLOR_BORDER = LINE

# --- مقاسات الخط: (px, وزن) ---
FONT_H1 = (22, 800)
FONT_H2 = (18, 800)
FONT_H3 = (16, 700)
FONT_BODY = (14, 600)
FONT_BODY_STRONG = (14, 800)
FONT_CAPTION = (12, 600)
FONT_LABEL = (11, 700)

# --- تباعد موحّد (بكسل) ---
SPACE_4 = 4
SPACE_8 = 8
SPACE_12 = 12
SPACE_16 = 16
SPACE_20 = 20
SPACE_24 = 24
SPACE_32 = 32

# --- انحناء الحواف الموحّد (H1 Design System: Cards 12px / Buttons 10px / Inputs 10px) ---
RADIUS_BUTTON = 10
RADIUS_CARD = 12
RADIUS_PILL = 999
RADIUS_INPUT = 10

# --- إعدادات ظل موحّدة (تُمرَّر لنفس دالة add_shadow الحالية بـ widgets.py) ---
SHADOW_SMALL = dict(blur=12, alpha=16, y_offset=2)
SHADOW_MEDIUM = dict(blur=16, alpha=20, y_offset=3)
SHADOW_LARGE = dict(blur=24, alpha=25, y_offset=6)

# --- عائلة الخط الافتراضية (H1 Visual Foundation Upgrade) ---
# Cairo هو الخط المرفق فعليًا بـ assets/fonts/ ويُحمَّل تلقائيًا عند الإقلاع؛
# البقية احتياط لو الخط المرفق ما انحمّل لأي سبب.
FONT_FAMILY_FALLBACK = [
    "Cairo", "IBM Plex Sans Arabic", "Noto Sans Arabic",
    "Almarai", "Dubai", "Segoe UI", "Tahoma",
]


def _font_family_css(bundled_family=None):
    families = list(FONT_FAMILY_FALLBACK)
    if bundled_family and bundled_family not in families:
        families.insert(0, bundled_family)
    return ", ".join(f"'{f}'" for f in families)


STYLESHEET = f"""
QWidget {{
    font-family: {_font_family_css()};
    font-size: 15px;
    font-weight: 700;
    color: {INK};
    background-color: {BG};
}}

QFrame#TopBar {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {TEAL_900},stop:1 {TEAL_700});
}}
QLabel#BrandLabel {{
    color: white;
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 0.4px;
}}
QPushButton#NavButton {{
    color: {TEAL_100};
    background: transparent;
    border: none;
    padding: 10px 14px;
    border-radius: 10px;
    font-weight: 700;
}}
QPushButton#NavButton:hover {{
    background-color: rgba(255,255,255,0.10);
}}
QPushButton#NavButton:checked {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_600});
    font-weight: 800;
    color: white;
}}

QFrame.Card {{
    background-color: {PANEL};
    border: 1px solid {LINE};
    border-radius: 16px;
}}
QFrame.Card:hover {{
    border: 1px solid {TEAL_100};
}}

QPushButton {{
    background-color: {PANEL_2};
    color: {INK};
    border: 1px solid {LINE};
    border-radius: 10px;
    padding: 8px 14px;
    font-weight: 700;
}}
QPushButton:hover {{
    background-color: {TEAL_50};
    border: 1px solid {TEAL_100};
}}
QPushButton:pressed {{
    background-color: {TEAL_100};
}}
QPushButton:disabled {{
    background-color: {PANEL_2};
    color: {INK_2};
    border: 1px solid {LINE};
}}

QPushButton#PayButton {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});
    color: white;
    font-size: 16px;
    font-weight: 800;
    border-radius: 12px;
    padding: 13px;
    border: none;
}}
QPushButton#PayButton:hover {{ background-color: {TEAL_500}; }}
QPushButton#PayButton:pressed {{ background-color: {TEAL_600}; }}

QPushButton#AddButton {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {TEAL_400},stop:1 {TEAL_700});
    color: white;
    border-radius: 10px;
    padding: 7px 12px;
    font-weight: 800;
    border: none;
}}
QPushButton#AddButton:hover {{ background-color: {TEAL_500}; }}
QPushButton#AddButton:pressed {{ background-color: {TEAL_600}; }}

QPushButton#ClearButton {{
    background-color: {RED_500};
    color: white;
    border-radius: 10px;
    padding: 7px 13px;
    font-weight: 800;
    border: none;
}}
QPushButton#ClearButton:hover {{ background-color: #B91C1C; }}
QPushButton#ClearButton:pressed {{ background-color: #991B1B; }}

QPushButton#OutlineButton {{
    background: transparent;
    color: {TEAL_600};
    border: 1.5px solid {TEAL_500};
    border-radius: 10px;
    padding: 7px 12px;
    font-weight: 800;
}}
QPushButton#OutlineButton:hover {{ background-color: {TEAL_50}; }}
QPushButton#OutlineButton:pressed {{ background-color: {TEAL_100}; }}

QLabel.Badge {{
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 800;
}}
QLabel.BadgeLow {{ background-color: {RED_100}; color: #991B1B; }}
QLabel.BadgeOk {{ background-color: {TEAL_100}; color: {TEAL_800}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    border: 1.5px solid {LINE};
    border-radius: 12px;
    padding: 9px 13px;
    background-color: {PANEL};
    font-weight: 700;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border: 1.5px solid {TEAL_100};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {TEAL_400};
}}
QLineEdit:disabled, QComboBox:disabled {{
    background-color: {PANEL_2};
    color: {INK_2};
    border: 1.5px solid {LINE};
}}

QTableWidget {{
    background-color: {PANEL};
    border: 1px solid {LINE};
    border-radius: 14px;
    gridline-color: {LINE};
    selection-background-color: {TEAL_100};
    selection-color: {TEAL_900};
    alternate-background-color: {PANEL_2};
}}
QHeaderView::section {{
    background-color: {PANEL_2};
    color: {TEAL_800};
    font-weight: 800;
    padding: 9px;
    border: none;
    border-bottom: 1.5px solid {LINE};
}}
QTableWidget::item {{
    padding: 7px;
}}
QTableWidget::item:hover {{
    background-color: {TEAL_50};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #94A3B8;
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEAL_600}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def stylesheet_for(bundled_family=None):
    """يرجّع نفس STYLESHEET، بس بعائلة خط مضافة بالأولوية الأولى لو انحمّل
    خط Cairo فعليًا من assets/fonts/ عند الإقلاع (H1 Visual Foundation
    Upgrade). لو ماكو خط محمّل لأي سبب، يرجّع STYLESHEET العادي بدون تغيير."""
    if not bundled_family:
        return STYLESHEET
    return STYLESHEET.replace(_font_family_css(), _font_family_css(bundled_family), 1)
