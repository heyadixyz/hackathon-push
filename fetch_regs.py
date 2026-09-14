"""Reads the country registration table from colosseum.com/analytics and writes regs.json."""
import json, re, sys, datetime
from playwright.sync_api import sync_playwright

URL = "https://colosseum.com/analytics"
OUT = "regs.json"
TOP_N = 10
MAX_JUMP = 1.40  # a reading more than 40% above the last one is a scrape bug, not a spike

try:
    from zoneinfo import ZoneInfo
    NPT = ZoneInfo("Asia/Kathmandu")
except Exception:  # no tzdata on the host
    NPT = datetime.timezone(datetime.timedelta(hours=5, minutes=45), "NPT")

NEPAL = ("nepal", "np", "npl")
COUNT_KEYS = ("count", "value", "registrations", "participants", "users")
NAME_KEYS = ("country", "countryname", "country_name", "name", "label",
             "region", "location", "key", "id", "code")


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def pick_count(d):
    """A row's count. Prefer an explicitly named key over guessing with max()."""
    for want in COUNT_KEYS:
        for k, v in d.items():
            if str(k).lower() == want and is_num(v) and v >= 0:
                return int(v)
    nums = [v for v in d.values() if is_num(v) and v > 0]
    return int(max(nums)) if nums else None


def pick_name(d):
    for want in NAME_KEYS:
        for k, v in d.items():
            if str(k).lower() == want and isinstance(v, str) and v.strip():
                return v.strip()
    for v in d.values():
        if isinstance(v, str) and 0 < len(v.strip()) <= 60:
            return v.strip()
    return None


def is_nepal(name):
    return isinstance(name, str) and name.strip().lower() in NEPAL


def country_tables(obj, found):
    """Collect every list that reads like a country/count table."""
    if isinstance(obj, list):
        rows = [x for x in obj if isinstance(x, dict)]
        if len(rows) >= 3 and len(rows) == len(obj):
            good = [(n, c) for n, c in ((pick_name(r), pick_count(r)) for r in rows)
                    if n and c is not None]
            if len(good) >= max(3, int(len(rows) * 0.8)):
                found.append(good)
        for v in obj:
            country_tables(v, found)
    elif isinstance(obj, dict):
        for v in obj.values():
            country_tables(v, found)
    return found


def best_table(payloads):
    """The longest country table that actually has a Nepal row in it."""
    found = []
    for pl in payloads:
        country_tables(pl, found)
    with_nepal = [t for t in found if any(is_nepal(n) for n, _ in t)]
    return max(with_nepal, key=len) if with_nepal else None


def rank_table(table):
    """Fold duplicate names, sort by count descending. Returns [{name, count}]."""
    agg = {}
    for name, count in table:
        if name not in agg or count > agg[name]:
            agg[name] = count
    return [{"name": n, "count": c} for n, c in
            sorted(agg.items(), key=lambda kv: (-kv[1], kv[0].lower()))]


def find_nepal(obj):
    """Fallback: walk any payload looking for a single country row for Nepal."""
    if isinstance(obj, dict):
        if any(is_nepal(v) for v in obj.values() if isinstance(v, str)):
            c = pick_count(obj)
            if c:
                return c
        for v in obj.values():
            r = find_nepal(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_nepal(v)
            if r:
                return r
    return None


def scrape():
    payloads = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()

        def on_response(res):
            try:
                if "json" in res.headers.get("content-type", ""):
                    payloads.append(res.json())
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(4000)
        text = page.inner_text("body")
        b.close()
    return payloads, text


def main():
    payloads, text = scrape()

    total = None
    m = re.search(r"Hackathon Registrations[^\d]*(\d[\d,]*)", text)
    if m:
        total = int(m.group(1).replace(",", ""))

    ranked, nepal, nepal_rank = None, None, None
    table = best_table(payloads)
    if table:
        ranked = rank_table(table)
        for i, row in enumerate(ranked, 1):
            if is_nepal(row["name"]):
                nepal, nepal_rank = row["count"], i
                break

    if nepal is None:
        for pl in payloads:
            nepal = find_nepal(pl)
            if nepal:
                break

    if nepal is None:
        # last resort: a "Nepal" label next to a number in the rendered chart
        m = re.search(r"Nepal\D{0,40}?(\d[\d,]*)", text) or re.search(r"(\d[\d,]*)\D{0,40}?Nepal", text)
        if m:
            nepal = int(m.group(1).replace(",", ""))

    if nepal is None:
        print("Nepal not found. Is it still in the top ten?", file=sys.stderr)
        sys.exit(1)

    prev = {}
    try:
        with open(OUT) as f:
            prev = json.load(f)
    except Exception:
        pass

    before = prev.get("nepal")
    if isinstance(before, int) and before > 0:
        if nepal < before:
            print("Refusing to write: Nepal read as %d, below the last count of %d. "
                  "The analytics page probably changed shape." % (nepal, before), file=sys.stderr)
            sys.exit(1)
        if nepal > before * MAX_JUMP:
            print("Refusing to write: Nepal read as %d, more than %d%% above the last count of %d. "
                  "That is a scrape bug, not a spike." % (nepal, round((MAX_JUMP - 1) * 100), before),
                  file=sys.stderr)
            sys.exit(1)

    today = datetime.datetime.now(NPT).date().isoformat()
    out = {
        "nepal": nepal,
        "total": total,
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "history": (prev.get("history", []) + [[today, nepal]])[-60:],
    }
    if ranked:
        out["countries"] = ranked[:TOP_N]
        out["nepalRank"] = nepal_rank

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(out)


if __name__ == "__main__":
    main()
