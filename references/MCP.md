# MCP 接入

- 服务名为 `fund-analysis-9tools`。脚本使用 Streamable HTTP，MCP 地址从 `E_ALLOCATION_MCP_URL` 读取，也可通过 `--mcp-url` 指定。单次请求默认超时 120 秒，可用 `--timeout` 调整。测试环境使用 `demo_org`，无需 API key。正式鉴权读取环境变量 `E_ALLOCATION_MCP_API_KEY`，要求 HTTPS。自定义鉴权头或前缀使用 `E_ALLOCATION_MCP_AUTH_HEADER` 和 `E_ALLOCATION_MCP_AUTH_SCHEME`。
- `get_portfolio_report_data(action="analyze")` 一次编排 P01–P19。发送 `org_id`、`port_id`、`port_holding`、`start_date`、`idx_code`，按需发送 `end_date`、`port_trade`。日期为 YYYY-MM-DD，持仓计量字段二选一，数字用 JSON number。交易只进入 P08–P11，组合工具无需指定模块。
- 行业汇总按完整组合 P07 的 `top5SectorClassificationSystem` 分组。每个非空分组用 P03 的当前持仓日和 `heldFundShares` 作为独立份额快照，通过同一 MCP 工具取 P16。分组请求省略交易、组合标识和对比指数。分组覆盖完整组合时复用完整组合 P16。保留分组 P16 及追踪号，日期、份额不一致或取数失败时记入诊断。
- `query_fund_reference(action="prices")` 批量按基金和持仓日查价。C03 的 `fundPrice` 为原币报价，`hDate` 为供价记录日。只有已核实为人民币且对应原持仓日的价格才可用于人民币金额换份额。该转换避免金额快照被服务按最新日价格折算。
- 对比指数使用单一 `idx_code`。候选通过 P08 真实指数收益和 P10 走势验证。接口没有指数目录工具，用户提供的其他代码仍以实际返回为准。P09 Beta 使用独立固定市场基准。
- 响应优先读结构化内容，否则解析纯 JSON。保留原始快照和每块状态、真实日期、单位、分母与追踪号。部分成功时使用成功块，`no_data` 为空、`not_applicable` 为不适用、`failed` 或 `skipped_dependency` 保留原因。
- 每个工具调用串行，开始时间至少间隔 3 秒。连接失败、超时、HTTP 429/5xx 或 JSON-RPC -32603 按限流头或 1/3/10 秒退避重试。参数、鉴权和业务响应无需重试。保持 MCP 路径。
