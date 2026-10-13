"""Observe the M3 send receipt in real Edge against the owned loopback UI."""
import argparse
import json
from pathlib import Path
import uuid

from playwright.sync_api import sync_playwright

import lab


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=['cancel', 'unknown'], required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if not output.is_relative_to(lab.ROOT.resolve()) or output.exists():
        raise RuntimeError('Browser output must be a new repository-owned directory')
    output.mkdir(parents=True)
    secrets = json.loads((lab.LAB / 'secrets.json').read_text(encoding='utf-8'))
    external = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, locale='zh-CN')
        page = context.new_page()
        page.on('request', lambda request: external.append(request.url) if not request.url.startswith('http://127.0.0.1:18080') else None)
        page.goto('http://127.0.0.1:18080/', wait_until='networkidle')
        page.get_by_label('邮箱地址').fill(secrets['accounts']['alice']['address'])
        page.get_by_label('密码').fill(secrets['accounts']['alice']['password'])
        page.get_by_role('button', name='进入邮箱').click()
        page.get_by_role('heading', name='收件箱').wait_for()
        page.get_by_role('button', name='写信').click()
        page.get_by_label('收件人').fill(f'{args.mode}-browser@test.invalid')
        page.get_by_label('主题').fill('M3 browser ' + args.mode + ' ' + uuid.uuid4().hex[:8])
        page.get_by_label('正文').fill('浏览器发送回执证据')
        page.get_by_role('button', name='发送', exact=True).click()
        page.get_by_role('heading', name='发送意图已耐久保存').wait_for()
        page.get_by_text('SUBMITTED_LOCAL', exact=True).wait_for()
        facts = {'mode': args.mode, 'submitted_local': True, 'browser_version': browser.version,
                 'external_requests': sorted(set(external))}
        if args.mode == 'cancel':
            page.get_by_role('button', name='取消发送').click()
            page.get_by_text('取消裁决已持久保存。').wait_for()
            page.get_by_text('Scope：CANCELLED', exact=False).wait_for()
            facts.update(cancelled=True, scope_text=page.locator('.scope-state').inner_text())
        else:
            page.get_by_text('UNKNOWN', exact=True).wait_for(timeout=20000)
            page.get_by_text('下一跳是否接受无法确认，自动重投已暂停。', exact=False).wait_for()
            before = page.locator('.recipient-result p').nth(0).inner_text()
            page.on('dialog', lambda dialog: dialog.accept())
            page.get_by_role('button', name='确认可能重复并重试').click()
            page.get_by_text('已记录重复风险确认并创建一次重试资格。').wait_for()
            page.get_by_text('尝试 2 次', exact=False).wait_for(timeout=20000)
            facts.update(unknown_copy=True, attempts_before=before,
                         attempts_after=page.locator('.recipient-result p').nth(0).inner_text())
        screenshot = output / (args.mode + '.png')
        page.screenshot(path=str(screenshot), full_page=True)
        facts['screenshot'] = screenshot.name
        context.close(); browser.close()
    (output / 'browser.json').write_text(json.dumps(facts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(facts, ensure_ascii=False))


if __name__ == '__main__':
    main()
