#!/usr/bin/env python3
"""One portfolio MCP tool; retain the existing 19-block reporting contract."""
import datetime as dt
import json
import math
import os
import re
import time
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from mcp_client import MCPClient, MCPError
from review_options import PERIODS, selections

ENDPOINTS = dict(enumerate([
    "metadata", "basic-information", "fund-overview", "fund-performance",
    "fund-risk-metrics", "fund-asset-and-equity-region-allocation",
    "fund-equity-sector-distribution", "historical-performance",
    "historical-risk-metrics", "performance-series", "holding-period-return-contribution",
    "ex-ante-risk", "fund-pairwise-correlation", "fund-category-distribution",
    "look-through-asset-and-equity-region-allocation", "look-through-equity-six-sector-distribution",
    "look-through-equity-industry-distribution", "look-through-equity-index-and-market-cap-distribution",
    "look-through-stock-holdings",
], 1))
PORTFOLIO_TOOL = 'get_portfolio_report_data'
REFERENCE_TOOL = 'query_fund_reference'
SECTOR_GROUPS = ('申万一级', 'GICS一级')
SECTOR_KEYS = ('financialsRealEstate', 'cyclical', 'industrial', 'healthcare', 'tmt', 'consumer')
TOOLS = {seq: PORTFOLIO_TOOL for seq in ENDPOINTS}


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def number(value):
    try:
        if isinstance(value, bool):
            raise ValueError("数值不能是布尔值")
        n = Decimal(str(value))
        if not n.is_finite() or n < 0:
            raise ValueError("数值必须是非负有限数")
        return n
    except InvalidOperation:
        raise ValueError("数值无效") from None


def day(value):
    d = date.fromisoformat(str(value))
    if d.isoformat() != value:
        raise ValueError("日期必须为 YYYY-MM-DD")
    return value


def code(value):
    if not isinstance(value, str) or len(value) != 6 or not value.isascii() or not value.isdigit():
        raise ValueError("基金代码必须是六位数字字符串")
    return value


def holding_totals(raw, snapshots, total_amount=None):
    """Resolve explicit CNY totals before converting weights; never infer history."""
    def money(value):
        value = number(amount(value, 'N_MARKET_VALUE', '', '真实持仓总金额'))
        if value <= 0:
            raise ValueError('真实持仓总金额必须大于零')
        return value
    weights = [s for s in snapshots if s['input_type'] == 'WEIGHT']
    totals = {}
    def assign(d, value):
        value = money(value)
        if d in totals and totals[d] != value:
            raise ValueError(d + '：真实持仓总金额存在冲突，请确认')
        totals[d] = value
    for s in snapshots:
        value = s.pop('total_amount', None)
        if value is not None:
            if s['input_type'] != 'WEIGHT':
                raise ValueError('total_amount仅适用于权重持仓，不覆盖已有份额或市值')
            assign(day(s['holding_date']), value)
    for value in (raw.get('total_amount'), total_amount):
        if value is None:
            continue
        if not weights:
            raise ValueError('total_amount仅适用于权重持仓，不覆盖已有份额或市值')
        if isinstance(value, dict):
            dates = {day(s['holding_date']) for s in weights}
            for d, total in value.items():
                if day(d) not in dates:
                    raise ValueError(d + '：总金额日期没有对应的权重快照')
                assign(d, total)
        else:
            if len(weights) != 1:
                raise ValueError('多日期权重持仓须按日期提供total_amount，不能将单一总额套用到历史快照')
            assign(day(weights[0]['holding_date']), value)
    missing = [day(s['holding_date']) for s in weights if day(s['holding_date']) not in totals]
    if missing:
        raise ValueError('权重持仓缺少真实总金额（' + '、'.join(missing) + '），请先在对话中确认各持仓日人民币总金额，再通过--total-amount或total_amount提交；不能默认100万元')
    return totals


