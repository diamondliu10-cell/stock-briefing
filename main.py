import akshare as ak
import requests
import smtplib
import os
import pandas as pd
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
                    stocks.append((parts[0].strip(), parts[1].strip()))
    except FileNotFoundError:
        print("stocks.txt不存在")
    return stocks

def format_amount(amount_yuan):
    if amount_yuan is None or amount_yuan == 0:
        return "0"
    yi = amount_yuan / 1e8
    if abs(yi) >= 0.01:
        return f"{yi:.2f}亿元"
    return f"{amount_yuan / 1e4:.0f}万元"

def is_etf(code):
    """判断代码是否为ETF（沪市5开头，深市1开头）"""
    return code.startswith(("5", "1"))

# ------------------------------------------------------------
# 数据获取（全部基于akshare，稳定可靠）
# ------------------------------------------------------------
def get_stock_quote(code, name):
    """获取个股实时行情"""
    try:
        if is_etf(code):
            # ETF行情
            df = ak.fund_etf_spot_em()
            row = df[df["代码"] == code]
            if not row.empty:
                row = row.iloc[0]
                return {
                    "price": float(row["最新价"]),
                    "change_pct": float(row["涨跌幅"]),
                    "amount": float(row["成交额"])
                }
        else:
            # 股票行情
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == code]
            if not row.empty:
                row = row.iloc[0]
                return {
                    "price": float(row["最新价"]),
                    "change_pct": float(row["涨跌幅"]),
                    "amount": float(row["成交额"])
                }
    except Exception as e:
        print(f"行情获取异常 {code}: {e}")
    return None

def get_fund_flow(code, name):
    """获取主力资金净流入和占比"""
    try:
        # 使用个股资金流排名接口，数据完整
        df = ak.stock_individual_fund_flow_rank(market="沪深A股")
        # 兼容ETF
        if is_etf(code):
            df = ak.stock_individual_fund_flow_rank(market="沪深ETF")
        row = df[df["代码"] == code]
        if not row.empty:
            row = row.iloc[0]
            main_in = float(row["主力净流入"])
            main_pct = float(row["主力净占比"])
            return {"main_net_in": main_in, "main_net_pct": main_pct}
    except Exception as e:
        print(f"资金流向异常 {code}: {e}")
    return {"main_net_in": 0, "main_net_pct": 0.0}

def get_technical(code, name):
    """计算技术指标（日K，MA，MACD，RSI）"""
    try:
        if is_etf(code):
            df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
        else:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq", start_date="20260101")
        if df.empty:
            return "技术数据不足"
        df = df.tail(60)
        closes = df["收盘"].tolist()
        highs = df["最高"].tolist()
        lows = df["最低"].tolist()
        volumes = df["成交量"].tolist()
        dates = df["日期"].tolist()

        # 最新日K
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else None
        date = str(last["日期"])[:10]
        open_p = last["开盘"]
        close_p = last["收盘"]
        high_p = last["最高"]
        low_p = last["最低"]
        volume = last["成交量"]
        change_pct = (close_p - prev["收盘"]) / prev["收盘"] * 100 if prev is not None else 0

        # 换手率（股票有，ETF可能没有）
        turnover = None
        if "换手率" in df.columns and not pd.isna(last["换手率"]):
            turnover = float(last["换手率"])

        # 量能对比
        if prev is not None:
            prev_vol = prev["成交量"]
            vol_change = ((volume - prev_vol) / prev_vol * 100) if prev_vol > 0 else 0
            vol_desc = "放量" if vol_change > 20 else ("缩量" if vol_change < -20 else "量平")
        else:
            vol_change, vol_desc = 0, "量平"

        # 均线
        def ma(data, w):
            return sum(data[-w:]) / w if len(data) >= w else None
        ma5 = ma(closes, 5)
        ma10 = ma(closes, 10)
        ma20 = ma(closes, 20)

        # MACD
        def ema(data, n):
            if len(data) < 2: return None
            k = 2 / (n + 1)
            result = [data[0]]
            for price in data[1:]:
                result.append(price * k + result[-1] * (1 - k))
            return result
        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        dif = ema12[-1] - ema26[-1] if ema12 and ema26 else None
        dea = ema([dif], 9) if dif else None
        macd_val = (dif - dea) * 2 if dif and dea else None

        # RSI
        def rsi(data, n=14):
            if len(data) < n+1: return None
            gains = sum(max(0, data[i] - data[i-1]) for i in range(-n, 0))
            losses = sum(max(0, data[i-1] - data[i]) for i in range(-n, 0))
            if losses == 0: return 100.0
            return 100.0 - 100.0 / (1 + gains / losses)
        rsi_val = rsi(closes)

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
        if rsi_val:
            if rsi_val > 70:
                status.append(f"RSI超买({rsi_val:.1f})")
            elif rsi_val < 30:
                status.append(f"RSI超卖({rsi_val:.1f})")
            else:
                status.append(f"RSI中性({rsi_val:.1f})")

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
        print(f"技术分析异常 {code}: {e}")
        return "技术数据解析失败"

