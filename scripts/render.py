#!/usr/bin/env python3
"""BI-style offline report: complete tables first, reference-matched SVG charts."""
import sys
sys.dont_write_bytecode = True
import html
from provider_policy import public_text, STOCK_INDUSTRY_NOTE
import json
import math
from datetime import date
from pathlib import Path
from fetch import (ASSETS, REGIONS, SECTORS, MARKET_CAP, SECTOR_KEYS, numeric, fmt, holding_rows,
                   holding_valuation, industry_group_summaries)
from report_ui import STOCK_CSS, STOCK_JS, stock_table, OVERVIEW_CSS, overview_cards

COLORS = ['#00579A', '#447EAD', '#D7AA00', '#779BBC', '#65788B', '#B8CDDF']
LINE_COLORS = ['#00579A', '#D55E00']
REPORT_CSS = '''
:root{--blue:#00579A;--cyan:#00579A;--ink:#263746;--muted:#657582}
*{box-sizing:border-box}body{margin:0;background:#f2f4f5;color:var(--ink);font:13px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;font-variant-numeric:tabular-nums}
main{max-width:1360px;margin:20px auto;padding:24px 32px;background:white}header{text-align:center}h1{color:var(--blue);font-size:27px;margin:0 0 16px}h2{color:var(--blue);font-size:20px;margin:26px 0 14px;padding:5px 0;border-bottom:2px solid var(--blue)}h2.major{text-align:center}h3{color:var(--blue);font-size:15px;margin:18px 0 8px}h4{color:var(--blue);font-size:14px;margin:0 0 8px}.note,.meta{color:var(--muted);font-size:12px;margin:7px 0}.meta{text-align:left;border:1px solid #cbd9e1;padding:10px 14px}.panel{margin:12px 0}.section-copy{border-left:3px solid #b7dce6;padding-left:10px;color:#506575;font-size:12px}.chart-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 22px}.chart{min-width:0;margin:10px 0}.chart svg{display:block;width:100%;height:auto;max-height:260px}svg text{font-family:inherit;fill:var(--ink);font-size:11px}.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:11px}.swatch{display:inline-block;width:9px;height:9px;margin-right:5px}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px;text-align:right}th,td{padding:6px 7px;border-bottom:1px solid #e3e9ed;vertical-align:middle}thead th{background:var(--cyan);color:white;font-weight:600;white-space:normal}tbody tr:nth-child(even){background:#f3f5f6}td:first-child,th:first-child{text-align:left}td:nth-child(2){text-align:left}td{white-space:nowrap}tr.total{font-weight:700;background:#e9f2f7!important}table.heat{table-layout:fixed;font-size:11px}table.heat th{background:white;color:var(--ink);overflow-wrap:anywhere}table.heat th:first-child{width:180px}table.heat td{text-align:center;white-space:normal}.overview table{font-size:13px}.overview td{white-space:normal}.overview strong{color:var(--blue)}button{border:1px solid #cbd9e1;background:white;color:var(--blue);padding:5px 14px;cursor:pointer;float:right}details{margin:10px 0}summary{cursor:pointer;color:var(--blue)}footer{font-size:11px;color:var(--muted);border-top:1px solid #cbd9e1;padding-top:12px;margin-top:24px}#tooltip{display:none;position:fixed;background:#173c58;color:white;padding:8px 10px;font-size:12px;max-width:320px;z-index:10;pointer-events:none}[data-tip]:focus{outline:2px solid #ffd51e}.chart .active{filter:brightness(1.15)}
/* Explicit column alignment overrides positional rules for all table types. */
table th.cell-text,table td.cell-text{text-align:left}
table th.cell-number,table td.cell-number{text-align:right}
table thead th.group-heading{text-align:center;border-bottom:1px solid #ffffff60}
table thead th{background:var(--blue);line-height:1.4}
.chart-grid{align-items:start}.chart-grid>.chart{display:flex;flex-direction:column}
.chart-grid>.chart>h4{min-height:42px}.chart-grid>.chart>svg{height:240px;max-height:240px;flex:none}
.section-copy{border-left-color:#B8CDDF}
.data-description{display:flex;align-items:flex-start;gap:14px;border-style:dashed;line-height:1.8}
.data-description-label{flex:none;background:#e4f3fb;color:var(--blue);font-weight:600;padding:3px 7px}
.data-description-content{min-width:0}.data-description-content p{margin:0 0 8px}.data-description-content p:last-child{margin-bottom:0}
@media(max-width:760px){.data-description{flex-direction:column;gap:8px}}
#tooltip{white-space:pre-line}
header{position:relative}header button{position:absolute;right:0;top:0;float:none}header h1{padding:0 100px}
@media(max-width:760px){main{margin:0;padding:14px}h1{font-size:22px}.chart-grid{grid-template-columns:1fr}th,td{padding:5px}table{font-size:11px}.heat{min-width:800px}header h1{padding:36px 0 0}.chart-grid>.chart>h4{min-height:0}}
@media print{@page{size:A3 landscape;margin:12mm}body{background:white}main{max-width:none;margin:0;padding:0}button,#tooltip{display:none!important}h2,h3,h4{break-after:avoid}.chart{break-inside:avoid}.table-scroll{overflow:visible}table{font-size:9px}th,td{padding:4px}thead{display:table-header-group}tr{break-inside:avoid}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
'''
REPORT_CSS += STOCK_CSS + OVERVIEW_CSS
REPORT_CSS += """
/* Uniform table widths; column and group titles stay on one line. */
main{max-width:1760px;padding-left:24px;padding-right:24px}
.table-scroll{width:100%;max-width:100%;overflow-x:auto}
main table,main table.heat,main table.stock-table{
 width:var(--report-table-width,100%)!important;max-width:none!important;min-width:0!important;
 table-layout:auto!important;margin-left:auto;margin-right:auto;text-align:center!important;
}
main table th,main table td,main table th.cell-text,main table td.cell-text,
main table th.cell-number,main table td.cell-number,main table.heat th:first-child{
 text-align:center!important;vertical-align:middle!important;width:auto!important;
 min-width:0!important;padding:7px 6px!important;white-space:normal;
 overflow-wrap:anywhere;word-break:normal;line-height:1.6;
}
main table thead th,main table thead th.group-heading{
 white-space:nowrap!important;overflow-wrap:normal;word-break:normal;
}
main table .stock-value{text-align:center!important;white-space:normal;overflow-wrap:anywhere}
@media screen and (max-width:760px){main{padding-left:14px;padding-right:14px}}
@media screen and (max-width:1164px){
 main table,main table.heat,main table.stock-table{min-width:1100px!important}
}
@media print{
 main{max-width:none;padding:0}
 main table,main table.heat,main table.stock-table{width:100%!important;min-width:0!important;max-width:100%!important}
 main table th,main table td{white-space:normal;padding:5px 6px!important}
}
"""
REPORT_CSS += '''
footer.report-disclaimer{border:0;margin-top:30px;padding-top:0;color:#999;font-size:14px;line-height:1.9;text-align:left}
.report-disclaimer .disclaimer-title{display:block;color:inherit;font-size:20px;font-weight:700;margin:0}
.report-disclaimer p{margin:0;text-indent:2em;line-height:1.9;overflow-wrap:anywhere}
'''
DATA_REPORT_CSS = '''
thead th.group-start{border-left:2px solid #b6d6eb}
tbody td.group-start{border-left:1px solid #aabdc9}
.chart>.legend{justify-content:center;margin-top:8px;text-align:center}
.chart-plot{overflow-x:auto}
.chart-plot svg{max-height:none}
.chart-plot svg text{font-size:13px}
.allocation-grid{gap:16px 22px}
.allocation-grid>.chart{margin:0}
.allocation-grid>.chart>h4{min-height:0;margin-bottom:4px}
.allocation-grid>.chart>svg{height:auto;max-height:none}
@media screen and (max-width:900px){
 .chart-plot svg{min-width:800px}
 .chart-plot svg text{font-size:16px}
}
.correlation-viewport{
 --label-width:clamp(138px,14vw,220px);
 --header-height:54px;
 --row-height:35px;
 overflow:auto;
}
.correlation-viewport[data-many-funds]{
 max-height:calc(var(--header-height) + var(--visible-funds) * var(--row-height));
 cursor:grab;
}
.correlation-viewport.is-dragging{cursor:grabbing;user-select:none}
.correlation-viewport:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
main table.heat.correlation-matrix{
 width:max(calc(var(--label-width) + 108px * var(--fund-count)),
           calc(var(--label-width) + (100% - var(--label-width)) * var(--fund-count) / var(--visible-funds)))!important;
 min-width:0!important;table-layout:fixed!important;
 border-collapse:separate;border-spacing:0;margin:0;
}
.correlation-matrix .correlation-label-column{width:var(--label-width)}
.correlation-matrix thead th{position:sticky;top:0;z-index:2;height:var(--header-height)}
.correlation-matrix th:first-child{position:sticky;left:0;z-index:1}
.correlation-matrix thead th:first-child{z-index:3}
.correlation-matrix tbody th,.correlation-matrix tbody td{height:var(--row-height)}
.correlation-matrix .correlation-label{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media print{
 .correlation-viewport[data-many-funds]{max-height:none}
 .correlation-viewport{overflow:visible}
 main table.heat.correlation-matrix{width:100%!important}
 .correlation-matrix th{position:static!important}
}
'''
DISCLAIMER_PARAGRAPHS = (
    '基金有风险，投资需谨慎，详阅基金法律文件。请投资者关注各基金的相关风险，在全面了解基金产品的风险收益特征、运作特点及销售机构适当性意见的基础上，审慎作出投资决策。',
    '本报告中所包含的数据信息及观点等仅供本公司提供对象内部参考，禁止向不特定公众分发传播，不作为任何基金业务的宣传推介、投资建议或关于收益的明示或暗示及担保，也不作为任何法律性文件或宣传营销材料。本报告所载信息基于相关数据方整理而来，但本公司不保证其准确性、可靠性、时效性及完整性，且不对任何机构或个人依据或者使用本报告资料所造成的任何后果及与此有关的任何直接或间接损失承担任何责任。本报告所载的观点、分析等信息反映的是本公司基于自有方法在特定时间、特定环境下的判断，这些判断可能与其他机构的判断存在差异，后续也存在发生变动的可能，本公司保留对本报告资料的修改、解释权，但无义务保证随时将最新资料、观点及分析及时对外传递。',
    '未经本公司授权，本报告的任何部分均不得以任何方式进行拷贝、复制、修改、或转载、分发、披露给任何第三方，或以任何侵犯本公司版权的其他方式使用。任何本公司以外的机构或个人发送、披露、使用本报告的，则由其自行承担由此产生的全部后果与责任。任何机构或个人以任何方式使用本报告，即视为已完全知悉、理解并接受本声明的全部内容。',
)
REPORT_JS = '''(()=>{
const tip=document.getElementById('tooltip');
function hide(){tip.style.display='none';document.querySelectorAll('[data-trend-cursor]').forEach(el=>el.setAttribute('visibility','hidden'))}
function show(text,e,el){tip.textContent=text;tip.style.display='block';const b=el.getBoundingClientRect();tip.style.left=Math.max(6,Math.min((e.clientX??b.left)+12,innerWidth-tip.offsetWidth-8))+'px';tip.style.top=Math.max(6,Math.min((e.clientY??b.top)+12,innerHeight-tip.offsetHeight-8))+'px'}
document.querySelectorAll('[data-tip]').forEach(el=>{const display=e=>show(el.dataset.tip,e,el);el.addEventListener('pointerenter',display);el.addEventListener('pointermove',display);el.addEventListener('pointerleave',hide);el.addEventListener('focus',display);el.addEventListener('blur',hide)});
document.querySelectorAll('[data-trend-hit]').forEach(el=>{
const svg=el.ownerSVGElement,points=JSON.parse(svg.dataset.trendPoints),cursor=svg.querySelector('[data-trend-cursor]');
function display(index,e){const p=points[index];cursor.setAttribute('x1',p.x);cursor.setAttribute('x2',p.x);cursor.setAttribute('visibility','visible');show(p.tip,e,el);el.setAttribute('aria-label',p.tip)}
let index=0;
el.addEventListener('pointermove',e=>{const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const x=p.matrixTransform(svg.getScreenCTM().inverse()).x;index=points.reduce((best,p,i)=>Math.abs(p.x-x)<Math.abs(points[best].x-x)?i:best,0);display(index,e)});
el.addEventListener('pointerleave',hide);el.addEventListener('focus',e=>display(index,e));el.addEventListener('blur',hide);
el.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();index=Math.max(0,Math.min(points.length-1,index+(e.key==='ArrowRight'?1:-1)));display(index,e)}});
});
document.addEventListener('keydown',e=>{if(e.key==='Escape')hide()});document.querySelector('[data-print]').addEventListener('click',()=>{hide();window.print()});
})();'''


