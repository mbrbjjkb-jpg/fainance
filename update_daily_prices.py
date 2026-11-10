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

    # 1. 基準価額（price）の抽出（metaタグ優先）
    price = None
    meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta_desc and meta_desc.get("content"):
        m = re.search(r'基準価額\s*([0-9,.]+)\s*円', meta_desc["content"])
        if m:
            price = int(float(m.group(1).replace(",", "")))

    if not price:
        m = re.search(r'基準価額\s*(?:\d{1,2}/\d{1,2})?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*円', page_text)
        if m:
            price = int(m.group(1).replace(",", ""))

    # 2. 基準日（date）の抽出（metaタグ優先）
    date_val = None
    meta_time = soup.find("meta", attrs={"property": "og:update_time"})
    if meta_time and meta_time.get("content"):
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', meta_time["content"])
        if m:
            date_val = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

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
    temp_dates = []

    for key, code in FUNDS.items():
        try:
            date_str, price = get_latest_price(code)
            temp_prices[key] = price
            temp_dates.append(date_str)
            print(f"取得成功: {key} -> {price:,}円 (基準日: {date_str})")
        except Exception as e:
            print(f"【エラー】{key} の取得中にエラーが発生しました: {str(e)}", file=sys.stderr)
            sys.exit(1)

    # 代表日として取得された中で最新の日付を採用
    target_date = max(temp_dates)
    print(f"\n採用判定日: {target_date}")

    # =======================================================
    # ★ 価格の差異検知ロジック（日付ではなく金額の差で判定）
    # =======================================================
    has_diff = False

    # ケースA: すでに該当日のデータが存在している場合（上書き修正判定）
    if target_date in database:
        existing_prices = database[target_date]
        diff_details = []
        for k, new_p in temp_prices.items():
            old_p = existing_prices.get(k)
            if old_p != new_p:
                has_diff = True
                diff_details.append(f"{k}: {old_p}円 -> {new_p:,}円")

        if not has_diff:
            print(f"  --> {target_date} の記録簿と価格差異はありません（全銘柄一致）。更新をスキップします。")
            sys.exit(0)
        else:
            print(f"  --> 【差異検知】{target_date} の既存価格データと差異を発見しました:")
            for d in diff_details:
                print(f"      - {d}")
            print(f"  --> 最新の正しい価格データで上書き更新します。")

    # ケースB: 新規の日付の場合（直近最新レコードからの価格変動判定）
    else:
        if database:
            last_recorded_date = max(database.keys())
            last_prices = database[last_recorded_date]
            diff_details = []
            for k, new_p in temp_prices.items():
                old_p = last_prices.get(k)
                if old_p != new_p:
                    has_diff = True
                    diff_details.append(f"{k}: {old_p}円 -> {new_p:,}円")

            if not has_diff:
                print(f"  --> 最新基準日（{target_date}）ですが、前回収録日（{last_recorded_date}）から価格変動がありません。更新をスキップします。")
                sys.exit(0)
            else:
                print(f"  --> 【価格変動検知】前回収録日（{last_recorded_date}）からの価格変化を確認しました:")
                for d in diff_details:
                    print(f"      - {d}")
                print(f"  --> {target_date} の確定データとして新規追記します。")
        else:
            # 記録簿が空の場合は無条件で初回登録
            has_diff = True
            print(f"  --> 記録簿が空のため、新規作成します。")

    # データベースに反映して保存
    database[target_date] = temp_prices
    sorted_database = dict(sorted(database.items()))

    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(sorted_database, f, indent=2, ensure_ascii=False)

    print(f"  --> 【成功】{target_date} の最新価格データを {db_file} に保存しました。")
    sys.exit(0)

if __name__ == '__main__':
    main()