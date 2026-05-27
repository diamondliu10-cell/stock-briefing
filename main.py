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
        print(f"错误：邮件发送失败 - {e}")

def get_secid(code):
    if code.startswith("0") or code.startswith("3"):
        return f"0.{code}"
    else:
        return f"1.{code}"

def get_market_suffix(code):
    if code.startswith(("0", "3", "1")):
        return "SZ"
    else:
        return "SH"

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
        print("错误：找不到stocks.txt文件。")
    return stocks

def format_amount(amount_yuan):
    if amount_yuan is None or amount_yuan == 0:
        return "0"
    yi = amount_yuan / 1e8
    if abs(yi) >= 0.01:
        return f"{yi:.2f}亿元"
    wan = amount_yuan / 1e4
    return f"{wan:.0f}万元"

# ------------------------------------------------------------
# 数据抓取模块（高可用版）
# ------------------------------------------------------------
def get_basic_em(secid):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f170,f48",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json()["data"]
        if data:
            return {
                "price": data["f43"] / 100 if data.get("f43") else None,
                "change_pct": data["f170"] / 100 if data.get("f170") else None,
                "amount": data["f48"] if data.get("f48") else None
            }
    except:
        pass
    return None

def get_fund_flow(secid):
    """主力资金，更换为更稳定的字段组合"""
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f62,f184,f66,f72",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json().get("data", {})
        main_in = data.get("f62", 0) or data.get("f66", 0) or 0
        main_pct = (data.get("f184", 0) or data.get("f72", 0) or 0) / 100.0
        return {"main_net_in": main_in, "main_net_pct": main_pct}
    except:
        return {"main_net_in": 0, "main_net_pct": 0.0}

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

def get_stock_sentiment(code):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": get_secid(code),
        "fields": "f12,f14,f92",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json().get("data", {})
        rank = data.get("f92", None)
        if rank is not None and int(rank) > 0:
            return f"人气排名第{int(rank)}位"
        return "关注度低"
    except:
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
                return ["（未发现重要机构持仓）"]
        else:
            return ["（暂无最新股东数据）"]
    except:
        return ["（暂无最新股东数据）"]

# ------------------------------------------------------------
# 增强技术面分析模块（修复了数据兼容性）
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
    macd_val = (dif_list[-1] - dea) * 2
    return dif_list[-1], macd_val

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = 0
    losses = 0
    for i in range(-period, 0):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - (100.0 / (1 + rs))

def analyze_technical(code, name, secid):
    """专业版技术分析，增强数据容错"""
    print(f"  分析 {name} 技术面...")
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101,
        "fqt": 1,
        "end": "20500101",
        "lmt": 60
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        klines = r.json()["data"]["klines"]
        if not klines:
            return "技术数据获取失败"
        
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
        
        # 换手率字段稳健处理
        turnover = None
        try:
            if len(latest) > 10 and latest[10] and latest[10] != '-':
                turnover = float(latest[10])
        except:
            pass
            
        change_pct = float(latest[8]) if len(latest) > 8 else 0
        
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
        
        status_parts = []
        if ma5 and ma10 and ma20:
            if close_p > ma5 > ma10 > ma20:
                status_parts.append("多头排列")
            elif close_p < ma5 < ma10 < ma20:
                status_parts.append("空头排列")
            else:
                status_parts.append("均线缠绕")
                
        if dif and macd_val:
            if dif > 0 and macd_val > 0:
                status_parts.append("MACD红柱多头")
            elif dif < 0 and macd_val < 0:
                status_parts.append("MACD绿柱空头")
            else:
                status_parts.append("MACD方向不明")
                
        if rsi:
            if rsi > 70:
                status_parts.append(f"RSI超买({rsi:.1f})")
            elif rsi < 30:
                status_parts.append(f"RSI超卖({rsi:.1f})")
            else:
                status_parts.append(f"RSI中性({rsi:.1f})")
        
        support = f"{min(lows[-20:]):.2f}" if len(lows) >= 20 else "?"
        resistance = f"{max(highs[-20:]):.2f}" if len(highs) >= 20 else "?"
        
        summary = f"日K：{date} | 开{open_p:.2f}/收{close_p:.2f} | 高{high_p:.2f}/低{low_p:.2f} | {vol_desc}（量变{vol_change:+.1f}%）"
        if turnover:
            summary += f" | 换手{turnover:.2f}%"
        if ma5 and ma10 and ma20:
            summary += f"\n  均线：MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}"
        summary += f"\n  技术状态：{'、'.join(status_parts)}"
        summary += f"\n  支撑/压力：近20日低{support} / 高{resistance}"
        
        if change_pct > 3 and vol_desc == "放量":
            summary += "\n  信号：放量突破，短线强势"
        elif change_pct < -3 and vol_desc == "放量":
            summary += "\n  信号：放量下杀，短线风险"
        elif abs(change_pct) < 1 and vol_desc == "缩量":
            summary += "\n  信号：窄幅缩量，变盘临近"
            
        return summary
        
    except Exception as e:
        print(f"  技术分析异常：{e}")
        return "技术数据分析出错"