REPORT_JS += STOCK_JS

TABLE_JS = '''(()=>{
const main=document.querySelector('main');if(!main)return;
let pending=false;
function fitTables(){
 pending=false;main.style.removeProperty('--report-table-width');
 const tables=Array.from(main.querySelectorAll('table:not(.correlation-matrix)'));
 const width=Math.ceil(Math.max(0,...tables.map(table=>table.getBoundingClientRect().width)));
 if(width)main.style.setProperty('--report-table-width',width+'px');
}
function schedule(){if(!pending){pending=true;requestAnimationFrame(fitTables)}}
schedule();window.addEventListener('resize',schedule);
document.addEventListener('toggle',schedule,true);
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(schedule);
})();'''
REPORT_JS += TABLE_JS

DATA_REPORT_JS = '''document.querySelectorAll('[data-correlation-scroll]').forEach(viewport => {
  const tooltip = document.getElementById('tooltip');
  let start = null;

  viewport.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'mouse' || event.button !== 0 || !event.target.closest('table')) return;
    if (viewport.scrollWidth <= viewport.clientWidth && viewport.scrollHeight <= viewport.clientHeight) return;
    start = { id: event.pointerId, x: event.clientX, y: event.clientY,
              left: viewport.scrollLeft, top: viewport.scrollTop };
    event.preventDefault();
  });
  viewport.addEventListener('pointermove', event => {
    if (!start || event.pointerId !== start.id) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (!viewport.hasPointerCapture(start.id)) {
      if (Math.hypot(dx, dy) < 4) return;
      viewport.setPointerCapture(start.id);
      viewport.classList.add('is-dragging');
    }
    viewport.scrollLeft = start.left - dx;
    viewport.scrollTop = start.top - dy;
    tooltip.style.display = 'none';
  });
  function stop(event) {
    if (!start || event.pointerId !== start.id) return;
    start = null;
    viewport.classList.remove('is-dragging');
  }
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    viewport.addEventListener(type, stop);
  }
  viewport.addEventListener('pointerleave', event => {
    if (!viewport.hasPointerCapture(event.pointerId)) stop(event);
  });
  viewport.addEventListener('scroll', () => { tooltip.style.display = 'none'; });
});'''


def actual_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def data_description_html(report):
    """FOF holding period follows the agreed schedule at the P01 valuation date."""
    meta = report['meta']
    p01 = report.get('data', {}).get('1') or {}
    valuation_day = actual_date(p01.get('latestDate'))
    stock_quarter = actual_date(p01.get('periodicReportCutoffDate'))
    fof_period = None
    if valuation_day:
        as_of = date.fromisoformat(valuation_day)
        if 4 <= as_of.month <= 8:
            fof_period = date(as_of.year - 1, 12, 31).isoformat()
        else:
            year = as_of.year - 1 if as_of.month <= 3 else as_of.year
            fof_period = date(year, 6, 30).isoformat()
    lines = [
        '本报告涉及的单只基金数据均基于公开数据计算',
        '1. 业绩和风险数据：回顾期为%s~%s，如无标记，其他数据截至%s，ETF基金基于收盘价计算；' % (
            meta.get('range_start') or '日期未返回',
            meta.get('range_end') or '日期未返回',
            meta.get('calculation_date') or '日期未返回'),
        '2. 资产配置数据：FOF基金以最近半年报/年报（%s）持仓全部基金为基础，'
        '穿透季报（%s）持仓前十大股票；ETF和联接基于每日最新持仓全部股票穿透计算。'
        '其他基金根据季报持仓前十大股票计算。' % (fof_period or '日期未返回', stock_quarter or '日期未返回'),
    ]
    return '<div class="meta data-description"><span class="data-description-label">数据说明</span><div class="data-description-content">' + ''.join('<p>' + esc(line) + '</p>' for line in lines) + '</div></div>'


def esc(value):
    return html.escape(str(value if value is not None else '—'), quote=True)


def disclaimer_html():
    return ('<footer class="report-disclaimer"><strong class="disclaimer-title">免责声明与风险提示</strong>'
            + ''.join('<p>' + esc(text) + '</p>' for text in DISCLAIMER_PARAGRAPHS) + '</footer>')


def attr(text):
    return 'tabindex="0" data-tip="'+esc(text)+'" aria-label="'+esc(text)+'"'


def axis_label_lines(text, width):
    """E-Allocation's CJK-aware wrapping; never abbreviate category names."""
    import unicodedata
    limit = max(2, int(width / 6))
    lines, current, units = [], '', 0
    for char in str(text):
        size = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
        if current and units + size > limit:
            lines.append(current)
            current, units = '', 0
        current += char
        units += size
    if current:
        lines.append(current)
    return lines or ['']


def axis_label(x, y, lines, anchor='middle', role='category'):
    return '<text x="%s" y="%s" text-anchor="%s" data-label-role="%s">%s</text>' % (
        x, y, anchor, role, ''.join('<tspan x="%s" dy="%s">%s</tspan>' %
                                  (x, 0 if i == 0 else 14, esc(text)) for i, text in enumerate(lines)))


