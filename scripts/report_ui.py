"""Presentation-only widgets. Input cells are already formatted by each backend."""
import html
import math

OVERVIEW_CSS = '''
.overview-section{background:white;padding:0;margin:24px 0;color:#263746}
.overview-section>.overview-title{border-bottom:2px solid #00579A;color:#00579A;font-size:20px;margin:26px 0 14px;padding:5px 0}
.overview-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px 18px}
.overview-card{background:#f8fbfd;border:1px solid #cbd9e1;border-top:3px solid #00579A;padding:12px 15px;min-width:0;break-inside:avoid}
.overview-card-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:10px}
.overview-card-heading h3{margin:0;color:#00579A;font-size:15px;line-height:1.45}.overview-tag,.overview-muted{color:#657582;font-size:11px}
.overview-tag{white-space:nowrap}.overview-label{display:block;color:#657582;font-size:12px;margin-bottom:4px}
.overview-main{font-size:24px;font-weight:700;line-height:1.35;color:#00579A;overflow-wrap:anywhere}.overview-unit{font-size:12px;font-weight:400;margin-left:3px}
.overview-divider{border-top:1px solid #dfe7ed;margin:12px 0 10px}.overview-foot{display:grid;grid-template-columns:1fr 1.7fr;gap:12px;align-items:start}
.overview-count{font-size:18px;color:#00579A}.overview-benchmark{font-size:12px;overflow-wrap:anywhere}.overview-period{margin-top:10px;color:#657582;font-size:11px}
.overview-return-positive,.overview-return-negative,.overview-return-neutral{color:#00579A}
.overview-inline{display:flex;justify-content:space-between;align-items:center;gap:10px}.overview-inline .overview-label{margin:0}.overview-year{font-size:18px;font-weight:700}
.overview-risk-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 16px}.overview-risk-value{font-size:18px;font-weight:700;line-height:1.4;color:#00579A}.overview-risk-value .overview-unit{font-size:12px}
.overview-heading{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:18px 0 10px}.overview-heading h3{margin:0;color:#00579A;font-size:15px}.overview-heading .overview-muted{text-align:right}
.overview-allocation .overview-inline{margin:10px 0}.overview-equity{font-size:22px;font-weight:700;color:#00579A}.overview-section .overview-bar{display:none}
.overview-regions{margin-top:12px}.overview-regions .overview-inline{margin:8px 0;font-size:12px}
.overview-industry-denominator{margin-top:-4px;margin-bottom:8px}.overview-industry-row{margin:7px 0}.overview-industry-line{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:12px}
.overview-industry-name{min-width:0;overflow-wrap:anywhere}.overview-industry-rank{color:#657582;font-size:11px;margin-right:8px}.overview-empty{color:#657582;padding:12px 0;font-size:12px}
@media(max-width:1050px){.overview-grid{grid-template-columns:1fr}}
@media(max-width:760px){.overview-heading{align-items:flex-start;flex-direction:column}.overview-heading .overview-muted{text-align:left}}
@media print{.overview-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.overview-card{padding:10px 12px}.overview-main{font-size:22px}.overview-risk-value{font-size:17px}}
'''


