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
    inc=None; news=[]
    try: inc=tkr.income_stmt
    except Exception: pass
    try: news=tkr.news or []
    except Exception: pass
    return info,inc,news

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
    fig.add_trace(go.Bar(x=d,y=dp,name="이격도(%)",marker_color="#E5A823",opacity=0.85,
                  hovertemplate="%{x|%Y-%m-%d}<br>이격도 %{y:.1f}%<extra></extra>"),secondary_y=True)
    unit="원" if is_kr(code) else "$"
    fig.add_trace(go.Scatter(x=d,y=p,name=f"주가({unit})",line=dict(color="#111111",width=1.7),
                  hovertemplate="%{x|%Y-%m-%d}<br>"+f"%{{y:,.0f}}{unit}<extra></extra>"),secondary_y=False)
    fig.add_trace(go.Scatter(x=d,y=mm,name=f"{ma}일선",line=dict(color="#8A99B0",width=3)),secondary_y=False)
    if p.max()/max(p.min(),1)>3: fig.update_yaxes(type="log",secondary_y=False)
    fig.update_yaxes(title_text=f"주가({unit})",secondary_y=False,showgrid=True,gridcolor="#EEF1F5")
    fig.update_yaxes(title_text="이격도(%)",secondary_y=True,showgrid=False,
                     range=[min(95,np.floor(dp.min()/5)*5),np.ceil(dp.max()/5)*5+2])
    fig.update_layout(title=f"{name} · {ma}일 이격도 (주가÷{ma}일선×100)",template="plotly_white",
                      height=460,margin=dict(l=10,r=10,t=46,b=10),legend=dict(orientation="h",y=1.08,x=0.5,xanchor="center"),
                      hovermode="x unified",font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"))
    return fig.to_html(include_plotlyjs="cdn",full_html=False,config={"displayModeBar":True,"displaylogo":False})

def fig_fin(years,rev,op,ni,kr):
    div=1e12 if kr else 1e9; u="조원" if kr else "$B"
    fig=go.Figure()
    fig.add_bar(x=years,y=[ (v/div if v else None) for v in rev],name="매출",marker_color="#2563B0")
    fig.add_bar(x=years,y=[ (v/div if v else None) for v in op ],name="영업이익",marker_color="#1E7E45")
    fig.add_bar(x=years,y=[ (v/div if v else None) for v in ni ],name="순이익",marker_color="#E5A823")
    fig.update_layout(barmode="group",template="plotly_white",height=320,title=f"5년 재무 추이 ({u})",
                      margin=dict(l=10,r=10,t=46,b=10),legend=dict(orientation="h",y=1.12,x=0.5,xanchor="center"),
                      font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"))
    return fig.to_html(include_plotlyjs=False,full_html=False,config={"displayModeBar":False})

CSS="""
<meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1, viewport-fit=cover'>
<meta name='apple-mobile-web-app-capable' content='yes'>
<meta name='mobile-web-app-capable' content='yes'>
<meta name='apple-mobile-web-app-status-bar-style' content='black-translucent'>
<meta name='apple-mobile-web-app-title' content='주식분석'><meta name='theme-color' content='#16243F'>
<link rel='manifest' href='/manifest.webmanifest'>
<style>
*{box-sizing:border-box} body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;margin:0;background:#F4F7FB;color:#1C2530;-webkit-text-size-adjust:100%}
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
@media(max-width:560px){
  .wrap{padding:0 10px 40px} .top h1{font-size:18px}
  form.bar{flex-direction:column;align-items:stretch;gap:8px}
  form.bar>div{width:100%} input[type=text]{width:100%} select{width:100%} button{width:100%;padding:13px}
  table{font-size:12px} th,td{padding:6px 5px} .sec{font-size:14px}
  .ex{display:block;text-align:center}
}
</style>"""

def form_html(code="",ma="30",months="18"):
    def opt(v,cur): return f"<option value='{v}'{' selected' if str(v)==str(cur) else ''}>{v}</option>"
    return f"""<form class='bar' action='/analyze' method='get'>
      <div><label>종목코드 (한국 005930 / 미국 NVDA)</label><input type='text' name='code' value='{esc(code)}' placeholder='005930' autofocus></div>
      <div><label>이격 기준일수</label><select name='ma'>{''.join(opt(v,ma) for v in [10,20,30,60,120])}</select></div>
      <div><label>기간(개월)</label><select name='months'>{''.join(opt(v,months) for v in [3,6,12,18,24,36])}</select></div>
      <button type='submit'>분석</button>
    </form>"""

@app.route("/")
def home():
    ex="".join(f"<a class='ex' href='/analyze?code={c}'>{n}</a>" for c,n in
        [("005930","삼성전자"),("000660","SK하이닉스"),("042700","한미반도체"),("082740","한화엔진"),("NVDA","엔비디아"),("MU","마이크론")])
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
      {phone}
      <div class='card'><b>바로가기</b><br>{ex}</div>
      <div class='note'>한국=6자리 코드, 미국=티커. 데이터: FinanceDataReader·yfinance. 투자 권유 아님.</div>
      <div class='foot'>주식 분석 웹앱 · 로컬 실행</div></div></body></html>"""

@app.route("/manifest.webmanifest")
def manifest():
    import json as _j
    m={"name":"주식 분석","short_name":"주식분석","start_url":"/","scope":"/","display":"standalone",
       "background_color":"#F4F7FB","theme_color":"#16243F","lang":"ko","icons":[]}
    return Response(_j.dumps(m,ensure_ascii=False),mimetype="application/manifest+json")

@app.route("/analyze")
def analyze():
    code=(request.args.get("code") or "").strip().upper()
    ma=int(request.args.get("ma") or 30); months=int(request.args.get("months") or 18)
    if not code: return home()
    kr=is_kr(code)
    try:
        d,p,mm,dp=get_prices(code,ma,months)
        if len(d)<2: raise ValueError("데이터 부족")
    except Exception as e:
        return f"<!doctype html><html>{CSS}<body><div class='top'><div class='wrap' style='padding:0'><h1>📈 주식 분석</h1></div></div><div class='wrap'>{form_html(code,ma,months)}<div class='note warn'>‼ '{esc(code)}' 데이터를 가져오지 못했습니다. 종목코드를 확인하세요(한국=6자리, 미국=티커). ({esc(e)})</div></div></body></html>"
    info,inc,news=fetch_meta(code)
    name=info.get("longName") or info.get("shortName") or code
    cur=int(p[-1]); curdisp=float(dp[-1]); unit="원" if kr else "$"
    # 재무
    years=[];rev=[];op=[];ni=[]
    if inc is not None and not inc.empty:
        def pick(keys):
            for k in keys:
                if k in inc.index: return inc.loc[k]
            return None
        sr=pick(["Total Revenue","Operating Revenue"]);so=pick(["Operating Income","Total Operating Income As Reported"]);sn=pick(["Net Income","Net Income Common Stockholders"])
        for c in list(inc.columns)[::-1]:
            years.append(str(c.year))
            rev.append(float(sr[c]) if sr is not None and c in sr and not np.isnan(sr[c]) else None)
            op.append(float(so[c]) if so is not None and c in so and not np.isnan(so[c]) else None)
            ni.append(float(sn[c]) if sn is not None and c in sn and not np.isnan(sn[c]) else None)
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
    fin_html="<div class='note'>재무 데이터를 가져오지 못했습니다(일부 한국주). DART/IR 확인 권장.</div>"
    if years:
        rows="".join(f"<tr{' class=hl' if i==len(years)-1 else ''}><td>{y}</td><td>{fmt(rev[i],kr)}</td><td>{fmt(op[i],kr)}</td><td>{fmt(ni[i],kr)}</td><td>{(f'{op[i]/rev[i]*100:.1f}%') if (op[i] and rev[i]) else '-'}</td></tr>" for i,y in enumerate(years))
        fin_html=f"<table><tr><th>연도</th><th>매출</th><th>영업이익</th><th>순이익</th><th>영업이익률</th></tr>{rows}</table>"+fig_fin(years,rev,op,ni,kr)
    # 뉴스
    items=""
    for n in news[:7]:
        c=n.get("content",n) if isinstance(n.get("content",None),dict) else n
        ti=c.get("title") or n.get("title"); lk=(c.get("canonicalUrl",{}) or {}).get("url") or n.get("link")
        if ti:
            items+=f"<li>{('<a target=_blank href=\"'+esc(lk)+'\">') if lk else ''}{esc(ti)}{'</a>' if lk else ''}</li>"
    news_html=f"<ul class='news'>{items or '<li>(뉴스 없음)</li>'}</ul>"
    # 스코어카드
    def star(b): return "<span class=star>★★★★☆</span>" if b is True else ("<span class=star>★★★☆☆</span>" if b is None else "<span class=star>★★☆☆☆</span>")
    g_rev=(years and rev[-1] and rev[0] and rev[-1]>rev[0]); g_op=(years and op[-1] and op[0] and op[-1]>op[0])
    val=(per is not None and per<15); dok=(curdisp<115)
    score=f"""<table><tr><th>항목</th><th>등급</th><th>근거(자동)</th></tr>
      <tr><td>매출 성장(5Y)</td><td>{star(bool(g_rev))}</td><td>{'최근>과거' if g_rev else '정체/감소·확인'}</td></tr>
      <tr><td>이익 성장(5Y)</td><td>{star(bool(g_op))}</td><td>{'영업이익 개선' if g_op else '확인 필요'}</td></tr>
      <tr><td>밸류(PER)</td><td>{star(True if val else (None if per is None else False))}</td><td>PER {num(per)}</td></tr>
      <tr><td>이격도 위치</td><td>{star(True if dok else False)}</td><td>{curdisp:.1f}% ({'안정권' if dok else '과열경계'})</td></tr></table>"""
    summ=esc((info.get("longBusinessSummary") or "")[:700])
    sector=esc((info.get("sector") or "")+" · "+(info.get("industry") or ""))
    chart=fig_disparity(code,ma,d,p,mm,dp,name)
    return f"""<!doctype html><html lang='ko'>{CSS}<body>
    <div class='top'><div class='wrap' style='padding:0'><h1>{esc(name)} <span style='font-size:14px;color:#C7D6EC'>({esc(code)})</span></h1><p>{sector} · 생성 {dt.date.today()} · 투자권유 아님</p></div></div>
    <div class='wrap'>{form_html(code,ma,months)}
      <div class='sec'>■ 핵심 요약 (실시간)</div><div class='card'>{kpi}
        <div class='note'>{ma}일 이격도 <b>{curdisp:.1f}%</b> — 100 위=이평선 위(과열 경향)·아래=침체. 한국주는 PER/목표가가 '-'일 수 있음.</div></div>
      <div class='sec'>📊 이격도 차트 ({ma}일선, 최근 {months}개월)</div><div class='card'>{chart}</div>
      <div class='sec'>💰 5년 재무 추이</div><div class='card'>{fin_html}</div>
      <div class='sec'>🏢 사업 개요</div><div class='card'><div class='muted'>{summ or '(요약 없음)'}</div></div>
      <div class='sec'>📰 최근 뉴스 (계약·전망 단서)</div><div class='card'>{news_html}<div class='muted'>상세 계약·수주·가이던스는 공시(DART/SEC)·IR 원문 확인.</div></div>
      <div class='sec'>⭐ 자동 스코어카드 (룰 기반)</div><div class='card'>{score}</div>
      <div class='note warn'>⚠ 자동 산출(정량 데이터 기반)입니다. 정성 펀더멘털·향후 계약은 리서치로 보강하세요. <b>투자 권유가 아니며</b> 데이터 오류·지연 가능. 최종 책임은 투자자 본인.</div>
      <div class='foot'>주식 분석 웹앱 · {esc(code)} · {dt.date.today()} · FinanceDataReader·yfinance</div>
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
