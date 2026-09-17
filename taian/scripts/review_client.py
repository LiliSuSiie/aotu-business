"""Configuration-driven authentication and the verified Taian HTTP contracts."""
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AES_KEY_HEX = '31323334353637383930414243444546'
ENDPOINTS = {
    1: ('POST', '/comm/v1/user/login'),
    2: ('GET', '/mobile/village/appraise/info/list'),
    8: ('GET', '/mobile/village/trustee/detail/info'),
    9: ('GET', '/mobile/village/appraise/info/type'),
    11: ('POST', '/mobile/village/trustee/detail/save'),
    28: ('POST', '/mobile/village/appraise/info/resident/save'),
    29: ('POST', '/mobile/village/appraise/info/trustee/list'),
    32: ('POST', '/mobile/village/appraise/info/resident/list'),
    33: ('POST', '/mobile/village/appraise/info/resident'),
}


def encrypt(value):
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    return AES.new(bytes.fromhex(AES_KEY_HEX), AES.MODE_ECB).encrypt(
        pad(value.encode('utf-8'), AES.block_size)).hex()


def load_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        raise RuntimeError('请先填写 taian/config/review.private.json 中的用户名和密码。') from None
    except (ValueError, UnicodeError):
        raise RuntimeError('配置文件不是有效的 UTF-8 JSON。') from None
    if not isinstance(config, dict):
        raise RuntimeError('配置必须是 JSON 对象。')
    for key in ('username', 'password'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise RuntimeError('请填写配置中的 %s；账号密码使用明文，无需手工加密。' % key)
    config.setdefault('baseUrl', 'http://47.98.151.170:8085/xczx/backend')
    url = urllib.parse.urlsplit(config['baseUrl'])
    if url.scheme not in ('http', 'https') or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise RuntimeError('baseUrl 必须是无凭证、无查询参数的 HTTP(S) 服务地址。')
    config['baseUrl'] = config['baseUrl'].rstrip('/')
    return config


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('登录或业务接口发生重定向，已停止。')


class Client:
    def __init__(self, config, audit):
        if encrypt('hh01') != 'c4d94d84638ff343fbc6aa700906a5e6':
            raise RuntimeError('AES 已知样本校验失败。')
        self.config = config
        self.audit = Path(audit) if audit is not None else None
        self.events = []
        self.base_url = config['baseUrl']
        self.headers = {'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded',
                        'Device': 'Android', 'Authorization': '', 'EnterpriseCode': 'null'}
        self.opener = urllib.request.build_opener(NoRedirect)
        self.writes = 0
        self.user_id = None
        self.enterprise = None

    encrypt_house = staticmethod(encrypt)

    def login(self):
        self.headers['Authorization'] = ''
        self.headers['EnterpriseCode'] = 'null'
        self.user_id = self.enterprise = None
        params = {'userName': encrypt(self.config['username']), 'password': encrypt(self.config['password']),
                  'loginType': '4', 'smsType': 'H5'}
        if self.config.get('smsVerifyCode'):
            params['smsVerifyCode'] = str(self.config['smsVerifyCode'])
        data = self.call(1, params).get('data')
        if not isinstance(data, dict) or not isinstance(data.get('token'), str) or not data['token'].strip():
            raise RuntimeError('登录响应没有有效 Token，已停止，不使用历史 Token。')
        if data.get('userId') is None or not data.get('enterpCode'):
            raise RuntimeError('登录响应缺少用户或企业标识，已停止。')
        self.user_id, self.enterprise = str(data['userId']), str(data['enterpCode'])
        self.headers['Authorization'] = data['token']
        self.headers['EnterpriseCode'] = self.enterprise

    def call(self, index, params=None, write=False):
        if index not in ENDPOINTS or write != (index in (11, 28)):
            raise RuntimeError('不允许的接口操作。')
        if index != 1 and not self.headers['Authorization']:
            raise RuntimeError('尚未登录，禁止查询或提交评议。')
        method, path = ENDPOINTS[index]
        params = params or {}
        encoded = urllib.parse.urlencode(params)
        url = self.base_url + path + (('?' + encoded) if method == 'GET' else '')
        request = urllib.request.Request(url, data=encoded.encode() if method == 'POST' else None,
                                         headers=self.headers, method=method)
        event = {'at': datetime.now(timezone.utc).isoformat(), 'recordingTemplate': index,
                 'method': method, 'path': path, 'write': write}
        # Login audit contains neither credentials nor their hashes or the token.
        if index != 1:
            event['requestDigest'] = hashlib.sha256(encoded.encode()).hexdigest()
        start = time.monotonic()
        try:
            with self.opener.open(request, timeout=25) as response:
                raw = response.read()
                result = json.loads(raw)
                event.update(http=response.status, businessCode=result.get('code'))
                if index != 1:
                    event.update(requestId=result.get('requestId'), responseSha256=hashlib.sha256(raw).hexdigest())
                if response.status != 200 or str(result.get('code')) != '0':
                    if index == 1:
                        raise RuntimeError('登录失败：请核对账号密码；若该环境要求短信验证码，请填写有效 smsVerifyCode。不会重试或复用旧 Token。')
                    raise RuntimeError('业务接口失败，已停止；请查看审计业务码，写请求不会自动重试。')
                if write:
                    self.writes += 1
                return result
        except RuntimeError:
            event['errorType'] = 'RuntimeError'
            raise
        except Exception as exc:
            event['errorType'] = type(exc).__name__
            raise RuntimeError('接口请求失败（%s），已停止，不自动重试。' % type(exc).__name__) from None
        finally:
            event['elapsedMs'] = round((time.monotonic() - start) * 1000)
            self.events.append(event)
            if self.audit is not None:
                self.audit.parent.mkdir(parents=True, exist_ok=True)
                with self.audit.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + '\n')


def batch_list(client):
    """The current backend can return recordsTotal=0 for a nonempty last page."""
    result, seen = [], set()
    for page in range(1, 10001):
        response = client.call(2, {'page': page, 'rows': 10})
        rows = response.get('data')
        if not isinstance(rows, list):
            raise RuntimeError('批次列表格式异常。')
        if not rows:
            return result
        for row in rows:
            code = row.get('code')
            if not code or code in seen:
                raise RuntimeError('批次分页出现缺失或重复 code，请重新查询。')
            seen.add(code)
            result.append(row)
        if len(rows) < 10:
            return result
    raise RuntimeError('批次分页超过限制。')


def choose(title, rows, label, input_fn=input, output=print):
    if not rows:
        raise RuntimeError(title + '：没有可选择的数据。')
    output('\n' + title)
    for i, row in enumerate(rows, 1):
        output('%d. %s' % (i, label(row)))
    while True:
        try:
            value = input_fn('输入序号或完整 code（q 退出）：').strip()
        except EOFError:
            raise RuntimeError('终端输入已结束，未自动选择。') from None
        if value.lower() == 'q':
            raise KeyboardInterrupt
        # Exact code takes precedence over a numeric menu index.
        matches = [row for row in rows if row.get('code') == value]
        if len(matches) == 1:
            return matches[0]
        if value.isdecimal() and 1 <= int(value) <= len(rows):
            return rows[int(value)-1]
        output('输入无效，请选择列表中的序号或完整 code。')
