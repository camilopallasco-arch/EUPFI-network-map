"""EU-CFA Network tracker: network, overlap and events views built from the EU-CFA Public finance tracker's data.

Run:  python network.py
Reads the tracker's data (TRACKER_DATA_URL below, or data/tracker.json) and data/events.csv; writes site/index.html.
"""
import csv, json, re, pathlib, urllib.request, datetime, unicodedata, collections

# ---------------------------------------------------------------- settings you can edit
# Address of your tracker's data file. On GitHub, open data/tracker.json in your tracker repository,
# click "Raw" and paste that address here. Leave empty to use the copy in data/tracker.json.
TRACKER_DATA_URL = ""
# Address of the main tracker website (used for links back to it). Leave empty to hide the link.
TRACKER_SITE_URL = ""

ROOT = pathlib.Path(__file__).resolve().parent
DATA, SITE, REF = ROOT / "data", ROOT / "site", ROOT / "ref"
for d in (DATA, SITE, REF):
    d.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (EU-CFA network tracker)"}
TODAY = datetime.date.today()
warnings = []

# ---------------------------------------------------------------- 1. load the tracker's data
def get(url, timeout=120):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

if TRACKER_DATA_URL:
    try:
        raw = get(TRACKER_DATA_URL)
        json.loads(raw)
        (DATA / "tracker.json").write_bytes(raw)
        print("downloaded tracker data from", TRACKER_DATA_URL)
    except Exception as e:
        warnings.append(f"Could not download the tracker data ({e}); the last saved copy is used.")
if not (DATA / "tracker.json").exists():
    raise SystemExit("No tracker data: set TRACKER_DATA_URL in network.py or upload data/tracker.json")
T = json.load(open(DATA / "tracker.json", encoding="utf-8"))
generated = T.get("generated", "")

# ---------------------------------------------------------------- 2. scope: EU public financial institutions and EU-financed World Bank trust funds
INCLUDED_TYPES = {"DFI", "Bilateral development bank", "NPB", "ECA", "EU institution", "World Bank trust fund"}
INST = {i["institution_id"]: i for i in T["institutions"] if i["type"] in INCLUDED_TYPES}
COUNTRIES = T["countries"]
MS_NAMES = {"FR": "France", "DE": "Germany", "NL": "Netherlands", "BE": "Belgium", "FI": "Finland", "DK": "Denmark", "SE": "Sweden",
            "AT": "Austria", "ES": "Spain", "IT": "Italy", "PT": "Portugal", "PL": "Poland", "CZ": "Czechia", "SK": "Slovakia",
            "HR": "Croatia", "GR": "Greece", "SI": "Slovenia", "HU": "Hungary", "RO": "Romania", "BG": "Bulgaria", "EE": "Estonia",
            "LV": "Latvia", "LT": "Lithuania", "IE": "Ireland", "LU": "Luxembourg", "EU": "European Union", "WBTF": "World Bank trust funds"}
inv_by_id = {i["investment_id"]: i for i in T["investments"] if i["institution_id"] in INST}

# deals with their Franc Zone allocations
deals = {}
for a in T["allocations"]:
    inv = inv_by_id.get(a["investment_id"])
    if not inv:
        continue
    d = deals.setdefault(inv["investment_id"], {"id": inv["investment_id"], "i": inv["institution_id"], "t": inv["title"][:160],
                                                "y": inv.get("year") or "", "n": inv.get("instrument", ""), "s": inv.get("sector_broad", ""),
                                                "u": inv.get("source_url", ""), "g": inv.get("impl_agency", ""), "v": 0.0, "c": [], "e": False})
    d["v"] += a.get("amount_attributed_eur") or 0
    d["c"].append(a["country"])
    if a.get("attribution_method") == "equal_split_estimate":
        d["e"] = True
deals = {k: v for k, v in deals.items()}

# ---------------------------------------------------------------- 3. network: nodes and weighted links
nodes, links = {}, collections.defaultdict(lambda: {"v": 0.0, "n": 0})
def node(nid, kind, label, **kw):
    if nid not in nodes:
        nodes[nid] = {"id": nid, "k": kind, "l": label, "v": 0.0, **kw}
    return nodes[nid]
for d in deals.values():
    ins = INST[d["i"]]
    node("i:" + d["i"], "institution", ins["name"], t=ins["type"], ms=ins["member_state"])
    nodes["i:" + d["i"]]["v"] += d["v"]
    share = d["v"] / max(1, len(d["c"]))
    for cc in d["c"]:
        node("c:" + cc, "country", COUNTRIES[cc]["name"], u=COUNTRIES[cc].get("union", ""))
        nodes["c:" + cc]["v"] += share
        l = links[("i:" + d["i"], "c:" + cc)]; l["v"] += share; l["n"] += 1
    if d["s"]:
        node("s:" + d["s"], "sector", d["s"])
        nodes["s:" + d["s"]]["v"] += d["v"]
        l = links[("i:" + d["i"], "s:" + d["s"])]; l["v"] += d["v"]; l["n"] += 1
    if d["g"] and ins["type"] == "EU institution":  # EU money entrusted to an implementing agency
        node("a:" + d["g"], "agency", d["g"])
        nodes["a:" + d["g"]]["v"] += d["v"]
        l = links[("i:" + d["i"], "a:" + d["g"])]; l["v"] += d["v"]; l["n"] += 1
for nid, n in list(nodes.items()):
    if n["k"] == "institution" and n.get("ms"):
        node("m:" + n["ms"], "memberstate", MS_NAMES.get(n["ms"], n["ms"]))
        nodes["m:" + n["ms"]]["v"] += n["v"]
        l = links[("m:" + n["ms"], nid)]; l["v"] += n["v"]; l["n"] += 1
# frameworks (programmes): participants and countries, no amounts added up
for p in T.get("programmes", []):
    fid = "f:" + p["programme_id"]
    parts = [("i:" + x) if ("i:" + x) in nodes else ("m:" + x) if ("m:" + x) in nodes else None for x in p["participants"]]
    parts = [x for x in parts if x]
    ccs = ["c:" + c for c in p["countries"] if ("c:" + c) in nodes]
    if not parts or not ccs:
        continue
    node(fid, "framework", p["name"][:90], fk=p["kind"], src=p.get("source_url", ""))
    for x in parts:
        links[(x, fid)]["n"] += 1
    for c in ccs:
        links[(fid, c)]["n"] += 1

# euros each country receives per sector (shown when a country is clicked)
csec = collections.defaultdict(lambda: collections.defaultdict(float))
for d in deals.values():
    if d["s"]:
        for cc in d["c"]:
            csec[cc][d["s"]] += d["v"] / max(1, len(d["c"]))
csec = {cc: {k: round(v) for k, v in sorted(m.items(), key=lambda x: -x[1]) if v > 0} for cc, m in csec.items()}

# ---------------------------------------------------------------- 4. overlap: shared countries and sectors, co-financed projects
cs = collections.defaultdict(lambda: collections.defaultdict(float))  # institution -> (country, sector) -> euros
for d in deals.values():
    for cc in d["c"]:
        cs[d["i"]][(cc, d["s"])] += d["v"] / max(1, len(d["c"]))
top = sorted(cs, key=lambda i: -sum(cs[i].values()))[:24]
matrix = []
for a in top:
    row = []
    for b in top:
        if a == b:
            row.append(round(sum(cs[a].values())))
        else:
            row.append(round(sum(min(v, cs[b].get(k, 0)) for k, v in cs[a].items() if k in cs[b])))
    matrix.append(row)
pair_detail = {}
for ai, a in enumerate(top):
    for bi, b in enumerate(top):
        if bi <= ai:
            continue
        shared = [(k, cs[a][k], cs[b][k]) for k in cs[a] if k in cs[b] and cs[a][k] > 0 and cs[b][k] > 0]
        shared.sort(key=lambda x: -min(x[1], x[2]))
        if shared:
            pair_detail[f"{a}|{b}"] = [[k[0], k[1], round(x), round(y)] for k, x, y in shared[:25]]