def ticks_with_zero(low, span, position):
    ticks = [low + span * i / 4 for i in range(5)]
    return sorted([0] + [value for value in ticks
                         if round(value, 1) and abs(position(value) - position(0)) >= 15])


def grid_tick(value, start, end, label, unit, anchor='end'):
    stroke = 'data-zero-line="true" stroke="#526d82" stroke-width="1.6"' if value == 0 else 'stroke="#e3e9ed"'
    number = '0' if value == 0 else f'{value:.1f}'
    return (f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" {stroke}/>'
            f'<text x="{label[0]}" y="{label[1]}" text-anchor="{anchor}">{number}{esc(unit)}</text>')


def table(headers, rows, total=False, groups=()):
    # BI columns are fixed: missing data must not erase their headings.
    if any(len(row) != len(headers) for row in rows):
        raise ValueError('表格列数不一致：'+str(headers))
    if groups and sum(span for _,span in groups) != len(headers):
        raise ValueError('分组表头列数不一致')
    text_headers = ('代码','名称','日期','披露日','报告类别','基金经理','基金类型','基金细分类型','风格标签','赛道标签','所属地区','行业板块','一级行业','大行业')
    text_labels = {'指标','类别','行业','管理人','基金大类','对比指数','价格日期','核心发现','数据及解读'}
    classes = ['cell-text' if h in text_labels or any(label in h for label in text_headers) else 'cell-number' for h in headers]
    column_groups, group_cells = [], []
    offset = 0
    for label, span in groups:
        divider = ' group-start' if offset else ''
        classes[offset] += divider
        column_groups.append('<colgroup span="%d"></colgroup>' % span)
        group_cells.append('<th class="group-heading%s" scope="colgroup" colspan="%d">%s</th>' %
                           (divider, span, esc(label)))
        offset += span
    group_row = '<tr>'+''.join(group_cells)+'</tr>' if groups else ''
    scope = ' scope="col"' if groups else ''
    return '<div class="table-scroll"><table>'+''.join(column_groups)+'<thead>'+group_row+'<tr>'+''.join('<th class="'+cls+'"'+scope+'>'+esc(h)+'</th>' for h,cls in zip(headers,classes))+'</tr></thead><tbody>'+''.join(
        '<tr'+(' class="total"' if total and i == len(rows)-1 else '')+'>'+''.join('<td class="'+cls+'">'+esc(c)+'</td>' for c,cls in zip(row,classes))+'</tr>' for i, row in enumerate(rows))+'</tbody></table></div>'


def chart(key, title, kind, content, note='', *, legend='', wide=False):
    if wide and content:
        content = '<div class="chart-plot">'+content+'</div>'
    return '<article class="chart" data-chart-key="'+esc(key)+'" data-chart-type="'+kind+'">'+('<h4>'+esc(title)+'</h4>' if title else '')+content+legend+('<p class="note">'+esc(note)+'</p>' if note else '')+'</article>'


def standard_data_notes(content, meta):
    """Keep the data report's four approved footnotes."""
    import re
    allowed = {
        '注：排名越靠前代表风险越大',
        '注：相关性指基金收益与组合收益的相关系数',
        '注：统计区间为'+str(meta.get('range_start') or '未返回')+'~'+str(meta.get('range_end') or '未返回')+'，基金收益的相关系数',
        STOCK_INDUSTRY_NOTE,
    }
    def retain(match):
        return match.group(0) if html.unescape(match.group(1)) in allowed else ''
    return re.sub(r'<p class="note">(.*?)</p>', retain, content, flags=re.S)


def report_title_dates(report):
    """Resolve actual interface dates; never use request, price or disclosure dates."""
    data = report.get('data', {})
    holding = actual_date(data.get('3', {}).get('holdingDate'))
    result = {'holdings': {'date': holding, 'sources': ['#/data/3/holdingDate'] if holding else [],
                           'reason': None if holding else 'P03未返回有效holdingDate，标题不补日期'}}
    performance = data.get('4', {})
    module_date = actual_date(performance.get('statisticsEndDate'))
    codes = {row['portCode'] for row in holding_rows(data)}
    found, actual_dates, pointers = set(), set(), []
    complete = bool(codes)
    current_windows = {'REVIEW', '1D', '1W', '1M', 'YTD', '1Y'}
    for i, fund in enumerate(performance.get('funds', [])):
        if fund.get('fCode') not in codes:
            continue
        found.add(fund.get('fCode'))
        periods = [(j, p) for j, p in enumerate(fund.get('periods', []))
                   if p.get('periodCode') in current_windows]
        if not periods:
            complete = False
        for j, period in periods:
            actual = actual_date(period.get('statisticsEndDate'))
            if actual:
                actual_dates.add(actual)
                pointers.append('#/data/4/funds/%d/periods/%d/statisticsEndDate' % (i, j))
            else:
                complete = False
    complete = complete and found == codes
    cutoff, sources, reason = None, [], None
    if len(actual_dates) > 1 or (module_date and actual_dates and actual_dates != {module_date}):
        reason = 'P04实际统计日期不一致，不能给出统一业绩截止日期'
    elif module_date:
        cutoff, sources = module_date, ['#/data/4/statisticsEndDate']
    elif complete and len(actual_dates) == 1:
        cutoff, sources = next(iter(actual_dates)), pointers
    else:
        reason = 'P04缺少可确认的统一实际统计日期；endDate、持仓日和估值取价日不作为替代'
    result['performance'] = {'date': cutoff, 'sources': sources, 'actual_dates': sorted(actual_dates),
                             'reason': reason}
    return result


def title_with_cutoff(title, resolved):
    return title + ('（截止' + resolved['date'] + '）' if resolved.get('date') else '')


def doughnut_svg(title, rows):
    """Draw one continuous arc per category and visible outside labels."""
    cx, cy, radius = 260, 115, 75
    theta = -math.pi / 2
    svg = ['<svg viewBox="0 0 520 240" role="img" aria-label="'+esc(title)+'"><circle cx="260" cy="115" r="75" fill="none" stroke="#eef1f3" stroke-width="30"/>']
    labels = {-1: [], 1: []}
    for i, (name, value) in enumerate(rows):
        end = theta + 2 * math.pi * value / 100
        color = COLORS[i % len(COLORS)]
        tip = attr(name+' '+fmt(value, '%'))
        if value >= 100:
            svg.append('<circle cx="260" cy="115" r="75" fill="none" stroke="%s" stroke-width="30" %s/>' % (color, tip))
        elif value > 0:
            svg.append('<path d="M%.3f,%.3f A75,75 0 %s,1 %.3f,%.3f" fill="none" stroke="%s" stroke-width="30" %s/>' % (cx+radius*math.cos(theta), cy+radius*math.sin(theta), int(value > 50), cx+radius*math.cos(end), cy+radius*math.sin(end), color, tip))
        if value > 0:
            mid = (theta+end)/2
            side = 1 if math.cos(mid) >= 0 else -1
            labels[side].append((cy+105*math.sin(mid), mid, name, value, color))
        theta = end
    for side, items in labels.items():
        items.sort(key=lambda item: item[0])
        positions = []
        for desired, *_ in items:
            positions.append(max(18, desired, positions[-1]+28 if positions else 18))
        if positions and positions[-1] > 215:
            positions[-1] = 215
            for i in range(len(positions)-2, -1, -1):
                positions[i] = min(positions[i], positions[i+1]-28)
        for (_, mid, name, value, color), label_y in zip(items, positions):
            x1, y1 = cx+91*math.cos(mid), cy+91*math.sin(mid)
            elbow, label_x = cx+side*108, cx+side*120
            svg.append('<polyline points="%.2f,%.2f %.2f,%.2f %.2f,%.2f" fill="none" stroke="%s"/><text x="%s" y="%.2f" text-anchor="%s">%s %s</text>' % (x1, y1, elbow, label_y, label_x-side*4, label_y, color, label_x, label_y+4, 'start' if side > 0 else 'end', esc(name), fmt(value, '%')))
    return ''.join(svg)


