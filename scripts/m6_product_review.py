"""Independent product view over two M6 round records."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

import lab

ROOT = lab.ROOT


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def load(path_text):
    path = Path(path_text).resolve()
    if not path.is_file() or path.is_symlink() or path.name != 'round.json':
        raise RuntimeError('Product review requires an ordinary M6 round.json')
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('schema') != 'GuiHongM6Round/1.0' or record.get('verdict') != 'PASS':
        raise RuntimeError('Product review refuses a non-PASS round')
    return path, record


def signature(rows, key):
    return {row[key]: {'bytes': row['bytes'], 'sha256': row['sha256']} for row in rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--round-a', required=True)
    parser.add_argument('--round-b', required=True)
    args = parser.parse_args()
    if git('status', '--porcelain'):
        raise RuntimeError('M6 product review requires committed clean exact source')
    source = git('rev-parse', 'HEAD')
    path_a, a = load(args.round_a); path_b, b = load(args.round_b)
    if a['source_sha'] != source or b['source_sha'] != source:
        raise RuntimeError('Product review source does not match both rounds')
    binaries_a = signature(a['build']['artifacts'], 'role')
    binaries_b = signature(b['build']['artifacts'], 'role')
    frontend_a = signature(a['build']['frontend_assets'], 'path')
    frontend_b = signature(b['build']['frontend_assets'], 'path')

    def product_ok(round_record):
        product = round_record['product']
        return (product['desktop']['navigation_visible'] and product['desktop']['search_found'] and
                product['desktop']['accepted'] and product['desktop']['stale_alice_absent_after_bob_login'] and
                product['mobile']['card_visible'] and product['mobile']['rejected'] and
                product['mobile']['viewport'] == [390, 844] and product['cancel']['cancelled'] and
                product['unknown']['unknown_copy'] and not product['cancel']['external_requests'] and
                not product['unknown']['external_requests'] and not product['m4_external_requests'] and
                all(product['classification_cases'].values()))

    cases = {
        'P-01': a['identity'] != b['identity'] and a['checkout_identity'] != b['checkout_identity'] and
                a['source_sha'] == b['source_sha'] == source,
        'P-02': binaries_a == binaries_b and frontend_a == frontend_b and
                set(binaries_a) == {'mailbox', 'ingress', 'delivery'} and bool(frontend_a),
        'P-03': product_ok(a) and product_ok(b),
        'P-04': all(len(item['product']['screenshots']) == 4 and
                    all(row['bytes'] > 0 and len(row['sha256']) == 64 for row in item['product']['screenshots'])
                    for item in (a, b)),
        'P-05': all(all(item['recovery']['snapshot_cases'].values()) and item['recovery']['m3_restart']['equal'] and
                    item['recovery']['m4_restart']['equal'] for item in (a, b)),
        'P-06': all(all(lab_row['clean'] for lab_row in item['cleanup']['labs']) and
                    all(item['cleanup']['ports_free'].values()) for item in (a, b)),
    }
    run = 'guihong-m6review-' + uuid.uuid4().hex
    output = lab.local_run(run, create=True)
    review = {
        'schema': 'GuiHongM6ProductReview/1.0', 'identity': run, 'source_sha': source,
        'reviewer_role': 'independent-product-review', 'verdict': 'PASS' if all(cases.values()) else 'FAIL',
        'cases': cases,
        'rounds': {
            'a': {'identity': a['identity'], 'sha256': hashlib.sha256(path_a.read_bytes()).hexdigest()},
            'b': {'identity': b['identity'], 'sha256': hashlib.sha256(path_b.read_bytes()).hexdigest()},
        },
        'asset_signature': {'binaries': binaries_a, 'frontend': frontend_a},
        'visual_state': 'VISUAL_POLISH_PENDING',
        'scope': {'public_internet_mail': 'NOT_PROVEN', 'final_visual_approval': 'PENDING_HUMAN_M7'},
    }
    lab.write_new(output / 'review.json', json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'identity': run, 'source_sha': source, 'verdict': review['verdict'],
                      'record': (output / 'review.json').relative_to(ROOT).as_posix()}))
    return 0 if review['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
