# -*- coding: utf-8 -*-
r"""주식 분석 웹앱 (HTML/인터랙티브) — 브라우저에서 종목·이격일수·기간을 바꿔가며 분석.
   이격도 차트(Plotly·확대/호버) + 5년 재무 + 밸류 + 뉴스 + 스코어카드.
   실행:  python 웹앱.py     (또는 실행_웹앱.bat 더블클릭) → 브라우저 자동 열림
   데이터: FinanceDataReader(가격) + yfinance(재무·밸류·뉴스). 실행 시마다 최신.
"""
import warnings, re, datetime as dt, threading, webbrowser, html, socket, io
warnings.filterwarnings("ignore")
# --- 필요 라이브러리 자동 설치(다른 컴퓨터 대비) ---
import importlib, subprocess, sys
for _mod,_pip in [("numpy","numpy"),("flask","flask"),("plotly","plotly"),
                  ("FinanceDataReader","finance-datareader"),("yfinance","yfinance"),("qrcode","qrcode")]:
    try: importlib.import_module(_mod)
    except Exception:
        print(f"설치 중: {_pip} ..."); subprocess.check_call([sys.executable,"-m","pip","install","--quiet",_pip])
# 콘솔(특히 exe)의 cp949 인코딩에서 이모지·특수문자 출력 시 크래시 방지
try:
    sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    sys.stderr.reconfigure(encoding="utf-8",errors="replace")
except Exception: pass
import numpy as np
import FinanceDataReader as fdr
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from flask import Flask, request, Response

PORT=8765
app=Flask(__name__)
PHONE_URL=f"http://127.0.0.1:{PORT}"   # 실행 시 LAN 주소로 갱신

def lan_ip():
    """같은 Wi-Fi의 폰이 접속할 PC의 사설 IP 추정."""
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(("8.8.8.8",80))
        ip=s.getsockname()[0]; s.close(); return ip
    except Exception: return "127.0.0.1"

def qr_svg(url):
    """의존성 적은 SVG QR(Pillow 불필요). 실패 시 빈 문자열."""
    try:
        import qrcode, qrcode.image.svg
        img=qrcode.make(url,image_factory=qrcode.image.svg.SvgPathImage,box_size=10,border=2)
        b=io.BytesIO(); img.save(b); return b.getvalue().decode("utf-8")
    except Exception: return ""

# ---------- 종목 추천/검색(부분 이름) ----------
RECO=[("삼성전자","005930"),("SK하이닉스","000660"),("한미반도체","042700"),
      ("삼성전기","009150"),("한화엔진","082740"),("엔비디아","NVDA"),
      ("마이크론","MU"),("브로드컴","AVGO"),("TSMC","TSM"),("마벨","MRVL")]
CURATED=dict(RECO+[
  ("한화에어로스페이스","012450"),("LG에너지솔루션","373220"),("현대차","005380"),
  ("기아","000270"),("네이버","035420"),("카카오","035720"),("셀트리온","068270"),
  ("POSCO홀딩스","005490"),("LG화학","051910"),("삼성SDI","006400"),
  ("현대모비스","012330"),("KB금융","105560"),("두산에너빌리티","034020"),
  ("HD현대중공업","329180"),("한화오션","042660"),
  ("애플","AAPL"),("마이크로소프트","MSFT"),("구글","GOOGL"),("아마존","AMZN"),
  ("테슬라","TSLA"),("메타","META"),("AMD","AMD"),("오라클","ORCL"),
  ("버티브","VRT"),("이튼","ETN"),("코히런트","COHR"),("암코","AMKR")])
_KRX=None
def krx():
    global _KRX
    if _KRX is None:
        try:
            df=fdr.StockListing("KRX")
            _KRX={str(getattr(r,"Code")).zfill(6):str(getattr(r,"Name")) for r in df.itertuples()}
        except Exception: _KRX={}
    return _KRX
def kr_name(code):
    return krx().get(code) or code
def disp_name(code, info):
    for nm,c in CURATED.items():
        if c==code: return nm
    if re.fullmatch(r"\d{6}",code):
        n=kr_name(code)
        if n and n!=code: return n
    return (info or {}).get("shortName") or (info or {}).get("longName") or code
def resolve_code(q):
    """코드/티커/이름 일부 → 종목코드. '삼성','하이' 같은 부분 입력도 검색."""
    q=(q or "").strip()
    if not q: return ""
    if re.fullmatch(r"\d{6}",q): return q
    if re.fullmatch(r"[A-Za-z.\-]{1,6}",q): return q.upper()
    for nm,c in CURATED.items():           # 큐레이션 정확
        if nm==q: return c
    for nm,c in CURATED.items():           # 큐레이션 시작
        if nm.startswith(q): return c
    for nm,c in CURATED.items():           # 큐레이션 포함
        if q in nm: return c
    km=krx()                                # 전체 KRX 부분검색
    for c,nm in km.items():
        if nm==q: return c
    cands=[(c,nm) for c,nm in km.items() if nm.startswith(q)] or [(c,nm) for c,nm in km.items() if q in nm]
    if cands: cands.sort(key=lambda x:len(x[1])); return cands[0][0]
    return q.upper()