def distribution(key, title, rows, kind='bar', note='', unit='%', emphasize_sign=False, *, label_width=130, wide=False):
    """Configuration charts show labels and hover values, without duplicate tables."""
    rows = [(str(name), numeric(value)) for name, value in rows]
    valid = [(name, value) for name, value in rows if value is not None]
    svg = []
    if valid:
        if kind == 'doughnut' and (any(v < 0 for _, v in valid) or sum(v for _, v in valid) > 100.05):
            kind = 'column'
            note += '；构成不满足环形图条件，柱状图保留原值，不归一化'
        if kind == 'doughnut':
            svg = [doughnut_svg(title, valid)]
            note += '；灰色留白为未列比例，不代表已确认类别' if sum(v for _, v in valid) < 99.95 else ''
        else:
            lo = min(0, min(v for _, v in valid)); hi = max(0, max(v for _, v in valid)); span = hi-lo or 1
            if kind == 'column':
                width = max(520, 80*len(valid)); y = lambda v: 210-(v-lo)/span*160
                plot_left, plot_right = 40, width-15
                step = (plot_right-plot_left)/len(valid)
                bar_width = step*.55
                labels = [axis_label_lines(name, step-14) for name, _ in valid]
                axis_y = 250
                height = axis_y + max(len(label) for label in labels)*14 + 15
                svg = ['<svg viewBox="0 0 %s %s" role="img" aria-label="%s">' % (width, height, esc(title))]
                for v in ticks_with_zero(lo, span, y):
                    tick = y(v)
                    svg.append(grid_tick(v, (plot_left, tick), (plot_right, tick), (plot_left-5, tick+4), unit))
                for i, (name, value) in enumerate(valid):
                    center = plot_left+(i+.5)*step
                    x = center-bar_width/2
                    svg.append('<g %s><rect x="%s" y="%s" width="%s" height="%s" fill="%s"/><text x="%s" y="%s" text-anchor="middle" data-label-role="value">%s</text>%s</g>' % (attr(name+' '+fmt(value,'%')), x, min(y(value), y(0)), bar_width, abs(y(value)-y(0)), COLORS[0], center, y(value)-6 if value>=0 else y(value)+14, fmt(value,'%'), axis_label(center, axis_y, labels[i])))
            else:
                labels = [axis_label_lines(name, 200 if wide else label_width) for name, _ in valid]
                heights = [max(34 if wide else 29, len(label)*14+10) for label in labels]
                height = sum(heights)+20
                plot_left = 220 if wide else label_width + 25
                plot_right = 1160 if wide else 455
                value_x = plot_right + 10
                x = lambda v: plot_left+(v-lo)/span*(plot_right-plot_left)
                width = (1280 if wide else 530) + max(0, len(unit.strip()) - 1) * 11
                svg = ['<svg viewBox="0 0 %s %s" role="img" aria-label="%s">' % (width, height, esc(title))]
                zero = x(0)
                svg.append(grid_tick(0, (zero, 5), (zero, height-15), (zero, height-3), unit, 'middle'))
                top = 5
                for i, (name, value) in enumerate(valid):
                    y = top+(heights[i]-18)/2
                    display = fmt(value, unit)
                    color = LINE_COLORS[1] if emphasize_sign and value < 0 else COLORS[1]
                    svg.append('<g %s>%s<rect x="%s" y="%s" width="%s" height="18" fill="%s"/><text x="%s" y="%s" data-label-role="value">%s</text></g>' % (attr(name+' '+display), axis_label(plot_left-10, top+heights[i]/2-(len(labels[i])-1)*7+4, labels[i], 'end'), min(x(0),x(value)), y, abs(x(value)-x(0)), color, value_x, y+13, esc(display)))
                    top += heights[i]
        svg.append('</svg>')
        if kind == 'doughnut':
            svg.append('<div class="legend">'+''.join('<span><i class="swatch" style="background:'+COLORS[i % len(COLORS)]+'"></i>'+esc(name)+' '+fmt(value,'%')+'</span>' for i,(name,value) in enumerate(valid))+'</div>')
    return chart(key, title, kind, ''.join(svg), note, wide=wide)


def line(rows, benchmark, chart_key='portfolio-trend', title='', show_note=True, *, wide=False):
    rows = sorted(rows, key=lambda r:r['statisticsDate'])
    fields = [('portfolioCumulativeReturnRate','组合',LINE_COLORS[0]), ('comparisonIndexCumulativeReturnRate',benchmark,LINE_COLORS[1])]
    values = [numeric(r.get(k)) for r in rows for k,_,_ in fields if numeric(r.get(k)) is not None]
    if not values:
        return '<p class="note">未取得累计收益走势数据。</p>' if show_note else ''
    days = [date.fromisoformat(r['statisticsDate']).toordinal() for r in rows]
    lo, hi = min(0, min(values)), max(0, max(values)); span = hi-lo or 1
    width = 1280 if wide else 940
    left, right = (68, width-20) if wide else (60, width-60)
    plot_width = right-left
    x = lambda i: left+(days[i]-days[0])/max(1,days[-1]-days[0])*plot_width
    y = lambda v: 225-(v-lo)/span*190
    points_data = [{'x': x(i), 'tip': row['statisticsDate']+'\n'+'\n'.join(name+'：'+fmt(numeric(row.get(key)), '%') for key,name,_ in fields)} for i,row in enumerate(rows)]
    svg = ['<svg viewBox="0 0 %s 265" role="img" aria-label="累计收益走势" data-trend-points="%s">' %
           (width, esc(json.dumps(points_data, ensure_ascii=False)))]
    for v in ticks_with_zero(lo, span, y):
        tick = y(v)
        svg.append(grid_tick(v, (left, tick), (right, tick), (left-10, tick+4), '%'))
    for key,name,color in fields:
        points = []
        for i,row in enumerate(rows):
            value = numeric(row.get(key))
            if value is None:
                if points: svg.append('<polyline points="'+' '.join(points)+'" fill="none" stroke="'+color+'" stroke-width="3"/>'); points=[]
                continue
            points.append('%.2f,%.2f' % (x(i),y(value)))
            svg.append('<circle cx="%s" cy="%s" r="2" fill="%s" %s/>' % (x(i),y(value),color,attr(row['statisticsDate']+' '+name+' '+fmt(value,'%'))))
        if points:svg.append('<polyline points="'+' '.join(points)+'" fill="none" stroke="'+color+'" stroke-width="3"/>')
    svg.append(f'<line data-trend-cursor x1="{left}" x2="{left}" y1="35" y2="225" stroke="#657582" stroke-dasharray="4 3" visibility="hidden" pointer-events="none"/>'
               f'<rect data-trend-hit x="{left}" y="35" width="{plot_width}" height="190" fill="transparent" pointer-events="all" tabindex="0" aria-label="累计收益走势；左右方向键查看日期和收益率"/>'
               f'<text x="{left}" y="252">{esc(rows[0]["statisticsDate"])}</text>'
               f'<text x="{right}" y="252" text-anchor="end">{esc(rows[-1]["statisticsDate"])}</text></svg>')
    legend = '<div class="legend">'+''.join('<span><i class="swatch" style="background:'+color+'"></i>'+esc(name)+'</span>' for _,name,color in fields)+'</div>'
    return chart(chart_key,title,'line',''.join(svg),'实际日期及累计收益，缺失区间断开。' if show_note else '',
                 legend=legend,wide=wide)


def heatmap(rows, names, codes, key='fund-correlation', title='', show_note=True, *, scrollable=False):
    lookup = {(r['fundCode1'],r['fundCode2']):numeric(r.get('fundReturnCorrelation')) for r in rows}
    def label(text):
        escaped = esc(text)
        return f'<span class="correlation-label" title="{escaped}">{escaped}</span>' if scrollable else escaped

    if scrollable:
        count = len(codes)
        many = ' data-many-funds' if count > 10 else ''
        visible = max(1, min(count, 10))
        parts = [f'<div class="correlation-viewport" data-correlation-scroll{many} tabindex="0" role="region" '
                 f'aria-label="组合当前持仓基金两两相关性" style="--fund-count:{count};--visible-funds:{visible}">'
                 '<table class="heat correlation-matrix"><colgroup><col class="correlation-label-column"></colgroup>']
    else:
        parts = ['<div class="table-scroll"><table class="heat">']
    parts.append('<thead><tr><th scope="col">基金</th>' +
                 ''.join(f'<th scope="col">{label(names.get(c,c))}<span>{esc(c)}</span></th>' if scrollable
                         else f'<th scope="col">{label(names.get(c,c))}<br>{esc(c)}</th>' for c in codes) +
                 '</tr></thead><tbody>')
    for a in codes:
        parts.append('<tr><th scope="row">'+label(names.get(a,a)+' '+a)+'</th>')
        for b in codes:
            v = lookup.get((a,b),lookup.get((b,a)))
            bg = '#edf1f4' if v is None else 'rgba(%s,%.3f)' % ('0,87,154' if v>=0 else '172,96,62', .08+min(1,abs(v))*.75)
            parts.append('<td style="background:'+bg+(';color:white' if v is not None and abs(v)>.7 else '')+'" '+attr(names.get(a,a)+' / '+names.get(b,b)+' '+('未返回' if v is None else fmt(v)))+'>'+('未返回' if v is None else fmt(v))+'</td>')
        parts.append('</tr>')
    return chart(key,title,'heatmap',''.join(parts)+'</tbody></table></div>','基金收益两两相关系数；缺失值不填0。' if show_note else '')


def first(row, *keys):
    """Known display aliases only; missing backend fields remain missing."""
    return next((row[k] for k in keys if row.get(k) is not None), None)


