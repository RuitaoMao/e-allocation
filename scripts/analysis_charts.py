"""Offline analysis visuals backed by a single report snapshot."""
from analysis_contract import NOTE_LABEL
from fetch import holding_rows, numeric
from render import distribution, dual_distribution, heatmap, line, top_industries


def catalogue(report):
    data, meta = report['data'], report['meta']
    charts = {}
    benchmark = meta.get('benchmark_name') or meta['benchmark_code']

    def cutoff(title, day):
        return '%s（截止%s）' % (title, day) if day else title

    def bars(key, title, rows, unit='%', labels=None):
        if any(numeric(value) is not None for row in rows for value in row[1:]):
            charts[key] = dict(kind='grouped' if labels else 'bar', title=title,
                               rows=rows, labels=labels, unit=unit)

    def ranked(rows, field, name, limit=7, by_magnitude=False):
        values = [(name(row), numeric(row.get(field))) for row in rows]
        return sorted((row for row in values if row[1] is not None),
                      key=lambda row: abs(row[1]) if by_magnitude else row[1], reverse=True)[:limit]

    series = data['10'].get('series') or []
    if any(numeric(row.get('portfolioCumulativeReturnRate')) is not None for row in series):
        charts['trend'] = dict(kind='line', title='组合与对比指数累计收益（回顾期）',
                               rows=series, benchmark=benchmark)
    order = ('REVIEW', 'YTD', '1M', '1Y', '3Y')
    periods = {row['periodCode']: row for row in data['8'].get('periods', [])}
    shown_periods = [periods[code] for code in order if code in periods]
    fixed_end = data['8'].get('statisticsEndDate')
    returns_title = '各窗口收益对比（固定窗口截止%s）' % fixed_end if fixed_end else '各窗口收益对比'
    bars('returns', returns_title,
         [(row['periodName'], row.get('portfolioReturnRate'), row.get('comparisonIndexReturnRate'))
          for row in shown_periods],
         labels=['组合', benchmark])
    funds = holding_rows(data)
    bars('weights', cutoff('持仓权重较高的基金', data['3'].get('holdingDate')),
         ranked(funds, 'currentHoldingWeight', lambda row: row.get('fInfoName') or row['portCode']))
    bars('contribution', '影响较大的收益贡献（回顾期）',
         ranked(report['contributions_percent'], 'fundReturnContribution',
                lambda row: row.get('fundName') or row['fundCode'], by_magnitude=True))
    risk = data['12']
    bars('risk', '影响较大的年化波动率贡献（近一年）',
         ranked(risk.get('items', []), 'fundAnnualizedRiskContribution',
                lambda row: row.get('fundName') or row['fundCode'], by_magnitude=True))
    asset = data['15']
    disclosure_day = meta.get('report_date')
    bars('regions', cutoff('穿透股票地区仓位', disclosure_day), [(label, asset.get(field)) for label, field in (
         ('A股', 'aShareRatio'), ('港股', 'hongKongEquityRatio'), ('美股', 'usEquityRatio'),
         ('其他地区', 'otherRegionEquityRatio'))])
    for key, system, label in (('industry-domestic', '申万一级', '非QDII'), ('industry-qdii', 'GICS一级', 'QDII')):
        bars(key, cutoff(label + '前五行业股票占比', disclosure_day),
             [(row['sectorName'], row.get('equityRatioInHoldings'))
              for row in top_industries(data['17'].get('items', []), system)])
    by_weight = ranked(funds, 'currentHoldingWeight', lambda row: row['portCode'], limit=6)
    codes = [code for code, _ in by_weight]
    selected = set(codes)
    correlation = data['13']
    pairs = [row for row in correlation.get('items', [])
             if row['fundCode1'] in selected and row['fundCode2'] in selected]
    if any(row['fundCode1'] != row['fundCode2'] and numeric(row.get('fundReturnCorrelation')) is not None
           for row in pairs):
        start, end = correlation.get('startDate'), correlation.get('endDate')
        window = '回顾期'
        if start and end and (start, end) != (meta['range_start'], meta['range_end']):
            window = '%s 至 %s' % (start, end)
        charts['correlation'] = dict(kind='heatmap', title='主要持仓的收益相关性（%s）' % window,
                                     rows=pairs, codes=codes,
                                     names={row['portCode']: row.get('fInfoName') or row['portCode'] for row in funds})
    return charts


