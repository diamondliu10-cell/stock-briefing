import requests
import smtplib
import os
import numpy as np
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

# ------------------------------------------------------------
# 基础配置
# ------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_now():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")

def send_email(subject, body):
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    to_addr = os.environ.get("EMAIL_TO")
    if not user or not password or not to_addr:
        print("邮件凭证缺失")
        return
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(user, password)
        server.sendmail(user, to_addr, msg.as_string())
        server.quit()
        print("邮件发送成功")
    except Exception as e:
        print(f"邮件发送失败：{e}")

def load_stocks():
    """读取stocks.txt，支持可选成本价"""
    stocks = []
    try:
        with open("stocks.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    code = parts[0].strip()
                    name = parts[1].strip()
                    cost = float(parts[2].strip()) if len(parts) >= 3 and parts[2].strip() else None
                    stocks.append((code, name, cost))
    except FileNotFoundError:
        print("stocks.txt不存在")
    return stocks

def format_amount(amount_yuan):
    if amount_yuan is None or amount_yuan == 0:
        return "0"
    yi = amount_yuan / 1e8
    if abs(yi) >= 0.01:
        return f"{yi:.2f}亿"
    wan = amount_yuan / 1e4
    return f"{wan:.0f}万"

def get_sina_code(code):
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    else:
        return f"sz{code}"

# ------------------------------------------------------------
# 数据获取
# ------------------------------------------------------------
def get_realtime_quote(code):
    """新浪实时行情"""
    try:
        sina_code = get_sina_code(code)
        url = f"https://hq.sinajs.cn/list={sina_code}"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
        resp = requests.get(url, headers=headers, timeout=5)
        resp.encoding = "gb2312"
        data_str = resp.text.split('"')[1]
        if not data_str:
            return None
        parts = data_str.split(",")
        if len(parts) < 30:
            return None
        return {
            "price": float(parts[3]),
            "change_pct": round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2),
            "high": float(parts[4]),
            "low": float(parts[5]),
            "amount": float(parts[9]) if len(parts) > 9 else 0.0,
            "volume": float(parts[8]) if len(parts) > 8 else 0.0,
            "open": float(parts[1]),
            "prev_close": float(parts[2]),
            "date": parts[30] if len(parts) > 30 else "?"
        }
    except Exception as e:
        print(f"行情获取异常 {code}: {e}")
    return None

def get_kline_data(code):
    """新浪历史日K"""
    try:
        sina_code = get_sina_code(code)
        url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen=60"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if not data:
            return None
        df = pd.DataFrame(data)
        df["close"] = pd.to_numeric(df["close"])
        df["high"] = pd.to_numeric(df["high"])
        df["low"] = pd.to_numeric(df["low"])
        df["volume"] = pd.to_numeric(df["volume"])
        df["open"] = pd.to_numeric(df["open"])
        return df
    except Exception as e:
        print(f"K线获取异常 {code}: {e}")
    return None

def compute_technical(df):
    """计算技术指标"""
    if df is None or df.empty:
        return None, None, None, "获取失败"
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values

    last_close = closes[-1]
    last_open = df["open"].iloc[-1]
    last_high = highs[-1]
    last_low = lows[-1]
    last_vol = volumes[-1]

    # 涨跌幅（相对前一交易日）
    change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) > 1 else 0

    # 均线
    ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else None
    ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else None
    ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else None

    # 量能变化
    if len(volumes) > 1:
        vol_change = (volumes[-1] - volumes[-2]) / volumes[-2] * 100
        vol_desc = "放量" if vol_change > 20 else ("缩量" if vol_change < -20 else "量平")
    else:
        vol_change = 0
        vol_desc = "量平"

    # MACD
    dif, macd_val = None, None
    if len(closes) >= 26:
        ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().iloc[-1]
        ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().iloc[-1]
        dif = ema12 - ema26
        dea = pd.Series([dif] * 9).ewm(span=9, adjust=False).mean().iloc[-1]  # 简化处理
        macd_val = (dif - dea) * 2

    # RSI
    rsi_val = None
    if len(closes) >= 15:
        delta = np.diff(closes[-15:])
        gain = np.sum(delta[delta > 0])
        loss = -np.sum(delta[delta < 0])
        if loss == 0:
            rsi_val = 100.0
        else:
            rsi_val = 100.0 - (100.0 / (1 + gain / loss))

    # 趋势判断
    trend = "→横盘"
    if ma5 and ma10 and ma20:
        if last_close > ma5 > ma10 > ma20:
            trend = "↑多头"
        elif last_close < ma5 < ma10 < ma20:
            trend = "↓空头"

    # 支撑/压力
    support = f"{min(lows[-20:]):.2f}" if len(lows) >= 20 else "?"
    resistance = f"{max(highs[-20:]):.2f}" if len(highs) >= 20 else "?"

    tech_summary = f"{trend} | MACD:{'红柱' if (dif and macd_val and dif > 0 and macd_val > 0) else '绿柱' if (dif and macd_val and dif < 0 and macd_val < 0) else '不明'} | RSI:{rsi_val:.0f}" if rsi_val else f"{trend} | RSI:?"

    # 详细技术字符串，留给AI分析用
    detail = f"趋势{trend}，"
    if ma5:
        detail += f"MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}，"
    detail += f"量能{vol_desc}({vol_change:+.1f}%)，"
    if rsi_val:
        detail += f"RSI={rsi_val:.1f}，"
    detail += f"支撑{support} 压力{resistance}"

    # 风险分类
    risk_flag = "➖"
    if "空头" in trend or (rsi_val and rsi_val < 30):
        risk_flag = "🔴"
    elif "多头" in trend and rsi_val and rsi_val > 70:
        risk_flag = "🟡"  # 超买风险
    elif "多头" in trend:
        risk_flag = "🟢"

    return risk_flag, tech_summary, detail, None  # 无错误

