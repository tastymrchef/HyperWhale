
const WALLETS = [];
const BUTTONS  = ["ALL","BTC","ETH","HYPE","SOL","PUMP","XRP","ZEC","XPL"];
const ANOMALY  = 5000000;

const TIER_COLOR = {
  apex:          '#FFD700',
  whale:         '#4C8EDA',
  dormant_whale: '#6E7681',
  shark:         '#2EC4B6',
  dolphin:       '#48BB78',
  skip:          '#6E7681',
};
const TIER_EMOJI = {
  apex:'💎', whale:'🐋', dormant_whale:'😴', shark:'🦈', dolphin:'🐬', skip:'·'
};

// ── helpers ──────────────────────────────────────────────────────────────
function fmt(v) {
  const a = Math.abs(v);
  if (a >= 1e9) return '$' + (v/1e9).toFixed(2) + 'B';
  if (a >= 1e6) return '$' + (v/1e6).toFixed(2) + 'M';
  if (a >= 1e3) return '$' + (v/1e3).toFixed(1)  + 'K';
  return '$' + v.toFixed(0);
}

function calcBias(wallet, asset) {
  let L = 0, S = 0;
  for (const p of wallet.positions) {
    if (asset !== 'ALL' && p.coin !== asset) continue;
    if (p.side === 'long') L += p.notional;
    else                   S += p.notional;
  }
  const tot = L + S;
  if (tot === 0) return { bias:0, L:0, S:0, tot:0, flat:true };
  return { bias:(L-S)/tot*100, L, S, tot, flat:false };
}

function radius(av) {
  // $100k->8px  $1M->14px  $10M->28px  $100M->55px
  return Math.max(8, Math.min(55, Math.sqrt(av / 1e5) * 4.4));
}

// ── DOM refs ─────────────────────────────────────────────────────────────
const chartEl  = document.getElementById('chart');
const tooltip  = document.getElementById('tooltip');
let   pinned   = null;
let   curAsset = 'ALL';

// ── SVG skeleton ─────────────────────────────────────────────────────────
const svg = d3.select('#chart').append('svg')
  .style('width','100%').style('height','100%');

const axisLayer   = svg.append('g').attr('id','axis-layer');
const bubbleLayer = svg.append('g').attr('id','bubble-layer');

// ── Simulation handles ────────────────────────────────────────────────────
let sim  = null;   // dormant band
let sim2 = null;   // active band

