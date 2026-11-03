import os
import sys
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# みんかぶ投信の正しいファンドコード
FUNDS = {
    "hifumi": "9C31108A",       # ひふみ投信
    "saison": "96311073",       # セゾン・グローバルバランスファンド
    "rakuten_vti": "9I312179",   # 楽天・全米株式インデックス・ファンド（楽天・ＶＴＩ）
    "ishares": "4831C139"       # ｉシェアーズ 米国株式（Ｓ＆Ｐ５００）インデックス・ファンド
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_latest_price(code):
    url = f"https://itf.minkabu.jp/fund/{code}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"接続エラー ({url}): {str(e)}")

    soup = BeautifulSoup(r.text, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    # 1. 基準価額（price）の抽出
    price = None
    # meta description から抽出（例: "基準価額92651.0円"）
    meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta_desc and meta_desc.get("content"):
        m = re.search(r'基準価額\s*([0-9,.]+)\s*円', meta_desc["content"])
        if m:
            price = int(float(m.group(1).replace(",", "")))

    # フォールバック: 本文テキストから抽出
    if not price:
        m = re.search(r'基準価額\s*(?:\d{1,2}/\d{1,2})?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*円', page_text)
        if m:
            price = int(m.group(1).replace(",", ""))

    # 2. 基準日（date）の抽出
    date_val = None
    # meta og:update_time から抽出（例: "2026-11-02"）
    meta_time = soup.find("meta", attrs={"property": "og:update_time"})
    if meta_time and meta_time.get("content"):
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', meta_time["content"])
        if m:
            date_val = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # フォールバック: 本文テキストから抽出
    if not date_val:
        m = re.search(r'基準価額\s*(\d{1,2})/(\d{1,2})', page_text)
        if m:
            y = datetime.now().year
            date_val = f"{y:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    if price and date_val:
        return date_val, price

    raise RuntimeError(f"みんかぶ ({url}) から基準価額または日付を抽出できませんでした (price={price}, date={date_val})")

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

    # 取得した日付の同期確認
    if len(temp_dates) != 1:
        print(f"警告: 各投信の間で更新基準日が一致していません。取得日付: {temp_dates}")
        target_date = max(temp_dates)
    else:
        target_date = list(temp_dates)[0]

    print(f"\n判定日: {target_date}")

    # すでに本日のデータが存在していればスキップ
    if target_date in database:
        print("  --> 本日の価格データはすでに記録簿に存在します。ファイル更新をスキップします。")
        sys.exit(0)

    # 確定価格を追記して保存
    database[target_date] = temp_prices
    sorted_database = dict(sorted(database.items()))

    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(sorted_database, f, indent=2, ensure_ascii=False)

    print(f"  --> 【成功】{target_date} の確定価格データを {db_file} に新規追記しました。")
    sys.exit(0)

if __name__ == '__main__':
    main()