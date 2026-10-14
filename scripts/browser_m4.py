"""Observe M4 classification controls and decisions in real Edge."""
import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

import lab


def login(page, address, password):
    page.goto('http://127.0.0.1:18080/', wait_until='networkidle')
    page.get_by_label('邮箱地址').fill(address)
    page.get_by_label('密码').fill(password)
    page.get_by_role('button', name='进入邮箱').click()
    page.get_by_role('heading', name='收件箱').wait_for()


def open_subject(page, subject):
    page.get_by_role('button').filter(has_text=subject).first.click()
    page.get_by_text('CLASSIFICATION · SUGGESTED', exact=False).wait_for(timeout=15000)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--desktop-subject', required=True)
    parser.add_argument('--mobile-subject', required=True)
    parser.add_argument('--stale-subject', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if not output.is_relative_to(lab.ROOT.resolve()) or output.exists():
        raise RuntimeError('Browser output must be a new repository-owned directory')
    output.mkdir(parents=True)
    secrets = json.loads((lab.LAB / 'secrets.json').read_text(encoding='utf-8'))
    external = []
    facts = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
        browser_version = browser.version
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, locale='zh-CN')
        page = context.new_page()
        page.on('request', lambda request: external.append(request.url) if not request.url.startswith('http://127.0.0.1:18080') else None)
        login(page, secrets['accounts']['alice']['address'], secrets['accounts']['alice']['password'])
        navigation_labels = ['写信', '收件箱', '已发邮件', '草稿箱', '归档', '垃圾邮件', '已删除']
        navigation_visible = all(page.get_by_role('button', name=label, exact=True).count() == 1 for label in navigation_labels)
        page.get_by_label('搜索邮件').fill(args.desktop_subject)
        page.get_by_role('button', name='搜索', exact=True).click()
        page.get_by_role('button').filter(has_text=args.desktop_subject).first.wait_for()
        search_found = True
        page.get_by_label('搜索邮件').fill(''); page.get_by_role('button', name='搜索', exact=True).click()
        tools = page.get_by_text('智能分类设置', exact=True)
        tools.click()
        page.get_by_text('算法仅接收本账户的发件地址、域名和主题散列特征。').wait_for()
        row = page.locator('.rule-row').filter(has_text='browser-probe').first
        priority = row.locator('input[type="number"]')
        before_priority = priority.input_value()
        priority.fill('799'); priority.blur()
        page.wait_for_timeout(400)
        after_priority = priority.input_value()
        open_subject(page, args.desktop_subject)
        reason = page.locator('.classification-card').inner_text()
        page.get_by_role('button', name='接受并人工锁定').click()
        page.get_by_text('建议已确认并锁定为人工分类。').wait_for()
        desktop_shot = output / 'desktop.png'; page.screenshot(path=str(desktop_shot), full_page=True)

        # Delay only the Alice classification call. Session generation must discard its late result after Bob logs in.
        page.evaluate("""() => {
          const original = window.fetch.bind(window);
          window.fetch = (input, init) => {
            const url = String(input);
            if (url.includes('/classification') && !url.includes('/decision') && !url.includes('/settings') && !url.includes('/rules')) {
              return new Promise((resolve, reject) => setTimeout(() => original(input, init).then(resolve, reject), 1500));
            }
            return original(input, init);
          };
        }""")
        page.get_by_role('button', name='收件箱').click()
        page.get_by_role('button').filter(has_text=args.stale_subject).first.click()
        page.get_by_role('button', name='退出').click()
        page.get_by_label('邮箱地址').fill(secrets['accounts']['bob']['address'])
        page.get_by_label('密码').fill(secrets['accounts']['bob']['password'])
        page.get_by_role('button', name='进入邮箱').click()
        page.get_by_role('heading', name='收件箱').wait_for()
        page.wait_for_timeout(1900)
        stale_absent = page.get_by_text(args.stale_subject, exact=True).count() == 0 and page.locator('.classification-card').count() == 0
        facts['desktop'] = {'reason': reason, 'accepted': True, 'priority_before': before_priority,
                            'priority_after': after_priority, 'stale_alice_absent_after_bob_login': stale_absent,
                            'navigation_visible': navigation_visible, 'search_found': search_found,
                            'screenshot': desktop_shot.name}
        context.close()

        mobile = browser.new_context(viewport={'width': 390, 'height': 844}, locale='zh-CN')
        page = mobile.new_page()
        page.on('request', lambda request: external.append(request.url) if not request.url.startswith('http://127.0.0.1:18080') else None)
        login(page, secrets['accounts']['alice']['address'], secrets['accounts']['alice']['password'])
        open_subject(page, args.mobile_subject)
        page.get_by_role('button', name='拒绝建议').click()
        page.get_by_text('建议已拒绝，不会作为正样本。').wait_for()
        mobile_shot = output / 'mobile-390.png'; page.screenshot(path=str(mobile_shot), full_page=True)
        facts['mobile'] = {'viewport': [390, 844], 'rejected': True, 'card_visible': page.locator('.classification-card').is_visible(),
                           'screenshot': mobile_shot.name}
        mobile.close(); browser.close()
    facts['browser_version'] = browser_version
    facts['external_requests'] = sorted(set(external))
    (output / 'browser.json').write_text(json.dumps(facts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(facts, ensure_ascii=False))


if __name__ == '__main__':
    main()
