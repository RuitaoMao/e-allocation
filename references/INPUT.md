# 输入与选择

- Excel 遍历各 sheet 按语义识别表头。持仓按组合名和日期形成完整快照，完整列优先级为份额、权重、市值。多组合用 `--portfolio` 选择，`--port-name` 只重命名。缺持仓日可传已确认的 `--date`。公式先在副本粘贴为值，旧格式另存为 .xlsx。
- 份额单位为份，金额为人民币元。Excel 的万份、万元由表头转换。权重可写百分比或 [0,1] 小数，须有该日真实持仓总额。单日期可用 `--total-amount "250万元"`、JSON `total_amount` 或 Excel 持仓总金额列。多日期使用日期映射或逐快照金额。重复填写的同日总额不累加。
- 金额持仓包含权重换算后的金额。历史金额必须锁定原持仓日份额。确认全部对应原日报价均为人民币后用 `--confirm-cny-prices`，否则使用实际份额。缺当日价格时停止。金额交易仍原样交给后端处理。
- 交易逐笔给出基金代码、日期、买卖方向，以及份额或人民币金额。交易和持仓快照分别提交。图片或文字转录沿用已确认的代码、日期、数值和单位，可用表格 JSON 的 `columns` 和 `rows`。有歧义时核实。
- 回顾起点用 `--review-period since-holding`、`--review-period holding-year` 或 `--start-date YYYY-MM-DD`。可选 `--end-date YYYY-MM-DD`，省略时由服务使用最新可用估值日。自定义区间可覆盖近一月、近一年等任意有效窗口。选择回顾期不会修改持仓日期。
- `--benchmark` 传一个指数代码。JSON 可用 `analysis.review_period`、`analysis.start_date`、`analysis.end_date`、`analysis.benchmark_code`。常用候选以 `run.py --options` 为准。其他指数取决于服务的行情覆盖。

```json
{
  "port_name": "我的组合",
  "port_holding": {
    "holding_date": "2026-01-02",
    "input_type": "SHARE",
    "items": [{"fund_code": "001513", "shares": 25000}]
  },
  "port_trade": [
    {"fund_code": "001513", "trade_date": "2026-06-10", "trade_direction": "买入", "shares": 5000}
  ],
  "analysis": {"review_period": "since-holding", "benchmark_code": "000905"}
}
```
