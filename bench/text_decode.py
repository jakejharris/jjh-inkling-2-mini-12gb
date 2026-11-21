#!/usr/bin/env python3
"""Text decode check against a running llama-server (standard library only).

Sends two fixed prompts, 400 tokens each, reasoning effort "none", and prints the
server's own prompt and generation speeds (the "timings" block of the reply).

usage:
  python bench/text_decode.py                      # server at http://127.0.0.1:8080
  python bench/text_decode.py --temp 1.0
  python bench/text_decode.py --server http://127.0.0.1:8081
  python3 bench/text_decode.py --curl-exe /mnt/c/Windows/System32/curl.exe   # from WSL, see README
"""
import argparse
import json
import subprocess
import time
import urllib.request

PROMPTS = [
    "Explain how TCP congestion control works, covering slow start, congestion avoidance, "
    "fast retransmit and fast recovery. Be thorough.",
    "Write a Python function that parses an nginx access log line into a dict, with a docstring "
    "and three unit tests.",
]


def post_json(server, path, body, curl_exe=None, timeout=600):
    """POST a JSON body and return the parsed JSON reply.

    With curl_exe set (WSL only), the request goes through Windows curl.exe, because from a
    WSL2 NAT shell 127.0.0.1 is WSL itself, not Windows. The body is passed on stdin.
    """
    data = json.dumps(body).encode()
    url = server.rstrip("/") + path
    if curl_exe:
        p = subprocess.run([curl_exe, "-s", "-m", str(timeout), "-H", "Content-Type: application/json",
                            "--data-binary", "@-", url], input=data, capture_output=True)
        if p.returncode != 0:
            raise RuntimeError(f"curl.exe exit {p.returncode}: {p.stderr.decode(errors='replace')[:300]}")
        return json.loads(p.stdout.decode())
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never send 127.0.0.1 to a proxy
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser(description="Fixed text decode test against llama-server.")
    ap.add_argument("--server", default="http://127.0.0.1:8080")
    ap.add_argument("--temp", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--curl-exe", default=None, help="WSL only: path to Windows curl.exe")
    a = ap.parse_args()

    for i, prompt in enumerate(PROMPTS, 1):
        body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": a.max_tokens,
                "temperature": a.temp, "top_p": 1.0, "top_k": 0, "min_p": 0.0,
                "chat_template_kwargs": {"reasoning_effort": "none"}}
        t0 = time.time()
        j = post_json(a.server, "/v1/chat/completions", body, a.curl_exe)
        wall = time.time() - t0
        t = j.get("timings", {})
        print(json.dumps({"prompt": i, "prompt_tokens": t.get("prompt_n"),
                          "prompt_tok_s": round(t.get("prompt_per_second", 0), 1),
                          "gen_tokens": t.get("predicted_n"),
                          "gen_tok_s": round(t.get("predicted_per_second", 0), 2),
                          "wall_s": round(wall, 1)}), flush=True)


if __name__ == "__main__":
    main()