STOP = set("""projet project programme program programa support appui appuis renforcement strengthening financement financing development developpement
du des les la le de et pour and the for of in au aux en dans sur with par loan pret grant investment investissement phase facility fund fonds
national nationale regional services service capacite capacity sector secteur public publique additional additionnel contrat convention
contribution agreement tranche force mise oeuvre urgence budgetaire budget sectoriel sectoriels activity under preparation assistance technique
technical emergency corona covid jeunesse youth formation professionnelle insertion women femmes gestion management access acces
objectifs durable sustainable flagship initiative""".split())
# place names: shared place names say nothing about a shared project
PLACES = set("""africa afrique ouest west central centrale sahel ghana nigeria guinee guinea mauritanie mauritania gambie gambia liberia sierra leone
dakar abidjan bamako ouagadougou niamey cotonou porto novo lome bissau yaounde douala bangui ndjamena brazzaville pointe noire libreville malabo kribi
kayes koulikoro sikasso segou mopti tombouctou timbuktu kidal menaka taoudeni tillaberi tahoua maradi zinder dosso agadez diffa sahel kaya bobo dioulasso
koudougou boucle mouhoun centre nord sud est ziguinchor casamance thies kaolack saint louis tambacounda matam kolda sedhiou kedougou fatick louga
diourbel kaffrine yamoussoukro bouake korhogo daloa san pedro man atlantique borgou alibori atacora donga zou collines mono couffo plateau oueme
kara savanes maritime centrale extreme garoua maroua ngaoundere bertoua ebolowa bamenda buea logone chari ouaddai kanem moyen ogooue franceville
port gentil oyem""".split())
def toks(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z]{4,}", t) if w not in STOP and w not in PLACES}
country_words = {w for c in COUNTRIES.values() for w in toks(c["name"])}
df = collections.Counter(w for d in deals.values() for w in toks(d["t"]))
by_cc = collections.defaultdict(list)
for d in deals.values():
    if d["v"] > 0:
        for cc in d["c"]:
            by_cc[cc].append(d)
# a pair of deals from different institutions is a candidate when, in the same country and within three years,
# their titles share one very distinctive word (a dam, railway or company name) or two distinctive words.
groups = collections.defaultdict(dict)   # (country, key word) -> {deal id: deal}
evidence = collections.defaultdict(set)
for cc, ds in by_cc.items():
    for x in range(len(ds)):
        for y in range(x + 1, len(ds)):
            p, q = ds[x], ds[y]
            if p["i"] == q["i"]:
                continue
            if p["y"] and q["y"] and abs(int(p["y"]) - int(q["y"])) > 3:
                continue
            shared = (toks(p["t"]) & toks(q["t"])) - country_words
            rare = sorted((w for w in shared if df[w] <= 5 and len(w) >= 6), key=lambda w: df[w])
            fairly = [w for w in shared if df[w] <= 15]
            if not rare and len(fairly) < 2:
                continue
            key = (cc, rare[0] if rare else " ".join(sorted(fairly)[:2]))
            groups[key][p["id"]] = p; groups[key][q["id"]] = q
            evidence[key].update(rare or fairly)
cofin = []
for key, members in groups.items():
    ms = sorted(members.values(), key=lambda d: -d["v"])
    if len({m["i"] for m in ms}) < 2 or len(ms) > 10:
        continue
    cofin.append({"w": sorted(evidence[key])[:5], "c": [key[0]],
                  "m": [[m["i"], m["t"], m["y"], round(m["v"]), m["u"]] for m in ms], "v": round(sum(m["v"] for m in ms))})
# the same project can surface under two key words: keep one entry per set of deals
seen_sets, uniq = set(), []
for c in sorted(cofin, key=lambda x: -x["v"]):
    sig = frozenset(m[1] + m[0] for m in c["m"])
    if sig in seen_sets:
        continue
    seen_sets.add(sig); uniq.append(c)
cofin = uniq

# ---------------------------------------------------------------- 5. timeline: yearly commitments by type and by country
years = list(range(1999, TODAY.year + 1))
series = collections.defaultdict(lambda: collections.defaultdict(float))
for d in deals.values():
    if not d["y"] or not d["y"].isdigit() or int(d["y"]) < 1999:
        continue
    t = INST[d["i"]]["type"]
    share = d["v"] / max(1, len(d["c"]))
    for cc in d["c"]:
        series["ALL|" + t][int(d["y"])] += share
        series[cc + "|" + t][int(d["y"])] += share
timeline = {k: [round(v.get(y, 0)) for y in years] for k, v in series.items()}

# ---------------------------------------------------------------- 6. events (data/events.csv), with a source check
events = []
for r in csv.DictReader(open(DATA / "events.csv", encoding="utf-8-sig")):
    r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
    if not r.get("date") or not r.get("title"):
        continue
    status = r.get("status") or ("upcoming" if r["date"] > TODAY.isoformat() else "past")
    if status == "upcoming" and r["date"] < TODAY.isoformat():
        status = "past"
    try:
        code = urllib.request.urlopen(urllib.request.Request(r["source_url"], headers=UA), timeout=40).status if r.get("source_url") else "no source"
    except Exception as e:
        code = getattr(e, "code", None) or str(e)[:40]
    if code != 200:
        warnings.append(f"Event \u201c{r['title']}\u201d: source did not answer normally ({code}); check it by hand.")
    events.append({"d": r["date"], "e": r.get("end_date", ""), "st": status, "cat": r.get("category", ""),
                   "cc": r.get("countries", "ALL").split("|"), "t": r["title"], "x": r.get("description", ""), "u": r.get("source_url", "")})
events.sort(key=lambda e: e["d"])

TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>EU-CFA Network tracker</title>
<meta name="description" content="Network, overlap and events of European public financial institutions in the CFA franc zone (WAEMU and CEMAC) since 1999.">
<meta property="og:title" content="EU-CFA Network tracker">
<meta property="og:description" content="How European public financial institutions connect, overlap and react to events in the CFA franc zone.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#040a0f; --panel:#08151d; --panel2:#0a1c26; --ink:#d9f4ff; --muted:#8db1c0; --dim:#56798a; --line:#163746; --line-hi:#2a6a80;
  --accent:#40e8ff; --waemu:#ffbf5c; --cemac:#ff9a7a;
  --t-dfi:#3aa6ff; --t-bdb:#ff8c42; --t-npb:#2dffc8; --t-eca:#ff3d8e; --t-eu:#ffd84a; --t-wbtf:#e0c8a0;
  --k-ms:#ffffff; --k-sec:#7be3c0; --k-ag:#d8b4ff; --k-fw:#9fb4c4;
  --c-mon:#ffd84a; --c-pol:#ff6b6b; --c-eu:#40e8ff; --c-fin:#7be36b; --c-meet:#c592ff;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace; --sans:"IBM Plex Sans","Segoe UI",system-ui,-apple-system,sans-serif;
  color-scheme:dark;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark}}
