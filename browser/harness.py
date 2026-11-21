#!/usr/bin/env python3
"""Browser-use trial for Inkling 2 Mini served by llama-server.

Each step: take a screenshot of a headless Chromium page -> send it to the model with the task
and the previous actions -> the model replies with one JSON action (click, type, key, scroll,
done) -> run it. Every click is scored against the DOM.

usage:
  python browser/harness.py --install-browser       (once: downloads Playwright's headless Chromium into .browsers/)
  python browser/harness.py <run_label> coords|som [--scale 0.75] [--tasks login,shop]

  coords  the model answers with pixel coordinates (pure visual grounding)
  som     interactive elements get red numbered boxes and the model also gets a list of them

Writes browser/runs/<run_label>/steps.jsonl, summary.json, screenshots and raw replies.
Summarize with: python browser/summarize.py

The browser is Playwright's own headless Chromium. It never opens a window.
The "wiki" task loads the public en.wikipedia.org main page (read-only); leave it out with --tasks.
"""
import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGES = HERE / "pages"
# Keep Playwright's browser inside the clone (.browsers/) unless the user chose a location.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(HERE.parent / ".browsers"))
W, H = 1280, 800

TASKS = {
    "login": dict(url=(PAGES / "login.html").as_uri(),
                  goal="Sign in with username 'demo' and password 'hunter2'."),
    "shop": dict(url=(PAGES / "shop.html").as_uri(),
                 goal="Add the cheapest blue mug to the cart (only that one)."),
    "settings": dict(url=(PAGES / "settings.html").as_uri(),
                     goal="Go to Settings, turn on Dark mode, and save the changes."),
    "newsletter": dict(url=(PAGES / "newsletter.html").as_uri(),
                       goal="Subscribe to the newsletter with the email test@example.com and weekly frequency."),
    "wiki": dict(url="https://en.wikipedia.org/wiki/Main_Page",
                 goal="Use the site's search box to open the Wikipedia article about Ada Lovelace."),
}


def state(page, task):
    return page.evaluate("""(t) => {
      const b = document.body ? document.body.dataset : {};
      const q = (s) => document.querySelector(s);
      return {url: location.href, done: b.done||null, cart: b.cart||'', view: b.view||null, saved: b.saved||null, sub: b.sub||null,
              u: q('#u') ? q('#u').value : null, p: q('#p') ? q('#p').value : null,
              dark: q('#dark') ? q('#dark').checked : null, email: q('#e') ? q('#e').value : null,
              weekly: q('#fw') ? q('#fw').checked : null};
    }""", task)


def success(task, s):
    if task == "login": return s["done"] == "1"
    if task == "shop": return s["cart"] == "3"
    if task == "settings":
        try: return json.loads(s["saved"] or "{}").get("dark") is True
        except Exception: return False
    if task == "newsletter":
        try:
            j = json.loads(s["sub"] or "{}"); return j.get("email") == "test@example.com" and j.get("freq") == "weekly"
        except Exception: return False
    if task == "wiki": return "Ada_Lovelace" in s["url"]


def failed_terminal(task, s):
    if task == "shop": return s["cart"] not in ("", "3")
    if task == "newsletter": return s["sub"] is not None and not success(task, s)
    return False


def expected(task, s):
    """Acceptable data-targets for the next action given the page state (None = not scored per step)."""
    if task == "login":
        if (s["u"] or "").strip() != "demo": return {"username"}
        if s["p"] != "hunter2": return {"password"}
        return {"login"}
    if task == "shop": return {"add-3"}
    if task == "settings":
        if s["view"] != "settings": return {"nav-settings"}
        if not s["dark"]: return {"dark"}
        return {"save"}
    if task == "newsletter":
        if s["email"] != "test@example.com": return {"email"}
        if not s["weekly"]: return {"weekly"}
        return {"subscribe"}
    return None


TARGET_AT = """([x,y]) => { let e = document.elementFromPoint(x,y); if(!e) return null;
  if (e.tagName==='LABEL' && e.htmlFor) { const i=document.getElementById(e.htmlFor); if(i) e=i; }
  const t = e.closest('[data-target]'); if (t) return t.dataset.target;
  const l = e.closest('label'); if (l && l.htmlFor) { const i=document.getElementById(l.htmlFor); if (i && i.dataset.target) return i.dataset.target; }
  return (e.tagName||'').toLowerCase() + (e.id?('#'+e.id):'') }"""

