"""Small Streamable HTTP MCP client; portfolio data never uses REST endpoints."""
import json
import os
import re
import socket
import threading
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

HOLDING_SCHEMA = {'type': 'object', 'properties': {
    'items': {'type': 'array', 'items': {'type': 'object', 'properties': {
        field: {'type': 'number'} for field in ('shares', 'market_value', 'weight')}}}}}


class MCPError(ValueError):
    def __init__(self, message, http=200, retryable=False, retry_after=None):
        super().__init__(message)
        self.http = http
        self.retryable = retryable
        self.retry_after = retry_after


def adapt(value, schema):
    """Adapt JSON numeric fields without changing stored canonical input."""
    kind = schema.get('type')
    if kind == 'string' and isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if kind in ('number', 'integer') and isinstance(value, str):
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError('MCP数值必须有限')
        return int(number) if number == number.to_integral_value() else float(number)
    if kind == 'object' and isinstance(value, dict):
        properties = schema.get('properties', {})
        return {key: adapt(item, properties.get(key, {})) for key, item in value.items()}
    if kind == 'array' and isinstance(value, list):
        return [adapt(item, schema.get('items', {})) for item in value]
    return value


def business_payload(result):
    if result.get('isError'):
        # Do not echo gateway text: it can contain request/authentication details.
        status = 200
        for block in result.get('content', []):
            match = re.search(r'\bstatus:\s*(\d{3})\b', block.get('text', ''))
            if match:
                status = int(match.group(1))
                break
        raise MCPError('MCP工具执行失败（isError=true，HTTP %s）；未取得业务数据' % status,
                       http=status, retryable=status >= 500)
    payload = result.get('structuredContent')
    if isinstance(payload, dict):
        return payload
    for block in result.get('content', []):
        if block.get('type') != 'text':
            continue
        text = block.get('text', '')
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        if isinstance(payload, dict):
            return payload
    raise MCPError('MCP响应缺少纯JSON业务对象')