def hover_percent(value, unit='%'):
    """Keep the returned numeric precision in allocation bar tooltips."""
    from decimal import Decimal
    text = format(Decimal(str(value)), 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text + unit


def dual_distribution(key, title, rows, kind='column', labels=None, colors=None, unit='%', *, wide=False, label_width=125):
    """BI grouped series, shared by returns and dual-denominator allocation."""
    labels = labels or ['占组合重仓股比例', '占组合净值比例']
    colors = colors or (['#D7AA00', '#27B7D5'] if key == 'six-sector' else ['#27B7D5', '#779BBC'])
    rows = [(str(name), numeric(left), numeric(right)) for name,left,right in rows]
    values = [v for _,*pair in rows for v in pair if v is not None]
    svg = []
    if values:
        lo, hi = min(0, min(values)), max(0, max(values))
        span = hi-lo or 1
        width = (max(1280 if wide else 560, 100*len(rows)) if kind == 'column'
                 else (1280 if wide else 600) + max(0, len(unit.strip()) - 1) * 11)
        plot_left, plot_right = (68 if wide else 45), width-15
        step = (plot_right-plot_left)/max(1,len(rows))
        axis_lines = [axis_label_lines(name, step-14 if kind == 'column' else (200 if wide else label_width)) for name, *_ in rows]
        axis_y = 264
        row_heights = [max(44, len(label)*14+10) for label in axis_lines]
        height = axis_y+max(len(label) for label in axis_lines)*14+(3 if wide else 15) if kind == 'column' else max(200, sum(row_heights)+35)
        svg.append('<svg viewBox="0 0 %s %s" role="img" aria-label="%s">' % (width,height,esc(title)))
        if kind == 'column':
            y = lambda v: 210-(v-lo)/span*160
            bar_pitch = min(60, step*.28) if wide else step*.28
            bar_width = bar_pitch*.9
            group_width = bar_pitch+bar_width
            label_spacing = 18 if wide else 14
            for v in ticks_with_zero(lo, span, y):
                tick = y(v)
                svg.append(grid_tick(v, (plot_left, tick), (plot_right, tick), (plot_left-5, tick+4), unit))
            for i,(name,*pair) in enumerate(rows):
                group_center = plot_left+(i+.5)*step
                left = group_center-group_width/2
                svg.append(axis_label(group_center, axis_y, axis_lines[i]))
                placed = []
                for j,value in enumerate(pair):
                    if value is None:continue
                    x = left+j*bar_pitch
                    text = esc(fmt(value, unit)); center = x+bar_width/2
                    label_y = y(value)-6 if value>=0 else y(value)+14
                    half_width = len(text)*(4.5 if wide else 3)
                    while any(abs(center-px) < half_width+pw+3 and abs(label_y-py) < label_spacing for px,py,pw in placed):
                        label_y += -label_spacing if value>=0 else label_spacing
                    placed.append((center,label_y,half_width))
                    true_height = abs(y(value)-y(0))
                    visible_height = max(2, true_height) if value != 0 else 0
                    bar_y = y(0)-visible_height if value > 0 else y(0)
                    hit_height = max(12, visible_height)
                    hit_y = y(0)-hit_height if value >= 0 else y(0)
                    svg.append('<g data-bar-value="%s" %s><rect data-bar-visible="true" x="%s" y="%s" width="%s" height="%s" fill="%s"/><rect data-bar-hit="true" x="%s" y="%s" width="%s" height="%s" fill="transparent" pointer-events="all"/><text x="%s" y="%s" text-anchor="middle" data-label-role="value">%s</text></g>' % (esc(value),attr(name+' '+labels[j]+' '+hover_percent(value, unit)),x,bar_y,bar_width,visible_height,colors[j],x,hit_y,bar_width,hit_height,center,label_y,text))
        else:
            plot_left = 220 if wide else label_width + 20
            plot_right = 1160 if wide else 510
            value_x = plot_right + 15
            x = lambda v: plot_left+(v-lo)/span*(plot_right-plot_left)
            for v in ticks_with_zero(lo, span, x):
                tick = x(v)
                svg.append(grid_tick(v, (tick, 5), (tick, height-30), (tick, height-10), unit, 'middle'))
            top = 8
            for i,(name,*pair) in enumerate(rows):
                svg.append(axis_label(plot_left-10, top+row_heights[i]/2-(len(axis_lines[i])-1)*7+4, axis_lines[i], 'end'))
                for j,value in enumerate(pair):
                    if value is None:continue
                    y = top+j*15
                    true_width = abs(x(value)-x(0))
                    visible_width = max(2, true_width) if value != 0 else 0
                    bar_x = x(0)-visible_width if value < 0 else x(0)
                    hit_width = max(12, visible_width)
                    hit_x = x(0)-hit_width if value < 0 else x(0)
                    svg.append('<g data-bar-value="%s" %s><rect data-bar-visible="true" x="%s" y="%s" width="%s" height="13" fill="%s"/><rect data-bar-hit="true" x="%s" y="%s" width="%s" height="13" fill="transparent" pointer-events="all"/><text x="%s" y="%s" data-label-role="value">%s</text></g>' % (esc(value),attr(name+' '+labels[j]+' '+hover_percent(value, unit)),bar_x,y,visible_width,colors[j],hit_x,y,hit_width,value_x,y+11,esc(fmt(value, unit))))
                top += row_heights[i]
        svg.append('</svg>')
    legend = '<div class="legend">'+''.join('<span><i class="swatch" style="background:'+color+'"></i>'+esc(label)+'</span>' for color,label in zip(colors,labels))+'</div>'
    return chart(key,title,kind,''.join(svg),legend=legend,wide=wide)


def market_cap_rows(data):
    """Omit only the specified empty sub-50bn bucket; retain nonzero holdings."""
    rows = []
    for key, label in MARKET_CAP.items():
        left, right = data.get(key+'EquityRatio'), data.get(key+'PortfolioRatio')
        if key == 'otherAShareMarketCapBelowCny5bn' and all(numeric(value) in (None, 0) for value in (left, right)):
            continue
        rows.append((label, left, right))
    return rows


def manager_chart(rows, title, note=''):
    """The BI manager view is a stacked column by fund type, not a pie."""
    managers=list(dict.fromkeys(r.get('fundManagement') for r in rows))
    types=list(dict.fromkeys(r.get('fundType1') for r in rows))
    totals={}
    for name in managers:
        values=[numeric(r.get('portfolioHoldingValueRatio')) for r in rows if r.get('fundManagement')==name]
        totals[name]=sum(values) if all(v is not None for v in values) else None
    scale=max([v for v in totals.values() if v is not None]+[1])
    label_room = max(48, max((len(str(kind))*10 for kind in types), default=0))
    slot_width = max(190, 2*(label_room+50))
    width = max(520, slot_width*len(managers)+60)
    plot_left, plot_right = 45, width-15
    step = (plot_right-plot_left)/max(1,len(managers))
    axis_lines = [axis_label_lines(name, step-12) for name in managers]
    axis_y = 240
    svg=['<svg viewBox="0 0 %s %s" role="img" aria-label="%s">' % (width,axis_y+max((len(v) for v in axis_lines),default=1)*14+15,esc(title))]
    for j in range(5):
        v=scale*j/4;y=195-v/scale*165
        svg.append(grid_tick(v, (plot_left, y), (plot_right, y), (plot_left-5, y+4), '%'))
    for i,name in enumerate(managers):
        center = plot_left+(i+.5)*step
        bar_width = min(100, step*.43)
        x = center-bar_width/2
        base=195
        callouts=[]
        for j,kind in enumerate(types):
            values=[numeric(r.get('portfolioHoldingValueRatio')) for r in rows if r.get('fundManagement')==name and r.get('fundType1')==kind]
            if not values or any(v is None for v in values):continue
            value=sum(values);height=value/scale*165;base-=height
            color=COLORS[j%len(COLORS)];mid=base+height/2
            svg.append('<g data-manager-segment="true" %s><rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>' % (attr(str(name)+' '+str(kind)+' '+fmt(value,'%')),x,base,bar_width,height,color))
            if height >= 30:
                foreground='#263746' if color in ('#D7AA00','#B8CDDF','#779BBC') else '#ffffff'
                svg.append('<text x="%s" y="%s" text-anchor="middle" data-label-role="segment" style="fill:%s;font-size:10px"><tspan x="%s">%s</tspan><tspan x="%s" dy="13">%s</tspan></text>' % (center,mid-3,foreground,center,esc(kind),center,fmt(value,'%')))
            else:
                callouts.append((mid,str(kind),value,color))
            svg.append('</g>')
        positions=[]
        for mid,*_ in sorted(callouts):
            positions.append(max(42,mid,positions[-1]+29 if positions else 42))
        if positions and positions[-1]>184:
            positions[-1]=184
            for k in range(len(positions)-2,-1,-1):positions[k]=min(positions[k],positions[k+1]-29)
        for (mid,kind,value,color),label_y in zip(sorted(callouts),positions):
            label_x=x+bar_width+14
            svg.append('<path d="M%s,%s L%s,%s L%s,%s" fill="none" stroke="%s"/><text x="%s" y="%s" data-label-role="segment" style="font-size:10px"><tspan x="%s">%s</tspan><tspan x="%s" dy="13">%s</tspan></text>' % (x+bar_width,mid,label_x-5,label_y,label_x-2,label_y,color,label_x,label_y-3,label_x,esc(kind),label_x,fmt(value,'%')))
        svg.append('<text x="%s" y="%s" text-anchor="middle" data-label-role="value">%s</text>%s' % (center,base-7,fmt(totals[name],'%'),axis_label(center,axis_y,axis_lines[i])))
    svg.append('</svg><div class="legend">'+''.join('<span><i class="swatch" style="background:'+COLORS[i%len(COLORS)]+'"></i>'+esc(kind)+'</span>' for i,kind in enumerate(types))+'</div>')
    return chart('category-5-0',title,'stacked-column',''.join(svg),note)


def rank(row, key, count):
    return str(row[key])+'/'+str(row[count]) if row.get(key) is not None and row.get(count) is not None else '—'


def complete_sum(rows, field):
    values = [numeric(row.get(field)) for row in rows]
    return math.fsum(values) if values and all(value is not None for value in values) else None


def top_industries(rows, system):
    def order(row):
        rank = numeric(row.get('sectorOrder'))
        ratio = numeric(row.get('equityRatioInHoldings'))
        return (rank if rank is not None and rank > 0 else math.inf,
                -ratio if ratio is not None else math.inf)
    return sorted((row for row in rows if row.get('sectorClassificationSystem') == system), key=order)[:5]


def render(report, destination):
    d, m = report['data'], report['meta']
    funds = sorted(holding_rows(d), key=lambda r:numeric(r.get('currentHoldingWeight')) if numeric(r.get('currentHoldingWeight')) is not None else -math.inf, reverse=True)
    if not funds:raise ValueError('缺少有效当前持仓')
    names = {r['portCode']:r.get('fInfoName') or r['portCode'] for r in funds}
    by_code = {r['portCode']:r for r in funds}
    report_period=str(m.get('report_period') or '披露期')
    report_date=str(m.get('report_date') or '未返回')
    disclosure_text='穿透'+report_period+' · '+report_date
    disclosure='（穿透'+report_period+'，'+report_date+'）'
    out = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(m['name'])+' · 组合分析</title><style>'+REPORT_CSS+DATA_REPORT_CSS+'</style></head><body><main><header><button data-print>打印报告</button><h1>'+esc(m['name'])+'持仓风险分析</h1>'+data_description_html(report)+'</header>']
    def heading(text, level=3):out.append('<h%s>%s</h%s>' % (level,esc(text),level))
    def note(text):out.append('<p class="note">'+esc(text)+'</p>')
    def wan(value):return fmt(numeric(value)/10000 if numeric(value) is not None else None)
    value = holding_valuation(d)
    total = value['holdings_total_cny']
    basic_total = value['basic_information_total_cny']
    basic_count = value['basic_information_fund_count']
    basic_available = basic_total is not None or basic_count is not None
    size_date = value['basic_information_date'] if basic_available else value['holding_date']
    same_day = bool(size_date) and size_date == value['holding_date']
    review = next((r for r in report['portfolio_periods'] if r['periodCode']=='REVIEW'),{})
    year = next((r for r in d['8'].get('periods',[]) if r['periodCode']=='1Y'),{})
    year_risk = next((r for r in d['9'].get('periods',[]) if r['periodCode']=='1Y'),{})
    industry_groups=[]
    for system,title,scope in (('\u7533\u4e07一级','申万前五大行业（非QDII）','非QDII'),('GICS一级','GICS前五大行业（QDII）','QDII')):
        industries = top_industries(d['17'].get('items', []), system)
        industry_groups.append({'title':title,'scope':'穿透持仓','denominator':'占股票市值比例','items':[(r.get('sectorName'),fmt(r.get('equityRatioInHoldings'),'%')) for r in industries]})
    overview_total = basic_total if basic_available else total
    if same_day and basic_total is None and basic_count:
        overview_total = total
    overview_count = basic_count if basic_count is not None else len(by_code) if not basic_available or same_day else None
    out.append(overview_cards({'size_wan':wan(overview_total),'fund_count':overview_count,
        'benchmark':(str(m.get('benchmark_name'))+' ('+str(m['benchmark_code'])+')') if m.get('benchmark_name') else m['benchmark_code'],
        'review_return':fmt(review.get('portfolioReturnRate'),'%',signed=True),'year_return':fmt(year.get('portfolioReturnRate'),'%',signed=True),
        'review_period':str(m['range_start'])+' ~ '+str(m['range_end']),'holding_date':size_date or '未返回',
        'performance_date':d['8'].get('statisticsEndDate') or '未返回','risk_date':d['9'].get('statisticsEndDate') or '未返回',
        'risk_metrics':[(label,fmt(year_risk.get(key),unit)) for key,label,unit in [('portfolioAnnualizedVolatility','年化波动率','%'),('portfolioMaxDrawdown','最大回撤','%'),('portfolioSharpeRatio','Sharpe（年化）',''),('portfolioBeta','Beta','')]],
        'disclosure':disclosure_text, 'equity':fmt(d['15'].get('equityRatio'),'%'),
        'regions':[(label,fmt(d['15'].get(key),'%')) for key,label in [('aShareRatio','A股'),('hongKongEquityRatio','港股'),('usEquityRatio','美股')]],
        'industry_groups':industry_groups}))
    heading('持仓单只基金情况',2)
    title_dates = report_title_dates(report)
    heading(title_with_cutoff('1、组合当前持仓基金明细', title_dates['holdings']))
    headers = ['基金代码','基金名称','成立日期','基金经理','基金细分类型','持有份额','价格','估值取价日期','持仓市值(万)','持仓占比%','风格标签','赛道标签']
    rows = [[r['portCode'],names[r['portCode']],r.get('fInfoSetupDate'),r.get('fundManagerName'),r.get('fundSubtype'),fmt(r.get('heldFundShares')),format(numeric(r['fundPrice']),'.4f') if numeric(r.get('fundPrice')) is not None else '—',r.get('valuationPriceDate') or '未返回',wan(r.get('holdingMarketValue')),fmt(r.get('currentHoldingWeight')),r.get('styleLabel'),r.get('investmentThemeLabel')] for r in funds]
    rows.append(['基金组合','','','','','','','',wan(total),fmt(complete_sum(funds, 'currentHoldingWeight')) if len(by_code) == len(funds) else '—','',''])
    out.append(table(headers,rows,True))
    fp = {r['fCode']:r for r in d['4'].get('funds',[])};fr = {r['fCode']:r for r in d['5'].get('funds',[])}
    available_periods = []
    for fund in funds:
        for p in fp.get(fund['portCode'],{}).get('periods',[]):
            if p['periodCode'] not in [q['periodCode'] for q in available_periods]:available_periods.append(p)
    order = ['REVIEW','1D','1W','1M','YTD','1Y']
    prior_year=str(int(m['range_end'][:4])-1)
    period_names=['回顾期','过去一日','过去一周','过去一月','今年以来','过去一年']
    periods=[dict(next((p for p in available_periods if p['periodCode']==code),{'periodCode':code}),periodName=name) for code,name in zip(order,period_names)]
    periods.append(next((p for p in available_periods if str(p.get('calendarYear'))==prior_year),{'periodCode':prior_year,'calendarYear':int(prior_year)}))
    heading(title_with_cutoff('2、组合当前持仓基金业绩表现', title_dates['performance']))
    headers = ['基金代码','基金名称','持仓市值(万)'];groups=[('',3)]
    for p in periods:
        columns=['收益率%'] if p['periodCode']=='REVIEW' else ['收益率%','排名']
        headers.extend(columns);groups.append((str(p.get('calendarYear') or p.get('periodName') or p['periodCode']),len(columns)))
    rows=[]
    for fund in funds:
        lookup={p['periodCode']:p for p in fp.get(fund['portCode'],{}).get('periods',[])}
        row=[fund['portCode'],names[fund['portCode']],wan(fund.get('holdingMarketValue'))]
        for p in periods:
            q=lookup.get(p['periodCode'],{});row.append(fmt(q.get('fundReturn')))
            if p['periodCode']!='REVIEW':row.append(rank(q,'returnRank','returnRankCount'))
        rows.append(row)
    row=['基金组合','',wan(total)]
    for p in periods:
        q=next((q for q in d['8'].get('periods',[]) if q['periodCode']==p['periodCode']),{});row.append(fmt(q.get('portfolioReturnRate')))
        if p['periodCode']!='REVIEW':row.append('—')
    rows.append(row);out.append(table(headers,rows,True,groups))
    heading('3、组合当前持仓基金风险情况（过去1年）')
    risk_fields=[('stdardDev','波动率%','stdardDevRank','stdardDevRankCount'),('sharpe','Sharpe（年化）','sharpeRank','sharpeRankCount'),('beta','Beta','betaPeerRank','betaPeerCount'),('maxDown','最大回撤%','maxDownRank','maxDownRankCount')]
    rows=[]
    for fund in funds:
        q=next((p for p in fr.get(fund['portCode'],{}).get('periods',[]) if p['periodCode']=='1Y'),{})
        row=[fund['portCode'],names[fund['portCode']],wan(fund.get('holdingMarketValue'))]
        for k,_,rk,rc in risk_fields:row.extend([fmt(q.get(k)),rank(q,rk,rc)])
        rows.append(row)
    row=['基金组合','',wan(total)]
    for k in ('portfolioAnnualizedVolatility','portfolioSharpeRatio','portfolioBeta','portfolioMaxDrawdown'):row.extend([fmt(year_risk.get(k)),'—'])
    rows.append(row);out.append(table(['基金代码','基金名称','持仓市值(万)']+[h for _,label,_,_ in risk_fields for h in (label,label.replace('%','')+'排名')],rows,True));note('注：排名越靠前代表风险越大')
    heading('4、组合当前持仓基金资产配置'+disclosure)
    allocations={r['portCode']:r for r in d['6'].get('items',[])}
    fields=[('equityRatio','股票仓位')]+list(REGIONS.items())+[(k,v) for k,v in ASSETS.items() if k!='equityRatio']
    rows=[[r['portCode'],names[r['portCode']],wan(r.get('holdingMarketValue'))]+[fmt(allocations.get(r['portCode'],{}).get(k.replace('Ratio','AllocationRatio'))) for k,_ in fields] for r in funds]
    rows.append(['基金组合','',wan(total)]+[fmt(d['15'].get(k)) for k,_ in fields]);out.append(table(['基金代码','基金名称','持仓市值(万)']+[v+'%' for _,v in fields],rows,True))
    sectors={r['portCode']:r for r in d['7'].get('items',[])}
    sector_keys=SECTOR_KEYS
    summary_groups = industry_group_summaries(d['7'])
    summary_groups.update(report.get('industry_group_summaries') or {})
    for index,system,label,total_label in [(5,'\u7533\u4e07一级','非QDII','不含QDII'),(6,'GICS一级','QDII','仅QDII')]:
        heading(str(index)+'、组合当前持仓基金（'+label+'）行业板块配置'+disclosure)
        rows=[]
        for fund in funds:
            q=sectors.get(fund['portCode'],{})
            if q.get('top5SectorClassificationSystem') != system:continue
            rows.append([fund['portCode'],names[fund['portCode']],wan(fund.get('holdingMarketValue')),fmt(q.get('sixSectorEquityNavRatio'))]+[fmt(q.get(k+'EquityValueRatio')) for k in sector_keys]+[(str(q.get('top'+str(i)+'SectorName'))+' '+fmt(q.get('top'+str(i)+'SectorAllocationRatio'),'%')) if q.get('top'+str(i)+'SectorName') else '—' for i in range(1,6)])
        summary = summary_groups.get(system)
        if summary:
            industries = d['17']
            group_date = actual_date(summary.get('holdingDate'))
            leaders = (top_industries(industries.get('items') or [], system)
                       if group_date and industries.get('holdingDate') == group_date else [])
            top_five = [row['sectorName']+' '+fmt(row.get('equityRatioInHoldings'),'%')
                        for row in leaders if row.get('sectorName')]
            rows.append(['','基金组合（'+total_label+'）',wan(summary['holdingMarketValue']),
                         fmt(summary['sixSectorEquityNavRatio'])]
                        + [fmt(summary.get(key+'EquityRatio')) for key in sector_keys]
                        + top_five + ['—'] * (5-len(top_five)))
        industry_system='申万一级' if index==5 else 'GICS'
        out.append(table(['基金代码','基金名称','持仓市值(万)','股票六大行业板块占净值比例%']+[SECTORS[k]+'%' for k in sector_keys]+['第'+str(i)+'大行业' for i in range(1,6)],rows,total=bool(summary),groups=[('',4),('股票六大行业板块配置占股票市值比例',6),('股票'+industry_system+'行业配置占股票市值比例',5)]))
    out.append('<h2 class="major">组合业绩风险分析</h2>')
    heading('一、业绩与风险情况',2)
    heading('1、组合累计收益率走势');out.append(line(d['10'].get('series',[]),m.get('benchmark_name') or m['benchmark_code'],wide=True))
    heading('2、组合历史业绩表现')
    window_order=['REVIEW','YTD','1M','1Y','3Y']
    ps=sorted([p for p in d['8'].get('periods',[]) if p['periodCode'] in window_order],key=lambda p:window_order.index(p['periodCode']))
    out.append(table(['指标']+[str(p.get('calendarYear') or p.get('periodName'))+'%' for p in ps],[[label]+[fmt(p.get(k)) for p in ps] for k,label in [('portfolioReturnRate','组合收益率%'),('comparisonIndexReturnRate','对比指数收益率%'),('portfolioExcessReturnRate','超额收益率%')]]))
    out.append(dual_distribution('historical-returns','收益率情况',[(p.get('periodName'),p.get('portfolioReturnRate'),p.get('comparisonIndexReturnRate')) for p in ps],labels=['组合收益率','对比指数('+str(m.get('benchmark_name') or m['benchmark_code'])+')收益率'],colors=['#00579A','#27B7D5'],wide=True))
    heading('3、组合历史持仓基金业绩贡献（回顾期）')
    rows=[]
    for r in sorted(report['contributions_percent'],key=lambda r:numeric(r.get('fundReturnContribution')) if numeric(r.get('fundReturnContribution')) is not None else -math.inf,reverse=True):
        fund=by_code.get(r['fundCode'],{})
        rows.append([r['fundCode'],r['fundName'],first(r,'fundSubtype','fundType') or fund.get('fundSubtype'),first(r,'styleLabel','investmentStyleLabel') or fund.get('styleLabel'),r.get('investmentThemeLabel') or fund.get('investmentThemeLabel')]+[fmt(r.get(k)) for k in ('currentHoldingWeight','holdingPeriodAverageWeight','averageConsecutiveHoldingDays','holdingPeriodFundReturnRate','fundReturnContribution')])
    rows.append(['组合合计']+['']*8+[fmt(complete_sum(report['contributions_percent'], 'fundReturnContribution'))]);out.append(table(['基金代码','基金名称','基金类型','风格标签','赛道标签','当前权重%','平均权重%','平均持有天数','持有期收益率%','收益贡献%'],rows,True))
    heading('4、组合历史风险情况')
    ps=sorted([p for p in d['9'].get('periods',[]) if p['periodCode'] in window_order],key=lambda p:window_order.index(p['periodCode']))
    out.append(table(['指标']+[str(p.get('periodName')) for p in ps],[[label]+[fmt(p.get(k),'%' if k!='portfolioSharpeRatio' else '') for p in ps] for k,label in [('portfolioAnnualizedVolatility','波动率%'),('portfolioSharpeRatio','Sharpe（年化）'),('portfolioMaxDrawdown','最大回撤%')]]))
    heading('二、组合风险分析',2)
    heading('1、当前持仓基金与组合的相关性和风险分析（过去1年）')
    keys=['fundPortfolioReturnCorrelation','currentHoldingWeight','backtestFundAnnualizedVolatility','backtestFundMaxDrawdown','fundQuarterlyVar','fundAnnualizedRiskContribution','fundMarginalRiskContribution']
    risk_rows = [r for r in (d['12'].get('items') or []) if r.get('fundCode')]
    rows=[[r['fundCode'],r.get('fundName') or names.get(r['fundCode']),r.get('fundManagerName') or by_code.get(r['fundCode'],{}).get('fundManagerName')]+[('未返回' if k=='fundPortfolioReturnCorrelation' and numeric(r.get(k)) is None else fmt(r.get(k))) for k in keys] for r in risk_rows]
    summary=d['12'].get('summary') or {}
    risk_codes = {r['fundCode'] for r in risk_rows}
    complete_risk = risk_codes == set(by_code) and len(risk_codes) == len(risk_rows)
    total_weight = complete_sum(risk_rows, 'currentHoldingWeight') if complete_risk else None
    total_risk_contribution = complete_sum(risk_rows, 'fundAnnualizedRiskContribution') if complete_risk else None
    rows.append(['组合风险测算结果','','','—',fmt(total_weight),fmt(summary.get('backtestPortfolioAnnualizedVolatility')),fmt(summary.get('backtestPortfolioMaxDrawdown')),fmt(summary.get('portfolioQuarterlyVar')),fmt(total_risk_contribution),'—'])
    out.append(table(['基金代码','基金名称','基金经理','与组合相关性','当前权重%','波动率%','最大回撤%','季度VaR%','年化波动率贡献%','边际风险贡献%'],rows,True))
    note('注：相关性指基金收益与组合收益的相关系数')
    codes=[r['portCode'] for r in funds]
    heading('2、组合当前持仓基金两两相关性')
    out.append(heatmap(d['13'].get('items') or [], names, codes, scrollable=True))
    note('注：统计区间为'+str(m.get('range_start') or '未返回')+'~'+str(m.get('range_end') or '未返回')+'，基金收益的相关系数')
    heading('三、组合当前资产配置情况',2)
    out.append('<div class="chart-grid allocation-grid" data-chart-grid="two-columns">')
    classification=d['14'].get('items',[])
    specs=[('fundType1','基金类型','doughnut','基金类型'),('fundType2','基金细分类型','column','基金细分类型'),('investmentThemeLabel','权益基金赛道','column','权益基金赛道'),('investmentStyleLabel','权益基金风格','column','权益基金风格'),('fundManagement','基金管理人','stacked-column','管理人')]
    for i,(field,title,kind,method) in enumerate(specs,1):
        selected=[row for row in classification if row.get('classificationMethod')==method]
        if field=='fundManagement':
            out.append(manager_chart(selected,'5、组合持仓基金管理人情况（截至'+str(m.get('snapshot_date') or '未返回')+'）'))
            continue
        groups={}
        for row in selected:
            if row.get(field) is not None:
                group=(row.get('classificationMethod'),row.get('statisticsScope'),row.get('ratioDenominatorDescription'))
                groups.setdefault(group,[]).append((row[field],row.get('portfolioHoldingValueRatio')))
        if not groups:groups={('','',''):[]}
        for j,(group,items) in enumerate(groups.items()):
            out.append(distribution('category-'+str(i)+'-'+str(j),str(i)+'、组合持仓'+title+'分布（截至'+str(m.get('snapshot_date') or '未返回')+'）',items,kind))
    out.append(distribution('asset-allocation','6、组合大类资产配置情况'+disclosure,[(v,d['15'].get(k)) for k,v in ASSETS.items()]+[(v,d['15'].get(k)) for k,v in REGIONS.items()],'bar',label_width=84))
    out.append(dual_distribution('six-sector','7、组合股票行业配置情况'+disclosure,[(SECTORS[k],d['16'].get(k+'EquityRatio'),d['16'].get(k+'PortfolioRatio')) for k in sector_keys]))
    out.append(dual_distribution('market-cap','8、组合持仓指数成分分布'+disclosure,market_cap_rows(d['18'])))
    for i,system,key in [(9,'\u7533\u4e07一级','sw'),(10,'GICS一级','gics')]:
        items = top_industries(d['17'].get('items', []), system)
        title = ('9、组合持股申万一级行业分布（不含QDII，穿透'+report_period+'，'+report_date+'，前5大）' if i==9 else '10、组合持仓QDII基金GICS行业分布（穿透'+report_period+'，'+report_date+'，前5大）')
        out.append(dual_distribution('industry-'+key,title,[(r['sectorName'],r.get('equityRatioInHoldings'),r.get('portfolioRatio')) for r in items],'bar',label_width=84))
    out.append('</div>')
    heading('11、前50大持仓股票（穿透'+report_period+'，截至'+report_date+'）')
    stocks=sorted(d['19'].get('items',[]),key=lambda r:numeric(r.get('portfolioRatio')) if numeric(r.get('portfolioRatio')) is not None else -math.inf,reverse=True)
    def stock_rows(items,start=1):return [[i,r.get('iCode'),r.get('sCName'),fmt(r.get('lookthroughHoldingMarketValue')),fmt(r.get('lookthroughEquityRatio')),fmt(r.get('portfolioRatio')),fmt(r.get('stockReturnRateYtd')),fmt(r.get('stockTotalMv')),fmt(r.get('stockPeTtm')),r.get('stockRegion'),r.get('sector6'),stock_industry_label(r)] for i,r in enumerate(items,start)]
    headers=['序号','股票代码','股票名称','组合持股市值（元）','占组合重仓股比例（%）','占组合净值比例（%）','今年以来涨跌幅（%）','个股总市值（亿元）','个股P/E','所属地区','行业板块','申万一级行业/GICS一级行业']
    out.append(stock_table(headers,stock_rows(stocks[:50])));note(STOCK_INDUSTRY_NOTE)
    out.append(disclaimer_html()+'</main><div id="tooltip" role="status"></div><script>'+REPORT_JS+DATA_REPORT_JS+'</script></body></html>')
    Path(destination).write_text(public_text(standard_data_notes(''.join(out), m)),encoding='utf-8')
    return destination


