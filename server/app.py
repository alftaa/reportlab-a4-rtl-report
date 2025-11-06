
from __future__ import annotations
import io, os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Form
from fastapi.responses import Response, RedirectResponse
from fastapi.staticfiles import StaticFiles

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import arabic_reshaper
from bidi.algorithm import get_display

# --- مسارات المشروع ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))        # server/
ROOT_DIR = os.path.dirname(BASE_DIR)                         # project root
STATIC_DIR = os.path.join(ROOT_DIR, "static")
FONTS_DIR = os.path.join(BASE_DIR, "fonts")

# --- الخطوط ---
FONT_REGULAR_PATH = os.path.join(FONTS_DIR, "Tajawal-Medium.ttf")
FONT_BOLD_PATH    = os.path.join(FONTS_DIR, "Tajawal-Bold.ttf")  # إن لم يوجد سيُستخدم Regular

# --- FastAPI & Static ---
app = FastAPI(title="ReportLab A4 RTL PDF Generator — Sun–Tue")
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# ---------------- RTL helpers ---------------- #
try:
    reshaper = arabic_reshaper.ArabicReshaper(
        arabic_reshaper.config_for_true_type_font(FONT_REGULAR_PATH)
    )
except Exception:
    # إن لم يتوفّر ملف الخط عند بدء التشغيل
    reshaper = arabic_reshaper.ArabicReshaper({})

def rtl(text: str) -> str:
    if text is None:
        return ""
    return get_display(reshaper.reshape(str(text)))


def ensure_fonts(regular_path: str, bold_path: Optional[str]) -> tuple[str, str]:
    if not os.path.exists(regular_path):
        raise FileNotFoundError(
            f"لم يتم العثور على الخط: {regular_path}. ضع ملفات TTF في server/fonts."
        )
    regular_name = "Arabic-Regular"
    pdfmetrics.registerFont(TTFont(regular_name, regular_path))

    bold_name = "Arabic-Bold"
    if bold_path and os.path.exists(bold_path):
        try:
            pdfmetrics.registerFont(TTFont(bold_name, bold_path))
        except Exception:
            bold_name = regular_name
    else:
        bold_name = regular_name
    return regular_name, bold_name

# ---------------- Header/Footer ---------------- #

def draw_header_footer(canvas, doc_obj, font_regular):
    page_w, page_h = A4
    margin = 15 * mm
    top = page_h - margin

    canvas.setFont(font_regular, 11)
    lines = [
        "وزارة التعليم",
        "الإدارة العامة للتعليم بمكة المكرمة",
        "مكتب تعليم العوالي",
        "ابتدائية أم منيع الأنصارية",
    ]
    y = top
    for ln in lines:
        canvas.drawRightString(page_w - margin, y, rtl(ln))
        y -= 13

    # تذييل ثابت
    canvas.setFont(font_regular, 12)
    footer_y = margin + 8 * mm
    canvas.drawRightString(page_w - margin, footer_y, rtl("مديرة المدرسة / ابتسام القرني"))

# ---------------- Dates: Sunday → Tuesday ---------------- #

def current_week_sun_mon_tue():
    """يُعيد تاريخ الأحد/الإثنين/الثلاثاء للأسبوع الحالي (أقرب أحد ماضٍ أو اليوم نفسه)."""
    today = datetime.now()
    # weekday(): الإثنين=0 .. الأحد=6  → نريد الأحد = 6
    diff_to_sun = (today.weekday() - 6) % 7
    sun = today - timedelta(days=diff_to_sun)
    mon = sun + timedelta(days=1)
    tue = sun + timedelta(days=2)
    fmt = lambda d: d.strftime("%Y/%m/%d")
    return fmt(sun), fmt(mon), fmt(tue)

# ---------------- PDF builder ---------------- #

def _fields_row(font_name: str, admin_name: str, period: str, week: str, term: str):
    """صف حقول المعلومات الأساسية: اسم الإدارية (ثابت) + الحصة/الأسبوع/الفصل (من المدخلات)
    نرتّب الأعمدة لتظهر من اليمين لليسار بصرياً (اسم الإدارية في أقصى اليمين)."""
    # رتب العناوين والقيم لتظهر RTL: [يسار ← يمين]
    headers = [rtl("الفصل الدراسي"), rtl("الأسبوع"), rtl("الحصة"), rtl("اسم الإدارية")]
    values  = [rtl(term or ""), rtl(week or ""), rtl(period or ""), rtl(admin_name)]
    widths = [38*mm, 30*mm, 28*mm, 64*mm]

    t = Table([headers, values], colWidths=widths, hAlign="RIGHT")
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), font_name),
        ("FONTSIZE", (0,0), (-1,-1), 11),
        ("GRID", (0,0), (-1,-1), 1, colors.black),
        ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN", (0,0), (-1,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
    ]))
    return t


