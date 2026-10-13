"""Run the sealed M2 browser observations against the owned loopback service."""
import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

import lab


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    arguments = parser.parse_args()
    output = Path(arguments.output).resolve()
    if output.parent != lab.ROOT.resolve() and lab.ROOT.resolve() not in output.parents:
        raise RuntimeError('Browser evidence escaped repository')
    output.mkdir(parents=True, exist_ok=False)
    secrets = json.loads((lab.LAB / 'secrets.json').read_text(encoding='utf-8'))
    external = []
    facts = {'browser': {}, 'desktop': {}, 'mobile': {}, 'stale_response': {}}
    executable = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, locale='zh-CN')
        page = context.new_page()
        page.on('request', lambda request: external.append(request.url) if not request.url.startswith('http://127.0.0.1:18080') else None)
        page.goto('http://127.0.0.1:18080/', wait_until='networkidle')
        page.get_by_label('邮箱地址').fill(secrets['accounts']['alice']['address'])
        page.get_by_label('密码').fill(secrets['accounts']['alice']['password'])
        page.get_by_role('button', name='进入邮箱').click()
        page.get_by_role('heading', name='收件箱').wait_for()
        base_labels = ['写信', '收件箱', '已发邮件', '草稿箱', '归档', '垃圾邮件', '已删除']
        nav_labels = page.locator('nav > .nav-item .nav-label').all_inner_texts()
        pane_overflow = page.locator('.nav-pane,.list-pane,.reader-pane').evaluate_all(
            "els => els.map(e => getComputedStyle(e).overflowY)")
        page.screenshot(path=str(output / 'desktop-inbox.png'), full_page=True)
        page.locator('.message-row').first.click()
        page.locator('.message-detail').wait_for()
        frame = page.locator('iframe.safe-mail')
        safe_text = frame.content_frame.locator('body').inner_text() if frame.count() else page.locator('.plain-mail').inner_text()
        page.screenshot(path=str(output / 'desktop-reader.png'), full_page=True)
        facts['desktop'] = {'navigation': nav_labels, 'expected_navigation': base_labels,
                            'three_scroll_regions': pane_overflow,
                            'safe_projection_contains_script_text': '<script>' in safe_text,
                            'unsafe_script_executed': page.evaluate("Boolean(window.__guihongUnsafeExecuted)"),
                            'reader_subject': page.locator('.mail-header h1').inner_text(),
                            'screenshots': ['desktop-inbox.png', 'desktop-reader.png']}

        # Hold an A detail response in page JavaScript. Logout/login advances ApiClient's
        # generation before the old response is released, exercising the actual stale guard.
        page.evaluate("""() => {
          const original = window.fetch.bind(window); window.__heldResponse = null; window.__holdDetail = true;
          window.fetch = async (...args) => {
            const url = String(args[0]); const response = await original(...args);
            if (window.__holdDetail && /\/api\/mailbox\/messages\/[0-9a-f-]+$/.test(url)) {
              window.__holdDetail = false;
              return await new Promise(resolve => { window.__heldResponse = () => resolve(response); });
            }
            return response;
          };
        }""")
        page.get_by_role('button', name='收件箱').click()
        page.locator('.message-row').first.click(no_wait_after=True)
        deadline = time.monotonic() + 10
        while not page.evaluate("() => window.__heldResponse !== null"):
            if time.monotonic() >= deadline:
                raise RuntimeError('controlled A response was not held')
            time.sleep(.05)
        page.get_by_role('button', name='退出').click()
        page.get_by_label('邮箱地址').fill(secrets['accounts']['bob']['address'])
        page.get_by_label('密码').fill(secrets['accounts']['bob']['password'])
        page.get_by_role('button', name='进入邮箱').click()
        page.get_by_role('heading', name='收件箱').wait_for()
        page.evaluate("window.__heldResponse()")
        page.wait_for_timeout(300)
        body_after_switch = page.locator('body').inner_text()
        facts['stale_response'] = {'b_account_visible': '乙用户' in body_after_switch,
                                   'a_private_marker_absent': 'ALICE-PRIVATE-MARKER' not in body_after_switch,
                                   'held_response_released_after_switch': True}

        context.close()
        mobile = browser.new_context(viewport={'width': 390, 'height': 844}, locale='zh-CN')
        page = mobile.new_page()
        page.goto('http://127.0.0.1:18080/', wait_until='networkidle')
        page.get_by_label('邮箱地址').fill(secrets['accounts']['alice']['address'])
        page.get_by_label('密码').fill(secrets['accounts']['alice']['password'])
        page.get_by_role('button', name='进入邮箱').click()
        page.get_by_role('heading', name='收件箱').wait_for()
        page.screenshot(path=str(output / 'mobile-list.png'), full_page=True)
        page.locator('.message-row').first.click()
        page.locator('.message-detail').wait_for()
        reader_subject = page.locator('.mail-header h1').inner_text()
        page.screenshot(path=str(output / 'mobile-reader.png'), full_page=True)
        page.go_back(); page.wait_for_timeout(250)
        step_after_back = page.locator('.workspace').get_attribute('class')
        facts['mobile'] = {'viewport': [390, 844], 'reader_subject': reader_subject,
                           'step_after_browser_back': step_after_back,
                           'screenshots': ['mobile-list.png', 'mobile-reader.png']}
        facts['browser'] = {'version': browser.version, 'executable': str(executable),
                            'external_requests': sorted(set(external))}
        mobile.close(); browser.close()
    (output / 'browser.json').write_text(json.dumps(facts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'browser_evidence': str(output), 'external_requests': len(set(external))}))


if __name__ == '__main__':
    main()
