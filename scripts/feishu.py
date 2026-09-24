# -*- coding: utf-8 -*-
"""
飞书自定义机器人 Webhook 推送模块
================================================================
- 固化 webhook 地址到本目录 feishu_config.json（或环境变量 FEISHU_WEBHOOK 覆盖）
- 提供 send_text / send_card 两个函数
- 统一 UTF-8 编码（PowerShell 直接 --data-binary 传中文会因 GBK 错乱导致 9499，务必走本函数写 UTF-8 body）

用法：
    import feishu
    feishu.send_text('hello')
    feishu.send_card(header='标题', template='green', elements=[{'tag':'div','text':{'tag':'lark_md','content':'**加粗**'}}])

独立测试：
    python feishu.py                 # 发一条确认消息
    python feishu.py --card          # 发一条卡片确认消息
"""
import os, json, sys
import urllib.request

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'feishu_config.json')
DEFAULT_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/09c21713-73a7-4348-a2d2-9d92441741ef'


def webhook():
    env = os.environ.get('FEISHU_WEBHOOK', '').strip()
    if env:
        return env
    try:
        with open(CONFIG_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
        return (cfg.get('webhook') or '').strip()
    except Exception:
        return DEFAULT_WEBHOOK


def post(payload):
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(webhook(), data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))


def send_text(text, extra=None):
    payload = {'msg_type': 'text', 'content': {'text': text}}
    if extra:
        payload.update(extra)
    return post(payload)


def send_card(header, template='green', elements=None, note=None):
    """header: 标题字符串；elements: 飞书卡片元素列表（tag=div 用 lark_md）。"""
    el = list(elements or [])
    if note:
        el.append({'tag': 'note', 'elements': [{'tag': 'lark_md', 'content': note}]})
    card = {
        'config': {'wide_screen_mode': True},
        'header': {'template': template, 'title': {'content': header, 'tag': 'plain_text'}},
        'elements': el,
    }
    payload = {'msg_type': 'interactive', 'card': card}
    return post(payload)


def md(el):
    return {'tag': 'div', 'text': {'tag': 'lark_md', 'content': el}}


if __name__ == '__main__':
    card = '--card' in sys.argv
    if card:
        r = send_card('d-variant-strategy 已连接', 'green',
                      [md('✅ 飞书推送通道已打通，后续 A4 冻结策略信号将推送到这里。')])
    else:
        r = send_text('✅ d-variant-strategy 飞书推送模块已上线。')
    print(r)