:root[data-theme="dark"]{color-scheme:dark}
:root{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
*,*::before,*::after{box-sizing:inherit}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--ink);font:400 15px/1.5 var(--sans);display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:20px;padding:12px 22px;border-bottom:1px solid var(--line);flex-wrap:wrap}
header .code{font:500 12px var(--mono);color:var(--muted);letter-spacing:.06em}
header h1{margin:0;font-size:20px;font-weight:600}
nav{display:flex;border:1px solid var(--line-hi);margin-left:auto}
nav button{appearance:none;border:0;background:transparent;color:var(--muted);font:600 14px var(--sans);padding:9px 18px;cursor:pointer}
nav button[aria-pressed="true"]{background:rgba(64,232,255,.08);color:var(--ink);box-shadow:inset 0 -2px 0 var(--accent)}
nav button:focus-visible,button:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
main{flex:1;min-height:0;position:relative}
.view{position:absolute;top:0;right:0;bottom:0;left:0;display:grid;grid-template-columns:minmax(0,1fr) 400px}
.view[hidden]{display:none}
.stage{position:relative;min-height:0;overflow:hidden}
aside{border-left:1px solid var(--line);background:var(--panel);overflow:auto;padding:16px 18px}
aside h2{margin:0 0 4px;font-size:17px}
aside h3{margin:16px 0 6px;font-size:13px;color:var(--muted);font-weight:600}
.hint{font-size:13px;color:var(--muted);margin:4px 0 10px}
.tools{position:absolute;left:14px;top:12px;z-index:2;display:flex;flex-wrap:wrap;gap:6px;max-width:calc(100% - 150px)}
.chip{appearance:none;border:1px solid var(--line);background:rgba(4,12,17,.85);color:var(--ink);padding:5px 10px;font:500 12.5px var(--sans);cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.chip[aria-pressed="false"]{opacity:.4}
.sw{width:9px;height:9px;border-radius:50%;display:inline-block}
.legend{position:absolute;left:14px;bottom:12px;z-index:2;background:rgba(4,12,17,.85);border:1px solid var(--line);padding:8px 10px;font-size:12px;color:var(--muted);display:flex;flex-wrap:wrap;gap:4px 12px;max-width:calc(100% - 28px)}
.legend span{display:inline-flex;align-items:center;gap:5px}
.zoom{position:absolute;right:14px;top:12px;z-index:2;display:flex;gap:4px}
.zoom button{appearance:none;border:1px solid var(--line-hi);background:rgba(4,12,17,.85);color:var(--ink);width:32px;height:32px;font:600 16px var(--sans);cursor:pointer}
select,input[type=range]{font:500 13px var(--sans);color:var(--ink);background:var(--panel2);border:1px solid var(--line);padding:5px 7px}
label.ctl{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--muted);background:rgba(4,12,17,.85);border:1px solid var(--line);padding:3px 8px}
#net{position:absolute;top:0;left:0;width:100%;height:100%;display:block;cursor:grab}
#net3d{position:absolute;top:0;left:0;width:100%;height:100%;display:none}
.use3d #net3d{display:block}
.use3d #net{display:none}
#v-net:fullscreen{background:var(--bg);width:100vw;height:100vh}
#v-net:fullscreen .stage{height:100vh}
.zoom button.fs{width:auto;padding:0 10px;font-size:13px;display:inline-flex;align-items:center;gap:6px}
.scene-tooltip:empty{display:none}
.scene-tooltip{font:500 12.5px var(--sans)!important;color:var(--ink)!important;background:rgba(10,28,38,.92)!important;border:1px solid var(--line-hi);padding:6px 9px!important;border-radius:0!important}
.modenote{position:absolute;right:14px;bottom:12px;z-index:2;font-size:12px;color:var(--muted);background:rgba(4,12,17,.85);border:1px solid var(--line);padding:5px 9px}
svg text{font-family:var(--sans)}
.node{cursor:pointer}
.node text{fill:var(--ink);font-size:10.5px;pointer-events:none;paint-order:stroke;stroke:#000;stroke-width:3px}
.link{stroke-opacity:.35}
.faded{opacity:.08}
.tip{position:fixed;z-index:20;pointer-events:none;background:var(--panel2);border:1px solid var(--line-hi);padding:7px 9px;font-size:12.5px;max-width:300px;box-shadow:0 0 18px rgba(64,232,255,.12)}
.tip b{color:var(--accent)}
.deal{border-top:1px solid var(--line);padding:8px 0;font-size:13px}
.deal a{color:var(--accent)}
.meta{color:var(--muted);font-size:12px}
.amt{font:500 12px var(--mono);color:var(--ink)}
.bar{display:grid;grid-template-columns:minmax(100px,46%) 1fr auto;gap:8px;align-items:center;font-size:12.5px;margin:3px 0}
.bar .track{height:9px;background:rgba(255,255,255,.05);position:relative}
.bar .track i{position:absolute;left:0;top:0;bottom:0}
.bar .val{font:500 11.5px var(--mono);color:var(--muted)}
.big{font:600 24px var(--sans)}
.matrix{overflow:auto;padding:58px 18px 18px;height:100%}
.matrix table{border-collapse:collapse;font-size:11px}
.matrix th{font-weight:500;color:var(--muted);white-space:nowrap;padding:2px 4px}
.matrix th.col{height:150px;vertical-align:bottom}
.matrix th.col div{writing-mode:vertical-rl;transform:rotate(180deg)}
.matrix td{width:28px;height:24px;border:1px solid #0d2430;text-align:center;font:500 9.5px var(--mono);color:#fff;cursor:pointer}
.matrix td.diag{outline:1px solid var(--line-hi)}
.events{padding:58px 18px 18px;height:100%;overflow:auto}
.ev{border-top:1px solid var(--line);padding:9px 0;display:grid;grid-template-columns:120px 1fr;gap:10px;font-size:13px}
.ev .d{font:500 12px var(--mono);color:var(--muted)}
.ev .badge{font:600 11px var(--sans);padding:1px 6px;border:1px solid var(--line-hi);margin-right:6px}
.ev.up .badge{border-color:var(--accent);color:var(--accent)}
.ev a{color:var(--accent);font-size:12.5px}
.warn{font-size:12px;color:#ffc9a8;border:1px dashed #6b3a28;padding:6px 8px;margin-top:8px}
.about{padding:24px;max-width:860px;overflow:auto;height:100%}
.about p,.about li{color:var(--muted)}
.about h2{margin-top:22px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media (max-width:900px){
  .view{grid-template-columns:1fr;grid-template-rows:62vh auto;position:static}
  main{overflow:auto}
  aside{border-left:0;border-top:1px solid var(--line)}
  nav{margin-left:0}
}
</style>
</head>
<body>
<noscript><p style="padding:24px">This tracker needs JavaScript to draw the network.</p></noscript>
<header>
  <div><div class="code">EU-CFA network tracker</div><h1>European public finance in the CFA franc zone: network, overlap, events</h1></div>
  <nav aria-label="Views">
    <button data-v="net" aria-pressed="true">Network</button><button data-v="ovl" aria-pressed="false">Overlap</button>
    <button data-v="evt" aria-pressed="false">Events</button><button data-v="src" aria-pressed="false">Sources</button><button data-v="abt" aria-pressed="false">About</button>
  </nav>
</header>
<main>
  <section class="view" id="v-net">
    <div class="stage" id="netstage">
      <div class="tools" id="layers"></div>
      <div class="zoom"><button id="zin" aria-label="Zoom in">+</button><button id="zout" aria-label="Zoom out">−</button><button id="zreset" aria-label="Reset view">↺</button>
        <button id="fs" class="fs" aria-label="Full screen" title="Full screen (Esc to leave)"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M1 5V1h4M9 1h4v4M13 9v4H9M5 13H1V9" fill="none" stroke="currentColor" stroke-width="1.6"/></svg><span>Full screen</span></button></div>
      <svg id="net" role="img" aria-label="Network of European public financial institutions, countries, sectors and agencies"></svg>
      <div id="net3d" aria-label="Three-dimensional network: drag to rotate, scroll to zoom"></div>
      <div class="modenote" id="modenote" hidden></div>
      <div class="legend" id="netlegend"></div>
    </div>
    <aside id="netpanel"></aside>
  </section>
  <section class="view" id="v-ovl" hidden>
    <div class="stage"><div class="tools"><label class="ctl">Institutions shown <select id="ovn"><option>12</option><option selected>18</option><option>24</option></select></label>
      <label class="ctl">Country <select id="ovc"></select></label></div><div class="matrix" id="matrix"></div></div>
    <aside id="ovlpanel"></aside>
  </section>
  <section class="view" id="v-evt" hidden>
    <div class="stage"><div class="tools" id="evtools"></div><div class="events" id="evmain"></div></div>
    <aside id="evpanel"></aside>
  </section>
  <section class="view" id="v-src" hidden><div class="about" id="sources" style="grid-column:1/-1;max-width:1000px"></div></section>
  <section class="view" id="v-abt" hidden><div class="about" id="about" style="grid-column:1/-1"></div></section>
</main>
<div class="tip" id="tip" hidden></div>
<script>/*__D3__*/</script>
<script>/*__THREE__*/</script>
<script>/*__FG3D__*/</script>
<script>const DATA = /*__DATA__*/null;</script>
<script>
(() => {
const D = DATA, $ = s => document.querySelector(s);
const HAS_WEBGL = (() => { try { const c = document.createElement("canvas"); return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl"))); } catch (e) { return false; } })();
const USE3D = HAS_WEBGL && typeof ForceGraph3D === "function" && typeof THREE !== "undefined";

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = v => v >= 1e9 ? "€" + (v/1e9).toFixed(1) + " bn" : v >= 1e6 ? "€" + (v/1e6).toFixed(v >= 1e8 ? 0 : 1) + " m" : v >= 1e3 ? "€" + Math.round(v/1e3) + " k" : "€" + Math.round(v || 0);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const TYPEVAR = {"DFI":"--t-dfi","Bilateral development bank":"--t-bdb","NPB":"--t-npb","ECA":"--t-eca","EU institution":"--t-eu","World Bank trust fund":"--t-wbtf"};
const TYPELABEL = {"DFI":"DFI","Bilateral development bank":"Development bank","NPB":"Promotional bank","ECA":"Export credit agency","EU institution":"EU institution","World Bank trust fund":"World Bank trust fund (EU-financed)"};
const instName = id => (D.inst[id] || {}).n || id;
const tip = $("#tip");
function showTip(e, html) { tip.innerHTML = html; tip.hidden = false; tip.style.left = Math.min(e.clientX + 14, innerWidth - 320) + "px"; tip.style.top = (e.clientY + 14) + "px"; }
function hideTip() { tip.hidden = true; }

// ---------- views
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.setAttribute("aria-pressed", x === b));
  ["net","ovl","evt","src","abt"].forEach(v => $("#v-" + v).hidden = v !== b.dataset.v);
  if (b.dataset.v === "ovl") drawMatrix(); if (b.dataset.v === "evt") drawEvents();
});

// ---------- NETWORK
const KIND = {institution:{c:t => css(TYPEVAR[t] || "--t-dfi"), label:"Institution"}, country:{c:(t,u) => css(u === "CEMAC" ? "--cemac" : "--waemu"), label:"Country"},
  memberstate:{c:() => css("--k-ms"), label:"Member state"}, sector:{c:() => css("--k-sec"), label:"Sector"}, agency:{c:() => css("--k-ag"), label:"Implementing agency (EU funds)"},
  framework:{c:() => css("--k-fw"), label:"Framework (no amounts)"}};
const layers = {memberstate:true, sector:false, agency:true, framework:false};
const typeOn = Object.fromEntries(Object.keys(TYPEVAR).map(t => [t, true]));
const lay = $("#layers");
function chip(label, color, on, fn) { const b = document.createElement("button"); b.className = "chip"; b.setAttribute("aria-pressed", on);
  b.innerHTML = `<span class="sw" style="background:${color}"></span>${label}`; b.onclick = () => { fn(); b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") !== "true"); }; lay.append(b); }
Object.keys(TYPEVAR).forEach(t => chip(TYPELABEL[t], css(TYPEVAR[t]), true, () => { typeOn[t] = !typeOn[t]; buildGraph(); }));
[["memberstate","Member states"],["agency","Implementing agencies"],["sector","Sectors"],["framework","Frameworks"]].forEach(([k,l]) =>
  chip(l, KIND[k].c(), layers[k], () => { layers[k] = !layers[k]; buildGraph(); }));
const minWrap = document.createElement("label"); minWrap.className = "ctl";
minWrap.innerHTML = `Hide links under <select id="minv"><option value="0">€0</option><option value="1000000" selected>€1 m</option><option value="10000000">€10 m</option><option value="50000000">€50 m</option></select>`;
lay.append(minWrap); $("#minv").onchange = buildGraph;
$("#netlegend").innerHTML = Object.entries(KIND).map(([k,v]) => `<span><i class="sw" style="background:${k === "country" ? css("--waemu") : v.c()}"></i>${v.label}</span>`).join("") +
  (USE3D ? `<span>Drag to rotate, scroll to zoom, hover to light up an actor, click for details.</span>` : `<span>Size and line width follow euros. Drag a dot to pin it, double-click to release.</span>`);

const svg = d3.select("#net"), g = svg.append("g"), gl = g.append("g"), gn = g.append("g");
const zoom = d3.zoom().scaleExtent([0.2, 6]).on("zoom", e => g.attr("transform", e.transform));
svg.call(zoom).on("dblclick.zoom", null);
const cam = f => { const p = G3.cameraPosition(); G3.cameraPosition({x: p.x * f, y: p.y * f, z: p.z * f}, undefined, reduce ? 0 : 400); };
$("#zin").onclick = () => USE3D && G3 ? cam(0.72) : svg.transition().duration(reduce ? 0 : 250).call(zoom.scaleBy, 1.4);
$("#zout").onclick = () => USE3D && G3 ? cam(1.38) : svg.transition().duration(reduce ? 0 : 250).call(zoom.scaleBy, 1 / 1.4);
$("#zreset").onclick = () => USE3D && G3 ? G3.zoomToFit(reduce ? 0 : 800, 30) : svg.transition().duration(reduce ? 0 : 250).call(zoom.transform, d3.zoomIdentity);
let sim = null, selected = null, focusCountry = null;
// ---------- 3D nebula (falls back to the 2D network when the computer cannot draw 3D)
if (USE3D) $("#netstage").classList.add("use3d");
else { $("#modenote").hidden = false; $("#modenote").textContent = "This computer cannot draw the 3D view, so the 2D network is shown."; }
let G3 = null, hovered = null, nbrs = new Set(), hotLinks = new Set();
const SHELL = {memberstate: 45, institution: 135, agency: 205, sector: 245, framework: 265, country: 320};
function glowTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 128; const g = c.getContext("2d");
  const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(0.18, "rgba(255,255,255,.7)"); gr.addColorStop(0.45, "rgba(255,255,255,.18)"); gr.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = gr; g.fillRect(0, 0, 128, 128); return new THREE.CanvasTexture(c);
}
let GLOW = null;
function textSprite(text, color) {
  const c = document.createElement("canvas"), g = c.getContext("2d"), fs = 44;
  g.font = `600 ${fs}px IBM Plex Sans, Segoe UI, sans-serif`; const w = Math.ceil(g.measureText(text).width) + 24;
  c.width = w; c.height = fs + 22; g.font = `600 ${fs}px IBM Plex Sans, Segoe UI, sans-serif`;
  g.lineWidth = 8; g.strokeStyle = "rgba(0,0,0,.85)"; g.strokeText(text, 12, fs); g.fillStyle = color; g.fillText(text, 12, fs);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false}));
  s.scale.set(c.width / 5.5, c.height / 5.5, 1); return s;
}
function shellForce(alpha) {
  for (const n of shellForce.nodes || []) {
    const R = SHELL[n.k] || 200, x = n.x || 0.01, y = n.y || 0.01, z = n.z || 0.01, r = Math.hypot(x, y, z) || 1, k = (R - r) / r * alpha * 0.25;
    n.vx += x * k; n.vy += y * k; n.vz += z * k;
  }
}
shellForce.initialize = ns => { shellForce.nodes = ns; };
function nodeColor(d) { return d.k === "framework" ? css("--k-fw") : KIND[d.k].c(d.t, d.u); }
function render3D(nodes, ls, rn, labelled) {
  if (!GLOW) GLOW = glowTexture();
  const el = $("#net3d"), stage = $("#netstage");
  const prev = G3 ? Object.fromEntries(G3.graphData().nodes.map(n => [n.id, n])) : {};
  nodes.forEach(n => { const p = prev[n.id]; if (p) { n.x = p.x; n.y = p.y; n.z = p.z; } });
  ls.forEach(l => { const s = nodeById[l.source]; l.col = l.cs ? css("--k-sec") : s && s.k === "institution" ? KIND.institution.c(s.t) : "#6f8f9c"; });
  if (!G3) {
    G3 = ForceGraph3D({controlType: "orbit"})(el)
      .backgroundColor("#02060b").showNavInfo(false)
      .nodeThreeObject(d => {
        const col = nodeColor(d), size = Math.max(4, rn(d) * 0.85), grp = new THREE.Group();
        const glow = new THREE.Sprite(new THREE.SpriteMaterial({map: GLOW, color: col, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false}));
        glow.scale.set(size * 4, size * 4, 1);
        const core = new THREE.Mesh(new THREE.SphereGeometry(size * 0.42, 18, 14), new THREE.MeshBasicMaterial({color: col, transparent: true, opacity: 0.95}));
        grp.add(glow); grp.add(core);
        if (labelled(d)) { const s = textSprite(d.k === "institution" ? shortName(d.l) : d.l.length > 30 ? d.l.slice(0, 28) + "…" : d.l, "#e9f8ff"); s.position.set(0, size * 1.1 + 4, 0); grp.add(s); d.__label = s; }
        d.__glow = glow; d.__core = core; d.__size = size; return grp;
      })
      .nodeLabel(d => `<b>${esc(d.l)}</b><br>${esc(KIND[d.k].label)}${d.v ? "<br>" + fmt(d.v) + " in the Franc Zone" : ""}`)
      .linkColor(l => l.col).linkOpacity(0.2).linkWidth(l => hotLinks.has(l) ? 0.9 : 0)
      .linkVisibility(l => !hovered || hotLinks.has(l))
      .linkDirectionalParticles(l => (!reduce && hotLinks.has(l)) ? 3 : 0).linkDirectionalParticleWidth(1.8).linkDirectionalParticleSpeed(0.007)
      .onNodeHover(n => { el.style.cursor = n ? "pointer" : "grab"; setHover(n); })
      .onNodeClick(n => clickNode(n))
      .onBackgroundClick(() => { selected = null; const had = focusCountry; focusCountry = null; setHover(null); if (had) buildGraph(); netIntro(); })
      .d3Force("shell", shellForce).d3VelocityDecay(0.35).cooldownTicks(reduce ? 0 : 300);
    G3.d3Force("charge").strength(-55);
    G3.d3Force("link").distance(60).strength(0.05);
    // a faint star field for the nebula look
    const pts = [], N = 2200;
    for (let i = 0; i < N; i++) { const r = 900 + Math.random() * 1500, a = Math.random() * Math.PI * 2, b = Math.acos(2 * Math.random() - 1); pts.push(r * Math.sin(b) * Math.cos(a), r * Math.sin(b) * Math.sin(a), r * Math.cos(b)); }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    G3.scene().add(new THREE.Points(geo, new THREE.PointsMaterial({color: 0x7fb8d8, size: 1.6, transparent: true, opacity: 0.55, depthWrite: false})));
    // coloured clouds of light: the nebula
    const CLOUD = ["#1f6fd6", "#16b3a4", "#7a3fd1", "#c97a2a", "#1aa0d8", "#9a2f7a"];
    for (let i = 0; i < 16; i++) {
      const m = new THREE.Sprite(new THREE.SpriteMaterial({map: GLOW, color: CLOUD[i % CLOUD.length], transparent: true, opacity: 0.07 + Math.random() * 0.05, blending: THREE.AdditiveBlending, depthWrite: false}));
      const r = 80 + Math.random() * 260, a = Math.random() * Math.PI * 2, b = Math.acos(2 * Math.random() - 1), sc = 380 + Math.random() * 520;
      m.position.set(r * Math.sin(b) * Math.cos(a), r * Math.sin(b) * Math.sin(a), r * Math.cos(b)); m.scale.set(sc, sc, 1); m.renderOrder = -1;
      G3.scene().add(m);
    }
    if (!reduce) (function pulse(t) { if (hovered && hovered.__glow) { const s = hovered.__size * (7.5 + Math.sin(t / 260) * 1.4); hovered.__glow.scale.set(s, s, 1); } requestAnimationFrame(pulse); })(0);
    setTimeout(() => G3.zoomToFit(reduce ? 0 : 900, 30), 1600);
  }
  G3.width(stage.clientWidth).height(stage.clientHeight).graphData({nodes, links: ls});
  if (selected) { const n = G3.graphData().nodes.find(x => x.id === selected); if (n) setTimeout(() => setHover(n, true), 50); }
}
function setHover(n, sticky) {
  if (!G3) return;
  hovered = n || (selected ? G3.graphData().nodes.find(x => x.id === selected) : null);
  nbrs = new Set(); hotLinks = new Set();
  if (hovered) { nbrs.add(hovered.id); G3.graphData().links.forEach(l => { const s = l.source.id || l.source, t = l.target.id || l.target; if (s === hovered.id || t === hovered.id) { nbrs.add(s); nbrs.add(t); hotLinks.add(l); } }); }
  G3.graphData().nodes.forEach(d => {
    if (!d.__core) return;
    const on = !hovered || nbrs.has(d.id), me = hovered && d.id === hovered.id;
    d.__core.material.opacity = on ? 0.95 : 0.12;
    d.__glow.material.opacity = me ? 1 : on ? (hovered ? 0.85 : 0.7) : 0.05;
    const s = d.__size * (me ? 7.5 : 4); d.__glow.scale.set(s, s, 1);
    if (d.__label) d.__label.material.opacity = on ? 1 : 0.15;
  });
  G3.linkWidth(G3.linkWidth()).linkVisibility(G3.linkVisibility()).linkDirectionalParticles(G3.linkDirectionalParticles());
}
function clickNode(n) {
  selected = n.id;
  if (n.k === "country") { const was = focusCountry; focusCountry = n.id.slice(2); if (was !== focusCountry) buildGraph(); }
  panel(nodeById[n.id] || n); setHover(n, true);
  const d = 150, r = Math.hypot(n.x, n.y, n.z) || 1, f = 1 + d / r;
  G3.cameraPosition({x: n.x * f, y: n.y * f, z: n.z * f}, n, reduce ? 0 : 1200);
}
// full screen: the network and its panel together
$("#fs").onclick = () => { const v = $("#v-net"); if (!document.fullscreenElement) (v.requestFullscreen ? v.requestFullscreen() : v.webkitRequestFullscreen && v.webkitRequestFullscreen()); else document.exitFullscreen(); };
document.addEventListener("fullscreenchange", () => {
  $("#fs span").textContent = document.fullscreenElement ? "Exit full screen" : "Full screen";
  setTimeout(() => { if (USE3D && G3) G3.width($("#netstage").clientWidth).height($("#netstage").clientHeight); else buildGraph(); }, 120);
});
const nodeById = Object.fromEntries(D.nodes.map(n => [n.id, n]));
const COL = {country: 0.86, memberstate: 0.06, institution: 0.34, agency: 0.6, sector: 0.6, framework: 0.97};
function visibleNode(n) {
  if (n.k === "institution") return typeOn[n.t];
  if (n.k === "country") return true;
  if (n.k === "sector" && focusCountry) return true;  // a clicked country shows its sectors
  return layers[n.k];
}
function buildGraph() {
  const minv = +$("#minv").value;
  const ns = D.nodes.filter(visibleNode).map(n => Object.assign({}, n));
  const ok = new Set(ns.map(n => n.id));
  let ls = D.links.filter(l => ok.has(l.s) && ok.has(l.t) && (l.t.startsWith("f:") || l.s.startsWith("f:") || l.v >= minv))
    .filter(l => !(focusCountry && !layers.sector && l.t.startsWith("s:")))   // in country focus, sectors connect to that country only
    .map(l => ({source:l.s, target:l.t, v:l.v, n:l.n}));
  if (focusCountry) Object.entries(D.csec[focusCountry] || {}).forEach(([sec, v]) => { if (ok.has("s:" + sec)) ls.push({source:"c:" + focusCountry, target:"s:" + sec, v, n:0, cs:true}); });
  const used = new Set(ls.flatMap(l => [l.source, l.target]));
  const nodes = ns.filter(n => used.has(n.id) || n.k === "country");
  const W = $("#netstage").clientWidth, H = $("#netstage").clientHeight;
  const r0 = d3.scaleSqrt().domain([0, d3.max(nodes.filter(n => n.k !== "memberstate"), n => n.v) || 1]).range([3, 26]);
  const r = v => r0(v); const rn = d => d.k === "memberstate" ? Math.min(14, 3 + r0(d.v || 0) * 0.4) : r0(d.v || 0);
  if (USE3D) {
    const instV = nodes.filter(n => n.k === "institution").map(n => n.v).sort((a, b) => b - a), cut = instV[Math.min(14, instV.length - 1)] || 0;
    render3D(nodes, ls, rn, d => d.k === "country" || d.k === "memberstate" || (d.k === "institution" && d.v >= cut) || d.k === "agency" || (d.k === "sector" && focusCountry));
    return;
  }
  const w = d3.scaleSqrt().domain([0, d3.max(ls, l => l.v) || 1]).range([0.4, 6]);
  gl.selectAll("*").remove(); gn.selectAll("*").remove();
  const link = gl.selectAll("line").data(ls).join("line").attr("class", "link")
    .attr("stroke", l => { if (l.cs) return css("--k-sec"); const s = nodeById[l.source]; return s && s.k === "institution" ? KIND.institution.c(s.t) : "#5f7f8c"; })
    .attr("stroke-width", l => l.v ? w(l.v) : 0.6).attr("stroke-dasharray", l => l.v ? null : "3 3");
  const node = gn.selectAll("g").data(nodes, n => n.id).join("g").attr("class", "node")
    .call(d3.drag().on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; }).on("end", (e) => { if (!e.active) sim.alphaTarget(0); }))
    .on("dblclick", (e, d) => { d.fx = null; d.fy = null; sim.alpha(0.3).restart(); })
    .on("mousemove", (e, d) => showTip(e, `<b>${esc(d.l)}</b><br>${esc(KIND[d.k].label)}${d.v ? "<br>" + fmt(d.v) + " in the Franc Zone" : ""}`))
    .on("mouseleave", hideTip).on("click", (e, d) => {
      selected = d.id;
      if (d.k === "country") { const was = focusCountry; focusCountry = d.id.slice(2); if (was !== focusCountry) { buildGraph(); } }
      highlight(); panel(nodeById[d.id] || d);
    });
  const csz = focusCountry ? d3.scaleSqrt().domain([0, d3.max(Object.values(D.csec[focusCountry] || {})) || 1]).range([4, 16]) : null;
  if (csz) nodes.forEach(d => { if (d.k === "sector" && !layers.sector) d.fv = (D.csec[focusCountry] || {})[d.id.slice(2)] || 0; });
  node.append("circle").attr("r", d => d.k === "framework" ? 5 : (csz && d.k === "sector" && !layers.sector) ? csz(d.fv) : rn(d))
    .attr("fill", d => d.k === "framework" ? "none" : KIND[d.k].c(d.t, d.u)).attr("stroke", d => d.k === "framework" ? css("--k-fw") : "#000")
    .attr("stroke-width", d => d.k === "framework" ? 1.5 : 0.8);
  node.filter(d => d.k !== "framework" && (d.k !== "sector" || d.v > 0)).append("text")
    .attr("text-anchor", d => d.k === "sector" ? "end" : "start").attr("dx", d => d.k === "sector" ? -(rn(d) + 3) : rn(d) + 3).attr("dy", 3.5)
    .text(d => d.k === "institution" ? shortName(d.l) : d.l.length > 28 ? d.l.slice(0, 26) + "…" : d.l);
  if (sim) sim.stop();
  sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(ls).id(d => d.id).distance(110).strength(0.06))
    .force("charge", d3.forceManyBody().strength(d => -90 - rn(d) * 9))
    .force("x", d3.forceX(d => W * (d.k === "sector" && focusCountry && !layers.sector ? 0.93 : (COL[d.k] ?? 0.5))).strength(0.55))
    .force("y", d3.forceY(H / 2).strength(0.04))
    .force("collide", d3.forceCollide(d => rn(d) + 9).strength(0.9))
    .on("tick", () => {
      link.attr("x1", l => l.source.x).attr("y1", l => l.source.y).attr("x2", l => l.target.x).attr("y2", l => l.target.y);
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });
  if (reduce) { sim.stop(); for (let i = 0; i < 300; i++) sim.tick(); link.attr("x1", l => l.source.x).attr("y1", l => l.source.y).attr("x2", l => l.target.x).attr("y2", l => l.target.y); node.attr("transform", d => `translate(${d.x},${d.y})`); }
  window._net = {node, link, ls};
  highlight();
}
const SHORT_ID = {"eu-intpa":"European Commission","eu-eutf":"EU Trust Fund for Africa","edfi-mc":"ElectriFI / AgriFI","eu-blending":"EU blending grants",
  "eu-aitf":"EU-AITF","wbtf":"World Bank trust funds","eib":"EIB","afd":"AFD","kfw-db":"KfW","proparco":"Proparco","deg":"DEG","fmo":"FMO","bio":"BIO",
  "invest-intl":"Invest International","dggf":"DGGF","finnfund":"Finnfund","ifu":"Impact Fund Denmark","atradius-dsb":"Atradius DSB","bgk":"BGK","kuke":"KUKE",
  "cofides":"COFIDES","swedfund":"Swedfund","sace":"SACE","cdp":"CDP","eifo":"EIFO","credendo":"Credendo","bpifrance-ae":"Bpifrance Assurance Export","oeeb":"OeEB"};
const SHORTS = Object.fromEntries(Object.entries(SHORT_ID).filter(([id]) => D.inst[id]).map(([id, s]) => [D.inst[id].n, s]));
function shortName(n) { if (SHORTS[n]) return SHORTS[n]; const m = n.match(/\(([^)]+)\)\s*$/); return m && m[1].length < 26 ? m[1] : n.split(" – ")[0].slice(0, 26); }
function highlight() {
  if (!window._net) return; const {node, link, ls} = window._net;
  if (!selected) { node.classed("faded", false); link.classed("faded", false); return; }
  const nb = new Set([selected]); ls.forEach(l => { const s = l.source.id || l.source, t = l.target.id || l.target; if (s === selected) nb.add(t); if (t === selected) nb.add(s); });
  node.classed("faded", d => !nb.has(d.id)); link.classed("faded", l => (l.source.id || l.source) !== selected && (l.target.id || l.target) !== selected);
}
svg.on("click", e => { if (e.target === svg.node()) { selected = null; const had = focusCountry; focusCountry = null; if (had) buildGraph(); highlight(); netIntro(); } });
function bars(items, color) { const max = Math.max(1, ...items.map(x => x[1]));
  return items.map(([l, v]) => `<div class="bar"><span>${esc(l)}</span><span class="track"><i style="width:${(100 * v / max).toFixed(1)}%;background:${color}"></i></span><span class="val">${fmt(v)}</span></div>`).join(""); }
