import requests
import smtplib
import os
import re
import json
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
    stocks = []
    try:
        with open("stocks.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    stocks.append((parts[0].strip(), parts[1].strip()))
    except FileNotFoundError:
        print("stocks.txt不存在")
    return stocks

def format_amount(amount_yuan):
    if amount_yuan is None or amount_yuan == 0:
        return "0"
    yi = amount_yuan / 1e8
    if abs(yi) >= 0.01:
        return f"{yi:.2f}亿元"
    return f"{amount_yuan / 1e4:.0f}万元"

# ------------------------------------------------------------
# 可靠数据获取（新浪财经）
# ------------------------------------------------------------
def get_sina_code(code):
    """转换为新浪代码"""
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    else:
        return f"sz{code}"

def get_realtime_quote(code):
    """获取实时行情数据，基于新浪接口"""
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
        # 新浪数据格式：名称、今开、昨收、现价、最高、最低、... 成交额、... 日期、...
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
        print(f"新浪行情获取异常 {code}: {e}")
    return None

def get_kline_data(code, period="daily", count=60):
    """获取历史K线数据，基于新浪接口"""
    try:
        sina_code = get_sina_code(code)
        # 新浪历史数据接口
        url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen={count}"
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
        print(f"K线数据获取异常 {code}: {e}")
    return None

def compute_technical(df):
    """计算技术指标"""
    if df is None or df.empty:
        return "技术数据获取失败"
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values
    date = df.index[-1] if isinstance(df.index[-1], str) else str(df["day"].iloc[-1])

    last_close = closes[-1]
    last_open = df["open"].iloc[-1]
    last_high = highs[-1]
    last_low = lows[-1]
    last_vol = volumes[-1]

    change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) > 1 else 0

    # 均线
    ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else None
    ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else None
    ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else None

    # 量能
    if len(volumes) > 1:
        vol_change = (volumes[-1] - volumes[-2]) / volumes[-2] * 100
        vol_desc = "放量" if vol_change > 20 else ("缩量" if vol_change < -20 else "量平")
    else:
        vol_change, vol_desc = 0, "量平"

    # MACD
    dif, macd_val = None, None
    if len(closes) >= 26:
        ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().iloc[-1]
        ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().iloc[-1]
        dif = ema12 - ema26
        dea = pd.Series([dif]).ewm(span=9, adjust=False).mean().iloc[-1]
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

    status = []
    if ma5 and ma10 and ma20:
        if last_close > ma5 > ma10 > ma20:
            status.append("多头排列")
        elif last_close < ma5 < ma10 < ma20:
            status.append("空头排列")
        else:
            status.append("均线缠绕")
    if dif and macd_val:
        if dif > 0 and macd_val > 0:
            status.append("MACD红柱多头")
        elif dif < 0 and macd_val < 0:
            status.append("MACD绿柱空头")
    if rsi_val:
        if rsi_val > 70:
            status.append(f"RSI超买({rsi_val:.1f})")
        elif rsi_val < 30:
            status.append(f"RSI超卖({rsi_val:.1f})")
        else:
            status.append(f"RSI中性({rsi_val:.1f})")

    support = f"{min(lows[-20:]):.2f}" if len(lows) >= 20 else "?"
    resistance = f"{max(highs[-20:]):.2f}" if len(highs) >= 20 else "?"

    summary = f"日K：{date} | 开{last_open:.2f}/收{last_close:.2f} | 高{last_high:.2f}/低{last_low:.2f} | {vol_desc}({vol_change:+.1f}%)"
    if ma5:
        summary += f"\n  均线：MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}"
    summary += f"\n  状态：{'、'.join(status)}"
    summary += f"\n  支撑/压力：近20日低{support} / 高{resistance}"

    return summary

def get_intelligence(code):
    # 此部分因新浪接口限制，暂时保留，后期可接入新闻API
    return ["无相关预测情报"]

def get_hot_sectors():
    # 此部分暂时保留，后期可接入板块数据
    return "板块数据暂不可用"

def get_calendar():
    return "暂无重要事件"

