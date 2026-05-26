import requests
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

def send_email(subject, body):
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    to_addr = os.environ.get("EMAIL_TO")

    if not user or not password or not to_addr:
        print("错误：邮箱凭证未设置完整")
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
            "price": data["f43"] / 100 if data.get("f43") else "?",
            "change_pct": data["f170"] / 100 if data.get("f170") else "?",
            "amount": data["f48"] if data.get("f48") else "?"
        }
    except Exception as e:
        print(f"获取行情失败：{e}")
        return None

def get_fund_flow(secid):
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55",
        "lmt": 1,
        "klt": 1,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        lines = r.json()["data"]["klines"]
        if lines:
            parts = lines[0].split(",")
            return {
                "main_net_in": parts[2],
                "main_net_pct": parts[3]
            }
        else:
            return {"main_net_in": "无数据", "main_net_pct": "无数据"}
    except Exception as e:
        print(f"获取资金流向失败：{e}")
        return {"main_net_in": "获取失败", "main_net_pct": "获取失败"}

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
        print(f"获取公告失败：{e}")
        return ["(获取失败)"]

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
        print("错误：找不到stocks.txt文件")
    return stocks

def main():
    stocks = load_stocks()
    if not stocks:
        send_email("股票简报 - 错误", "股票列表为空")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    brief = f"📈 持仓全量简报 ({now})\n━━━━━━━━━━━━━━━━\n\n"

    for code, name, secid in stocks:
        brief += f"【{name}】({code})\n"

        basic = get_stock_basic(secid)
        if basic:
            pct = basic['change_pct']
            if isinstance(pct, (int, float)):
                if pct >= 2:
                    label = "🟢大涨"
                elif pct <= -2:
                    label = "🔴大跌"
                else:
                    label = ""
                brief += f"  💰 {basic['price']}元 | 涨跌：{pct}% {label}\n"
                brief += f"  📊 成交额：{basic['amount']}元\n"
            else:
                brief += f"  💰 行情获取异常\n"

        flow = get_fund_flow(secid)
        brief += f"  💵 主力资金：净流入{flow['main_net_in']}元 (占比{flow['main_net_pct']}%)\n"

        notices = get_notices(code)
        if notices and "(获取失败)" not in notices[0]:
            brief += f"  📰 最新公告：\n"
            for n in notices:
                brief += f"    • {n}\n"
        else:
            brief += f"  📰 最新公告：无\n"

        brief += "\n"

    brief += "━━━━━━━━━━━━━━━━\n数据来源：东方财富，仅供参考。"

    print(brief)
    send_email(f"📈 投资简报 {now}", brief)

if __name__ == "__main__":
    main()