function dealList(ds, n = 12) { return ds.sort((a, b) => b.v - a.v).slice(0, n).map(d => `<div class="deal">${esc(d.t)}<div class="meta">${esc(shortName(instName(d.i)))}, ${d.c.map(c => esc((D.countries[c] || {}).n || c)).join(", ")}${d.y ? ", " + esc(d.y) : ""}, ${esc(d.n)} · <span class="amt">${fmt(d.v)}</span>${d.e ? " (estimated share)" : ""} <a href="${esc(d.u)}" target="_blank" rel="noopener">source</a></div></div>`).join(""); }
function panel(n) {
  const id = n.id.slice(2), p = $("#netpanel");
  const nb = D.links.filter(l => l.s === n.id || l.t === n.id).map(l => [nodeById[l.s === n.id ? l.t : l.s], l]).filter(x => x[0]);
  let html = `<h2>${esc(n.l)}</h2><div class="meta">${esc(KIND[n.k].label)}${n.t ? " · " + esc(TYPELABEL[n.t]) : ""}</div>`;
  if (n.v) html += `<div class="big">${fmt(n.v)}</div><div class="hint">attributed to Franc Zone countries since 1999</div>`;
  const grp = k => nb.filter(([m, l]) => m.k === k && l.v).sort((a, b) => b[1].v - a[1].v).slice(0, 10).map(([m, l]) => [m.l.length > 40 ? m.l.slice(0, 38) + "…" : m.l, l.v]);
  if (n.k === "institution") {
    const ds = D.deals.filter(d => d.i === id);
    html += `<h3>Countries</h3>${bars(grp("country"), css("--waemu"))}<h3>Sectors</h3>${bars(grp("sector"), css("--k-sec"))}`;
    if (grp("agency").length) html += `<h3>EU funds entrusted to implementing agencies</h3>${bars(grp("agency"), css("--k-ag"))}`;
    const co = D.cofin.filter(c => c.m.some(m => m[0] === id)).slice(0, 6);
    if (co.length) html += `<h3>Co-financed projects</h3>` + co.map(c => `<div class="deal">${c.m.map(m => esc(shortName(instName(m[0])))).filter((v,i,a) => a.indexOf(v) === i).join(" + ")} <span class="meta">(shared words: ${esc(c.w.join(", "))})</span></div>`).join("");
    html += `<h3>Largest deals (${ds.length})</h3>${dealList(ds)}`;
  } else if (n.k === "country") {
    const secs = Object.entries(D.csec[id] || {});
    html += `<h3>Sectors it receives money in</h3>` + (secs.length ? bars(secs.slice(0, 11).map(([s, v]) => [s, v]), css("--k-sec")) : `<p class="hint">No sector recorded.</p>`) +
      `<p class="hint">Shown as green links on the graph. Click empty space to hide them.</p>` +
      `<h3>Institutions</h3>${bars(grp("institution"), css("--t-dfi"))}<h3>Largest deals</h3>${dealList(D.deals.filter(d => d.c.includes(id)))}`;
  } else if (n.k === "memberstate") {
    html += `<h3>Institutions</h3>${bars(grp("institution"), css("--t-dfi"))}`;
  } else if (n.k === "sector") {
    html += `<h3>Institutions</h3>${bars(grp("institution"), css("--t-dfi"))}<h3>Largest deals</h3>${dealList(D.deals.filter(d => d.s === id))}`;
  } else if (n.k === "agency") {
    html += `<p class="hint">EU money (Commission, EU Trust Fund for Africa, blending, EU-AITF) entrusted to this agency to implement; counted under the EU.</p><h3>From</h3>${bars(grp("institution"), css("--t-eu"))}<h3>Largest EU-funded deals it implements</h3>${dealList(D.deals.filter(d => d.g === id))}`;
  } else if (n.k === "framework") {
    html += `<p class="hint">${esc(n.fk)}. Frameworks carry no amounts in this network: the money appears in the deals of the institutions involved.</p><h3>Linked to</h3>` +
      nb.map(([m]) => `<div class="deal">${esc(m.l)} <span class="meta">${esc(KIND[m.k].label)}</span></div>`).join("") + (n.src ? `<p><a href="${esc(n.src)}" target="_blank" rel="noopener">Source</a></p>` : "");
  }
  p.innerHTML = html;
}
function netIntro() {
  const tot = D.deals.reduce((s, d) => s + d.v, 0);
  $("#netpanel").innerHTML = `<h2>The network</h2><p class="hint">European public financial institutions (development banks, DFIs, promotional banks, export credit agencies, EU institutions) and World Bank trust funds financed by European donors, linked to the 14 CFA franc countries they finance since 1999, to their member states, and to the agencies that implement EU funds.</p>
    <div class="big">${fmt(tot)}</div><div class="hint">${D.deals.length.toLocaleString("en")} deals from ${Object.keys(D.inst).length} institutions in scope</div>
    <h3>How to read it</h3><p class="hint">Click any dot for its details and sources. Click a country to see the sectors it receives money in. Click empty space to clear. Use the buttons to add sectors or frameworks, or to hide small links.</p>
    ${D.site ? `<p><a href="${esc(D.site)}" target="_blank" rel="noopener" style="color:var(--accent)">Open the EU-CFA Public finance tracker</a></p>` : ""}`;
}
netIntro();

