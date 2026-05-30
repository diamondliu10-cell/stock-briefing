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
# DeepSeek 联网搜索（无需第三方 API）
# ------------------------------------------------------------
def search_with_deepseek(code, name):
    """
    调用 DeepSeek API，开启联网搜索，让 AI 直接搜索并总结该股票的最新消息。
    返回 AI 总结后的文本。
    """
    if not DEEPSEEK_API_KEY:
        return "❌ 未配置 DeepSeek API Key"

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""请联网搜索 {name}（股票代码 {code}）近一周的重要公告、新闻、监管信息。

要求：
1. 列出 3-5 条最重要的消息，每条包含标题、来源、日期、内容摘要（50字以内）
2. 判断每条消息是利好、利空还是中性
3. 如果有减持、监管处罚、业绩大幅下滑、诉讼等重大利空，请特别标注🔴
4. 如果没有搜到相关消息，回复"近一周未搜到相关消息"
5. 只回复搜索结果，不要添加额外说明"""

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2000,
        "stream": False,
        "search": True   # 开启联网搜索
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"搜索失败：{str(e)}"

# ------------------------------------------------------------
# AI 综合分析
# ------------------------------------------------------------
def generate_final_summary(all_results, report_date):
    """将每只股票的搜索结果汇总，生成最终简报"""
    if not DEEPSEEK_API_KEY:
        return "❌ 未配置 DeepSeek API Key"

    data_text = ""
    for item in all_results:
        data_text += f"\n【{item['name']}（{item['code']}）】\n"
        data_text += item["result"] + "\n"

    prompt = f"""你是资深投资分析师。今天日期：{report_date}。请基于以下搜索到的近一周消息，撰写消息面简报。

要求：
1. 每只股票列出最重要的消息（最多3条），每条标注利好/利空/中性判断，并简要说明理由。
2. 如果某只股票无消息，写"近一周未搜到相关消息"。
3. 最后，若存在减持、监管问询、业绩大幅下滑、重大诉讼等利空，请单独列出【⚠️ 风险预警】，用🔴标记。

{data_text}"""
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2000,
        "stream": False
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ AI调用失败：{str(e)}"

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

    # 判断是否为下午
    morning_file = os.environ.get("MORNING_DATA_PATH", "")
    morning_msgs = {}
    if morning_file and os.path.exists(morning_file):
        try:
            with open(morning_file, "r", encoding="utf-8") as f:
                morning_msgs = json.load(f)
        except:
            morning_msgs = {}
    is_afternoon = bool(morning_msgs)

    # 对每只股票联网搜索
    all_results = []
    for code, name in stocks:
        print(f"联网搜索：{name}({code})...")
        search_result = search_with_deepseek(code, name)
        print(f"  搜索完成")
        all_results.append({
            "name": name,
            "code": code,
            "result": search_result
        })

    # 生成最终简报
    print("生成最终简报...")
    final_brief = generate_final_summary(all_results, report_date)

    if not is_afternoon:
        # 上午模式
        body = f"📈 每日消息简报 | {now}\n"
        body += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        body += final_brief
        body += "\n\n━━━━━━━━━━━━━━━━━━━━━━\n【📋 搜索详情】\n\n"
        for item in all_results:
            body += f"🔹 {item['name']}（{item['code']}）\n"
            body += f"{item['result']}\n\n"
        body += "━━━━━━━━━━━━━━━━━━━━━━\n"
        body += "数据源：DeepSeek 联网搜索 | 分析：DeepSeek AI | 仅供参考，不构成投资建议"

        send_email(f"📈 消息简报 {now}", body)

        # 保存上午摘要用于下午对比
        morning_data = {}
        for item in all_results:
            morning_data[item["code"]] = item["result"][:200]  # 用前200字做指纹
        with open("morning_news.json", "w", encoding="utf-8") as f:
            json.dump(morning_data, f, ensure_ascii=False)
        print("上午数据已保存")
    else:
        # 下午模式：对比是否有新增
        has_new = False
        new_items = []
        for item in all_results:
            code = item["code"]
            old_fingerprint = morning_msgs.get(code, "")
            new_fingerprint = item["result"][:200]
            if new_fingerprint != old_fingerprint and "未搜到相关消息" not in item["result"]:
                has_new = True
                new_items.append(item)

        if not has_new:
            print("无新增消息，不发送邮件")
        else:
            print(f"发现新增消息，发送简报")
            final_brief_pm = generate_final_summary(new_items, report_date)

            body = f"📈 午间消息更新 | {now}\n"
            body += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            body += final_brief_pm
            body += "\n\n━━━━━━━━━━━━━━━━━━━━━━\n【📋 新增消息详情】\n\n"
            for item in new_items:
                body += f"🔹 {item['name']}（{item['code']}）\n"
                body += f"{item['result']}\n\n"
            body += "━━━━━━━━━━━━━━━━━━━━━━\n"
            body += "数据源：DeepSeek 联网搜索 | 分析：DeepSeek AI | 仅供参考"

            send_email(f"📈 午间消息更新 {now}", body)

    print("任务结束")

if __name__ == "__main__":
    main()
