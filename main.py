import requests
import smtplib
import os
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ------------------------------------------------------------
# 基础配置
# ------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ------------------------------------------------------------
# 通用工具
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

def get_secid(code):
    """根据代码生成东方财富secid"""
    if code.startswith("0") or code.startswith("3"):
        return f"0.{code}"
    else:
        return f"1.{code}"

def get_sina_code(code):
    """生成新浪行情代码（例如 sh600519, sz000651）"""
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    else:
        return f"sz{code}"

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
                    stocks.append((code, name))
    except FileNotFoundError:
        print("找不到stocks.txt")
    return stocks

# ------------------------------------------------------------
# 1. 行情数据（东方财富为主，新浪备份）
# ------------------------------------------------------------
def get_basic_em(secid):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f169,f170,f48",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json()["data"]
        return {
            "price": data["f43"] / 100 if data.get("f43") else None,
            "change_pct": data["f170"] / 100 if data.get("f170") else None,
            "amount": data["f48"] if data.get("f48") else None
        }
    except:
        return None

def get_basic_sina(sina_code):
    url = f"http://hq.sinajs.cn/list={sina_code}"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
    try:
        r = requests.get(url, headers=headers, timeout=5)
        r.encoding = "gb2312"
        data = r.text.split('"')[1].split(",")
        if len(data) > 30:
            return {
                "price": float(data[3]),
                "change_pct": round((float(data[3]) - float(data[2])) / float(data[2]) * 100, 2),
                "amount": None
            }
    except:
        pass
    return None

def get_stock_basic(code, secid):
    # 优先东方财富，失败则用新浪备份
    result = get_basic_em(secid)
    if result and result["price"] is not None:
        return result
    sina_code = get_sina_code(code)
    return get_basic_sina(sina_code)

# ------------------------------------------------------------
# 2. 主力资金流向（东方财富）
# ------------------------------------------------------------
def get_fund_flow(secid):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f62,f184",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json().get("data", {})
        main_in = data.get("f62", 0) or 0
        main_pct = (data.get("f184", 0) or 0) / 100.0
        return {"main_net_in": main_in, "main_net_pct": main_pct}
    except:
        return {"main_net_in": 0, "main_net_pct": 0.0}

# ------------------------------------------------------------
# 3. 公告（东方财富）
# ------------------------------------------------------------
def get_notices(stock_code):
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "page_size": 3, "page_index": 1, "ann_type": "A",
        "stock_list": stock_code, "f_node": 1, "s_node": 0
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        items = r.json()["data"]["list"]
        return [f"{item['notice_date'][:10]} {item['title']}" for item in items]
    except:
        return []

# ------------------------------------------------------------
# 4. 市场情绪温度计（三大指数涨跌 + 涨跌家数）
# ------------------------------------------------------------
def get_market_sentiment():
    # 获取上证、深证、创业板指涨跌
    indices = {
        "上证指数": "1.000001",
        "深证成指": "0.399001",
        "创业板指": "0.399006"
    }
    sentiment_lines = []
    for name, secid in indices.items():
        basic = get_basic_em(secid)
        if basic and basic.get("change_pct") is not None:
            sentiment_lines.append(f"{name}：{basic['change_pct']}%")
        else:
            sentiment_lines.append(f"{name}：获取失败")
    # 尝试获取全市场涨跌家数（用东方财富API，失败则留空）
    try:
        url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
        params = {
            "fltt": 2,
            "fields": "f2,f3,f4,f12,f14",
            "secids": "1.000001,0.399001,0.399006",
            "ut": "fa5fd1943c7b386f172d6893dbf30c78"
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params=params, headers=headers, timeout=5)
        # 涨跌家数接口较复杂，暂用简单方式，只展示指数
    except:
        pass
    return " | ".join(sentiment_lines) if sentiment_lines else "市场情绪数据暂时无法获取"

# ------------------------------------------------------------
# 5. 十大流通股东透视（社保/北向/机构）
# ------------------------------------------------------------
def get_market_suffix(code):
    """判断市场后缀SZ或SH"""
    if code.startswith(("0", "3", "1")):  # 深市包含创业板、ETF
        return "SZ"
    else:
        return "SH"

def get_top_holders(code):
    """获取最新一期十大流通股东，识别社保、北向"""
    suffix = get_market_suffix(code)
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_EH_HOLDERS",
        "columns": "HOLDER_NAME,HOLDER_NUM,HOLD_NUM_CHANGE,HOLD_NUM_RATIO,END_DATE",
        "filter": f'(SECUCODE="{code}.{suffix}")(IS_HOLDORG=1)',
        "pageNumber": 1,
        "pageSize": 10,
        "sortTypes": -1,
        "sortColumns": "END_DATE",
        "source": "HSF10",
        "client": "PC"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        data = r.json()
        if data.get("success") and data.get("result") and data["result"].get("data"):
            holders = data["result"]["data"]
            result_lines = []
            latest_date = holders[0]["END_DATE"][:10] if holders else "未知"
            result_lines.append(f"（数据截止：{latest_date}）")
            for h in holders:
                name = h.get("HOLDER_NAME", "")
                if "社保" in name or "香港中央结算" in name:
                    ratio = h.get("HOLD_NUM_RATIO", None)
                    change = h.get("HOLD_NUM_CHANGE", 0)
                    if ratio is not None:
                        change_str = "增持" if change > 0 else ("减持" if change < 0 else "不变")
                        result_lines.append(f"  • {name} 持股{ratio}%，{change_str}")
            return result_lines
    except:
        pass
    return None

