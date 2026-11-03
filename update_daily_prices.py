import os
import sys
import json
import re
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

    soup = BeautifulSoup(r.text, "html.parser")

    # 1. 基準価額の取得（「基準価額」という文字を含む要素から価格を探索）
    price = None
    target_header = soup.find(lambda tag: tag.name in ["dt", "th", "div", "span", "p"] and tag.get_text(strip=True) == "基準価額")
    if target_header:
        # 親要素や次の兄弟要素から数値を探す
        parent = target_header.parent
        # 数値（カンマ区切りの数字）を正規表現で抽出
        text = parent.get_text(" ", strip=True)
        price_match = re.search(r'基準価額\s*([0-9,]+)\s*円?', text)
        if price_match:
            price = int(price_match.group(1).replace(",", ""))

    # 2. 基準日（日付）の取得（ページ内の「YYYY/MM/DD」または「YYYY年MM月DD日」を探索）
    # 通常、基準価額の付近または上部に「2026/06/03」等の日付が表示される
    date_val = None
    
    # ページ上部の日付表記を探索
    date_match = re.search(r'(\d{4})[年/](\d{1,2})[月/](\d{1,2})日?', soup.text)
    if date_match:
        y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
        date_val = f"{y:04d}-{m:02d}-{d:02d}"

    if price and date_val:
        return date_val, price

    raise RuntimeError(f"コード {code} のHTML内に基準価額または日付が見つかりません。")

def main():
    db_file = 'prices_daily.json'
    
    # 既存の prices_daily.json を読み込む
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

    # 取得した日付の確認
    if len(temp_dates) != 1:
        print(f"警告: 各投信の間で更新基準日が一致していません。取得日付: {temp_dates}")
        target_date = max(temp_dates)
    else:
        target_date = list(temp_dates)[0]

    print(f"\n判定日: {target_date}")

    if target_date in database:
        print("  --> 本日の価格データはすでに記録簿に存在します。ファイル更新をスキップします。")
        sys.exit(0)

    # 追記保存
    database[target_date] = temp_prices
    sorted_database = dict(sorted(database.items()))

    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(sorted_database, f, indent=2, ensure_ascii=False)

    print(f"  --> 【成功】{target_date} の確定価格データを {db_file} に新規追記しました。")
    sys.exit(0)

if __name__ == '__main__':
    main()