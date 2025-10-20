# -*- coding: utf-8 -*-
from __future__ import annotations
import io, os, json
from datetime import datetime
from typing import List, Tuple, Optional

from fastapi import FastAPI, Form
from fastapi.responses import Response, RedirectResponse
from fastapi.staticfiles import StaticFiles

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib import colors

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.utils import ImageReader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))        # server/
ROOT_DIR = os.path.dirname(BASE_DIR)                          # project root
STATIC_DIR = os.path.join(ROOT_DIR, "static")
FONTS_DIR = os.path.join(BASE_DIR, "fonts")

# ثبّت هنا ملفات الخطوط (ضع .ttf في server/fonts)
FONT_REGULAR_PATH = os.path.join(FONTS_DIR, "Tajawal-Medium.ttf")
FONT_BOLD_PATH    = os.path.join(FONTS_DIR, "Tajawal-Bold.ttf")  # إن لم يوجد سيُستخدم Regular كبديل

# مسارات الصور الثابتة (ضعها في static/images)
CENTER_LOGO_PATH = os.path.join(STATIC_DIR, "images", "center_logo.png")
LEFT_LOGO_PATH   = os.path.join(STATIC_DIR, "images", "left_logo.png")

app = FastAPI(title="ReportLab A4 RTL PDF Generator")
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# ---------------- RTL helpers ---------------- #
# arabic_reshaper يتطلب مسار خط صحيح للإصدار الأحدث
try:
    reshaper = arabic_reshaper.ArabicReshaper(
        arabic_reshaper.config_for_true_type_font(FONT_REGULAR_PATH)
    )
except Exception:
    # احتياط: إن لم يتوفر الملف لأي سبب
    reshaper = arabic_reshaper.ArabicReshaper(
        arabic_reshaper.config_for_true_type_font(FONT_REGULAR_PATH)
    )

def rtl(text: str) -> str:
    if text is None:
        return ""
    return get_display(reshaper.reshape(str(text)))


