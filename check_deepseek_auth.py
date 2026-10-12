"""Read-only authentication diagnostic. Never saves keys or response bodies."""
import getpass
import argparse
import json
import urllib.error
import urllib.request
import warnings
import re


def error_details(exc, key):
    """Only expose bounded identifiers and allowlisted descriptions, never raw bodies."""
    def identifier(value):
        if not isinstance(value, str) or key in value or re.search(r'sk-|bearer', value, re.I):
            return '未提供或已隐藏'
        return value if re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value) else '未提供或已隐藏'
    request_id = identifier((exc.headers or {}).get('x-request-id'))
    try:
        raw = exc.read(65537)
        data = json.loads(raw) if len(raw) <= 65536 else {}
        error = data.get('error', {}) if isinstance(data, dict) else {}
        if not isinstance(error, dict):
            error = {}
        code = identifier(error.get('code') or error.get('type'))
        message = error.get('message', '')
        message = message.lower() if isinstance(message, str) else ''
        if 'api key' in message and any(word in message for word in ('invalid', 'incorrect')):
            explanation = '平台错误说明指向API密钥无效或不正确；需核对密钥与账号。'
        elif 'authentication' in message or 'unauthorized' in message:
            explanation = '平台错误说明指向身份认证失败。'
        else:
            explanation = '平台说明未匹配安全展示规则，原文未输出。'
    except (ValueError, OSError, TypeError):
        code, explanation = '未取得', '未取得可解析的错误说明。'
    return f'\n平台错误代码：{code}\n错误说明（安全摘要）：{explanation}\n平台请求编号：{request_id}'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(key, opener=None, direct=False):
    key = key.strip()
    if not key or not key.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key):
        return 'LOCAL_INPUT_INVALID: 密钥为空或含空白/非ASCII字符；未发送请求。'
    if key.startswith(('"', "'", 'Bearer ')) or key.endswith(('"', "'")):
        return 'LOCAL_INPUT_INVALID: 只输入密钥本身，不加引号或Bearer前缀；未发送请求。'
    request = urllib.request.Request(
        'https://api.deepseek.com/user/balance',
        headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}, method='GET')
    try:
        handlers = [NoRedirect]
        if direct:
            handlers.append(urllib.request.ProxyHandler({}))
        with (opener or urllib.request.build_opener(*handlers)).open(request, timeout=20) as response:
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                return 'UNEXPECTED_RESPONSE: 未取得预期余额响应，不能确认认证结果。'
            data = json.loads(raw)
            if not isinstance(data, dict) or type(data.get('is_available')) is not bool:
                return 'UNEXPECTED_RESPONSE: 响应结构异常，不能确认认证结果。'
            available = '充足' if data['is_available'] else '不足'
            return f'AUTH_OK: 官方余额接口认证成功；接口报告余额{available}。未请求模型回答。'
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            details = error_details(exc, key)
        finally:
            exc.close()
        if code == 401:
            return 'AUTH_FAILED_401: 本次余额查询也认证失败；尚不能仅凭此确定具体原因。' + details
        return f'HTTP_ERROR_{code}: 查询失败；未请求模型回答。' + details
    except (urllib.error.URLError, OSError, TimeoutError):
        return 'NETWORK_ERROR: 连接失败或超时；不能判断密钥是否有效。'
    except (ValueError, TypeError):
        return 'UNEXPECTED_RESPONSE: 响应解析失败；未打印响应内容。'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--direct', action='store_true', help='Bypass explicit system proxies for this request only')
    args = parser.parse_args()
    print('本次连接：' + ('不使用系统显式代理（不改变系统设置）' if args.direct else '使用默认网络设置'))
    print('仅查询官方余额接口一次，不调用模型，不保存密钥；禁止转发请求到重定向地址。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('DeepSeek API Key (hidden input): ')
    except getpass.GetPassWarning:
        print('当前终端不支持隐藏输入，已停止。请在本机PowerShell运行。')
        return
    except (EOFError, KeyboardInterrupt):
        print('\n已取消，未发送请求。')
        return
    try:
        print(check(key, direct=args.direct))
    finally:
        del key


if __name__ == '__main__':
    main()