# ------------------------------------------------------------
# 预测性情报模块（彻底重写，只抓个股专属信息）
# ------------------------------------------------------------
def get_predictive_intel(stock_code, stock_name):
    """抓取个股专属的研报和预警公告"""
    print(f"  获取 {stock_name} 专属情报...")
    all_titles = []
    
    # 1. 个股专属研报
    try:
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "page_size": 3, "page_index": 1,
            "stock_list": stock_code,
            "f_node": 2,  # 研报
            "s_node": 0
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params=params, headers=headers, timeout=5)
        items = r.json()["data"]["list"]
        for item in items:
            title = item.get("title", "")
            if title and stock_name in title:
                all_titles.append(f"[研报]{title}")
    except:
        pass

    # 2. 带有预测、预警关键词的公告
    try:
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "page_size": 10, "page_index": 1,
            "stock_list": stock_code,
            "f_node": 1, "s_node": 0
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params=params, headers=headers, timeout=5)
        items = r.json()["data"]["list"]
        keywords = ["预测", "预警", "调出", "减持", "诉讼", "罚款", "下调", "目标价", "评级", "退市"]
        for item in items:
            title = item.get("title", "")
            if any(kw in title for kw in keywords):
                all_titles.append(f"[预警]{title}")
    except:
        pass

    if all_titles:
        return all_titles[:5]
    return ["无相关预测情报"]

# ------------------------------------------------------------
# 宏观模块
# ------------------------------------------------------------
def get_hot_sectors():
    print("获取资金热点板块...")
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "fid": "f62",
        "po": 1, "pz": 5, "pn": 1, "np": 1,
        "fltt": 2, "invt": 2,
        "fs": "m:90+t2",
        "fields": "f12,f14,f62,f184",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json().get("data", {})
        if data and data.get("diff"):
            lines = []
            for item in data["diff"]:
                name = item.get("f14", "?")
                main_in = item.get("f62", 0) or 0
                main_pct = (item.get("f184", 0) or 0) / 100.0
                lines.append(f"{name}（净流入{main_in/1e8:.2f}亿，占比{main_pct:.2f}%）")
            return "；\n  ".join(lines)
        print("  热点板块数据为空")
    except Exception as e:
        print(f"  热点板块获取异常：{e}")
    return "板块数据暂时不可用"

def get_finance_calendar():
    return "暂无重要事件提醒"

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
2. 必须引用技术面信号（如均线排列、MACD状态等）和预测情报（如有）。
3. 最后以“整体风险：”总结组合风险。

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
    print(f"简报任务开始 - {beijing_now()}")
    stocks = load_stocks()
    if not stocks:
        send_email("股票简报 - 错误", "股票列表为空")
        return

    hot_sectors = get_hot_sectors()
    calendar = get_finance_calendar()

    stocks_data = []
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

        stocks_data.append({
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

    print("请求AI分析...")
    ai_summary = generate_ai_summary(stocks_data, hot_sectors, calendar)

    now = beijing_now()
    body = f"📈 智能深度简报 ({now} 北京时间)\n"
    body += "━━━━━━━━━━━━━━━━━━━━\n\n"

    body += f"【🔥 市场热点板块】\n  {hot_sectors}\n\n"
    body += f"【📅 今日关注】\n  {calendar}\n\n"

    if ai_summary and not ai_summary.startswith("❌"):
        body += "【🧠 AI核心判断】\n"
        body += ai_summary + "\n\n"
    else:
        body += f"【⚠️ AI状态】\n{ai_summary or 'AI 返回为空'}\n\n"

    body += "━━━━━━━━━━━━━━━━━━━━\n【📋 详细数据】\n"

    for sd in stocks_data:
        body += f"\n【{sd['name']}】({sd['code']})\n"
        if sd.get("price"):
            pct = sd['change_pct']
            label = ""
            if pct is not None:
                if pct >= 2:
                    label = " 🟢"
                elif pct <= -2:
                    label = " 🔴"
            body += f"  💰 {sd['price']}元 | {pct}%{label}\n"
            if sd.get("amount"):
                body += f"  📊 成交 {format_amount(sd['amount'])}\n"

        body += f"  💵 主力：{format_amount(sd['main_net_in'])} (占比{sd['main_net_pct']:.2f}%)\n"
        
        if sd.get("technical"):
            body += f"  📈 技术：{sd['technical']}\n"
        else:
            body += f"  📈 技术：获取失败\n"
        
        body += f"  🗣️ 情绪：{sd.get('sentiment', '获取失败')}\n"

        body += f"  🔍 股东：\n"
        for line in (sd.get("holders_info") or ["（暂无最新数据）"]):
            body += f"    {line}\n"

        if sd.get("intel") and sd['intel'] != ["无相关预测情报"]:
            body += f"  📰 情报：\n"
            for line in sd['intel']:
                body += f"    • {line}\n"

    body += "\n━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据源：东方财富 | 分析：DeepSeek AI | 仅供参考，不构成投资建议。"

    print("发送邮件...")
    send_email(f"📈 投资简报 {now}", body)
    print(f"任务结束 - {beijing_now()}")

if __name__ == "__main__":
    main()