def resolve(spec, presets, evidence):
    """Resolve a chart selection or custom series without accepting authored values."""
    if not isinstance(spec, dict):
        raise ValueError('图表须为对象')
    # Older submissions may include a caption. It is accepted without rendering.
    for key in ('title', 'caption'):
        if key in spec and (not isinstance(spec[key], str) or not spec[key].strip()):
            raise ValueError(key + ' 须为非空文字')
    if NOTE_LABEL.search(spec.get('title', '')):
        raise ValueError('图标题使用指标名称，必要的日期或窗口放在括号内')
    if 'id' in spec:
        if set(spec) - {'id', 'title', 'caption'} or not isinstance(spec['id'], str) or spec['id'] not in presets:
            raise ValueError('请使用本次数据中可用的图表 id，或定义自选图表')
        return dict(presets[spec['id']], title=spec.get('title', presets[spec['id']]['title']), evidence=[])
    if set(spec) - {'type', 'title', 'caption', 'unit', 'labels', 'rows'}:
        raise ValueError('自选图表含未知字段')
    kind, unit, rows = spec.get('type'), spec.get('unit'), spec.get('rows')
    if kind not in ('bar', 'grouped') or 'title' not in spec or not isinstance(unit, str) or len(unit) > 8:
        raise ValueError('自选图表需要 type、title 和 unit，type 可选 bar 或 grouped')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
        raise ValueError('自选图表须有 1–12 行')
    labels = spec.get('labels')
    if kind == 'grouped' and (not isinstance(labels, list) or len(labels) != 2
                              or not all(isinstance(label, str) and label.strip() for label in labels)):
        raise ValueError('分组图须有两个非空图例标签')
    points, pointers = [], []
    width = 2 if kind == 'grouped' else 1
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or set(row) != {'label', 'values'}
                or not isinstance(row['label'], str) or not row['label'].strip()
                or not isinstance(row['values'], list) or len(row['values']) != width):
            raise ValueError('第 %d 行须提供名称和 %d 个证据取值' % (index + 1, width))
        point = [row['label']]
        for ref in row['values']:
            if not isinstance(ref, dict) or set(ref) != {'pointer', 'field'} or not all(isinstance(v, str) for v in ref.values()):
                raise ValueError('图表取值须提供真实证据指针及数值字段名')
            record = evidence.get(ref['pointer'])
            value = numeric(record.get(ref['field'])) if isinstance(record, dict) else None
            if value is None:
                raise ValueError('图表证据没有有效数值：' + ref['pointer'] + ' / ' + ref['field'])
            point.append(value)
            pointers.append(ref['pointer'])
        points.append(point)
    return dict(kind=kind, title=spec['title'], rows=points, labels=labels, unit=unit,
                evidence=list(dict.fromkeys(pointers)))


def render_chart(spec, key, *, full_width=False):
    kind, title, rows = spec['kind'], spec['title'], spec['rows']
    if kind == 'line':
        content = line(rows, spec['benchmark'], key, title, show_note=False, wide=True)
    elif kind == 'heatmap':
        content = heatmap(rows, spec['names'], spec['codes'], key, title, show_note=False)
    elif kind == 'grouped':
        content = dual_distribution(key, title, rows, kind='bar', labels=spec['labels'], unit=spec['unit'],
                                    wide=full_width)
    else:
        content = distribution(key, title, rows, unit=spec['unit'], emphasize_sign=True, wide=full_width)
    wide = ' analysis-wide' if full_width or kind in ('line', 'heatmap') else ''
    return '<div class="analysis-visual' + wide + '">' + content + '</div>'