// ── Render ────────────────────────────────────────────────────────────────
function render(asset) {
  curAsset = asset;
  const W = chartEl.clientWidth;
  const H = chartEl.clientHeight;
  if (!W || !H) { setTimeout(function(){ render(asset); }, 80); return; }

  // enrich nodes
  const nodes = WALLETS.map(function(w) {
    const b  = calcBias(w, asset);
    const r  = radius(w.account_value);
    const anomaly = w.positions.some(function(p) {
      return (asset === 'ALL' || p.coin === asset) && p.notional >= ANOMALY;
    });
    const node = Object.assign({}, w);
    node._b = b; node._r = r; node._anomaly = anomaly;
    return node;
  });

  // ── stats bar ──
  const active = nodes.filter(function(n){ return !n._b.flat; });
  const flat   = nodes.filter(function(n){ return  n._b.flat; });
  const longs  = active.filter(function(n){ return n._b.bias > 10; });
  const shorts = active.filter(function(n){ return n._b.bias < -10; });
  const totNtl = nodes.reduce(function(s,n){ return s + n._b.tot; }, 0);
  const totL   = nodes.reduce(function(s,n){ return s + n._b.L;   }, 0);
  const totS   = nodes.reduce(function(s,n){ return s + n._b.S;   }, 0);
  const grand  = totL + totS;
  const bearPct = grand > 0 ? (totS / grand * 100) : 50;

  document.getElementById('s-total').textContent = nodes.length;
  document.getElementById('s-flat').textContent  = flat.length;
  document.getElementById('s-long').textContent  = longs.length;
  document.getElementById('s-short').textContent = shorts.length;
  document.getElementById('s-ntl').textContent   = fmt(totNtl);

  document.getElementById('bear-fill').style.width  = bearPct.toFixed(1) + '%';
  document.getElementById('bull-fill').style.width  = (100-bearPct).toFixed(1) + '%';
  document.getElementById('st-bear').textContent = 'Bear ' + bearPct.toFixed(0) + '%';
  document.getElementById('st-bull').textContent = 'Bull ' + (100-bearPct).toFixed(0) + '%';

  // ── axis ──
  // ── Layout constants ──────────────────────────────────────────────────────
  // Top 25% = dormant/flat band.  Bottom 75% = active positions.
  const SPLIT    = H * 0.25;   // Y of the horizontal dividing line
  const PAD      = 28;         // px padding from edges
  const dormMid  = SPLIT * 0.50;  // vertical centre of dormant band
  const actTop   = SPLIT + 16;    // top of active zone (just below divider)
  const actBot   = H - 10;        // bottom of active zone

  // Weighted vertical divider: if 70% long, divider sits at 30% from left
  const bullRatio = grand > 0 ? (totL / grand) : 0.5;
  const bearRatio = 1 - bullRatio;

  // ── Draw axes / dividers ──────────────────────────────────────────────────
  axisLayer.selectAll('*').remove();

  // Horizontal band separator
  axisLayer.append('line')
    .attr('x1', 0).attr('y1', SPLIT)
    .attr('x2', W).attr('y2', SPLIT)
    .attr('stroke','#30363d').attr('stroke-width',1)
    .attr('stroke-dasharray','6 4');

  // "DORMANT / FLAT" label — top-left of band
  axisLayer.append('text')
    .attr('x', 10).attr('y', SPLIT - 6)
    .attr('fill','#484f58').attr('font-size','10px')
    .text('DORMANT / FLAT');

  // Weighted vertical divider — sits at centre (conviction axis is symmetric)
  // We still show the long/short ratio as a background fill hint
  const longZoneW  = (W - PAD * 2) * 0.5 * (grand > 0 ? totL / grand : 0.5);
  const shortZoneW = (W - PAD * 2) * 0.5 * (grand > 0 ? totS / grand : 0.5);

  // Centre divider line
  axisLayer.append('line')
    .attr('x1', centre).attr('y1', SPLIT + 6)
    .attr('x2', centre).attr('y2', actBot)
    .attr('stroke','#30363d').attr('stroke-width',1.5)
    .attr('stroke-dasharray','4 4');

  // Left edge label — balanced shorts live here
  axisLayer.append('text')
    .attr('x', PAD).attr('y', actBot - 6)
    .attr('fill','#f85149').attr('font-size','11px')
    .text('<-- balanced  SHORT  ' + bearPct.toFixed(0) + '%');

  // Right edge label — balanced longs live here
  axisLayer.append('text')
    .attr('x', W - PAD).attr('y', actBot - 6)
    .attr('fill','#3fb950').attr('font-size','11px')
    .attr('text-anchor','end')
    .text((100 - bearPct).toFixed(0) + '%  LONG  balanced -->');

  // Centre bottom label — pure conviction zone
  axisLayer.append('text')
    .attr('x', centre).attr('y', actBot - 6)
    .attr('fill','#484f58').attr('font-size','10px')
    .attr('text-anchor','middle')
    .text('pure conviction');

  // ── Target X/Y per node ───────────────────────────────────────────────────

  const dormNodes   = nodes.filter(function(n){ return  n._b.flat; });
  const activeNodes = nodes.filter(function(n){ return !n._b.flat; });

  // Dormant: random-ish X spread across full width (deterministic via address hash)
  // Use a simple hash of the address so position is stable across re-renders
  function addrHash(addr) {
    var h = 0;
    for (var i = 0; i < addr.length; i++) {
      h = (Math.imul(31, h) + addr.charCodeAt(i)) | 0;
    }
    return Math.abs(h) / 2147483647;  // 0..1
  }
  dormNodes.forEach(function(n) {
    n._tx = PAD + addrHash(n.address) * (W - PAD * 2);
    n._ty = dormMid;
  });

  // Active X axis — CONVICTION layout:
  //   Centre = most convicted (|bias| near 100%)
  //   Edges  = most hedged/balanced (|bias| near 0%)
  //   Positive bias (net long) → right half of centre
  //   Negative bias (net short) → left half of centre
  //
  //   Formula:
  //     conviction = |bias| / 100          (0 = balanced, 1 = pure)
  //     halfW      = (W - PAD*2) / 2
  //     long:   x = centre + (1 - conviction) * halfW   ... pushes balanced longs to right edge
  //     short:  x = centre - (1 - conviction) * halfW   ... pushes balanced shorts to left edge
  //
  //   Wait — we want pure = centre, balanced = edge, so:
  //     long:   x = centre + (1 - conviction) * halfW
  //   No — that puts conviction=1 at centre and conviction=0 at far right.
  //   Correct: pure long (conviction=1) → centre-right, balanced long → far right
  //     long:   x = centre + (1 - conviction) * halfW
  //     short:  x = centre - (1 - conviction) * halfW

  const centre = W / 2;
  const halfW  = (W - PAD * 2) / 2;

  const yLogActive = d3.scaleLog()
    .domain([5e4, 5e8])
    .range([actBot - 10, actTop + 10])
    .clamp(true);

  activeNodes.forEach(function(n) {
    const conviction = Math.abs(n._b.bias) / 100;  // 0..1
    if (n._b.bias >= 0) {
      // Net long: pure long → just right of centre, balanced long → far right
      n._tx = centre + (1 - conviction) * halfW;
    } else {
      // Net short: pure short → just left of centre, balanced short → far left
      n._tx = centre - (1 - conviction) * halfW;
    }
    n._ty = yLogActive(Math.max(n._b.tot, 5e4));
  });

  // ── Bind bubbles ──────────────────────────────────────────────────────────
  const groups = bubbleLayer.selectAll('g.bubble')
    .data(nodes, function(d){ return d.address; });

  const enter = groups.enter().append('g').attr('class','bubble')
    .style('cursor','pointer');

  enter.append('circle').attr('class','ring');
  enter.append('circle').attr('class','main');

  const all = enter.merge(groups);

  all.select('circle.ring')
    .attr('r', function(d){ return d._r + 5; })
    .attr('fill','none')
    .attr('stroke','#FF4136')
    .attr('stroke-width', 2)
    .classed('pulse', function(d){ return d._anomaly; })
    .attr('opacity', function(d){ return d._anomaly ? 0.8 : 0; });

  all.select('circle.main')
    .attr('r', function(d){ return d._r; })
    .attr('fill', function(d){ return TIER_COLOR[d.tier] || '#6E7681'; })
    .attr('stroke','rgba(255,255,255,0.10)')
    .attr('stroke-width', 1)
    .attr('opacity', function(d){
      if (d._b.flat) return asset === 'ALL' ? 0.55 : 0.28;
      if (asset !== 'ALL' && d._b.tot === 0) return 0.10;
      return 0.88;
    });

  groups.exit().remove();

  // Set initial position for new nodes
  nodes.forEach(function(d) {
    if (d.x === undefined) { d.x = d._tx; d.y = d._ty; }
  });

  // Render immediately at target before sim starts
  bubbleLayer.selectAll('g.bubble')
    .attr('transform', function(d){ return 'translate(' + d.x + ',' + d.y + ')'; });

  // Events
  bubbleLayer.selectAll('g.bubble')
    .on('mouseover', function(event, d){ showTip(event, d); })
    .on('mousemove', function(event)   { moveTip(event);    })
    .on('mouseout',  function(event, d){ if (pinned !== d.address) hideTip(); })
    .on('click',     function(event, d){ pinTip(event, d);  });

  // ── Two separate force simulations ───────────────────────────────────────
  // Running them separately prevents dormant from drifting into the active zone.

  if (sim)  sim.stop();
  if (sim2) sim2.stop();

  // Dormant sim: strong X spread, strong Y lock to top band
  sim = d3.forceSimulation(dormNodes)
    .force('x',       d3.forceX(function(d){ return d._tx; }).strength(0.80))
    .force('y',       d3.forceY(dormMid).strength(0.90))
    .force('collide', d3.forceCollide(function(d){ return d._r + 2; }).iterations(4))
    .alphaDecay(0.025)
    .on('tick', function() {
      // Hard clamp: never let dormant bubbles leave the top band
      dormNodes.forEach(function(d) {
        if (d.y > SPLIT - d._r - 2) d.y = SPLIT - d._r - 2;
        if (d.y < d._r + 2)         d.y = d._r + 2;
      });
      bubbleLayer.selectAll('g.bubble')
        .attr('transform', function(d){ return 'translate(' + d.x + ',' + d.y + ')'; });
    });

  // Active sim: bias-driven X, notional-driven Y
  sim2 = d3.forceSimulation(activeNodes)
    .force('x',       d3.forceX(function(d){ return d._tx; }).strength(0.35))
    .force('y',       d3.forceY(function(d){ return d._ty; }).strength(0.28))
    .force('collide', d3.forceCollide(function(d){ return d._r + 3; }).iterations(3))
    .alphaDecay(0.025)
    .on('tick', function() {
      // Hard clamp: never let active bubbles float into dormant band
      activeNodes.forEach(function(d) {
        if (d.y < SPLIT + d._r + 4) d.y = SPLIT + d._r + 4;
        if (d.y > actBot - d._r)    d.y = actBot - d._r;
      });
      bubbleLayer.selectAll('g.bubble')
        .attr('transform', function(d){ return 'translate(' + d.x + ',' + d.y + ')'; });
    });
}