class MCPClient:
    def __init__(self, url=None, timeout=120):
        url = url or os.environ.get('E_ALLOCATION_MCP_URL')
        if not url:
            raise ValueError('请设置 E_ALLOCATION_MCP_URL 或通过 --mcp-url 提供 MCP 地址')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('MCP URL须为不含凭证、查询参数或片段的HTTP(S)地址')
        if '/mcp-servers/' not in parsed.path or parsed.path.rstrip('/').endswith('/sse'):
            raise ValueError('请提供Streamable HTTP MCP地址（不是REST接口或旧SSE地址）')
        self.url, self.timeout = url, timeout
        self.session = None
        self.protocol = '2024-11-05'
        self.tools = {}
        self._counter = 0
        self._lock = threading.Lock()
        self._tool_lock = threading.Lock()
        self._last_call = None
        # No authentication by default. Future credentials stay out of arguments/files.
        self._token = os.environ.get('E_ALLOCATION_MCP_API_KEY', '')
        self._auth_header = os.environ.get('E_ALLOCATION_MCP_AUTH_HEADER', 'Authorization')
        self._auth_scheme = os.environ.get('E_ALLOCATION_MCP_AUTH_SCHEME', 'Bearer')
        if self._token and parsed.scheme != 'https':
            raise ValueError('带认证的MCP连接须使用HTTPS')

    def _rpc(self, method, params=None, notification=False):
        with self._lock:
            self._counter += 1
            request_id = self._counter
        body = {'jsonrpc': '2.0', 'method': method}
        if not notification:
            body['id'] = request_id
        if params is not None:
            body['params'] = params
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': self.protocol}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        if self._token:
            headers[self._auth_header] = ((self._auth_scheme + ' ') if self._auth_scheme else '') + self._token
        try:
            request = Request(self.url, data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8'), headers=headers)
            with urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get('Mcp-Session-Id')
                if session:
                    self.session = session
                if notification:
                    return None
                if 'text/event-stream' in response.headers.get('Content-Type', ''):
                    payload = self._read_sse(response, request_id)
                else:
                    payload = json.load(response)
                status = response.status
                remaining = response.headers.get('x-ratelimit-remaining')
                reset = response.headers.get('x-ratelimit-reset')
        except HTTPError as exc:
            raise MCPError('MCP网关HTTP %s%s' % (exc.code, '：请确认平台认证配置' if exc.code in (401, 403) else ''),
                           http=exc.code, retryable=exc.code == 429 or exc.code >= 500) from None
        except (URLError, socket.timeout, TimeoutError, OSError):
            raise MCPError('MCP网关连接失败或超时', http=0, retryable=True) from None
        except ValueError:
            raise MCPError('MCP响应不是合法JSON') from None
        if not isinstance(payload, dict) or payload.get('id') != request_id:
            raise MCPError('MCP响应ID不匹配')
        if 'error' in payload:
            error = payload['error']
            code = error.get('code') if isinstance(error, dict) else None
            retry_after = None
            if remaining == '0' and reset is not None:
                try:
                    retry_after = max(0, float(reset))
                except (ValueError, TypeError):
                    pass
            raise MCPError('MCP服务繁忙或暂时不可用（code=-32603）' if code == -32603 else
                           'MCP JSON-RPC错误（code=%s）' % code, http=status,
                           retryable=code == -32603, retry_after=retry_after)
        if not isinstance(payload.get('result'), dict):
            raise MCPError('MCP响应缺少result对象')
        return payload['result']

    @staticmethod
    def _read_sse(response, request_id):
        data = []
        for raw in response:
            line = raw.decode('utf-8').rstrip('\r\n')
            if line.startswith('data:'):
                data.append(line[5:].lstrip(' '))
            elif not line and data:
                event = json.loads('\n'.join(data))
                data = []
                if isinstance(event, dict) and event.get('id') == request_id:
                    return event
        if data:
            event = json.loads('\n'.join(data))
            if isinstance(event, dict) and event.get('id') == request_id:
                return event
        raise MCPError('MCP事件流没有返回对应请求的结果')

    def connect(self):
        result = self._rpc('initialize', {'protocolVersion': self.protocol, 'capabilities': {},
                           'clientInfo': {'name': 'e-allocation-mcp', 'version': '1.0.0'}})
        protocol = result.get('protocolVersion')
        if protocol not in ('2024-11-05', '2025-03-26', '2025-06-18'):
            raise MCPError('MCP服务返回不支持的协议版本')
        self.protocol = protocol
        self._rpc('notifications/initialized', notification=True)
        cursor, seen = None, set()
        while True:
            page = self._rpc('tools/list', {'cursor': cursor} if cursor else {})
            for tool in page.get('tools', []):
                self.tools[tool['name']] = tool
            cursor = page.get('nextCursor')
            if not cursor:
                break
            if cursor in seen:
                raise MCPError('MCP工具分页游标重复')
            seen.add(cursor)
        return self

    def call_tool(self, name, arguments):
        if name not in self.tools:
            raise MCPError('MCP服务未提供工具：' + name)
        schema = self.tools[name].get('inputSchema', {})
        missing = set(schema.get('required', [])) - set(arguments)
        if missing:
            raise MCPError('MCP工具缺少必填参数：' + ', '.join(sorted(missing)))
        # Normalize canonical Decimal strings to JSON numbers, including union schemas.
        schema = dict(schema, properties=dict(schema.get('properties', {})))
        schema.setdefault('type', 'object')
        holding = arguments.get('port_holding')
        if holding is not None:
            schema['properties']['port_holding'] = ({'type': 'array', 'items': HOLDING_SCHEMA}
                                                     if isinstance(holding, list) else HOLDING_SCHEMA)
        if 'port_trade' in arguments:
            schema['properties']['port_trade'] = {'type': 'array', 'items': {
                'type': 'object', 'properties': {
                    field: {'type': 'number'} for field in ('shares', 'market_value')}}}
        arguments = adapt(arguments, schema)
        # One report is one call. Additional queries/retries share the 20/min budget.
        import time
        with self._tool_lock:
            if self._last_call is not None:
                wait = 3 - (time.monotonic() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
            self._last_call = time.monotonic()
            result = self._rpc('tools/call', {'name': name, 'arguments': arguments})
        return business_payload(result)
