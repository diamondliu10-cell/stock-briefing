import requests
import smtplib
import os
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
    if code.startswith("0") or code.startswith("3"):
        return f"0.{code}"
    else:
        return f"1.{code}"

def get_sina_code(code):
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

def format_amount(amount_yuan):
    """智能单位转换：大于1亿显示亿，否则显示万"""
    if amount_yuan is None:
        return "0"
    yi = amount_yuan / 1e8
    if abs(yi) >= 0.01:
        return f"{yi:.2f}亿元"
    wan = amount_yuan / 1e4
    return f"{wan:.0f}万元"

# ------------------------------------------------------------
# 1. 行情数据（东方财富 + 新浪备份）
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
    result = get_basic_em(secid)
    if result and result["price"] is not None:
        return result
    return get_basic_sina(get_sina_code(code))

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
# 4. 个股资讯（东方财富，补充发布会等事件）
# ------------------------------------------------------------
def get_news(stock_code):
    """抓取个股最新5条资讯标题，补充公告之外的事件信息"""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "page_size": 5, "page_index": 1,
        "stock_list": stock_code,
        "f_node": 0,  # 0=全部, 1=公告, 2=研报
        "s_node": 0
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        items = r.json()["data"]["list"]
        return [f"{item['notice_date'][:10]} {item['title']}" for item in items]
    except:
        return []

# ------------------------------------------------------------
# 5. 个股市场情绪（东方财富人气榜排名）
# ------------------------------------------------------------
def get_stock_sentiment(code):
    secid = get_secid(code)
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f12,f14,f19,f20,f92",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json().get("data", {})
        rank = data.get("f92", None)
        if rank is not None and int(rank) > 0:
            return f"人气排名第{int(rank)}位"
        return "暂无排名数据"
    except:
        return "获取失败"

# ------------------------------------------------------------
# 6. 十大流通股东透视（社保/北向）
# ------------------------------------------------------------
def get_market_suffix(code):
    if code.startswith(("0", "3", "1")):
        return "SZ"
    else:
        return "SH"

def get_top_holders(code):
    suffix = get_market_suffix(code)
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_EH_HOLDERS",
        "columns": "HOLDER_NAME,HOLDER_NUM,HOLD_NUM_CHANGE,HOLD_NUM_RATIO,END_DATE",
        "filter": f'(SECUCODE="{code}.{suffix}")(IS_HOLDORG=1)',
        "pageNumber": 1, "pageSize": 10,
        "sortTypes": -1, "sortColumns": "END_DATE",
        "source": "HSF10", "client": "PC"
    }
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        data = r.json()
        if data.get("success") and data.get("result") and data["result"].get("data"):
            holders = data["result"]["data"]
            result_lines = []
            latest_date = holders[0].get("END_DATE", "未知")[:10] if holders else "未知"
            result_lines.append(f"（数据截止：{latest_date}）")
            has_info = False
            for h in holders:
                name = h.get("HOLDER_NAME", "")
                if any(keyword in name for keyword in ["社保", "香港中央结算", "中国证券金融", "中央汇金"]):
                    ratio = h.get("HOLD_NUM_RATIO", None)
                    change = h.get("HOLD_NUM_CHANGE", 0)
                    if ratio is not None:
                        change_str = "增持" if change > 0 else ("减持" if change < 0 else "不变")
                        result_lines.append(f"  • {name} 持股{ratio}%，{change_str}")
                        has_info = True
            if has_info:
                return result_lines
            else:
                return ["（当期十大流通股东中未发现社保/北向持仓）"]
        else:
            return None
    except:
        return None

