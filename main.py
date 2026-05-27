import requests
import smtplib
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

# ------------------------------------------------------------
# 基础配置
# ------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
JUHE_API_KEY = os.environ.get("JUHE_API_KEY")
JUHE_STOCK_URL = "https://apis.juhe.cn/stockdata/index"

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

def is_etf(code):
    """判断代码是否为ETF（沪市51开头，深市159开头）"""
    return code.startswith(("51", "159"))

# ------------------------------------------------------------
# 稳定数据获取（聚合数据API）
# ------------------------------------------------------------
def get_stock_info(code):
    """获取个股行情、资金、技术指标"""
    try:
        params = {
            "key": JUHE_API_KEY,
            "code": code,
            "type": "all"  # 获取全部数据
        }
        resp = requests.get(JUHE_STOCK_URL, params=params, timeout=10)
        data = resp.json()
        if data.get("error_code") == 0:
            result = data["result"]
            return {
                "price": float(result["price"]),
                "change_pct": float(result["changePercent"]),
                "amount": float(result["turnover"]),
                "main_net_in": float(result["mainNetIn"]),
                "main_net_pct": float(result["mainNetPercent"]),
                "technical": result.get("technicalSummary", "技术数据获取失败")
            }
        else:
            print(f"API错误 {code}: {data.get('reason')}")
    except Exception as e:
        print(f"行情获取异常 {code}: {e}")
    return None

def get_intelligence(code):
    """个股研报与预警公告（聚合数据暂不提供，保留原逻辑）"""
    # 此部分保留原有逻辑，作为辅助
    return ["无相关预测情报"]

def get_hot_sectors():
    """市场热点板块（聚合数据暂不提供，保留原逻辑）"""
    return "板块数据暂不可用"

def get_calendar():
    """财经日历（聚合数据暂不提供，保留原逻辑）"""
    return "暂无重要事件"

# ------------------------------------------------------------
# AI 总结（核心功能）
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
            data_text += f"，成交额{format_amount(sd['amount'])}；"
        data_text += f"主力资金：{format_amount(sd['main_net_in'])}，占比{sd['main_net_pct']:.2f}%；\n"
        if sd.get("technical"):
            data_text += f"  技术面：{sd['technical']}\n"
        if sd.get("intel") and sd['intel'] != ["无相关预测情报"]:
            data_text += f"  🔍 预测情报：{'；'.join(sd['intel'])}\n"

    prompt = f"""你是一位INTJ型投资分析师。请结合所有数据，为每只股票生成专业判断。

要求：
1. 格式：[股票名]：🔴/🟢/➖ 核心分析... 关联动态：1. 动态一；2. 动态二
2. 必须引用技术面信号。
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
        info = get_stock_info(code)
        intel = get_intelligence(code)

        data_list.append({
            "code": code, "name": name,
            "price": info["price"] if info else None,
            "change_pct": info["change_pct"] if info else None,
            "amount": info["amount"] if info else None,
            "main_net_in": info["main_net_in"] if info else 0,
            "main_net_pct": info["main_net_pct"] if info else 0.0,
            "technical": info["technical"] if info else "获取失败",
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

        body += f"  💵 主力：{format_amount(sd['main_net_in'])} (占比{sd['main_net_pct']:.2f}%)\n"
        body += f"  📈 技术：{sd.get('technical', '获取失败')}\n"

        if sd.get("intel") and sd['intel'] != ["无相关预测情报"]:
            body += f"  📰 情报：\n"
            for line in sd['intel']:
                body += f"    • {line}\n"

    body += "\n━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据源：聚合数据 | 分析：DeepSeek AI | 仅供参考，不构成投资建议。"

    send_email(f"📈 投资简报 {now}", body)
    print("简报发送完毕")

if __name__ == "__main__":
    main()
