import requests
import smtplib
import os
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

# ------------------------------------------------------------
# 通用工具
# ------------------------------------------------------------
def send_email(subject, body):
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    to_addr = os.environ.get("EMAIL_TO")
    if not user or not password or not to_addr:
        print("错误：邮件凭证缺失")
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
    return f"0.{code}" if code.startswith("0") or code.startswith("3") else f"1.{code}"

def get_market_suffix(code):
    return "SZ" if code.startswith(("0", "3", "1")) else "SH"

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
        print("错误：找不到stocks.txt")
    return stocks

def format_amount(amount_yuan):
    if amount_yuan is None or amount_yuan == 0:
        return "0"
    yi = amount_yuan / 1e8
    if abs(yi) >= 0.01:
        return f"{yi:.2f}亿元"
    return f"{amount_yuan / 1e4:.0f}万元"

# ------------------------------------------------------------
# 数据抓取模块
# ------------------------------------------------------------
def get_basic_em(secid):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f170,f48",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json()["data"]
        if data:
            return {
                "price": data["f43"] / 100 if data.get("f43") else None,
                "change_pct": data["f170"] / 100 if data.get("f170") else None,
                "amount": data.get("f48")
            }
    except:
        pass
    return None

def get_fund_flow(secid):
    """
    获取当日主力资金流向，使用最通用的日内资金流向接口。
    返回：主力净流入（元）、主力净占比（%）
    """
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56",
        "lmt": 1,
        "klt": 101,  # 日线
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        klines = data.get("data", {}).get("klines", [])
        if klines:
            parts = klines[0].split(",")
            main_in = float(parts[1]) if len(parts) > 1 else 0
            main_pct = float(parts[5]) / 100.0 if len(parts) > 5 else 0.0
            return {"main_net_in": main_in, "main_net_pct": main_pct}
    except Exception as e:
        print(f"  资金流向获取异常：{e}")
    return {"main_net_in": 0, "main_net_pct": 0.0}

def get_notices(stock_code):
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "page_size": 3, "page_index": 1, "ann_type": "A",
        "stock_list": stock_code, "f_node": 1, "s_node": 0
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        items = r.json()["data"]["list"]
        return [f"{item['notice_date'][:10]} {item['title']}" for item in items]
    except:
        return []

def get_stock_sentiment(code):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": get_secid(code),
        "fields": "f12,f14,f92",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        rank = r.json().get("data", {}).get("f92")
        if rank and int(rank) > 0:
            return f"人气排名第{int(rank)}位"
    except:
        pass
    return "关注度低"

def get_top_holders(code):
    suffix = get_market_suffix(code)
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_EH_HOLDERS",
        "columns": "HOLDER_NAME,HOLD_NUM_CHANGE,HOLD_NUM_RATIO,END_DATE",
        "filter": f'(SECUCODE="{code}.{suffix}")(IS_HOLDORG=1)',
        "pageNumber": 1, "pageSize": 10,
        "sortTypes": -1, "sortColumns": "END_DATE",
        "source": "HSF10", "client": "PC"
    }
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        data = r.json()
        if data.get("success") and data.get("result"):
            holders = data["result"].get("data", [])
            if holders:
                latest_date = holders[0].get("END_DATE", "?")[:10]
                lines = [f"（数据截止：{latest_date}）"]
                for h in holders:
                    name = h.get("HOLDER_NAME", "")
                    if any(k in name for k in ["社保", "香港中央结算", "中国证券金融", "中央汇金"]):
                        ratio = h.get("HOLD_NUM_RATIO")
                        change = h.get("HOLD_NUM_CHANGE", 0)
                        change_str = "增持" if change > 0 else ("减持" if change < 0 else "不变")
                        if ratio is not None:
                            lines.append(f"  • {name} 持股{ratio}%，{change_str}")
                if len(lines) > 1:
                    return lines
                return ["（未发现重要机构）"]
    except:
        pass
    return ["（暂无最新数据）"]

# ------------------------------------------------------------
# 技术分析（全面加固）
# ------------------------------------------------------------
def calculate_ma(values, window):
    if len(values) >= window:
        return sum(values[-window:]) / window
    return None