def canonical(raw, org_id="demo_org", scale="1000000", total_amount=None):
    """Canonical input retains snapshot/trade meaning, normalizes weights explicitly."""
    if raw.get("prices"):
        raise ValueError("新版接口不接受自定义 prices；需确认取价口径，不能静默忽略")
    fields = {"N_SHARE": "shares", "N_MARKET_VALUE": "market_value", "N_WEIGHT": "weight"}
    types = {"shares": "SHARE", "market_value": "MARKET_VALUE", "weight": "WEIGHT"}
    snapshots, trades = [], []
    if "holdings" in raw:
        groups = {}
        for row in raw["holdings"]:
            groups.setdefault(day(row["BEG_DATE"]), []).append(row)
        for d, source_rows in sorted(groups.items()):
            complete = [f for f in ("N_SHARE", "N_WEIGHT", "N_MARKET_VALUE")
                        if all(row.get(f) is not None for row in source_rows)]
            if not complete:
                raise ValueError("同一持仓日期的份额、权重、市值至少一列须全部完整")
            chosen = complete[0]
            rows = [{"fund_code": code(row["I_CODE"]), fields[chosen]: row[chosen]} for row in source_rows]
            snapshots.append({"holding_date": d, "input_type": types[fields[chosen]], "items": rows})
        source_trades = raw.get("trades", [])
        if source_trades:
            complete = [f for f in ("N_SHARE", "N_MARKET_VALUE")
                        if all(row.get(f) is not None for row in source_trades)]
            for row in source_trades:
                chosen = complete[0] if complete else next((f for f in ("N_SHARE", "N_MARKET_VALUE") if row.get(f) is not None), None)
                if chosen is None:
                    raise ValueError("每条交易须填写正数份额或交易金额")
                trades.append({"fund_code": code(row["I_CODE"]), "trade_date": day(row["TRADE_DATE"]),
                               "trade_direction": row["TRADE_DIRECTION"], fields[chosen]: row[chosen]})
    else:
        source = raw.get("port_holding", [])
        snapshots = json.loads(json.dumps(source if isinstance(source, list) else [source]))
        trades = json.loads(json.dumps(raw.get("port_trade", [])))
    if not snapshots:
        raise ValueError("缺少持仓快照")
    scale = number(scale)
    if scale <= 0:
        raise ValueError("权重模型规模必须大于零")
    actual_totals = holding_totals(raw, snapshots, total_amount)
    conversions = []
    model_dates, dates = [], set()
    for snapshot in snapshots:
        d = day(snapshot["holding_date"])
        if d in dates:
            raise ValueError("同日多个快照需先确认，不能自动合并")
        dates.add(d)
        mode = snapshot["input_type"]
        f = {v: k for k, v in types.items()}.get(mode)
        if f is None:
            raise ValueError("input_type 仅支持 SHARE / MARKET_VALUE / WEIGHT")
        seen, positive = set(), []
        for row in snapshot["items"]:
            c = code(row["fund_code"])
            if c in seen:
                raise ValueError("同日基金代码重复")
            seen.add(c)
            if any(row.get(k) is not None for k in types if k != f):
                raise ValueError("持仓值与input_type不匹配")
            n = number(row.get(f))
            if n > 0:
                positive.append({"fund_code": c, f: format(n, "f")})
        if not positive:
            raise ValueError("全零/清仓快照需后端支持，不能自动删除该快照")
        if mode == "WEIGHT":
            total = sum(number(r[f]) for r in positive)
            base = actual_totals.get(d, scale)
            conversions.append({'holding_date': d, 'total_amount_cny': format(base, 'f'),
                                'source': 'user_actual' if d in actual_totals else 'model',
                                'input_weight_sum': format(total, 'f')})
            positive = [{"fund_code": r["fund_code"], "market_value": format(number(r[f]) / total * base, "f")}
                        for r in positive]
            snapshot["input_type"] = "MARKET_VALUE"
            if d not in actual_totals:
                model_dates.append(d)
        snapshot["items"] = positive
    for row in trades:
        code(row["fund_code"]); day(row["trade_date"])
        if row["trade_direction"] not in ("买入", "卖出"):
            raise ValueError("交易方向必须为买入/卖出")
        fs = [k for k in ("shares", "market_value") if row.get(k) is not None]
        if len(fs) != 1 or number(row[fs[0]]) <= 0:
            raise ValueError("交易须有正数份额或金额，二选一")
        row[fs[0]] = format(number(row[fs[0]]), "f")
    a = raw.get("analysis") or {}
    if a.get("report_date") or a.get("report_flag"):
        raise ValueError("MCP工具自动选取披露期，不支持指定 report_date/report_flag；请先确认")
    selected = selections(raw)
    period = selected['review_period']
    if period and period not in PERIODS:
        raise ValueError('无效回顾期选项；自定义请传 start_date 和可选 end_date')
    first_holding = min(dates)
    start = day(selected['start_date'] or (first_holding if period == 'since-holding' else first_holding[:4] + '-01-01'))
    end = day(selected['end_date']) if selected['end_date'] else None
    if end and start > end:
        raise ValueError('回顾期起点不能晚于截止日')
    benchmark = selected['benchmark_code']
    if benchmark is not None and (not isinstance(benchmark, str) or not 1 <= len(benchmark.strip()) <= 50):
        raise ValueError('对比指数须为有效代码字符串')
    return {"name": raw.get("port_name") or "基金组合", "org_id": raw.get("org_id") or raw.get("ORG_ID") or org_id,
            "port_id": raw.get("port_id") or raw.get("port_ID") or "skill_portfolio",
            "snapshots": sorted(snapshots, key=lambda s: s["holding_date"]), "trades": trades,
            "start_date": start, "end_date": end, "benchmark": benchmark.strip() if benchmark else '000300',
            "weight_model": {"scale_cny": str(scale), "snapshot_dates": model_dates} if model_dates else None,
            "weight_conversion": conversions}


def _retry(operation, retries):
    """Retry transport failures only; business partial/no_data is never refetched."""
    for attempt in range(min(4, max(1, retries))):
        try:
            return operation()
        except MCPError as exc:
            if not exc.retryable or attempt == min(4, max(1, retries)) - 1:
                raise
            wait = max((1, 3, 10)[attempt], exc.retry_after or 0)
            print('MCP暂时不可用，%s秒后重试' % wait, flush=True)
            time.sleep(wait)


