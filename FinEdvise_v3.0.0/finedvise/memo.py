"""One-page decision memo, generated from a proposal and the engine.

Everything typed by users or read from files is escaped with html.escape.
The memo is plain HTML with print styles: the browser's Print saves it as PDF.
"""
from __future__ import annotations

from html import escape
from typing import Any, Dict, Optional

from . import engine, fmt
from .data import opening_cash, outstanding_tuition, reserve_amount
from .store import Sandbox

STYLE = """
body{font-family:system-ui,-apple-system,'Segoe UI','Noto Sans Bengali','Nirmala UI',sans-serif;color:#1d2433;margin:0;background:#f4f1ea}
.page{max-width:800px;margin:24px auto;background:#fff;padding:32px 40px;border:1px solid #ddd6c8}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 8px;color:#0f5c4d;text-transform:uppercase;letter-spacing:.04em}
.meta{color:#5b6475;font-size:13px}.tag{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:99px;margin-left:6px;vertical-align:middle}
.syn{background:#fff3d6;color:#8a5a00}.ok{background:#dff3ea;color:#0f5c4d}.bad{background:#fde6e4;color:#a1281c}.pend{background:#e7ecf7;color:#2b4a8b}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #ece6da;padding:6px 8px;text-align:left}td.n{text-align:right;font-variant-numeric:tabular-nums}
.box{background:#f7f4ee;border-left:4px solid #0f5c4d;padding:10px 14px;font-size:14px}.small{font-size:12px;color:#5b6475}
code{font-size:11px;word-break:break-all}@media print{body{background:#fff}.page{border:0;margin:0}}
"""


def render(sb: Sandbox, pid: str, lang: str = "en") -> Optional[str]:
    proposal = sb.state["proposals"].get(pid)
    if proposal is None:
        return None
    lang = "bn" if lang == "bn" else "en"
    e = lambda s: escape(str(s), quote=True)  # noqa: E731
    money = lambda v: e(fmt.bdt(v, lang))  # noqa: E731
    data = sb.data()
    c = proposal["content"]
    others = [l for l in sb.commitments() if not l["id"].startswith(pid + "-")]
    base = engine.scenario_view(data, engine.BASE, others)
    stress = engine.scenario_view(data, engine.DOWNSIDE, others)
    cmp = engine.compare_plans(data, engine.DOWNSIDE, others)
    be = engine.break_even(data, c["total"])
    bn = lang == "bn"
    T = (lambda en_text, bn_text: bn_text if bn else en_text)  # noqa: E731
    status_tag = {"approved": ("ok", T("APPROVED", "অনুমোদিত")), "rejected": ("bad", T("REJECTED", "বাতিল")),
                  "pending": ("pend", T("PENDING APPROVAL", "অনুমোদনের অপেক্ষায়"))}[proposal["status"]]
    title = c["title_bn"] if bn else c["title_en"]
    school = data["meta"]["school_name_bn" if bn else "school_name_en"]

    rows = "".join(
        f"<tr><td>{e(i['label_bn'] if bn else i['label_en'])}</td><td>{e(i['pay_date'])}</td>"
        f"<td class='n'>{money(i['amount'])}</td><td class='n'>{money(i['staging_cost'])}</td></tr>"
        for i in c["schedule"])
    reason = cmp["reason"]["bn" if bn else "en"]
    checks = c["checks"]
    yes, no = T("yes", "হ্যাঁ"), T("no", "না")
    decided = ""
    if proposal["decided_by"]:
        decided = (f"<tr><td>{T('Decided by', 'সিদ্ধান্ত')}</td><td>{e(proposal['decided_by'])} · {e(proposal['decided_utc'])}</td></tr>"
                   f"<tr><td>{T('Sandbox ledger posting', 'স্যান্ডবক্স লেজার পোস্টিং')}</td><td>#{e(proposal.get('posting_seq') or '-')}</td></tr>")
    note = f"<p class='small'>{T('Note', 'নোট')}: {e(c['note'])}</p>" if c.get("note") else ""
    rate = str(data["student_economics"]["collection_rate"])
    estimate_note = T("Extra students per plan are the owner's estimates (ASSUMED); advertising is not assumed to cause admissions.",
                      "প্ল্যানভিত্তিক অতিরিক্ত শিক্ষার্থী মালিকের অনুমান (ASSUMED); বিজ্ঞাপনই ভর্তি ঘটায় এমন দাবি করা হয়নি।")
    collection_note = T("Collection rate " + rate + " was approved by the owner after last year's variance.",
                        "আদায়ের হার " + rate + " গত বছরের পার্থক্যের পর মালিক অনুমোদন করেছেন।")
    html = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(T('Decision memo', 'সিদ্ধান্ত মেমো'))} {e(pid)}</title><style>{STYLE}</style></head><body><div class="page">