// ---------- OVERLAP
$("#ovc").innerHTML = `<option value="">All countries</option>`; // matrix uses all countries; the panel lists country detail
function drawMatrix() {
  const n = +$("#ovn").value, ids = D.top.slice(0, n), M = D.matrix;
  const max = Math.max(1, ...ids.flatMap((a, i) => ids.map((b, j) => i === j ? 0 : M[i][j])));
  const col = v => `rgba(64,232,255,${(0.08 + 0.92 * Math.sqrt(v / max)).toFixed(3)})`;
  let h = `<table><tr><th></th>${ids.map(b => `<th class="col"><div>${esc(shortName(instName(b)))}</div></th>`).join("")}</tr>`;
  ids.forEach((a, i) => { h += `<tr><th style="text-align:right">${esc(shortName(instName(a)))}</th>` + ids.map((b, j) => {
      const v = M[i][j];
      if (i === j) return `<td class="diag" style="background:${css(TYPEVAR[(D.inst[a] || {}).t] || "--t-dfi")};color:#000" title="${esc(instName(a))}: ${fmt(v)} in total">●</td>`;
      return `<td data-a="${a}" data-b="${b}" style="background:${v ? col(v) : "transparent"}" title="${esc(shortName(instName(a)))} and ${esc(shortName(instName(b)))}: ${fmt(v)} of overlapping finance">${v >= 1e8 ? Math.round(v / 1e8) / 10 : ""}</td>`; }).join("") + "</tr>"; });
  $("#matrix").innerHTML = h + "</table>";
  $("#matrix").querySelectorAll("td[data-a]").forEach(td => td.onclick = () => pairPanel(td.dataset.a, td.dataset.b));
}
$("#ovn").onchange = drawMatrix;
function pairPanel(a, b) {
  const key = D.pairs[a + "|" + b] ? a + "|" + b : b + "|" + a, rows = D.pairs[key] || [], flip = key !== a + "|" + b;
  const co = D.cofin.filter(c => c.m.some(m => m[0] === a) && c.m.some(m => m[0] === b));
  $("#ovlpanel").innerHTML = `<h2>${esc(shortName(instName(a)))} and ${esc(shortName(instName(b)))}</h2>
    <p class="hint">Where both finance the same sector in the same country. The overlap is the smaller of the two amounts, summed over every shared country and sector.</p>
    <h3>Shared countries and sectors</h3>` + (rows.length ? rows.map(r => `<div class="deal">${esc((D.countries[r[0]] || {}).n || r[0])}, ${esc(r[1])}<div class="meta">${esc(shortName(instName(flip ? b : a)))} <span class="amt">${fmt(r[2])}</span>, ${esc(shortName(instName(flip ? a : b)))} <span class="amt">${fmt(r[3])}</span></div></div>`).join("") : `<p class="hint">None.</p>`) +
    `<h3>Co-financed projects</h3>` + (co.length ? co.map(cofinHtml).join("") : `<p class="hint">No project found in both records.</p>`);
}
function cofinHtml(c) { return `<div class="deal"><b>${c.m.map(m => esc(shortName(instName(m[0])))).filter((v,i,a) => a.indexOf(v) === i).join(" + ")}</b>, ${c.c.map(x => esc((D.countries[x] || {}).n || x)).join(", ")}
  <div class="meta">Evidence: both records name ${esc(c.w.join(", "))}</div>` + c.m.map(m => `<div class="meta">· ${esc(shortName(instName(m[0])))}: ${esc(m[1])}${m[2] ? " (" + esc(m[2]) + ")" : ""} <span class="amt">${fmt(m[3])}</span> <a href="${esc(m[4])}" target="_blank" rel="noopener">source</a></div>`).join("") + `</div>`; }