def holding_shares(request, client, retries):
    """Lock dated CNY amounts to shares before the gateway moves the valuation date."""
    dates = {(item['fund_code'], snapshot['holding_date'])
             for snapshot in request['snapshots'] if snapshot['input_type'] == 'MARKET_VALUE'
             for item in snapshot['items']}
    if not dates:
        return request['snapshots'], []
    if REFERENCE_TOOL not in client.tools:
        raise ValueError('MCP未提供持仓日价格查询；请提供实际持有份额')
    queries = [dict(fund_code=fund, start_date=day, end_date=day) for fund, day in sorted(dates)]
    response = _retry(lambda: client.call_tool(
        REFERENCE_TOOL, {'action': 'prices', 'org_id': request['org_id'], 'price_queries': queries}), retries)
    if response.get('status') != 'ok':
        raise ValueError('MCP未成功返回持仓日价格；请核实估值日或提供实际持有份额')
    prices = {}
    for group in response.get('items') or []:
        key = (group.get('iCode'), group.get('startDate'))
        if key not in dates or key[1] != group.get('endDate'):
            raise ValueError('MCP返回的价格查询范围与请求不一致')
        for quote in group.get('prices') or []:
            if quote.get('hDate') != key[1] or key in prices:
                raise ValueError('MCP返回的持仓日价格日期不一致或有重复')
            raw_price = quote.get('fundPrice')
            price = numeric(raw_price)
            prices[key] = Decimal(str(raw_price)) if price is not None and price > 0 else None
    missing = ['%s/%s' % key for key in sorted(dates) if not prices.get(key)]
    if missing:
        raise ValueError('缺少有效持仓日价格：' + '、'.join(missing) + '；请提供实际持有份额')
    holdings, conversions = [], []
    for snapshot in request['snapshots']:
        if snapshot['input_type'] == 'SHARE':
            holdings.append(snapshot)
            continue
        holding_date = snapshot['holding_date']
        items = []
        for item in snapshot['items']:
            fund = item['fund_code']
            price = prices[fund, holding_date]
            shares = (number(item['market_value']) / price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if not shares:
                raise ValueError('%s/%s金额换算后不足0.01份；请核实原始持仓' % (fund, holding_date))
            items.append({'fund_code': fund, 'shares': str(shares)})
            conversions.append({'fund_code': fund, 'holding_date': holding_date,
                                'market_value_cny': item['market_value'], 'fund_price_cny': str(price),
                                'shares': str(shares), 'source': 'MCP C03；报价币种已确认人民币'})
        holdings.append({'holding_date': holding_date, 'input_type': 'SHARE', 'items': items})
    return holdings, conversions


def mcp_block_data(snapshot, seq):
    block = (snapshot.get('blocks') or {}).get('P%02d' % seq, {})
    if block.get('status') != 'ok':
        return None
    value = block.get('data')
    return value if value is not None else (snapshot.get('data') or {}).get(str(seq))


def industry_groups(p07):
    groups = {}
    for row in p07.get('items') or []:
        system = row.get('top5SectorClassificationSystem')
        if system in SECTOR_GROUPS:
            groups.setdefault(system, []).append(row)
    return groups


def current_positions(p03):
    positions = {}
    for row in p03.get('items') or []:
        fund = row.get('portCode')
        if not fund:
            continue
        shares = numeric(row.get('heldFundShares'))
        if fund in positions or shares is None or shares <= 0:
            return {}
        positions[fund] = number(row['heldFundShares'])
    return positions


def collect_industry_groups(client, request, snapshot, retries):
    p03 = mcp_block_data(snapshot, 3) or {}
    p07 = mcp_block_data(snapshot, 7) or {}
    groups = industry_groups(p07)
    if not groups:
        return {}, []
    positions = current_positions(p03)
    try:
        holding_date = day(p03.get('holdingDate'))
    except ValueError:
        return {}, ['行业分组汇总缺少当前持仓日期']
    if p07.get('holdingDate') != holding_date:
        return {}, ['行业分组明细与当前持仓的计算日期不一致']

    results, warnings = {}, []
    for system, rows in groups.items():
        funds = [row.get('portCode') for row in rows]
        if len(set(funds)) != len(funds) or not set(funds) <= positions.keys():
            warnings.append('P16 %s 分组无法确认完整持仓份额' % system)
            continue
        group_positions = {fund: positions[fund] for fund in funds}
        response = snapshot
        if group_positions != positions:
            body = {'action': 'analyze', 'org_id': request['org_id'],
                    'start_date': holding_date, 'end_date': holding_date,
                    'port_holding': {'holding_date': holding_date, 'input_type': 'SHARE',
                                     'items': [{'fund_code': fund, 'shares': format(shares, 'f')}
                                               for fund, shares in group_positions.items()]}}
            try:
                response = _retry(lambda: client.call_tool(PORTFOLIO_TOOL, body), retries)
            except MCPError as exc:
                warnings.append('P16 %s 分组取数失败：%s' % (system, exc))
                continue
        p16 = mcp_block_data(response, 16)
        if not p16:
            warnings.append('P16 %s 分组未返回六大板块' % system)
            continue
        result_positions = mcp_block_data(response, 3) or {}
        if (p16.get('holdingDate') != holding_date or result_positions.get('holdingDate') != holding_date
                or current_positions(result_positions) != group_positions):
            warnings.append('P16 %s 分组返回的持仓日期或份额与本次组合不一致' % system)
            continue
        results[system] = {'data': p16, 'fundCodes': funds,
                           'request_ids': response['blocks']['P16'].get('request_ids')}
    return results, warnings


def collect(request, out=None, base=None, timeout=120, selected=None, retries=4, workers=1,
            confirm_cny_prices=False):
    """Fetch the full report and any required industry subgroup data."""
    if selected is not None:
        raise ValueError('新组合工具不支持--only模块裁剪；请全量取数后在本地查看对应模块')
    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        save(out / "request.json", request)
    client = _retry(lambda: MCPClient(base, timeout).connect(), retries)
    if PORTFOLIO_TOOL not in client.tools:
        raise ValueError('MCP服务缺少所需工具：' + PORTFOLIO_TOOL)
    holdings, conversions = (holding_shares(request, client, retries) if confirm_cny_prices
                             else (request['snapshots'], []))
    body = {'action': 'analyze', 'org_id': request['org_id'], 'port_id': request['port_id'],
            'port_holding': holdings, 'start_date': request['start_date'],
            'idx_code': request['benchmark']}
    if request['trades']:
        body['port_trade'] = request['trades']
    if request['end_date'] is not None:
        body['end_date'] = day(request['end_date'])
    started = time.monotonic()
    snapshot = _retry(lambda: client.call_tool(PORTFOLIO_TOOL, body), retries)
    bundle = {'mcp_url': base, 'transport': 'mcp', 'snapshot': snapshot,
              'seconds': round(time.monotonic() - started, 3)}
    if conversions:
        bundle['holding_conversions'] = conversions
    # Persist even a failed business response for local diagnostics.
    if out is not None:
        save(out / "analysis-result.json", bundle)
    if snapshot.get('status') not in ('complete', 'partial'):
        reason = '；'.join(str(e) for e in snapshot.get('errors', [])) or str(snapshot.get('status'))
        raise ValueError('组合分析失败：' + reason)
    if not isinstance(snapshot.get('blocks'), dict) or not isinstance(snapshot.get('data'), dict):
        raise ValueError('组合分析响应缺少blocks/data完整快照')
    meta = snapshot.get('meta', {})
    valuation_day = meta.get('latest_date') or (snapshot['data'].get('1') or {}).get('latestDate')
    if any(s['input_type'] == 'MARKET_VALUE' and s['holding_date'] != valuation_day for s in holdings):
        raise ValueError('金额快照日期与接口估值日不同。请提供实际份额，或确认金额持仓基金在快照日的报价均为人民币后使用 --confirm-cny-prices 按持仓日换算')
    request['end_date'] = day(meta.get('end_date') or request['end_date'])
    request['start_date'] = day(meta.get('start_date') or request['start_date'])
    request['benchmark'] = meta.get('IDX_CODE') or request['benchmark']
    groups, warnings = collect_industry_groups(client, request, snapshot, retries)
    if groups or warnings:
        bundle.update(industry_group_responses=groups, industry_group_warnings=warnings)
    print('get_portfolio_report_data: ' + snapshot['status'], flush=True)
    if out is not None:
        save(out / 'request.json', request)
        if groups or warnings:
            save(out / 'analysis-result.json', bundle)
    return bundle


class InputError(ValueError):
    pass


ALIASES = {
    "total_amount": ("真实持仓总金额", "持仓总金额", "组合总金额", "总持仓金额", "total_amount"),
    "port_name": ("组合名称", "自选基金组合名称", "组合名", "port_name"),
    "I_CODE": ("基金代码", "基金编码", "证券代码", "代码", "i_code"),
    "name": ("基金名称", "基金简称", "证券名称"),
    "BEG_DATE": ("持仓日期", "建仓日期", "建仓日", "持仓日", "日期", "beg_date"),
    "TRADE_DATE": ("交易日期", "成交日期", "trade_date"),
    "TRADE_DIRECTION": ("交易方向", "买卖方向", "trade_direction"),
    "N_WEIGHT": ("权重", "持仓权重", "持仓占比", "占比", "比例", "n_weight"),
    "N_SHARE": ("份额", "持仓份额", "持有份额", "份数", "n_share"),
    "N_MARKET_VALUE": ("市值", "持仓市值", "持有市值", "持仓金额", "持有金额", "交易金额", "成交金额", "交易市值", "金额", "market_value", "n_market_value"),
}
VALUE_FIELDS = ("N_WEIGHT", "N_SHARE", "N_MARKET_VALUE")


def clean(value):
    return unicodedata.normalize("NFKC", "" if value is None else str(value)).strip()


def header(value):
    text = re.sub(r"\s+", "", clean(value)).lower()
    base = text.split("(", 1)[0]
    for field, aliases in ALIASES.items():
        if base in aliases:
            # 单位只从表头括号读取，不从备注里的“万”字猜单位。
            unit = re.search(r"\((万元|万份|万|元|份|%|百分比)\)", text)
            return field, unit.group(1) if unit else ""
    return None


def date_text(value, where):
    if isinstance(value, (dt.datetime, dt.date)):
        return value.strftime("%Y-%m-%d")
    text = clean(value).replace("年", "-").replace("月", "-").replace("日", "")
    text = text.replace("/", "-").replace(".", "-")
    if re.fullmatch(r"\d{8}", text):
        text = text[:4] + "-" + text[4:6] + "-" + text[6:]
    try:
        parts = text.split("-")
        if len(parts) != 3:
            raise ValueError()
        return dt.date(*(int(part) for part in parts)).isoformat()
    except (TypeError, ValueError):
        raise InputError("%s：缺少或无法识别日期，请提供 YYYY-MM-DD；不能从文件时间推断。" % where)


def amount(value, field, unit, where):
    text = clean(value).replace(",", "").replace(" ", "")
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(万元|万份|万|元|份|%)?", text)
    if not match:
        raise InputError("%s：无法识别数值 %r。" % (where, value))
    suffix = match.group(2) or unit
    allowed = {"N_WEIGHT": ("", "%", "百分比"),
               "N_SHARE": ("", "份", "万份", "万"),
               "N_MARKET_VALUE": ("", "元", "万元", "万")}
    if suffix not in allowed[field]:
        raise InputError("%s：单位与持仓口径不一致。" % where)
    try:
        result = Decimal(match.group(1))
    except InvalidOperation:
        raise InputError("%s：数值无效。" % where)
    if suffix in ("万元", "万份", "万"):
        result *= 10000
    if field == "N_WEIGHT":
        if suffix in ("%", "百分比"):
            result /= 100
        elif result > 1:
            raise InputError("%s：权重大于1且无百分号，请明确是40%%还是0.40。" % where)
    if result < 0:
        raise InputError("%s：金额、份额或权重不能为负，卖出请用交易方向。" % where)
    return format(result, "f")


def _choose_portfolio(rows, portfolio):
    choices = sorted({row["_portfolio"] for row in rows})
    if portfolio:
        if portfolio not in choices:
            raise InputError("未找到组合 %r；可选组合：%s" % (portfolio, "、".join(choices)))
        return [row for row in rows if row["_portfolio"] == portfolio], portfolio
    if len(choices) > 1:
        raise InputError("文件含多个组合，请通过 --portfolio 选择；可选组合：%s" % "、".join(choices))
    return rows, choices[0] if choices else "导入基金组合"


def _select_complete(rows, priorities, label):
    complete = [field for field in priorities if all(row.get(field) not in (None, "") for row in rows)]
    if not complete:
        raise InputError("%s：%s至少一列须对全部记录完整填写。" % (label, "、".join(ALIASES[f][0] for f in priorities)))
    return complete[0]


def table_rows(grids, default_date=None, port_name=None, portfolio=None):
    parsed = []
    for sheet_name, grid in grids:
        mapping = None
        for line_no, row in enumerate(grid, 1):
            if not isinstance(row, (list, tuple)):
                raise InputError("%s第%d行必须是数组。" % (sheet_name, line_no))
            candidate = {}
            for index, value in enumerate(row):
                item = header(value)
                if item:
                    candidate[index] = item
            fields = [item[0] for item in candidate.values()]
            if "I_CODE" in fields and any(field in fields for field in VALUE_FIELDS):
                if len(fields) != len(set(fields)):
                    raise InputError("%s：存在重复字段列，请保留唯一的代码、日期及数值列。" % sheet_name)
                mapping = candidate
                continue
            if mapping is None:
                continue
            cells = {field: (row[index] if index < len(row) else None, unit) for index, (field, unit) in mapping.items()}
            active = {key: value for key, value in cells.items() if clean(value[0])}
            if not active or any(clean(value[0]) in ("合计", "总计", "小计") for value in active.values()):
                continue
            where = "%s第%d行" % (sheet_name, line_no)
            raw_code = clean(cells.get("I_CODE", (None, ""))[0])
            if re.fullmatch(r"\d+\.0", raw_code): raw_code = raw_code[:-2]
            if not re.fullmatch(r"\d{1,6}", raw_code):
                raise InputError("%s：缺少或无效的六位基金代码，不按名称猜测。" % where)
            is_trade = "TRADE_DIRECTION" in cells or "TRADE_DATE" in cells or "交易" in clean(sheet_name)
            date_key = "TRADE_DATE" if is_trade else "BEG_DATE"
            raw_date = cells.get(date_key, (None, ""))[0]
            item = {"_portfolio": clean(cells.get("port_name", (None, ""))[0]) or "导入基金组合", "_where": where,
                    "_trade": is_trade, "I_CODE": raw_code.zfill(6),
                    date_key: date_text(raw_date or (default_date if not is_trade else None), where)}
            if is_trade:
                direction = clean(cells.get("TRADE_DIRECTION", (None, ""))[0])
                if direction not in ("买入", "卖出"): raise InputError("%s：交易方向必须为买入/卖出。" % where)
                item["TRADE_DIRECTION"] = direction
            for field in VALUE_FIELDS:
                if field in cells and clean(cells[field][0]): item[field] = amount(cells[field][0], field, cells[field][1], where)
            if not is_trade and 'total_amount' in cells and clean(cells['total_amount'][0]):
                item['total_amount'] = amount(cells['total_amount'][0], 'N_MARKET_VALUE', cells['total_amount'][1], where)
            parsed.append(item)
    if not parsed: raise InputError("未找到有效数据。需含基金代码及数值表头和数据行。")
    parsed, selected_name = _choose_portfolio(parsed, portfolio)
    holding_rows = [row for row in parsed if not row["_trade"]]
    trade_rows = [row for row in parsed if row["_trade"]]
    if not holding_rows: raise InputError("所选组合未找到有效持仓。")
    holdings, by_date, totals = [], {}, {}
    for row in holding_rows: by_date.setdefault(row["BEG_DATE"], []).append(row)
    for holding_date, rows in sorted(by_date.items()):
        codes = [row["I_CODE"] for row in rows]
        if len(codes) != len(set(codes)): raise InputError("%s：同日基金代码重复，请核对，不能自动叠加。" % holding_date)
        field = _select_complete(rows, ("N_SHARE", "N_WEIGHT", "N_MARKET_VALUE"), holding_date + "持仓")
        amounts = {row['total_amount'] for row in rows if 'total_amount' in row}
        if len({Decimal(v) for v in amounts}) > 1:
            raise InputError(holding_date + '：真实持仓总金额存在冲突，请确认')
        if amounts and field == 'N_WEIGHT': totals[holding_date] = next(iter(amounts))
        chosen = [{"I_CODE": row["I_CODE"], "BEG_DATE": holding_date, field: row[field]} for row in rows]
        if not any(Decimal(item[field]) > 0 for item in chosen): raise InputError("%s：持仓数值不能全部为零。" % holding_date)
        holdings.extend(chosen)
    trades = []
    if trade_rows:
        complete = [f for f in ("N_SHARE", "N_MARKET_VALUE") if all(row.get(f) is not None for row in trade_rows)]
        for row in trade_rows:
            field = complete[0] if complete else next((f for f in ("N_SHARE", "N_MARKET_VALUE") if row.get(f) is not None), None)
            if field is None: raise InputError("%s：每条交易须填写份额或交易金额。" % row["_where"])
            if Decimal(row[field]) <= 0: raise InputError("%s：交易份额或市值必须为正数。" % row["_where"])
            trades.append({"I_CODE": row["I_CODE"], "TRADE_DATE": row["TRADE_DATE"], "TRADE_DIRECTION": row["TRADE_DIRECTION"], field: row[field]})
    result = {"port_name": port_name or selected_name, "holdings": holdings,
              "analysis": {"modules": ["gtt_validation", "portfolio_metrics"]}}
    if trades: result["trades"] = trades
    if totals: result['total_amount'] = totals
    return result


def table_input(data, default_date=None, port_name=None, portfolio=None):
    result = table_rows([('转录表格', [data['columns']] + data['rows'])], default_date, port_name, portfolio)
    if data.get('total_amount') is not None:
        checked = canonical(result, total_amount=data['total_amount'])
        result['total_amount'] = {r['holding_date']: r['total_amount_cny']
                                  for r in checked['weight_conversion'] if r['source'] == 'user_actual'}
    return result


def load(path, default_date=None, port_name=None, portfolio=None):
    """普通请求JSON保持原样；table JSON和xlsx经过统一转换。"""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".json", ".xlsx"):
        raise InputError("仅支持.xlsx或JSON；截图须先由模型读图转录，.xls请另存为.xlsx。")
    if ext == ".json":
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise InputError("输入JSON顶层必须是对象。")
        if "columns" not in data and "rows" not in data:
            return data
        if not isinstance(data.get("columns"), list) or not isinstance(data.get("rows"), list):
            raise InputError("转录JSON需包含columns数组和rows二维数组。")
        return table_input(data, default_date, port_name, portfolio)
    try:
        import openpyxl
    except ImportError:
        raise InputError("Excel导入需要openpyxl：请运行 python3 -m pip install openpyxl。")
    book = None
    try:
        # 示例工作簿dimension误写为A1；普通模式读取实际单元格，不受该元数据影响。
        book = openpyxl.load_workbook(path, data_only=False, keep_links=False)
        grids = []
        for sheet in book.worksheets:
            grid = []
            for row in sheet.iter_rows():
                values = []
                for cell in row:
                    if cell.data_type == "f":
                        raise InputError("%s!%s含公式，请在副本中粘贴为值后导入。" % (sheet.title, cell.coordinate))
                    value = cell.value
                    # Excel百分比样式存储的是小数；转为百分数字符串避免按表头再次除100。
                    if isinstance(value, (int, float)) and "%" in cell.number_format:
                        value = str(Decimal(str(value)) * 100) + "%"
                    values.append(value)
                grid.append(values)
            grids.append((sheet.title, grid))
        return table_rows(grids, default_date, port_name, portfolio)
    except InputError:
        raise
    except Exception as exc:
        raise InputError("无法读取Excel：%s" % exc) from None
    finally:
        if book is not None:
            book.close()


