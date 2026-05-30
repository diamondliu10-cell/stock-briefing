import requests
import smtplib
import os
import time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime, timezone, timedelta
from io import BytesIO
import base64

# ------------------------------------------------------------
# 基础配置
# ------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_now():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")

def beijing_date():
    return datetime.now(BEIJING_TZ).strftime("%Y年%m月%d日")

def send_email(subject, html_body, img_data):
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    to_addr = os.environ.get("EMAIL_TO")
    if not user or not password or not to_addr:
        print("邮件凭证缺失")
        return
    msg = MIMEMultipart('related')
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg_alt = MIMEMultipart('alternative')
    msg.attach(msg_alt)
    msg_alt.attach(MIMEText(html_body, 'html', 'utf-8'))
    img = MIMEImage(img_data, _subtype="png")
    img.add_header('Content-ID', '<briefing_chart>')
    img.add_header('Content-Disposition', 'inline', filename='briefing.png')
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
                    cost = float(parts[2].strip()) if len(parts) >= 3 and parts[2].strip() else None
                    stocks.append((code, name, cost))
    except FileNotFoundError:
        print("stocks.txt不存在")
    return stocks

def format_amount(amount_yuan):
    if amount_yuan is None or amount_yuan == 0:
        return "0"
    yi = amount_yuan / 1e8
    if abs(yi) >= 0.01:
        return f"{yi:.2f}亿"
    wan = amount_yuan / 1e4
    return f"{wan:.0f}万"

def get_secid(code):
    if code.startswith(("0", "3")):
        return f"0.{code}"
    else:
        return f"1.{code}"

# ------------------------------------------------------------
# 带重试的数据获取
# ------------------------------------------------------------
def robust_get(func, *args, retries=2, delay=10, **kwargs):
    for attempt in range(retries + 1):
        try:
            result = func(*args, **kwargs)
            if result is not None and (not isinstance(result, pd.DataFrame) or not result.empty):
                return result
        except Exception as e:
            print(f"  尝试{attempt+1}失败: {e}")
        if attempt < retries:
            time.sleep(delay)
    return None

def get_kline_data(code, count=1):
    """获取最近count根日K线，返回DataFrame"""
    secid = get_secid(code)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62",
        "klt": 101,          # 日K
        "fqt": 1,            # 前复权
        "end": "20500101",
        "lmt": count
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()["data"]
        if data is None or not data.get("klines"):
            return None
        klines = data["klines"]
        df = pd.DataFrame([k.split(",") for k in klines],
                          columns=["date","open","close","high","low","volume","amount",
                                   "amp","pct_chg","chg","turnover","main_net_in"])
        for col in ["open","close","high","low","volume","amount","turnover","main_net_in","pct_chg"]:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except:
        return None

def get_fund_flow_multi(code, days=20):
    """获取最近N日主力净流入列表（按日期升序，最后一个为最新）"""
    secid = get_secid(code)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56",
        "lmt": days,
        "klt": 101,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        klines = r.json()["data"]["klines"]
        if not klines:
            return []
        return [float(k.split(",")[1]) for k in klines if len(k.split(",")) > 1]
    except:
        return []

def get_news(stock_code, stock_name):
    """抓取标题中包含股票名称的新闻，确保相关性"""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "page_size": 15, "page_index": 1,
        "stock_list": stock_code,
        "f_node": 0, "s_node": 0
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    relevant = []
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        items = r.json()["data"]["list"]
        for item in items:
            title = item.get("title", "")
            # 只保留标题中包含股票名称的新闻
            if stock_name in title:
                relevant.append(f"{item['notice_date'][:10]} {title}")
        return relevant[:5]
    except:
        return []

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
        "model": "deepseek-chat",  # 使用你最优质的模型
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2500
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=35)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ AI调用失败：{str(e)}"

