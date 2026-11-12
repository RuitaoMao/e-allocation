"""Complete structured reading view and independent offline analysis rendering."""
import hashlib
import json
import re
from itertools import groupby
from pathlib import Path
from provider_policy import public_text

from analysis_charts import catalogue, render_chart, resolve
from analysis_contract import AnalysisValidationError, structure_errors
from fetch import ENDPOINTS, ASSETS, REGIONS, SECTORS, MARKET_CAP, fmt, numeric, holding_valuation
from render import REPORT_CSS, REPORT_JS, data_description_html, disclaimer_html, esc, table

FINDINGS_CSS = '''
.core-findings{margin:24px 0}.core-findings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 18px}
.finding-card{border:1px solid #cbd9e1;border-top:3px solid #00579A;padding:12px 15px;background:#f8fbfd;break-inside:avoid}
.finding-card h3{margin:0 0 8px;font-size:14px}.finding-card p{margin:5px 0;line-height:1.75}.finding-card strong{color:#00579A}
.core-findings-grid>.finding-card:last-child:nth-child(odd){grid-column:1 / -1}
@media(max-width:760px){.core-findings-grid{grid-template-columns:1fr}}
'''
ANALYSIS_CSS = REPORT_CSS + FINDINGS_CSS + '''
p{line-height:1.7}section{margin:24px 0}
.analysis-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:18px 0}
.analysis-metric,.analysis-visual{min-width:0;background:#f8fbfd;border:1px solid #cbd9e1;padding:12px 15px;break-inside:avoid}
.analysis-metric span{display:block;font-size:12px;color:var(--muted)}
.analysis-metric strong{font-size:21px;color:var(--blue)}
.analysis-visuals{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px 0}
.analysis-wide,.analysis-visual:only-child{grid-column:1 / -1}
.analysis-visual .chart{margin:0}.analysis-visual svg{max-height:none}
.analysis-visual .legend{justify-content:center;margin-top:8px;text-align:center}
.analysis-body .heat{width:100%;min-width:560px}
.analysis-copy{margin:14px 0 18px}
.analysis-copy h3{font-size:16px;font-weight:700;margin:0 0 6px}
.analysis-reading{
 max-width:none;width:100%;margin:0 0 10px;font-size:15px;line-height:1.8;
 text-align:left;letter-spacing:normal;word-spacing:normal;font-variant-numeric:normal;overflow-wrap:anywhere;
}
.analysis-reading:last-child{margin-bottom:0}
@media(max-width:760px){
header [data-print]{position:static;display:block;margin:0 0 8px auto}header h1{font-size:23px;padding:0}
.analysis-visuals{grid-template-columns:1fr}.analysis-visual{padding:10px}
.analysis-visual svg{min-width:410px}.analysis-visual .chart{overflow-x:auto}
.analysis-visual .chart-plot svg{min-width:720px}
}
.analysis-body table{font-size:13px}.analysis-body td{white-space:normal;overflow-wrap:anywhere;line-height:1.7}
.analysis-body th{min-width:0}
.evidence-details{margin-top:30px;border:1px solid #cbd9e1;border-radius:4px;padding:12px 15px;background:#f8fbfd}
.evidence-details summary{font-weight:600}.evidence-details a{color:#00579A;overflow-wrap:anywhere}
.evidence-index{padding:12px 0;border-bottom:1px solid #cbd9e1}.evidence-index p{margin:5px 0}
.evidence-details article{margin:16px 0}.evidence-details pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
@media print{.evidence-details:not([open])>*:not(summary){display:none}.analysis-body th{min-width:0}}
'''


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def normalize_analysis_units(value):
    """Display legacy return differences and contributions with a percent sign."""
    if isinstance(value, str):
        return re.sub(r'[ \t]*(?:(?:个[ \t]*)?百分点|(?<![A-Za-z])pp(?![A-Za-z]))', '%', value,
                      flags=re.IGNORECASE)
    if isinstance(value, list):
        return [normalize_analysis_units(item) for item in value]
    if isinstance(value, dict):
        references = {'evidence', 'pointer', 'field', 'id'}
        return {key: item if key in references else normalize_analysis_units(item) for key, item in value.items()}
    return value


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def records(report):
    """One compact record per original row/window; no sampling or time-series cuts.

    Exclude raw 11 only: contributions_percent is its fully retained normalized
    representation. Other endpoint objects are traversed in full, including nulls.
    JSON pointers remain valid against the unchanged complete report-data.json.
    """
    result = {}

    def visit(value, path):
        if isinstance(value, dict):
            scalar = {k: v for k, v in value.items() if not isinstance(v, (dict, list))}
            if scalar or not value:
                result['#' + path] = scalar
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    visit(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            if not value:
                result['#' + path] = []
            for i, child in enumerate(value):
                visit(child, path + '/' + str(i))
        else:
            result['#' + path] = value

    for key in ('meta', 'unit_rules', 'valuation', 'warnings'):
        visit(report[key], '/' + key)
    if report.get('industry_group_summaries'):
        visit(report['industry_group_summaries'], '/industry_group_summaries')
    for seq in ENDPOINTS:
        source = report['sources'][str(seq)]
        # Operational timing is not analysis data; source status is retained.
        result['#/sources/' + str(seq)] = {k: source.get(k) for k in (
            'endpoint', 'ok', 'error', 'not_requested', 'status', 'api_id', 'actual_dates',
            'requested_as_of', 'units', 'denominator', 'source_api_ids', 'request_ids', 'scope') if k in source}
        if seq == 11:
            visit({k: v for k, v in report['data']['11'].items() if k != 'items'}, '/data/11')
            visit(report['contributions_percent'], '/contributions_percent')
        else:
            visit(report['data'][str(seq)], '/data/' + str(seq))
    return result


def write_context(report, destination, run_id, data_hash):
    rows = records(report)
    intro = [
        '# 本次组合结构化分析数据（完整阅读视图）',
        'run_id=' + run_id + '; report_data_sha256=' + data_hash,
        '事实来源为本次report-data.json；数据HTML与分析报告均使用同一快照。以下不是HTML提取结果，也不是抽样摘要。',
        '每行以真实JSON指针标识；evidence直接引用例如#/data/3/items/0。编号只证明来源存在，模型须核对数值、单位、日期、分母与推论。',
        '嵌套基金先列基金身份，随后列其全部periods。空数组、空对象与null保留，不能视为零。data.11.items只使用完整contributions_percent规范化视图，四个比例字段已经乘100，收益贡献以%显示。',
        '同一列表内字段一致的行采用无损列式表示：[columns:列表指针]给出完整字段顺序，其后每行JSON数组与字段一一对应；证据指针仍定位原始JSON对象，所有数值和null原样保留。列头不是证据。',
        '完整保留所有基金、窗口、时序、股票和实际返回的相关性配对。不能累加重复配对；不能把原始11比例再当百分数，不能跨模块累加同一持仓。',
        '基金代码对外只展示六位数字，去掉接口返回的.OF/of后缀（大小写均适用）；对话、分析正文、表格与证据展示副本均适用。原始数据和真实证据指针仍以本地快照核验，不修改股票代码、实际基准代码或数值。',
        '字段辅助标签=' + compact(dict(ASSETS, **REGIONS, **SECTORS, **MARKET_CAP)),
        '接口模块=' + compact(ENDPOINTS),
        '本次可用图表=' + compact({key: value['title'] for key, value in catalogue(report).items()}),
        '## 固定数据报告口径（与当前渲染器共用）',
        (Path(__file__).resolve().parents[1] / 'references' / 'REPORT.md').read_text(encoding='utf-8'),
        '## 完整结构化数据',
    ]
    Path(destination).write_text('\n'.join(intro) + '\n' + '\n'.join(reading_lines(rows)) + '\n', encoding='utf-8')
    return len(rows)


def reading_lines(rows):
    """Lossless column compression removes repeated field names, never data rows."""
    groups = {}
    for pointer, value in rows.items():
        parent, _, last = pointer.rpartition('/')
        if last.isdigit() and isinstance(value, dict) and value:
            groups.setdefault(parent, []).append(tuple(value))
    schemas = {parent: keys[0] for parent, keys in groups.items()
               if len(keys) > 1 and all(k == keys[0] for k in keys) and len(compact(keys[0])) < 1700}
    emitted = set()
    for pointer, value in rows.items():
        parent, _, last = pointer.rpartition('/')
        if last.isdigit() and parent in schemas and isinstance(value, dict) and tuple(value) == schemas[parent]:
            schema = schemas[parent]
            if parent not in emitted:
                yield '[columns:' + parent + '] ' + compact(schema)
                emitted.add(parent)
            value = [value[key] for key in schema]
        yield '[' + pointer + '] ' + compact(value)


def validate(analysis, report):
    errors = structure_errors(analysis)
    available = records(report)
    presets = catalogue(report)
    visuals = {}
    for group in ('findings', 'sections'):
        items = analysis.get(group, []) if isinstance(analysis, dict) else []
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            path = '/%s/%d/evidence' % (group, i)
            specs = item.get('charts', [])
            if group == 'sections' and isinstance(specs, list):
                visuals[i] = []
                for j, spec in enumerate(specs):
                    try:
                        visuals[i].append(resolve(spec, presets, available))
                    except ValueError as exc:
                        errors.append({'path': '/sections/%d/charts/%d' % (i, j), 'error': str(exc)})
            evidence = item.get('evidence')
            if not isinstance(evidence, list) or not evidence:
                errors.append({'path': path, 'error': '须提供非空证据列表'})
                continue
            for j, pointer in enumerate(evidence):
                value = available.get(pointer) if isinstance(pointer, str) else None
                valid = value is not None and value != {} and value != []
                if isinstance(value, dict):
                    valid = any(v is not None for v in value.values())
                if not valid:
                    errors.append({'path': path + '/' + str(j), 'value': pointer,
                                   'error': '须引用本次完整阅读视图中的真实非空证据指针'})
    if errors:
        raise AnalysisValidationError(errors)
    return available, visuals, presets


def summary_html(report):
    meta, data = report['meta'], report['data']
    review = next((row for row in data['8'].get('periods', []) if row['periodCode'] == 'REVIEW'), {})
    value = holding_valuation(data)
    total = numeric(value['basic_information_total_cny'])
    if total is None:
        total = numeric(value['holdings_total_cny'])
    valuation_day = value['basic_information_date'] if value['basic_information_total_cny'] is not None else value['holding_date']
    holding_label = '持仓市值（截止%s）' % valuation_day if valuation_day else '持仓市值'
    benchmark = meta.get('benchmark_name') or meta['benchmark_code']
    metrics = [
        (holding_label, total / 10000 if total is not None else None, ' 万元'),
        ('组合回顾期收益', review.get('portfolioReturnRate'), '%'),
        (benchmark + '回顾期收益', review.get('comparisonIndexReturnRate'), '%'),
        ('回顾期超额收益', review.get('portfolioExcessReturnRate'), '%'),
    ]
    return '<div class="analysis-metrics">' + ''.join(
        '<div class="analysis-metric"><span>' + esc(label) + '</span><strong>' + esc(fmt(amount, unit)) + '</strong></div>'
        for label, amount, unit in metrics if numeric(amount) is not None) + '</div>'


def render_analysis(report, analysis, destination, run_id, data_hash):
    analysis = normalize_analysis_units(analysis)
    available, visuals, presets = validate(analysis, report)
    item_evidence = [item['evidence'] for item in analysis['findings']] + [
        list(dict.fromkeys(item['evidence'] + [p for chart in visuals[i] for p in chart['evidence']]))
        for i, item in enumerate(analysis['sections'])]
    used = list(dict.fromkeys(p for pointers in item_evidence for p in pointers))
    ids = {p: 'evidence-%d' % (i + 1) for i, p in enumerate(used)}

    body = ['<div class="analysis-body"><section class="core-findings"><h2>核心发现</h2><div class="core-findings-grid">']
    for finding in analysis['findings']:
        body.append('<article class="finding-card"><h3>' + esc(finding['title']) + '</h3>')
        for field in ('conclusion', 'highlights', 'risk_impact'):
            if field in finding:
                body.append('<p>' + esc(finding[field]) + '</p>')
        body.append('</article>')
    body.append('</div></section>')
    def add_charts(charts, key):
        if not charts:
            return
        body.append('<div class="analysis-visuals">')
        index = 0
        for always_wide, group in groupby(charts, lambda chart: chart['kind'] in ('line', 'heatmap')):
            run = list(group)
            for offset, chart in enumerate(run):
                unpaired = offset == len(run) - 1 and offset % 2 == 0
                body.append(render_chart(chart, 'analysis-%s-%d' % (key, index),
                                         full_width=always_wide or unpaired))
                index += 1
        body.append('</div>')

    fallback = []
    if not any(visuals.values()) and presets:
        fallback = [presets[key] for key in ('trend', 'weights', 'contribution', 'regions') if key in presets]
        if not fallback:
            fallback = list(presets.values())[:3]
        body.append('<section><h2>组合数据图览</h2>')
        add_charts(fallback, 'overview')
        body.append('</section>')
    for i, section in enumerate(analysis['sections']):
        body.append('<section><h2>' + esc(section['title']) + '</h2>')
        add_charts(visuals[i], str(i))
        if section.get('paragraphs'):
            body.append('<div class="analysis-copy">')
            if section.get('reading_title'):
                body.append('<h3>' + esc(section['reading_title']) + '</h3>')
            body.extend('<p class="analysis-reading">' + esc(p) + '</p>' for p in section['paragraphs'])
            body.append('</div>')
        for grid in section.get('tables', []):
            body.append(table(grid['headers'], grid['rows']))
        body.append('</section>')
    body.append('<section><h2>组合层面总结</h2><p>' + esc(analysis['conclusion']) + '</p></section>')
    body.append('</div><details class="evidence-details"><summary>数据证据与来源</summary><div class="evidence-index">')
    for item, pointers in zip(analysis['findings'] + analysis['sections'], item_evidence):
        body.append('<p><strong>' + esc(item['title']) + '</strong> ' + ' · '.join(
            '<a href="#' + ids[p] + '">' + esc(p) + '</a>' for p in pointers) + '</p>')
    body.append('</div>')
    for pointer in used:
        displayed = normalize_analysis_units(available[pointer])
        body.append('<article id="' + ids[pointer] + '"><h4>' + esc(pointer) + '</h4><pre>' + esc(compact(displayed)) + '</pre></article>')
    body.append('</details>')
    style = ANALYSIS_CSS
    html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="allocation-run-id" content="' + esc(run_id) + '"><meta name="allocation-data-sha256" content="' + esc(data_hash) + '"><title>' + esc(analysis['title']) + '</title><style>' + style + '</style></head><body><main><header><button data-print>打印报告</button><h1>' + esc(analysis['title']) + '</h1>' + data_description_html(report) + summary_html(report) + '</header>' + ''.join(body) + disclaimer_html() + '</main><div id="tooltip" role="status"></div><script>' + REPORT_JS + '</script></body></html>'
    Path(destination).write_text(public_text(html), encoding='utf-8')
    return {'errors': [], 'finding_count': len(analysis['findings']), 'section_count': len(analysis['sections']),
            'chart_count': len(fallback) + sum(map(len, visuals.values())), 'evidence_count': len(used)}
