"""Официальный документ предписания — HTML, генерируется на сервере из данных БД.

Единый источник (шаблон + номер из БД), одинаков у всех. Клиент открывает и
печатает (браузер → «Сохранить как PDF»). PDF-версию можно добавить позже
(fpdf2), не меняя контракт.
"""
from __future__ import annotations

import html


def _esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


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