def generate_analysis(stocks_data, report_date):
    data_text = ""
    for sd in stocks_data:
        data_text += f"【{sd['name']}（{sd['code']}）】\n"
        if sd.get("price"):
            data_text += f"最新价：{sd['price']:.2f}元，涨跌幅：{sd.get('change_pct',0):+.2f}%\n"
        k = sd.get("yest_kline")
        if k:
            data_text += f"日K数据：开盘{k['open']:.2f} 收盘{k['close']:.2f} 最高{k['high']:.2f} 最低{k['low']:.2f} 成交量{k['volume']:.0f}手 换手率{k['turnover']:.2f}%\n"
        flows = sd.get("fund_flows", {})
        data_text += f"主力资金净流入：近5日 {format_amount(flows.get('5d',0))}，近10日 {format_amount(flows.get('10d',0))}，近20日 {format_amount(flows.get('20d',0))}\n"
        news = sd.get("news", [])
        if news:
            data_text += "相关新闻（来源：东方财富）：\n"
            for n in news:
                data_text += f"  · {n}\n"
        else:
            data_text += "相关新闻：暂无\n"
        if sd.get("profit_str"):
            data_text += f"持仓盈亏：{sd['profit_str']}\n"
        data_text += "\n"

    prompt = f"""你是资深投资分析师且非常了解A股。今天的日期是 {report_date}，请基于以下真实数据撰写一份专业投资简报。

⚠️ 重要规则：
1. 报告中的日期必须为 {report_date}，不得使用其他日期。
2. 只能分析下面列出的股票，不得编造任何其他股票。
3. 消息面必须逐条列出新闻标题，然后明确判断该消息对个股是利好、利空还是中性，并简要说明理由。
4. 如果没有相关新闻，请写“近期暂无该公司相关新闻”。
5. 格式请严格遵守以下结构，不要添加无关的解释性文字。

【一、⚠️ 风险提示】
- 用🔴标记存在明显风险的个股，说明风险原因（如技术破位、资金持续流出、重大利空消息等）。
- 若无明显风险，则写“今日无特别风险提示”。

【二、📊 个股深度分析】
对每只股票，按以下格式输出：
股票名（代码）：🔴/🟢/➖
· 技术面：（趋势、量价关系、支撑压力等，1-2句）
· 资金面：（主力动向、多日净额变化，1句）
· 消息面：
  ① [来源]新闻标题 → 利好/利空/中性，理由（1句）
  ② [来源]新闻标题 → 利好/利空/中性，理由（1句）
  （最多列3条，如无消息则写“近期暂无该公司相关新闻”）
· 建议：持有/加仓/减仓/观望（1句理由）

{data_text}"""
    return call_deepseek(prompt)