def calculate_macd(closes):
    if len(closes) < 26:
        return None, None
    ema12 = closes[0]
    ema26 = closes[0]
    dif_list = []
    for price in closes:
        ema12 = ema12 * (11/13) + price * (2/13)
        ema26 = ema26 * (25/27) + price * (2/27)
        dif_list.append(ema12 - ema26)
    dea = sum(dif_list[-9:]) / 9 if len(dif_list) >= 9 else 0
    return dif_list[-1], (dif_list[-1] - dea) * 2

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = sum(max(0, closes[i] - closes[i-1]) for i in range(-period, 0))
    losses = sum(max(0, closes[i-1] - closes[i]) for i in range(-period, 0))
    if losses == 0:
        return 100.0
    return 100.0 - (100.0 / (1 + gains / losses))

def analyze_technical(code, name, secid):
    print(f"  分析 {name} 技术面...")
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101, "fqt": 1, "end": "20500101", "lmt": 60
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        klines = r.json()["data"]["klines"]
        if not klines:
            return "技术数据不足"

        closes, highs, lows, volumes = [], [], [], []
        for line in klines:
            parts = line.split(",")
            closes.append(float(parts[2]))
            highs.append(float(parts[3]))
            lows.append(float(parts[4]))
            volumes.append(int(parts[5]))

        latest = klines[-1].split(",")
        prev = klines[-2].split(",") if len(klines) > 1 else None

        date = latest[0]
        open_p = float(latest[1])
        close_p = float(latest[2])
        high_p = float(latest[3])
        low_p = float(latest[4])
        volume = int(latest[5])
        change_pct = float(latest[8]) if len(latest) > 8 else 0

        # 换手率稳健读取
        turnover = None
        try:
            if len(latest) > 10 and latest[10] and latest[10] != '-':
                turnover = float(latest[10])
        except:
            pass

        if prev:
            prev_vol = int(prev[5])
            vol_change = ((volume - prev_vol) / prev_vol * 100) if prev_vol > 0 else 0
            vol_desc = "放量" if vol_change > 20 else ("缩量" if vol_change < -20 else "量平")
        else:
            vol_change, vol_desc = 0, "量平"

        ma5 = calculate_ma(closes, 5)
        ma10 = calculate_ma(closes, 10)
        ma20 = calculate_ma(closes, 20)
        dif, macd_val = calculate_macd(closes)
        rsi = calculate_rsi(closes)

        status = []
        if ma5 and ma10 and ma20:
            if close_p > ma5 > ma10 > ma20:
                status.append("多头排列")
            elif close_p < ma5 < ma10 < ma20:
                status.append("空头排列")
            else:
                status.append("均线缠绕")
        if dif and macd_val:
            if dif > 0 and macd_val > 0:
                status.append("MACD红柱多头")
            elif dif < 0 and macd_val < 0:
                status.append("MACD绿柱空头")
        if rsi:
            if rsi > 70:
                status.append(f"RSI超买({rsi:.1f})")
            elif rsi < 30:
                status.append(f"RSI超卖({rsi:.1f})")
            else:
                status.append(f"RSI中性({rsi:.1f})")

        support = f"{min(lows[-20:]):.2f}" if lows else "?"
        resistance = f"{max(highs[-20:]):.2f}" if highs else "?"

        summary = f"日K：{date} | 开{open_p:.2f}/收{close_p:.2f} | 高{high_p:.2f}/低{low_p:.2f} | {vol_desc}({vol_change:+.1f}%)"
        if turnover:
            summary += f" | 换手{turnover:.2f}%"
        if ma5:
            summary += f"\n  均线：MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}"
        summary += f"\n  状态：{'、'.join(status)}"
        summary += f"\n  支撑/压力：近20日低{support} / 高{resistance}"

        if change_pct > 3 and vol_desc == "放量":
            summary += "\n  信号：放量突破，短线强势"
        elif change_pct < -3 and vol_desc == "放量":
            summary += "\n  信号：放量下杀，短线风险"
        elif abs(change_pct) < 1 and vol_desc == "缩量":
            summary += "\n  信号：缩量窄幅，变盘临近"

        return summary

    except Exception as e:
        print(f"  {name} 技术分析异常：{e}")
        return "技术数据解析失败"