# ------------------------------------------------------------
# AI 总结
# ------------------------------------------------------------
def generate_ai_summary(stocks_data):
    if not DEEPSEEK_API_KEY:
        return "❌ 未设置 DEEPSEEK_API_KEY"

    data_text = "【持仓股票数据】\n"
    for sd in stocks_data:
        data_text += f"\n{sd['name']}({sd['code']})："
        if sd.get("price"):
            data_text += f"现价{sd['price']}元，涨跌幅{sd['change_pct']}%"
        if sd.get("amount"):
            data_text += f"，成交额{format_amount(sd['amount'])}；"
        data_text += f"主力资金：{format_amount(sd['main_net_in'])}，占比{sd['main_net_pct']:.2f}%；"
        if sd.get("sentiment"):
            data_text += f"人气：{sd['sentiment']}；"
        if sd.get("notices"):
            data_text += f"公告：{'；'.join(sd['notices'])}；"
        if sd.get("news"):
            data_text += f"资讯：{'；'.join(sd['news'])}；"
        if sd.get("holders_info") and sd["holders_info"] != ["（暂无最新股东数据）"]:
            data_text += f"股东动向：{'；'.join(sd['holders_info'])}"

    prompt = f"""你是一位INTJ型投资分析师，冷静、客观、一针见血。根据以下数据，为每只股票生成简短判断（不超过60字），并用一句话总结整体账户风险。

重要规则：
1. 公告中已包含“2026年一季报”的，请基于已有数据判断，不要说“等待一季报”。
2. 资讯中包含“发布会”“业绩说明会”“重大合同”等事件的，请重点提及。
3. 资金数据已智能显示单位（亿元/万元），请直接引用。
4. 每只股票前标注🔴（风险）或🟢（积极）或➖（中性）。
5. 最后单独一行给出整体风险总结。

{data_text}

请按以下格式输出：
比亚迪：🔴/🟢/➖ 核心判断...
（其他股票依次列出）
整体风险：一句话总结。"""

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 800
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

    stocks_data = []
    for code, name in stocks:
        secid = get_secid(code)
        basic = get_stock_basic(code, secid)
        flow = get_fund_flow(secid)
        notices = get_notices(code)
        news = get_news(code)  # 新增：个股资讯
        sentiment = get_stock_sentiment(code)
        holders = get_top_holders(code)

        stocks_data.append({
            "code": code, "name": name,
            "price": basic["price"] if basic else None,
            "change_pct": basic["change_pct"] if basic else None,
            "amount": basic["amount"] if basic else None,
            "main_net_in": flow["main_net_in"],
            "main_net_pct": flow["main_net_pct"],
            "notices": notices,
            "news": news,
            "sentiment": sentiment,
            "holders_info": holders
        })

    ai_summary = generate_ai_summary(stocks_data)

    body = f"📈 持仓全量智能简报 ({now})\n"
    body += "━━━━━━━━━━━━━━━━━━━━\n\n"

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
                body += f"  📊 成交额 {format_amount(sd['amount'])}\n"
        else:
            body += f"  💰 行情获取异常（已尝试东方财富及新浪）\n"

        body += f"  💵 主力资金：净流入 {format_amount(sd['main_net_in'])} (占比 {sd['main_net_pct']:.2f}%)\n"
        body += f"  📈 市场情绪：{sd.get('sentiment', '获取失败')}\n"

        body += f"  🔍 重要股东动向（社保/北向）:\n"
        holders = sd.get("holders_info")
        if holders and holders != ["（当期十大流通股东中未发现社保/北向持仓）"]:
            for line in holders:
                body += f"    {line}\n"
        elif holders == ["（当期十大流通股东中未发现社保/北向持仓）"]:
            body += f"    （当期十大流通股东中未发现社保/北向持仓）\n"
        else:
            body += f"    （暂无最新股东数据）\n"

        if sd.get("notices"):
            body += f"  📰 最新公告：\n"
            for n in sd['notices']:
                body += f"    • {n}\n"
        else:
            body += f"  📰 最新公告：无\n"

        if sd.get("news"):
            body += f"  📰 最新资讯：\n"
            for n in sd['news']:
                body += f"    • {n}\n"

    body += "\n━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据来源：东方财富、新浪财经 | 分析：DeepSeek AI | 本简报不构成投资建议，请独立决策。"

    print(body)
    send_email(f"📈 投资简报 {now}", body)

if __name__ == "__main__":
    main()
