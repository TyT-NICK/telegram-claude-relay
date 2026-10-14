"""A fake Telegram Bot API server that taps buttons and sends replies on cue."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHAT = 42


class FakeTelegram:
    """Records sent messages. For each message sent with buttons, plays the next entry of
    `script`: a list of ("tap", button text), ("reply", text) or ("plain", text) actions."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                method = self.path.rsplit("/", 1)[-1]
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                data = json.dumps({"ok": True, "result": fake.handle(method, body)}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.server.server_port

    def reset(self):
        with self.lock:
            self.updates = []
            self.next_update = 1
            self.next_message = 100
            self.sent = []  # (message_id, text, reply_markup)
            self.edits = []
            self.script = []

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    # ------------------------------------------------------------ Bot API

    def handle(self, method, body):
        if method == "getUpdates":
            deadline = time.time() + min(body.get("timeout", 0), 1)
            while True:
                with self.lock:
                    self.updates = [u for u in self.updates if u["update_id"] >= body.get("offset", 0)]
                    result = list(self.updates)
                if result or time.time() > deadline:
                    return result
                time.sleep(0.1)
        if method == "sendMessage":
            with self.lock:
                self.next_message += 1
                message_id = self.next_message
                self.sent.append((message_id, body["text"], body.get("reply_markup")))
                actions = self.script.pop(0) if body.get("reply_markup") and self.script else []
            if actions:
                threading.Thread(target=self.play, args=(message_id, body["reply_markup"], actions),
                                 daemon=True).start()
            return {"message_id": message_id}
        if method.startswith("edit"):
            self.edits.append(body)
        if method == "getMe":
            return {"username": "fakebot"}
        return True

    # ------------------------------------------------------------ simulated user

    def push(self, update):
        with self.lock:
            update["update_id"] = self.next_update
            self.next_update += 1
            self.updates.append(update)

    def tap(self, message_id, markup, label):
        buttons = [b for row in markup["inline_keyboard"] for b in row]
        btn = next(b for b in buttons if label in b["text"])
        self.push({"callback_query": {
            "id": "cq%d" % self.next_update, "data": btn["callback_data"], "from": {"id": CHAT},
            "message": {"message_id": message_id, "chat": {"id": CHAT}},
        }})

    def message(self, text, reply_to=None):
        msg = {"message_id": 900 + self.next_update, "date": int(time.time()),
               "chat": {"id": CHAT, "type": "private"}, "from": {"id": CHAT}, "text": text}
        if reply_to:
            msg["reply_to_message"] = {"message_id": reply_to}
        self.push({"message": msg})

    def play(self, message_id, markup, actions):
        time.sleep(0.3)
        for kind, arg in actions:
            if kind == "tap":
                self.tap(message_id, markup, arg)
            else:
                self.message(arg, reply_to=message_id if kind == "reply" else None)
            time.sleep(0.3)
