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
# 数据获取
# ------------------------------------------------------------
def get_fund_flow_rank(code):
    """从个股资金流排名接口获取当日主力净流入和占比"""
    secid = get_secid(code)
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f62,f184,f43,f170,f48",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        data = r.json().get("data", {})
        main_in = data.get("f62", 0) or 0
        main_pct = (data.get("f184", 0) or 0) / 100.0
        price = data.get("f43", 0) / 100 if data.get("f43") else None
        change_pct = data.get("f170", 0) / 100 if data.get("f170") else None
        amount = data.get("f48", 0)
        return {
            "main_net_in": main_in,
            "main_net_pct": main_pct,
            "price": price,
            "change_pct": change_pct,
            "amount": amount
        }
    except:
        return {"main_net_in": 0, "main_net_pct": 0.0, "price": None, "change_pct": None, "amount": 0}

def get_fund_flow_history(code, days=20):
    """获取历史主力资金净流入列表"""
    secid = get_secid(code)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56",
        "lmt": days, "klt": 101,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        klines = r.json()["data"].get("klines", [])
        flows = []
        for k in klines:
            parts = k.split(",")
            if len(parts) > 1:
                flows.append(float(parts[1]))
        return flows
    except:
        return []

def get_kline_data(code, count=1):
    """获取最近count根日K线"""
    secid = get_secid(code)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62",
        "klt": 101, "fqt": 1, "end": "20500101", "lmt": count
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

def get_all_news(stock_code):
    """获取个股全部公告和资讯，不做名称过滤，由AI判断相关性"""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "page_size": 10, "page_index": 1,
        "stock_list": stock_code,
        "f_node": 0, "s_node": 0
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        items = r.json()["data"]["list"]
        return [f"{item['notice_date'][:10]} {item['title']}" for item in items]
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
        "model": "deepseek-chat",
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
        data_text += f"最新价：{sd['price']}元，涨跌幅：{sd['change_pct']}%\n"
        data_text += f"成交额：{format_amount(sd.get('amount', 0))}\n"
        k = sd.get("yest_kline")
        if k:
            data_text += f"日K：开盘{k['open']} 收盘{k['close']} 最高{k['high']} 最低{k['low']} 成交量{k['volume']}手 换手率{k['turnover']}%\n"
        flows = sd.get("fund_flows", {})
        data_text += f"今日主力净流入：{format_amount(flows.get('today', 0))}，占比{flows.get('today_pct', 0):.2f}%\n"
        data_text += f"近5日累计净流入：{format_amount(flows.get('5d', 0))}\n"
        data_text += f"近10日累计净流入：{format_amount(flows.get('10d', 0))}\n"
        data_text += f"近20日累计净流入：{format_amount(flows.get('20d', 0))}\n"
        news = sd.get("news", [])
        if news:
            data_text += "近期公告/资讯：\n"
            for n in news[:6]:
                data_text += f"  · {n}\n"
        else:
            data_text += "近期公告/资讯：暂无\n"
        if sd.get("profit_str"):
            data_text += f"持仓：{sd['profit_str']}\n"
        data_text += "\n"

    prompt = f"""你是资深投资分析师。今天日期：{report_date}。请基于以下真实数据撰写投资简报。

⚠️ 规则：
1. 日期必须为 {report_date}。
2. 只能分析下面列出的股票。
3. 消息面要逐条列出，判断利好/利空/中性并说明理由。
4. 对消息列表进行过滤，只保留与该公司直接相关的（含公司名称、主营业务、行业政策等），把无关的（如其他公司的公告、基金合同变更等）去掉，不要列出无关消息。

【一、⚠️ 风险提示】
用🔴标记存在风险的个股及原因。若无则写"今日无特别风险提示"。

【二、📊 个股分析】
每只格式：
股票名（代码）：🔴/🟢/➖
· 技术面：（趋势、量价关系，1-2句）
· 资金面：今日主力净流入XXX，占比X%；5日/10日/20日累计XXX，分析方向（1-2句）
· 消息面：逐条列出相关消息，标注利好/利空/中性+理由（最多3条，无关的跳过）
· 建议：持有/加仓/减仓/观望（1句理由）

{data_text}"""
    return call_deepseek(prompt)

