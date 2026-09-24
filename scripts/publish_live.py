# -*- coding: utf-8 -*-
"""增量推送实盘部署文件（feishu 模块 + A4 实时推送器 + 修复版扫描器 + README）。
用法：python publish_live.py <TOKEN>
复用 publish_repo.py 的 curl 直连/代理重试方案，带 SHA 更新已存在文件。
"""
import sys, os, json, base64, subprocess, tempfile, time

TOKEN = sys.argv[1]
REPO = 'd-variant-strategy'
API = 'https://api.github.com'
PROXY = 'http://127.0.0.1:7897'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

FILES = [
    'README.md',                    # 根目录（更新部署说明）
    'scripts/csb_signal_scanner.py',  # 更新：代理/curl/重试
    'scripts/feishu.py',            # 新增：飞书推送模块
    'scripts/feishu_config.json',   # 新增：webhook 配置
    'scripts/s28_a4_live.py',       # 新增：A4 实时推送器
    'scripts/publish_live.py',      # 新增：本脚本
]


def read_bytes(p):
    return open(os.path.join(ROOT if p.startswith('scripts/') else HERE, p), 'rb').read()


def curl(method, url, payload=None):
    last = (None, None)
    for attempt in range(5):
        cmd = ['curl.exe', '-sS', '-X', method, '--max-time', '25',
               '-H', f'Authorization: token {TOKEN}', '-H', 'User-Agent: trae',
               '-H', 'Accept: application/vnd.github+json',
               '-o', '-', '-w', '\n%{http_code}']
        tmp = None
        if payload is not None:
            tmp = os.path.join(tempfile.gettempdir(), f'gh_body_{os.getpid()}.json')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f)
            cmd += ['-H', 'Content-Type: application/json', '--data-binary', f'@{tmp}']
        for proxy_opt in ([], ['-x', PROXY] if attempt % 2 == 1 else ['--noproxy', '*']):
            full = cmd + proxy_opt + [url]
            try:
                r = subprocess.run(full, capture_output=True, text=True, timeout=60)
            except Exception:
                r = None
            if r is not None and r.returncode == 0:
                out = r.stdout
                body, _, code = out.rpartition('\n')
                code = code.strip()
                try:
                    j = json.loads(body) if body.strip() else None
                except Exception:
                    j = body.strip() or None
                if code in ('200', '201', '404', '422', '409'):
                    return j, code
                last = (j, code)
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
        time.sleep(2)
    return last


def curl_json(url):
    for attempt in range(5):
        for proxy_opt in ([], ['-x', PROXY]):
            cmd = ['curl.exe', '-sS', '--max-time', '25', '-H', f'Authorization: token {TOKEN}',
                   '-H', 'User-Agent: trae', '-H', 'Accept: application/vnd.github+json'] + proxy_opt + [url]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            except Exception:
                continue
            if r is not None and r.returncode == 0 and r.stdout.strip():
                try:
                    return json.loads(r.stdout)
                except Exception:
                    return r.stdout.strip()
        time.sleep(2)
    return None


me = curl_json(f'{API}/user')
OWNER = me['login']
print(f'登录用户: {OWNER}')

ok, fail = 0, 0
for p in FILES:
    try:
        b = read_bytes(p)
    except FileNotFoundError as e:
        print(f'!! 缺本地文件 {p} ({e})'); continue
    payload = {'message': f'deploy: {p}', 'content': base64.b64encode(b).decode()}
    # 已存在则带 sha（否则 422）
    meta = curl_json(f'{API}/repos/{OWNER}/{REPO}/contents/{p}')
    if isinstance(meta, dict) and meta.get('sha'):
        payload['sha'] = meta['sha']
    resp, code = curl('PUT', f'{API}/repos/{OWNER}/{REPO}/contents/{p}', payload)
    if code in ('200', '201'):
        ok += 1
        print(f'ok {p} ({len(b)}B){" 更新" if payload.get("sha") else " 新增"}')
    else:
        fail += 1
        print(f'!! {p} HTTP {code}: {str(resp)[:160]}')

print(f'\n完成: ok={ok} fail={fail}')
print(f'→ https://github.com/{OWNER}/{REPO}')