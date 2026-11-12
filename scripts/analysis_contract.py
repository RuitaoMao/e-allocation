"""Strict analysis submission contract; errors are batched for local repair."""
import copy
import json
import math
import re

NOTE_LABEL = re.compile(
    r'^[ \t>#*_-]*(?:注|备注|附注|脚注|图注|说明|补充说明|数据说明|口径说明|日期说明|统计口径|统计区间|数据口径(?:与局限)?)[ \t*_]*(?:[:：]|$)',
    re.MULTILINE,
)


class AnalysisValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('分析校验失败：%d处；请按返回路径局部修正' % len(errors))


def load_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('JSON字段重复：' + key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError('JSON不允许非有限数值：' + value)

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def structure_errors(analysis):
    errors = []

    def error(path, message, **extra):
        errors.append(dict(path=path, error=message, **extra))

    def text(value, path):
        if not isinstance(value, str) or not value.strip():
            error(path, '须为非空文字')
        elif NOTE_LABEL.search(value):
            error(path, '请删除独立注释，必要的日期或统计窗口放在标题括号内')

    def keys(obj, allowed, path):
        for key in obj:
            if key not in allowed:
                error(path + '/' + key, '未知字段')

    if not isinstance(analysis, dict):
        return [{'path': '', 'error': '分析须为JSON对象'}]
    keys(analysis, {'title', 'findings', 'sections', 'conclusion'}, '')
    for field in ('title', 'conclusion'):
        text(analysis.get(field), '/' + field)
    findings = analysis.get('findings')
    if not isinstance(findings, list):
        error('/findings', '核心发现须为1–5条对象列表')
    else:
        if not 1 <= len(findings) <= 5:
            error('/findings', '核心发现须为1–5条')
        for i, item in enumerate(findings):
            path = '/findings/' + str(i)
            if not isinstance(item, dict):
                error(path, '发现须为对象')
                continue
            fields = ('title', 'conclusion', 'highlights', 'risk_impact')
            keys(item, set(fields) | {'evidence'}, path)
            for field in ('title', 'conclusion', *(key for key in ('highlights', 'risk_impact') if key in item)):
                text(item.get(field), path + '/' + field)
    sections = analysis.get('sections')
    if not isinstance(sections, list) or not sections:
        error('/sections', '须提供至少一个分析章节')
    else:
        for i, item in enumerate(sections):
            path = '/sections/' + str(i)
            if not isinstance(item, dict):
                error(path, '章节须为对象')
                continue
            keys(item, {'title', 'reading_title', 'paragraphs', 'evidence', 'tables', 'charts'}, path)
            text(item.get('title'), path + '/title')
            paragraphs = item.get('paragraphs', [])
            if 'reading_title' in item:
                text(item['reading_title'], path + '/reading_title')
                if not paragraphs:
                    error(path + '/reading_title', '正文小标题须搭配正文')
            if not isinstance(paragraphs, list):
                error(path + '/paragraphs', '正文须为文字列表')
            else:
                for j, paragraph in enumerate(paragraphs):
                    text(paragraph, path + '/paragraphs/' + str(j))
            tables = item.get('tables', [])
            charts = item.get('charts', [])
            if not isinstance(charts, list):
                error(path + '/charts', '图表须为对象列表')
            if not (paragraphs or charts or tables):
                error(path, '章节须有正文、图表或表格')
            if not isinstance(tables, list):
                error(path + '/tables', '须为表格列表')
                continue
            for j, grid in enumerate(tables):
                gp = path + '/tables/' + str(j)
                if not isinstance(grid, dict):
                    error(gp, '表格须为对象')
                    continue
                keys(grid, {'headers', 'rows'}, gp)
                headers, rows = grid.get('headers'), grid.get('rows')
                valid_headers = isinstance(headers, list) and 1 <= len(headers) <= 8
                if not valid_headers:
                    error(gp + '/headers', '须为1—8列表头')
                if not isinstance(rows, list):
                    error(gp + '/rows', '须为表格行列表')
                    continue
                cells = [(gp + '/headers/' + str(k), cell) for k, cell in enumerate(headers)] if isinstance(headers, list) else []
                for k, row in enumerate(rows):
                    rp = gp + '/rows/' + str(k)
                    if not isinstance(row, list):
                        error(rp, '表格行须为列表')
                        continue
                    if valid_headers and len(row) != len(headers):
                        error(rp, '行列数不一致', expected_columns=len(headers))
                    cells.extend((rp + '/' + str(n), cell) for n, cell in enumerate(row))
                for cp, cell in cells:
                    if (cell is not None and (isinstance(cell, bool) or not isinstance(cell, (str, int, float)))) or (isinstance(cell, float) and not math.isfinite(cell)):
                        error(cp, '单元格须为文字、有限数值或null')
                    elif isinstance(cell, str) and NOTE_LABEL.search(cell):
                        error(cp, '表格不添加独立注释')
    return errors


def repair(analysis, operations):
    """Atomic replacements; invalid operations never change the cached submission."""
    if not isinstance(operations, list) or not operations:
        raise ValueError('repair须为非空局部替换列表')
    result = copy.deepcopy(analysis)
    allowed = {'root': {'title', 'findings', 'sections', 'conclusion'},
               'findings': {'title', 'conclusion', 'highlights', 'risk_impact', 'evidence'},
               'sections': {'title', 'reading_title', 'paragraphs', 'evidence', 'tables', 'charts'},
               'tables': {'headers', 'rows'},
               'charts': {'id', 'type', 'title', 'unit', 'labels', 'rows', 'caption'},
               'rows': {'label', 'values'}, 'values': {'pointer', 'field'}}
    for op in operations:
        if not isinstance(op, dict) or set(op) != {'path', 'value'}:
            raise ValueError('每项repair仅含path和value')
        path = op['path']
        if not isinstance(path, str) or not path.startswith('/'):
            raise ValueError('无效修复路径：' + str(path))
        parts = path[1:].split('/')
        if parts[0] not in allowed['root']:
            raise ValueError('无效修复路径：' + path)
        obj = result
        try:
            for part in parts[:-1]:
                if isinstance(obj, list):
                    if not part.isdigit() or int(part) >= len(obj):
                        raise ValueError('列表索引越界')
                    obj = obj[int(part)]
                else:
                    obj = obj[part]
            key = parts[-1]
            if isinstance(obj, list):
                if not key.isdigit() or int(key) >= len(obj):
                    raise ValueError('列表索引越界')
                key = int(key)
            elif isinstance(obj, dict):
                kind = 'root' if len(parts) == 1 else parts[-3] if len(parts) >= 3 else ''
                if key not in obj and key not in allowed.get(kind, set()):
                    raise ValueError('未知缺失字段')
            else:
                raise ValueError('路径父项不是对象或列表')
            obj[key] = op['value']
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError('修复路径无效：' + path + '；' + str(exc)) from exc
    return result