# ------------------------------------------------------------
# PPT风格信息图
# ------------------------------------------------------------
def create_chart(stocks_data, report_date):
    font_path = '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'
    if not os.path.exists(font_path):
        font_path = fm.findfont(fm.FontProperties(family='WenQuanYi Zen Hei'))
    font_title = fm.FontProperties(fname=font_path, size=18, weight='bold')
    font_header = fm.FontProperties(fname=font_path, size=12, weight='bold')
    font_body = fm.FontProperties(fname=font_path, size=10)
    font_sm = fm.FontProperties(fname=font_path, size=8)
    font_micro = fm.FontProperties(fname=font_path, size=7)

    n = len(stocks_data)
    # 高密度布局
    fig = plt.figure(figsize=(12, 2.5 + n * 1.8), facecolor='#1a1a2e')
    gs = fig.add_gridspec(1, 2, width_ratios=[3, 2], hspace=0, wspace=0.02)
    ax_left = fig.add_subplot(gs[0, 0])
    ax_right = fig.add_subplot(gs[0, 1])

    # 全局背景
    for ax in [ax_left, ax_right]:
        ax.set_facecolor('#1a1a2e')
        ax.axis('off')

    # ---------- 左栏：个股关键数据 ----------
    ax_left.set_xlim(0, 10)
    ax_left.set_ylim(0, n + 1.5)
    # 标题
    ax_left.text(5, n + 1.0, f"📈 投资简报 | {report_date}", ha='center', fontproperties=font_title, color='#e0e0e0')
    ax_left.text(5, n + 0.5, "每日开盘前自动生成 | 数据源：东方财富 | 分析：DeepSeek AI", ha='center', fontproperties=font_sm, color='#888888')

    # 列标题
    col_headers = ["股票", "现价/涨跌", "换手率", "主力5日", "主力20日", "盈亏"]
    col_x = [0.2, 2.0, 4.2, 5.6, 7.2, 8.8]
    for hx, htext in zip(col_x, col_headers):
        ax_left.text(hx, n, htext, fontproperties=font_header, color='#cccccc')

    for i, sd in enumerate(stocks_data):
        y = n - i - 1
        flows = sd.get("fund_flows", {})
        total_20d = flows.get('20d', 0)
        risk_icon = "🟢" if total_20d > 50000000 else "🔴" if total_20d < -50000000 else "🟡"

        # 名称
        ax_left.text(0.2, y, f"{risk_icon} {sd['name']}", fontproperties=font_body, color='#ffffff', va='center')
        ax_left.text(1.5, y, sd['code'], fontproperties=font_micro, color='#999999', va='center')
        # 现价/涨跌
        price_txt = f"{sd['price']}" if sd.get('price') else "N/A"
        chg_txt = f"{sd['change_pct']}%" if sd.get('change_pct') is not None else ""
        chg_color = '#ff4444' if (isinstance(sd.get('change_pct'), (int, float)) and sd['change_pct'] < 0) else '#44ff44'
        ax_left.text(2.0, y + 0.2, price_txt, fontproperties=font_body, color='#ffffff', va='center')
        ax_left.text(2.0, y - 0.3, chg_txt, fontproperties=font_sm, color=chg_color, va='center')
        # 换手率
        k = sd.get("yest_kline")
        turnover = f"{k['turnover']:.1f}%" if k and k.get('turnover') else "N/A"
        ax_left.text(4.2, y, turnover, fontproperties=font_body, color='#ffffff', va='center')
        # 主力5日
        fund5 = format_amount(flows.get('5d', 0))
        ax_left.text(5.6, y, fund5, fontproperties=font_body, color='#ffcc00', va='center')
        # 主力20日
        fund20 = format_amount(flows.get('20d', 0))
        ax_left.text(7.2, y, fund20, fontproperties=font_body, color='#ffcc00', va='center')
        # 盈亏
        profit = sd.get("profit_str", "")
        ax_left.text(8.8, y, profit if profit else "未设成本", fontproperties=font_sm, color='#cccccc', va='center')
        # 分隔线
        ax_left.axhline(y=y - 0.6, xmin=0.01, xmax=0.99, color='#333355', linewidth=0.3)

    # ---------- 右栏：新闻摘要 ----------
    ax_right.set_xlim(0, 10)
    ax_right.set_ylim(0, n + 1.5)
    ax_right.text(5, n + 1.0, "📰 最新资讯速览", ha='center', fontproperties=font_header, color='#e0e0e0')
    ax_right.text(5, n + 0.5, "近7日公告/新闻 | 由AI判断相关性", ha='center', fontproperties=font_sm, color='#888888')

    row_idx = 0
    for i, sd in enumerate(stocks_data):
        news = sd.get("news", [])
        if news:
            # 股票名
            ax_right.text(0.3, n - row_idx - 0.3, f"▸ {sd['name']}", fontproperties=font_body, color='#ffcc00', va='center')
            row_idx += 0.5
            for nline in news[:3]:
                # 截断过长标题
                display = nline if len(nline) <= 55 else nline[:52] + "..."
                ax_right.text(0.8, n - row_idx - 0.3, f"• {display}", fontproperties=font_micro, color='#cccccc', va='center')
                row_idx += 0.5
                if row_idx > n + 0.2:
                    break
            row_idx += 0.3
        if row_idx > n + 0.2:
            break

    plt.tight_layout(pad=1.5)
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=180, bbox_inches='tight', facecolor=fig.get_facecolor())
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
        # 获取当日资金和行情
        rank_data = get_fund_flow_rank(code)
        price = rank_data.get("price")
        change_pct = rank_data.get("change_pct")
        amount = rank_data.get("amount", 0)
        today_main = rank_data.get("main_net_in", 0)
        today_pct = rank_data.get("main_net_pct", 0.0)

        # 获取历史资金流向
        hist_flows = get_fund_flow_history(code, days=20)

        # 获取日K线
        kline_df = get_kline_data(code, count=1)
        yest_kline = None
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
            if price is None:
                price = last["close"]
            if change_pct is None:
                change_pct = last["pct_chg"] if pd.notna(last["pct_chg"]) else 0.0

        # 获取新闻（不做名称过滤）
        news = get_all_news(code)

        # 计算多日资金
        def safe_sum(lst, n):
            if len(lst) >= n:
                return sum(lst[-n:])
            elif lst:
                return sum(lst)
            return 0

        fund_summary = {
            "today": today_main,
            "today_pct": today_pct,
            "5d": safe_sum(hist_flows, 5),
            "10d": safe_sum(hist_flows, 10),
            "20d": safe_sum(hist_flows, 20)
        }

        profit_str = ""
        if price and cost:
            profit_pct = (price - cost) / cost * 100
            profit_str = f"盈亏{profit_pct:+.1f}%"

        stocks_data.append({
            "name": name, "code": code,
            "price": price, "change_pct": change_pct,
            "amount": amount,
            "yest_kline": yest_kline,
            "fund_flows": fund_summary,
            "news": news,
            "profit_str": profit_str
        })

    # 生成图片
    print("生成PPT风格信息图...")
    img_data = create_chart(stocks_data, report_date)

    # 生成AI分析
    print("请求DeepSeek分析...")
    ai_analysis = generate_analysis(stocks_data, report_date)

    # 构建HTML邮件
    html_body = f"""
    <html>
    <head>
    <style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; background: #f0f0f0; margin: 0; padding: 10px; }}
        .card {{ background: white; border-radius: 10px; padding: 20px; margin: 10px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .title {{ font-size: 20px; font-weight: bold; color: #222; margin-bottom: 12px; }}
        .analysis {{ white-space: pre-wrap; font-size: 14px; line-height: 1.7; color: #333; }}
        .footer {{ text-align: center; font-size: 11px; color: #aaa; margin-top: 10px; }}
        img {{ max-width: 100%; border-radius: 8px; border: 1px solid #ddd; }}
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
