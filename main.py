import requests
import smtplib
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ------------------------------------------------------------
# 基础配置
# ------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ------------------------------------------------------------
# 邮件发送
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# 数据抓取（修复资金流向字段）
# ------------------------------------------------------------
def get_stock_basic(secid):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f169,f170,f48",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json()["data"]
        return {
            "price": data["f43"] / 100 if data.get("f43") else None,
            "change_pct": data["f170"] / 100 if data.get("f170") else None,
            "amount": data["f48"] if data.get("f48") else None
        }
    except Exception as e:
        print(f"行情获取失败：{e}")
        return None

def get_fund_flow(secid):
    """获取主力资金流向，修正字段索引"""
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56",  # 增加了f56（主力净占比）
        "lmt": 1,
        "klt": 1,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        lines = r.json()["data"]["klines"]
        if lines:
            parts = lines[0].split(",")
            # 字段顺序：时间, 主力净流入, 小单净流入, 中单净流入, 大单净流入, 主力净占比
            main_net_in = parts[1] if len(parts) > 1 else "0"
            main_net_pct = parts[5] if len(parts) > 5 else "0"
            return {
                "main_net_in": float(main_net_in) if main_net_in != "0" else 0,
                "main_net_pct": float(main_net_pct) if main_net_pct != "0" else 0
            }
        else:
            return {"main_net_in": 0, "main_net_pct": 0}
    except Exception as e:
        print(f"资金流向获取失败：{e}")
        return {"main_net_in": 0, "main_net_pct": 0}

def get_notices(stock_code):
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "page_size": 3,
        "page_index": 1,
        "ann_type": "A",
        "stock_list": stock_code,
        "f_node": 1,
        "s_node": 0
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        items = r.json()["data"]["list"]
        return [f"{item['notice_date'][:10]} {item['title']}" for item in items]
    except Exception as e:
        print(f"公告获取失败：{e}")
        return []

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
                    secid = f"0.{code}" if code.startswith("0") or code.startswith("3") else f"1.{code}"
                    stocks.append((code, name, secid))
    except FileNotFoundError:
        print("stocks.txt 文件未找到")
    return stocks

# ------------------------------------------------------------
# AI 总结（DeepSeek V4-Pro）
# ------------------------------------------------------------
def generate_ai_summary(stocks_data):
    """将原始数据喂给DeepSeek，生成一针见血的总结"""
    if not DEEPSEEK_API_KEY:
        print("未设置DEEPSEEK_API_KEY，跳过AI总结")
        return None

    # 构建精简但信息完整的输入文本
    data_text = "以下是今日持仓股票的实时数据：\n"
    for sd in stocks_data:
        data_text += f"\n{sd['name']}({sd['code']})："
        if sd.get("price"):
            data_text += f"现价{sd['price']}元，涨跌幅{sd['change_pct']}%，成交额{sd['amount']}元；"
        data_text += f"主力净流入{sd['main_net_in']:.0f}元，占比{sd['main_net_pct']:.2f}%；"
        if sd.get("notices"):
            data_text += f"最新公告：{'；'.join(sd['notices'])}"
        else:
            data_text += "无最新公告"

    prompt = f"""你是一位INTJ型投资分析师，风格冷静、客观、一针见血，不提供情绪安慰，只说事实和逻辑。

根据以下每只股票的实时数据，为每只股票生成一个简短的"今日核心判断"（不超过50字）。
要求：
1. 直接指出最关键的变化或风险（例如资金连续流出、公告重大利好/利空等）。
2. 如果数据正常或平淡，就说"今日无异常"。
3. 重点标注🔴（风险）或🟢（积极），并注明原因。
4. 不要啰嗦，不要客套话。

{data_text}

请严格按以下格式输出（每只股票一行）：
比亚迪：🔴/🟢/➖ 核心判断...
恒生科技ETF：🔴/🟢/➖ 核心判断...
龙佰集团：🔴/🟢/➖ 核心判断...
半导体ETF：🔴/🟢/➖ 核心判断...

最后，在单独一行用一句话总结整体账户今日最需要关注的风险点。"""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",  # V4-Pro
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 600
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"AI总结调用失败：{e}")
        return None

# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def main():
    stocks = load_stocks()
    if not stocks:
        send_email("股票简报 - 错误", "股票列表为空")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    stocks_data = []

    for code, name, secid in stocks:
        basic = get_stock_basic(secid)
        flow = get_fund_flow(secid)
        notices = get_notices(code)
        stocks_data.append({
            "code": code,
            "name": name,
            "price": basic["price"] if basic else None,
            "change_pct": basic["change_pct"] if basic else None,
            "amount": basic["amount"] if basic else None,
            "main_net_in": flow["main_net_in"],
            "main_net_pct": flow["main_net_pct"],
            "notices": notices
        })

    # 尝试获取 AI 总结
    ai_summary = generate_ai_summary(stocks_data)

    # 构建邮件正文
    body = f"📈 持仓全量智能简报 ({now})\n"
    body += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if ai_summary:
        body += "【今日核心判断（AI生成）】\n"
        body += ai_summary + "\n\n"
        body += "━━━━━━━━━━━━━━━━━━━━\n"
        body += "【详细数据】\n"
    else:
        body += "（AI 总结暂时不可用，以下是基础数据）\n\n"

    for sd in stocks_data:
        body += f"\n【{sd['name']}】({sd['code']})\n"
        if sd.get("price"):
            pct = sd['change_pct']
            if pct is not None:
                if pct >= 2:
                    label = " 🟢大涨"
                elif pct <= -2:
                    label = " 🔴大跌"
                else:
                    label = ""
                body += f"  💰 现价 {sd['price']}元 | 涨跌 {pct}%{label}\n"
                body += f"  📊 成交额 {sd['amount']}元\n"
            else:
                body += f"  💰 行情获取异常\n"

        body += f"  💵 主力资金：净流入 {sd['main_net_in']:.0f} 元 (占比 {sd['main_net_pct']:.2f}%)\n"

        if sd.get("notices"):
            body += f"  📰 最新公告：\n"
            for n in sd['notices']:
                body += f"    • {n}\n"
        else:
            body += f"  📰 最新公告：无\n"

    body += "\n━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据来源：东方财富 | 分析：DeepSeek AI"

    print(body)
    send_email(f"📈 投资简报 {now}", body)

if __name__ == "__main__":
    main()
