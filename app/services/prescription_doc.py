"""Официальный документ предписания — HTML, генерируется на сервере из данных БД.

Единый источник (шаблон + номер из БД), одинаков у всех. Клиент открывает и
печатает (браузер → «Сохранить как PDF»). PDF-версию можно добавить позже
(fpdf2), не меняя контракт.
"""
from __future__ import annotations

import html
from pathlib import Path

_FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "DejaVuSans.ttf"


def _esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def _s(v) -> str:
    return str(v) if v is not None else ""


def render_pdf(*, city, presc, obj, owner, violations, inspector) -> bytes:
    """Тот же официальный документ, но настоящий PDF (fpdf2 + кириллический шрифт)."""
    from fpdf import FPDF

    number = _s(getattr(presc, "id", ""))
    owner_line = _s(getattr(owner, "name", "")) if owner else "—"
    if owner and getattr(owner, "bin", None):
        owner_line += f", БИН {owner.bin}"

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(_FONT_PATH))
    W = pdf.w - pdf.l_margin - pdf.r_margin

    def text(s: str, size=11, align="L", gap=1.2):
        pdf.set_font("DejaVu", "", size)
        pdf.multi_cell(W, size * 0.5 + 2, _s(s), align=align)
        pdf.ln(gap)

    text(f"Аппарат акима г. {city}", 12, "C", 0.5)
    text("Отдел урбанистики и городской среды", 9, "C", 3)
    text(f"ПРЕДПИСАНИЕ № {number}\nоб устранении нарушений", 14, "C", 0.5)
    text(f"г. {city} · {getattr(presc, 'issuedAt', '')}", 9, "C", 4)

    text(f"Кому: {owner_line}")
    text(f"Объект: {getattr(obj, 'name', '')} ({getattr(obj, 'type', '')})")
    text(f"Адрес: {getattr(obj, 'address', '')}", gap=3)

    text(f"По результатам проверки от {getattr(presc, 'issuedAt', '')} выявлены несоответствия дизайн-коду города:")
    if violations:
        for i, v in enumerate(violations, 1):
            text(f"  {i}. {v}", gap=0.5)
    else:
        text(getattr(presc, "description", "") or "—")
    pdf.ln(2)

    text(f"Требуется устранить нарушения в срок до {getattr(presc, 'deadline', '')}.")
    text(f"Повторная проверка назначена на {getattr(presc, 'reinspectionDate', '')}.", gap=3)
    text("Основание: правила благоустройства и дизайн-код города. Неисполнение в срок влечёт "
         "ответственность согласно законодательству РК.", 9, gap=8)

    text(f"Проверку провёл (урбанист): {_s(inspector or '________________')}", 10, gap=6)
    text("Подпись / печать: ________________", 10)

    out = pdf.output()
    return bytes(out)


def render_html(*, city, presc, obj, owner, violations, inspector) -> str:
    number = getattr(presc, "id", "")
    items = "".join(f"<li>{_esc(v)}</li>" for v in violations)
    violations_block = (
        f"<ol>{items}</ol>" if violations
        else f"<p><i>{_esc(getattr(presc, 'description', ''))}</i></p>"
    )
    owner_line = _esc(getattr(owner, "name", "")) if owner else "—"
    bin_line = f", БИН {_esc(owner.bin)}" if owner and getattr(owner, "bin", None) else ""

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Предписание № {_esc(number)}</title>
<style>
  @page {{ size: A4; margin: 20mm; }}
  body {{ font-family: 'Times New Roman', Georgia, serif; color: #111; font-size: 13px; line-height: 1.5; max-width: 720px; margin: 24px auto; padding: 0 16px; }}
  .center {{ text-align: center; }}
  h1 {{ font-size: 16px; text-align: center; margin: 18px 0 4px; }}
  .muted {{ color: #555; }}
  ol {{ padding-left: 22px; }}
  .row {{ margin: 4px 0; }}
  .sign {{ display: flex; justify-content: space-between; margin-top: 48px; }}
  .sign .line {{ border-top: 1px dashed #999; padding-top: 4px; min-width: 180px; }}
  .toolbar {{ text-align: center; margin-bottom: 16px; }}
  .toolbar button {{ padding: 8px 16px; font-size: 14px; cursor: pointer; }}
  @media print {{ .toolbar {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<div class="toolbar"><button onclick="window.print()">🖨 Печать / Сохранить как PDF</button></div>

<div class="center">
  <p><b>Аппарат акима г. {_esc(city)}</b></p>
  <p class="muted">Отдел урбанистики и городской среды</p>
</div>

<h1>ПРЕДПИСАНИЕ № {_esc(number)}<br>об устранении нарушений</h1>
<p class="center muted">г. {_esc(city)} · {_esc(getattr(presc, 'issuedAt', ''))}</p>

<div class="row"><b>Кому:</b> {owner_line}{bin_line}</div>
<div class="row"><b>Объект:</b> {_esc(getattr(obj, 'name', ''))} ({_esc(getattr(obj, 'type', ''))})</div>
<div class="row"><b>Адрес:</b> {_esc(getattr(obj, 'address', ''))}</div>

<p>По результатам проверки от {_esc(getattr(presc, 'issuedAt', ''))} на объекте выявлены следующие несоответствия дизайн-коду города:</p>
{violations_block}

<p>Требуется устранить выявленные нарушения в срок до <b>{_esc(getattr(presc, 'deadline', ''))}</b>.</p>
<p>Повторная проверка назначена на {_esc(getattr(presc, 'reinspectionDate', ''))}.</p>

<p class="muted">Основание: правила благоустройства и дизайн-код города. Неисполнение в установленный срок влечёт ответственность согласно законодательству РК.</p>

<div class="sign">
  <div><div class="muted">Проверку провёл (урбанист)</div><div class="line">{_esc(inspector or '')}</div></div>
  <div><div class="muted">Подпись / печать</div><div class="line">&nbsp;</div></div>
</div>
</body></html>"""