SOM_JS = """() => {
  document.querySelectorAll('.__som').forEach(n=>n.remove());
  const els = [...document.querySelectorAll('a,button,input,select,textarea,[role=button],[onclick]')].filter(e=>{
    const r=e.getBoundingClientRect(); const st=getComputedStyle(e);
    return r.width>2&&r.height>2&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth&&st.visibility!=='hidden'&&st.display!=='none'});
  const out=[];
  els.forEach((e,i)=>{const r=e.getBoundingClientRect(); const id=i+1;
    const b=document.createElement('div'); b.className='__som';
    b.style.cssText=`position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;outline:2px solid #e00;z-index:2147483646;pointer-events:none`;
    const l=document.createElement('div'); l.className='__som'; l.textContent=id;
    l.style.cssText=`position:fixed;left:${Math.max(0,r.left-2)}px;top:${Math.max(0,r.top-14)}px;background:#e00;color:#fff;font:bold 11px Arial;padding:0 3px;z-index:2147483647;pointer-events:none`;
    document.body.appendChild(b); document.body.appendChild(l);
    let txt=(e.innerText||e.value||e.placeholder||e.getAttribute('aria-label')||e.name||'').trim().replace(/\\s+/g,' ').slice(0,40);
    if(e.tagName==='INPUT'){const lab=e.id&&document.querySelector('label[for="'+e.id+'"]'); txt=(e.type||'text')+' input'+(lab?(' "'+lab.innerText.trim()+'"'):'')+(e.placeholder?(' placeholder="'+e.placeholder+'"'):'')+(e.type==='checkbox'||e.type==='radio'?(e.checked?' [checked]':' [unchecked]'):(e.value?(' value="'+e.value+'"'):''));}
    out.push({id, tag:e.tagName.toLowerCase(), text:txt, cx:Math.round(r.left+r.width/2), cy:Math.round(r.top+r.height/2)})});
  return out; }"""

SYS_COORDS = (
    "You control a web browser to complete a task. Each turn you get the task, your previous actions, and a screenshot "
    "of the current page ({w}x{h} pixels). Reply with exactly one JSON object for the next action and nothing else:\n"
    '{{"action":"click","x":X,"y":Y}}  click at pixel X,Y of the screenshot\n'
    '{{"action":"type","x":X,"y":Y,"text":"..."}}  click the field at X,Y, clear it, and type text\n'
    '{{"action":"key","key":"Enter"}}  press a key\n'
    '{{"action":"scroll","direction":"down"}}\n'
    '{{"action":"done"}}  when the task is complete\n'
    "Coordinates are integer pixels in the screenshot.")
SYS_SOM = (
    "You control a web browser to complete a task. Each turn you get the task, your previous actions, a screenshot of the "
    "current page where every interactive element has a red box and a red number label, and the list of those elements. "
    "Reply with exactly one JSON object for the next action and nothing else:\n"
    '{"action":"click","id":N}  click element N\n'
    '{"action":"type","id":N,"text":"..."}  click field N, clear it, and type text\n'
    '{"action":"key","key":"Enter"}  press a key\n'
    '{"action":"scroll","direction":"down"}\n'
    '{"action":"done"}  when the task is complete')


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


def call_model(a, messages, outpath):
    body = {"messages": messages, "max_tokens": a.max_tokens, "temperature": 0.0, "top_p": 1.0, "top_k": 0,
            "min_p": 0.0, "chat_template_kwargs": {"reasoning_effort": a.effort}, "cache_prompt": True}
    t = time.time()
    j = post_json(a.server, "/v1/chat/completions", body, a.curl_exe)
    j["_wall_s"] = round(time.time() - t, 3)
    outpath.write_text(json.dumps(j, indent=1), encoding="utf-8")
    return j


def parse_action(txt):
    m = re.findall(r"\{[^{}]*\}", txt or "")
    for s in reversed(m):
        try:
            a = json.loads(s)
            if "action" in a: return a
        except Exception: pass
    return None