# ------------------------------------------------------------
# 生成信息图（完整展示所有关键数据）
# ------------------------------------------------------------
def create_chart(stocks_data, report_date):
    # 中文字体
    font_path = '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'
    if not os.path.exists(font_path):
        font_path = fm.findfont(fm.FontProperties(family='WenQuanYi Zen Hei'))
    zh_font = fm.FontProperties(fname=font_path, size=9)
    zh_font_sm = fm.FontProperties(fname=font_path, size=7)
    zh_font_title = fm.FontProperties(fname=font_path, size=12, weight='bold')

    n = len(stocks_data)
    fig, ax = plt.subplots(figsize=(10, max(6, n * 1.2)))

    # 背景
    fig.patch.set_facecolor('#FAFAFA')
    ax.set_facecolor('#FAFAFA')
    ax.set_xlim(0, 10)
    ax.set_ylim(0, n + 2)
    ax.axis('off')

    # 标题
    ax.text(5, n + 1.5, f"📈 投资简报 | {report_date}", ha='center', fontproperties=zh_font_title, color='#222222')
    ax.text(5, n + 1.1, "数据源：东方财富 | 分析：DeepSeek AI | 仅供参考", ha='center', fontproperties=zh_font_sm, color='#999999')
    ax.axhline(y=n + 0.9, xmin=0.05, xmax=0.95, color='#E0E0E0', linewidth=0.5)

    # 每只股票一行
    for i, sd in enumerate(stocks_data):
        y = n - i - 0.5

        # 风险标签（基于20日资金流向）
        flows = sd.get("fund_flows", {})
        total_20d = flows.get('20d', 0)
        if total_20d > 50000000:
            risk_label = "🟢"
        elif total_20d < -50000000:
            risk_label = "🔴"
        else:
            risk_label = "🟡"

        # 第一行：名称 + 价格 + 涨跌幅
        price_str = f"{sd['price']:.2f}" if sd.get("price") else "N/A"
        change_str = f"{sd.get('change_pct', 0):+.2f}%" if sd.get('change_pct') is not None else "N/A"
        name_str = f"{risk_label} {sd['name']}({sd['code']})  {price_str}元  {change_str}"

        # 换手率和盈亏
        k = sd.get("yest_kline")
        turnover_str = f"换手{k['turnover']:.2f}%" if k and k.get('turnover') else ""
        profit_str = sd.get("profit_str", "")

        ax.text(0.3, y + 0.3, name_str, fontproperties=zh_font, color='#222222', va='center')
        if turnover_str or profit_str:
            extra_str = f"{turnover_str}  {profit_str}"
            ax.text(9.7, y + 0.3, extra_str, fontproperties=zh_font_sm, color='#666666', va='center', ha='right')

        # 第二行：资金流向
        fund_str = f"主力资金：5日 {format_amount(flows.get('5d',0))} | 10日 {format_amount(flows.get('10d',0))} | 20日 {format_amount(flows.get('20d',0))}"
        ax.text(0.3, y - 0.15, fund_str, fontproperties=zh_font_sm, color='#555555', va='center')

        # 第三行：相关新闻（最多2条，截断过长文本）
        news = sd.get("news", [])
        if news:
            news_lines = news[:2]
            news_str = "📰 " + " | ".join(news_lines)
            if len(news_str) > 80:
                news_str = news_str[:77] + "..."
            ax.text(0.3, y - 0.45, news_str, fontproperties=zh_font_sm, color='#888888', va='center')
        else:
            ax.text(0.3, y - 0.45, "📰 暂无相关新闻", fontproperties=zh_font_sm, color='#BBBBBB', va='center')

        # 行分隔线
        ax.axhline(y=y - 0.8, xmin=0.05, xmax=0.95, color='#EEEEEE', linewidth=0.3)

    plt.tight_layout()
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
        send_email("股票简报 - 错误", "<p>股票列表为空</p>", b"")
        return

    now = beijing_now()
    report_date = beijing_date()
    stocks_data = []

    for code, name, cost in stocks:
        print(f"处理：{name}({code})")
        # 获取日K线（最近1根）
        kline_df = robust_get(get_kline_data, code, count=1, retries=2, delay=8)
        # 获取20日主力资金流向
        fund_flows = robust_get(get_fund_flow_multi, code, days=20, retries=2, delay=8) or []
        # 获取相关新闻
        news = robust_get(get_news, code, name, retries=1, delay=5) or []

        yest_kline = None
        price = None
        change_pct = None
        if kline_df is not None and not kline_df.empty:
            last = kline_df.iloc[-1]
            yest_kline = {
                "open": last["open"],
                "close": last["close"],
                "high": last["high"],
                "low": last["low"],
                "volume": last["volume"],
                "turnover": last["turnover"] if pd.notna(last["turnover"]) else 0.0
            }
            price = last["close"]
            change_pct = last["pct_chg"] if pd.notna(last["pct_chg"]) else 0.0

        # 根据实际数据长度计算5/10/20日净流入
        def safe_sum(lst, n):
            if len(lst) >= n:
                return sum(lst[-n:])
            elif lst:
                return sum(lst)
            return 0

        fund_summary = {
            "5d": safe_sum(fund_flows, 5),
            "10d": safe_sum(fund_flows, 10),
            "20d": safe_sum(fund_flows, 20)
        }

        profit_str = ""
        if price and cost:
            profit_pct = (price - cost) / cost * 100
            profit_str = f"成本{cost:.2f} 盈亏{profit_pct:+.1f}%"

        stocks_data.append({
            "name": name,
            "code": code,
            "price": price,
            "change_pct": change_pct,
            "yest_kline": yest_kline,
            "fund_flows": fund_summary,
            "news": news,
            "profit_str": profit_str
        })

    # 生成图片
    print("生成信息图...")
    img_data = create_chart(stocks_data, report_date)

    # 生成AI分析
    print("请求DeepSeek分析...")
    ai_analysis = generate_analysis(stocks_data, report_date)

    # 构建HTML邮件
    html_body = f"""
    <html>
    <head>
    <style>
        body {{ font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; background-color: #f5f5f5; padding: 10px; }}
        .card {{ background: white; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .title {{ font-size: 18px; font-weight: bold; color: #333; margin-bottom: 10px; }}
        .analysis {{ white-space: pre-wrap; font-size: 13px; line-height: 1.6; color: #444; }}
        .footer {{ font-size: 11px; color: #999; margin-top: 10px; text-align: center; }}
        img {{ max-width: 100%; border-radius: 8px; }}
    </style>
    </head>
    <body>
        <div class="card">
            <div class="title">📈 投资简报 | {now}</div>
            <div class="analysis">{ai_analysis}</div>
        </div>
        <div class="card">
            <img src="cid:briefing_chart" alt="简报图表">
        </div>
        <div class="footer">数据源：东方财富 | 分析：DeepSeek AI | 仅供参考，不构成投资建议</div>
    </body>
    </html>
    """

    send_email(f"📈 投资简报 {now}", html_body, img_data)
    print("简报发送完毕")

if __name__ == "__main__":
    main()