def korean_news(query, n=6):
    """구글뉴스 한국어 RSS로 한글 헤드라인 추출."""
    try:
        import urllib.parse, urllib.request, xml.etree.ElementTree as ET
        url="https://news.google.com/rss/search?q="+urllib.parse.quote((query or "")+" 주식")+"&hl=ko&gl=KR&ceid=KR:ko"
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        root=ET.fromstring(urllib.request.urlopen(req,timeout=10).read())
        out=[]
        for it in list(root.iter("item"))[:n]:
            t=it.findtext("title"); l=it.findtext("link")
            if t: out.append((t,l))
        return out
    except Exception: return []

# ---------- 유틸 ----------
def is_kr(c): return bool(re.fullmatch(r"\d{6}",c))
def esc(s): return html.escape(str(s)) if s is not None else ""
def fmt(v,kr):
    if v is None or (isinstance(v,float) and np.isnan(v)): return "-"
    v=float(v); a=abs(v)
    if kr:
        if a>=1e12: return f"{v/1e12:.1f}조"
        if a>=1e8:  return f"{v/1e8:.0f}억"
        return f"{v:,.0f}"
    if a>=1e9: return f"${v/1e9:.1f}B"
    if a>=1e6: return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"
def num(x,suf=""):
    if x is None: return "-"
    try:
        x=float(x); return f"{x:,.0f}{suf}" if abs(x)>=100 else f"{x:.2f}{suf}"
    except: return "-"

def fetch_meta(code):
    info={}; tkr=None
    for c in ([code+".KS",code+".KQ"] if is_kr(code) else [code]):
        try:
            t=yf.Ticker(c); inf=t.info
            if inf and (inf.get("shortName") or inf.get("marketCap")): info=inf; tkr=t; break
        except Exception: continue
    if tkr is None: tkr=yf.Ticker(code if not is_kr(code) else code+".KS")
    inc=None; qinc=None; news=[]
    try: inc=tkr.income_stmt
    except Exception: pass
    try: qinc=tkr.quarterly_income_stmt
    except Exception:
        try: qinc=tkr.quarterly_financials
        except Exception: pass
    try: news=tkr.news or []
    except Exception: pass
    return info,inc,qinc,news

def get_prices(code,ma,months):
    today=dt.date.today(); start=today-dt.timedelta(days=int(months*30.5))
    fs=start-dt.timedelta(days=int(ma*3)+10)
    df=fdr.DataReader(code,fs.isoformat(),today.isoformat()).dropna(subset=["Close"])
    close=df["Close"].astype(float); m=close.rolling(ma).mean(); disp=close/m*100
    mask=df.index.date>=start
    d=df.index[mask]; p=close[mask].values; mm=m[mask].values; dp=disp[mask].values
    ok=~np.isnan(mm)
    return d[ok],p[ok],mm[ok],dp[ok]

