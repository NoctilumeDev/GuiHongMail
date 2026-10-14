"""Owned loopback SMTP next hop with finite recipient policies and durable transcripts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socketserver
import threading
import time


class State:
    def __init__(self, policy, output):
        self.policy = policy
        self.output = output
        self.lock = threading.Lock()
        self.counts = {}

    def event(self, value):
        value = {'utc_epoch': time.time(), **value}
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n'
        with self.lock, self.output.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def next_policy(self, recipient):
        with self.lock:
            count = self.counts.get(recipient, 0) + 1
            self.counts[recipient] = count
        selected = self.policy.get('recipients', {}).get(recipient, self.policy.get('default', {'mode': 'accept'}))
        return count, selected


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        connection = f'{self.client_address[0]}:{self.client_address[1]}'
        recipient = ''
        attempt = 0
        selected = {'mode': 'accept'}

        def reply(value):
            self.wfile.write((value + '\r\n').encode('ascii'))
            self.wfile.flush()
            self.server.state.event({'connection': connection, 'direction': 'reply', 'line': value,
                                     'recipient': recipient, 'attempt': attempt})

        reply('220 controlled.guihong.test ESMTP')
        while True:
            line = self.rfile.readline(1002)
            if not line or len(line) > 1000:
                return
            text = line.decode('utf-8', errors='replace').rstrip('\r\n')
            command, _, argument = text.partition(' ')
            command = command.upper()
            self.server.state.event({'connection': connection, 'direction': 'command', 'command': command,
                                     'argument': argument, 'recipient': recipient, 'attempt': attempt})
            if command == 'EHLO':
                reply('250-controlled.guihong.test')
                reply('250 SIZE 5242880')
            elif command == 'MAIL':
                reply('250 Sender accepted')
            elif command == 'RCPT':
                start, end = argument.find('<'), argument.find('>')
                recipient = argument[start + 1:end].lower() if start >= 0 and end > start else ''
                attempt, selected = self.server.state.next_policy(recipient)
                mode = selected.get('mode', 'accept')
                failures = int(selected.get('failures', 0))
                if mode == 'permanent_rcpt':
                    reply('550 Recipient rejected')
                elif mode == 'temporary_rcpt' and attempt <= failures:
                    reply('451 Recipient temporarily unavailable')
                else:
                    reply('250 Recipient accepted')
            elif command == 'DATA':
                reply('354 End data with <CRLF>.<CRLF>')
                content = bytearray()
                while True:
                    part = self.rfile.readline(5 * 1024 * 1024 + 3)
                    if not part or part == b'.\r\n':
                        break
                    if part.startswith(b'..'):
                        part = part[1:]
                    content.extend(part)
                    if len(content) > 5 * 1024 * 1024:
                        reply('552 Message too large')
                        return
                self.server.state.event({'connection': connection, 'direction': 'data', 'recipient': recipient,
                                         'attempt': attempt, 'bytes': len(content),
                                         'sha256': hashlib.sha256(content).hexdigest()})
                mode = selected.get('mode', 'accept')
                failures = int(selected.get('failures', 0))
                if mode == 'unknown':
                    return
                if mode == 'hold':
                    time.sleep(float(selected.get('seconds', 5)))
                if mode == 'temporary_data' and attempt <= failures:
                    reply('451 DATA temporarily unavailable')
                else:
                    reply('250 Queued by controlled next hop')
            elif command == 'QUIT':
                reply('221 Bye')
                return
            else:
                reply('250 OK')


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address, state):
        self.state = state
        super().__init__(address, Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--policy', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    policy_path, output = Path(args.policy).resolve(), Path(args.output).resolve()
    policy = json.loads(policy_path.read_text(encoding='utf-8'))
    if output.exists() or output.parent != policy_path.parent:
        raise RuntimeError('Controlled SMTP output must be a new sibling of its policy')
    output.touch(exist_ok=False)
    state = State(policy, output)
    with Server(('127.0.0.1', 12525), state) as server:
        print(json.dumps({'ready': True, 'address': '127.0.0.1:12525', 'output': str(output)}), flush=True)
        server.serve_forever(poll_interval=.1)


if __name__ == '__main__':
    main()