<div class="meta">{e(school)} <span class="tag syn">{e(data['meta']['dataset_label'])}</span></div>
<h1>{e(T('Decision memo', 'সিদ্ধান্ত মেমো'))}: {e(title)} <span class="tag {status_tag[0]}">{e(status_tag[1])}</span></h1>
<div class="meta">{e(pid)} · {T('created', 'তৈরি')} {e(proposal['created_utc'])} {T('by', '—')} {e(proposal['created_by'])} · {T('scenario date', 'সিনারিও তারিখ')} {e(data['meta']['scenario_date'])}</div>

<h2>{T('Decision', 'সিদ্ধান্ত')}</h2>
<div class="box">{T('Spend', 'খরচ')} <b>{money(c['total'])}</b> {T('on the admission season, on this schedule', 'ভর্তি মৌসুমে, এই সময়সূচিতে')}.
{T('Safe in the base forecast', 'মূল পূর্বাভাসে নিরাপদ')}: <b>{yes if checks['base_ok'] else no}</b> ·
{T('safe in the stress test', 'স্ট্রেস টেস্টে নিরাপদ')}: <b>{yes if checks['stress_ok'] else no}</b></div>
<table><tr><th>{T('Item', 'খাত')}</th><th>{T('Pay on', 'পরিশোধ')}</th><th>{T('Amount', 'পরিমাণ')}</th><th>{T('Cost of paying later', 'পরে দেওয়ার খরচ')}</th></tr>{rows}</table>

<h2>{T('Why', 'কেন')}</h2>
<p>{e(reason)}</p>
<table>
<tr><td>{T('Cash you can use today (C_0)', 'আজ ব্যবহারযোগ্য নগদ (C_0)')} <span class="tag ok">VERIFIED</span></td><td class="n">{money(opening_cash(data).value)}</td></tr>
<tr><td>{T('Tuition parents owe (not cash)', 'বকেয়া টিউশন (নগদ নয়)')} <span class="tag ok">VERIFIED</span></td><td class="n">{money(outstanding_tuition(data).value)}</td></tr>
<tr><td>{T('Minimum reserve', 'ন্যূনতম রিজার্ভ')} <span class="tag pend">ASSUMED</span></td><td class="n">{money(reserve_amount(data))}</td></tr>
<tr><td>{T('Safe to spend before this decision: base forecast', 'এই সিদ্ধান্তের আগে নিরাপদ খরচ: মূল পূর্বাভাস')} <span class="tag pend">SIMULATED</span></td><td class="n">{money(base['sti']['value'])}</td></tr>
<tr><td>{T('Safe to spend before this decision: stress test', 'এই সিদ্ধান্তের আগে নিরাপদ খরচ: স্ট্রেস টেস্ট')} <span class="tag pend">SIMULATED</span></td><td class="n">{money(stress['sti']['value'])}</td></tr>
<tr><td>{T('Extra students to break even (12 months)', 'ব্রেক-ইভেনে অতিরিক্ত শিক্ষার্থী (১২ মাস)')}</td><td class="n">{e(be['economic_break_even']['value'])}</td></tr>
<tr><td>{T('Extra students to get the cash back by end of January', 'জানুয়ারির মধ্যে নগদ ফেরতে অতিরিক্ত শিক্ষার্থী')}</td><td class="n">{e(be['cash_payback']['value'])}</td></tr>
</table>

<h2>{T('Assumptions and risks', 'অনুমান ও ঝুঁকি')}</h2>
<ul>
<li>{e(T('Stress test: ' + ', '.join(engine.DOWNSIDE.describe('en')) + '.', 'স্ট্রেস টেস্ট: ' + ', '.join(engine.DOWNSIDE.describe('bn')) + '।'))}</li>
<li>{e(estimate_note)}</li>
<li>{e(collection_note)}</li>
<li>{e(T('Money the campaign may bring in is not counted in safe-to-spend.', 'প্রচারণা থেকে আসা সম্ভাব্য টাকা নিরাপদ খরচের হিসাবে ধরা হয়নি।'))}</li>
</ul>
{note}
<h2>{T('Approval record', 'অনুমোদনের রেকর্ড')}</h2>
<table>
<tr><td>{T('Status', 'অবস্থা')}</td><td>{e(status_tag[1])}</td></tr>
<tr><td>{T('Content hash (SHA-256)', 'কনটেন্ট হ্যাশ (SHA-256)')}</td><td><code>{e(proposal['content_hash'])}</code></td></tr>
{decided}
</table>
<p class="small">{e(T('Generated by FinEdvise. Every number comes from the deterministic engine and data version ', 'FinEdvise তৈরি করেছে। প্রতিটি সংখ্যা ডিটারমিনিস্টিক ইঞ্জিন ও ডেটা সংস্করণ ') + c['data_version'] + T('. Synthetic sandbox data.', ' থেকে। সিন্থেটিক স্যান্ডবক্স ডেটা।'))}</p>
</div></body></html>"""
    return html
