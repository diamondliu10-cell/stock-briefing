import requests
import smtplib
import os
import re
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# ------------------------------------------------------------
# 基础配置
# ------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_now():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")

def beijing_date():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")

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
                    stocks.append((code, name))
    except FileNotFoundError:
        print("stocks.txt不存在")
    return stocks

# ------------------------------------------------------------
# 消息获取
# ------------------------------------------------------------
def fetch_cninfo(code, days=3):
    """从巨潮资讯网获取公告"""
    messages = []
    try:
        # 巨潮资讯网个股公告页面
        url = f"http://www.cninfo.com.cn/new/disclosure/detail?stockCode={code}&orgId=gssz{code}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "http://www.cninfo.com.cn/"
        }
        # 实际上巨潮有专门的公告列表API
        api_url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        end_date = beijing_date()
        start_date = (datetime.now(BEIJING_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        params = {
            "pageNum": 1,
            "pageSize": 30,
            "stock": f"{code}",
            "startDate": start_date,
            "endDate": end_date,
            "column": "szse",
            "tabName": "fulltext"
        }
        resp = requests.post(api_url, data=params, headers=headers, timeout=15)
        data = resp.json()
        if data.get("announcements"):
            for item in data["announcements"]:
                title = item.get("announcementTitle", "")
                date_str = item.get("adjunctUrl", "")[:10] if item.get("adjunctUrl") else ""
                if not date_str:
                    date_str = item.get("announcementTime", "")[:10]
                url_path = item.get("adjunctUrl", "")
                full_url = f"http://static.cninfo.com.cn/{url_path}" if url_path else ""
                messages.append({
                    "date": date_str,
                    "title": title,
                    "source": "巨潮资讯",
                    "url": full_url
                })
    except Exception as e:
        print(f"巨潮资讯获取异常 {code}: {e}")
    return messages

def fetch_eastmoney(code, name, days=3):
    """从东方财富获取个股资讯和研报"""
    messages = []
    try:
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "page_size": 20,
            "page_index": 1,
            "stock_list": code,
            "f_node": 0,
            "s_node": 0
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        items = resp.json()["data"]["list"]
        cutoff = (datetime.now(BEIJING_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        for item in items:
            date_str = item["notice_date"][:10]
            if date_str >= cutoff:
                messages.append({
                    "date": date_str,
                    "title": item["title"],
                    "source": "东方财富",
                    "url": f"https://data.eastmoney.com/notices/detail/{code}/{item['art_code']}.html"
                })
    except Exception as e:
        print(f"东方财富获取异常 {code}: {e}")
    return messages

def fetch_regulatory(code, name):
    """从交易所获取监管信息"""
    messages = []
    try:
        # 判断交易所
        if code.startswith(("0", "3")):
            exchange = "szse"  # 深交所
        else:
            exchange = "sse"   # 上交所
        
        if exchange == "szse":
            # 深交所问询函查询
            url = "https://www.szse.cn/api/disc/announcement/queryAnnList"
            params = {
                "stockCode": code,
                "pageNum": 1,
                "pageSize": 10,
                "channelCode": "listedNotice",
                "seDate": f"{(datetime.now(BEIJING_TZ) - timedelta(days=30)).strftime('%Y-%m-%d')}~{beijing_date()}"
            }
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
            if data.get("data"):
                for item in data["data"]:
                    title = item.get("title", "")
                    if any(kw in title for kw in ["问询", "关注", "监管", "处分", "警示"]):
                        messages.append({
                            "date": item.get("pubDate", "")[:10],
                            "title": title,
                            "source": "深交所",
                            "url": f"https://www.szse.cn{data.get('attachPath', '')}"
                        })
        else:
            # 上交所监管函查询
            url = "https://query.sse.com.cn/listedquery/announcement/queryAnnList.do"
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.sse.com.cn/"}
            params = {
                "stockCode": code,
                "pageNum": 1,
                "pageSize": 10,
                "beginDate": (datetime.now(BEIJING_TZ) - timedelta(days=30)).strftime("%Y-%m-%d"),
                "endDate": beijing_date()
            }
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.text:
                soup = BeautifulSoup(resp.text, "html.parser")
                for row in soup.select(".table_list tbody tr"):
                    cells = row.select("td")
                    if len(cells) >= 3:
                        title = cells[1].text.strip()
                        date_str = cells[2].text.strip()
                        if any(kw in title for kw in ["问询", "关注", "监管", "处分", "警示"]):
                            messages.append({
                                "date": date_str,
                                "title": title,
                                "source": "上交所",
                                "url": f"https://www.sse.com.cn{cells[1].select_one('a').get('href', '')}"
                            })
    except Exception as e:
        print(f"交易所监管信息获取异常 {code}: {e}")
    return messages

def gather_all_messages(code, name):
    """汇总所有来源的消息"""
    all_msgs = []
    all_msgs.extend(fetch_cninfo(code))
    all_msgs.extend(fetch_eastmoney(code, name))
    all_msgs.extend(fetch_regulatory(code, name))
    
    # 去重（按标题）
    seen = set()
    unique = []
    for msg in all_msgs:
        if msg["title"] not in seen:
            seen.add(msg["title"])
            unique.append(msg)
    
    # 按日期倒序
    unique.sort(key=lambda x: x["date"], reverse=True)
    return unique

# ------------------------------------------------------------
# AI 分析
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

def generate_analysis(stocks_data, report_date):
    # 构建消息文本
    data_text = ""
    for sd in stocks_data:
        data_text += f"\n【{sd['name']}（{sd['code']}）】\n"
        msgs = sd.get("messages", [])
        if msgs:
            for m in msgs:
                data_text += f"  [{m['date']}] [{m['source']}] {m['title']}\n"
        else:
            data_text += "  近3日无公告/新闻\n"
        data_text += "\n"

    prompt = f"""你是资深投资分析师。今天日期：{report_date}。请基于以下近3日的公司公告和新闻，撰写一份每日消息面简报。

⚠️ 规则：
1. 日期必须为 {report_date}。
2. 每只股票的消息按以下格式分析：
   股票名（代码）：
   · 关键消息1：[来源] 标题 → 利好/利空/中性，理由（1句）
   · 关键消息2：[来源] 标题 → 利好/利空/中性，理由（1句）
   （最多3条，选最重要的，无关的消息略过）
   · 综合判断：🔴/🟢/➖ 持有/关注/谨慎（1句话）
3. 最后，如果任何股票存在减持、监管问询、业绩大幅下滑、重大诉讼等利空，请单独列出【⚠️ 风险预警】，用🔴标记。

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
    report_date = beijing_date()
    stocks_data = []

    for code, name in stocks:
        print(f"处理：{name}({code})")
        messages = gather_all_messages(code, name)
        print(f"  共获取 {len(messages)} 条消息")
        stocks_data.append({
            "name": name,
            "code": code,
            "messages": messages
        })

    # 生成AI分析
    print("请求DeepSeek分析...")
    ai_analysis = generate_analysis(stocks_data, report_date)

    # 构建邮件
    body = f"📈 每日消息简报 | {now}\n"
    body += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    body += ai_analysis if ai_analysis else "AI分析生成失败"
    body += "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
    body += "【📋 消息详情】\n\n"
    for sd in stocks_data:
        body += f"🔹 {sd['name']}（{sd['code']}）\n"
        msgs = sd.get("messages", [])
        if msgs:
            for m in msgs:
                body += f"  [{m['date']}] [{m['source']}] {m['title']}\n"
        else:
            body += "  近3日无公告/新闻\n"
        body += "\n"
    body += "━━━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据源：巨潮资讯、深交所、上交所、东方财富 | 分析：DeepSeek AI | 仅供参考，不构成投资建议"

    send_email(f"📈 消息简报 {now}", body)
    print("简报发送完毕")

if __name__ == "__main__":
    main()
