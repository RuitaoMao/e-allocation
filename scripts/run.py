#!/usr/bin/env python3
"""Fetch MCP tools once; model analyzes structured data; publish two HTMLs."""
import argparse
import contextlib
import io
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import fetch
import render
from analysis_contract import AnalysisValidationError, load_json, repair
from analysis_report import fingerprint, write_context, render_analysis
from provider_policy import audit
from review_options import PERIODS, menu


def read_json(path):
    return load_json(Path(path).read_text(encoding='utf-8-sig'))


def failure(directory, stage, exc, **extra):
    errors = exc.errors if isinstance(exc, AnalysisValidationError) else [{'error': str(exc)}]
    if isinstance(exc, json.JSONDecodeError):
        errors[0].update(line=exc.lineno, column=exc.colno, offset=exc.pos,
                         context=exc.doc[max(0, exc.pos - 60):exc.pos + 60])
    result = dict(prepared=str(directory), stage=stage, error=str(exc), errors=errors,
                  retry='仅修正报错字段或JSON语法；复用本次目录，不重新取数', **extra)
    fetch.save(directory / 'analysis-errors.json', result)
    print(json.dumps(result, ensure_ascii=False))
    return 2


def read_input(args):
    if args.input == '-':
        raw = load_json(sys.stdin.read())
        if 'columns' in raw or 'rows' in raw:
            raw = fetch.table_input(raw, args.date, args.port_name, args.portfolio)
    elif args.input:
        raw = fetch.load(args.input, default_date=args.date, port_name=args.port_name, portfolio=args.portfolio)
    else:
        raw = {}
    if args.port_name:
        raw['port_name'] = args.port_name
    analysis = raw['analysis'] = raw.get('analysis') or {}
    for key, value in (('start_date', args.start_date), ('end_date', args.end_date),
                       ('benchmark_code', args.benchmark), ('review_period', args.review_period)):
        if value is not None:
            analysis[key] = value
    return raw


def prepare(args, raw):
    started = time.monotonic()
    request = fetch.canonical(raw, args.org_id, args.weight_scale, getattr(args, 'total_amount', None))
    directory = Path(tempfile.mkdtemp(prefix='e-allocation-mcp-')).resolve()
    try:
        bundle = fetch.collect(request, directory, args.base_url, args.timeout, retries=args.retries,
                               workers=args.workers, confirm_cny_prices=args.confirm_cny_prices)
        report = fetch.build(request, bundle)
        fetch.save(directory / 'report-data.json', report)
        data_hash = fingerprint(directory / 'report-data.json')
        context_started = time.monotonic()
        context = directory / 'analysis-context.md'
        count = write_context(report, context, directory.name, data_hash)
        # Business prompt is copied unchanged from the installed skill.
        prompt = Path(__file__).resolve().parents[1] / 'references' / 'ANALYSIS_PROMPT.md'
        if not prompt.is_file():
            raise ValueError('缺少ANALYSIS_PROMPT.md业务提示词')
        shutil.copyfile(prompt, directory / 'ANALYSIS_PROMPT.md')
        prepared = {'version': 1, 'name': request['name'], 'run_id': directory.name,
                    'report_data_sha256': data_hash, 'context_sha256': fingerprint(context),
                    'prompt_sha256': fingerprint(directory / 'ANALYSIS_PROMPT.md'),
                    'prepared_at': time.time(), 'finalize_attempts': [],
                    'timings': {'prepare_seconds': round(time.monotonic() - started, 3),
                                'context_seconds': round(time.monotonic() - context_started, 3)}}
        fetch.save(directory / 'prepared.json', prepared)
        return {'prepared': str(directory), 'analysis_context': str(context),
                'analysis_prompt': str(directory / 'ANALYSIS_PROMPT.md'),
                 'record_count': count, 'succeeded': sum(s['ok'] for s in report['sources'].values()),
                 'warnings': report['warnings'], 'title_dates': render.report_title_dates(report),
                 'timings': prepared['timings']}
    except Exception as exc:
        # Keep successful API responses on failure; do not refetch automatically.
        fetch.save(directory / 'prepare-errors.json', {'error': str(exc)})
        raise ValueError(str(exc) + '；本次数据保留于' + str(directory)) from exc