def scaled_jpeg(path, size):
    from PIL import Image  # only needed with --scale
    buf = io.BytesIO()
    Image.open(path).resize(size).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def main():
    if sys.argv[1:] == ["--install-browser"]:
        print("installing Playwright headless Chromium into", os.environ["PLAYWRIGHT_BROWSERS_PATH"], flush=True)
        sys.exit(subprocess.call([sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"]))
    ap = argparse.ArgumentParser(description="Browser-use trial for a llama-server vision model (headless Chromium).")
    ap.add_argument("label", help="run name; output goes to browser/runs/<label>/")
    ap.add_argument("mode", choices=["coords", "som"])
    ap.add_argument("--server", default="http://127.0.0.1:8080", help="llama-server base URL")
    ap.add_argument("--curl-exe", default=None, help="WSL only: send requests through this Windows curl.exe")
    ap.add_argument("--effort", default="minimal", help="chat_template_kwargs.reasoning_effort (default minimal)")
    ap.add_argument("--scale", type=float, default=1.0, help="resize the screenshot sent to the model (0.75 = 960x600)")
    ap.add_argument("--tasks", default=",".join(TASKS), help="comma list from: " + ",".join(TASKS))
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=600)
    ap.add_argument("--chrome", default=None, help="optional Chromium executable (default: Playwright's own)")
    ap.epilog = "First run once: python browser/harness.py --install-browser"
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright

    rd = HERE / "runs" / a.label
    rd.mkdir(parents=True, exist_ok=True)
    stepf = open(rd / "steps.jsonl", "a", encoding="utf-8")
    iw, ih = int(W * a.scale), int(H * a.scale)
    summary = []
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True, executable_path=a.chrome)
        for task in a.tasks.split(","):
            T = TASKS[task]
            pg = br.new_page(viewport={"width": W, "height": H})
            pg.goto(T["url"], wait_until="load", timeout=30000)
            hist = []; ok = False; steps = 0
            for step in range(1, a.max_steps + 1):
                steps = step
                s0 = state(pg, task); exp = expected(task, s0)
                som = pg.evaluate(SOM_JS) if a.mode == "som" else None
                shot = rd / f"{task}_{step}.jpg"
                pg.screenshot(path=str(shot), type="jpeg", quality=85, scale="css")
                if a.mode == "som": pg.evaluate("() => document.querySelectorAll('.__som').forEach(n=>n.remove())")
                img = shot.read_bytes() if a.scale == 1.0 else scaled_jpeg(shot, (iw, ih))
                b64 = base64.b64encode(img).decode()
                sysmsg = SYS_COORDS.format(w=iw, h=ih) if a.mode == "coords" else SYS_SOM
                txt = f"Task: {T['goal']}\nPrevious actions: {json.dumps(hist) if hist else 'none'}\n"
                if a.mode == "som":
                    txt += "Elements:\n" + "\n".join(f"[{e['id']}] {e['tag']}: {e['text']}" for e in som) + "\n"
                txt += "Next action JSON:"
                msgs = [{"role": "system", "content": sysmsg},
                        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                                                      {"type": "text", "text": txt}]}]
                try:
                    j = call_model(a, msgs, rd / f"{task}_{step}.resp.json")
                    msg = j["choices"][0]["message"]; tm = j.get("timings", {})
                except Exception as ex:
                    stepf.write(json.dumps(dict(task=task, step=step, mode=a.mode, err=f"request failed: {ex}"[:200], correct=None)) + "\n"); stepf.flush()
                    print(f"request failed on {task} step {step}: {ex}", flush=True)
                    break
                act = parse_action(msg.get("content")) or parse_action(msg.get("reasoning_content"))
                hit = None; err = None
                try:
                    if act is None: err = "no-json"
                    elif act["action"] in ("click", "type"):
                        if a.mode == "som":
                            e = next(e for e in som if e["id"] == int(act["id"])); x, y = e["cx"], e["cy"]
                        else:
                            x, y = float(act["x"]) / a.scale, float(act["y"]) / a.scale
                        hit = pg.evaluate(TARGET_AT, [x, y])
                        pg.mouse.click(x, y)
                        if act["action"] == "type":
                            pg.keyboard.press("Control+A"); pg.keyboard.type(str(act.get("text", "")))
                    elif act["action"] == "key": pg.keyboard.press(str(act.get("key", "Enter")))
                    elif act["action"] == "scroll": pg.mouse.wheel(0, 500 if act.get("direction", "down") == "down" else -500)
                    elif act["action"] == "done": pass
                    else: err = "unknown-action"
                except Exception as ex:
                    err = f"exec: {ex}"[:200]
                try: pg.wait_for_load_state("load", timeout=15000)
                except Exception: pass
                time.sleep(0.4)
                s1 = state(pg, task)
                correct = None if exp is None else (hit in exp)
                if act and act.get("action") == "done": correct = None if exp is None else success(task, s0)
                row = dict(task=task, step=step, mode=a.mode, effort=a.effort, scale=a.scale, action=act, hit=hit, expected=sorted(exp) if exp else None,
                           correct=correct, err=err, prompt_n=tm.get("prompt_n"), cache_n=tm.get("cache_n"), prompt_ms=round(tm.get("prompt_ms", 0)),
                           gen_n=tm.get("predicted_n"), gen_ms=round(tm.get("predicted_ms", 0)), wall_s=j["_wall_s"],
                           reasoning_chars=len(msg.get("reasoning_content") or ""), content=(msg.get("content") or "")[:300])
                stepf.write(json.dumps(row) + "\n"); stepf.flush()
                print(json.dumps({k: row[k] for k in ("task", "step", "action", "hit", "correct", "prompt_n", "prompt_ms", "gen_n", "gen_ms", "wall_s")}), flush=True)
                hist.append(act if act else {"invalid": (msg.get("content") or "")[:80]})
                if success(task, s1): ok = True; break
                if failed_terminal(task, s1) or (act and act.get("action") == "done"): break
            summary.append(dict(task=task, success=ok, steps=steps))
            pg.close()
        br.close()
    (rd / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