def fig_disparity(code,ma,d,p,mm,dp,name):
    fig=make_subplots(specs=[[{"secondary_y":True}]])
    unit="원" if is_kr(code) else "$"
    # 이격도='막대'(100 기준 anchored): 위=과열(주황)·아래=침체(청록). 주가·이평선 '뒤'(먼저 add → 뒤로).
    dev=[float(v)-100 for v in dp]
    bcol=["#FB8C00" if v>=0 else "#26A69A" for v in dev]
    fig.add_trace(go.Bar(x=d,y=dev,base=100,name="이격도(막대)",marker_color=bcol,opacity=0.5,
                  marker_line_width=0,customdata=dp,
                  hovertemplate="%{x|%Y-%m-%d}<br>이격도 %{customdata:.1f}%<extra></extra>"),secondary_y=True)
    fig.add_trace(go.Scatter(x=d,y=mm,name=f"{ma}일선",line=dict(color="#1565C0",width=2.4),
                  hovertemplate="%{x|%Y-%m-%d}<br>"+f"{ma}일선 %{{y:,.0f}}{unit}<extra></extra>"),secondary_y=False)
    fig.add_trace(go.Scatter(x=d,y=p,name=f"주가({unit})",line=dict(color="#111111",width=2.4),
                  hovertemplate="%{x|%Y-%m-%d}<br>"+f"주가 %{{y:,.0f}}{unit}<extra></extra>"),secondary_y=False)
    if p.max()/max(p.min(),1)>3: fig.update_yaxes(type="log",secondary_y=False)
    lo2=min(float(dp.min()),100.0); hi2=max(float(dp.max()),100.0); pad=max(2.0,(hi2-lo2)*0.12)
    fig.update_yaxes(title_text=f"주가({unit})",secondary_y=False,showgrid=True,gridcolor="#E6EBF1",
                     title_font=dict(size=12),tickfont=dict(size=11))
    fig.update_yaxes(title_text="이격도%",secondary_y=True,showgrid=False,zeroline=False,
                     title_font=dict(size=12,color="#E67E00"),tickfont=dict(size=11,color="#E67E00"),
                     range=[lo2-pad,hi2+pad])
    fig.add_hline(y=100,line=dict(color="#8A97A6",width=1.4,dash="dash"),secondary_y=True,
                  annotation_text="100=이평선",annotation_position="top left",
                  annotation_font=dict(size=10,color="#5B6B7C"))
    fig.add_annotation(x=d[-1],y=float(dp[-1]),yref="y2",text=f"현재 {float(dp[-1]):.1f}%",showarrow=True,
                  arrowhead=2,arrowcolor="#E67E00",ax=-34,ay=-22,font=dict(size=11,color="#E67E00"),
                  bgcolor="rgba(255,255,255,0.82)")
    fig.update_xaxes(tickfont=dict(size=11))
    fig.update_layout(title=dict(text=f"{name} · {ma}일 이격도 (막대 100기준: 위=과열·아래=침체)",font=dict(size=14)),
                      template="plotly_white",height=440,margin=dict(l=6,r=6,t=60,b=6),
                      legend=dict(orientation="h",y=1.13,x=0.5,xanchor="center",font=dict(size=12)),
                      hovermode="x unified",bargap=0.04,
                      font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif",size=12))
    return fig.to_html(include_plotlyjs="cdn",full_html=False,
                       config={"displayModeBar":False,"displaylogo":False,"responsive":True})

def fig_fin(years,rev,op,ni,kr,title="5년 재무 추이"):
    div=1e12 if kr else 1e9; u="조원" if kr else "$B"
    def vals(s): return [ (round(v/div,1) if v else 0) for v in s]
    R,O,N=vals(rev),vals(op),vals(ni)
    mx=max(R+O+N+[1])
    fig=go.Figure()
    fig.add_bar(x=years,y=R,name="매출",marker_color="#1565C0")
    fig.add_bar(x=years,y=O,name="영업이익",marker_color="#2E7D32")
    fig.add_bar(x=years,y=N,name="순이익",marker_color="#EF6C00")
    fig.update_layout(barmode="group",template="plotly_white",height=300,
                      title=dict(text=f"{title} (단위: {u})",font=dict(size=14)),
                      margin=dict(l=8,r=8,t=64,b=8),bargap=0.3,bargroupgap=0.06,
                      legend=dict(orientation="h",y=1.18,x=0.5,xanchor="center",font=dict(size=13)),
                      font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif",size=12))
    fig.update_yaxes(range=[0,mx*1.15],tickfont=dict(size=11),showgrid=True,gridcolor="#E6EBF1")
    fig.update_xaxes(tickfont=dict(size=13))
    return fig.to_html(include_plotlyjs=False,full_html=False,
                       config={"displayModeBar":False,"responsive":True})

def extract_stmt(stmt, label):
    """손익계산서(연간/분기)에서 (라벨, 매출, 영업이익, 순이익) 추출. 오래된→최신 순."""
    ys=[];rev=[];op=[];ni=[]
    if stmt is not None and not stmt.empty:
        def pick(keys):
            for k in keys:
                if k in stmt.index: return stmt.loc[k]
            return None
        sr=pick(["Total Revenue","Operating Revenue"])
        so=pick(["Operating Income","Total Operating Income As Reported"])
        sn=pick(["Net Income","Net Income Common Stockholders"])
        def g(s,c): return float(s[c]) if (s is not None and c in s and not np.isnan(s[c])) else None
        for c in list(stmt.columns)[::-1]:
            ys.append(label(c)); rev.append(g(sr,c)); op.append(g(so,c)); ni.append(g(sn,c))
    return ys,rev,op,ni

def tech(code):
    """RSI(14)·20/60일선 교차·52주 위치 계산."""
    try:
        end=dt.date.today(); start=end-dt.timedelta(days=430)
        c=fdr.DataReader(code,start.isoformat(),end.isoformat())["Close"].astype(float).dropna()
        if len(c)<30: return None
        d=c.diff(); up=d.clip(lower=0).rolling(14).mean(); dn=(-d.clip(upper=0)).rolling(14).mean()
        rsi=float((100-100/(1+up/dn.replace(0,np.nan))).iloc[-1])
        ms=float(c.rolling(20).mean().iloc[-1]); ml=float(c.rolling(60).mean().iloc[-1])
        w=c.tail(252); hi=float(w.max()); lo=float(w.min()); cur=float(c.iloc[-1])
        pos=(cur-lo)/(hi-lo)*100 if hi>lo else 50.0
        return {"rsi":rsi,"cross":ms>=ml,"pos":pos,"hi":hi,"lo":lo,"cur":cur}
    except Exception: return None

_MKT={"t":0.0,"d":[]}
MKT_SYMS=[("KS11","코스피"),("KQ11","코스닥"),("USD/KRW","원/달러"),("US500","S&P500"),("IXIC","나스닥")]
def market():
    import time
    if _MKT["d"] and time.time()-_MKT["t"]<600: return _MKT["d"]
    out=[]; start=(dt.date.today()-dt.timedelta(days=12)).isoformat()
    for sym,nm in MKT_SYMS:
        try:
            df=fdr.DataReader(sym,start).dropna(subset=["Close"])
            last=float(df["Close"].iloc[-1]); prev=float(df["Close"].iloc[-2]) if len(df)>=2 else last
            out.append((nm,last,(last/prev-1)*100 if prev else 0.0))
        except Exception: pass
    if out: _MKT["t"]=time.time(); _MKT["d"]=out
    return out

CSS="""
<meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1, viewport-fit=cover'>
<meta name='apple-mobile-web-app-capable' content='yes'>
<meta name='mobile-web-app-capable' content='yes'>
<meta name='apple-mobile-web-app-status-bar-style' content='black-translucent'>
<meta name='apple-mobile-web-app-title' content='주식분석'><meta name='theme-color' content='#16243F'>
<link rel='manifest' href='/manifest.webmanifest'>
<style>
*{box-sizing:border-box} html{overflow-x:hidden} body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;margin:0;background:#F4F7FB;color:#1C2530;-webkit-text-size-adjust:100%;overflow-x:hidden;max-width:100vw}
#js-plotly-tester{position:absolute!important;left:-99999px!important;top:0!important;visibility:hidden!important}
.js-plotly-plot,.plot-container,.svg-container{max-width:100%!important}
.wrap{max-width:920px;margin:0 auto;padding:0 14px 40px}
.top{background:#16243F;color:#fff;padding:18px 16px;border-radius:0 0 14px 14px}
.top h1{margin:0;font-size:20px} .top p{margin:4px 0 0;color:#C7D6EC;font-size:13px}
form.bar{background:#fff;border:1px solid #C9D6E5;border-radius:12px;padding:14px;margin:16px 0;display:flex;flex-wrap:wrap;gap:10px;align-items:end}
form.bar label{font-size:12px;color:#5B6B7C;display:block;margin-bottom:3px}
input,select{padding:9px 10px;border:1px solid #C9D6E5;border-radius:8px;font-size:15px}
input[type=text]{width:150px} button{background:#2563B0;color:#fff;border:0;border-radius:8px;padding:10px 18px;font-size:15px;cursor:pointer}
button.alt{background:#33507A}
.card{background:#fff;border:1px solid #E2E8F0;border-radius:12px;padding:14px 16px;margin:14px 0}
.sec{background:#16243F;color:#fff;padding:9px 12px;border-radius:8px;font-weight:bold;margin:18px 0 8px;font-size:15px}
table{width:100%;border-collapse:collapse;font-size:13.5px} th,td{border:1px solid #E2E8F0;padding:7px 8px;text-align:left}
th{background:#2563B0;color:#fff} tr:nth-child(even) td{background:#F4F7FB}
.kpi td:first-child{font-weight:bold;width:42%;color:#16243F;background:#EEF3F9}
.hl td{background:#FFF7E6 !important;font-weight:bold}
.note{background:#FBF3E2;border-left:3px solid #B9770E;padding:9px 11px;border-radius:6px;font-size:12.5px;margin:8px 0}
.warn{background:#FDEEEC;border-left:3px solid #C0392B}
.news a{color:#2563B0;text-decoration:none} .news li{margin:5px 0;font-size:13.5px}
.star{color:#C9A227;letter-spacing:1px} .muted{color:#5B6B7C;font-size:11.5px}
.foot{color:#8090A0;font-size:11px;text-align:center;margin:24px 0 0}
.grid{display:grid;grid-template-columns:1fr;gap:0}
.ex{display:inline-block;background:#EEF3F9;border-radius:6px;padding:7px 11px;margin:3px;font-size:13px;color:#16243F;text-decoration:none}
.qr{max-width:190px;margin:8px 0} .qr svg{width:100%;height:auto;background:#fff;border-radius:8px}
.purl{font-size:17px;font-weight:bold;color:#16243F;word-break:break-all;margin:6px 0}
.js-plotly-plot,.plotly,.plot-container,.svg-container{-webkit-touch-callout:none !important;-webkit-user-select:none;user-select:none}
@media(max-width:560px){
  .wrap{padding:0 10px 40px} .top h1{font-size:18px}
  form.bar{flex-direction:column;align-items:stretch;gap:8px}
  form.bar>div{width:100%} input[type=text]{width:100%} select{width:100%} button{width:100%;padding:13px}
  table{font-size:12px} th,td{padding:6px 5px} .sec{font-size:14px}
  .ex{display:block;text-align:center}
}
</style>
<script>
function _favs(){try{return JSON.parse(localStorage.getItem('favs')||'[]')}catch(e){return[]}}
function addFav(code,name){var f=_favs();if(!f.some(function(x){return x.code===code})){f.push({code:code,name:name});localStorage.setItem('favs',JSON.stringify(f));}renderFavs();alert(name+' ⭐ 즐겨찾기 추가됨');}
function delFav(code){localStorage.setItem('favs',JSON.stringify(_favs().filter(function(x){return x.code!==code})));renderFavs();}
function renderFavs(){var el=document.getElementById('favbox');if(!el)return;var f=_favs();if(!f.length){el.innerHTML="<span class='muted'>아직 없음 — 분석 화면에서 ⭐ 추가</span>";return;}var h='';for(var i=0;i<f.length;i++){var x=f[i];h+="<span class='ex' style='display:inline-flex;align-items:center;gap:5px'><a href='/analyze?code="+encodeURIComponent(x.code)+"'>"+x.name+"</a> <a href='#' data-del='"+x.code+"' style='color:#C0392B;text-decoration:none'>x</a></span>";}el.innerHTML=h;}
function loadMarket(){var el=document.getElementById('mktbox');if(!el)return;fetch('/market').then(function(r){return r.text()}).then(function(h){el.innerHTML=h}).catch(function(){el.innerHTML="<span class='muted'>시장지표 불러오기 실패</span>"});}
document.addEventListener('click',function(e){var t=e.target;if(t&&t.getAttribute&&t.getAttribute('data-del')){e.preventDefault();delFav(t.getAttribute('data-del'));}});
document.addEventListener('DOMContentLoaded',function(){try{renderFavs()}catch(e){}try{loadMarket()}catch(e){}});
</script>"""

def form_html(code="",ma="30",months="18"):
    def opt(v,cur): return f"<option value='{v}'{' selected' if str(v)==str(cur) else ''}>{v}</option>"
    dl="".join(f"<option value='{esc(nm)}'>{esc(c)}</option>" for nm,c in CURATED.items())
    return f"""<form class='bar' action='/analyze' method='get'>
      <div style='flex:1 1 180px'><label>종목 이름 일부 또는 코드 (예: 삼성 · 하이닉스 · 005930 · NVDA)</label>
        <input type='text' name='code' value='{esc(code)}' placeholder='삼성  /  하이닉스  /  005930  /  NVDA' list='codes' autocomplete='off' autofocus>
        <datalist id='codes'>{dl}</datalist></div>
      <div><label>이격 기준일수</label><select name='ma'>{''.join(opt(v,ma) for v in [10,20,30,60,120])}</select></div>
      <div><label>기간(개월)</label><select name='months'>{''.join(opt(v,months) for v in [3,6,12,18,24,36])}</select></div>
      <button type='submit'>분석</button>
    </form>"""

@app.route("/")
def home():
    ex="".join(f"<a class='ex' href='/analyze?code={c}'>{n}</a>" for n,c in RECO)
    phone=""
    if not PHONE_URL.startswith("http://127."):
        qr=qr_svg(PHONE_URL)
        phone=f"""<div class='card'><b>📱 폰에서 열기</b>
          <div class='muted'>같은 Wi-Fi에 연결된 폰 카메라로 QR을 비추거나, 폰 브라우저 주소창에 입력:</div>
          <div class='purl'>{esc(PHONE_URL)}</div>{('<div class=qr>'+qr+'</div>') if qr else ''}
          <div class='muted'>열린 뒤 [공유]→[홈 화면에 추가] 하면 앱처럼 쓸 수 있어요.</div></div>"""
    return f"""<!doctype html><html lang='ko'>{CSS}<body><div class='top'><div class='wrap' style='padding:0'>
      <h1>📈 주식 분석 (HTML)</h1><p>종목·이격일수·기간을 바꿔가며 인터랙티브 차트로 분석 · 실행 시 최신 데이터</p></div></div>
      <div class='wrap'>{form_html()}
      <div class='card'><b>🌐 시장지표 (실시간)</b><div id='mktbox' style='margin-top:6px'><span class='muted'>불러오는 중…</span></div></div>
      <div class='card'><b>🔥 추천 종목 (탭하면 바로 분석)</b><br><div style='margin-top:6px'>{ex}</div></div>
      <div class='card'><b>⭐ 즐겨찾기</b><div id='favbox' style='margin-top:6px'></div></div>
      <div class='card'><b>🔁 종목 비교 (2~3개)</b>{compare_form()}</div>
      {phone}
      <div class='note'>이름 <b>일부만</b> 입력해도 검색됩니다(예: "삼성"·"하이닉스"). 한국=6자리코드·미국=티커도 가능. 데이터: FinanceDataReader·yfinance(한글뉴스: 구글뉴스). 투자 권유 아님.</div>
      <div class='foot'>주식 분석 웹앱</div></div></body></html>"""

@app.route("/manifest.webmanifest")
def manifest():
    import json as _j
    m={"name":"주식 분석","short_name":"주식분석","start_url":"/","scope":"/","display":"standalone",
       "background_color":"#F4F7FB","theme_color":"#16243F","lang":"ko","icons":[]}
    return Response(_j.dumps(m,ensure_ascii=False),mimetype="application/manifest+json")

@app.route("/market")
def market_frag():
    m=market()
    if not m: return "<span class='muted'>시장지표 불러오기 실패(잠시 후 새로고침)</span>"
    def cell(nm,v,ch):
        col="#C0392B" if ch<0 else "#1E7E45"; ar="▲" if ch>0 else ("▼" if ch<0 else "·")
        return f"<div style='flex:1;min-width:84px;text-align:center;padding:6px 4px'><div class='muted'>{esc(nm)}</div><div style='font-weight:bold;font-size:14px'>{v:,.0f}</div><div style='color:{col};font-size:12px'>{ar}{abs(ch):.2f}%</div></div>"
    return "<div style='display:flex;flex-wrap:wrap'>"+"".join(cell(*x) for x in m)+"</div>"

def compare_form(codes=""):
    return (f"<form class='bar' action='/compare' method='get'><div style='flex:1 1 240px'>"
            f"<label>비교 종목 2~3개 (쉼표/공백 구분, 이름 일부 OK)</label>"
            f"<input type='text' name='codes' value='{esc(codes)}' placeholder='삼성, 하이닉스, 엔비디아' list='codes'></div>"
            f"<button type='submit'>비교</button></form>")

@app.route("/compare")
def compare():
    raw=(request.args.get("codes") or "").strip()
    codes=[]
    for t in re.split(r"[,\s]+",raw):
        if t.strip():
            c=resolve_code(t.strip())
            if c and c not in codes: codes.append(c)
    codes=codes[:3]; form=compare_form(raw)
    dl="".join(f"<option value='{esc(nm)}'>{esc(c)}</option>" for nm,c in CURATED.items())
    form=form+f"<datalist id='codes'>{dl}</datalist>"
    head_html=f"<!doctype html><html lang='ko'>{CSS}<body><div class='top'><div class='wrap' style='padding:0'><h1>🔁 종목 비교</h1></div></div><div class='wrap'>{form}"
    if not codes:
        return head_html+"<div class='note'>비교할 종목을 2~3개 입력하세요(쉼표/공백 구분). 예: 삼성, 하이닉스, 엔비디아</div></div></body></html>"
    cols=[]
    for code in codes:
        kr=is_kr(code); cur=disp=None
        try:
            d,p,mm,dp=get_prices(code,30,6); cur=float(p[-1]); disp=float(dp[-1])
        except Exception: pass
        info,_,_,_=fetch_meta(code); nm=disp_name(code,info)
        px=info.get("currentPrice") or info.get("regularMarketPrice") or cur
        hi=info.get("fiftyTwoWeekHigh"); lo=info.get("fiftyTwoWeekLow")
        pos=((px-lo)/(hi-lo)*100) if (px and hi and lo and hi>lo) else None
        cols.append({"code":code,"nm":nm,"kr":kr,"px":px,"disp":disp,"per":info.get("trailingPE"),
                     "fper":info.get("forwardPE"),"pbr":info.get("priceToBook"),"mc":info.get("marketCap"),
                     "dy":info.get("dividendYield"),"pos":pos})
    def row(label,fn): return "<tr><td>"+label+"</td>"+"".join("<td>"+fn(c)+"</td>" for c in cols)+"</tr>"
    head="<tr><th>지표</th>"+"".join(f"<th>{esc(c['nm'])}<br><span style='font-weight:normal;font-size:11px'>{esc(c['code'])}</span></th>" for c in cols)+"</tr>"
    body=(row("현재가",lambda c:(f"{c['px']:,.0f}"+('원' if c['kr'] else '$')) if c['px'] else '-')
        +row("30일 이격도",lambda c:(f"{c['disp']:.1f}%") if c['disp'] is not None else '-')
        +row("PER 후/선",lambda c:f"{num(c['per'])}/{num(c['fper'])}")
        +row("PBR",lambda c:num(c['pbr']))
        +row("시가총액",lambda c:fmt(c['mc'],c['kr']))
        +row("배당%",lambda c:(f"{c['dy']*100:.2f}%") if c['dy'] else '-')
        +row("52주 위치",lambda c:(f"{c['pos']:.0f}%") if c['pos'] is not None else '-'))
    links="".join(f"<a class='ex' href='/analyze?code={c['code']}'>{esc(c['nm'])} 상세</a>" for c in cols)
    return head_html+f"<div class='card'><table>{head}{body}</table></div><div class='card'>{links}</div><div class='note warn'>실시간 자동 산출 · 한국주는 일부 '-' 가능 · 투자 권유 아님.</div></div></body></html>"

@app.route("/analyze")
def analyze():
    raw=(request.args.get("code") or "").strip()
    code=resolve_code(raw)
    ma=int(request.args.get("ma") or 30); months=int(request.args.get("months") or 18)
    if not code: return home()
    kr=is_kr(code)
    try:
        d,p,mm,dp=get_prices(code,ma,months)
        if len(d)<2: raise ValueError("데이터 부족")
    except Exception as e:
        return f"<!doctype html><html>{CSS}<body><div class='top'><div class='wrap' style='padding:0'><h1>📈 주식 분석</h1></div></div><div class='wrap'>{form_html(code,ma,months)}<div class='note warn'>‼ '{esc(code)}' 데이터를 가져오지 못했습니다. 종목코드를 확인하세요(한국=6자리, 미국=티커). ({esc(e)})</div></div></body></html>"
    info,inc,qinc,news=fetch_meta(code)
    name=disp_name(code,info)
    cur=int(p[-1]); curdisp=float(dp[-1]); unit="원" if kr else "$"
    # 재무(연간 + 분기)
    years,rev,op,ni = extract_stmt(inc, lambda c: str(c.year))
    qy,qr,qo,qn = extract_stmt(qinc, lambda c: f"{c.year}.{(c.month-1)//3+1}Q")
    qy,qr,qo,qn = qy[-6:],qr[-6:],qo[-6:],qn[-6:]   # 최근 6개 분기
    # KPI
    mc=info.get("marketCap");per=info.get("trailingPE");fper=info.get("forwardPE");pbr=info.get("priceToBook")
    hi=info.get("fiftyTwoWeekHigh");lo=info.get("fiftyTwoWeekLow");tgt=info.get("targetMeanPrice");dy=info.get("dividendYield")
    px=info.get("currentPrice") or info.get("regularMarketPrice") or cur
    kpi=f"""<table class='kpi'>
      <tr><td>현재가</td><td>{px:,.0f}{unit}</td></tr>
      <tr><td>시가총액</td><td>{fmt(mc,kr)}</td></tr>
      <tr><td>PER (후행/선행)</td><td>{num(per)} / {num(fper)}</td></tr>
      <tr><td>PBR</td><td>{num(pbr)}</td></tr>
      <tr><td>52주 고/저</td><td>{num(hi)} / {num(lo)}</td></tr>
      <tr><td>평균 목표주가</td><td>{(f'{tgt:,.0f}'+unit) if tgt else '- (미제공)'}</td></tr>
      <tr><td>배당수익률</td><td>{(f'{dy*100:.2f}%') if dy else '-'}</td></tr>
      <tr><td>{ma}일 이격도</td><td><b>{curdisp:.1f}%</b></td></tr></table>"""
    # 재무표/차트
    def fin_rows(labels,r,o,n,unit_label,yoy_lag=0):
        def yoy(i):
            j=i-yoy_lag
            if yoy_lag and 0<=j and r[i] and r[j]: return f"{(r[i]/r[j]-1)*100:+.0f}%"
            return "-"
        yh="<th>매출 전년比</th>" if yoy_lag else ""
        rows="".join(f"<tr{' class=hl' if i==len(labels)-1 else ''}><td>{x}</td><td>{fmt(r[i],kr)}</td><td>{fmt(o[i],kr)}</td><td>{fmt(n[i],kr)}</td><td>{(f'{o[i]/r[i]*100:.1f}%') if (o[i] and r[i]) else '-'}</td>{('<td>'+yoy(i)+'</td>') if yoy_lag else ''}</tr>" for i,x in enumerate(labels))
        return f"<table><tr><th>{unit_label}</th><th>매출</th><th>영업이익</th><th>순이익</th><th>영업이익률</th>{yh}</tr>{rows}</table>"
    fin_html="<div class='note'>재무 데이터를 가져오지 못했습니다(일부 한국주). DART/IR 확인 권장.</div>"
    if years:
        fin_html=fin_rows(years,rev,op,ni,"연도",1)+fig_fin(years,rev,op,ni,kr,"연간 추이")
    # 분기별 (YoY=전년 동분기 대비, 4분기 전)
    q_html=""
    if qy:
        q_html=("<div class='sec' style='font-size:13px;margin:14px 0 6px'>📅 분기별 실적 (최근 "+str(len(qy))+"개 분기, 전년동기比)</div>"
                + fin_rows(qy,qr,qo,qn,"분기",4)
                + fig_fin(qy,qr,qo,qn,kr,"분기 추이"))
    else:
        q_html="<div class='note' style='margin-top:12px'>분기 데이터 미제공(일부 한국주). DART 분기보고서 확인 권장.</div>"
    # 이격도 해석(상태 문구)
    cd_=curdisp
    if cd_>=110: dstate="강한 과열권 (평균보다 많이 비쌈)"
    elif cd_>=105: dstate="과열 경향"
    elif cd_>=95: dstate="안정권 (평균 부근)"
    elif cd_>=90: dstate="침체 경향"
    else: dstate="강한 침체권 (저평가 가능)"
    guide=("<div class='note'><b>📖 이격도 쉽게 보는 법</b><br>"
           f"<b>이격도 = 주가 ÷ {ma}일 이동평균 × 100</b> · <b>100</b>이면 주가가 이평선과 같음.<br>"
           "▸ 막대가 <b style='color:#E67E00'>100 위(주황)</b> = 주가가 평균보다 <b>비쌈</b> → 단기 <b>과열</b><br>"
           "▸ 막대가 <b style='color:#1A8C7A'>100 아래(청록)</b> = 평균보다 <b>쌈</b> → <b>침체·저평가</b> 가능<br>"
           "▸ 100에서 많이 벗어날수록 평균으로 되돌아가려는 힘↑ (적정 폭은 종목마다 다름)<br>"
           f"현재 <b style='font-size:15px'>{cd_:.1f}%</b> → <b>{dstate}</b></div>")
    fav_btn=(f"<button onclick=\"addFav('{esc(code)}','{esc(name)}')\" style='background:#C9A227'>⭐ 즐겨찾기</button> "
             f"<a class='ex' href='/compare?codes={esc(code)}' style='padding:10px 14px'>🔁 비교</a>")
    sector=esc((info.get("sector") or "")+" · "+(info.get("industry") or ""))
    chart=fig_disparity(code,ma,d,p,mm,dp,name)
    return f"""<!doctype html><html lang='ko'>{CSS}<body>
    <div class='top'><div class='wrap' style='padding:0'><h1>{esc(name)} <span style='font-size:14px;color:#C7D6EC'>({esc(code)})</span></h1><p>{sector} · 생성 {dt.date.today()} · 투자권유 아님</p></div></div>
    <div class='wrap'>{form_html(code,ma,months)}
      <div class='card' style='text-align:center'>{fav_btn}</div>
      <div class='sec'>■ 핵심 요약 (실시간)</div><div class='card'>{kpi}</div>
      <div class='sec'>📊 이격도 차트 ({ma}일선, 최근 {months}개월)</div><div class='card'>{chart}{guide}</div>
      <div class='sec'>💰 재무 추이 (연간 + 분기)</div><div class='card'>{fin_html}{q_html}</div>
      <div class='note warn'>⚠ 실시간 자동 산출 · 데이터 오류·지연 가능 · <b>투자 권유가 아님</b> · 최종 책임은 투자자 본인.</div>
      <div class='foot'>주식 분석 웹앱 · {esc(code)} · {dt.date.today()}</div>
    </div></body></html>"""

def open_browser():
    try: webbrowser.open(f"http://127.0.0.1:{PORT}")
    except Exception: pass

if __name__=="__main__":
    PHONE_URL=f"http://{lan_ip()}:{PORT}"
    print("="*60)
    print("  [*] 주식 분석 웹앱 실행")
    print(f"  - 이 PC          : http://127.0.0.1:{PORT}")
    print(f"  - 폰/태블릿(같은 Wi-Fi): {PHONE_URL}")
    print("    → 폰 브라우저에 위 주소 입력, 또는 첫 화면 QR을 폰 카메라로 스캔")
    print("  (종료: 이 창에서 Ctrl+C)")
    print("="*60)
    threading.Timer(1.2,open_browser).start()
    app.run(host="0.0.0.0",port=PORT,debug=False)
