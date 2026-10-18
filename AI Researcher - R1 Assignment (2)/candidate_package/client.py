"""Endpoint client: OpenAI-compatible via stdlib urllib (Fix: no deps).

Every call carries X-Item-Id. Model/sampling fixed per brief:
ibm-granite/granite-4.2-8b, temperature=1.0, top_p=0.95, reasoning disabled.

Resilience: transient network failures (dropped TLS connections, timeouts,
truncated chunked bodies) are retried with exponential backoff WITHOUT
consuming budget -- the per-item call is only counted once the endpoint
returns a parseable completion. Budget overruns still raise immediately.
"""
import http.client
import json
import os
import socket
import ssl
import time
import urllib.request

# DO NOT CHANGE -- the re-run enforces this model id and the call settings.
MODEL_ID = "ibm-granite/granite-4.2-8b"

# Attempts per logical call + backoff schedule (seconds). Total worst-case
# added latency per call is ~14s, well below the endpoint timeout.
MAX_RETRIES = 4
BACKOFF_S = (2, 4, 8)
READ_TIMEOUT_S = 300


class TransientError(RuntimeError):
    """Retryable network/endpoint failure. Never a budget violation."""


class BudgetExceeded(RuntimeError):
    """Per-item call cap reached. Terminal for this item's repair loop."""



def load_env(repo_root):
    env = {}
    p = os.path.join(repo_root, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


class BudgetCounter:
    def __init__(self, cap):
        self.cap = cap
        self.used = {}

    def check(self, item_id):
        n = self.used.get(item_id, 0)
        if n >= self.cap:
            raise BudgetExceeded("budget exceeded for %s" % item_id)

    def record(self, item_id):
        self.used[item_id] = self.used.get(item_id, 0) + 1


class ModelClient:
    def __init__(self, base_url, api_key, counter, offline=False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.counter = counter
        self.offline = offline
        self.calls_log = []

    # Transient network failures: everything the stdlib raises for a
    # dropped socket / reset connection / timed-out or truncated chunked
    # body, plus non-200 HTTP responses and truncated JSON. Deliberately
    # NOT BudgetExceeded (terminal) and NOT offline-mode errors.
    _TRANSIENT = (TimeoutError, ConnectionError, socket.timeout,
                  socket.gaierror, ssl.SSLError, ssl.SSLZeroReturnError,
                  http.client.HTTPException, urllib.error.URLError,
                  json.JSONDecodeError)

    def chat(self, item_id, messages, max_retries=MAX_RETRIES):
        """One model call. Returns text. Counts against per-item budget.

        Budget is consumed only when the endpoint returns a parseable
        completion: failed attempts sleep BACKOFF_S and retry, so a flaky
        network cannot silently eat the 1x/3x/10x cap. Raises
        BudgetExceeded without retrying once the cap is reached, and
        TransientError if all attempts fail.
        """
        self.counter.check(item_id)
        if self.offline:
            raise RuntimeError("offline mode: no model available")
        url = self.base_url + "/chat/completions"
        body = {
            "model": MODEL_ID,
            "messages": messages,
            "temperature": 1.0,
            "top_p": 0.95,
            "extra_body": {"reasoning": {"enabled": False}},
        }
        data = json.dumps(body).encode("utf-8")
        last = None
        for attempt in range(max_retries):
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + self.api_key,
                         "X-Item-Id": item_id})
            try:
                with urllib.request.urlopen(req,
                                            timeout=READ_TIMEOUT_S) as r:
                    if getattr(r, "status", 200) != 200:
                        raise http.client.HTTPException(
                            "HTTP %s" % getattr(r, "status", "?"))
                    out = json.loads(r.read().decode("utf-8"))
                text = out["choices"][0]["message"]["content"]
            except self._TRANSIENT as e:
                last = e
                if attempt < max_retries - 1:
                    time.sleep(BACKOFF_S[min(attempt,
                                             len(BACKOFF_S) - 1)])
                    continue
                raise TransientError(
                    "endpoint failed %dx for %s: %r"
                    % (max_retries, item_id, e))
            self.counter.record(item_id)
            self.calls_log.append((item_id, text))
            return text
        raise TransientError("endpoint failed for %s: %r" % (item_id, last))