def stock_industry_label(row):
    """Support both documented P19 field layouts without altering raw evidence."""
    names = [str(row[key]) for key in ('industrySw1', 'industryGics1') if row.get(key)]
    return '；'.join(names) or str(row.get('industryName') or '—')


def check(path, data):
    """Validate BI order and chart types, without requiring redundant graphs."""
    from html.parser import HTMLParser
    class Audit(HTMLParser):
        def __init__(self):super().__init__();self.charts={};self.errors=[];self.tables=0;self.targets=0;self.trend_hit=False;self.trend_points=[]
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag in {'iframe','object','embed'}:self.errors.append('禁止嵌入外部对象')
            if tag in {'script','img','link'} and (a.get('src') or a.get('href')):self.errors.append('不能依赖外部资源')
            if any(k.lower().startswith('on') for k in a):self.errors.append('禁止内联事件属性')
            if any(str(v).lower().startswith('javascript:') for v in a.values()):self.errors.append('禁止javascript伪协议')
            if a.get('data-chart-key'):self.charts[a['data-chart-key']]=a.get('data-chart-type')
            if tag=='table':self.tables+=1
            if a.get('data-tip'):self.targets+=1
            if 'data-trend-hit' in a:self.trend_hit=True
            if 'data-trend-points' in a:
                try:self.trend_points=json.loads(a['data-trend-points'])
                except (ValueError,TypeError):self.errors.append('累计收益悬浮数据格式错误')
    content=Path(path).read_text(encoding='utf-8');audit=Audit();audit.feed(content)
    if '<!doctype html>' not in content.lower():audit.errors.append('缺少完整HTML')
    titles=['基金组合概况','持仓单只基金情况','组合业绩风险分析','一、业绩与风险情况','二、组合风险分析','三、组合当前资产配置情况','11、前50大持仓股票','免责声明与风险提示']
    positions=[content.find(t) for t in titles]
    if any(p<0 for p in positions) or positions!=sorted(positions):audit.errors.append('BI章节缺失或顺序错误')
    if audit.tables<12:audit.errors.append('缺少可见明细表')
    if content.count('data-overview-card=')!=6:audit.errors.append('缺少六张组合概况卡片')
    if 'data-chart-grid="two-columns"' not in content:audit.errors.append('缺少配置区两列布局')
    for key,kind in audit.charts.items():
        expected='doughnut' if key.startswith('category-1-') else 'stacked-column' if key.startswith('category-5-') else 'column' if key.startswith(('category-','six-sector','market-cap','historical-returns')) else 'line' if key=='portfolio-trend' else 'heatmap' if key.startswith('fund-correlation') else 'bar'
        if kind!=expected and not (key.startswith('category-1-') and kind=='column'):audit.errors.append('图形类型不符：'+key)
    if data['data']['10'].get('series') and 'portfolio-trend' not in audit.charts:audit.errors.append('缺少累计收益折线图')
    if 'portfolio-trend' in audit.charts and (not audit.trend_hit or not audit.trend_points):audit.errors.append('缺少累计收益绘图区悬浮提示')
    if 'historical-returns' not in audit.charts:audit.errors.append('缺少历史收益率分组柱状图')
    config=content[content.find('data-chart-grid="two-columns"'):content.find('11、前50大持仓股票')]
    if '<table' in config:audit.errors.append('配置图下不应重复展示数值表')
    expected_categories = 1 + sum(max(1, len({(row.get('classificationMethod'), row.get('statisticsScope'), row.get('ratioDenominatorDescription')) for row in data['data']['14'].get('items', []) if row.get('classificationMethod') == method and row.get(field) is not None})) for field, method in [('fundType1', '基金类型'), ('fundType2', '基金细分类型'), ('investmentThemeLabel', '权益基金赛道'), ('investmentStyleLabel', '权益基金风格')])
    if config.count('data-chart-key=')!=expected_categories+5:audit.errors.append('配置区图数与返回分类口径不符')
    if not all(label in content for label in ('基金经理','股票六大行业板块占净值比例%')):audit.errors.append('缺少BI固定列名')
    for key in ('six-sector','market-cap','industry-sw','industry-gics'):
        start=content.find('data-chart-key="'+key+'"')
        section=content[start:content.find('</article>',start)] if start>=0 else ''
        if not all(label in section for label in ('占组合重仓股比例','占组合净值比例')):audit.errors.append('配置图缺少双口径系列：'+key)
    return {'errors':audit.errors,'chart_count':len(audit.charts),'table_count':audit.tables,'interactive_targets':audit.targets,'notices':data.get('warnings',[]),'title_dates':report_title_dates(data),'browser_verified':False}


def _safe_name(text):
    import re
    return re.sub(r'[\\/:*?"<>|]+','_',str(text)).strip() or '组合分析'


def generate(report, destination):
    """Render and validate the data-only BI report."""
    destination=Path(destination)
    if destination.exists():
        raise ValueError('输出文件已存在，请使用新文件名：'+str(destination))
    destination.parent.mkdir(parents=True,exist_ok=True)
    render(report,destination)
    return check(destination,report)