// ── tooltip ───────────────────────────────────────────────────────────────
function tipHTML(d) {
  const em    = TIER_EMOJI[d.tier] || '';
  const name  = d.label || (d.address.slice(0,8) + '...' + d.address.slice(-6));
  const tier  = (d.tier||'').replace('_',' ').toUpperCase();
  const color = TIER_COLOR[d.tier] || '#aaa';
  const b     = d._b;
  const biasColor = b.bias > 5 ? '#3fb950' : b.bias < -5 ? '#f85149' : '#8b949e';
  const biasLbl   = b.flat ? 'FLAT'
    : (b.bias > 0 ? 'LONG ' : 'SHORT ') + Math.abs(b.bias).toFixed(0) + '%';

  const filtered = curAsset === 'ALL'
    ? d.positions
    : d.positions.filter(function(p){ return p.coin === curAsset; });
  const top = filtered.slice().sort(function(a,z){ return z.notional - a.notional; }).slice(0,6);

  let posRows = '';
  if (top.length === 0) {
    posRows = '<div style="color:#484f58;margin-top:4px">No positions in this asset</div>';
  } else {
    top.forEach(function(p) {
      const cls = p.side === 'long' ? 'plong' : 'pshort';
      const dir = p.side === 'long' ? '▲' : '▼';
      const upnl = p.upnl ? '  uPnL: ' + fmt(p.upnl) : '';
      posRows += '<div class="tt-pos">'
        + '<span class="' + cls + '">' + dir + ' ' + p.coin + '</span>'
        + '&nbsp;' + fmt(p.notional)
        + ' @ ' + p.leverage + 'x'
        + '&nbsp; entry $' + (+p.entry).toLocaleString('en-US', {maximumFractionDigits:2})
        + upnl + '</div>';
    });
  }

  return '<span class="tt-x" id="tt-x">&#x2715;</span>'
    + '<div class="tt-name">' + em + ' <span style="color:' + color + '">' + name + '</span>'
    + ' <span class="tt-tier">' + tier + '</span></div>'
    + '<div class="tt-row"><span>Score</span><span>' + (+d.whale_score).toFixed(0) + '</span></div>'
    + '<div class="tt-row"><span>Account Value</span><span>' + fmt(d.account_value) + '</span></div>'
    + '<div class="tt-row"><span>Net Bias</span><span style="color:' + biasColor + '">' + biasLbl + '</span></div>'
    + '<div class="tt-row"><span>Long / Short</span><span>' + fmt(b.L) + ' / ' + fmt(b.S) + '</span></div>'
    + '<hr class="tt-hr">'
    + posRows
    + '<div class="tt-link"><a href="https://app.hyperliquid.xyz/explorer/address/'
    + d.address + '" target="_blank">&#128279; Explorer</a></div>';
}

