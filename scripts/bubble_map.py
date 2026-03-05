# bubble_map.py  --  D3 force-simulation bubble map for HyperWhale
import argparse, json, os, webbrowser

BASE           = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE      = os.path.join(BASE, "data", "live_positions_snapshot.json")
WHALE_FILE     = os.path.join(BASE, "data", "whale_addresses.json")
OUT_FILE       = os.path.join(BASE, "reports", "bubble_map.html")

def load_snapshot(path=DATA_FILE):
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)

    # Build staking lookup from whale_addresses.json (source of truth)
    staking_lookup = {}
    if os.path.exists(WHALE_FILE):
        with open(WHALE_FILE, encoding="utf-8") as f:
            for w in json.load(f).get("whales", []):
                staking_lookup[w["address"].lower()] = w.get("staked_hype_tier", "none")

    # Backfill staked_hype_tier into snapshot wallets — always from registry
    for w in snap.get("wallets", []):
        w["staked_hype_tier"] = staking_lookup.get(w["address"].lower(), "none")

    return snap

def build_wallet_js(wallets):
    out = []
    for w in wallets:
        out.append({
            "address":       w.get("address", ""),
            "label":            w.get("label", w.get("address", "")[:8]),
            "tier":             w.get("tier", "dolphin"),
            "whale_score":      w.get("whale_score", 0),
            "account_value":    w.get("account_value", 0),
            "staked_hype_tier": w.get("staked_hype_tier", "none"),
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

/* staker ring visual config — keyed by staked_hype_tier */
var STAKER_RING = {
  elite: { width: 3.5, color: '#FFD700', opacity: 0.95, gap: 3 },
  high:  { width: 2.5, color: '#E8C84A', opacity: 0.80, gap: 3 },
  mid:   { width: 2.0, color: '#C4A832', opacity: 0.65, gap: 2 },
  low:   { width: 1.5, color: '#A08820', opacity: 0.45, gap: 2 },
};

function stakerRing(sel) {
  /* rings are only drawn when the staker toggle is active */
  if (!curStakerFilter) return;
  sel.each(function(d) {
    var st = (d._w && d._w.staked_hype_tier) || 'none';
    /* if a staking tier sub-filter is active, skip wallets that don't match */
    if (curStakingTier !== 'ALL' && st !== curStakingTier) return;
    var cfg = STAKER_RING[st];
    if (!cfg) return;
    d3.select(this).append('circle')
      .attr('class', 'staker-ring')
      .attr('r', d._r + cfg.gap + cfg.width / 2)
      .attr('fill', 'none')
      .attr('stroke', cfg.color)
      .attr('stroke-width', cfg.width)
      .attr('stroke-opacity', cfg.opacity);
  });
}

/* ---------------------------------------------------------------
   Tier filter — which tiers are currently visible
   'ALL' means no filter applied
--------------------------------------------------------------- */
var curTierFilter   = 'ALL';
var curStakerFilter = false;   /* true = highlight stakers + show staker bias panel */

function getVisibleWallets() {
  /* staker toggle NEVER hides bubbles — it only affects the staker bias panel */
  if (curTierFilter === 'ALL') return WALLETS;
  return WALLETS.filter(function(w) {
    return (w.tier || 'dolphin').toLowerCase() === curTierFilter.toLowerCase();
  });
}

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
  var visWallets = getVisibleWallets();
  var dormCount = 0, activeCount = 0;
  var dormAV = 0, activeAV = 0;
  var totL = 0, totS = 0, totNotional = 0;

  visWallets.forEach(function(w) {
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

  document.getElementById('st-total').textContent  = visWallets.length;
  document.getElementById('st-active').textContent = activeCount;
  document.getElementById('st-dorm').textContent   = dormCount;
  document.getElementById('st-long').textContent   = '$' + fmt(totL);
  document.getElementById('st-short').textContent  = '$' + fmt(totS);
  document.getElementById('st-avact').textContent  = '$' + fmt(activeAV);
  document.getElementById('st-avdorm').textContent = '$' + fmt(dormAV);
  document.getElementById('st-lev').textContent    = '$' + fmt(totNotional);

  updateSmartMoneyBias(asset);
  updateStakerBias(asset);
}

/* ---------------------------------------------------------------
   Smart Money Bias — APEX + WHALE tier only, for the current coin
--------------------------------------------------------------- */
function updateSmartMoneyBias(asset) {
  var smL = 0, smS = 0, smCount = 0;
  WALLETS.forEach(function(w) {
    var t = (w.tier || '').toLowerCase();
    if (t !== 'apex' && t !== 'whale') return;
    var b = calcBias(w, asset);
    if (b.flat) return;
    smL += b.L;
    smS += b.S;
    smCount++;
  });

  var smTot = smL + smS;
  var panel = document.getElementById('sm-bias-panel');
  if (!panel) return;

  if (smTot === 0 || smCount === 0) {
    panel.innerHTML = '<span style="color:#666;font-size:13px;font-weight:600;">No APEX/WHALE positions' +
      (asset !== 'ALL' ? ' in ' + asset : '') + '</span>';
    return;
  }

  var longPct  = (smL / smTot * 100).toFixed(1);
  var shortPct = (smS / smTot * 100).toFixed(1);
  var longBarW  = (smL / smTot * 100).toFixed(1);
  var shortBarW = (smS / smTot * 100).toFixed(1);

  /* bias label */
  var biasNum = ((smL - smS) / smTot * 100);
  var biasLabel, biasColor;
  if      (biasNum >=  60) { biasLabel = 'STRONG LONG';  biasColor = '#52e07c'; }
  else if (biasNum >=  25) { biasLabel = 'LEAN LONG';    biasColor = '#85e09a'; }
  else if (biasNum >= -25) { biasLabel = 'NEUTRAL';      biasColor = '#8b949e'; }
  else if (biasNum >= -60) { biasLabel = 'LEAN SHORT';   biasColor = '#e08585'; }
  else                     { biasLabel = 'STRONG SHORT'; biasColor = '#e05252'; }

  var coinLabel = asset === 'ALL' ? 'ALL COINS' : asset;

  panel.innerHTML =
    /* row 1: header + bias label */
    '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">' +
      '<span style="font-size:13px;font-weight:700;color:#e6edf3;letter-spacing:.8px;white-space:nowrap;">' +
        '&#x1F9E0; Smart Money — ' + coinLabel + '</span>' +
      '<span style="font-size:15px;font-weight:800;color:' + biasColor + ';white-space:nowrap;letter-spacing:.5px;">' +
        biasLabel + '</span>' +
      '<span style="font-size:12px;font-weight:600;color:#8b949e;white-space:nowrap;">' +
        smCount + ' wallets&nbsp;·&nbsp;$' + fmt(smTot) + ' notional</span>' +
    '</div>' +
    /* row 2: bar + percentages */
    '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">' +
      '<div style="display:flex;height:16px;border-radius:5px;overflow:hidden;width:240px;flex-shrink:0;">' +
        '<div style="width:' + longBarW  + '%;background:#52e07c;"></div>' +
        '<div style="width:' + shortBarW + '%;background:#e05252;"></div>' +
      '</div>' +
      '<span style="font-size:14px;font-weight:700;color:#52e07c;white-space:nowrap;">' + longPct  + '% L</span>' +
      '<span style="font-size:14px;font-weight:700;color:#e05252;white-space:nowrap;">' + shortPct + '% S</span>' +
    '</div>';
}

/* ---------------------------------------------------------------
   Staker Bias — only wallets with any staking tier, current coin
   Panel is shown/hidden based on curStakerFilter toggle
--------------------------------------------------------------- */
function updateStakerBias(asset) {
  var panel = document.getElementById('staker-bias-panel');
  var sep   = document.getElementById('staker-sep');
  if (!panel) return;

  /* hide everything when toggle is off */
  if (!curStakerFilter) {
    panel.style.display = 'none';
    if (sep) sep.style.display = 'none';
    return;
  }
  if (sep) sep.style.display = 'block';
  panel.style.display = 'flex';

  var stL = 0, stS = 0, stDorm = 0, stCount = 0;
  getVisibleWallets().forEach(function(w) {
    var wst = (w.staked_hype_tier || 'none');
    if (wst === 'none') return;
    /* apply staking tier sub-filter */
    if (curStakingTier !== 'ALL' && wst !== curStakingTier) return;
    var b = calcBias(w, asset);
    stCount++;
    if (b.flat) { stDorm++; return; }
    stL += b.L;
    stS += b.S;
  });

  var stTot = stL + stS;
  var coinLabel = asset === 'ALL' ? 'ALL COINS' : asset;
  var tierLabel = curStakingTier === 'ALL' ? 'All Stakers' : curStakingTier.charAt(0).toUpperCase() + curStakingTier.slice(1) + ' Stakers';

  if (stCount === 0 || stTot === 0) {
    panel.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;">' +
        '<span style="font-size:13px;font-weight:700;color:#FFD700;white-space:nowrap;">&#x1F48E; ' + tierLabel + '</span>' +
        '<span style="font-size:12px;color:#666;">No positions' + (asset !== 'ALL' ? ' in ' + asset : '') + '</span>' +
      '</div>';
    return;
  }

  var longPct  = (stL / stTot * 100).toFixed(1);
  var shortPct = (stS / stTot * 100).toFixed(1);
  var activeCount = stCount - stDorm;

  var biasNum = ((stL - stS) / stTot * 100);
  var biasLabel, biasColor;
  if      (biasNum >=  60) { biasLabel = 'STRONG LONG';  biasColor = '#52e07c'; }
  else if (biasNum >=  25) { biasLabel = 'LEAN LONG';    biasColor = '#85e09a'; }
  else if (biasNum >= -25) { biasLabel = 'NEUTRAL';      biasColor = '#8b949e'; }
  else if (biasNum >= -60) { biasLabel = 'LEAN SHORT';   biasColor = '#e08585'; }
  else                     { biasLabel = 'STRONG SHORT'; biasColor = '#e05252'; }

  panel.innerHTML =
    '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">' +
      '<span style="font-size:13px;font-weight:700;color:#FFD700;letter-spacing:.8px;white-space:nowrap;">' +
        '&#x1F48E; ' + tierLabel + ' — ' + coinLabel + '</span>' +
      '<span style="font-size:15px;font-weight:800;color:' + biasColor + ';white-space:nowrap;">' +
        biasLabel + '</span>' +
      '<span style="font-size:12px;font-weight:600;color:#8b949e;white-space:nowrap;">' +
        activeCount + ' active&nbsp;·&nbsp;' + stDorm + ' dormant&nbsp;·&nbsp;$' + fmt(stTot) + '</span>' +
    '</div>' +
    '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">' +
      '<div style="display:flex;height:16px;border-radius:5px;overflow:hidden;width:200px;flex-shrink:0;">' +
        '<div style="width:' + longPct  + '%;background:#52e07c;"></div>' +
        '<div style="width:' + shortPct + '%;background:#e05252;"></div>' +
      '</div>' +
      '<span style="font-size:14px;font-weight:700;color:#52e07c;white-space:nowrap;">' + longPct  + '% L</span>' +
      '<span style="font-size:14px;font-weight:700;color:#e05252;white-space:nowrap;">' + shortPct + '% S</span>' +
    '</div>';
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

  var visWallets = getVisibleWallets();
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

  visWallets.forEach(function(w) {
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
  activeSnap.forEach(function(n) { totL += n._b.L; totS += n._b.S; });  var totLS    = totL + totS || 1;
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
  dormEnter.call(stakerRing);
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
  actEnter.call(stakerRing);
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
    })
    .on('dblclick', function(event, d) {
      var slug = d.address.slice(0, 10).toLowerCase();
      window.open('wallet_' + slug + '.html', '_blank');
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
  var stLabel = { elite:'💎 Elite Staker', high:'💎 High Staker', mid:'💎 Mid Staker', low:'💎 Low Staker' };
  var stBadge = (w.staked_hype_tier && stLabel[w.staked_hype_tier])
    ? '<span style="background:#2a2000;border:1px solid #FFD700;color:#FFD700;' +
      'border-radius:3px;padding:1px 6px;font-size:10px;font-weight:700;margin-left:6px;">' +
      stLabel[w.staked_hype_tier] + '</span>'
    : '';
  var html = '<strong>' + w.label + '</strong>' + stBadge + '<br>'
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
  var addr = d.address;
  tooltip.innerHTML += '<div style="margin-top:6px;font-size:10px;color:#8b949e;">double-click to open profile ↗</div>';
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

/*  tier filter buttons  */
(function buildTierButtons() {
  var bar  = document.getElementById('tier-buttons');
  var tiers = [
    { id:'ALL',    label:'ALL TIERS', color:'#c9d1d9' },
    { id:'apex',   label:'⭐ APEX',   color:'#FFD700' },
    { id:'whale',  label:'🐋 WHALE',  color:'#4C8EDA' },
    { id:'shark',  label:'🦈 SHARK',  color:'#2EC4B6' },
    { id:'dolphin',label:'🐬 DOLPHIN',color:'#48BB78' },
  ];
  tiers.forEach(function(t) {
    var el = document.createElement('button');
    el.textContent = t.label;
    el.className = t.id === 'ALL' ? 'btn tier-btn active' : 'btn tier-btn';
    el.style.setProperty('--tier-color', t.color);
    el.addEventListener('click', function() {
      document.querySelectorAll('#tier-buttons .tier-btn').forEach(function(x){ x.classList.remove('active'); });
      el.classList.add('active');
      curTierFilter = t.id;
      render(curAsset);
    });
    bar.appendChild(el);
  });
})();

/* staker column — toggle + staking tier sub-filter + bias panel */
var curStakingTier = 'ALL';   /* ALL / elite / high / mid / low */

(function buildStakerSection() {
  var col = document.getElementById('staker-col');
  if (!col) return;

  /* ── row 1: toggle button ── */
  var row1 = document.createElement('div');
  row1.style.cssText = 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;';

  var stakerBtn = document.createElement('button');
  stakerBtn.id = 'staker-toggle';
  stakerBtn.textContent = '\uD83D\uDC8E STAKERS OFF';
  stakerBtn.className = 'btn staker-btn';
  stakerBtn.title = 'Show only wallets with staked HYPE';
  row1.appendChild(stakerBtn);
  col.appendChild(row1);

  /* ── row 2: staking tier sub-buttons (greyed when toggle off) ── */
  var row2 = document.createElement('div');
  row2.id = 'staking-tier-row';
  row2.style.cssText = 'display:flex;align-items:center;gap:6px;flex-wrap:wrap;opacity:0.3;pointer-events:none;';

  var stakingTiers = [
    { id:'ALL',   label:'ALL STAKERS' },
    { id:'elite', label:'\uD83D\uDC8E ELITE' },
    { id:'high',  label:'\uD83D\uDC8E HIGH' },
    { id:'mid',   label:'\uD83D\uDC8E MID' },
    { id:'low',   label:'\uD83D\uDC8E LOW' },
  ];
  stakingTiers.forEach(function(t) {
    var el = document.createElement('button');
    el.textContent = t.label;
    el.className = t.id === 'ALL' ? 'btn staking-tier-btn active' : 'btn staking-tier-btn';
    el.dataset.stid = t.id;
    el.addEventListener('click', function() {
      document.querySelectorAll('.staking-tier-btn').forEach(function(x){ x.classList.remove('active'); });
      el.classList.add('active');
      curStakingTier = t.id;
      render(curAsset);
    });
    row2.appendChild(el);
  });
  col.appendChild(row2);

  /* ── row 3: bias panel ── */
  var row3 = document.createElement('div');
  row3.id = 'staker-bias-panel';
  row3.style.cssText = 'display:none;flex-direction:column;gap:8px;';
  col.appendChild(row3);

  /* toggle click handler */
  stakerBtn.addEventListener('click', function() {
    curStakerFilter = !curStakerFilter;
    stakerBtn.classList.toggle('active', curStakerFilter);
    stakerBtn.textContent = curStakerFilter ? '\uD83D\uDC8E STAKERS ON' : '\uD83D\uDC8E STAKERS OFF';
    /* enable / disable sub-filter row */
    row2.style.opacity = curStakerFilter ? '1' : '0.3';
    row2.style.pointerEvents = curStakerFilter ? 'auto' : 'none';
    render(curAsset);
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
.stat-label { font-size:11px; color:#8b949e; text-transform:uppercase; letter-spacing:0.8px; font-weight:700; }
.stat-val   { font-size:16px; font-weight:700; color:#ffffff; }
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
.leg-lbl  { font-size:12px; color:#c9d1d9; font-weight:600; }

/*  ── two-column control panel ──────────────────────────────────────
    LEFT  col: coin filter buttons (row 1) + tier filter buttons (row 2)
    RIGHT col: smart money bias (fills remaining width)
    Separated by a vertical divider.
-------------------------------------------------------------------- */
#ctrlpanel {
  display:flex; flex-direction:row; flex-shrink:0;
  background:#0d1117; border-bottom:1px solid #21262d;
  overflow:hidden;
}

/* ---- left column ---- */
#ctrl-left {
  display:flex; flex-direction:column; flex-shrink:0;
  padding:8px 14px; gap:8px;
}

/* section label (COINS / FILTER) */
.ctrl-label {
  font-size:10px; font-weight:700; color:#e6edf3;
  letter-spacing:1.2px; text-transform:uppercase; margin-bottom:2px;
}

/* coin & tier button rows */
#btnbar {
  display:flex; flex-wrap:wrap; gap:6px;
}
#tier-buttons {
  display:flex; flex-wrap:wrap; gap:6px;
}

/* shared button style */
.btn {
  background:#161b22; color:#c9d1d9; border:1px solid #21262d;
  border-radius:5px; padding:5px 13px; font-size:13px;
  font-weight:600; cursor:pointer; white-space:nowrap;
}
.btn.active, .btn:hover {
  background:#388bfd22; border-color:#388bfd; color:#ffffff;
}
.tier-btn {
  background:#161b22; border:1px solid #21262d;
  border-radius:5px; padding:5px 13px; font-size:13px;
  font-weight:600; cursor:pointer;
  color: var(--tier-color, #c9d1d9); white-space:nowrap;
}
.tier-btn.active, .tier-btn:hover {
  background: color-mix(in srgb, var(--tier-color, #388bfd) 18%, transparent);
  border-color: var(--tier-color, #388bfd); color:#ffffff;
}

/* staker toggle button — gold theme, independent toggle */
.staker-btn {
  background:#1a1400; border:1px solid #4a3800; color:#C4A832;
  border-radius:5px; padding:5px 13px; font-size:13px; font-weight:700;
  cursor:pointer; white-space:nowrap; letter-spacing:.3px;
}
.staker-btn.active, .staker-btn:hover {
  background:#2a2000; border-color:#FFD700; color:#FFD700;
  box-shadow: 0 0 8px #FFD70044;
}

/* ---- vertical divider ---- */
#ctrl-sep {
  width:1px; background:#21262d; flex-shrink:0; margin:10px 0;
}

/* ---- right columns (smart money + staker) ---- */
#sm-col {
  flex:1; min-width:0; padding:10px 18px;
  display:flex; flex-direction:column; justify-content:center; gap:8px;
}
#sm-bias-panel { display:flex; flex-direction:column; gap:8px; }

/* vertical divider before staker col — hidden until toggle on */
#staker-sep {
  width:1px; background:#21262d; flex-shrink:0; margin:10px 0; display:none;
}

/* staker column */
#staker-col {
  flex:1; min-width:0; padding:10px 18px;
  display:flex; flex-direction:column; justify-content:center; gap:8px;
}

/* staking tier sub-buttons */
.staking-tier-btn {
  background:#1a1400; border:1px solid #4a3800; color:#C4A832;
  border-radius:5px; padding:4px 10px; font-size:12px; font-weight:600;
  cursor:pointer; white-space:nowrap;
}
.staking-tier-btn.active, .staking-tier-btn:hover {
  background:#2a2000; border-color:#FFD700; color:#FFD700;
}

/*  bubble canvas (bottom)  */
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
        "<div class='leg-item'>"
          "<div class='leg-dot' style='background:none;border:2px solid #FFD700;box-sizing:border-box;'></div>"
          "<span class='leg-lbl' style='color:#FFD700;'>💎 Staker</span>"
        "</div>"
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
        "<div id='ctrlpanel'>"
          "<div id='ctrl-left'>"
            "<div><span class='ctrl-label'>&#x1F4B9; Coins</span>"
              "<div id='btnbar'></div>"
            "</div>"
            "<div><span class='ctrl-label'>&#x1F50D; Filter</span>"
              "<div id='tier-buttons'></div>"
            "</div>"
          "</div>"
          "<div id='ctrl-sep'></div>"
          "<div id='sm-col'>"
            "<div id='sm-bias-panel'></div>"
          "</div>"
          "<div id='staker-sep'></div>"
          "<div id='staker-col'></div>"
        "</div>"
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