function ovlIntro() {
  $("#ovlpanel").innerHTML = `<h2>Overlap</h2><p class="hint">Each cell shows how much two institutions overlap: the euros they both put into the same sector in the same country (the smaller of the two amounts, summed). The diagonal marks each institution. Click a cell for the shared countries and sectors and the projects both finance.</p>
    <h3>Co-financed projects (${D.cofin.length})</h3><p class="hint">Deals from different institutions in the same country, within three years, whose titles share distinctive words (for example a dam or company name). The evidence is shown with each match; check the sources before citing.</p>` + D.cofin.slice(0, 25).map(cofinHtml).join("");
}
ovlIntro();

// ---------- EVENTS
const CATVAR = {"Monetary":"--c-mon","Politics & security":"--c-pol","EU–Africa policy":"--c-eu","Financing instrument":"--c-fin","Summit / meeting":"--c-meet"};
const catOn = Object.fromEntries(Object.keys(CATVAR).map(c => [c, true]));
let evCountry = "ALL";
const evt = $("#evtools");
evt.innerHTML = `<label class="ctl">Country <select id="evc"><option value="ALL">All 14 countries</option>${Object.entries(D.countries).filter(([k]) => k.length === 2 && k !== "XW" && k !== "XC").map(([k, c]) => `<option value="${k}">${esc(c.n)}</option>`).join("")}</select></label>`;
Object.keys(CATVAR).forEach(c => { const b = document.createElement("button"); b.className = "chip"; b.setAttribute("aria-pressed", "true");
  b.innerHTML = `<span class="sw" style="background:${css(CATVAR[c])}"></span>${c}`; b.onclick = () => { catOn[c] = !catOn[c]; b.setAttribute("aria-pressed", catOn[c]); drawEvents(); }; evt.append(b); });