def get_intelligence(code):
    # 暂时保留，后续可接入新闻API
    return []

# ------------------------------------------------------------
# AI 总结（保留，生成顶部一句话风险判断）
# ------------------------------------------------------------
def generate_risk_summary(stocks_data):
    if not DEEPSEEK_API_KEY:
        return "AI未配置"
    # 构建简要数据
    data_text = ""
    for sd in stocks_data:
        data_text += f"{sd['name']}: 涨跌{sd['change_pct']}%, 趋势{sd['trend']}, 主力{format_amount(sd['amount'])}, 技术{sd['tech_detail']}\n"
    prompt = f"""根据以下持仓简况，用一句话（不超过40字）总结整体风险，并给出一个风险等级（低/中/高）。格式：🟢/🟡/🔴 风险等级 简要总结。
{data_text}
"""
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 80
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except:
        return "风险总结生成失败"

# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def main():
    print(f"简报开始 - {beijing_now()}")
    stocks = load_stocks()
    if not stocks:
        send_email("股票简报 - 错误", "股票列表为空")
        return

    now = beijing_now()
    stocks_data = []

    for code, name, cost in stocks:
        print(f"处理：{name}({code})")
        quote = get_realtime_quote(code)
        kline_df = get_kline_data(code)
        risk_flag, tech_summary, tech_detail, tech_error = compute_technical(kline_df)

        price = quote["price"] if quote else None
        change_pct = quote["change_pct"] if quote else None
        amount = quote["amount"] if quote else None

        # 计算盈亏
        profit_str = ""
        if price and cost:
            profit_pct = (price - cost) / cost * 100
            profit_str = f" | 成本{cost:.2f} 盈亏{profit_pct:+.1f}%"

        stocks_data.append({
            "name": name,
            "code": code,
            "price": price,
            "change_pct": change_pct,
            "amount": amount,
            "risk_flag": risk_flag,
            "tech_summary": tech_summary,
            "tech_detail": tech_detail,
            "profit_str": profit_str,
            "intel": get_intelligence(code)
        })

    # 获取整体风险总结
    risk_summary = generate_risk_summary(stocks_data)

    # 按风险分组排序：🔴 > 🟡 > 🟢 > ➖
    risk_order = {"🔴": 0, "🟡": 1, "🟢": 2, "➖": 3}
    stocks_data.sort(key=lambda x: risk_order.get(x["risk_flag"], 9))

    # 分组
    high_risk = [s for s in stocks_data if s["risk_flag"] == "🔴"]
    strong = [s for s in stocks_data if s["risk_flag"] == "🟢"]
    watch = [s for s in stocks_data if s["risk_flag"] in ("🟡", "➖")]

    # 构建邮件
    body = f"📈 投资简报 | {now}\n"
    body += "━━━━━━━━━━━━━━━━━━━━━━\n"
    body += f"{risk_summary}\n\n"

    # 高风险
    if high_risk:
        body += "━━━━━━━━━━━━━━━━━━━━━━\n🔴 高风险关注\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for s in high_risk:
            body += f"\n【{s['name']}】{s['price']}元 | {s['change_pct']:+.2f}%{s['profit_str']}\n"
            body += f"  趋势：{s['tech_summary']}\n"
            body += f"  资金：成交 {format_amount(s['amount'])}\n"
            for intel in s["intel"]:
                body += f"  ⚠️ {intel}\n"

    # 强势
    if strong:
        body += "\n━━━━━━━━━━━━━━━━━━━━━━\n🟢 强势持仓\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for s in strong:
            body += f"\n【{s['name']}】{s['price']}元 | {s['change_pct']:+.2f}%{s['profit_str']}\n"
            body += f"  趋势：{s['tech_summary']}\n"
            body += f"  资金：成交 {format_amount(s['amount'])}\n"

    # 观望
    if watch:
        body += "\n━━━━━━━━━━━━━━━━━━━━━━\n➖ 观望标的\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for s in watch:
            body += f"\n【{s['name']}】{s['price']}元 | {s['change_pct']:+.2f}%{s['profit_str']}\n"
            body += f"  趋势：{s['tech_summary']}\n"
            body += f"  资金：成交 {format_amount(s['amount'])}\n"

    body += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据源：新浪财经 | 分析：DeepSeek AI | 仅供参考，不构成投资建议。"

    send_email(f"📈 投资简报 {now}", body)
    print("简报发送完毕")

if __name__ == "__main__":
    main()
