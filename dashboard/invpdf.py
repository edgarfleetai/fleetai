"""Short investor report as a ready PDF file (downloaded, not printed).

Same content as the short report: per car received / expenses / profit /
share with the owner's explanation, the total, what is due, and what the
money was spent on (work, parts, prices, labour). Read-only.
"""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _font():
    """A font with Cyrillic letters: DejaVu on the server, Arial on Windows."""
    from fleetai.contract_extra import _font as contract_font
    name = contract_font()
    if name == "Helvetica":
        raise RuntimeError("Нет шрифта с русскими буквами для PDF")
    return name


def rub(kop):
    kop = int(kop or 0)
    sign, kop = ("−" if kop < 0 else ""), abs(kop)
    whole, cents = divmod(kop, 100)
    s = f"{whole:,}".replace(",", " ")  # non-breaking: an amount never splits across lines
    return f"{sign}{s}{',%02d' % cents if cents else ''} ₽"


def d2(v):
    s = str(v or "")[:10]
    return f"{s[8:10]}.{s[5:7]}.{s[0:4]}" if len(s) == 10 and s[4] == "-" else s


def parts_text(parts):
    out = []
    for p in parts or []:
        t = " ".join(x for x in (p.get("name"), p.get("brand"), p.get("position")) if x)
        if p.get("price"):
            t += f" — {rub(p['price'])}"
        if p.get("labor"):
            t += f", работа {rub(p['labor'])}"
        out.append(t)
    return "; ".join(out)


def build(report, notes, car_info):
    """report: invreport.investor_report(); notes: {code: {text}}; car_info: {code: "Model · plate"}."""
    font = _font()
    st = lambda size, **kw: ParagraphStyle("s", fontName=font, fontSize=size, leading=size * 1.3, **kw)
    h1, h2, sub = st(17), st(13, spaceBefore=12, spaceAfter=4), st(10, textColor=colors.HexColor("#555555"))
    td, tdr, why = st(9.5), st(9.5, alignment=2), st(9, textColor=colors.HexColor("#333333"))
    small = st(8.5, textColor=colors.HexColor("#444444"))
    P = lambda text, style=td: Paragraph(escape(str(text)), style)
    B = lambda text, style=td: Paragraph(f"<b>{escape(str(text))}</b>", style)

    T, cars = report.get("total") or {}, report.get("cars") or []
    fixed = (T.get("gps") or 0) + (T.get("garage") or 0)
    to_pay = (T.get("investor_part") or 0) - fixed - (T.get("payouts") or 0)
    story = [P(f"Отчёт инвестору: {report.get('name', '')}", h1),
             P(f"Период {d2(report.get('start'))} — {d2(report.get('end'))}", sub), Spacer(1, 6)]

    # --- cars ---
    rows, style = [[P("Машина"), P("Получено", tdr), P("Расход", tdr), P("Прибыль", tdr), P("Доля", tdr)]], [
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    for x in cars:
        code = x.get("code")
        label = f"{code} · {car_info[code]}" if car_info.get(code) else code
        rows.append([B(label), P(rub(x.get("income")), tdr), P(rub(x.get("expenses")), tdr),
                     P(rub(x.get("profit")), tdr), Paragraph(f"<b>{rub(x.get('investor_part'))}</b> ({x.get('percent')}%)", tdr)])
        text = ((notes or {}).get(code) or {}).get("text")
        if text:
            rows.append([Paragraph(f"<i>{escape(text)}</i>".replace("\n", "<br/>"), why), "", "", "", ""])
            style.append(("SPAN", (0, len(rows) - 1), (-1, len(rows) - 1)))
        style.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.4, colors.HexColor("#cccccc")))
    rows.append([B("Итого"), B(rub(T.get("income")), tdr), B(rub(T.get("expenses")), tdr),
                 B(rub(T.get("profit")), tdr), B(rub(T.get("investor_part")), tdr)])
    style.append(("LINEABOVE", (0, len(rows) - 1), (-1, len(rows) - 1), 1.2, colors.black))
    story.append(Table(rows, colWidths=[62 * mm, 28 * mm, 26 * mm, 28 * mm, 36 * mm], style=TableStyle(style)))

    pay = f"Доля инвестора {rub(T.get('investor_part'))}"
    if fixed:
        pay += f" − GPS и гараж {rub(fixed)}"
    if T.get("payouts"):
        pay += f" − выплачено в периоде {rub(T.get('payouts'))}"
    story += [Spacer(1, 8), Paragraph(escape(pay) + f" = <b>к выплате {escape(rub(to_pay))}</b>", st(11))]

    # --- expenses ---
    story.append(P("На что потрачены деньги", h2))
    ex = (report.get("lines") or {}).get("expenses") or []
    if not ex:
        story.append(P("Расходов за период не было."))
    else:
        rows, style = [[P("Дата"), P("На что"), P("Сумма", tdr)]], [
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        for code in dict.fromkeys(e.get("car") for e in ex):
            lst = [e for e in ex if e.get("car") == code]
            rows.append([B(f"{code} · {car_info[code]}" if car_info.get(code) else code), "", ""])
            style += [("SPAN", (0, len(rows) - 1), (-1, len(rows) - 1)),
                      ("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), colors.HexColor("#f1f1f1"))]
            for e in lst:
                what = e.get("what") or e.get("text") or e.get("category") or ""
                cat = e.get("category") or ""
                line = escape(what)
                if cat and cat.lower() not in what.lower():
                    line += f' <font color="#666666">({escape(cat.lower())})</font>'
                if e.get("share") == "investor_only":
                    line += " — <b>за счёт инвестора</b>"
                elif e.get("share") == "park_only":
                    line += " — за счёт парка"
                cell = [Paragraph(line, td)]
                pt = parts_text(e.get("parts"))
                if pt:
                    cell.append(P(pt, small))
                rows.append([P(d2(e.get("date"))), cell, P(rub(e.get("amount")), tdr)])
                style.append(("LINEBELOW", (0, len(rows) - 1), (-1, len(rows) - 1), 0.4, colors.HexColor("#cccccc")))
            rows.append(["", B(f"Всего по {code}"), B(rub(sum(e.get("amount") or 0 for e in lst)), tdr)])
        rows.append(["", B("Всего расходов"), B(rub(sum(e.get("amount") or 0 for e in ex)), tdr)])
        style.append(("LINEABOVE", (0, len(rows) - 1), (-1, len(rows) - 1), 1.2, colors.black))
        story.append(Table(rows, colWidths=[24 * mm, 126 * mm, 30 * mm], style=TableStyle(style)))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                      bottomMargin=15 * mm, title=f"Отчёт инвестору {report.get('name', '')}").build(story)
    return buf.getvalue()