$("#evc").onchange = e => { evCountry = e.target.value; drawEvents(); };
function drawEvents() {
  const evs = D.events.filter(e => catOn[e.cat] !== false && (evCountry === "ALL" || e.cc.includes("ALL") || e.cc.includes(evCountry)));
  const types = Object.keys(TYPEVAR), key = evCountry === "ALL" ? "ALL" : evCountry;
  const ys = D.years, stack = ys.map((y, i) => types.map(t => ((D.timeline[key + "|" + t] || [])[i]) || 0));
  const W = Math.max(600, $("#evmain").clientWidth - 40), H = 260, pad = {l: 56, r: 10, t: 14, b: 26};
  const x = d3.scaleBand().domain(ys).range([pad.l, W - pad.r]).padding(0.15), ymax = d3.max(stack, s => d3.sum(s)) || 1;
  const y = d3.scaleLinear().domain([0, ymax]).nice().range([H - pad.b, pad.t]);
  let svgs = `<svg width="${W}" height="${H}" role="img" aria-label="European commitments per year with events">`;
  y.ticks(4).forEach(t => svgs += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}" stroke="#163746"/><text x="${pad.l - 6}" y="${y(t) + 4}" text-anchor="end" fill="#8db1c0" font-size="11">${fmt(t)}</text>`);
  ys.forEach((yr, i) => { let acc = 0; types.forEach((t, j) => { const v = stack[i][j]; if (!v) return;
    svgs += `<rect x="${x(yr)}" width="${x.bandwidth()}" y="${y(acc + v)}" height="${y(acc) - y(acc + v)}" fill="${css(TYPEVAR[t])}"><title>${yr}, ${TYPELABEL[t]}: ${fmt(v)}</title></rect>`; acc += v; });
    if (i % 3 === 0) svgs += `<text x="${x(yr) + x.bandwidth() / 2}" y="${H - 8}" text-anchor="middle" fill="#8db1c0" font-size="11">${yr}</text>`; });
  evs.forEach(e => { const yr = +e.d.slice(0, 4); if (!ys.includes(yr)) return; const cx = x(yr) + x.bandwidth() * ((+e.d.slice(5, 7) || 6) / 12);
    svgs += `<line x1="${cx}" x2="${cx}" y1="${pad.t}" y2="${H - pad.b}" stroke="${css(CATVAR[e.cat] || "--accent")}" stroke-dasharray="2 3"><title>${esc(e.d)}: ${esc(e.t)}</title></line><circle cx="${cx}" cy="${pad.t + 2}" r="4" fill="${css(CATVAR[e.cat] || "--accent")}"><title>${esc(e.d)}: ${esc(e.t)}</title></circle>`; });
  svgs += `</svg>`;
  const up = evs.filter(e => e.st !== "past"), past = evs.filter(e => e.st === "past").reverse();
  const row = e => `<div class="ev ${e.st !== "past" ? "up" : ""}"><div class="d">${esc(e.d)}${e.e ? "<br>to " + esc(e.e) : ""}</div><div><span class="badge" style="border-color:${css(CATVAR[e.cat] || "--line-hi")}">${esc(e.cat)}</span>${e.st !== "past" ? `<span class="badge">${esc(e.st)}</span>` : ""}<b>${esc(e.t)}</b><div class="meta">${esc(e.x)}</div><div class="meta">${e.cc.includes("ALL") ? "All countries" : e.cc.map(c => esc((D.countries[c] || {}).n || c)).join(", ")} · <a href="${esc(e.u)}" target="_blank" rel="noopener">source</a></div></div></div>`;
  $("#evmain").innerHTML = `<h2 style="margin:0 0 4px">European commitments per year${evCountry === "ALL" ? "" : " in " + esc(D.countries[evCountry].n)}, with events</h2>
    <p class="hint">Bars: euros committed by the institutions in scope, by year of signature or start (undated deals left out). Dashed lines: events, coloured by category; hover for details.</p>${svgs}
    <h2>Coming up (${up.length})</h2>${up.map(row).join("") || `<p class="hint">No upcoming event in this selection.</p>`}<h2>Past events (${past.length})</h2>${past.map(row).join("")}`;
  const tot = ys.map((yr, i) => [yr, d3.sum(stack[i])]);
  const before = (y0, y1) => d3.sum(tot.filter(([yr]) => yr >= y0 && yr <= y1), t => t[1]);
  $("#evpanel").innerHTML = `<h2>Events</h2><p class="hint">Summits, monetary reforms, coups and sanctions, and new financing instruments since the 1999 euro peg, plus scheduled meetings. Every event links its source; the list lives in data/events.csv and can be edited on GitHub.</p>
    <h3>Commitments by period${evCountry === "ALL" ? "" : " (" + esc(D.countries[evCountry].n) + ")"}</h3>` +
    bars([["1999–2009", before(1999, 2009)], ["2010–2019", before(2010, 2019)], ["2020–2022", before(2020, 2022)], ["2023 onward", before(2023, 2100)]], css("--accent")) +
    (D.warnings.length ? `<h3>Build warnings</h3>` + D.warnings.map(w => `<div class="warn">${esc(w)}</div>`).join("") : "");
}

