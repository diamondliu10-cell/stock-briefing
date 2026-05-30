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
# DeepSeek 联网搜索（优化版提示词）
# ------------------------------------------------------------
def search_with_deepseek(code, name, report_date):
    """
    调用 DeepSeek API，开启联网搜索。
    强制指定搜索周期为近一周，并要求输出格式精简。
    """
    if not DEEPSEEK_API_KEY:
        return f"❌ 未配置 DeepSeek API Key"

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""今天是 {report_date}。请联网搜索 {name}（股票代码 {code}）最近一周（从 {report_date} 往前推7天）内的重要公告、新闻、监管信息。

按以下格式逐条列出（每条一行，最多5条，选择最重要的）：
[日期] [来源] 消息标题 → 【利好/利空/中性】原因简述（15字以内）

如果未搜到近一周的消息，回复：近一周未搜到相关消息
如果搜索失败，回复：搜索暂时不可用

只输出上述格式的内容，不要添加开头语或结尾语。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1500,
        "stream": False,
        "search": True
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"搜索失败：{str(e)}"

# ------------------------------------------------------------
# AI 综合分析（风险前置 + 精简输出）
# ------------------------------------------------------------
def generate_final_summary(all_results, report_date):
    """将每只股票的搜索结果汇总，生成风险前置的简报"""
    if not DEEPSEEK_API_KEY:
        return "❌ 未配置 DeepSeek API Key"

    # 先提取所有股票中的利空消息，用于风险汇总
    risk_lines = []
    data_text = ""
    for item in all_results:
        result = item["result"]
        data_text += f"\n【{item['name']}（{item['code']}）】\n{result}\n"
        # 提取利空行
        for line in result.split("\n"):
            if "利空" in line or "🔴" in line:
                risk_lines.append(f"  {item['name']}：{line.strip()}")

    # 构建风险提示部分
    risk_section = ""
    if risk_lines:
        risk_section = "【⚠️ 风险预警】\n"
        for rl in risk_lines[:10]:  # 最多10条风险
            risk_section += f"🔴 {rl}\n"
        risk_section += "\n"
    else:
        risk_section = "【⚠️ 风险预警】\n今日未发现明确利空信号\n\n"

    prompt = f"""你是资深投资分析师。今天日期：{report_date}。

请基于以下搜索到的近一周消息，生成一份精简的消息面简报。严格按以下结构输出：

【⚠️ 风险预警】
- 如果以下消息中存在减持、监管问询、业绩大幅下滑、重大诉讼等利空，请在此处汇总，每条用🔴标记
- 如果没有利空，写"今日未发现明确利空信号"

【📊 个股消息及判断】
对每只股票，直接复述其搜索结果（已包含利好/利空/中性判断和原因），不要重新分析。如果某只股票显示"近一周未搜到相关消息"或"搜索暂时不可用"，保留原文即可，不要删掉。

{data_text}

只输出上述两个模块的内容，不要添加开头语、结尾语或额外分析。"""

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
        search_result = search_with_deepseek(code, name, report_date)
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
        # 上午模式：完整简报
        body = f"📈 每日消息简报 | {now}\n"
        body += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        body += final_brief
        body += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
        body += "数据源：DeepSeek 联网搜索 | 仅供参考，不构成投资建议"

        send_email(f"📈 消息简报 {now}", body)

        # 保存上午摘要用于下午对比
        morning_data = {}
        for item in all_results:
            morning_data[item["code"]] = item["result"][:200]
        with open("morning_news.json", "w", encoding="utf-8") as f:
            json.dump(morning_data, f, ensure_ascii=False)
        print("上午数据已保存")
    else:
        # 下午模式：只检测新增
        has_new = False
        new_items = []
        for item in all_results:
            code = item["code"]
            old_fingerprint = morning_msgs.get(code, "")
            new_fingerprint = item["result"][:200]
            if new_fingerprint != old_fingerprint and "未搜到相关消息" not in item["result"] and "搜索失败" not in item["result"]:
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
            body += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
            body += "数据源：DeepSeek 联网搜索 | 仅供参考"

            send_email(f"📈 午间消息更新 {now}", body)

    print("任务结束")

if __name__ == "__main__":
    main()
