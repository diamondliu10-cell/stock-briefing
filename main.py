import requests
import smtplib
import os
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime, timezone, timedelta
from io import BytesIO

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

def send_email(subject, body_text, img_bytes):
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    to_addr = os.environ.get("EMAIL_TO")
    if not user or not password or not to_addr:
        print("邮件凭证缺失")
        return
    msg = MIMEMultipart("related")
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    msg.attach(alt)
    alt.attach(MIMEText(body_text, "plain", "utf-8"))

    img = MIMEImage(img_bytes, _subtype="png")
    img.add_header("Content-ID", "<briefing_chart>")
    img.add_header("Content-Disposition", "inline", filename="briefing.png")
    msg.attach(img)

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
# DeepSeek 联网搜索（强制要求附链接）
# ------------------------------------------------------------
def search_stock_news(code, name, report_date):
    if not DEEPSEEK_API_KEY:
        return "❌ API Key未配置"

    start_date = (datetime.now(BEIJING_TZ) - timedelta(days=7)).strftime("%Y-%m-%d")
    
    prompt = f"""今天是 {report_date}。请严格搜索 {name}（股票代码 {code}）在 {start_date} 至 {report_date} 期间的所有重要公告、新闻、监管信息。

必须按照以下格式逐条输出（每条单独一行，最多6条）：
[{日期}] [{来源}] {标题} → 【利好/利空/中性】 {原因(不超过15字)}
  🔗 {原文链接}

要求：
1. 每条消息必须包含原文链接，链接要完整且可点击
2. 如果未搜到该时间段内的消息，回复：近一周未搜到相关消息
3. 如果搜索功能无法使用，回复：搜索不可用
4. 只输出上述格式的内容，不要添加任何解释性开头语或结尾语"""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 2000,
        "search": True
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        return result
    except Exception as e:
        return f"搜索失败：{str(e)}"

# ------------------------------------------------------------
# 生成一页图片
# ------------------------------------------------------------
def generate_image(stocks_data, report_date):
    font_path = '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'
    if not os.path.exists(font_path):
        font_path = fm.findfont(fm.FontProperties(family='WenQuanYi Zen Hei'))
    font_title = fm.FontProperties(fname=font_path, size=16, weight='bold')
    font_head = fm.FontProperties(fname=font_path, size=12, weight='bold')
    font_body = fm.FontProperties(fname=font_path, size=9)
    font_small = fm.FontProperties(fname=font_path, size=7)

    total_lines = 0
    for sd in stocks_data:
        total_lines += 1
        msg_text = sd["result"]
        lines = msg_text.split('\n')
        total_lines += len(lines)
        total_lines += 1

    fig_height = max(14, total_lines * 0.45 + 5)
    fig, ax = plt.subplots(figsize=(14, fig_height), facecolor='#F4F6F9')
    ax.set_facecolor('#F4F6F9')
    ax.axis('off')

    y_pos = fig_height - 0.8

    ax.text(0.5, y_pos/fig_height + 0.02, f"📈 持仓消息简报 ({report_date})", 
            transform=ax.transAxes, ha='center', fontproperties=font_title, color='#1a1a2e')
    y_pos -= 1.2

    risk_msgs = []
    for sd in stocks_data:
        for line in sd["result"].split('\n'):
            if '利空' in line or '减持' in line or '问询' in line or '处罚' in line:
                risk_msgs.append(f"🔴 {sd['name']}：{line.strip()}")
    if risk_msgs:
        ax.text(0.08, y_pos/fig_height, "⚠️ 风险预警", transform=ax.transAxes,
                fontproperties=font_head, color='#CC0000')
        y_pos -= 0.6
        for r in risk_msgs[:8]:
            ax.text(0.1, y_pos/fig_height, r, transform=ax.transAxes,
                    fontproperties=font_small, color='#333333')
            y_pos -= 0.4
    else:
        ax.text(0.08, y_pos/fig_height, "⚠️ 风险预警：今日未发现明显利空", transform=ax.transAxes,
                fontproperties=font_head, color='#555555')
        y_pos -= 0.6

    y_pos -= 0.6
    ax.axhline(y=y_pos/fig_height + 0.02, color='#E0E0E0', linewidth=0.5)

    for sd in stocks_data:
        if y_pos < 1.5:
            break
        ax.text(0.08, y_pos/fig_height, f"▌{sd['name']} ({sd['code']})", transform=ax.transAxes,
                fontproperties=font_head, color='#1a1a2e')
        y_pos -= 0.6
        lines = sd["result"].split('\n')
        for line in lines:
            if y_pos < 1.0:
                break
            line = line.strip()
            if not line:
                continue
            if '🔗' in line:
                if len(line) > 120:
                    line = line[:117] + '...'
                ax.text(0.14, y_pos/fig_height, line, transform=ax.transAxes,
                        fontproperties=font_small, color='#3366CC')
            else:
                if len(line) > 100:
                    line = line[:97] + '...'
                ax.text(0.12, y_pos/fig_height, line, transform=ax.transAxes,
                        fontproperties=font_body, color='#333333')
            y_pos -= 0.45
        y_pos -= 0.3

    ax.text(0.5, 0.02, "数据源：DeepSeek 联网搜索 | 仅供参考，不构成投资建议",
            transform=ax.transAxes, ha='center', fontproperties=font_small, color='#999999')

    plt.tight_layout(pad=2)
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()
    buf.seek(0)
    return buf.read()

# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def main():
    print(f"简报开始 - {beijing_now()}")
    stocks = load_stocks()
    if not stocks:
        send_email("消息简报 - 错误", "股票列表为空", b"")
        return

    report_date = beijing_date()
    now = beijing_now()

    morning_file = os.environ.get("MORNING_DATA_PATH", "")
    morning_msgs = {}
    if morning_file and os.path.exists(morning_file):
        try:
            with open(morning_file, "r", encoding="utf-8") as f:
                morning_msgs = json.load(f)
        except:
            pass
    is_afternoon = bool(morning_msgs)

    stocks_data = []
    for code, name in stocks:
        print(f"搜索：{name}({code})")
        result = search_stock_news(code, name, report_date)
        stocks_data.append({"name": name, "code": code, "result": result})

    text_body = f"📈 每日消息简报 | {now}\n"
    text_body += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    risk_list = []
    for sd in stocks_data:
        for line in sd["result"].split('\n'):
            if '利空' in line:
                risk_list.append(f"🔴 {sd['name']}：{line.strip()}")
    if risk_list:
        text_body += "【⚠️ 风险预警】\n" + "\n".join(risk_list[:10]) + "\n\n"
    else:
        text_body += "【⚠️ 风险预警】\n今日未发现明确利空信号\n\n"
    text_body += "【📊 个股消息及判断】\n"
    for sd in stocks_data:
        text_body += f"\n🔹 {sd['name']}（{sd['code']}）\n{sd['result']}\n"
    text_body += "\n━━━━━━━━━━━━━━━━━━━━━━\n数据源：DeepSeek 联网搜索 | 仅供参考"

    img_data = generate_image(stocks_data, report_date)

    if not is_afternoon:
        send_email(f"📈 消息简报 {now}", text_body, img_data)
        fingerprint = {}
        for sd in stocks_data:
            fingerprint[sd["code"]] = sd["result"][:300]
        with open("morning_news.json", "w", encoding="utf-8") as f:
            json.dump(fingerprint, f, ensure_ascii=False)
        print("上午简报已发送")
    else:
        new_data = []
        has_new = False
        for sd in stocks_data:
            old = morning_msgs.get(sd["code"], "")
            new_finger = sd["result"][:300]
            if new_finger != old and "未搜到" not in sd["result"] and "搜索不可用" not in sd["result"]:
                new_data.append(sd)
                has_new = True
        if has_new:
            new_text = f"📈 午间消息更新 | {now}\n"
            new_text += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            risk_list = []
            for sd in new_data:
                for line in sd["result"].split('\n'):
                    if '利空' in line:
                        risk_list.append(f"🔴 {sd['name']}：{line.strip()}")
            if risk_list:
                new_text += "【⚠️ 风险预警】\n" + "\n".join(risk_list) + "\n\n"
            new_text += "【📊 新增个股消息】\n"
            for sd in new_data:
                new_text += f"\n🔹 {sd['name']}（{sd['code']}）\n{sd['result']}\n"
            new_text += "\n━━━━━━━━━━━━━━━━━━━━━━\n数据源：DeepSeek 联网搜索 | 仅供参考"
            new_img = generate_image(new_data, report_date)
            send_email(f"📈 午间消息更新 {now}", new_text, new_img)
            print("下午新增简报已发送")
        else:
            print("无新增消息，不发送邮件")

if __name__ == "__main__":
    main()