function showTip(event, d) {
  tooltip.innerHTML = tipHTML(d);
  tooltip.style.opacity = '1';
  tooltip.dataset.addr  = d.address;
  const xEl = document.getElementById('tt-x');
  if (xEl) {
    xEl.addEventListener('click', function() {
      pinned = null;
      tooltip.classList.remove('pinned');
      tooltip.style.opacity = '0';
    });
  }
  moveTip(event);
}
function moveTip(event) {
  if (tooltip.classList.contains('pinned')) return;
  const R = chartEl.getBoundingClientRect();
  const W = chartEl.clientWidth, H = chartEl.clientHeight;
  let x = event.clientX - R.left + 14;
  let y = event.clientY - R.top  - 10;
  if (x + 320 > W) x = event.clientX - R.left - 330;
  if (y + 340 > H) y = H - 350;
  tooltip.style.left = x + 'px';
  tooltip.style.top  = y + 'px';
}
function hideTip() {
  if (tooltip.classList.contains('pinned')) return;
  tooltip.style.opacity = '0';
}
function pinTip(event, d) {
  pinned = d.address;
  tooltip.classList.add('pinned');
  showTip(event, d);
  moveTip(event);
}

// ── filter buttons ────────────────────────────────────────────────────────
BUTTONS.forEach(function(asset) {
  const btn = document.createElement('button');
  btn.className   = 'fbtn' + (asset === 'ALL' ? ' active' : '');
  btn.textContent = asset;
  btn.addEventListener('click', function() {
    document.querySelectorAll('.fbtn').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    pinned = null;
    tooltip.classList.remove('pinned');
    tooltip.style.opacity = '0';
    render(asset);
  });
  document.getElementById('filters').appendChild(btn);
});

// ── kick off ──────────────────────────────────────────────────────────────
render('ALL');
window.addEventListener('resize', function() {
  pinned = null;
  tooltip.style.opacity = '0';
  render(curAsset);
});