# ------------------------------------------------------------
# AI 总结
# ------------------------------------------------------------
def generate_ai_summary(stocks_data, hot_sectors, calendar):
    if not DEEPSEEK_API_KEY:
        return "❌ 未设置 DEEPSEEK_API_KEY"

    data_text = f"【今日市场热点板块】\n  {hot_sectors}\n\n"
    data_text += f"【重要财经提醒】\n  {calendar}\n\n"
    data_text += "【持仓股票数据（含技术面、情报）】\n"

    for sd in stocks_data:
        data_text += f"\n{sd['name']}({sd['code']})：\n"
        if sd.get("price"):
            data_text += f"  现价{sd['price']}元，涨跌幅{sd['change_pct']}%"
        if sd.get("amount"):
            data_text += f"，成交额{format_amount(sd['amount'])}；\n"
        if sd.get("technical"):
            data_text += f"  技术面：{sd['technical']}\n"
        if sd.get("intel") and sd['intel'] != ["无相关预测情报"]:
            data_text += f"  🔍 预测情报：{'；'.join(sd['intel'])}\n"

    prompt = f"""你是一位INTJ型投资分析师。请结合所有数据，为每只股票生成专业判断。

要求：
1. 格式：[股票名]：🔴/🟢/➖ 核心分析... 关联动态：1. 动态一；2. 动态二
2. 必须引用技术面信号（如均线排列、MACD、RSI、量价关系）。
3. 最后以“整体风险：”总结组合风险。

{data_text}

请直接输出。"""

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1500
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=25)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ AI调用失败：{str(e)}"

# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def main():
    print(f"简报开始 - {beijing_now()}")
    stocks = load_stocks()
    if not stocks:
        send_email("股票简报 - 错误", "股票列表为空")
        return

    hot = get_hot_sectors()
    cal = get_calendar()

    data_list = []
    for code, name in stocks:
        print(f"处理：{name}({code})")
        quote = get_realtime_quote(code)
        kline_df = get_kline_data(code)
        technical = compute_technical(kline_df)
        intel = get_intelligence(code)

        data_list.append({
            "code": code, "name": name,
            "price": quote["price"] if quote else None,
            "change_pct": quote["change_pct"] if quote else None,
            "amount": quote["amount"] if quote else None,
            "technical": technical,
            "intel": intel
        })

    ai_summary = generate_ai_summary(data_list, hot, cal)

    now = beijing_now()
    body = f"📈 智能深度简报 ({now} 北京时间)\n"
    body += "━━━━━━━━━━━━━━━━━━━━\n\n"
    body += f"【🔥 市场热点板块】\n  {hot}\n\n"
    body += f"【📅 今日关注】\n  {cal}\n\n"

    if ai_summary and not ai_summary.startswith("❌"):
        body += "【🧠 AI核心判断】\n" + ai_summary + "\n\n"
    else:
        body += f"【⚠️ AI状态】\n{ai_summary or 'AI 返回为空'}\n\n"

    body += "━━━━━━━━━━━━━━━━━━━━\n【📋 详细数据】\n"

    for sd in data_list:
        body += f"\n【{sd['name']}】({sd['code']})\n"
        if sd.get("price"):
            pct = sd['change_pct']
            label = ""
            if pct is not None:
                if pct >= 2: label = " 🟢"
                elif pct <= -2: label = " 🔴"
            body += f"  💰 {sd['price']}元 | {pct}%{label}\n"
            if sd.get("amount"):
                body += f"  📊 成交 {format_amount(sd['amount'])}\n"
        body += f"  📈 技术：{sd.get('technical', '获取失败')}\n"

        if sd.get("intel") and sd['intel'] != ["无相关预测情报"]:
            body += f"  📰 情报：\n"
            for line in sd['intel']:
                body += f"    • {line}\n"

    body += "\n━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据源：新浪财经 | 分析：DeepSeek AI | 仅供参考，不构成投资建议。"

    send_email(f"📈 投资简报 {now}", body)
    print("简报发送完毕")

if __name__ == "__main__":
    main()
