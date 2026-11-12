"""Choices exposed by the conversation and enforced before report collection."""

PERIODS = {
    'since-holding': '首个持仓日至回顾截止日',
    'holding-year': '首个持仓年份年初至回顾截止日',
}
BENCHMARKS = {
    '000300': '沪深300',
    '000905': '中证500',
    '000852': '中证1000',
    '000016': '上证50',
    '399006': '创业板指数',
}


def selections(raw):
    analysis = raw.get('analysis') or {}
    return {
        'review_period': analysis.get('review_period'),
        'start_date': analysis.get('start_date') or raw.get('start_date') or raw.get('START_DATE'),
        'end_date': analysis.get('end_date') or raw.get('end_date') or raw.get('END_DATE'),
        'benchmark_code': analysis.get('benchmark_code') or raw.get('idx_code') or raw.get('IDX_CODE'),
    }


def menu(raw):
    selected = selections(raw)
    questions = []
    if not (selected['start_date'] or selected['review_period']):
        end = selected['end_date'] or '最新可用估值日'
        questions.append({
            'field': 'review_period', 'title': '选择组合回顾期',
            'options': [{'value': code, 'label': label.replace('回顾截止日', end)}
                        for code, label in PERIODS.items()]
                       + [{'value': 'custom', 'label': '自定义日期（输入起止日）'}],
        })
    if not selected['benchmark_code']:
        questions.append({
            'field': 'benchmark_code', 'title': '选择对比指数',
            'options': [{'value': code, 'label': '%s（%s）' % (name, code)}
                        for code, name in BENCHMARKS.items()]
                       + [{'value': 'custom', 'label': '其他指数（输入指数代码）'}],
        })
    return {'selected': selected, 'questions': questions}
