import json, pathlib
from collections import defaultdict
from datetime import datetime, timezone

ROOT          = pathlib.Path(__file__).resolve().parents[1]
SNAPSHOT_FILE = ROOT / "data" / "live_positions_snapshot.json"
OUTPUT_FILE   = ROOT / "reports"  / "liq_heatmap.html"

def _pct(arr, p):
    if not arr: return 0
    i = max(0, min(len(arr) - 1, int(len(arr) * p / 100)))
    return arr[i]

def build_coin(wallets, coin, n_buckets=60):
    longs, shorts, entries = [], [], []
    for w in wallets:
        for p in w.get("positions", []):
            if p.get("coin") != coin: continue
            raw_liq = p.get("liq")
            if not raw_liq: continue
            try:
                liq_px   = float(raw_liq)
                notional = abs(float(p.get("notional", 0)))
                entry    = float(p.get("entry", 0))
                side     = str(p.get("side", "")).lower()
            except (ValueError, TypeError): continue
            if liq_px <= 0 or notional <= 0: continue
            entries.append(entry)
            if side == "long":  longs.append((liq_px, notional))
            elif side == "short": shorts.append((liq_px, notional))
    if not longs and not shorts: return None
    mark   = sorted(entries)[len(entries) // 2] if entries else 0
    raw_px = sorted(lp for lp, _ in longs + shorts)
    p20    = _pct(raw_px, 20)
    p80    = _pct(raw_px, 80)
    spread = max(p80 - p20, mark * 0.05)
    lo = max(p20 - spread * 0.5, mark * 0.10)
    hi = min(p80 + spread * 0.5, mark * 3.00)
    lo = min(lo, mark * 0.90)
    hi = max(hi, mark * 1.10)
    bsize = (hi - lo) / n_buckets
    if bsize <= 0: return None
    lb, sb, clipped = defaultdict(float), defaultdict(float), 0
    for liq_px, notional in longs:
        if liq_px < lo or liq_px > hi: clipped += 1; continue
        lb[min(n_buckets-1, int((liq_px-lo)/bsize))] += notional
    for liq_px, notional in shorts:
        if liq_px < lo or liq_px > hi: clipped += 1; continue
        sb[min(n_buckets-1, int((liq_px-lo)/bsize))] += notional
    labels     = ["{:,.0f}".format(lo + i*bsize) for i in range(n_buckets)]
    long_vals  = [round(lb.get(i, 0)) for i in range(n_buckets)]
    short_vals = [round(sb.get(i, 0)) for i in range(n_buckets)]
    mark_idx   = max(0, min(n_buckets-1, int((mark-lo)/bsize)))
    return {
        "labels": labels, "long_vals": long_vals, "short_vals": short_vals,
        "mark_price": mark, "mark_idx": mark_idx, "bucket_size": bsize,
        "n_longs": len(longs), "n_shorts": len(shorts),
        "total_long": sum(n for _,n in longs), "total_short": sum(n for _,n in shorts),
        "clipped": clipped,
    }

def generate(snapshot_file=SNAPSHOT_FILE, output_file=OUTPUT_FILE):
    raw     = json.loads(pathlib.Path(snapshot_file).read_text(encoding="utf-8"))
    wallets = raw.get("wallets", [])
    ts      = raw.get("fetched_at", "")[:19].replace("T", " ")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    coin_counts = defaultdict(int)
    for w in wallets:
        for p in w.get("positions", []):
            if p.get("liq"): coin_counts[p["coin"]] += 1
    top_coins = [c for c,_ in sorted(coin_counts.items(), key=lambda x:-x[1])]
    if not top_coins: print("[liq_heatmap] No liq data."); return

    coin_data = {}
    for coin in top_coins:
        r = build_coin(wallets, coin)
        if r: coin_data[coin] = r
    if not coin_data: print("[liq_heatmap] No valid data."); return

    default_coin = "BTC" if "BTC" in coin_data else top_coins[0]
    coin_data_js = json.dumps(coin_data)
    coin_list_js = json.dumps(list(coin_data.keys()))

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Whale Liq Heatmap</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:20px}
h1{font-size:22px;font-weight:600;margin-bottom:4px;color:#f0f6fc}
.sub{font-size:13px;color:#8b949e;margin-bottom:20px}
.ctl{display:flex;align-items:center;gap:16px;margin-bottom:20px}
select{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 12px;font-size:14px;cursor:pointer;outline:none}
select:hover{border-color:#58a6ff}
.srow{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 20px;min-width:160px}
.card .lbl{font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.card .val{font-size:20px;font-weight:600}
.cmark .val{color:#58a6ff}.clong .val{color:#3fb950}.cshort .val{color:#f85149}.cratio .val{color:#d29922}
.wrap{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px}
.ctitle{font-size:14px;color:#8b949e;margin-bottom:12px}
.leg{display:flex;gap:20px;margin-top:14px;font-size:12px;color:#8b949e;flex-wrap:wrap}
.li{display:flex;align-items:center;gap:6px}
.ld{width:12px;height:12px;border-radius:2px}
.foot{margin-top:16px;font-size:11px;color:#484f58;text-align:right}
</style>
</head>
<body>
<h1>&#128293; Whale Liquidation Heatmap</h1>
""" + '<div class="sub">Where whale positions get force-closed &mdash; based on ' + str(len(wallets)) + ' tracked wallets &nbsp;&middot;&nbsp; Snapshot: ' + ts + ' UTC</div>' + """
<div class="ctl"><label>Asset:</label><select id="coinSel" onchange="renderCoin(this.value)"></select></div>
<div class="srow" id="statsRow"></div>
<div class="wrap">
  <div class="ctitle" id="chartTitle"></div>
  <canvas id="myChart" height="90"></canvas>
  <div class="leg">
    <div class="li"><div class="ld" style="background:#238636"></div>Long liq (price drops here &rarr; longs wiped)</div>
    <div class="li"><div class="ld" style="background:#da3633"></div>Short liq (price rises here &rarr; shorts wiped)</div>
    <div class="li"><div class="ld" style="background:#58a6ff;border-radius:50%"></div>Approx. mark price</div>
  </div>
</div>
""" + '<div class="foot">HyperWhale &middot; ' + now_utc + ' UTC</div>' + """
<script>
var COIN_DATA = """ + coin_data_js + """;
var COIN_LIST = """ + coin_list_js + """;
var DEFAULT_COIN = """ + json.dumps(default_coin) + """;
var chart = null;

function fmtUSD(v){
  if(v>=1e9) return '$'+(v/1e9).toFixed(1)+'B';
  if(v>=1e6) return '$'+(v/1e6).toFixed(1)+'M';
  if(v>=1e3) return '$'+(v/1e3).toFixed(0)+'K';
  return '$'+v.toFixed(0);
}
function fmtPx(v){
  if(v>=1000) return '$'+v.toLocaleString('en-US',{maximumFractionDigits:0});
  if(v>=1)    return '$'+v.toLocaleString('en-US',{maximumFractionDigits:2});
  return '$'+v.toFixed(4);
}

function renderCoin(coin){
  var d = COIN_DATA[coin];
  if(!d) return;
  var tot   = d.total_long + d.total_short;
  var ratio = tot > 0 ? ((d.total_long/tot)*100).toFixed(0) : 50;

  document.getElementById('statsRow').innerHTML =
    '<div class="card cmark"><div class="lbl">Est. Mark Price</div><div class="val">'+fmtPx(d.mark_price)+'</div></div>'+
    '<div class="card clong"><div class="lbl">Long Liq ('+d.n_longs+' pos)</div><div class="val">'+fmtUSD(d.total_long)+'</div></div>'+
    '<div class="card cshort"><div class="lbl">Short Liq ('+d.n_shorts+' pos)</div><div class="val">'+fmtUSD(d.total_short)+'</div></div>'+
    '<div class="card cratio"><div class="lbl">Long / Short split</div><div class="val">'+ratio+'% / '+(100-ratio)+'%</div></div>';

  document.getElementById('chartTitle').textContent =
    coin + ' \u2014 Notional at liq price  (bucket \u2248 $' +
    d.bucket_size.toLocaleString('en-US',{maximumFractionDigits:0}) + ' wide)';

  if(chart){chart.destroy();chart=null;}

  var ctx = document.getElementById('myChart').getContext('2d');
  chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: d.labels,
      datasets: [
        {
          label:'Long liquidations',
          data: d.long_vals,
          backgroundColor:'rgba(35,134,54,0.85)',
          borderColor:'rgba(63,185,80,1)',
          borderWidth:1, borderRadius:2
        },
        {
          label:'Short liquidations',
          data: d.short_vals,
          backgroundColor:'rgba(218,54,51,0.85)',
          borderColor:'rgba(248,81,73,1)',
          borderWidth:1, borderRadius:2
        }
      ]
    },
    options:{
      responsive:true,
      animation:{duration:250},
      interaction:{mode:'index',intersect:false},
      plugins:{
        legend:{display:false},
        tooltip:{
          backgroundColor:'#1c2128',borderColor:'#30363d',borderWidth:1,
          titleColor:'#8b949e',bodyColor:'#e6edf3',
          callbacks:{
            title:function(items){return 'Price ~ $'+Number(items[0].label).toLocaleString();},
            label:function(item){return '  '+item.dataset.label+': '+fmtUSD(item.raw);}
          }
        }
      },
      scales:{
        x:{
          ticks:{
            color:'#484f58',maxRotation:45,autoSkip:true,maxTicksLimit:14,
            callback:function(val,idx){
              var n=Number(this.getLabelForValue(val));
              if(n>=1e6) return '$'+(n/1e6).toFixed(1)+'M';
              if(n>=1e3) return '$'+(n/1e3).toFixed(0)+'K';
              return '$'+n.toFixed(0);
            }
          },
          grid:{color:'#21262d'}
        },
        y:{
          ticks:{color:'#484f58',callback:function(v){return fmtUSD(v);}},
          grid:{color:'#21262d'}
        }
      }
    },
    plugins:[{
      id:'markLine',
      afterDraw:function(ch){
        var xs=ch.scales.x, ys=ch.scales.y;
        if(!xs||!ys) return;
        var x=xs.getPixelForValue(d.mark_idx);
        if(isNaN(x)) return;
        var c2=ch.ctx;
        c2.save();
        c2.beginPath();
        c2.moveTo(x,ys.top);
        c2.lineTo(x,ys.bottom);
        c2.strokeStyle='#58a6ff';
        c2.lineWidth=2;
        c2.setLineDash([5,4]);
        c2.stroke();
        c2.setLineDash([]);
        c2.fillStyle='#58a6ff';
        c2.font='bold 11px sans-serif';
        c2.textAlign='center';
        c2.fillText(fmtPx(d.mark_price),x,ys.top-6);
        c2.restore();
      }
    }]
  });
}

var sel=document.getElementById('coinSel');
COIN_LIST.forEach(function(c){
  var o=document.createElement('option');
  o.value=c;
  o.textContent=c+' ('+(COIN_DATA[c].n_longs+COIN_DATA[c].n_shorts)+' pos)';
  if(c===DEFAULT_COIN) o.selected=true;
  sel.appendChild(o);
});
renderCoin(DEFAULT_COIN);
</script>
</body>
</html>"""

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")
    print("[liq_heatmap] Written:", str(output_file), "({:,} chars)".format(len(html)))

if __name__ == "__main__":
    generate()