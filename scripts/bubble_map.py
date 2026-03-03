# bubble_map.py  --  D3 force-simulation bubble map for HyperWhale
import argparse, json, os, webbrowser

BASE      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE, "data", "live_positions_snapshot.json")
OUT_FILE  = os.path.join(BASE, "reports", "bubble_map.html")

def load_snapshot(path=DATA_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def build_wallet_js(wallets):
    out = []
    for w in wallets:
        out.append({
            "address":       w.get("address", ""),
            "label":         w.get("label", w.get("address", "")[:8]),
            "tier":          w.get("tier", "dolphin"),
            "whale_score":   w.get("whale_score", 0),
            "account_value": w.get("account_value", 0),
            "positions": [
                {
                    "coin":     p.get("coin", ""),
                    "side":     p.get("side", ""),
                    "notional": p.get("notional", 0),
                    "upnl":     p.get("upnl", 0),
                    "entry":    p.get("entry", 0),
                    "liq":      p.get("liq", 0),
                    "leverage": p.get("leverage", 1),
                }
                for p in w.get("positions", [])
            ],
        })
    return json.dumps(out)

def build_buttons_js(top_coins):
    btns = [{"id": "ALL", "label": "ALL"}]
    for c in list(top_coins.keys())[:12]:
        btns.append({"id": c, "label": c})
    return json.dumps(btns)

JS = r"""
var WALLETS = DATA_PLACEHOLDER;
var BUTTONS = BTNS_PLACEHOLDER;
var ANOMALY = THRESH_PLACEHOLDER;

var TIER_COLOR = {
  apex:'#FFD700', whale:'#4C8EDA', dormant_whale:'#6E7681',
  shark:'#2EC4B6', dolphin:'#48BB78'
};

/*  helpers  */
function fmt(v) {
  var a = Math.abs(v);
  if (a >= 1e9) return (v/1e9).toFixed(2)+'B';
  if (a >= 1e6) return (v/1e6).toFixed(2)+'M';
  if (a >= 1e3) return (v/1e3).toFixed(1)+'K';
  return v.toFixed(0)+'';
}

function calcBias(wallet, asset) {
  var L = 0, S = 0;
  (wallet.positions || []).forEach(function(p) {
    if (asset !== 'ALL' && p.coin !== asset) return;
    var side = p.side ? p.side.toLowerCase() : '';
    if (side === 'long')  L += Math.abs(p.notional);
    if (side === 'short') S += Math.abs(p.notional);
  });
  var tot = L + S;
  if (tot === 0) return { bias:0, L:0, S:0, tot:0, flat:true };
  return { bias:((L - S) / tot) * 100, L:L, S:S, tot:tot, flat:false };
}

function addrHash(addr) {
  var h = 0;
  for (var i = 0; i < addr.length; i++)
    h = (Math.imul(31, h) + addr.charCodeAt(i)) | 0;
  return Math.abs(h) / 2147483647;
}

function bubbleR(av) {
  return Math.max(8, Math.min(55, Math.sqrt(av / 1e5) * 4.4));
}

/*  stats panel  */
function updateStats(asset) {
  var dormCount = 0, activeCount = 0;
  var dormAV = 0, activeAV = 0;
  var totL = 0, totS = 0, totNotional = 0;

  WALLETS.forEach(function(w) {
    var b = calcBias(w, asset);
    if (b.flat) {
      dormCount++;
      dormAV += w.account_value;
    } else {
      activeCount++;
      activeAV += w.account_value;
      totL += b.L;
      totS += b.S;
      totNotional += b.tot;
    }
  });

  document.getElementById('st-total').textContent  = WALLETS.length;
  document.getElementById('st-active').textContent = activeCount;
  document.getElementById('st-dorm').textContent   = dormCount;
  document.getElementById('st-long').textContent   = '$' + fmt(totL);
  document.getElementById('st-short').textContent  = '$' + fmt(totS);
  document.getElementById('st-avact').textContent  = '$' + fmt(activeAV);
  document.getElementById('st-avdorm').textContent = '$' + fmt(dormAV);
  document.getElementById('st-lev').textContent    = '$' + fmt(totNotional);
}

/*  module-level SVG  */
var chartEl     = document.getElementById('chart');
var tooltip     = document.getElementById('tooltip');
var pinned      = null;
var curAsset    = 'ALL';
var sim         = null;
var sim2        = null;
var dormSnap    = [];   /* stable node list for dormant sim */
var activeSnap  = [];   /* stable node list for active sim  */

var svg         = d3.select('#chart').append('svg').style('width','100%').style('height','100%');
var axisLayer   = svg.append('g');
var bubbleLayer = svg.append('g');

/*  render  */
function render(asset) {
  curAsset = asset;
  updateStats(asset);

  var W = chartEl.clientWidth;
  var H = chartEl.clientHeight;
  if (!W || !H) { setTimeout(function(){ render(asset); }, 80); return; }

  var SPLIT   = H * 0.22;
  var PAD     = 30;
  var dormMid = SPLIT * 0.50;
  var actTop  = SPLIT + 16;
  var actBot  = H - 20;
  var centre  = W / 2;
  var halfW   = (W - PAD * 2) / 2;

  /* stop old sims */
  if (sim)  { sim.stop();  sim  = null; }
  if (sim2) { sim2.stop(); sim2 = null; }

  axisLayer.selectAll('*').remove();
  bubbleLayer.selectAll('*').remove();

  /* build fresh node lists — keyed by address for position memory */
  var prevPos = {};
  dormSnap.concat(activeSnap).forEach(function(n) {
    prevPos[n.address] = { x: n.x, y: n.y };
  });

  dormSnap   = [];
  activeSnap = [];

  WALLETS.forEach(function(w) {
    var b = calcBias(w, asset);
    var r = bubbleR(w.account_value);
    var node = {
      _w: w, _b: b, _r: r,
      address: w.address, label: w.label, tier: w.tier,
      isDorm: b.flat
    };
    var prev = prevPos[w.address];
    if (prev) { node.x = prev.x; node.y = prev.y; }
    if (b.flat) dormSnap.push(node);
    else        activeSnap.push(node);
  });

  /* long/short ratio -> vertical divider */
  var totL = 0, totS = 0;
  activeSnap.forEach(function(n) { totL += n._b.L; totS += n._b.S; });
  var totLS    = totL + totS || 1;
  var longPct  = totL / totLS;
  var shortPct = totS / totLS;
  var divX     = PAD + shortPct * (W - PAD * 2);

  /* log Y scale for active zone */
  var allTot = activeSnap.map(function(n){ return n._b.tot; });
  var minTot = allTot.length ? Math.min.apply(null, allTot) : 5e4;
  var maxTot = allTot.length ? Math.max.apply(null, allTot) : 1e7;
  minTot = Math.max(minTot, 1e3);
  if (maxTot <= minTot) maxTot = minTot * 10;

  var yLog = d3.scaleLog()
    .domain([minTot, maxTot])
    .range([actBot - 10, actTop + 10])
    .clamp(true);

  /* set targets */
  dormSnap.forEach(function(n) {
    n._tx = PAD + addrHash(n.address) * (W - PAD * 2);
    n._ty = dormMid;
    if (n.x === undefined || n.x === null) { n.x = n._tx; n.y = n._ty; }
  });

  /* Gap of 14px either side of divX keeps the two sides visually separate */
  var GAP      = 14;
  var shortL   = PAD;
  var shortR   = divX - GAP;
  var longL    = divX + GAP;
  var longR    = W - PAD;

  activeSnap.forEach(function(n) {
    var conviction = Math.abs(n._b.bias) / 100;  /* 1 = pure, 0 = hedged */
    var isLong = n._b.bias >= 0;
    if (isLong) {
      /* long side: pure conviction → near divX+GAP (left of long zone),
                   hedged          → near W-PAD (right of long zone) */
      n._tx = longL + (1 - conviction) * (longR - longL);
    } else {
      /* short side: pure conviction → near divX-GAP (right of short zone),
                    hedged           → near PAD (left of short zone) */
      n._tx = shortR - (1 - conviction) * (shortR - shortL);
    }
    n._ty = yLog(n._b.tot);
    if (n.x === undefined || n.x === null) { n.x = n._tx; n.y = n._ty; }
  });

  /*  axis decorations  */
  axisLayer.append('line')
    .attr('x1', 0).attr('y1', SPLIT).attr('x2', W).attr('y2', SPLIT)
    .attr('stroke', '#444').attr('stroke-dasharray', '6,4').attr('stroke-width', 1);
  axisLayer.append('text')
    .attr('x', 8).attr('y', SPLIT - 6)
    .attr('fill', '#555').attr('font-size', 10).attr('letter-spacing', 1)
    .text('DORMANT / FLAT');

  axisLayer.append('line')
    .attr('x1', divX).attr('y1', SPLIT + 4).attr('x2', divX).attr('y2', actBot)
    .attr('stroke', '#444').attr('stroke-dasharray', '4,4').attr('stroke-width', 1);

  axisLayer.append('text')
    .attr('x', PAD).attr('y', actBot + 14)
    .attr('fill', '#e05252').attr('font-size', 11)
    .text('\u2190 hedged SHORT ' + (shortPct * 100).toFixed(0) + '%');
  axisLayer.append('text')
    .attr('x', W - PAD).attr('y', actBot + 14)
    .attr('fill', '#52e07c').attr('font-size', 11).attr('text-anchor', 'end')
    .text((longPct * 100).toFixed(0) + '% LONG hedged \u2192');
  axisLayer.append('text')
    .attr('x', centre).attr('y', actBot + 14)
    .attr('fill', '#666').attr('font-size', 11).attr('text-anchor', 'middle')
    .text('pure conviction');

  /*  draw bubbles  */
  /* dormant layer */
  var dormSel = bubbleLayer.selectAll('g.dorm')
    .data(dormSnap, function(d){ return d.address; });
  var dormEnter = dormSel.enter().append('g').attr('class', 'dorm node').style('cursor','pointer');
  dormEnter.append('circle')
    .attr('r', function(d){ return d._r; })
    .attr('fill', '#6E7681').attr('fill-opacity', 0.55)
    .attr('stroke', '#8b949e').attr('stroke-width', 1);
  dormEnter.append('text')
    .attr('text-anchor','middle').attr('dy','0.35em')
    .attr('font-size', function(d){ return Math.max(7, d._r * 0.42); })
    .attr('fill','#8b949e').attr('pointer-events','none')
    .text(function(d){ return d.label; });
  dormSel.exit().remove();
  var dormAll = dormEnter.merge(dormSel);
  dormAll.attr('transform', function(d){ return 'translate('+d._tx+','+d._ty+')'; });

  /* active layer */
  var actSel = bubbleLayer.selectAll('g.active')
    .data(activeSnap, function(d){ return d.address; });
  var actEnter = actSel.enter().append('g').attr('class','active node').style('cursor','pointer');
  actEnter.append('circle')
    .attr('r', function(d){ return d._r; })
    .attr('fill', function(d){ return TIER_COLOR[d.tier] || '#4C8EDA'; })
    .attr('fill-opacity', 0.85)
    .attr('stroke', function(d){ return TIER_COLOR[d.tier] || '#4C8EDA'; })
    .attr('stroke-width', 1.5);
  actEnter.each(function(d) {
    if (d._b.tot >= ANOMALY) {
      d3.select(this).append('circle')
        .attr('class','pulse').attr('r', d._r + 5)
        .attr('fill','none')
        .attr('stroke', TIER_COLOR[d.tier] || '#fff')
        .attr('stroke-width', 1.5).attr('stroke-opacity', 0.5);
    }
  });
  actEnter.append('text')
    .attr('text-anchor','middle').attr('dy','0.35em')
    .attr('font-size', function(d){ return Math.max(8, d._r * 0.45); })
    .attr('fill','#fff').attr('pointer-events','none')
    .text(function(d){ return d.label; });
  actSel.exit().remove();
  var actAll = actEnter.merge(actSel);
  actAll.attr('transform', function(d){ return 'translate('+d._tx+','+d._ty+')'; });

  /* tooltip events on all nodes */
  bubbleLayer.selectAll('g.node')
    .on('mouseover', function(event, d) { if (!pinned) showTip(event, d); })
    .on('mousemove', function(event)    { if (!pinned) moveTip(event); })
    .on('mouseout',  function()         { if (!pinned) tooltip.style.display = 'none'; })
    .on('click', function(event, d) {
      if (pinned === d.address) { pinned = null; tooltip.style.display = 'none'; }
      else { pinned = d.address; showTip(event, d); }
      event.stopPropagation();
    });

  /*  sim: dormant  */
  sim = d3.forceSimulation(dormSnap)
    .alphaDecay(0.03)
    .force('cx', d3.forceX(function(d){ return d._tx; }).strength(0.12))
    .force('cy', d3.forceY(dormMid).strength(0.85))
    .force('collide', d3.forceCollide(function(d){ return d._r + 2; }).strength(0.9))
    .on('tick', function() {
      dormSnap.forEach(function(d) {
        var lo = d._r + 2;
        var hi = SPLIT - d._r - 2;
        if (hi < lo) hi = lo;
        d.y = Math.max(lo, Math.min(hi, d.y));
      });
      bubbleLayer.selectAll('g.dorm')
        .attr('transform', function(d){ return 'translate('+d.x+','+d.y+')'; });
    });

  /*  sim2: active  */
  sim2 = d3.forceSimulation(activeSnap)
    .alphaDecay(0.03)
    .force('cx', d3.forceX(function(d){ return d._tx; }).strength(0.55))
    .force('cy', d3.forceY(function(d){ return d._ty; }).strength(0.28))
    .force('collide', d3.forceCollide(function(d){ return d._r + 2; }).strength(0.9))
    .on('tick', function() {
      activeSnap.forEach(function(d) {
        var lo = actTop + d._r;
        var hi = actBot  - d._r;
        if (hi < lo) hi = lo;
        d.y = Math.max(lo, Math.min(hi, d.y));
        /* hard X clamp — keep long right of divX+GAP, short left of divX-GAP */
        var isLong = d._b.bias >= 0;
        if (isLong) {
          if (d.x < divX + GAP + d._r) d.x = divX + GAP + d._r;
        } else {
          if (d.x > divX - GAP - d._r) d.x = divX - GAP - d._r;
        }
      });
      bubbleLayer.selectAll('g.active')
        .attr('transform', function(d){ return 'translate('+d.x+','+d.y+')'; });
    });
}

/*  tooltip  */
function showTip(event, d) {
  var w = d._w, b = d._b;
  var html = '<strong>' + w.label + '</strong><br>'
    + 'Tier: ' + w.tier + '&nbsp;&nbsp;AV: $' + fmt(w.account_value) + '<br>';
  if (!b.flat) {
    html += 'Bias: ' + b.bias.toFixed(1) + '%<br>'
      + 'Long: $' + fmt(b.L) + '&nbsp;&nbsp;Short: $' + fmt(b.S) + '<br>';
    (w.positions || []).forEach(function(p) {
      if (curAsset !== 'ALL' && p.coin !== curAsset) return;
      html += p.coin + ' ' + (p.side||'').toUpperCase() + ' $' + fmt(Math.abs(p.notional));
      if (p.upnl) html += ' PnL: ' + fmt(p.upnl);
      html += '<br>';
    });
  } else {
    html += 'No open positions';
  }
  tooltip.innerHTML = html;
  tooltip.style.display = 'block';
  moveTip(event);
}

function moveTip(event) {
  var W = chartEl.clientWidth;
  var H = chartEl.clientHeight;
  var x = event.clientX + 14;
  var y = event.clientY + 14;
  if (x + 240 > W) x = event.clientX - 250;
  if (y + 200 > H) y = event.clientY - 210;
  tooltip.style.left = x + 'px';
  tooltip.style.top  = y + 'px';
}

/*  coin filter buttons  */
(function buildButtons() {
  var bar = document.getElementById('btnbar');
  BUTTONS.forEach(function(b) {
    var el = document.createElement('button');
    el.textContent = b.label;
    el.className = b.id === 'ALL' ? 'btn active' : 'btn';
    el.addEventListener('click', function() {
      document.querySelectorAll('#btnbar .btn').forEach(function(x){ x.classList.remove('active'); });
      el.classList.add('active');
      render(b.id);
    });
    bar.appendChild(el);
  });
})();

document.getElementById('chart').addEventListener('click', function() {
  pinned = null; tooltip.style.display = 'none';
});

render('ALL');
window.addEventListener('resize', function() { render(curAsset); });
"""

CSS = """
*, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
html, body { width:100%; height:100%; background:#0d1117; color:#c9d1d9;
  font-family:'Segoe UI',sans-serif; overflow:hidden; }
#app { display:flex; flex-direction:column; height:100vh; }

/*  stats panel (top 20%)  */
#stats {
  height:20vh; min-height:130px; flex-shrink:0;
  background:#0d1117; border-bottom:1px solid #21262d;
  display:flex; flex-direction:column; justify-content:center;
  padding:0 20px; gap:8px;
}
#stats-title {
  font-size:15px; font-weight:600; color:#e6edf3; letter-spacing:0.5px;
}
#stats-title span { font-size:11px; color:#8b949e; font-weight:400; margin-left:10px; }
#stats-bottom {
  display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px;
}
#stats-row {
  display:flex; flex-wrap:wrap; gap:6px 10px;
}
.stat-card {
  background:#161b22; border:1px solid #21262d; border-radius:6px;
  padding:6px 14px; display:flex; flex-direction:column; align-items:center; gap:2px;
  min-width:90px;
}
.stat-label { font-size:10px; color:#8b949e; text-transform:uppercase; letter-spacing:0.8px; }
.stat-val   { font-size:15px; font-weight:600; color:#e6edf3; }
.stat-val.green { color:#52e07c; }
.stat-val.red   { color:#e05252; }
.stat-val.blue  { color:#4C8EDA; }
.stat-val.grey  { color:#8b949e; }

/*  tier legend  */
#legend {
  display:flex; align-items:center; gap:14px; flex-wrap:wrap;
  padding:0 4px;
}
.leg-item { display:flex; align-items:center; gap:5px; }
.leg-dot  { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
.leg-lbl  { font-size:11px; color:#8b949e; }

/*  coin buttons  */
#btnbar {
  display:flex; flex-wrap:wrap; gap:5px; padding:5px 12px;
  background:#0d1117; border-bottom:1px solid #21262d; flex-shrink:0;
}
.btn { background:#161b22; color:#8b949e; border:1px solid #21262d;
  border-radius:4px; padding:3px 10px; font-size:11px; cursor:pointer; }
.btn.active, .btn:hover { background:#388bfd22; border-color:#388bfd; color:#58a6ff; }

/*  bubble canvas (bottom 80%)  */
#chart { flex:1; position:relative; overflow:hidden; }

/*  tooltip  */
#tooltip {
  position:fixed; background:#161b22ee; border:1px solid #30363d;
  border-radius:6px; padding:8px 12px; font-size:12px; pointer-events:none;
  display:none; max-width:260px; line-height:1.6; z-index:100;
}
@keyframes pulse { 0%,100%{stroke-opacity:.5;} 50%{stroke-opacity:.1;} }
.pulse { animation:pulse 2s ease-in-out infinite; }
"""

def build_html(snap):
    wallets    = snap.get("wallets", [])
    fetched_at = snap.get("fetched_at", "")
    top_coins  = snap.get("top_coins", {})

    js = (JS
          .replace("DATA_PLACEHOLDER", build_wallet_js(wallets))
          .replace("BTNS_PLACEHOLDER", build_buttons_js(top_coins))
          .replace("THRESH_PLACEHOLDER", "5000000"))

    stats_cards = (
        "<div class='stat-card'>"
          "<span class='stat-label'>Total Wallets</span>"
          "<span class='stat-val blue' id='st-total'>-</span>"
        "</div>"
        "<div class='stat-card'>"
          "<span class='stat-label'>Active</span>"
          "<span class='stat-val green' id='st-active'>-</span>"
        "</div>"
        "<div class='stat-card'>"
          "<span class='stat-label'>Dormant</span>"
          "<span class='stat-val grey' id='st-dorm'>-</span>"
        "</div>"
        "<div class='stat-card'>"
          "<span class='stat-label'>Total Long</span>"
          "<span class='stat-val green' id='st-long'>-</span>"
        "</div>"
        "<div class='stat-card'>"
          "<span class='stat-label'>Total Short</span>"
          "<span class='stat-val red' id='st-short'>-</span>"
        "</div>"
        "<div class='stat-card'>"
          "<span class='stat-label'>Active AUM</span>"
          "<span class='stat-val blue' id='st-avact'>-</span>"
        "</div>"
        "<div class='stat-card'>"
          "<span class='stat-label'>Dormant AUM</span>"
          "<span class='stat-val grey' id='st-avdorm'>-</span>"
        "</div>"
        "<div class='stat-card'>"
          "<span class='stat-label'>Total Notional</span>"
          "<span class='stat-val' id='st-lev'>-</span>"
        "</div>"
    )

    legend_html = (
        "<div id='legend'>"
        "<span style='font-size:10px;color:#555;text-transform:uppercase;letter-spacing:0.8px;margin-right:4px;'>Tier</span>"
        "<div class='leg-item'><div class='leg-dot' style='background:#FFD700'></div><span class='leg-lbl'>Apex</span></div>"
        "<div class='leg-item'><div class='leg-dot' style='background:#4C8EDA'></div><span class='leg-lbl'>Whale</span></div>"
        "<div class='leg-item'><div class='leg-dot' style='background:#2EC4B6'></div><span class='leg-lbl'>Shark</span></div>"
        "<div class='leg-item'><div class='leg-dot' style='background:#48BB78'></div><span class='leg-lbl'>Dolphin</span></div>"
        "<div class='leg-item'><div class='leg-dot' style='background:#6E7681'></div><span class='leg-lbl'>Dormant</span></div>"
        "</div>"
    )

    return (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>HyperWhale Bubble Map</title>"
        "<script src='https://d3js.org/d3.v7.min.js'></script>"
        "<style>" + CSS + "</style></head><body>"
        "<div id='app'>"
        "<div id='stats'>"
          "<div id='stats-title'>&#x1F433; HyperWhale"
            "<span>Snapshot: " + fetched_at + "</span>"
          "</div>"
          "<div id='stats-bottom'>"
            "<div id='stats-row'>" + stats_cards + "</div>"
            + legend_html +
          "</div>"
        "</div>"
        "<div id='btnbar'></div>"
        "<div id='chart'></div>"
        "</div>"
        "<div id='tooltip'></div>"
        "<script>" + js + "</script>"
        "</body></html>"
    )

def main():
    parser = argparse.ArgumentParser(description="HyperWhale bubble map")
    parser.add_argument("--data",    default=DATA_FILE)
    parser.add_argument("--output",  default=OUT_FILE)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    snap = load_snapshot(args.data)
    html = build_html(snap)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    print("Written: {} ({:,} chars)".format(args.output, len(html)))
    if not args.no_open:
        webbrowser.open("file:///" + args.output.replace("\\", "/"))

if __name__ == "__main__":
    main()
