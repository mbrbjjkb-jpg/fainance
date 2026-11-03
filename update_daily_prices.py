import os
import sys
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# Yahoo!ファイナンス用の投信協会コード（8桁）
FUNDS = {
    "hifumi": "9C31108A",       # ひふみ投信
    "saison": "04311073",       # セゾン・グローバルバランス
    "rakuten_vti": "9I311179",   # 楽天・全米株式
    "ishares": "96311139"       # iシェアーズ 米国株式(S&P500)
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_latest_price(code):
    url = f"https://finance.yahoo.co.jp/quote/{code}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"接続エラー ({url}): {str(e)}")

    html = r.text
    soup = BeautifulSoup(html, "html.parser")
    text_content = soup.get_text(" ", strip=True)

    # -----------------------------
    # 1. 基準価額（price）の抽出
    # -----------------------------
    price = None

    # パターンA: テキストから「基準価額」の直後にあるカンマ区切り数値を抽出
    m_price = re.search(r'基準価額[^\d]*?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*円?', text_content)
    if m_price:
        price = int(m_price.group(1).replace(",", ""))

    # パターンB: HTMLタグ込みで「基準価額」直後の数値を抽出（パターンAが取れなかった場合）
    if not price:
        m_price_html = re.search(r'基準価額.*?>\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*<', html, re.DOTALL)
        if m_price_html:
            price = int(m_price_html.group(1).replace(",", ""))

    # -----------------------------
    # 2. 基準日（date）の抽出
    # -----------------------------
    date_val = None

    # パターンA: <time> タグがある場合（datetime="YYYY-MM-DD" など）
    for time_tag in soup.find_all("time"):
        dt = time_tag.get("datetime")
        if dt:
            m_dt = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', dt)
            if m_dt:
                date_val = f"{int(m_dt.group(1)):04d}-{int(m_dt.group(2)):02d}-{int(m_dt.group(3)):02d}"
                break

    # パターンB: 「基準日」や「日付」の周辺にある YYYY年MM月DD日 または YYYY/MM/DD
    if not date_val:
        m_date = re.search(r'基準日[^\d]*?(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', text_content)
        if not m_date:
            m_date = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?\s*(?:基準|更新|\()', text_content)
        if not m_date:
            # ページ全体の最初の YYYY/MM/DD や YYYY年MM月DD日
            m_date = re.search(r'(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})', text_content)

        if m_date:
            y, m, d = int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
            date_val = f"{y:04d}-{m:02d}-{d:02d}"

    # パターンC: 年が省略されて「（MM/DD）」と表記されている場合
    if not date_val:
        m_short_date = re.search(r'[（\(](\d{1,2})[/月](\d{1,2})[日\)）]', text_content)
        if m_short_date:
            y = datetime.now().year
            m = int(m_short_date.group(1))
            d = int(m_short_date.group(2))
            date_val = f"{y:04d}-{m:02d}-{d:02d}"

    # どちらか一方でも取得できなかった場合は詳細を通知
    if not price or not date_val:
        raise RuntimeError(f"コード {code} の抽出結果 -> 基準価額: {price}, 基準日: {date_val}")

    return date_val, price

def main():
    db_file = 'prices_daily.json'
    
    if os.path.exists(db_file):
        try:
            with open(db_file, 'r', encoding='utf-8') as f:
                database = json.load(f)
        except Exception as e:
            print(f"警告: 既存の {db_file} が破損している可能性があるため、新規作成します。: {e}")
            database = {}
    else:
        database = {}

    print("--- 各投資信託の最新価格情報の自動取得を開始します ---")
    
    temp_prices = {}
    temp_dates = set()

    for key, code in FUNDS.items():
        try:
            date_str, price = get_latest_price(code)
            temp_prices[key] = price
            temp_dates.add(date_str)
            print(f"取得成功: {key} -> {price:,}円 (基準日: {date_str})")
        except Exception as e:
            print(f"【エラー】{key} の取得中にエラーが発生しました: {str(e)}", file=sys.stderr)
            sys.exit(1)

    if len(temp_dates) != 1:
        print(f"警告: 各投信の間で更新基準日が一致していません。取得日付: {temp_dates}")
        target_date = max(temp_dates)
    else:
        target_date = list(temp_dates)[0]

    print(f"\n判定日: {target_date}")

    if target_date in database:
        print("  --> 本日の価格データはすでに記録簿に存在します。ファイル更新をスキップします。")
        sys.exit(0)

    database[target_date] = temp_prices
    sorted_database = dict(sorted(database.items()))

    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(sorted_database, f, indent=2, ensure_ascii=False)

    print(f"  --> 【成功】{target_date} の確定価格データを {db_file} に新規追記しました。")
    sys.exit(0)

if __name__ == '__main__':
    main()