ASSETS = {"equityRatio": "股票", "convertibleBondRatio": "可转债", "bondAndReverseRepoRatio": "债券及逆回购",
          "bankDepositRatio": "银行存款", "otherAssetRatio": "其他资产"}
REGIONS = {"aShareRatio": "A股", "hongKongEquityRatio": "港股", "usEquityRatio": "美股", "otherRegionEquityRatio": "其他地区股票"}
SECTORS = {"cyclical": "周期", "industrial": "工业", "financialsRealEstate": "金融地产",
           "consumer": "消费", "healthcare": "医药", "tmt": "TMT"}
MARKET_CAP = {"csi300": "沪深300", "hongKongComposite": "港股综合", "csi500": "中证500",
              "csi1000": "中证1000", "csi2000": "中证2000", "otherAShareMarketCapBelowCny5bn": "其他A股市值低于50亿元"}
RISK12_FIELDS = ("fundReturnContributionRatio", "backtestFundAnnualizedVolatility",
                 "fundAnnualizedRiskContribution", "fundRiskContributionRatio",
                 "fundMarginalRiskContribution", "fundDailyVar", "fundQuarterlyVar",
                 "backtestFundMaxDrawdown")


def numeric(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def fmt(v, unit="", signed=False):
    n = numeric(v)
    if n is None:
        return "—"
    return format(n, "+,.2f" if signed else ",.2f") + unit


def holding_rows(data):
    return [row for row in (data.get('3', {}).get('items') or []) if row.get('portCode')]


def holding_valuation(data):
    rows = holding_rows(data)
    distinct = len({row['portCode'] for row in rows}) == len(rows)
    complete = bool(rows) and distinct and all(numeric(r.get('holdingMarketValue')) is not None for r in rows)
    total = sum(Decimal(str(r['holdingMarketValue'])) for r in rows) if complete else None
    basic = data['2'].get('portfolioTotalHoldingValue')
    basic = Decimal(str(basic)) if numeric(basic) is not None else None
    count = numeric(data['2'].get('heldFundCount'))
    count = int(count) if count is not None and count >= 0 and count.is_integer() else None
    holding_date = data['3'].get('holdingDate')
    basic_date = data['2'].get('statisticsEndDate')
    same_date = bool(holding_date) and holding_date == basic_date
    difference = total - basic if same_date and total is not None and basic is not None else None
    notices = []
    if basic_date and holding_date and not same_date:
        notices.append('组合概况与持仓明细的估值日不同，分别展示各自日期的数据')
    if difference is not None and abs(difference) > Decimal('0.01'):
        notices.append('同日组合总市值与持仓明细合计不一致，分别展示接口总额与明细合计')
    if same_date and count is not None and count != len(rows):
        notices.append('同日组合持有基金数与持仓明细行数不一致')
    if not distinct:
        notices.append('持仓明细有重复基金代码，无法核对明细合计')
    return {'holding_date': holding_date, 'holdings_total_cny': str(total) if total is not None else None,
            'basic_information_date': basic_date, 'basic_information_fund_count': count,
            'basic_information_total_cny': float(basic) if basic is not None else None,
            'total_difference_cny': float(difference) if difference is not None else None,
            'reconciliation_notices': notices}


def valuation(request, data):
    """保留输入金额与接口估值各自口径。"""
    snapshots = []
    for snapshot in request['snapshots']:
        amount = (sum(number(r['market_value']) for r in snapshot['items'])
                  if snapshot['input_type'] == 'MARKET_VALUE' else None)
        snapshots.append({'date': snapshot['holding_date'], 'input_type': snapshot['input_type'],
                          'market_value_cny': str(amount) if amount is not None else None})
    buys = sum(number(r['market_value']) for r in request['trades']
               if r['trade_direction'] == '买入' and r.get('market_value') is not None)
    sells = sum(number(r['market_value']) for r in request['trades']
                if r['trade_direction'] == '卖出' and r.get('market_value') is not None)
    return {**holding_valuation(data),
            'source': 'data.3.items.*.holdingMarketValue', 'includes_trades': False,
            'input_snapshots': snapshots, 'trade_count': len(request['trades']),
            'trade_buy_amount_cny': str(buys), 'trade_sell_amount_cny': str(sells),
            'trade_amounts_complete': all(r.get('market_value') is not None for r in request['trades'])}


def industry_group_summaries(p07, group_responses=None):
    summaries = {}
    group_responses = group_responses or {}
    for system, rows in industry_groups(p07).items():
        response = group_responses.get(system, {})
        p16 = response.get('data', {})
        funds = [row.get('portCode') for row in rows]
        amounts = [numeric(row.get('holdingMarketValue')) for row in rows]
        complete_amounts = all(funds) and len(set(funds)) == len(funds) and None not in amounts
        portfolio_ratios = [numeric(p16.get(key + 'PortfolioRatio')) for key in SECTOR_KEYS]
        summaries[system] = {
            'holdingDate': p07.get('holdingDate'),
            'fundCodes': funds,
            'request_ids': response.get('request_ids'),
            'holdingMarketValue': math.fsum(amounts) if complete_amounts else None,
            'sixSectorEquityNavRatio': math.fsum(portfolio_ratios) if None not in portfolio_ratios else None,
            **{key + 'EquityRatio': numeric(p16.get(key + 'EquityRatio')) for key in SECTOR_KEYS},
        }
    return summaries


def build(request, bundle):
    sources, data, warnings = {}, {}, []
    warnings.extend(bundle.get('industry_group_warnings', []))
    snapshot = bundle.get('snapshot')
    if snapshot is not None:
        warnings.extend(snapshot.get('warnings', []))
        warnings.extend(str(e) for e in snapshot.get('errors', []))
    if request['start_date'] < request['snapshots'][0]['holding_date']:
        warnings.append('回顾起点早于首个持仓快照；快照前结果是接口回溯，不能作为已验证的实际持仓历史')
    for seq, endpoint in ENDPOINTS.items():
        if snapshot is not None:
            block = snapshot['blocks'].get('P%02d' % seq, {})
            status = block.get('status', 'failed')
            value = mcp_block_data(snapshot, seq)
            record = {'ok': status == 'ok', 'http': 200, 'response': {'data': value},
                      'business_ok': status in ('ok', 'no_data', 'not_applicable'),
                      'no_data': status == 'no_data', 'seconds': None,
                      'error': '；'.join(str(e) for e in block.get('errors', [])) or None}
            if status == 'failed' and not block:
                record['error'] = '响应未提供该模块'
        else:
            # Retain compatibility with archived local snapshots; never calls old tools.
            record = bundle.get("records", {}).get(str(seq), {})
        value = record.get("response", {}).get("data")
        ok = record.get("ok") is True and value is not None
        sources[str(seq)] = {"endpoint": endpoint, "ok": ok, "http": record.get("http"),
                             "tool": TOOLS[seq], "transport": "mcp",
                             "business_ok": record.get('business_ok'), "no_data": record.get('no_data', False),
                             "seconds": record.get("seconds"), "error": record.get("error"),
                              "not_requested": record.get("not_requested", False)}
        if snapshot is not None:
            sources[str(seq)].update({k: block.get(k) for k in (
                'actual_dates', 'requested_as_of', 'units', 'denominator',
                'source_api_ids', 'request_ids', 'scope', 'subject')})
            sources[str(seq)].update(status=status, api_id='P%02d' % seq)
        data[str(seq)] = value if ok else {}
        if not ok and not record.get("not_requested"):
            if snapshot is not None and status == 'not_applicable':
                continue
            reason = '暂无该项数据' if record.get('no_data') else record.get('error') or '未取数'
            warnings.append(f'{seq:02d} {endpoint}: {reason}')
        elif isinstance(value, dict):
            for k in ("items", "funds", "series", "periods"):
                if k in value and not value[k]:
                    warnings.append(f"{seq:02d} {k}为空；不能解释为零")
    if any('MID原币价格' in w for w in warnings):
        warnings.append('提示：MID原币价格缺失通常表示后端价格库未覆盖对应基金或持仓日；结合本次blocks/errors定位，必要时用query_fund_reference的prices查询核验，再与用户确认持仓或日期。')
    meta = {"name": request["name"], "range_start": request["start_date"], "range_end": request["end_date"],
            "input_snapshot_dates": [s["holding_date"] for s in request["snapshots"]],
            "snapshot_date": data["3"].get("holdingDate"),
            "calculation_date": data["1"].get("latestDate"),
            "report_date": data["1"].get("periodicReportCutoffDate"),
            "report_period": data["1"].get("periodicReportPeriod"),
            "benchmark_code": request["benchmark"],
            "benchmark_name": data["8"].get("comparisonIndexName"),
            "weight_model": request.get("weight_model"),
            "weight_conversion": request.get("weight_conversion", []),
            "risk_backtest_start": data["12"].get("backtestStartDate"),
             "risk_backtest_end": data["12"].get("backtestEndDate")}
    if snapshot is not None:
        meta.update(mcp_run_id=snapshot.get('run_id'), mcp_status=snapshot.get('status'),
                    mcp_schema_version=snapshot.get('schema_version'),
                    requested_as_of=snapshot.get('meta', {}).get('requested_as_of'))
    # Different fixed-period anchors must never be silently joined.
    anchor8, anchor9 = data["8"].get("statisticsEndDate"), data["9"].get("statisticsEndDate")
    risk = {r["periodCode"]: r for r in data["9"].get("periods", [])}
    periods, joined_risk = [], set()
    for p in data["8"].get("periods", []):
        q = dict(p)
        if p["periodCode"] == "REVIEW" or (anchor8 and anchor8 == anchor9):
            q.update(risk.get(p["periodCode"], {}))
            joined_risk.add(p['periodCode'])
        q["anchorDate"] = request["end_date"] if p["periodCode"] == "REVIEW" else anchor8
        periods.append(q)
    for code, row in risk.items():
        if code not in joined_risk:
            q=dict(row)
            q['anchorDate']=request['end_date'] if code=='REVIEW' else anchor9
            q['periodName']=str(q.get('periodName',code))+'（仅风险，截至'+str(q['anchorDate'])+'）'
            periods.append(q)
    if anchor8 and anchor9 and anchor8 != anchor9:
        warnings.append("08与09的固定窗口锚点不同，未合并对应风险数据")
    current_dates = {data[str(i)].get(k) for i, k in [(2, "statisticsEndDate"), (3, "holdingDate"),
                     (6, "holdingDate"), (7, "holdingDate"), (12, "holdingDate"), (13, "holdingDate"),
                     (14, "statisticsEndDate"), (15, "holdingDate"), (16, "holdingDate"), (17, "holdingDate"),
                     (18, "holdingDate"), (19, "holdDate")] if data[str(i)].get(k)}
    if len(current_dates) > 1:
        warnings.append("当前持仓类接口计算日期不一致；不要生成跨日期合并结论")
    risk_rows = data['12'].get('items', [])
    for field in RISK12_FIELDS:
        missing = sum(numeric(row.get(field)) is None for row in risk_rows)
        if missing:
            warnings.append(f'12 {field}缺失或为空（{missing}行）；保留缺失，不补零或跨窗口估算')
    funds = holding_rows(data)
    names = {r["portCode"]: r.get("fInfoName") or r["portCode"] for r in funds}
    contributions = []
    fraction_fields = ["holdingPeriodAverageWeight", "holdingPeriodFundReturnRate", "fundReturnContribution", "currentHoldingWeight"]
    for row in data["11"].get("items", []):
        q = dict(row)
        for k in fraction_fields:
            n = numeric(q.get(k));q[k] = None if n is None else n * 100
        q["fundName"] = q.get("fundName") or names.get(q["fundCode"], q["fundCode"])
        contributions.append(q)
    extrema = {}
    for field in ["portfolioCumulativeReturnRate", "comparisonIndexCumulativeReturnRate"]:
        points = [(r["statisticsDate"], numeric(r.get(field))) for r in data["10"].get("series", [])]
        points = sorted((d, v) for d, v in points if v is not None)
        if points:
            extrema[field] = {"first": points[0], "last": points[-1], "min": min(points, key=lambda p: p[1]),
                              "max": max(points, key=lambda p: p[1])}
    value_summary = valuation(request, data)
    warnings.extend(value_summary['reconciliation_notices'])
    if bundle.get('holding_conversions'):
        value_summary['holding_conversions'] = bundle['holding_conversions']
    # Preserve the raw per-endpoint objects for complete answers, provenance and inspection.
    report = {"schema_version": 2, "meta": meta, "sources": sources, "data": data,
             "valuation": value_summary,
            "portfolio_periods": periods, "contributions_percent": contributions,
            "series_extrema": extrema, "warnings": warnings,
            "unit_rules": {"11": "contributions_percent中四个比例字段已由小数乘100；原始data.11不改动",
                           "12": "12收益/风险指标、权重、贡献占比均为百分数原值，不乘100；年化风险贡献为对组合波动率的贡献，贡献占比另用Ratio字段；边际风险贡献不等于风险占比",
                           "returns_ratios": "其他收益率、仓位、波动率、VaR按各接口百分数原值，禁止重复乘100",
                           "drawdown": "保留原始符号；展示最大回撤幅度时才取绝对值",
                           "correlation": "无量纲；12为基金与组合普通日收益相关性，使用12回溯窗口；13为两两相关性，使用请求回顾窗口",
                            "money": "元；19.stockTotalMv为亿元；收益贡献以%显示，贡献占比使用明确的Ratio字段"}}
    if snapshot is not None:
        # Local contribution normalization retains every original P11 field.
        # The server's differently named already-scaled view is kept separately.
        report['mcp_contributions_percent'] = snapshot.get('contributions_percent')
        report['mcp_unit_rules'] = snapshot.get('unit_rules', {})
    summaries = industry_group_summaries(data['7'], bundle.get('industry_group_responses'))
    if summaries:
        report['industry_group_summaries'] = summaries
    report['warnings'] = list(dict.fromkeys(warnings))
    return report