# ------------------------------------------------------------
# 预测情报（个股专属）
# ------------------------------------------------------------
def get_predictive_intel(stock_code, stock_name):
    print(f"  获取 {stock_name} 情报...")
    titles = []

    # 研报
    try:
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "page_size": 3, "page_index": 1,
            "stock_list": stock_code,
            "f_node": 2, "s_node": 0
        }
        r = requests.get(url, params=params, timeout=5)
        for item in r.json()["data"]["list"]:
            title = item.get("title", "")
            if stock_name in title:
                titles.append(f"[研报]{title}")
    except:
        pass

    # 预警公告
    try:
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "page_size": 10, "page_index": 1,
            "stock_list": stock_code,
            "f_node": 1, "s_node": 0
        }
        r = requests.get(url, params=params, timeout=5)
        keywords = ["预测", "预警", "调出", "减持", "诉讼", "罚款", "下调", "目标价", "评级", "退市"]
        for item in r.json()["data"]["list"]:
            title = item.get("title", "")
            if any(kw in title for kw in keywords):
                titles.append(f"[预警]{title}")
    except:
        pass

    return titles[:5] if titles else ["无相关预测情报"]

# ------------------------------------------------------------
# 宏观热点
# ------------------------------------------------------------
def get_hot_sectors():
    print("获取热点板块...")
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "fid": "f62", "po": 1, "pz": 5, "pn": 1, "np": 1,
        "fltt": 2, "invt": 2, "fs": "m:90+t2",
        "fields": "f12,f14,f62,f184",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json().get("data", {})
        if data and data.get("diff"):
            lines = []
            for item in data["diff"]:
                name = item.get("f14", "?")
                main_in = item.get("f62", 0) or 0
                main_pct = (item.get("f184", 0) or 0) / 100.0
                lines.append(f"{name}（净流入{main_in/1e8:.2f}亿，占比{main_pct:.2f}%）")
            return "；\n  ".join(lines)
    except:
        pass
    return "板块数据暂不可用"

def get_finance_calendar():
    return "暂无重要事件"

# ------------------------------------------------------------
# AI 总结
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
        if sd.get("sentiment"):
            data_text += f"  人气：{sd['sentiment']}；\n"
        if sd.get("holders_info"):
            data_text += f"  股东动向：{'；'.join(sd['holders_info'])}；\n"
        if sd.get("technical"):
            data_text += f"  技术面：{sd['technical']}\n"
        if sd.get("intel") and sd['intel'] != ["无相关预测情报"]:
            data_text += f"  🔍 预测情报：{'；'.join(sd['intel'])}\n"
        if sd.get("notices"):
            data_text += f"  公告：{'；'.join(sd['notices'])}；\n"

    prompt = f"""你是一位INTJ型投资分析师。请结合所有数据，为每只股票生成专业判断。

要求：
1. 格式：[股票名]：🔴/🟢/➖ 核心分析... 关联动态：1. 动态一；2. 动态二
2. 必须引用技术面信号（如均线排列、MACD、RSI、量价关系），解释成交量和换手率的含义。
3. 若技术面数据缺失，基于价格和资金直接给出判断。
4. 最后以“整体风险：”总结组合风险。

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
    cal = get_finance_calendar()

    data_list = []
    for code, name in stocks:
        print(f"处理：{name}({code})")
        secid = get_secid(code)
        basic = get_basic_em(secid)
        flow = get_fund_flow(secid)
        notices = get_notices(code)
        sentiment = get_stock_sentiment(code)
        holders = get_top_holders(code)
        technical = analyze_technical(code, name, secid)
        intel = get_predictive_intel(code, name)

        data_list.append({
            "code": code, "name": name,
            "price": basic["price"] if basic else None,
            "change_pct": basic["change_pct"] if basic else None,
            "amount": basic["amount"] if basic else None,
            "main_net_in": flow["main_net_in"],
            "main_net_pct": flow["main_net_pct"],
            "notices": notices,
            "sentiment": sentiment,
            "holders_info": holders,
            "technical": technical,
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
        body += f"  🗣️ 情绪：{sd.get('sentiment', '获取失败')}\n"

        body += f"  🔍 股东：\n"
        for line in (sd.get("holders_info") or ["（暂无）"]):
            body += f"    {line}\n"

        if sd.get("intel") and sd['intel'] != ["无相关预测情报"]:
            body += f"  📰 情报：\n"
            for line in sd['intel']:
                body += f"    • {line}\n"

    body += "\n━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据源：东方财富 | 分析：DeepSeek AI | 仅供参考，不构成投资建议。"

    send_email(f"📈 投资简报 {now}", body)
    print("简报发送完毕")

if __name__ == "__main__":
    main()
