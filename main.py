import requests
import smtplib
import os
import json
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
# 消息获取与过滤
# ------------------------------------------------------------
def is_relevant(title, code, name):
    """判断消息标题是否与给定股票相关"""
    # 精确匹配股票名称或代码
    if name in title or code in title:
        return True
    # 常见简称匹配（取股票名称的前2-3个字）
    short_names = [name[:2], name[:3], name[:4]]
    for sn in short_names:
        if len(sn) >= 2 and sn in title:
            return True
    return False

def fetch_cninfo(code, name, days=3):
    messages = []
    try:
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
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "http://www.cninfo.com.cn/"}
        resp = requests.post(api_url, data=params, headers=headers, timeout=15)
        data = resp.json()
        if data.get("announcements"):
            for item in data["announcements"]:
                title = item.get("announcementTitle", "")
                date_str = item.get("adjunctUrl", "")[:10] if item.get("adjunctUrl") else ""
                if not date_str:
                    date_str = item.get("announcementTime", "")[:10]
                # 只保留与该公司相关的消息
                if is_relevant(title, code, name):
                    messages.append({
                        "date": date_str,
                        "title": title,
                        "source": "巨潮资讯"
                    })
    except Exception as e:
        print(f"巨潮资讯获取异常 {code}: {e}")
    return messages

def fetch_eastmoney(code, name, days=3):
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
            title = item["title"]
            if date_str >= cutoff and is_relevant(title, code, name):
                messages.append({
                    "date": date_str,
                    "title": title,
                    "source": "东方财富"
                })
    except Exception as e:
        print(f"东方财富获取异常 {code}: {e}")
    return messages

def fetch_regulatory(code, name):
    messages = []
    try:
        if code.startswith(("0", "3")):
            exchange = "szse"
        else:
            exchange = "sse"
        if exchange == "szse":
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
                    if any(kw in title for kw in ["问询", "关注", "监管", "处分", "警示"]) and is_relevant(title, code, name):
                        messages.append({
                            "date": item.get("pubDate", "")[:10],
                            "title": title,
                            "source": "深交所"
                        })
        else:
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
                        if any(kw in title for kw in ["问询", "关注", "监管", "处分", "警示"]) and is_relevant(title, code, name):
                            messages.append({
                                "date": date_str,
                                "title": title,
                                "source": "上交所"
                            })
    except Exception as e:
        print(f"交易所监管信息获取异常 {code}: {e}")
    return messages

def gather_all_messages(code, name):
    all_msgs = []
    all_msgs.extend(fetch_cninfo(code, name))
    all_msgs.extend(fetch_eastmoney(code, name))
    all_msgs.extend(fetch_regulatory(code, name))
    # 去重
    seen = set()
    unique = []
    for msg in all_msgs:
        if msg["title"] not in seen:
            seen.add(msg["title"])
            unique.append(msg)
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

def analyze_messages(stocks_data, report_date, is_afternoon=False):
    data_text = ""
    for sd in stocks_data:
        data_text += f"\n【{sd['name']}（{sd['code']}）】\n"
        msgs = sd.get("messages", [])
        if msgs:
            for m in msgs:
                data_text += f"  [{m['date']}] [{m['source']}] {m['title']}\n"
        else:
            data_text += "  无新消息\n"
        data_text += "\n"

    prompt = f"""你是资深投资分析师。今天日期：{report_date}。请基于以下{"新增" if is_afternoon else "近3日"}消息，撰写一份消息面简报。

要求：
1. 每只股票列出最重要的消息（最多3条），每条标注来源和利好/利空/中性判断，并简要说明理由。
2. 如果某只股票无消息，写“暂无新消息”。
3. 最后，若存在减持、监管问询、业绩大幅下滑、重大诉讼等利空，请单独列出【⚠️ 风险预警】，用🔴标记。

{data_text}"""
    return call_deepseek(prompt)

# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def main():
    now = beijing_now()
    report_date = beijing_date()
    stocks = load_stocks()
    if not stocks:
        send_email("消息简报 - 错误", "股票列表为空")
        return

    morning_file = os.environ.get("MORNING_DATA_PATH", "")
    morning_msgs = {}
    if morning_file and os.path.exists(morning_file):
        try:
            with open(morning_file, "r", encoding="utf-8") as f:
                morning_msgs = json.load(f)
        except:
            morning_msgs = {}

    is_afternoon = bool(morning_msgs)

    stocks_data = []
    for code, name in stocks:
        print(f"处理：{name}({code})")
        messages = gather_all_messages(code, name)
        # 只保留与该股票直接相关的消息
        relevant_msgs = [m for m in messages if is_relevant(m["title"], code, name)]
        print(f"  共获取 {len(messages)} 条消息，其中 {len(relevant_msgs)} 条相关")
        stocks_data.append({
            "name": name,
            "code": code,
            "messages": relevant_msgs
        })

    if not is_afternoon:
        # 上午模式
        print("上午模式：生成全量简报")
        ai_analysis = analyze_messages(stocks_data, report_date, is_afternoon=False)

        body = f"📈 每日消息简报 | {now}\n"
        body += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        body += ai_analysis
        body += "\n\n━━━━━━━━━━━━━━━━━━━━━━\n【📋 消息详情】\n\n"
        for sd in stocks_data:
            body += f"🔹 {sd['name']}（{sd['code']}）\n"
            if sd['messages']:
                for m in sd['messages']:
                    body += f"  [{m['date']}] [{m['source']}] {m['title']}\n"
            else:
                body += "  近3日无相关公告/新闻\n"
            body += "\n"
        body += "━━━━━━━━━━━━━━━━━━━━━━\n"
        body += "数据源：巨潮资讯、深交所、上交所、东方财富 | 分析：DeepSeek AI | 仅供参考，不构成投资建议"

        send_email(f"📈 消息简报 {now}", body)

        # 保存上午消息
        morning_data = {}
        for sd in stocks_data:
            morning_data[sd["code"]] = [{"date": m["date"], "title": m["title"], "source": m["source"]} for m in sd["messages"]]
        with open("morning_news.json", "w", encoding="utf-8") as f:
            json.dump(morning_data, f, ensure_ascii=False)
        print("上午消息已保存")
    else:
        # 下午模式：只对比新增
        print("下午模式：检测新增消息")
        new_stocks_data = []
        has_new = False
        for sd in stocks_data:
            code = sd["code"]
            old_list = morning_msgs.get(code, [])
            old_titles = {m["title"] for m in old_list}
            new_msgs = [m for m in sd["messages"] if m["title"] not in old_titles]
            if new_msgs:
                has_new = True
                new_stocks_data.append({
                    "name": sd["name"],
                    "code": code,
                    "messages": new_msgs
                })

        if not has_new:
            print("无新增消息，不发送邮件")
        else:
            print(f"发现 {sum(len(s['messages']) for s in new_stocks_data)} 条新增消息，发送简报")
            ai_analysis = analyze_messages(new_stocks_data, report_date, is_afternoon=True)

            body = f"📈 午间消息更新 | {now}\n"
            body += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            body += ai_analysis
            body += "\n\n━━━━━━━━━━━━━━━━━━━━━━\n【📋 新增消息详情】\n\n"
            for sd in new_stocks_data:
                body += f"🔹 {sd['name']}（{sd['code']}）\n"
                for m in sd['messages']:
                    body += f"  [{m['date']}] [{m['source']}] {m['title']}\n"
                body += "\n"
            body += "━━━━━━━━━━━━━━━━━━━━━━\n"
            body += "数据源：巨潮资讯、深交所、上交所、东方财富 | 分析：DeepSeek AI | 仅供参考"

            send_email(f"📈 午间消息更新 {now}", body)

    print("任务结束")

if __name__ == "__main__":
    main()
