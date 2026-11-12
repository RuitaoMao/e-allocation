---
name: e-allocation-mcp
description: 用 MCP 分析用户的基金组合持仓、业绩、风险、相关性或穿透配置，接受 Excel、JSON、图片或文字输入，交付固定数据报告和带图表的 AI 分析报告。
---

# 基金组合分析

## 选择回顾期和对比指数

用户已给出的选择直接沿用。缺哪项，只让用户选哪项。优先在本轮用一次交互式选择工具展示所有缺失项，在 Codex 可用 `request_user_input_async` 或当前模式的选择工具。等用户选定后继续取数。自定义日期和指数代码请直接在同一界面自由输入。宿主没有选择工具时，才在聊天里发一个合并菜单。候选项的顺序不代表默认选择。

```bash
python3 "<skill>/scripts/run.py" --options --input "<xlsx 或 JSON>"
```

`--options` 只读本地输入，输出已选字段和待选菜单。自然语言已明确的信息也传给该命令。回顾期可选首个持仓日起、首个持仓年份年初起，或自定义起止日。预设的终点默认是接口最新可用估值日，也可指定截止日。对比指数只支持单一代码，候选菜单来自已核验的指数。自定义日期用 `--start-date` 和 `--end-date`，预设用 `--review-period`，指数用 `--benchmark`。用户明确接受某一选项后才执行 prepare。

## 取数和交付

配置 `E_ALLOCATION_MCP_URL`，或通过 `--mcp-url` 指定已授权的接入地址。详见 [MCP.md](references/MCP.md)。

```bash
python3 "<skill>/scripts/run.py" --input "<xlsx 或 JSON>" --prepare \
  --review-period since-holding --benchmark 000300
python3 "<skill>/scripts/run.py" --finalize "<prepared>" --analysis "<prepared>/analysis.json"
```

上面的回顾期和指数是调用示例。先取完整组合数据，再按持仓分组补取需要的行业板块数据。用户要求复用已有快照时，沿用该快照的选择。历史金额持仓按原持仓日报价先换算份额，只有报价均已确认是人民币才加 `--confirm-cny-prices`。权重持仓须提供对应日期的真实总金额。详见 [INPUT.md](references/INPUT.md)。

prepare 后，读取同一次返回的完整 `analysis_context` 和 `analysis_prompt`。根据组合特点组织短文、图表和必要的表格，直接写入 `analysis.json`。图表使用快照提供的预设或引用实际数值，证据使用阅读视图中的真实 JSON 指针。分析可以复用数据报告图表，并说明从图中得到的判断。参考 [ANALYSIS_PROMPT.md](references/ANALYSIS_PROMPT.md)。

两份报告共用页首「数据说明」。数据报告只保留模板已有的脚注，分析报告不加脚注、图注或独立的补充说明。日期或窗口需要标注时放在标题括号内。对账、缺失模块等诊断保留在取数结果，缺失数值使用模板占位。

finalize 离线校验并发布数据与分析两份 HTML。两份使用同一快照。JSON 或证据校验失败时修正分析文件或用 `--repair`，复用本次目录。回复附两份报告链接和简短结论。需要说明数据缺失时，点明受影响的指标或日期。明确的技能维护和数据诊断按实际任务处理。

## 数据边界

- 基金代码使用六位数字字符串，保留前导零。请求不带基金代码后缀。股票代码和实际指数代码保持原样。
- 公开内容使用中性来源名称，行业按实际体系标注（申万一级行业）或 GICS。报告证据是中性展示副本，原始响应仅保留在本地运行快照。发布技能包前运行 `scripts/provider_policy.py --audit`。
- 当前持仓估值、含交易回顾业绩、固定份额风险回溯和基金披露期是不同口径。依据模块的实际日期、分母、单位和状态解释。缺失保持空值。
- 接入、字段和故障处理见 [MCP.md](references/MCP.md)。当前数据报告口径见 [REPORT.md](references/REPORT.md)。