def overview_cards(data):
    """Compact report-style overview consumes display values, not backend contracts."""
    def number(value, unit=''):
        text = str(value if value is not None else '—')
        if text == '—': return '—'
        if text.endswith('%'):
            text, unit = text[:-1], '%'
        return esc(text) + ('<span class="overview-unit">' + esc(unit) + '</span>' if unit else '')

    def return_class(value):
        n = display_number(value)
        return 'overview-return-positive' if n is not None and n > 0 else 'overview-return-negative' if n is not None and n < 0 else 'overview-return-neutral'

    def bar(value):
        n = display_number(value)
        if n is None: return ''
        return '<div class="overview-bar" aria-hidden="true"><div class="overview-bar-fill" style="width:%.4f%%"></div></div>' % min(100, max(0, n))

    def card(title, tag, key, extra=''):
        return '<article class="overview-card ' + extra + '" data-overview-card="' + key + '"><div class="overview-card-heading"><h3>' + esc(title) + '</h3><span class="overview-tag">' + esc(tag) + '</span></div>'

    parts = ['<section class="overview-section" data-overview-cards><h2 class="overview-title">基金组合概况</h2><div class="overview-grid">']
    parts.append(card('组合基本信息', '当前持仓', 'size'))
    parts.append('<span class="overview-label">持仓市值</span><div class="overview-main">' + number(data['size_wan'], '万元') + '</div><div class="overview-divider"></div><div class="overview-foot"><div><span class="overview-label">持有基金</span><div class="overview-count">' + number(data['fund_count'], '只') + '</div></div><div><span class="overview-label">对比基准</span><div class="overview-benchmark">' + esc(data['benchmark']) + '</div></div></div><div class="overview-period">持仓截至 ' + esc(data['holding_date']) + '</div></article>')
    parts.append(card('收益表现', '回顾期', 'performance'))
    parts.append('<div class="overview-main ' + return_class(data['review_return']) + '">' + number(data['review_return']) + '</div><div class="overview-period">' + esc(data['review_period']) + '</div><div class="overview-divider"></div>')
    parts.append('<div class="overview-inline overview-performance-row"><span class="overview-main ' + return_class(data['year_return']) + '">' + number(data['year_return']) + '</span><span class="overview-label">过去一年</span></div><div class="overview-period">业绩截至 ' + esc(data['performance_date']) + '</div>')
    parts.append('</article>')
    parts.append(card('组合业绩风险情况（过去1年）', '', 'risk') + '<div class="overview-risk-grid">')
    for label, value in data['risk_metrics']:
        parts.append('<div><span class="overview-label">' + esc(label) + '</span><div class="overview-risk-value">' + number(value) + '</div></div>')
    parts.append('</div><div class="overview-period">风险截至 ' + esc(data['risk_date']) + '</div></article></div>')
    parts.append('<div class="overview-heading"><h3>组合配置情况（' + esc(str(data['disclosure']).replace(' · ', '，')) + '）</h3></div><div class="overview-grid">')
    parts.append(card('股票配置', '穿透持仓', 'allocation', 'overview-allocation'))
    parts.append('<div class="overview-inline"><span class="overview-label">股票仓位</span><span class="overview-equity">' + number(data['equity']) + '</span></div>' + bar(data['equity']) + '<div class="overview-regions">')
    for label, value in data['regions']:
        parts.append('<div class="overview-inline"><span class="overview-label">' + esc(label) + '</span><span>' + number(value) + '</span></div>')
    parts.append('</div></article>')
    for index, group in enumerate(data['industry_groups']):
        parts.append(card(group['title'], group['scope'], 'industry-sw' if index == 0 else 'industry-gics', 'overview-gics' if index else ''))
        parts.append('<div class="overview-muted overview-industry-denominator">' + esc(group['denominator']) + '</div>')
        if not group['items']:
            parts.append('<div class="overview-empty">—</div>')
        for rank, (name, value) in enumerate(group['items'], 1):
            parts.append('<div class="overview-industry-row"><div class="overview-industry-line"><span class="overview-industry-name"><span class="overview-industry-rank">%02d</span>%s</span><span>%s</span></div>%s</div>' % (rank, esc(name), number(value), bar(value)))
        parts.append('</article>')
    parts.append('</div></section>')
    return ''.join(parts)

STOCK_CSS = '''
.stock-panel{margin:12px 0}.stock-table{min-width:1180px;font-size:12px}
.stock-table thead th{background:#00579A;color:white;border:0;border-bottom:1px solid #e3e9ed;padding:6px 7px;text-align:right;font-weight:600;line-height:1.4}
.stock-table tbody td{text-align:right;padding:6px 7px;border-bottom:1px solid #e3e9ed}
.stock-table tbody tr:nth-child(even){background:#f3f5f6}
.stock-table th:nth-child(2),.stock-table th:nth-child(3),.stock-table th:nth-child(n+10),.stock-table td:nth-child(2),.stock-table td:nth-child(3),.stock-table td:nth-child(n+10){text-align:left}
.stock-table th:first-child,.stock-table td:first-child{text-align:right}
.stock-table .stock-cell{min-width:0}.stock-value{display:block;white-space:nowrap;color:inherit}.stock-mini-track{display:none}
.stock-pager{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin:10px 0 7px;color:#657582;font-size:12px}
.stock-pager[hidden]{display:none}.stock-pager-group{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.stock-pager button{float:none;border:1px solid #cbd9e1;background:white;color:#00579A;padding:5px 12px;font:inherit;cursor:pointer}
.stock-pager button:disabled{color:#a5afb7;cursor:default}.stock-pager input{width:60px;box-sizing:border-box;border:1px solid #cbd9e1;padding:5px 7px;font:inherit;color:#263746}
.stock-sort{float:none;border:0;background:transparent;padding:0 3px;color:#d5e6f2;font:inherit;cursor:pointer}.stock-sort:focus-visible,.stock-pager button:focus-visible,.stock-pager input:focus-visible{outline:2px solid #00579A;outline-offset:2px}
.stock-sort:focus-visible{outline-color:white}.stock-table th[aria-sort="ascending"] .stock-sort,.stock-table th[aria-sort="descending"] .stock-sort{color:white;font-weight:700}
@media(max-width:760px){.stock-table{font-size:11px}.stock-table tbody td,.stock-table thead th{padding:5px}}
@media print{.stock-table tbody tr[hidden]{display:table-row!important}.stock-pager,.stock-sort{display:none!important}.stock-table{min-width:0;font-size:9px}.stock-table tbody td,.stock-table thead th{padding:4px}}
'''