def finalize(args):
    entered = time.time()
    started = time.monotonic()
    directory = Path(args.finalize).expanduser().resolve()
    prepared = read_json(directory / 'prepared.json')
    for filename, field in (('report-data.json', 'report_data_sha256'), ('analysis-context.md', 'context_sha256'), ('ANALYSIS_PROMPT.md', 'prompt_sha256')):
        if fingerprint(directory / filename) != prepared[field]:
            raise ValueError('本次数据、阅读视图或提示词已改变：' + filename)
    attempts = prepared['finalize_attempts']
    attempts.append({'entered_at': entered, 'repair': bool(args.repair)})
    fetch.save(directory / 'prepared.json', prepared)
    cache = directory / 'analysis-submitted.json'
    raw_path = directory / ('analysis-repair.raw.txt' if args.repair else 'analysis-submitted.raw.txt')
    stage = 'json'
    try:
        argument = args.repair or args.analysis
        raw = sys.stdin.read() if argument == '-' else Path(argument).read_text(encoding='utf-8-sig')
        raw_path.write_text(raw, encoding='utf-8')
        submitted = load_json(raw)
        if args.repair:
            stage = 'repair'
            analysis = repair(read_json(cache), submitted)
        else:
            analysis = submitted
    except (ValueError, OSError) as exc:
        return failure(directory, stage, exc, analysis_raw=str(raw_path), analysis_cache=str(cache) if cache.exists() else None)
    fetch.save(cache, analysis)
    report = read_json(directory / 'report-data.json')
    stem = render._safe_name(prepared['name']) + '-' + directory.name[len('e-allocation-mcp-'):]
    destination = Path(args.output).expanduser().resolve() if args.output else Path.cwd() / (stem + '-组合数据报告.html')
    analysis_destination = Path(args.analysis_output).expanduser().resolve() if args.analysis_output else destination.with_name(stem + '-组合分析报告.html')
    try:
        if destination == analysis_destination or any(p.exists() for p in (destination, analysis_destination)):
            raise ValueError('两份HTML必须使用不同的新文件名，不能覆盖已有文件')
        draft = directory / 'analysis-report.html'
        checks = render_analysis(report, analysis, draft, prepared['run_id'], prepared['report_data_sha256'])
        data_draft = directory / 'data-report.html'
        # Reuse a successfully checked data draft on local analysis repair.
        if not data_draft.exists() or prepared.get('data_html_sha256') != fingerprint(data_draft):
            if data_draft.exists():
                data_draft.unlink()
            checks_data = render.generate(report, data_draft)
            if checks_data['errors']:
                raise ValueError('数据报告检查失败：' + '；'.join(checks_data['errors']))
            content = data_draft.read_text(encoding='utf-8')
            tags = '<meta name="allocation-run-id" content="' + render.esc(prepared['run_id']) + '"><meta name="allocation-data-sha256" content="' + render.esc(prepared['report_data_sha256']) + '">'
            data_draft.write_text(content.replace('</head>', tags + '</head>', 1), encoding='utf-8')
            prepared['data_html_sha256'] = fingerprint(data_draft)
            fetch.save(directory / 'prepared.json', prepared)
        policy_errors = audit(data_draft) + audit(draft)
        if policy_errors:
            raise ValueError('报告对外呈现检查失败：' + '；'.join(policy_errors))
        # Publish only after both reports pass; rollback a partial publication.
        published = []
        try:
            for target, source in ((destination, data_draft), (analysis_destination, draft)):
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as output:
                    published.append(target)
                    with source.open('rb') as stream:
                        shutil.copyfileobj(stream, output)
        except Exception:
            for target in published:
                target.unlink()
            raise
    except (ValueError, OSError) as exc:
        return failure(directory, 'validation_or_publish', exc, analysis_cache=str(cache))
    timings = dict(prepared['timings'], finalize_seconds=round(time.monotonic() - started, 3),
                   first_analysis_gap_seconds=round(attempts[0]['entered_at'] - prepared['prepared_at'], 3),
                   repair_gap_seconds=round(entered - attempts[0]['entered_at'], 3), finalize_attempt_count=len(attempts))
    removed = False
    if not args.keep_intermediates and directory.parent == Path(tempfile.gettempdir()).resolve() and directory.name.startswith('e-allocation-mcp-'):
        shutil.rmtree(directory)
        removed = True
    print(json.dumps(dict(data_report=str(destination), analysis_report=str(analysis_destination),
                          intermediatesRemoved=removed, timings=timings,
                          title_dates=render.report_title_dates(report), **checks), ensure_ascii=False))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description='MCP单次组合取数，结构化数据分析，交付数据与分析两份离线HTML')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--options', action='store_true', help='在本地读取已选回顾期和指数，返回缺少的选择菜单')
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--finalize', help='本次prepare返回的目录；不重新取数')
    p.add_argument('--input', help='.xlsx/.json路径或 -；prepare必填')
    p.add_argument('--date'); p.add_argument('--portfolio'); p.add_argument('--port-name')
    p.add_argument('--start-date'); p.add_argument('--end-date'); p.add_argument('--benchmark')
    p.add_argument('--review-period', choices=PERIODS, help='回顾期预设；自定义时用 --start-date 和 --end-date')
    p.add_argument('--org-id', default='demo_org'); p.add_argument('--weight-scale', default='1000000')
    p.add_argument('--total-amount', help='权重持仓的真实总金额（元），也接受250万元等明确单位')
    p.add_argument('--confirm-cny-prices', action='store_true', help='确认金额持仓的快照日报价为人民币，按原日价格换算份额')
    p.add_argument('--mcp-url', '--base-url', dest='base_url', help='Streamable HTTP MCP地址，默认读取 E_ALLOCATION_MCP_URL'); p.add_argument('--timeout', type=int, default=120)
    p.add_argument('--retries', type=int, default=4, help='含首次调用，最多4次尝试'); p.add_argument('--workers', type=int, choices=range(1, 9), default=1, help='兼容旧参数；取数始终单次串行')
    p.add_argument('--analysis'); p.add_argument('--repair')
    p.add_argument('--output'); p.add_argument('--analysis-output'); p.add_argument('--keep-intermediates', action='store_true')
    args = p.parse_args(argv)
    if args.options:
        print(json.dumps(menu(read_input(args)), ensure_ascii=False))
        return 0
    if args.prepare:
        if not args.input or args.analysis or args.repair:
            p.error('--prepare须提供--input，不接受--analysis或--repair')
        if args.timeout <= 0 or args.retries <= 0:
            p.error('timeout/retries须大于零')
        raw = read_input(args)
        choices = menu(raw)
        if choices['questions']:
            print(json.dumps(dict(status='selection_required', **choices), ensure_ascii=False))
            return 2
        # Existing API logs are retained for diagnostics, not expanded into context.
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            result = prepare(args, raw)
        Path(result['prepared'], 'fetch.log').write_text(log.getvalue(), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if bool(args.analysis) == bool(args.repair):
        p.error('--finalize须提供--analysis或--repair其中一个')
    return finalize(args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'error': str(exc), 'errors': [{'error': str(exc)}]}, ensure_ascii=False))
        sys.exit(2)
