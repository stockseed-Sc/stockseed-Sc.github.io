# -*- coding: utf-8 -*-
"""
주식 AI 사이트 키트 — 종목별 페이지 자동 생성기

  python build.py            # 실제 데이터로 전체 사이트 생성 → site/ 폴더
  python build.py --limit 50 # 시가총액 상위 50종목만 (빠른 테스트)
  python build.py --demo     # 인터넷 없이 가짜 샘플 데이터로 화면만 확인

데이터: 1순위 FinanceDataReader(네이버·KRX), 실패하면 2순위 다음 금융.
"""
import argparse, json, math, os, random, re, shutil, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "site"
KST = timezone(timedelta(hours=9))
# ───── 사이트별로 바꾸는 값의 기본값 (config.json에 같은 이름으로 적으면 덮어씀) ─────
DEFAULTS = {
    "theme": {  # 색상
        "ink": "#0F1B2D", "ink2": "#16263D", "bg": "#F4F5F7",
        "accent": "#B3122B", "ai": "#5B3DF5", "highlight": "#FFE14D",
        "up": "#D21F2D", "down": "#1B5FCC",
    },
    "copy": {  # 화면 문구 (일부는 HTML 태그 <b>, <br> 사용 가능)
        "home_title": "{site} | AI 주가예측 무료 — 코스피·코스닥 전 종목",
        "home_desc": "종목명만 입력하면 AI가 5거래일 뒤 상승 확률과 예상 가격 범위를 무료로 계산해 드립니다. 코스피·코스닥 {count}개 전 종목, 매 거래일 장 마감 후 갱신.",
        "promo": "AI 주가예측 전 종목 <b>무료</b> 공개 · 매 거래일 장 마감 후 갱신",
        "nav_ai": "AI 주가예측",
        "hero_badges": ["100% 무료", "가입 없이 바로"],
        "hero_title": "종목만 입력하세요.<br>AI가 주가를 예측합니다.",
        "hero_sub": "머신러닝 AI가 매일 장 마감 후 전 종목을 다시 학습해 5거래일 뒤 상승 확률을 계산합니다.",
        "tool_button": "AI 예측 돌리기",
        "news_title": "오늘의 주요 종목 뉴스",
        "hooks_title": "기본 예측으로 부족하다면",
        "hooks": [
            {"style": "ai", "tag": "AI 심층분석", "title": "AI가 더 깊게 분석합니다",
             "bullets": ["매수·매도 타이밍 구간 분석", "수급·변동성·업종 흐름까지 반영한 심층 리포트", "목표 구간과 손절 구간 설명"],
             "button": "AI 심층분석 받기", "hook": "AI 심층분석",
             "sub": "번호를 남기시면 심층분석 결과를 전화·카카오톡으로 직접 설명해 드립니다."},
            {"style": "pro", "tag": "전문가 종목상담", "title": "전문가에게 물어보세요", "title_nostock": "보유·관심 종목, 전문가에게 물어보세요",
             "bullets": ["지금 사도 될지, 팔아야 할지 1:1 상담", "물린 종목 대응 전략 상담", "상담 비용 없음"],
             "button": "전문가 상담 신청", "hook": "전문가 종목상담",
             "sub": "번호를 남기시면 전문가가 직접 연락드립니다."},
        ],
        "lead": {
            "badge": "상담 비용 0원 · 100% 무료",
            "title_1": "전문가", "title_2": "무료 종목상담",
            "sub": "휴대폰 번호만 남기시면 영업일 기준 {reply_days}일 안에 전문가가 직접 연락드립니다.",
            "points": ["보유·관심 종목 1:1 진단", "AI 분석 결과 상세 설명", "물린 종목 대응 전략 상담"],
            "free_big": "0원", "free_text": "가입·결제 없이 번호만 남기면 끝",
            "button": "전문가 무료 종목상담 신청", "hook": "전문가 무료 종목상담",
        },
        "popup_title": "{stock}, 지금 사도 될까요?",
        "popup_sub": "AI 분석 결과를 바탕으로 무료로 상담해 드립니다. 번호만 남겨주세요.",
        "comment_label": "AI 코멘트",
    },
    "design": {  # 디자인 프리셋: night | paper | neon | soft | grid | big | aurora
        "preset": "night",
        "home_sections": ["news", "hooks", "reports"],  # 메인에서 검색 도구 아래 섹션 순서
    },
    "features": {  # 기능 켜고 끄기
        "news": True, "reports": True, "comment": True, "popup": True, "ai_page": True,
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


CFG = _merge(DEFAULTS, json.loads((ROOT / "config.json").read_text(encoding="utf-8")))

DAUM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Referer": "https://finance.daum.net/",
    "Accept": "application/json",
}


def log(*a):
    print(datetime.now(KST).strftime("%H:%M:%S"), *a, flush=True)


# ════════════════════════ 1. 데이터 수집 ════════════════════════

def listing_fdr():
    import FinanceDataReader as fdr
    df = fdr.StockListing("KRX")
    df = df.rename(columns={"Code": "code", "Name": "name", "Market": "market", "Marcap": "marcap", "Stocks": "shares"})
    df["market"] = df["market"].replace({"KOSDAQ GLOBAL": "KOSDAQ"})
    df = df[["code", "name", "market", "marcap", "shares"]]
    try:  # 업종 정보 (실패해도 진행)
        desc = fdr.StockListing("KRX-DESC").rename(columns={"Code": "code", "Sector": "sector", "Industry": "industry"})
        df = df.merge(desc[["code", "sector", "industry"]], on="code", how="left")
    except Exception as e:
        log("업종 정보 생략:", e)
    return df


def listing_daum():
    import requests
    rows = []
    for m in CFG["markets"]:
        for p in range(1, 15):
            url = f"https://finance.daum.net/api/trend/market_capitalization?page={p}&perPage=200&fieldName=marketCap&order=desc&market={m}&pagination=true"
            j = requests.get(url, headers=DAUM_HEADERS, timeout=15).json()
            data = j.get("data") or []
            for d in data:
                rows.append({"code": d["symbolCode"][1:], "name": d["name"], "market": m,
                             "marcap": d.get("marketCap"), "shares": d.get("listedShareCount")})
            if len(data) < 200:
                break
    return pd.DataFrame(rows)


def get_sectors_naver():
    """네이버 증권 업종 분류(약 80개)를 종목코드 → 업종명으로 가져옴"""
    import requests
    H = {"User-Agent": DAUM_HEADERS["User-Agent"], "Referer": "https://finance.naver.com/",
         "Accept-Language": "ko-KR,ko;q=0.9"}
    base = "https://finance.naver.com"
    r = requests.get(base + "/sise/sise_group.naver?type=upjong", headers=H, timeout=15)
    r.encoding = "euc-kr"
    groups = dict(re.findall(r'type=upjong&(?:amp;)?no=(\d+)[^>]*>\s*([^<]+?)\s*</a>', r.text))
    if len(groups) < 10:
        raise RuntimeError(f"네이버 업종 목록 인식 실패 (HTTP {r.status_code}, {len(r.text)}자, 업종 {len(groups)}개)")
    out = {}

    def one(item):
        no, name = item
        rr = requests.get(f"{base}/sise/sise_group_detail.naver?type=upjong&no={no}", headers=H, timeout=15)
        rr.encoding = "euc-kr"
        return name.strip(), re.findall(r'code=(\d{6})', rr.text)

    with ThreadPoolExecutor(6) as ex:
        for name, codes in ex.map(one, groups.items()):
            for c in codes:
                out.setdefault(c, name)
    return out


def get_sectors_kind():
    """한국거래소 KIND 상장회사 목록의 '업종' (예: 반도체 제조업)"""
    import requests, html as _html
    url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
    r = requests.get(url, headers={"User-Agent": DAUM_HEADERS["User-Agent"]}, timeout=30)
    r.encoding = "euc-kr"
    out = {}
    for row in re.findall(r"<tr>(.*?)</tr>", r.text, re.S):
        cells = [_html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        # 회사명, 시장구분, 종목코드, 업종, 주요제품, ... (열 순서가 바뀌어도 6자리 코드 다음 칸을 업종으로 봄)
        for i, c in enumerate(cells):
            if re.fullmatch(r"[0-9A-Z]{6}", c) and i + 1 < len(cells):
                if cells[i + 1]:
                    out[c] = cells[i + 1]
                break
    if len(out) < 500:
        raise RuntimeError(f"KIND 업종 인식 실패 (HTTP {r.status_code}, {len(r.text)}자, {len(out)}종목)")
    return out


def get_sectors():
    for fn in (get_sectors_naver, get_sectors_kind):
        try:
            sec = fn()
            log(f"업종 분류({fn.__name__}): {len(set(sec.values()))}개 업종, {len(sec)}개 종목")
            if len(sec) > 500:
                return sec
        except Exception as e:
            log(f"{fn.__name__} 실패:", repr(e)[:200])
    return {}


def fetch_news(name, limit=5, days=7):
    """구글 뉴스 RSS에서 종목 관련 최신 기사 제목·언론사·시간·링크만 가져옴 (본문은 가져오지 않음)"""
    import requests, urllib.parse, xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    q = urllib.parse.quote(f'"{name}" 주가 OR "{name}" 주식')
    url = f"https://news.google.com/rss/search?q={q}+when:{days}d&hl=ko&gl=KR&ceid=KR:ko"
    r = requests.get(url, headers={"User-Agent": DAUM_HEADERS["User-Agent"]}, timeout=15)
    r.raise_for_status()
    items = []
    for it in ET.fromstring(r.content).iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST)
        except Exception:
            dt = None
        link = (it.findtext("link") or "").strip()
        if title and link.startswith("https://"):
            items.append({"title": title, "source": src, "link": link,
                          "time": dt.strftime("%m.%d %H:%M") if dt else "", "ts": dt.timestamp() if dt else 0})
    items.sort(key=lambda x: -x["ts"])
    seen, out = set(), []
    for x in items:
        k = x["title"][:30]
        if k not in seen:
            seen.add(k)
            out.append(x)
        if len(out) >= limit:
            break
    return out


def get_news(stocks):
    n = int(CFG.get("news_top_n", 300))
    targets = sorted(stocks, key=lambda s: -(s["marcap"] or 0))[:n]
    got, fail = 0, 0

    def one(s):
        for attempt in range(2):
            try:
                return s, fetch_news(s["name"])
            except Exception:
                time.sleep(1 + attempt)
        return s, None

    with ThreadPoolExecutor(4) as ex:
        for s, news in ex.map(one, targets):
            if news is None:
                fail += 1
            elif news:
                s["news"] = news
                got += 1
    log(f"종목 뉴스: {got}개 종목 수집 (대상 {len(targets)}, 실패 {fail})")


def get_listing():
    for fn in (listing_fdr, listing_daum):
        try:
            df = fn()
            if len(df) > 500:
                log(f"종목 목록: {fn.__name__} → {len(df)}개")
                return df
        except Exception as e:
            log(f"{fn.__name__} 실패:", e)
    sys.exit("종목 목록을 가져오지 못했습니다.")


def hist_fdr(code, start):
    import FinanceDataReader as fdr
    df = fdr.DataReader(code, start)
    return df[["Open", "High", "Low", "Close", "Volume"]]


def hist_daum(code, start):
    import requests
    rows, sym = [], "A" + code
    for p in range(1, 5):
        url = f"https://finance.daum.net/api/quote/{sym}/days?symbolCode={sym}&page={p}&perPage=100&pagination=true"
        data = requests.get(url, headers=DAUM_HEADERS, timeout=15).json().get("data") or []
        for d in data:
            rows.append({"Date": d["date"][:10], "Open": d["openingPrice"], "High": d["highPrice"],
                         "Low": d["lowPrice"], "Close": d["tradePrice"], "Volume": d["accTradeVolume"]})
        if len(data) < 100 or (data and data[-1]["date"][:10] < start):
            break
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date").sort_index()


def clean_ohlc(df):
    """거래정지일처럼 가격이 0이거나 비정상인 날을 걸러냄"""
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    df = df[(df["Volume"] > 0) & (df["Close"] > 0) & (df["High"] > 0) & (df["Low"] > 0)].copy()
    df["Open"] = df["Open"].where(df["Open"] > 0, df["Close"])
    df["High"] = df[["High", "Open", "Close"]].max(axis=1)
    df["Low"] = df[["Low", "Open", "Close"]].min(axis=1)
    return df


def get_history(code, start):
    for fn in (hist_fdr, hist_daum):
        for attempt in range(2):
            try:
                df = fn(code, start)
                df = clean_ohlc(df)
                if len(df) >= 2:
                    return df
            except Exception:
                time.sleep(0.5 + attempt)
    return None


# ════════════════════════ 데모 데이터 (테스트 전용) ════════════════════════

def demo_data(n=40):
    """실제 회사가 아닌 가짜 종목. 화면 확인용."""
    random.seed(7)
    sectors = ["반도체", "2차전지", "바이오", "자동차부품", "게임", "조선"]
    lst, hist = [], {}
    end = datetime.now(KST).date()
    days = pd.bdate_range(end=end, periods=260)
    for i in range(n):
        code = f"9{i:05d}"
        price = random.choice([3000, 12000, 45000, 180000])
        o = []
        for d in days:
            ch = random.gauss(0.0006, 0.022)
            op = price * (1 + random.gauss(0, 0.008))
            cl = max(100, op * (1 + ch))
            hi, lo = max(op, cl) * (1 + abs(random.gauss(0, 0.01))), min(op, cl) * (1 - abs(random.gauss(0, 0.01)))
            vol = int(abs(random.gauss(1, 0.4)) * 300000 * (3 if random.random() < 0.03 else 1))
            o.append([d, round(op), round(hi), round(lo), round(cl), vol])
            price = cl
        df = pd.DataFrame(o, columns=["Date", "Open", "High", "Low", "Close", "Volume"]).set_index("Date")
        shares = random.choice([5e6, 2e7, 8e7])
        lst.append({"code": code, "name": f"샘플종목{i+1:02d}", "market": "KOSPI" if i % 2 else "KOSDAQ",
                    "marcap": df.Close.iloc[-1] * shares, "shares": shares, "sector": sectors[i % len(sectors)]})
        hist[code] = df
    return pd.DataFrame(lst), hist


# ════════════════════════ 2. 지표 계산 ════════════════════════

def pct(a, b):
    return (a / b - 1) * 100 if b else None


def compute(row, df):
    df = clean_ohlc(df).tail(260)
    if len(df) < 2:
        raise ValueError("유효한 시세가 부족합니다")
    last, prev = df.iloc[-1], df.iloc[-2]
    c = float(last.Close)
    y = df.tail(250)
    hi52, lo52 = float(y.High.max()), float(y.Low.min())
    vol20 = float(df.Volume.iloc[-21:-1].mean()) if len(df) > 21 else None

    def ret(n):
        return pct(c, float(df.Close.iloc[-n - 1])) if len(df) > n else None

    shares = row.get("shares")
    marcap = row.get("marcap")
    if (not marcap or pd.isna(marcap)) and shares:
        marcap = c * shares

    recent = []
    rd = df.tail(11)
    for i in range(len(rd) - 1, 0, -1):
        r, p = rd.iloc[i], rd.iloc[i - 1]
        recent.append({"date": rd.index[i].strftime("%m.%d"), "close": float(r.Close),
                       "chg": pct(float(r.Close), float(p.Close)), "volume": int(r.Volume)})

    sector = row.get("sector")
    sector = sector if isinstance(sector, str) and sector.strip() else None
    return {
        "code": row["code"], "name": row["name"], "market": row["market"],
        "sector": sector,
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "date_kr": f"{df.index[-1].month}월 {df.index[-1].day}일",
        "open": float(last.Open), "high": float(last.High), "low": float(last.Low), "close": c,
        "prev": float(prev.Close), "change": c - float(prev.Close), "chg": pct(c, float(prev.Close)),
        "volume": int(last.Volume), "amount": c * float(last.Volume),
        "vol_ratio": (float(last.Volume) / vol20) if vol20 else None,
        "marcap": float(marcap) if marcap and not pd.isna(marcap) else None,
        "shares": float(shares) if shares and not pd.isna(shares) else None,
        "hi52": hi52, "lo52": lo52,
        "from_hi": pct(c, hi52), "from_lo": pct(c, lo52),
        "r1w": ret(5), "r1m": ret(20), "r3m": ret(60), "r6m": ret(120), "r1y": ret(245),
        "recent": recent,
        "chart": chart_svg(df.tail(120)),
        **tech_stats(df),
    }


def tech_stats(df):
    """AI 코멘트용 기술 지표"""
    c = df["Close"].astype(float)
    ret = c.pct_change()
    out = {"ma20": None, "ma60": None, "volat": None, "rsi": None, "hi20": None, "lo20": None}
    if len(c) >= 20:
        out["ma20"] = float(c.tail(20).mean())
        out["hi20"] = float(df["High"].tail(20).max())
        out["lo20"] = float(df["Low"].tail(20).min())
        sd = ret.tail(20).std()
        if sd == sd:
            out["volat"] = float(sd) * math.sqrt(252) * 100
    if len(c) >= 60:
        out["ma60"] = float(c.tail(60).mean())
    if len(c) >= 15:
        g = ret.clip(lower=0).tail(14).mean()
        l = (-ret.clip(upper=0)).tail(14).mean()
        if g + l > 0:
            out["rsi"] = float(100 * g / (g + l))
    return out


def ai_comment(s):
    """'AI 쉬운 해설' — 초보자 눈높이 존댓말, 전문용어는 괄호로 풀이 (투자 권유 문구 없음)"""
    import hashlib
    seed = int(hashlib.md5((s["code"] + s["date"]).encode()).hexdigest(), 16)
    pick = lambda opts, k=0: opts[(seed >> (k * 3)) % len(opts)]
    c = s["close"]
    ma20, ma60 = s.get("ma20"), s.get("ma60")
    pts = []

    # 1) 요즘 흐름
    trend = "중립"
    if ma20 and ma60:
        a20, a60 = c >= ma20, c >= ma60
        if a20 and a60:
            trend = "상승"
            t = pick(["지금 주가가 최근 한 달 평균과 석 달 평균보다 모두 높아요. 요즘 흐름이 좋은 편이라는 뜻이에요",
                      "최근 1개월·3개월 평균 가격(이동평균선)보다 위에 있어요. 오르는 흐름이 이어지고 있어요"], 1)
        elif a20:
            trend = "반등"
            t = "한 달 평균 가격은 넘어섰지만 석 달 평균보다는 아직 아래예요. 내려오다가 다시 올라오는 중(반등)이라고 볼 수 있어요"
        elif a60:
            trend = "조정"
            t = "석 달 평균보다는 위에 있지만 최근 한 달 평균보다는 아래예요. 오르다가 잠시 쉬어 가는 중(조정)이에요"
        else:
            trend = "하락"
            t = "한 달 평균과 석 달 평균보다 모두 아래에 있어요. 아직은 내려가는 흐름이 이어지고 있어요"
        pts.append(("요즘 흐름", f"{t}. (20일 평균 {fmt_price(ma20)}원 · 60일 평균 {fmt_price(ma60)}원)"))

    # 2) 최근 성적
    r1m, r3m = s.get("r1m"), s.get("r3m")
    if r1m is not None:
        m = f"최근 1개월 동안 {abs(r1m):.1f}% {'올랐' if r1m >= 0 else '내렸'}어요"
        if r3m is not None:
            m += f". 3개월로 보면 {abs(r3m):.1f}% {'올랐' if r3m >= 0 else '내렸'}어요"
        rsi = s.get("rsi")
        if rsi is not None and rsi >= 70:
            m += f". 짧은 기간에 많이 올라 '과열'(RSI {rsi:.0f}) 구간이에요. 이럴 땐 흔들림이 커질 수 있어요"
        elif rsi is not None and rsi <= 30:
            m += f". 짧은 기간에 많이 내려 '과매도'(RSI {rsi:.0f}) 구간이에요. 반등이 나오기도 하지만 더 내려가기도 해요"
        pts.append(("최근 성적", m + "."))

    # 3) 관심도(거래량)
    vr = s.get("vol_ratio")
    if vr:
        if vr >= 3:
            v = f"오늘 거래량(사고판 주식 수)이 평소의 {vr:.1f}배예요. 무슨 소식이 있었는지 뉴스와 공시를 꼭 확인해 보세요"
        elif vr >= 1.5:
            v = f"오늘 거래량이 평소보다 많아요({vr:.1f}배). 관심이 조금 늘었다는 뜻이에요"
        elif vr <= 0.6:
            v = "오늘은 평소보다 거래가 적었어요. 관심이 잠시 줄어든 조용한 날이에요"
        else:
            v = "오늘 거래량은 평소와 비슷했어요"
        pts.append(("관심도", v + "."))

    # 4) 출렁임
    vol = s.get("volat")
    if vol is not None:
        if vol >= 50:
            w = f"주가가 크게 출렁이는 편이에요(연 변동성 {vol:.0f}%). 초보자라면 한 번에 많이 사기보다 나눠서 접근하는 게 안전해요"
        elif vol >= 25:
            w = f"주가 출렁임은 보통 수준이에요(연 변동성 {vol:.0f}%)"
        else:
            w = f"주가가 비교적 차분하게 움직이는 편이에요(연 변동성 {vol:.0f}%)"
        if s.get("from_hi") is not None and s["from_hi"] > -3:
            w += ". 그리고 지금 가격이 최근 1년 중 가장 높은 가격(52주 최고가) 근처예요"
        elif s.get("from_lo") is not None and s["from_lo"] < 5:
            w += ". 그리고 지금 가격이 최근 1년 중 가장 낮은 가격(52주 최저가) 근처예요"
        pts.append(("출렁임", w + "."))

    # 5) AI
    ai = s.get("ai") or {}
    if ai.get("p") is not None:
        pts.append(("AI 계산", f"과거 데이터로 계산해 보면 5거래일 뒤 지금보다 높을 확률은 {ai['p']*100:.0f}%예요. "
                              f"보통 {fmt_price(ai['lo'])}~{fmt_price(ai['hi'])}원 사이에서 움직일 가능성이 높다고 봐요. 어디까지나 통계라서 참고만 해 주세요."))

    heads = {
        "상승": ["오르는 흐름이 이어지는 중이에요", "흐름이 좋은 편이지만, 너무 급하게 따라가진 마세요"],
        "반등": ["내려오다가 다시 힘을 내는 중이에요", "반등 중이에요. 석 달 평균선을 넘는지 지켜봐요"],
        "조정": ["오르다가 잠깐 쉬어 가는 중이에요", "잠시 숨 고르기 중이에요"],
        "하락": ["아직은 내려가는 흐름이에요", "흐름이 약해요. 서두르지 않는 게 좋아요"],
        "중립": ["뚜렷한 방향 없이 오르내리는 중이에요"],
    }
    head = pick(heads[trend], 4)

    watch = []
    if s.get("lo20"):
        watch.append(f"최근 한 달 가장 낮았던 가격 {fmt_price(s['lo20'])}원 아래로 내려가는지")
    if s.get("hi20"):
        watch.append(f"최근 한 달 가장 높았던 가격 {fmt_price(s['hi20'])}원을 넘는지")
    if vr and vr >= 3:
        watch.append("거래량이 갑자기 늘어난 이유(뉴스·공시)")
    else:
        watch.append("회사 실적 발표와 공시 내용")
    return {"head": head, "points": pts, "watch": watch[:3]}


# ════════════════════════ 3. 차트 (서버에서 SVG로 그림) ════════════════════════

def chart_svg(df, W=760, H=320):
    n = len(df)
    pad_l, pad_r, pad_t = 8, 64, 12
    ph, vh, gap = 210, 56, 22
    cw = (W - pad_l - pad_r) / n
    hi, lo = float(df.High.max()), float(df.Low.min())
    rng = (hi - lo) or 1
    vmax = float(df.Volume.max()) or 1
    Y = lambda v: pad_t + (hi - v) / rng * ph
    vy0 = pad_t + ph + gap
    parts = []
    # 가로 눈금
    for k in range(5):
        v = lo + rng * k / 4
        yy = Y(v)
        parts.append(f'<line x1="{pad_l}" x2="{W-pad_r}" y1="{yy:.1f}" y2="{yy:.1f}" class="g"/>'
                     f'<text x="{W-pad_r+6}" y="{yy+4:.1f}" class="t">{fmt_price(v)}</text>')
    for i, (d, r) in enumerate(df.iterrows()):
        x = pad_l + i * cw + cw / 2
        up = r.Close >= r.Open
        cls = "u" if up else "d"
        top, bot = Y(max(r.Open, r.Close)), Y(min(r.Open, r.Close))
        bw = max(1.0, cw * 0.62)
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{Y(r.High):.1f}" y2="{Y(r.Low):.1f}" class="{cls}"/>'
                     f'<rect x="{x-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(1, bot-top):.1f}" class="{cls}"/>')
        vhgt = r.Volume / vmax * vh
        parts.append(f'<rect x="{x-bw/2:.1f}" y="{vy0+vh-vhgt:.1f}" width="{bw:.1f}" height="{max(0.5, vhgt):.1f}" class="v{cls}"/>')
    for i in (0, n // 2, n - 1):
        x = pad_l + i * cw + cw / 2
        anchor = "start" if i == 0 else "end" if i == n - 1 else "middle"
        parts.append(f'<text x="{x:.1f}" y="{H-4}" class="t" text-anchor="{anchor}">{df.index[i].strftime("%y.%m.%d")}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="최근 {n}거래일 일봉 차트와 거래량">'
            + "".join(parts) + "</svg>")


# ════════════════════════ 4. 문장 자동 생성 ════════════════════════

def fmt_price(v):
    return f"{v:,.0f}"


def fmt_won(v):
    if v is None:
        return "-"
    if v >= 1e12:
        jo, eok = divmod(round(v / 1e8), 10000)
        return f"{jo:,}조 {eok:,}억원" if eok else f"{jo:,}조원"
    if v >= 1e8:
        return f"{v/1e8:,.0f}억원"
    return f"{v/1e4:,.0f}만원"


def fmt_pct(v, sign=True):
    if v is None:
        return "-"
    return f"{v:+.2f}%" if sign else f"{v:.2f}%"


def josa(word, a="은", b="는"):
    ch = word.strip()[-1:] if word else ""
    if "가" <= ch <= "힣":
        return word + (a if (ord(ch) - 0xAC00) % 28 else b)
    return f"{word}{a}({b})"


def summary(s):
    nm, out = s["name"], []
    nm_t = josa(nm)
    if s["chg"] is None or abs(s["chg"]) < 0.005:
        out.append(f"{nm_t} {s['date_kr']} {fmt_price(s['close'])}원에 거래를 마치며 전일과 같은 가격을 유지했습니다.")
    else:
        word = "상승" if s["chg"] > 0 else "하락"
        out.append(f"{nm_t} {s['date_kr']} 전일보다 {fmt_price(abs(s['change']))}원({abs(s['chg']):.2f}%) {word}한 "
                   f"{fmt_price(s['close'])}원에 거래를 마쳤습니다.")
    if s["marcap"]:
        out.append(f"종가 기준 시가총액은 {fmt_won(s['marcap'])}입니다.")
    if s["vol_ratio"]:
        vr = s["vol_ratio"]
        if vr >= 2:
            out.append(f"거래량은 {s['volume']:,}주로 최근 20거래일 평균의 {vr:.1f}배까지 늘었습니다.")
        elif vr <= 0.6:
            out.append(f"거래량은 {s['volume']:,}주로 최근 20거래일 평균보다 적었습니다.")
        else:
            out.append(f"거래량은 {s['volume']:,}주로 최근 20거래일 평균과 비슷한 수준입니다.")
    if s["r1m"] is not None:
        r = s["r1m"]
        out.append(f"최근 1개월 동안 주가는 {abs(r):.1f}% {'올랐' if r >= 0 else '내렸'}고, "
                   + (f"3개월 기준으로는 {fmt_pct(s['r3m'])}입니다." if s["r3m"] is not None else "") )
    if s["from_hi"] is not None and s["from_lo"] is not None:
        if s["from_hi"] > -1:
            out.append(f"현재 주가는 52주 최고가({fmt_price(s['hi52'])}원) 부근에 있습니다.")
        else:
            out.append(f"현재 주가는 52주 최고가 {fmt_price(s['hi52'])}원보다 {abs(s['from_hi']):.1f}% 낮고, "
                       f"52주 최저가 {fmt_price(s['lo52'])}원보다는 {s['from_lo']:.1f}% 높은 위치입니다.")
    return out


def faqs(s):
    nm = s["name"]
    q = [
        (f"{nm} 오늘 주가는 얼마인가요?",
         f"{s['date_kr']} 종가는 {fmt_price(s['close'])}원으로, 전일 대비 {fmt_pct(s['chg'])} 움직였습니다."),
        (f"{nm} 종목코드는 무엇인가요?",
         f"{nm}의 종목코드는 {s['code']}이며 {s['market']}에 상장되어 있습니다."),
        (f"{nm} 52주 최고가와 최저가는?",
         f"최근 52주 최고가는 {fmt_price(s['hi52'])}원, 최저가는 {fmt_price(s['lo52'])}원입니다."),
        (f"{nm} 시가총액은 얼마인가요?",
         f"{s['date_kr']} 종가 기준 시가총액은 {fmt_won(s['marcap'])}입니다." if s["marcap"] else "시가총액 정보가 없습니다."),
    ]
    ai = s.get("ai") or {}
    if ai.get("p") is not None:
        q.insert(1, (f"{nm} 주가 예측은 어떻게 나오나요?",
                     f"{CFG['site_name']} AI 모델이 계산한 {nm}의 5거래일 뒤 상승 확률은 {ai['p']*100:.0f}%({ai['signal']})이며, "
                     f"최근 변동성 기준 예상 가격 범위는 {fmt_price(ai['lo'])}원~{fmt_price(ai['hi'])}원입니다. "
                     f"과거 데이터로 계산한 통계적 추정이며 실제 주가와 다를 수 있습니다. AI 예측은 전 종목 무료로 제공됩니다."))
    return q


# ════════════════════════ 5. 페이지 생성 ════════════════════════

def safe_round(v):
    try:
        return round(float(v))
    except (TypeError, ValueError, OverflowError):
        return None


def slug(text):
    return re.sub(r"[^0-9A-Za-z가-힣]+", "-", text).strip("-")


def build(stocks, base_date):
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    # 폴더째 올라가지 않고 파일이 맨 바깥에 흩어져 있어도 찾을 수 있게 처리
    static_dir = ROOT / "static" if (ROOT / "static").is_dir() else ROOT
    for name in ("site.css", "site.js"):
        src = static_dir / name
        if not src.exists():
            sys.exit(f"{name} 파일을 찾을 수 없습니다.")
        shutil.copy(src, OUT / "assets" / name)

    tpl_dirs = [d for d in (ROOT / "templates", ROOT) if d.is_dir()]
    env = Environment(loader=FileSystemLoader(tpl_dirs), autoescape=select_autoescape(["html"]))
    env.filters.update(price=fmt_price, won=fmt_won, pct=fmt_pct, slug=slug)
    base = CFG["base_path"].rstrip("/")
    site_url = CFG["site_url"].rstrip("/") + base
    public_cfg = {k: CFG[k] for k in ("site_name", "sheet_url", "kakao_url", "phone", "phone_hours", "biz_info")}
    cp = json.loads(json.dumps(CFG["copy"], ensure_ascii=False)
                    .replace("{site}", CFG["site_name"]).replace("{reply_days}", str(CFG.get("reply_days", "1"))))
    common = {"cfg": CFG, "cp": cp, "th": CFG["theme"], "ft": CFG["features"], "dz": CFG["design"],
              "base": base, "site_url": site_url, "base_date": base_date,
              "public_cfg": json.dumps(public_cfg, ensure_ascii=False),
              "year": datetime.now(KST).year, "ai_report": MODEL_INFO["report"],
              "has_glossary": bool(GLOSSARY["terms"])}

    def write(out_path, tpl, **ctx):
        p = OUT / out_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(env.get_template(tpl).render(**common, **ctx), encoding="utf-8")

    stocks = sorted(stocks, key=lambda s: -(s["marcap"] or 0))
    rank = {s["code"]: i for i, s in enumerate(stocks)}
    by_sector, by_market = {}, {}
    for s in stocks:
        by_market.setdefault(s["market"], []).append(s)
        if s["sector"]:
            by_sector.setdefault(s["sector"], []).append(s)

    urls = [("/", "1.0"), ("/ai/", "0.9"), ("/market/kospi/", "0.8"), ("/market/kosdaq/", "0.8"), ("/privacy/", "0.2")]

    # 종목 페이지 (한 종목에서 문제가 생겨도 나머지는 계속 생성)
    skipped = []
    for s in stocks:
        peers = []
        if s["sector"] and len(by_sector[s["sector"]]) > 1:
            peers = [p for p in by_sector[s["sector"]] if p["code"] != s["code"]][:8]
        if len(peers) < 8:
            mk = by_market[s["market"]]
            i = mk.index(s)
            near = mk[max(0, i - 6): i] + mk[i + 1: i + 7]
            peers += [p for p in near if p not in peers][: 8 - len(peers)]
        try:
            s["comment"] = ai_comment(s) if CFG["features"].get("comment", True) else None
            write(f"stock/{s['code']}/index.html", "stock.html", s=s, peers=peers, guide=number_guide(s, len(stocks)),
                  summary=summary(s), faqs=faqs(s), rank=rank[s["code"]] + 1, total=len(stocks),
                  sector_slug=slug(s["sector"]) if s["sector"] and len(by_sector.get(s["sector"], [])) >= 3 else None)
            urls.append((f"/stock/{s['code']}/", "0.7"))
        except Exception as e:
            skipped.append(s["code"])
            log("페이지 생성 건너뜀", s["code"], s["name"], repr(e)[:120])

    # 업종 페이지 (3종목 이상)
    sectors = sorted([(k, v) for k, v in by_sector.items() if len(v) >= 3], key=lambda kv: -len(kv[1]))
    for name, lst in sectors:
        write(f"sector/{slug(name)}/index.html", "list.html", title=f"{name} 관련주", heading=f"{name} 업종 종목",
              desc=f"{name} 업종 {len(lst)}개 종목의 {base_date} 주가, 등락률, 시가총액을 한눈에 확인하세요.",
              items=lst, path=f"/sector/{slug(name)}/")
        urls.append((f"/sector/{slug(name)}/", "0.6"))

    # 주식 용어사전 (주식새싹 고유)
    today_term = None
    if GLOSSARY["terms"]:
        terms = GLOSSARY["terms"]
        for t in terms:
            same = [x for x in terms if x["cat"] == t["cat"] and x["slug"] != t["slug"]]
            ex = glossary_example(t["ex"], stocks, base_date) if t.get("ex") else None
            write(f"glossary/{t['slug']}/index.html", "glossary.html", t=t, ex=ex, related=same[:8],
                  categories=GLOSSARY["categories"])
            urls.append((f"/glossary/{t['slug']}/", "0.7"))
        groups = [(c, [t for t in terms if t["cat"] == c]) for c in GLOSSARY["categories"]]
        write("glossary/index.html", "glossary_list.html", groups=groups, n=len(terms))
        urls.insert(1, ("/glossary/", "0.9"))
        d0 = datetime.strptime(base_date, "%Y-%m-%d").date()
        today_term = terms[d0.toordinal() % len(terms)]

    # 시장 목록
    for m in ("KOSPI", "KOSDAQ"):
        lst = by_market.get(m, [])
        name = "코스피" if m == "KOSPI" else "코스닥"
        write(f"market/{m.lower()}/index.html", "list.html", title=f"{name} 전 종목 시세", heading=f"{name} 전 종목",
              desc=f"{name} 상장 {len(lst)}개 종목의 {base_date} 종가, 등락률, 시가총액 순위.",
              items=lst, path=f"/market/{m.lower()}/")

    # 증시 리포트 (매일 쌓이는 글)
    posts = load_posts()
    by_date = {}
    for p in posts:
        by_date.setdefault(p["date"], []).append(p)
    for p in posts:
        full, short = _kdate(p["date"])
        same_day = [x for x in by_date[p["date"]] if x["slug"] != p["slug"]][:12]
        write(f"report/{p['date']}/{p['slug']}/index.html", "post.html", p=p, date_full=full, related=same_day)
        urls.append((f"/report/{p['date']}/{p['slug']}/", "0.6"))
    dates = sorted(by_date, reverse=True)
    for d in dates:
        full, short = _kdate(d)
        write(f"report/{d}/index.html", "report_list.html", title=f"{full} 증시 리포트", path=f"/report/{d}/",
              heading=f"{full} 증시 리포트", groups=[(d, full, by_date[d])], dates=dates[:60])
        urls.append((f"/report/{d}/", "0.5"))
    if dates:
        write("report/index.html", "report_list.html", title="증시 리포트 — 매일 장 마감 후 자동 발행", path="/report/",
              heading="증시 리포트", groups=[(d, _kdate(d)[0], by_date[d]) for d in dates[:3]], dates=dates[:60])
        urls.append(("/report/", "0.8"))
    today_posts = by_date.get(dates[0], []) if dates else []

    # 메인
    def top(key, rev=True, n=10, flt=None):
        pool = [s for s in stocks if s[key] is not None and (flt is None or flt(s))]
        return sorted(pool, key=lambda s: s[key], reverse=rev)[:n]
    liquid = lambda s: s["amount"] >= 1e9
    ai_pool = [s for s in stocks if s["ai"].get("p") is not None and liquid(s)]
    ai_up = sorted(ai_pool, key=lambda s: -s["ai"]["p"])[:10]
    ai_down = sorted(ai_pool, key=lambda s: s["ai"]["p"])[:10]
    # 메인 '오늘의 주요 종목 뉴스': 시총 상위 종목 뉴스를 모아 최신순
    top_news, seen = [], set()
    for st in stocks[:40]:
        for n in st.get("news") or []:
            k = n["title"][:30]
            if k in seen:
                continue
            seen.add(k)
            top_news.append({**n, "code": st["code"], "name": st["name"]})
    top_news = sorted(top_news, key=lambda x: -x.get("ts", 0))[:15]
    write("index.html", "index.html", top_news=top_news,
          gainers=top("chg", flt=liquid), losers=top("chg", rev=False, flt=liquid),
          amount=top("amount"), bigcaps=stocks[:10], sectors=sectors[:24], count=len(stocks),
          ai_up=ai_up, ai_down=ai_down, today_posts=today_posts, today_term=today_term, checklist=CHECKLIST)
    write("ai/index.html", "ai.html", ai_up=ai_up, ai_down=ai_down, count=len(stocks))

    write("privacy/index.html", "privacy.html")
    write("404.html", "404.html")

    # 검색용 목록, 사이트맵, robots
    (OUT / "stocks.json").write_text(json.dumps([[s["code"], s["name"], s["market"], s["close"], round(s["chg"] or 0, 2),
                    round(s["ai"]["p"], 3) if s["ai"].get("p") is not None else None,
                    safe_round(s["ai"]["lo"]), safe_round(s["ai"]["hi"])] for s in stocks], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>{site_url}{u}</loc><lastmod>{base_date}</lastmod><priority>{p}</priority></url>" for u, p in urls]
    sm.append("</urlset>")
    (OUT / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site_url}/sitemap.xml\n", encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    if skipped:
        log(f"건너뛴 종목 {len(skipped)}개: {', '.join(skipped[:20])}")
    log(f"완료: 종목 {len(stocks)}개, 업종 {len(sectors)}개, 리포트 {len(posts)}개(누적), 총 {len(urls)}개 URL → {OUT}")


# ════════════════════════ 주식 용어사전 (주식새싹 고유 기능) ════════════════════════
# glossary.json 의 용어마다 /glossary/영문이름/ 페이지를 만들고,
# 관련 있는 용어에는 '오늘의 실제 예시'(그날 시세로 계산)를 붙입니다.
# 종목 페이지에는 '이 숫자는 무슨 뜻?' 풀이 박스를 넣습니다.

GLOSSARY = {"terms": [], "categories": [], "by_slug": {}}


def load_glossary():
    for p in (ROOT / "glossary.json", ROOT / "data" / "glossary.json"):
        if p.exists():
            g = json.loads(p.read_text(encoding="utf-8"))
            GLOSSARY["terms"] = g.get("terms", [])
            GLOSSARY["categories"] = g.get("categories", [])
            GLOSSARY["by_slug"] = {t["slug"]: t for t in GLOSSARY["terms"]}
            return
    log("glossary.json 없음 — 용어사전 생략")


def term_link(slug):
    t = GLOSSARY["by_slug"].get(slug)
    return {"slug": slug, "term": t["term"]} if t else None


def glossary_example(kind, stocks, base_date):
    """용어별 '오늘의 실제 예시' — 그날 시세로 계산"""
    today = [s for s in stocks if s["date"] == base_date and s["chg"] is not None]
    if not today:
        return None
    _, short = _kdate(base_date)
    liquid = [s for s in today if s["amount"] >= 5e8] or today
    big = sorted(today, key=lambda s: -(s["marcap"] or 0))
    R = lambda xs, f: [{"s": x, "v": f(x)} for x in xs]
    if kind == "market":
        lines = []
        for m, nm in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
            xs = [s for s in today if s["market"] == m]
            if xs:
                up, dn = sum(s["chg"] > 0 for s in xs), sum(s["chg"] < 0 for s in xs)
                lines.append(f"{short} {nm}에서는 {len(xs):,}개 종목 중 {up:,}개가 오르고 {dn:,}개가 내렸어요.")
        return {"title": f"{short} 시장 분위기", "lines": lines, "rows": [], "vlabel": ""}
    if kind == "gainers":
        xs = sorted(liquid, key=lambda s: -s["chg"])[:5]
        return {"title": f"{short} 가장 많이 오른 종목", "lines": [f"{xs[0]['name']}는 전날 종가 {fmt_price(xs[0]['prev'])}원에서 오늘 {fmt_price(xs[0]['close'])}원이 되어 등락률이 {fmt_pct(xs[0]['chg'])}예요."],
                "rows": R(xs, lambda s: fmt_pct(s["chg"])), "vlabel": "등락률"}
    if kind == "limit":
        xs = [s for s in today if s["chg"] >= 29.5]
        if xs:
            return {"title": f"{short} 상한가 종목", "lines": [f"오늘 상한가(+30% 가까이)에 도달한 종목은 {len(xs)}개예요."], "rows": R(xs[:8], lambda s: fmt_pct(s["chg"])), "vlabel": "등락률"}
        top = max(liquid, key=lambda s: s["chg"])
        return {"title": f"{short} 상한가 종목", "lines": [f"오늘 상한가 종목은 없었어요. 가장 많이 오른 종목은 {top['name']}({fmt_pct(top['chg'])})예요."], "rows": [], "vlabel": ""}
    if kind == "hi52":
        allx = [s for s in liquid if s["from_hi"] is not None and s["from_hi"] > -1]
        xs = sorted(allx, key=lambda s: -s["chg"])[:6]
        return {"title": f"{short} 52주 최고가 근처 종목", "lines": [f"오늘 종가가 최근 1년 최고가의 1% 안에 있는 종목은 {len(allx)}개예요." + (" 그중 6개만 보여드려요." if len(allx) > 6 else "")] if xs else ["오늘은 52주 최고가 근처에서 끝난 종목이 거의 없었어요."],
                "rows": R(xs, lambda s: fmt_price(s["hi52"]) + "원"), "vlabel": "52주 최고가"}
    if kind == "lo52":
        xs = sorted([s for s in liquid if s["from_lo"] is not None and s["from_lo"] < 1], key=lambda s: s["chg"])[:6]
        return {"title": f"{short} 52주 최저가 근처 종목", "lines": [f"오늘 종가가 최근 1년 최저가의 1% 안에 있는 종목들이에요."] if xs else ["오늘은 52주 최저가 근처에서 끝난 종목이 거의 없었어요."],
                "rows": R(xs, lambda s: fmt_price(s["lo52"]) + "원"), "vlabel": "52주 최저가"}
    if kind == "volume":
        xs = sorted([s for s in liquid if s["vol_ratio"]], key=lambda s: -s["vol_ratio"])[:5]
        return {"title": f"{short} 평소보다 거래가 많았던 종목", "lines": [f"{xs[0]['name']}는 오늘 {xs[0]['volume']:,}주가 거래돼 평소(최근 20일 평균)의 {xs[0]['vol_ratio']:.1f}배였어요."] if xs else [],
                "rows": R(xs, lambda s: f"{s['vol_ratio']:.1f}배"), "vlabel": "평소 대비"}
    if kind == "amount":
        xs = sorted(today, key=lambda s: -s["amount"])[:5]
        return {"title": f"{short} 거래대금이 가장 많았던 종목", "lines": [f"오늘 돈이 가장 많이 오간 종목은 {xs[0]['name']}로 약 {fmt_won(xs[0]['amount'])}이 거래됐어요."],
                "rows": R(xs, lambda s: fmt_won(s["amount"])), "vlabel": "거래대금"}
    if kind == "marcap":
        xs = big[:5]
        return {"title": f"{short} 시가총액 상위 종목", "lines": [f"{xs[0]['name']}의 시가총액은 약 {fmt_won(xs[0]['marcap'])}이에요."] if xs[0]["marcap"] else [],
                "rows": R(xs, lambda s: fmt_won(s["marcap"])), "vlabel": "시가총액"}
    if kind == "ma":
        s = next((x for x in big if x.get("ma20") and x.get("ma60")), None)
        if not s:
            return None
        pos = "위" if s["close"] >= s["ma20"] else "아래"
        return {"title": f"{short} 예시: {s['name']}", "lines": [
            f"{s['name']}의 오늘 종가는 {fmt_price(s['close'])}원, 20일 이동평균은 {fmt_price(s['ma20'])}원, 60일 이동평균은 {fmt_price(s['ma60'])}원이에요.",
            f"지금 주가는 20일 평균보다 {pos}에 있어요."], "rows": [], "vlabel": "", "stock": s}
    if kind == "rsi":
        xs = [s for s in liquid if s.get("rsi") is not None]
        if not xs:
            return None
        hi_, lo_ = sorted(xs, key=lambda s: -s["rsi"])[:3], sorted(xs, key=lambda s: s["rsi"])[:3]
        return {"title": f"{short} RSI 높은 종목·낮은 종목", "lines": [f"RSI가 가장 높은 종목은 {hi_[0]['name']}({hi_[0]['rsi']:.0f}), 가장 낮은 종목은 {lo_[0]['name']}({lo_[0]['rsi']:.0f})예요."],
                "rows": R(hi_ + lo_, lambda s: f"{s['rsi']:.0f}"), "vlabel": "RSI"}
    if kind == "volat":
        xs = [s for s in big[:100] if s.get("volat") is not None]
        if not xs:
            return None
        lo_, hi_ = sorted(xs, key=lambda s: s["volat"])[:3], sorted(xs, key=lambda s: -s["volat"])[:3]
        return {"title": f"{short} 대형주 중 변동성 낮은·높은 종목", "lines": [f"시가총액 상위 100개 중 가장 차분한 종목은 {lo_[0]['name']}(연 {lo_[0]['volat']:.0f}%), 가장 많이 출렁이는 종목은 {hi_[0]['name']}(연 {hi_[0]['volat']:.0f}%)예요."],
                "rows": R(lo_ + hi_, lambda s: f"연 {s['volat']:.0f}%"), "vlabel": "변동성"}
    if kind == "returns":
        s = big[0]
        return {"title": f"{short} 예시: {s['name']}", "lines": [f"{s['name']}의 기간 수익률은 1주 {fmt_pct(s['r1w'])}, 1개월 {fmt_pct(s['r1m'])}, 3개월 {fmt_pct(s['r3m'])}예요."],
                "rows": [], "vlabel": "", "stock": s}
    return None


def number_guide(s, total):
    """종목 페이지 '이 숫자는 무슨 뜻?' — 실제 숫자 + 쉬운 풀이 + 용어사전 링크"""
    nm = s["name"]
    G = []
    if s["chg"] is not None:
        G.append(("등락률", fmt_pct(s["chg"]), f"어제 종가 {fmt_price(s['prev'])}원보다 오늘 {'오른' if s['chg'] >= 0 else '내린'} 비율이에요.", "price-change"))
    if s["marcap"]:
        G.append(("시가총액", fmt_won(s["marcap"]), f"주가 × 주식 수, 시장이 매긴 {nm} 전체의 가격이에요.", "market-cap"))
    if s["vol_ratio"]:
        G.append(("거래량", f"{s['volume']:,}주", f"오늘 사고팔린 주식 수예요. 평소(최근 20일 평균)의 {s['vol_ratio']:.1f}배예요.", "volume"))
    G.append(("52주 최고·최저", f"{fmt_price(s['hi52'])} / {fmt_price(s['lo52'])}", "최근 1년 동안 가장 높았던 가격과 가장 낮았던 가격이에요.", "52-week-high"))
    if s.get("ma20"):
        G.append(("20일 평균", f"{fmt_price(s['ma20'])}원", f"최근 20거래일 종가의 평균(이동평균선)이에요. 지금 주가가 이보다 {'위' if s['close'] >= s['ma20'] else '아래'}에 있어요.", "moving-average"))
    if s.get("rsi") is not None:
        lv = "과열 쪽" if s["rsi"] >= 70 else "과매도 쪽" if s["rsi"] <= 30 else "보통"
        G.append(("RSI", f"{s['rsi']:.0f}", f"최근 오른 힘과 내린 힘을 0~100으로 나타낸 값이에요. 지금은 '{lv}'이에요.", "rsi"))
    if s.get("volat") is not None:
        G.append(("변동성", f"연 {s['volat']:.0f}%", "주가가 얼마나 크게 출렁이는지예요. 숫자가 클수록 많이 출렁여요.", "volatility"))
    return [{"label": a, "value": b, "desc": c, "slug": d if d in GLOSSARY["by_slug"] else None} for a, b, c, d in G]


CHECKLIST = [
    ("잃어도 생활에 지장 없는 돈으로 시작하기", "risk-tolerance"),
    ("비상금(몇 달 치 생활비)은 따로 떼어 두기", "emergency-fund"),
    ("처음엔 지정가 주문으로 사고팔기", "limit-order"),
    ("한 종목에 몰빵하지 않고 나눠 담기", "diversification"),
    ("한 번에 다 사지 말고 나눠서 사기", "dollar-cost-averaging"),
    ("사기 전에 '얼마에 손절할지' 정해 두기", "stop-loss"),
    ("급등주 뒤늦게 따라 사지 않기", "chasing"),
    ("빚(신용거래)으로 투자하지 않기", "margin-loan"),
    ("소문보다 공시를 먼저 확인하기", "disclosure"),
]


# ════════════════════════ 7. 매일 자동 리포트 글 ════════════════════════
# 거래일마다 실제 데이터로 리포트 글을 만들어 posts/날짜/글.json 으로 저장하고,
# 저장된 글은 지우지 않고 쌓아서 /report/ 아래 페이지로 계속 보여줍니다.

POSTS_DIR = ROOT / "posts"
MAX_SECTOR_POSTS = 60


def _row(s, extra=""):
    return {"code": s["code"], "name": s["name"], "market": s["market"],
            "close": s["close"], "chg": round(s["chg"] or 0, 2), "extra": extra}


def _kdate(d):
    y, m, dd = d.split("-")
    return f"{int(y)}년 {int(m)}월 {int(dd)}일", f"{int(m)}월 {int(dd)}일"


def make_posts(stocks, base_date):
    today = [s for s in stocks if s["date"] == base_date and s["chg"] is not None]
    if len(today) < 20:
        return []
    full, short = _kdate(base_date)
    liquid = [s for s in today if s["amount"] >= 5e8]
    posts = []

    def add(slug, kind, title, desc, intro, tables, tags):
        posts.append({"date": base_date, "slug": slug, "kind": kind, "title": title, "desc": desc,
                      "intro": [x for x in intro if x], "tables": tables, "tags": tags})

    def name_list(xs, k=3):
        return ", ".join(f"{x['name']}({fmt_pct(x['chg'])})" for x in xs[:k])

    # 1) 시장 마감 요약
    mk = {}
    for m in ("KOSPI", "KOSDAQ"):
        xs = [s for s in today if s["market"] == m]
        if not xs:
            continue
        chg = sorted(s["chg"] for s in xs)
        mk[m] = {"n": len(xs), "up": sum(c > 0 for c in chg), "down": sum(c < 0 for c in chg),
                 "med": chg[len(chg) // 2], "amt": sum(s["amount"] for s in xs)}
    gain = sorted(liquid, key=lambda s: -s["chg"])
    lose = sorted(liquid, key=lambda s: s["chg"])
    amt = sorted(today, key=lambda s: -s["amount"])
    intro = []
    for m, nm in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        if m in mk:
            v = mk[m]
            mood = "오른 종목이 더 많았습니다" if v["up"] > v["down"] else "내린 종목이 더 많았습니다" if v["down"] > v["up"] else "오른 종목과 내린 종목 수가 비슷했습니다"
            intro.append(f"{short} {nm}에서는 {v['n']:,}개 종목 중 {v['up']:,}개가 오르고 {v['down']:,}개가 내려 {mood}. "
                         f"종목들의 중간 성적(중앙값)은 {fmt_pct(v['med'])}, 하루 동안 오간 돈(거래대금)은 {fmt_won(v['amt'])}입니다.")
    intro.append(f"거래대금(사고판 금액) 5억원 이상 종목 가운데 가장 많이 오른 종목은 {name_list(gain)}이고, 가장 많이 내린 종목은 {name_list(lose)}입니다.")
    intro.append(f"오늘 돈이 가장 많이 오간 종목은 {amt[0]['name']}({fmt_won(amt[0]['amount'])})입니다.")
    intro.append("※ 등락률은 어제 종가와 비교해 몇 % 올랐는지·내렸는지를 뜻합니다. 모르는 용어는 용어사전에서 쉽게 찾아볼 수 있어요.")
    add("market-summary", "summary", f"{full} 오늘 주식시장 쉽게 정리 — 오른 종목·내린 종목·돈이 몰린 종목",
        f"{short} 코스피·코스닥 마감 결과. 상승·하락 종목 수, 상승률·하락률 상위, 거래대금 상위 종목을 정리했습니다.",
        intro,
        [{"title": "상승률 상위 10", "extra": "거래대금", "rows": [_row(s, fmt_won(s["amount"])) for s in gain[:10]]},
         {"title": "하락률 상위 10", "extra": "거래대금", "rows": [_row(s, fmt_won(s["amount"])) for s in lose[:10]]},
         {"title": "거래대금 상위 10", "extra": "거래대금", "rows": [_row(s, fmt_won(s["amount"])) for s in amt[:10]]}],
        ["증시 마감", "코스피", "코스닥"])

    # 2) 상승률·하락률 TOP 30
    if gain:
        add("top-gainers", "rank", f"{full} 오늘 가장 많이 오른 주식 30개 (상승률 순위)",
            f"{short} 코스피·코스닥 상승률 상위 30개 종목. 1위 {gain[0]['name']} {fmt_pct(gain[0]['chg'])}.",
            [f"{short} 거래대금 5억원 이상 종목 중 상승률 1위는 {gain[0]['name']}로 {fmt_pct(gain[0]['chg'])} 올랐습니다.",
             f"상위 30개 종목의 평균 상승률은 {fmt_pct(sum(s['chg'] for s in gain[:30]) / len(gain[:30]))}입니다."],
            [{"title": "상승률 TOP 30", "extra": "거래대금", "rows": [_row(s, fmt_won(s["amount"])) for s in gain[:30]]}],
            ["상승률 순위", "급등주"])
        add("top-losers", "rank", f"{full} 오늘 가장 많이 내린 주식 30개 (하락률 순위)",
            f"{short} 코스피·코스닥 하락률 상위 30개 종목. 1위 {lose[0]['name']} {fmt_pct(lose[0]['chg'])}.",
            [f"{short} 거래대금 5억원 이상 종목 중 가장 많이 내린 종목은 {lose[0]['name']}({fmt_pct(lose[0]['chg'])})입니다."],
            [{"title": "하락률 TOP 30", "extra": "거래대금", "rows": [_row(s, fmt_won(s["amount"])) for s in lose[:30]]}],
            ["하락률 순위", "급락주"])

    # 3) 거래량 급증
    surge = sorted([s for s in liquid if (s["vol_ratio"] or 0) >= 2], key=lambda s: -s["vol_ratio"])[:30]
    if len(surge) >= 5:
        add("volume-surge", "rank", f"{full} 거래량 급증 종목 — 평소보다 거래가 몰린 주식 {len(surge)}개",
            f"{short} 최근 20일 평균보다 거래량이 2배 이상 늘어난 종목. 1위 {surge[0]['name']} {surge[0]['vol_ratio']:.1f}배.",
            [f"{short} 거래량이 최근 20거래일 평균의 2배를 넘은 종목은 거래대금 5억원 이상 기준 {len(surge)}개입니다.",
             f"가장 크게 늘어난 종목은 {surge[0]['name']}로 평소의 {surge[0]['vol_ratio']:.1f}배가 거래됐고, 주가는 {fmt_pct(surge[0]['chg'])} 움직였습니다."],
            [{"title": "거래량 급증 순위", "extra": "평소 대비", "rows": [_row(s, f"{s['vol_ratio']:.1f}배") for s in surge]}],
            ["거래량 급증", "수급"])

    # 4) 52주 신고가·신저가 근접
    hi = sorted([s for s in liquid if s["from_hi"] is not None and s["from_hi"] > -1], key=lambda s: -s["chg"])[:30]
    if len(hi) >= 3:
        add("new-high", "rank", f"{full} 52주 신고가 근접 종목 {len(hi)}개",
            f"{short} 52주 최고가 부근(1% 이내)에서 거래를 마친 종목. {name_list(hi, 2)} 등.",
            [f"{short} 종가가 52주 최고가의 1% 이내에 있는 종목은 {len(hi)}개입니다.",
             f"이 중 당일 상승률이 높은 종목은 {name_list(hi)}입니다."],
            [{"title": "52주 신고가 근접", "extra": "52주 최고가", "rows": [_row(s, fmt_price(s["hi52"])) for s in hi]}],
            ["52주 신고가", "신고가"])
    lo = sorted([s for s in liquid if s["from_lo"] is not None and s["from_lo"] < 1], key=lambda s: s["chg"])[:30]
    if len(lo) >= 3:
        add("new-low", "rank", f"{full} 52주 신저가 근접 종목 {len(lo)}개",
            f"{short} 52주 최저가 부근(1% 이내)에서 거래를 마친 종목. {name_list(lo, 2)} 등.",
            [f"{short} 종가가 52주 최저가의 1% 이내에 있는 종목은 {len(lo)}개입니다."],
            [{"title": "52주 신저가 근접", "extra": "52주 최저가", "rows": [_row(s, fmt_price(s["lo52"])) for s in lo]}],
            ["52주 신저가", "신저가"])

    # 5) AI 상승 확률 상위
    aip = sorted([s for s in liquid if s["ai"].get("p") is not None], key=lambda s: -s["ai"]["p"])[:20]
    if len(aip) >= 5:
        add("ai-top", "ai", f"{full} AI 주가예측 — 5거래일 상승 확률 상위 20 종목",
            f"{short} 기준 AI 모델이 계산한 5거래일 뒤 상승 확률 상위 종목. 1위 {aip[0]['name']} {aip[0]['ai']['p']*100:.0f}%.",
            [f"{CFG['site_name']} AI 모델이 {short} 종가까지의 데이터로 계산한 5거래일 뒤 상승 확률 상위 종목입니다.",
             f"1위는 {aip[0]['name']}({aip[0]['ai']['p']*100:.0f}%)입니다. AI 예측은 통계적 추정이며 매수 추천이 아닙니다."],
            [{"title": "AI 상승 확률 상위 20", "extra": "상승 확률", "rows": [_row(s, f"{s['ai']['p']*100:.0f}%") for s in aip]}],
            ["AI 주가예측", "주가 예측"])

    # 6) 업종별
    by = {}
    for s in today:
        if s["sector"]:
            by.setdefault(s["sector"], []).append(s)
    secs = sorted([(k, v) for k, v in by.items() if len(v) >= 5], key=lambda kv: -sum(x["amount"] for x in kv[1]))[:MAX_SECTOR_POSTS]
    for sec, xs in secs:
        xs = sorted(xs, key=lambda s: -s["chg"])
        avg = sum(s["chg"] for s in xs) / len(xs)
        up, down = sum(s["chg"] > 0 for s in xs), sum(s["chg"] < 0 for s in xs)
        lead = max(xs, key=lambda s: s["amount"])
        tone = ("강세" if avg >= 1 else "약보합" if avg < 0 and avg > -1 else "약세" if avg <= -1 else "강보합")
        add(f"sector-{slug(sec)}", "sector", f"{full} {sec} 관련주 주가 — 업종 {tone}, 평균 {fmt_pct(avg)}",
            f"{short} {sec} 업종 {len(xs)}개 종목 등락률. 상승 {up}개·하락 {down}개, 최고 상승 {xs[0]['name']} {fmt_pct(xs[0]['chg'])}.",
            [f"{short} {sec} 업종 {len(xs)}개 종목의 평균 등락률은 {fmt_pct(avg)}로 {tone}를 보였습니다. 상승 {up}개, 하락 {down}개입니다.",
             f"가장 많이 오른 종목은 {name_list(xs, 3)}이고, 가장 많이 내린 종목은 {xs[-1]['name']}({fmt_pct(xs[-1]['chg'])})입니다.",
             f"업종 내 거래대금이 가장 많은 종목은 {lead['name']}({fmt_won(lead['amount'])}, {fmt_pct(lead['chg'])})입니다."],
            [{"title": f"{sec} 관련주 등락률", "extra": "시가총액", "rows": [_row(s, fmt_won(s["marcap"])) for s in xs[:40]]}],
            [f"{sec} 관련주", sec])
    return posts


def save_posts(posts):
    for p in posts:
        d = POSTS_DIR / p["date"]
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{p['slug']}.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")


def load_posts():
    out = []
    if POSTS_DIR.is_dir():
        for f in sorted(POSTS_DIR.glob("*/*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception as e:
                log("리포트 읽기 실패", f, e)
    order = {"summary": 0, "ai": 1, "rank": 2, "sector": 3}
    out.sort(key=lambda p: (p["date"], -order.get(p["kind"], 9)), reverse=True)
    return out


# ════════════════════════ 6. AI 주가예측 모델 ════════════════════════
# 전 종목의 일봉에서 기술적 특징을 뽑아, "5거래일 뒤 종가가 오늘보다 높을까?"를
# 맞히도록 로지스틱 회귀(머신러닝) 모델을 매일 새로 학습합니다.
# 최근 60거래일은 학습에서 빼고 검증용으로 써서, 실제 정확도를 그대로 공개합니다.

HORIZON = 5
TEST_DAYS = 60
FEATS = ["r1", "r5", "r20", "r60", "vol20", "vr", "hi_dist", "lo_dist", "rsi", "gap20", "gap60", "range5"]
MODEL_INFO = {"report": None}


def features(df):
    c, v = df["Close"].astype(float), df["Volume"].astype(float)
    ret = c.pct_change()
    f = pd.DataFrame(index=df.index)
    for n in (1, 5, 20, 60):
        f[f"r{n}"] = c.pct_change(n)
    f["vol20"] = ret.rolling(20).std()
    f["vr"] = (v / v.rolling(20).mean().shift(1)).clip(0, 20).apply(lambda x: math.log1p(x) if pd.notna(x) else x)
    f["hi_dist"] = c / df["High"].rolling(250, min_periods=60).max() - 1
    f["lo_dist"] = c / df["Low"].rolling(250, min_periods=60).min() - 1
    gain, loss = ret.clip(lower=0).rolling(14).mean(), (-ret.clip(upper=0)).rolling(14).mean()
    f["rsi"] = (gain / (gain + loss)).fillna(0.5) - 0.5
    f["gap20"] = c / c.rolling(20).mean() - 1
    f["gap60"] = c / c.rolling(60).mean() - 1
    f["range5"] = (df["High"].rolling(5).max() / df["Low"].rolling(5).min() - 1)
    f["y"] = (c.shift(-HORIZON) > c).astype(float).where(c.shift(-HORIZON).notna())
    return f.replace([float("inf"), float("-inf")], pd.NA)


def train_model(dfs):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    frames = [features(d) for d in dfs if len(d) >= 80]
    data = pd.concat(frames).dropna(subset=FEATS + ["y"])
    dates = sorted(data.index.unique())
    if len(dates) < TEST_DAYS + 40 or len(data) < 2000:
        log("학습 데이터 부족 — AI 예측 생략")
        return None, None
    cut = dates[-TEST_DAYS]
    train, test = data[data.index < cut], data[data.index >= cut]
    if len(train) > 600_000:
        train = train.sample(600_000, random_state=0)
    clip = lambda X: X.astype(float).clip(-5, 5)
    model = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=300))
    model.fit(clip(train[FEATS]), train["y"])

    p = model.predict_proba(clip(test[FEATS]))[:, 1]
    y = test["y"].values
    acc = float(((p >= 0.5) == (y == 1)).mean())
    base = float(max(y.mean(), 1 - y.mean()))
    strong = (p >= 0.6) | (p <= 0.4)
    acc_strong = float(((p[strong] >= 0.5) == (y[strong] == 1)).mean()) if strong.sum() > 100 else None
    try:
        auc = float(roc_auc_score(y, p))
    except Exception:
        auc = None
    top = p >= np.quantile(p, 0.9)
    report = {
        "train_rows": int(len(train)), "test_rows": int(len(test)),
        "test_from": pd.Timestamp(cut).strftime("%Y-%m-%d"), "test_to": pd.Timestamp(dates[-1]).strftime("%Y-%m-%d"),
        "acc": acc, "base": base, "acc_strong": acc_strong, "strong_share": float(strong.mean()), "auc": auc,
        "top_up_rate": float(y[top].mean()), "all_up_rate": float(y.mean()),
    }
    log(f"AI 검증: 정확도 {acc:.1%} (기준 {base:.1%}), AUC {auc}, 상위10% 실제상승률 {report['top_up_rate']:.1%} vs 전체 {report['all_up_rate']:.1%}")

    # 검증까지 끝난 뒤, 최신 데이터까지 포함해 다시 학습해서 오늘 예측에 사용
    full = data if len(data) <= 600_000 else data.sample(600_000, random_state=0)
    model.fit(clip(full[FEATS]), full["y"])
    return model, report


def predict(model, df):
    c = float(df["Close"].iloc[-1])
    sd = df["Close"].pct_change().tail(20).std()
    sd = 0.0 if sd is None or not math.isfinite(float(sd)) else float(sd)
    band = sd * math.sqrt(HORIZON)
    out = {"lo": c * (1 - band), "hi": c * (1 + band), "band": band * 100, "p": None, "signal": None}
    if model is None or len(df) < 80:
        return out
    f = features(df).iloc[[-1]][FEATS]
    if f.isna().any(axis=None):
        return out
    p = float(model.predict_proba(f.astype(float).clip(-5, 5))[:, 1][0])
    out["p"] = p
    out["signal"] = "상승 우위" if p >= 0.55 else "하락 우위" if p <= 0.45 else "중립"
    out["cls"] = "up" if p >= 0.55 else "down" if p <= 0.45 else "flat"
    return out


# ════════════════════════ 실행 ════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.demo:
        lst, hist = demo_data()
        get = lambda code: hist.get(code)
    else:
        lst = get_listing()
        lst = lst[lst["market"].isin(CFG["markets"])]
        if CFG.get("exclude_name_regex"):
            lst = lst[~lst["name"].str.contains(CFG["exclude_name_regex"], regex=True, na=False)]
        if CFG.get("min_marcap"):
            lst = lst[lst["marcap"].fillna(0) >= CFG["min_marcap"]]
        # 업종: 네이버 업종 우선, 실패하면 KRX 업종 중 '소속부' 같은 값은 버림
        sec = get_sectors()
        old_sec = lst["sector"] if "sector" in lst.columns else pd.Series([None] * len(lst), index=lst.index)
        bad = old_sec.astype(str).str.contains(r"부$|소속부|관리종목|투자주의|nan", regex=True)
        lst["sector"] = [sec.get(c) or (o if not b else None) for c, o, b in zip(lst["code"], old_sec, bad)]
        lst = lst.sort_values("marcap", ascending=False)
        if args.limit:
            lst = lst.head(args.limit)
        start = (datetime.now(KST) - timedelta(days=CFG["history_days"])).strftime("%Y-%m-%d")
        get = lambda code: get_history(code, start)

    rows = lst.to_dict("records")
    log(f"{len(rows)}개 종목 시세 수집 시작")
    pairs, fail = [], 0
    with ThreadPoolExecutor(CFG.get("workers", 8)) as ex:
        futs = {ex.submit(get, r["code"]): r for r in rows}
        for i, f in enumerate(as_completed(futs), 1):
            r = futs[f]
            try:
                df = f.result()
                if df is not None and len(df) >= 2:
                    pairs.append((r, df))
                else:
                    fail += 1
            except Exception as e:
                fail += 1
                log("오류", r["code"], r["name"], e)
            if i % 300 == 0:
                log(f"  {i}/{len(rows)} (실패 {fail})")
    if not pairs:
        sys.exit("시세를 하나도 받지 못했습니다.")
    if fail > len(rows) * 0.3:
        sys.exit(f"실패가 너무 많아 배포를 중단합니다 ({fail}/{len(rows)}). 기존 사이트는 그대로 유지됩니다.")

    # AI 모델 학습 → 종목별 예측
    load_glossary()
    model, MODEL_INFO["report"] = train_model([df for _, df in pairs])
    stocks = []
    for r, df in pairs:
        try:
            s = compute(r, df)
            s["ai"] = predict(model, df)
            stocks.append(s)
        except Exception as e:
            log("계산 오류", r["code"], r["name"], e)

    # 기준일: 가장 많은 종목이 가진 마지막 날짜
    base_date = pd.Series([s["date"] for s in stocks]).mode()[0]
    stale = [s for s in stocks if s["date"] < base_date]
    if stale:
        log(f"거래정지 등으로 기준일과 다른 종목 {len(stale)}개 (그대로 표시)")
    try:
        if not args.demo and CFG["features"].get("news", True):
            get_news(stocks)
        elif os.environ.get("DEMO_NEWS"):
            for i, st in enumerate(sorted(stocks, key=lambda x: -(x["marcap"] or 0))[:6]):
                st["news"] = [{"title": f"{st['name']} 관련 샘플 기사 제목입니다 {j}", "source": "샘플일보", "link": "https://example.com/", "time": f"10.26 1{j}:0{i}", "ts": 100 * j + i} for j in range(3)]
    except Exception as e:
        log("뉴스 수집 실패 (사이트는 계속 생성):", repr(e)[:200])
    try:
        new_posts = make_posts(stocks, base_date) if CFG["features"].get("reports", True) else []
        save_posts(new_posts)
        log(f"오늘의 리포트 {len(new_posts)}개 생성 ({base_date})")
    except Exception as e:
        log("리포트 생성 실패 (사이트는 계속 생성):", repr(e)[:200])
    build(stocks, base_date)


if __name__ == "__main__":
    main()