STOCK_JS = '''(()=>{
document.querySelectorAll('[data-stock-pagination]').forEach(panel=>{
const body=panel.querySelector('tbody'),rows=Array.from(body.querySelectorAll('[data-stock-row]'));
const controls=panel.querySelector('.stock-pager'),input=controls.querySelector('[data-page-size]');
const range=controls.querySelector('[data-stock-range]'),status=controls.querySelector('[data-stock-page]');
const previous=controls.querySelector('[data-stock-prev]'),next=controls.querySelector('[data-stock-next]');
let size=10,page=0,sortColumn=null,ascending=true;
function update(){const pages=Math.max(1,Math.ceil(rows.length/size));page=Math.max(0,Math.min(page,pages-1));
rows.forEach((row,i)=>{row.hidden=i<page*size||i>=(page+1)*size});
range.textContent=(rows.length?page*size+1:0)+'–'+Math.min((page+1)*size,rows.length)+' / 共 '+rows.length+' 只';
status.textContent='第 '+(page+1)+' / '+pages+' 页';previous.disabled=page===0;next.disabled=page===pages-1;}
function apply(){const value=Number(input.value);if(!Number.isInteger(value)||value<1||value>50){input.setCustomValidity('请输入1至50之间的整数');input.reportValidity();return}
input.setCustomValidity('');size=value;page=0;update();}
input.addEventListener('input',()=>input.setCustomValidity(''));
input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();apply()}});
controls.querySelector('[data-stock-apply]').addEventListener('click',apply);
previous.addEventListener('click',()=>{page--;update()});next.addEventListener('click',()=>{page++;update()});
panel.querySelectorAll('[data-stock-sort]').forEach(button=>button.addEventListener('click',()=>{
const column=Number(button.dataset.stockSort);ascending=sortColumn===column?!ascending:true;sortColumn=column;
rows.sort((left,right)=>{const a=left.children[column].dataset.sortValue,b=right.children[column].dataset.sortValue;
if(a===''&&b==='')return Number(left.dataset.stockRow)-Number(right.dataset.stockRow);
if(a==='')return 1;if(b==='')return -1;
const difference=Number(a)-Number(b);return difference?(ascending?difference:-difference):Number(left.dataset.stockRow)-Number(right.dataset.stockRow)});
rows.forEach(row=>body.appendChild(row));panel.querySelectorAll('thead th').forEach(th=>th.removeAttribute('aria-sort'));
button.closest('th').setAttribute('aria-sort',ascending?'ascending':'descending');page=0;update();}));
controls.hidden=false;update();
});})();'''


def esc(value):
    return html.escape(str(value if value is not None else '—'), quote=True)


def display_number(value):
    try:
        number = float(str(value).replace(',', '').replace('%', ''))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def stock_table(headers, rows):
    """Keep all top-50 rows in the HTML; browser pagination never fetches data."""
    if any(len(row) != len(headers) for row in rows):
        raise ValueError('股票表行列数不一致')
    numeric_columns = {0, 3, 4, 5, 6, 7, 8}
    sortable_columns = {0, 3, 7, 8}
    returns = [abs(display_number(row[6])) for row in rows if display_number(row[6]) is not None]
    return_scale = max(returns + [1])
    parts = ['<div class="stock-panel" data-stock-pagination><div class="table-scroll"><table class="stock-table"><thead><tr>']
    for index, name in enumerate(headers):
        parts.append('<th scope="col"><span>' + esc(name) + '</span>')
        if index in sortable_columns:
            parts.append('<button type="button" class="stock-sort" data-stock-sort="%d" aria-label="按%s排序">↕</button>' % (index, esc(name)))
        parts.append('</th>')
    parts.append('</tr></thead><tbody>')
    for index, row in enumerate(rows):
        parts.append('<tr data-stock-row="%d">' % index)
        for column, value in enumerate(row):
            number = display_number(value) if column in numeric_columns else None
            sort_value = '' if number is None else str(number)
            cls = 'stock-cell'
            if column == 6 and number is not None:
                cls += ' stock-positive' if number > 0 else ' stock-negative' if number < 0 else ''
            parts.append('<td class="%s" data-sort-value="%s"><span class="stock-value">%s</span>' % (cls, esc(sort_value), esc(value)))
            if column in (4, 5) and number is not None:
                parts.append('<span class="stock-mini-track" aria-hidden="true"><span class="stock-mini-fill" style="width:%.4f%%"></span></span>' % min(100, max(0, number)))
            elif column == 6 and number is not None:
                width = min(50, abs(number)/return_scale*50)
                left = 50-width if number < 0 else 50
                parts.append('<span class="stock-mini-track stock-return-track" aria-hidden="true"><span class="stock-return-fill" style="left:%.4f%%;width:%.4f%%"></span></span>' % (left, width))
            parts.append('</td>')
        parts.append('</tr>')
    if not rows:
        parts.append('<tr><td colspan="%d">—</td></tr>' % len(headers))
    parts.append('</tbody></table></div><div class="stock-pager" hidden><div class="stock-pager-group"><span data-stock-range role="status" aria-live="polite"></span><label>每页 <input type="number" data-page-size min="1" max="50" step="1" value="10" aria-label="每页股票条数"> 条</label><button type="button" data-stock-apply>应用</button></div><div class="stock-pager-group"><button type="button" data-stock-prev>上一页</button><span data-stock-page></span><button type="button" data-stock-next>下一页</button></div></div></div>')
    return ''.join(parts)
