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

# 北京时间时区
BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_now():
    """获取当前北京时间"""
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")

# ------------------------------------------------------------
# 通用工具
# ------------------------------------------------------------
def send_email(subject, body):
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    to_addr = os.environ.get("EMAIL_TO")
    if not user or not password or not to_addr:
        print("错误：邮件凭证缺失，请检查 GitHub Secrets。")
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
        print("错误：找不到stocks.txt文件，请检查仓库根目录。")
    return stocks

def format_amount(amount_yuan):
    if amount_yuan is None:
        return "0"
    yi = amount_yuan / 1e8
    if abs(yi) >= 0.01:
        return f"{yi:.2f}亿元"
    wan = amount_yuan / 1e4
    return f"{wan:.0f}万元"

# ------------------------------------------------------------
# 数据抓取模块
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
        if data:
            return {
                "price": data["f43"] / 100 if data.get("f43") else None,
                "change_pct": data["f170"] / 100 if data.get("f170") else None,
                "amount": data["f48"] if data.get("f48") else None
            }
        else:
            return None
    except Exception as e:
        print(f"  警告：获取{secid}行情失败 - {e}")
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
    print(f"  正在获取 {name} 行情...")
    result = get_basic_em(secid)
    if result and result["price"] is not None:
        return result
    return get_basic_sina(get_sina_code(code))

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

def get_news(stock_code):
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "page_size": 5, "page_index": 1,
        "stock_list": stock_code,
        "f_node": 0, "s_node": 0
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        items = r.json()["data"]["list"]
        return [f"{item['notice_date'][:10]} {item['title']}" for item in items]
    except:
        return []

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
# 技术面分析模块（修复了接口URL）
# ------------------------------------------------------------
def get_kline_data(code, secid, period="daily", limit=20):
    """获取日K或周K数据，修复了请求URL"""
    klt_map = {"daily": 101, "weekly": 102}
    klt = klt_map.get(period, 101)
    
    # 修复后的历史K线接口
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbf30c78",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": klt,
        "fqt": 1,  # 前复权
        "end": "20500101",
        "lmt": limit
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json()
        if data.get("data") and data["data"].get("klines"):
            return data["data"]["klines"]
        print(f"    警告：{period}K线数据为空 - {r.text[:200]}")
        return []
    except Exception as e:
        print(f"    错误：获取{period}K线失败 - {e}")
        return []