// ---------- SOURCES
(() => {
  const row = s => `<div class="deal"><b>${esc(s.name)}</b><div class="meta">${esc(s.provider)} · ${esc(s.method)}${s.records ? " · " + s.records.toLocaleString("en") + " deals" : ""}</div>
    <div class="meta">${esc(s.provides)}</div><div class="meta">Licence: ${esc(s.licence)}${s.url ? ` · <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url.replace(/^https?:\/\//, "").slice(0, 70))}</a>` : ""}</div></div>`;
  const TS = D.tracker_sources || [], roles = ["Figures", "Regional layer", "Programmes", "Reference", "Recommended next"];
  const evBad = D.warnings.filter(w => w.startsWith("Event"));
  const LC = D.tracker_checks || {};
  $("#sources").innerHTML = `<h2>Sources</h2>
    <p>Every deal in this network comes from the EU-CFA Public finance tracker and links to the record it came from: click any dot, then "source". Events link their own sources. Below: this site's own sources, then the tracker's full source register.</p>
    <h2>This site</h2>${D.own_sources.map(row).join("")}
    <h3>Event sources checked at this build: ${D.events.length - evBad.length} of ${D.events.length} answered normally</h3>${evBad.map(w => `<div class="warn">${esc(w)}</div>`).join("")}
    <h2>The tracker's sources</h2>` + (TS.length ? roles.map(r => { const rs = TS.filter(s => s.role === r); return rs.length ? `<h3>${esc(r)}</h3>` + rs.map(row).join("") : ""; }).join("") +
    (LC.checked ? `<h3>Tracker link check: ${LC.ok} of ${LC.checked} cited links answered normally</h3>` + (LC.problems || []).map(([u, c, used]) => `<div class="warn">${esc(c)}: <a href="${esc(u)}" target="_blank" rel="noopener" style="color:inherit">${esc(u.slice(0, 80))}</a> (${esc(used.join("; "))})</div>`).join("") +
      `<p class="hint">Some sites refuse automated checks (403) but open in a browser; Capacity4dev pages need a login.</p>` : "")
    : `<p class="hint">The tracker's source register appears here once the tracker has run with its new Sources feature.</p>`);
})();

// ---------- ABOUT
$("#about").innerHTML = `<h2>About this tracker</h2>
  <p>The EU-CFA Network tracker shows how European public financial institutions connect, overlap and respond to events in the 14 countries of the CFA franc zone: the eight WAEMU countries in West Africa and the six CEMAC countries in Central Africa (the Comoros are not covered). It is a companion to the EU-CFA Public finance tracker and reads that tracker's data, so both always show the same deals.</p>
  <h2>Scope</h2><ul><li>Included: European development banks and DFIs, national promotional banks, export credit agencies, EU institutions (the EIB, the European Commission, the EU Trust Fund for Africa, EU blending grants, the EU-Africa Infrastructure Trust Fund, ElectriFI and AgriFI), and World Bank-managed trust funds financed only by European donors.</li>
  <li>Not included: the EBRD, EU humanitarian aid and foreign-policy instruments, and non-European financiers.</li></ul>
  <h2>Method</h2><ul><li>Network: links are weighted by euros attributed to Franc Zone countries since 1999. EU money implemented by a member-state agency (AFD, GIZ, Expertise France, Enabel and others) is linked from the EU institution to that agency and counted under the EU.</li>
  <li>Overlap: for two institutions, the euros both put into the same sector in the same country (the smaller of the two amounts, summed over every shared country and sector).</li>
  <li>Co-financed projects: deals by different institutions in the same country, within three years of each other, whose titles share distinctive words. The shared words are shown as evidence. This is a rule-based match: check the sources before citing a project as co-financed.</li>
  <li>Events: hand-checked, each with its source; the build tests every source link and lists any that fail under Events.</li></ul>
  <h2>Data</h2><p>Tracker data dated ${esc(D.generated)}; this page built on ${esc(D.built)}. Every deal links to its source record.</p>`;

buildGraph();
addEventListener("resize", () => { clearTimeout(window._rz); window._rz = setTimeout(buildGraph, 300); });
})();
</script>
</body>
</html>
'''

try:
    TEMPLATE
except NameError:  # during development the page template is a separate file
    TEMPLATE = (ROOT / "template.html").read_text(encoding="utf-8")

# ---------------------------------------------------------------- 7. write the page
own_sources = [
    {"name": "EU-CFA Public finance tracker data", "provider": "Your tracker (data/tracker.json)", "url": TRACKER_DATA_URL or TRACKER_SITE_URL,
     "method": "Read at every build" if TRACKER_DATA_URL else "Saved copy in data/tracker.json", "licence": "Same as the tracker's sources (see below)",
     "provides": f"All deals, institutions, countries and programmes, data of {generated}. Each deal links to its original record."},
    {"name": "Event log", "provider": "data/events.csv", "url": "", "method": "Hand-checked; every link tested at build",
     "licence": "Per event", "provides": f"{len(events)} events, each with its own source (listed in the Events tab)."},
    {"name": "D3.js graphics library", "provider": "Mike Bostock and contributors", "url": "https://d3js.org", "method": "Downloaded once and embedded",
     "licence": "ISC", "provides": "Draws the network, the matrix and the timeline."}]
bundle = {"generated": generated, "built": TODAY.isoformat(), "site": TRACKER_SITE_URL,
          "own_sources": own_sources, "tracker_sources": T.get("sources", []), "tracker_checks": T.get("link_checks", {}),
          "inst": {k: {"n": v["name"], "t": v["type"], "ms": v["member_state"]} for k, v in INST.items()},
          "countries": {k: {"n": v["name"], "u": v.get("union", "")} for k, v in COUNTRIES.items()},
          "nodes": list(nodes.values()), "links": [{"s": a, "t": b, **v} for (a, b), v in links.items()],
          "deals": list(deals.values()), "csec": csec, "top": top, "matrix": matrix, "pairs": pair_detail, "cofin": cofin[:150],
          "years": years, "timeline": timeline, "events": events, "warnings": warnings}
d3 = REF / "d3.min.js"
if not d3.exists():
    d3.write_bytes(get("https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"))
LIBS = {"three.min.js": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js",
        "3d-force-graph.min.js": "https://cdn.jsdelivr.net/npm/3d-force-graph@1.73.4/dist/3d-force-graph.min.js"}
for name, url in LIBS.items():
    if not (REF / name).exists():
        (REF / name).write_bytes(get(url))
html = (TEMPLATE.replace("/*__DATA__*/null", json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
                .replace("/*__D3__*/", d3.read_text(encoding="utf-8"))
                .replace("/*__THREE__*/", (REF / "three.min.js").read_text(encoding="utf-8").replace("console.warn('Scripts", "void('Scripts", 1))
                .replace("/*__FG3D__*/", (REF / "3d-force-graph.min.js").read_text(encoding="utf-8")))
(SITE / "index.html").write_text(html, encoding="utf-8")
print(f"site/index.html {len(html.encode()) / 1e6:.2f} MB | {len(nodes)} nodes, {len(links)} links, {len(deals)} deals, "
      f"{len(cofin)} co-financed projects, {len(events)} events, {len(warnings)} warnings")
for w in warnings:
    print("warning:", w)
