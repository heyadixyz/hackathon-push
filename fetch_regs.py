"""Reads Nepal's registration count from colosseum.com/analytics and writes regs.json."""
import json, re, sys, datetime
from playwright.sync_api import sync_playwright

URL = "https://colosseum.com/analytics"
OUT = "regs.json"

def find_nepal(obj):
    """Walk any JSON payload looking for a country row for Nepal with a count."""
    if isinstance(obj, dict):
        vals = [str(v).lower() for v in obj.values() if isinstance(v, str)]
        if any(v in ("nepal", "np", "npl") for v in vals):
            nums = [v for v in obj.values() if isinstance(v, (int, float)) and v > 0]
            if nums:
                return int(max(nums))
        for v in obj.values():
            r = find_nepal(v)
            if r: return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_nepal(v)
            if r: return r
    return None

def main():
    nepal, total, payloads = None, None, []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        def on_response(res):
            try:
                ct = res.headers.get("content-type", "")
                if "json" in ct:
                    payloads.append(res.json())
            except Exception:
                pass
        page.on("response", on_response)
        page.goto(URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(4000)
        text = page.inner_text("body")
        b.close()

    m = re.search(r"Hackathon Registrations[^\d]*(\d[\d,]*)", text)
    if m: total = int(m.group(1).replace(",", ""))

    for pl in payloads:
        nepal = find_nepal(pl)
        if nepal: break

    if nepal is None:
        # fallback: a "Nepal" label followed or preceded by a number in the rendered chart
        m = re.search(r"Nepal\D{0,40}?(\d[\d,]*)", text) or re.search(r"(\d[\d,]*)\D{0,40}?Nepal", text)
        if m: nepal = int(m.group(1).replace(",", ""))

    if nepal is None:
        print("Nepal not found. Is it still in the top ten?", file=sys.stderr)
        sys.exit(1)

    prev = {}
    try: prev = json.load(open(OUT))
    except Exception: pass
    out = {"nepal": nepal, "total": total, "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "history": (prev.get("history", []) + [[datetime.date.today().isoformat(), nepal]])[-60:]}
    json.dump(out, open(OUT, "w"), indent=1)
    print(out)

if __name__ == "__main__":
    main()
