"""Neutral public wording; source snapshots remain untouched."""
import argparse
from pathlib import Path
import re
import zipfile
from html import unescape

_TERMS = ('\x77\x69\x6e\x64', '\u4e07\u5f97', '\u94f6\u6cb3', '\u6668\u661f',
          '\x6d\x6f\x72\x6e\x69\x6e\x67\x73\x74\x61\x72', '\u671d\u9633\u6c38\u7eed',
          '\u540c\u82b1\u987a', '\u805a\u6e90', '\u5f6d\u535a', '\x62\x6c\x6f\x6f\x6d\x62\x65\x72\x67',
          '\u8def\u900f', '\x72\x65\x75\x74\x65\x72\x73', '\u7533\u4e07', '\u7533\u94f6\u4e07\u56fd',
          '\u8d22\u6c47', '\x66\x61\x63\x74\x73\x65\x74', '\x6c\x73\x65\x67',
          '\x72\x65\x66\x69\x6e\x69\x74\x69\x76', '\u6807\u666e\u5168\u7403',
          '\u4e1c\u65b9\u8d22\u5bcc', '\x64\x61\x74\x61\x79\x65\x73', '\u901a\u8054\u6570\u636e')
_PATTERN = re.compile('|'.join(re.escape(t) + (r'(?=Code|Id|ID|全A|[^A-Za-z]|$)' if t.isascii() else '')
                               for t in sorted(_TERMS, key=len, reverse=True)), re.I)
# Exempt only explicit industry-standard labels, not standalone institution names.
_INDUSTRY_LABEL = re.compile(r'\u7533\u4e07(?:一级(?:行业)?(?=配置占股票市值比例|分布|[\s（）()，,。；;：:/<>\"\x27]|$)|前五大行业(?=[\s（）()，,。；;：:/<>\"\x27]|$))')
STOCK_INDUSTRY_NOTE = '注：A股、港股为\u7533\u4e07行业，其他境外股票为GICS行业'
_PUBLIC_LABEL = re.compile(_INDUSTRY_LABEL.pattern + '|' + re.escape(STOCK_INDUSTRY_NOTE))
_FUND_SUFFIX = re.compile(r'(?<![A-Za-z0-9])([0-9]{6})\.?of(?![A-Za-z0-9])', re.I)


def public_text(value):
    # Split narrow labels from ordinary text; no arbitrary-name protection tokens.
    text, parts, start = str(value), [], 0
    for match in _PUBLIC_LABEL.finditer(text):
        parts.extend((_neutral_text(text[start:match.start()]), match.group()))
        start = match.end()
    parts.append(_neutral_text(text[start:]))
    return ''.join(parts)


def _neutral_text(text):
    for term, label in ((_TERMS[13], '境内行业体系'), (_TERMS[12], '境内行业体系'),
                        (_TERMS[3], '市值与价值成长'), (_TERMS[4], '市值与价值成长')):
        text = re.sub(re.escape(term), label, text, flags=re.I)
    for term in _TERMS[:2]:
        text = re.sub(re.escape(term) + '全A', '全A基准指数', text, flags=re.I)
    return _FUND_SUFFIX.sub(r'\1', _PATTERN.sub('数据服务机构', text))


def audit(path):
    failures = []
    def inspect(name, raw):
        for number, line in enumerate(raw.decode('utf-8-sig', errors='replace').splitlines(), 1):
            if _PATTERN.search(_PUBLIC_LABEL.sub('', unescape(line))):
                failures.append('%s:%d：含具体机构名称' % (name, number))
            if _FUND_SUFFIX.search(unescape(line)):
                failures.append('%s:%d：基金代码含非中性后缀' % (name, number))
    path = Path(path)
    for file in sorted(path.rglob('*')) if path.is_dir() else [path]:
        if not file.is_file() or '__pycache__' in file.parts:
            continue
        if file.suffix == '.zip':
            with zipfile.ZipFile(str(file)) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    if '__pycache__/' in info.filename or info.filename.endswith(('.pyc', '.pyo')):
                        failures.append(str(file) + ':' + info.filename + '：含编译缓存')
                    else:
                        inspect(str(file) + ':' + info.filename, archive.read(info))
        elif file.suffix not in ('.pyc', '.pyo'):
            inspect(str(file), file.read_bytes())
    return failures


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='对外名称与发布包检查')
    parser.add_argument('--audit', required=True)
    failures = audit(parser.parse_args().audit)
    for failure in failures:
        print(failure)
    print('检查失败：%d项' % len(failures) if failures else '检查通过')
    raise SystemExit(bool(failures))