def analyze_technical(code, name, secid):
    """分析个股技术面并返回文字摘要"""
    print(f"  正在分析 {name} 技术面...")
    daily_k = get_kline_data(code, secid, "daily", 20)
    weekly_k = get_kline_data(code, secid, "weekly", 10)
    
    if not daily_k:
        return "技术数据获取失败"
    
    try:
        last_day = daily_k[-1].split(",")
        prev_day = daily_k[-2].split(",") if len(daily_k) >= 2 else None
        
        date = last_day[0]
        open_price = float(last_day[1])
        close_price = float(last_day[2])
        high = float(last_day[3])
        low = float(last_day[4])
        volume = int(last_day[5])
        turnover_rate = float(last_day[10]) if len(last_day) > 10 and last_day[10] != '-' else None
        
        change_pct = float(last_day[8]) if len(last_day) > 8 else 0
        
        if prev_day:
            prev_volume = int(prev_day[5])
            vol_change = ((volume - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0
            vol_desc = "放量" if vol_change > 20 else ("缩量" if vol_change < -20 else "量平")
        else:
            vol_change = 0
            vol_desc = "量平"
        
        weekly_desc = "数据不足"
        if len(weekly_k) >= 2:
            last_week = weekly_k[-1].split(",")
            prev_week = weekly_k[-2].split(",")
            if len(last_week) > 2 and len(prev_week) > 2:
                last_week_close = float(last_week[2])
                prev_week_close = float(prev_week[2])
                weekly_change = (last_week_close - prev_week_close) / prev_week_close * 100
                if weekly_change > 3:
                    weekly_desc = f"周线趋势向上({weekly_change:+.2f}%)"
                elif weekly_change < -3:
                    weekly_desc = f"周线趋势向下({weekly_change:+.2f}%)"
                else:
                    weekly_desc = f"周线横盘({weekly_change:+.2f}%)"
        
        summary = f"日K：{date} | 开{open_price:.2f}/收{close_price:.2f} | 高{high:.2f}/低{low:.2f} | {vol_desc}（量变{vol_change:+.1f}%）"
        if turnover_rate is not None:
            summary += f" | 换手率{turnover_rate:.2f}%"
        summary += f"\n  周K：{weekly_desc}"
        
        if change_pct > 2 and vol_desc == "放量":
            summary += " | 放量上涨，短线偏强"
        elif change_pct < -2 and vol_desc == "放量":
            summary += " | 放量下跌，短线偏弱"
        elif abs(change_pct) < 1 and vol_desc == "缩量":
            summary += " | 窄幅缩量整理"
        
        return summary
    except Exception as e:
        print(f"  错误：技术分析处理异常 - {e}")
        return "技术数据分析出错"

# ------------------------------------------------------------
# 宏观模块：市场热点板块
# ------------------------------------------------------------
def get_hot_sectors():
    """抓取全市场主力资金流入最多的5个行业板块，修复了请求参数"""
    print("正在获取资金热点板块...")
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "fid": "f62",
        "po": 1, "pz": 5, "pn": 1, "np": 1,
        "fltt": 2, "invt": 2,
        "fs": "m:90+t2",  # 行业板块
        "fields": "f12,f14,f62,f184",
        "ut": "fa5fd1943c7b386f172d6893dbf30c78"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json().get("data", {})
        if not data or not data.get("diff"):
            print(f"  警告：热点板块数据为空 - {r.text[:200]}")
            return "获取失败"
        
        lines = []
        for item in data["diff"]:
            name = item.get("f14", "?")
            main_in = item.get("f62", 0) or 0
            main_pct = (item.get("f184", 0) or 0) / 100.0
            lines.append(f"{name}（主力净流入{main_in/1e8:.2f}亿，占比{main_pct:.2f}%）")
        return "；\n  ".join(lines)
    except Exception as e:
        print(f"  错误：获取热点板块失败 - {e}")
        return "获取失败"

def get_finance_calendar():
    # 暂时保留占位符，未来可升级
    return "暂无重要事件提醒（可后续接入专业财经日历API）"

# ------------------------------------------------------------
# AI 总结
# ------------------------------------------------------------
def generate_ai_summary(stocks_data, hot_sectors, calendar):
    if not DEEPSEEK_API_KEY:
        return "❌ 未设置 DEEPSEEK_API_KEY"

    data_text = f"【今日市场热点板块】\n  {hot_sectors}\n\n"
    data_text += f"【重要财经提醒】\n  {calendar}\n\n"
    data_text += "【持仓股票数据（含技术面）】\n"
    
    for sd in stocks_data:
        data_text += f"\n{sd['name']}({sd['code']})：\n"
        if sd.get("price"):
            data_text += f"  现价{sd['price']}元，涨跌幅{sd['change_pct']}%"
        if sd.get("amount"):
            data_text += f"，成交额{format_amount(sd['amount'])}；"
        data_text += f"主力资金：{format_amount(sd['main_net_in'])}，占比{sd['main_net_pct']:.2f}%；\n"
        if sd.get("sentiment"):
            data_text += f"  人气：{sd['sentiment']}；\n"
        if sd.get("holders_info") and sd["holders_info"] != ["（暂无最新股东数据）"]:
            data_text += f"  股东动向：{'；'.join(sd['holders_info'])}；\n"
        if sd.get("technical"):
            data_text += f"  技术面：{sd['technical']}\n"
        if sd.get("notices"):
            data_text += f"  公告：{'；'.join(sd['notices'])}；\n"
        if sd.get("news"):
            data_text += f"  资讯：{'；'.join(sd['news'])}；"

    prompt = f"""你是一位INTJ型投资分析师，冷静、客观、一针见血。

请结合【市场热点板块】、【重要财经提醒】和【个股数据（含技术面）】，为每只股票生成简短判断（不超过80字），并附上最多3条关联动态。

要求：
1. 每只股票格式为：
   [股票名]：🔴/🟢/➖ 核心分析...
   关联动态：1. 动态一；2. 动态二（只列与股票或所属板块直接相关的公告、资讯或市场热点）
2. 技术面数据已提供，请在分析中融入关键技术信号（如放量/缩量、周线趋势等）。
3. 如果你持仓的股票属于今日资金流入TOP5的板块，请重点指出。
4. 公告和资讯中，如果已包含具体内容（如一季报），就基于已有信息分析，不要说"等待"。
5. 最后单独一行，以"整体风险："开头，用一句话总结你持仓组合最需要关注的风险点。

{data_text}

请直接按以下格式输出，不要加额外客套话：
比亚迪：🔴/🟢/➖ ...
关联动态：1. ...
整体风险：..."""

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1200
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

    # 1. 宏观视角
    hot_sectors = get_hot_sectors()
    calendar = get_finance_calendar()

    # 2. 个股数据（含技术面）
    stocks_data = []
    for code, name in stocks:
        print(f"处理股票：{name}({code})")
        secid = get_secid(code)
        basic = get_stock_basic(code, secid)
        flow = get_fund_flow(secid)
        notices = get_notices(code)
        news = get_news(code)
        sentiment = get_stock_sentiment(code)
        holders = get_top_holders(code)
        technical = analyze_technical(code, name, secid)

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
            "holders_info": holders,
            "technical": technical
        })

    # 3. AI 分析
    print("正在请求AI分析...")
    ai_summary = generate_ai_summary(stocks_data, hot_sectors, calendar)

    # 4. 构建邮件
    now = beijing_now()
    body = f"📈 持仓智能深度简报 ({now} 北京时间)\n"
    body += "━━━━━━━━━━━━━━━━━━━━\n\n"

    body += f"【🔥 今日资金热点板块】\n  {hot_sectors}\n\n"
    body += f"【📅 重要财经提醒】\n  {calendar}\n\n"

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
        
        # 技术面
        if sd.get("technical"):
            body += f"  📈 技术面：{sd['technical']}\n"
        else:
            body += f"  📈 技术面：获取失败\n"
        
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

    body += "\n━━━━━━━━━━━━━━━━━━━━\n"
    body += "数据来源：东方财富、新浪财经 | 分析：DeepSeek AI | 本简报不构成投资建议，请独立决策。"

    print("简报生成完毕，正在发送邮件...")
    send_email(f"📈 投资简报 {now}", body)
    print(f"简报任务结束 - {beijing_now()}")

if __name__ == "__main__":
    main()