def _date_row(font_name: str, date_str: str):
    # لكي يكون "التاريخ" على يمين الجدول بصرياً: [يسار القيمة | يمين العنوان]
    t = Table([[rtl(date_str), rtl("التاريخ")]], colWidths=[40*mm, 20*mm], hAlign="RIGHT")
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), font_name),
        ("FONTSIZE", (0,0), (-1,-1), 11),
        ("GRID", (0,0), (-1,-1), 1, colors.black),
        ("BACKGROUND", (1,0), (1,0), colors.whitesmoke),  # خلية العنوان
        ("ALIGN", (0,0), (-1,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
    ]))
    return t


def _visit_table(font_name: str, day_label: str, klass: str, follow: str, note: str):
    """جدول: اليوم | الفصل | متابعة الجولة | ملاحظات
    نمرّر البيانات معكوسة الأعمدة ليظهر بصرياً RTL (اليوم أقصى اليمين)."""
    # ترتيب الأعمدة في data هو من اليسار لليمين بصرياً، لذا نضعها بالعكس
    head = [rtl("ملاحظات"), rtl("متابعة الجولة"), rtl("الفصل"), rtl("اليوم")]
    row  = [rtl(note or ""), rtl(follow or ""), rtl(klass or ""), rtl(day_label)]
    widths = [60*mm, 60*mm, 25*mm, 25*mm]
    t = Table([head, row], colWidths=widths, hAlign="RIGHT")
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), font_name),
        ("FONTSIZE", (0,0), (-1,-1), 11),
        ("GRID", (0,0), (-1,-1), 1, colors.black),
        ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN", (0,0), (-1,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("LEADING", (0,1), (-1,-1), 14),
    ]))
    return t


def build_pdf_report(period: str, week: str, term: str,
                     sun_class: str, sun_follow: str, sun_note: str,
                     mon_class: str, mon_follow: str, mon_note: str,
                     tue_class: str, tue_follow: str, tue_note: str) -> bytes:

    font_regular, font_bold = ensure_fonts(FONT_REGULAR_PATH, FONT_BOLD_PATH)

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "H1", parent=styles["Heading1"], fontName=font_bold,
        alignment=TA_CENTER, fontSize=16, leading=22, spaceAfter=8
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=55*mm, bottomMargin=25*mm
    )

    story = []
    # العنوان المطابق
    story.append(Paragraph(rtl("تقرير الجولات الإدارية عبر منصة مدرستي"), h1))
    story.append(Spacer(1, 4*mm))

    # صف الحقول (اسم الإدارية ثابت)
    admin_name = "ابتسام قاسم الفيفي"
    story.append(_fields_row(font_regular, admin_name, period, week, term))
    story.append(Spacer(1, 6*mm))

    # تواريخ الأسبوع الحالي (الأحد → الثلاثاء)
    sun_d, mon_d, tue_d = current_week_sun_mon_tue()

    # الكتلة 1: الأحد
    story.append(_date_row(font_regular, sun_d))
    story.append(Spacer(1, 4*mm))
    story.append(_visit_table(font_regular, "الأحد", sun_class, sun_follow, sun_note))
    story.append(Spacer(1, 8*mm))

    # الكتلة 2: الإثنين
    story.append(_date_row(font_regular, mon_d))
    story.append(Spacer(1, 4*mm))
    story.append(_visit_table(font_regular, "الإثنين", mon_class, mon_follow, mon_note))
    story.append(Spacer(1, 8*mm))

    # الكتلة 3: الثلاثاء
    story.append(_date_row(font_regular, tue_d))
    story.append(Spacer(1, 4*mm))
    story.append(_visit_table(font_regular, "الثلاثاء", tue_class, tue_follow, tue_note))
    story.append(Spacer(1, 10*mm))

    def on_page(canvas, doc_obj):
        draw_header_footer(canvas, doc_obj, font_regular)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes

# ---------------- Routes ---------------- #

@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@app.post("/api/pdf")
async def generate_pdf(
    period: str = Form(""),
    week: str   = Form(""),
    term: str   = Form(""),
    # Sunday inputs
    sun_class: str  = Form("") , sun_follow: str = Form(""), sun_note: str = Form(""),
    # Monday inputs
    mon_class: str  = Form("") , mon_follow: str = Form(""), mon_note: str = Form(""),
    # Tuesday inputs
    tue_class: str  = Form("") , tue_follow: str = Form(""), tue_note: str = Form("")
):
    pdf_bytes = build_pdf_report(
        period, week, term,
        sun_class, sun_follow, sun_note,
        mon_class, mon_follow, mon_note,
        tue_class, tue_follow, tue_note,
    )
    from urllib.parse import quote
    filename = quote(f"تقرير_الجولات_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
