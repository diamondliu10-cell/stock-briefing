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

# ------------------------------------------------------------
# 数据获取函数
# ------------------------------------------------------------
def get_secid(code):
    """获取东方财富secid"""
    if code.startswith(("0", "3")):
        return f"0.{code}"
    else:
        return f"1.{code}"

def get_kline_data(code, count=1):
    """获取日K线数据，返回DataFrame，包含前一日行情"""
    secid = get_secid(code)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62",
        "klt": 101,       # 日K
        "fqt": 1,         # 前复权
        "end": "20500101",
        "lmt": count
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()["data"]
        if data is None:
            return None
        klines = data["klines"]
        if not klines:
            return None
        df = pd.DataFrame([k.split(",") for k in klines],
                          columns=["date","open","close","high","low","volume","amount",
                                   "amp","pct_chg","chg","turnover","main_net_in"])
        for col in ["open","close","high","low","volume","amount","turnover","main_net_in","pct_chg"]:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except Exception as e:
        print(f"K线获取异常 {code}: {e}")
        return None

def get_fund_flow_multi(code, days=20):
    """获取最近N日主力资金净流入明细"""
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
            return None
        flows = []
        for k in klines:
            parts = k.split(",")
            if len(parts) >= 2:
                flows.append(float(parts[1]))  # 主力净流入
        return flows
    except Exception as e:
        print(f"资金流向获取异常 {code}: {e}")
        return None

def get_news(stock_code):
    """获取个股相关新闻标题"""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "page_size": 5,
        "page_index": 1,
        "stock_list": stock_code,
        "f_node": 0,    # 0 表示全部公告和资讯
        "s_node": 0
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()["data"]["list"]
        return [f"{item['notice_date'][:10]} {item['title']}" for item in data]
    except:
        return []

# ------------------------------------------------------------
# AI 分析生成
# ------------------------------------------------------------
def call_deepseek(prompt):
    if not DEEPSEEK_API_KEY:
        return "❌ 未配置DeepSeek API Key"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",  # 你最优质的对话模型
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1500
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ AI调用失败：{str(e)}"

def generate_full_brief(stocks_data):
    """将整理好的数据传给DeepSeek，生成结构化简报"""
    # 构建数据文本
    data_text = ""
    for sd in stocks_data:
        data_text += f"\n股票：{sd['name']}（{sd['code']}）\n"
        if sd.get("price"):
            data_text += f"最新价：{sd['price']}元，涨跌幅：{sd['change_pct']:+.2f}%\n"
        if sd.get("yest_kline"):
            k = sd["yest_kline"]
            data_text += f"上一交易日日K：开{k['open']:.2f} 收{k['close']:.2f} 高{k['high']:.2f} 低{k['low']:.2f} 成交量{k['volume']:.0f}手 换手率{k['turnover']:.2f}%\n"
        # 资金流向
        flows = sd.get("fund_flows", {})
        if flows:
            data_text += f"主力资金净流入：5日{format_amount(flows.get('5d',0))}，10日{format_amount(flows.get('10d',0))}，20日{format_amount(flows.get('20d',0))}\n"
        # 新闻
        if sd.get("news"):
            data_text += f"最新相关新闻：\n"
            for n in sd["news"]:
                data_text += f"  · {n}\n"
        else:
            data_text += "无相关新闻\n"

    prompt = f"""你是一位顶级投资分析师，请根据以下每只股票的真实数据，生成一份简练、结构化的投资简报。简报必须包含以下两个部分：

【一、风险提示】
- 对存在明显技术风险（如破位、资金持续流出）、重大利空消息的个股进行重点提示，用🔴标记。
- 若无明确风险，则说“今日无特别风险提示”。

【二、个股针对性分析】
- 对每只股票，结合日K线形态、主力资金多日流向、相关新闻，给出简洁的操作建议（如持有、减仓、观望等），并说明核心理由。
- 每只股票分析不超过4行。

数据如下：
{data_text}

请直接输出，不要额外解释。"""

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
        # 获取最近1根日K线（前一交易日）
        kline_df = get_kline_data(code, count=1)
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

        # 获取20日主力资金流向
        fund_flows_raw = get_fund_flow_multi(code, days=20)
        fund_summary = {}
        if fund_flows_raw and len(fund_flows_raw) >= 20:
            fund_summary["5d"] = sum(fund_flows_raw[-5:])
            fund_summary["10d"] = sum(fund_flows_raw[-10:])
            fund_summary["20d"] = sum(fund_flows_raw)
        elif fund_flows_raw:
            # 数据不足20日，有多少算多少
            fund_summary["5d"] = sum(fund_flows_raw[-5:]) if len(fund_flows_raw) >= 5 else sum(fund_flows_raw)
            fund_summary["10d"] = sum(fund_flows_raw[-10:]) if len(fund_flows_raw) >= 10 else sum(fund_flows_raw)
            fund_summary["20d"] = sum(fund_flows_raw)

        # 获取新闻
        news = get_news(code)

        # 盈亏
        profit_str = ""
        if price and cost:
            profit_pct = (price - cost) / cost * 100
            profit_str = f" | 成本{cost:.2f} 盈亏{profit_pct:+.1f}%"

        stocks_data.append({
            "name": name,
            "code": code,
            "price": price,
            "change_pct": change_pct,
            "yest_kline": yest_kline,
            "fund_flows": fund_summary,
            "news": news,
            "profit_str": profit_str
        })

    # 调用AI生成简报
    print("正在请求DeepSeek生成分析...")
    ai_brief = generate_full_brief(stocks_data)

    # 组装邮件
    body = f"📈 投资简报 | {now}\n"
    body += "━━━━━━━━━━━━━━━━━━━━━━\n"
    body += ai_brief if ai_brief else "AI分析生成失败，请检查日志"
    body += "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据源：东方财富 | 分析：DeepSeek AI | 仅供参考，不构成投资建议。"

    send_email(f"📈 投资简报 {now}", body)
    print("简报发送完毕")

if __name__ == "__main__":
    main()