def get_intelligence(code, name):
    """获取个股研报与预警公告"""
    titles = []
    try:
        # 研报
        df_report = ak.stock_research_report_em(symbol=code)
        if not df_report.empty:
            for _, row in df_report.head(3).iterrows():
                titles.append(f"[研报]{row['研究报告名称']}")
    except:
        pass
    try:
        # 公告（过滤预警关键词）
        df_notice = ak.stock_notice_report(symbol=code)
        keywords = ["预测", "预警", "调出", "减持", "诉讼", "罚款", "下调", "目标价", "评级", "退市"]
        for _, row in df_notice.head(10).iterrows():
            title = row["公告标题"]
            if any(kw in title for kw in keywords):
                titles.append(f"[预警]{title}")
    except:
        pass
    return titles[:5] if titles else ["无相关预测情报"]

def get_market_sentiment(code):
    """获取人气排名"""
    try:
        df = ak.stock_hot_rank_em()
        row = df[df["代码"] == code]
        if not row.empty:
            rank = row.iloc[0]["排名"]
            return f"人气排名第{int(rank)}位"
    except:
        pass
    return "关注度低"

def get_top_holders(code):
    """十大流通股东中的社保/北向"""
    try:
        df = ak.stock_main_stock_holder(symbol=code)
        latest_date = str(df["截止日期"].max())[:10] if not df.empty else "?"
        holders = []
        for _, row in df.iterrows():
            name = row["股东名称"]
            if any(k in name for k in ["社保", "香港中央结算", "中国证券金融", "中央汇金"]):
                ratio = row["持股比例"]
                change = row.get("变动数量", 0)
                change_str = "增持" if change > 0 else ("减持" if change < 0 else "不变")
                holders.append(f"  • {name} 持股{ratio}%，{change_str}")
        if holders:
            return [f"（截止：{latest_date}）"] + holders
        return ["（未发现重要机构）"]
    except:
        return ["（暂无最新数据）"]

def get_hot_sectors():
    """热点行业板块资金流"""
    try:
        df = ak.stock_sector_fund_flow_rank(ind="行业板块", segment="今日资金流")
        lines = []
        for _, row in df.head(5).iterrows():
            name = row["名称"]
            main_in = row["主力净流入"]
            main_pct = row["主力净占比"]
            lines.append(f"{name}（净流入{main_in/1e8:.2f}亿，占比{main_pct}%）")
        return "；\n  ".join(lines)
    except Exception as e:
        print(f"热点板块异常：{e}")
        return "板块数据暂不可用"

def get_finance_calendar():
    """财经日历"""
    try:
        df = ak.stock_calendar_em()
        if not df.empty:
            latest = df.iloc[0]
            return f"{latest['日期']} {latest['事件']}"
    except:
        pass
    return "暂无重要事件"

# ------------------------------------------------------------
# AI 总结（保持不变）
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
        quote = get_stock_quote(code, name)
        flow = get_fund_flow(code, name)
        technical = get_technical(code, name)
        intel = get_intelligence(code, name)
        sentiment = get_market_sentiment(code)
        holders = get_top_holders(code)

        data_list.append({
            "code": code, "name": name,
            "price": quote["price"] if quote else None,
            "change_pct": quote["change_pct"] if quote else None,
            "amount": quote["amount"] if quote else None,
            "main_net_in": flow["main_net_in"],
            "main_net_pct": flow["main_net_pct"],
            "notices": [],  # 公告已集成到情报中
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
    body += "数据源：东方财富（via akshare） | 分析：DeepSeek AI | 仅供参考，不构成投资建议。"

    send_email(f"📈 投资简报 {now}", body)
    print("简报发送完毕")

if __name__ == "__main__":
    main()