def ensure_fonts(regular_path: str, bold_path: Optional[str]) -> tuple[str, str]:
    if not os.path.exists(regular_path):
        raise FileNotFoundError(
            f"لم يتم العثور على الخط: {regular_path}. ضع ملف TTF يدعم العربية في server/fonts."
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


# ---------------- Header/Footer drawing ---------------- #

def draw_header_footer(canvas, doc, header_right_lines,
                       center_logo_path: Optional[str], left_logo_path: Optional[str],
                       font_regular: str, font_bold: str):
    page_w, page_h = A4
    margin = 15 * mm
    top_y = page_h - margin

    # Right header text (multi lines)
    canvas.setFont(font_regular, 9)
    y = top_y - 4
    for line in header_right_lines:
        canvas.drawRightString(page_w - margin, y, rtl(line))
        y -= 11  # line spacing

    # Center logo (fixed)
    if center_logo_path and os.path.exists(center_logo_path):
        try:
            img = ImageReader(center_logo_path)
            iw, ih = img.getSize()
            max_w, max_h = 60 * mm, 26 * mm
            scale = min(max_w / iw, max_h / ih)
            w, h = iw * scale, ih * scale
            x = (page_w - w) / 2
            y_img = top_y - h + 2
            canvas.drawImage(img, x, y_img, w, h, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    # Left logo (fixed)
    if left_logo_path and os.path.exists(left_logo_path):
        try:
            img = ImageReader(left_logo_path)
            iw, ih = img.getSize()
            max_w, max_h = 40 * mm, 26 * mm
            scale = min(max_w / iw, max_h / ih)
            w, h = iw * scale, ih * scale
            x = margin
            y_img = top_y - h + 2
            canvas.drawImage(img, x, y_img, w, h, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    # Footer signature — أكثر وضوحًا وأعلى من الأسفل بمسافة واضحة
    canvas.setFont(font_bold, 15)
    signature_y = 26 * mm  # مرفوعة عن أسفل الصفحة ~ 2.6 سم
    canvas.drawRightString(page_w - margin, signature_y, rtl("إعداد مساعد الإداري / ابتسام الفيفي"))


# ---------------- utils ---------------- #

def arabic_day_and_date_now() -> tuple[str, str]:
    # الإثنين=0 .. الأحد=6 في weekday()
    days = [
        "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"
    ]
    now = datetime.now()
    day_ar = days[now.weekday()]
    date_str = now.strftime("%Y/%m/%d")
    return day_ar, date_str


# ---------------- PDF builder ---------------- #

def build_pdf(rows: List[Tuple[str, str]]) -> bytes:
    font_regular, font_bold = ensure_fonts(FONT_REGULAR_PATH, FONT_BOLD_PATH)

    styles = getSampleStyleSheet()
    style_ar = ParagraphStyle(
        name="Arabic",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=12,
        leading=18,
        alignment=TA_RIGHT,
    )
    style_h1 = ParagraphStyle(
        name="ArabicH1",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=8,
        spaceBefore=0,
    )
    style_small = ParagraphStyle(name="ArabicSmall", parent=style_ar, fontSize=11, leading=16)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=60 * mm,
        bottomMargin=40 * mm,  # نزود المسافة السفلية حتى لا يتصادم المحتوى مع التوقيع المرتفع
        title=rtl("تقرير الجولات"),
        author=rtl("ابتسام الفيفي"),
        subject=rtl("تقرير الجولات"),
    )

    story = []
    story.append(Paragraph(rtl("تقرير الجولات"), style_h1))

    day_ar, date_str = arabic_day_and_date_now()
    lines = [
        "بناءً على تعليمات إدارة التعليم بمنطقة مكة المكرمة بأن يكون",
        f"الدوام ليوم : ({day_ar})",
        f"({date_str}) دوام المعلمين الممارسين للتدريس \"عن بعد\" فقد تم تكليفي بالجولات للحصة الرابعة عبر منصة مدرستي من قبل مديرة المدرسة: ابتسام محمد القرني",
    ]
    lead_html = "<br/>".join(rtl(l) for l in lines)
    story.append(Paragraph(lead_html, style_ar))
    story.append(Spacer(1, 6 * mm))

    # ==== جدول معكوس الأعمدة ====
    # قبل: ["م", "اسم المعلمة", "سبب عدم الحضور"]
    # الآن (معكوس): ["سبب عدم الحضور", "اسم المعلمة", "م"]
    data = [[rtl("سبب عدم الحضور"), rtl("اسم المعلمة"), rtl("م")]]
    for i, (name, reason) in enumerate(rows, start=1):
        data.append([
            Paragraph(rtl(reason), style_small),
            Paragraph(rtl(name), style_small),
            Paragraph(rtl(str(i)), style_small),
        ])

    col_widths = [90 * mm, 70 * mm, 14 * mm]  # أعرض سبب، ثم الاسم، ثم رقم صغير
    tbl = Table(data, colWidths=col_widths, hAlign='RIGHT')
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),          # محاذاة عامة لليمين
        ("FONT", (0, 0), (-1, -1), font_regular),
        ("FONTSIZE", (0, 0), (-1, 0), 12),
        ("FONTSIZE", (0, 1), (-1, -1), 11),
        ("LEADING", (0, 0), (-1, -1), 14),
        ("ALIGN", (-1, 1), (-1, -1), "CENTER"),        # محاذاة عمود الرقم (آخر عمود) للوسط
    ]))

    story.append(tbl)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(rtl("*لوحظ الانضباط في دخول الحصص"), style_ar))
    story.append(Paragraph(rtl("ختامًا أرجو قبول التقرير ولكم جزيل الشكر"), style_ar))

    header_right_lines = [
        "وزارة التعليم",
        "مكتب التعليم جنوب مكة",
        "الادارة العامة للتعليم بمنطقة مكة",
        "ابتدائية أم منيع الأنصارية",
    ]

    def on_page(canvas, doc_obj):
        draw_header_footer(canvas, doc_obj, header_right_lines,
                           CENTER_LOGO_PATH, LEFT_LOGO_PATH,
                           font_regular, font_bold)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@app.post("/api/pdf")
async def generate_pdf(rows_json: str = Form(...)):
    try:
        rows_in = json.loads(rows_json)
        rows: List[Tuple[str, str]] = [(r.get("name",""), r.get("reason","")) for r in rows_in]
    except Exception:
        return Response(status_code=400, content="rows_json يجب أن يكون JSON صالحًا")

    pdf_bytes = build_pdf(rows=rows)

    # اسم ملف عربي بشكل صحيح عبر RFC 5987
    from urllib.parse import quote
    file_name = f"تقرير_الجولات_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    encoded_name = quote(file_name)

    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