# ------------------------------------------------------------
# AI 总结
# ------------------------------------------------------------
def generate_ai_summary(stocks_data, sentiment_text):
    if not DEEPSEEK_API_KEY:
        return "❌ 未设置 DEEPSEEK_API_KEY"

    data_text = f"【市场情绪】{sentiment_text}\n\n"
    data_text += "【持仓股票数据】\n"
    for sd in stocks_data:
        data_text += f"\n{sd['name']}({sd['code']})："
        if sd.get("price"):
            data_text += f"现价{sd['price']}元，涨跌幅{sd['change_pct']}%"
        if sd.get("amount"):
            data_text += f"，成交额{sd['amount']}元；"
        data_text += f"主力净流入{sd['main_net_in']:.0f}元，占比{sd['main_net_pct']:.2f}%；"
        if sd.get("notices"):
            data_text += f"公告：{'；'.join(sd['notices'])}；"
        if sd.get("holders_info"):
            data_text += f"重要股东动向：{'；'.join(sd['holders_info'])}"
        else:
            data_text += "重要股东动向：无"

    prompt = f"""你是一位INTJ型投资分析师，冷静、客观、一针见血。请根据以下今日数据，为每只股票生成简短判断（不超过60字），并用一句话总结整体账户风险。

要求：
1. 直接指出最关键的变化或风险（例如主力资金连续流出、公告重大利好/利空、社保增持或退出等）。
2. 数据平淡则说“今日无异常”。
3. 每只股票前面标注🔴（风险）或🟢（积极）或➖（中性）。
4. 最后单独一行给出整体账户今日最需要关注的风险点。

{data_text}

请按以下格式输出：
比亚迪：🔴/🟢/➖ 核心判断...
恒生科技ETF：🔴/🟢/➖ 核心判断...
龙佰集团：🔴/🟢/➖ 核心判断...
半导体ETF：🔴/🟢/➖ 核心判断...
整体风险：一句话总结。"""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 700
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
    stocks = load_stocks()
    if not stocks:
        send_email("股票简报 - 错误", "股票列表为空")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. 市场情绪
    sentiment = get_market_sentiment()

    # 2. 个股数据
    stocks_data = []
    for code, name in stocks:
        secid = get_secid(code)
        basic = get_stock_basic(code, secid)
        flow = get_fund_flow(secid)
        notices = get_notices(code)
        holders = get_top_holders(code)

        stock_item = {
            "code": code,
            "name": name,
            "price": basic["price"] if basic else None,
            "change_pct": basic["change_pct"] if basic else None,
            "amount": basic["amount"] if basic else None,
            "main_net_in": flow["main_net_in"],
            "main_net_pct": flow["main_net_pct"],
            "notices": notices,
            "holders_info": holders
        }
        stocks_data.append(stock_item)

    # 3. AI 总结
    ai_summary = generate_ai_summary(stocks_data, sentiment)

    # 4. 构建邮件
    body = f"📈 持仓全量智能简报 ({now})\n"
    body += "━━━━━━━━━━━━━━━━━━━━\n\n"

    # 市场情绪
    body += f"【🌡️ 市场情绪】\n{sentiment}\n\n"

    # AI 判断
    if ai_summary and not ai_summary.startswith("❌"):
        body += "【今日核心判断（AI生成）】\n"
        body += ai_summary + "\n\n"
    else:
        body += f"【⚠️ AI 状态】\n{ai_summary or 'AI 返回为空'}\n\n"

    body += "━━━━━━━━━━━━━━━━━━━━\n【📋 详细数据】\n"

    for sd in stocks_data:
        body += f"\n【{sd['name']}】({sd['code']})\n"
        if sd.get("price"):
            pct = sd['change_pct']
            label = ""
            if pct is not None:
                if pct >= 2:
                    label = " 🟢大涨"
                elif pct <= -2:
                    label = " 🔴大跌"
            body += f"  💰 现价 {sd['price']}元 | 涨跌 {pct}%{label}\n"
            if sd.get("amount"):
                body += f"  📊 成交额 {sd['amount']}元\n"
        else:
            body += f"  💰 行情获取异常（已尝试东方财富及新浪）\n"

        body += f"  💵 主力资金：净流入 {sd['main_net_in']:.0f} 元 (占比 {sd['main_net_pct']:.2f}%)\n"

        if sd.get("holders_info"):
            body += f"  🔍 重要股东动向（社保/北向）:\n"
            for line in sd["holders_info"]:
                body += f"    {line}\n"
        else:
            body += f"  🔍 重要股东动向：未能获取\n"

        if sd.get("notices"):
            body += f"  📰 最新公告：\n"
            for n in sd['notices']:
                body += f"    • {n}\n"
        else:
            body += f"  📰 最新公告：无\n"

    body += "\n━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据来源：东方财富、新浪财经 | 分析：DeepSeek AI | 本简报不构成投资建议，请独立决策。"

    print(body)
    send_email(f"📈 投资简报 {now}", body)

if __name__ == "__main__":
    main()
