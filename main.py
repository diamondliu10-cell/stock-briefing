import requests
import smtplib
import os
import time
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

def get_secid(code):
    if code.startswith(("0", "3")):
        return f"0.{code}"
    else:
        return f"1.{code}"

# ------------------------------------------------------------
# 带重试的数据获取
# ------------------------------------------------------------
def robust_get(func, *args, retries=2, delay=10, **kwargs):
    for attempt in range(retries + 1):
        try:
            result = func(*args, **kwargs)
            if result is not None and (not isinstance(result, pd.DataFrame) or not result.empty):
                return result
        except Exception as e:
            print(f"  尝试{attempt+1}失败: {e}")
        if attempt < retries:
            print(f"  等待{delay}秒重试...")
            time.sleep(delay)
    return None

def get_kline_data(code, count=1):
    """获取日K线，返回DataFrame"""
    secid = get_secid(code)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62",
        "klt": 101,
        "fqt": 1,
        "end": "20500101",
        "lmt": count
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()["data"]
        if data is None or not data.get("klines"):
            return None
        klines = data["klines"]
        df = pd.DataFrame([k.split(",") for k in klines],
                          columns=["date","open","close","high","low","volume","amount",
                                   "amp","pct_chg","chg","turnover","main_net_in"])
        for col in ["open","close","high","low","volume","amount","turnover","main_net_in","pct_chg"]:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except:
        return None

def get_fund_flow_multi(code, days=20):
    """获取最近N日主力净流入（元）"""
    secid = get_secid(code)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56",
        "lmt": days,
        "klt": 101,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        klines = r.json()["data"]["klines"]
        if not klines:
            return []
        return [float(k.split(",")[1]) for k in klines if len(k.split(",")) > 1]
    except:
        return []

def get_news(stock_code):
    """获取个股近期新闻标题（尽量抓取更多）"""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "page_size": 10,
        "page_index": 1,
        "stock_list": stock_code,
        "f_node": 0,
        "s_node": 0
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        items = r.json()["data"]["list"]
        titles = [f"{item['notice_date'][:10]} {item['title']}" for item in items]
        return titles[:8]  # 最多8条
    except:
        return []

# ------------------------------------------------------------
# AI 分析（深度增强）
# ------------------------------------------------------------
def call_deepseek(prompt):
    if not DEEPSEEK_API_KEY:
        return "❌ 未配置DeepSeek API Key"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2000
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ AI调用失败：{str(e)}"

def generate_analysis(stocks_data):
    data_text = ""
    for sd in stocks_data:
        data_text += f"【{sd['name']}（{sd['code']}）】\n"
        if sd.get("price"):
            data_text += f"最新价：{sd['price']:.2f}元，涨跌幅：{sd.get('change_pct',0):+.2f}%\n"
        k = sd.get("yest_kline")
        if k:
            data_text += f"上一交易日：开{k['open']:.2f} 收{k['close']:.2f} 高{k['high']:.2f} 低{k['low']:.2f} "
            data_text += f"成交量{k['volume']:.0f}手 换手率{k['turnover']:.2f}%\n"
        flows = sd.get("fund_flows", {})
        data_text += f"主力资金净流入：5日{format_amount(flows.get('5d',0))}，10日{format_amount(flows.get('10d',0))}，20日{format_amount(flows.get('20d',0))}\n"
        news = sd.get("news", [])
        if news:
            data_text += "近期消息：\n"
            for n in news[:5]:
                data_text += f"  · {n}\n"
        else:
            data_text += "近期消息：无\n"
        if sd.get("profit_str"):
            data_text += f"持仓盈亏：{sd['profit_str']}\n"
        data_text += "\n"

    prompt = f"""你是一位资深投资分析师，请基于以下每只股票的真实数据，撰写一份专业投资简报。必须包含两个部分：

【一、⚠️ 风险提示】
- 用🔴标记存在明显风险的个股，说明风险原因（如技术破位、资金持续流出、重大利空消息等）。
- 若无明确风险，则写“今日无特别风险提示”。

【二、📊 个股深度分析】
对每只股票，结合日K线形态、主力资金多日流向、近期消息面，给出：
- 技术面评估（趋势、支撑压力、量价关系）
- 资金面评估（主力动向、多日净额变化）
- 消息面解读（判断利好/利空，引用消息标题）
- 操作建议（持有/加仓/减仓/观望）并简述理由
每只股票分析篇幅4-5行，观点明确，不模棱两可。

{data_text}"""
    return call_deepseek(prompt)

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
        # 带重试获取数据
        kline_df = robust_get(get_kline_data, code, count=1, retries=2, delay=10)
        fund_flows = robust_get(get_fund_flow_multi, code, days=20, retries=2, delay=10)
        news = robust_get(get_news, code, retries=1, delay=5) or []

        yest_kline = None
        price = None
        change_pct = None
        if kline_df is not None and not kline_df.empty:
            last = kline_df.iloc[-1]
            yest_kline = {
                "open": last["open"],
                "close": last["close"],
                "high": last["high"],
                "low": last["low"],
                "volume": last["volume"],
                "turnover": last["turnover"] if pd.notna(last["turnover"]) else 0.0
            }
            price = last["close"]
            change_pct = last["pct_chg"] if pd.notna(last["pct_chg"]) else 0.0

        # 资金汇总
        fund_summary = {}
        if fund_flows:
            if len(fund_flows) >= 5:
                fund_summary["5d"] = sum(fund_flows[-5:])
            else:
                fund_summary["5d"] = sum(fund_flows)
            if len(fund_flows) >= 10:
                fund_summary["10d"] = sum(fund_flows[-10:])
            else:
                fund_summary["10d"] = fund_summary["5d"]
            if len(fund_flows) >= 20:
                fund_summary["20d"] = sum(fund_flows)
            else:
                fund_summary["20d"] = fund_summary["10d"]

        profit_str = ""
        if price and cost:
            profit_pct = (price - cost) / cost * 100
            profit_str = f"成本{cost:.2f} 盈亏{profit_pct:+.1f}%"

        stocks_data.append({
            "name": name, "code": code,
            "price": price, "change_pct": change_pct,
            "yest_kline": yest_kline,
            "fund_flows": fund_summary,
            "news": news,
            "profit_str": profit_str
        })

    # 生成AI分析
    print("请求DeepSeek深度分析...")
    ai_analysis = generate_analysis(stocks_data)

    # 构建邮件正文（优化排版）
    body = f"📈 投资简报 | {now}\n"
    body += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    body += ai_analysis if ai_analysis else "AI分析生成失败"
    body += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    body += "【📋 今日关键数据速览】\n"
    for sd in stocks_data:
        body += f"\n🔹 {sd['name']}（{sd['code']}）\n"
        if sd.get("price"):
            body += f"   现价 {sd['price']:.2f}元 | 涨跌 {sd['change_pct']:+.2f}%"
            if sd.get("yest_kline"):
                body += f" | 换手率 {sd['yest_kline']['turnover']:.2f}%"
            body += "\n"
        flows = sd.get("fund_flows", {})
        body += f"   主力资金：5日 {format_amount(flows.get('5d',0))} | 10日 {format_amount(flows.get('10d',0))} | 20日 {format_amount(flows.get('20d',0))}\n"
        if sd.get("profit_str"):
            body += f"   持仓盈亏：{sd['profit_str']}\n"
    body += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据源：东方财富、新浪财经 | 分析：DeepSeek AI | 仅供参考，不构成投资建议。"

    send_email(f"📈 投资简报 {now}", body)
    print("简报发送完毕")

if __name__ == "__main__":
    main()
