"""Anonymous GitHub prerelease and asset readback for the M6 candidate."""
import argparse
import hashlib
import json
import subprocess
import urllib.parse
import urllib.request
import uuid

import lab

ROOT = lab.ROOT
REPOSITORY = 'NoctilumeDev/GuiHongMail'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def opener(proxy):
    handlers = [urllib.request.ProxyHandler({'http': proxy, 'https': proxy})] if proxy else []
    return urllib.request.build_opener(*handlers)


def request_json(client, url):
    request = urllib.request.Request(url, headers={'User-Agent': 'GuiHongMail-M6-readback', 'Accept': 'application/vnd.github+json'})
    with client.open(request, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def asset_digest(client, url):
    request = urllib.request.Request(url, headers={'User-Agent': 'GuiHongMail-M6-readback', 'Accept': 'application/octet-stream'})
    digest = hashlib.sha256(); size = 0
    with client.open(request, timeout=120) as response:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            size += len(block); digest.update(block)
    return size, digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--expected-source', required=True)
    parser.add_argument('--asset', action='append', required=True, help='NAME=SHA256')
    parser.add_argument('--proxy')
    args = parser.parse_args()
    if git('status', '--porcelain'):
        raise RuntimeError('M6 release readback requires committed clean exact source')
    if git('rev-parse', 'HEAD') != args.expected_source:
        raise RuntimeError('M6 release readback source is not current checkout')
    expected = {}
    for item in args.asset:
        name, separator, wanted = item.partition('=')
        if not separator or not name or len(wanted) != 64 or any(character not in '0123456789abcdef' for character in wanted):
            raise RuntimeError('Invalid expected release asset')
        expected[name] = wanted
    client = opener(args.proxy)
    api = 'https://api.github.com/repos/' + REPOSITORY
    release = request_json(client, api + '/releases/tags/' + urllib.parse.quote(args.tag, safe=''))
    ref = request_json(client, api + '/git/ref/tags/' + urllib.parse.quote(args.tag, safe=''))
    target = ref['object']['sha']
    if ref['object']['type'] == 'tag':
        target = request_json(client, api + '/git/tags/' + target)['object']['sha']
    runs = request_json(client, api + '/actions/runs?head_sha=' + args.expected_source + '&branch=main&status=completed&per_page=20')
    successful = [row for row in runs.get('workflow_runs', []) if row.get('conclusion') == 'success']
    public_assets = {row['name']: row for row in release.get('assets', [])}
    observations = []
    for name, wanted in sorted(expected.items()):
        row = public_assets.get(name)
        if row is None:
            raise RuntimeError('Expected release asset is missing: ' + name)
        size, actual = asset_digest(client, row['browser_download_url'])
        observations.append({'name': name, 'expected_sha256': wanted, 'sha256': actual,
                             'bytes': size, 'api_bytes': row['size'], 'download_url': row['browser_download_url'],
                             'verified': actual == wanted and size == row['size']})
    facts = {
        'schema': 'GuiHongM6ReleaseReadback/1.0', 'identity': 'guihong-m6release-' + uuid.uuid4().hex,
        'source_sha': args.expected_source, 'tag': args.tag, 'tag_target_sha': target,
        'release_url': release['html_url'], 'draft': release['draft'], 'prerelease': release['prerelease'],
        'assets': observations,
        'main_ci': [{'id': row['id'], 'url': row['html_url'], 'name': row['name']} for row in successful],
    }
    facts['verdict'] = ('PASS' if target == args.expected_source and not facts['draft'] and facts['prerelease'] and
                        len(observations) == len(expected) and all(row['verified'] for row in observations) and successful
                        else 'FAIL')
    output = lab.local_run(facts['identity'], create=True)
    lab.write_new(output / 'readback.json', json.dumps(facts, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'identity': facts['identity'], 'source_sha': args.expected_source, 'verdict': facts['verdict'],
                      'record': (output / 'readback.json').relative_to(ROOT).as_posix()}))
    return 0 if facts['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
