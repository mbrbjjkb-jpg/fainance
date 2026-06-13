import os
import sys
import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

# ウエルスアドバイザー（Snapshot）の公式10桁コード
FUNDS = {
    "hifumi": "2008100102",       # ひふみ投信
    "saison": "2007031505",       # セゾン・グローバルバランス
    "rakuten_vti": "2017092908",   # 楽天・全米株式（新・旧共通）
    "ishares": "2013090306"       # iシェアーズ 米国株式(S&P500)
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 日本語の日付「2026年06月03日」を「2026-06-03」に標準化する関数
def normalize_date(date_str):
    match = re.search(r'(\d+)年(\d+)月(\d+)日', date_str)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"
    raise ValueError(f"日付形式を解析できませんでした: {date_str}")

def get_latest_price(code):
    url = f"https://www.wealthadvisor.co.jp/snapshot/{code}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"接続エラー ({url}): {str(e)}")

    soup = BeautifulSoup(r.text, "html.parser")

    # 基準価額テーブルの探索
    for block in soup.select("div.head-table-clm"):
        text = block.get_text(" ", strip=True)
        if "基準価額" not in text:
            continue

        price_tag = block.select_one("p.common-normal-l")
        if not price_tag:
            continue

        # 基準価額（カンマを外して整数化）
        price = int(price_tag.text.strip().replace(",", ""))

        # 基準日（日付）の抽出
        date_val = None
        for p in block.select("p"):
            t = p.get_text(strip=True)
            if "年" in t and "月" in t and "日" in t:
                date_val = normalize_date(t)
                break

        if date_val and price:
            return date_val, price

    raise RuntimeError(f"コード {code} のHTML内に基準価額または日付が見つかりません。")

def main():
    db_file = 'prices_daily.json'
    status_file = 'last_checked.txt'  # 本日の確認完了を記録するファイル
    
    # 1. 日本時間（JST）の現在の日付を取得
    jst = timezone(timedelta(hours=9))
    today_jst = datetime.now(jst).strftime('%Y-%m-%d')

    # 2. 本日すでに取得が成功（完了）しているかチェック
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                last_checked = f.read().strip()
            if last_checked == today_jst:
                print(f"本日の巡回・確認（{today_jst}）はすでに完了しています。これ以降の処理をスキップします。")
                sys.exit(0)
        except Exception as e:
            print(f"警告: ステータスファイルの読み込みに失敗しました（処理は続行します）: {e}")

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

    # 4つのコードから価格を取得
    for key, code in FUNDS.items():
        try:
            date_str, price = get_latest_price(code)
            temp_prices[key] = price
            temp_dates.add(date_str)
            print(f"取得成功: {key} -> {price:,}円 (基準日: {date_str})")
        except Exception as e:
            # ログを出力して正常終了（sys.exit(0)）させます。
            # これにより、GitHub Actionsのエラーメール通知を回避しつつ、status_fileが更新されないため15分後に再試行されます。
            print(f"【エラー】{key} の取得中にエラーが発生しました: {str(e)}", file=sys.stderr)
            sys.exit(0)

    # 取得した日付がすべて一致しているか確認
    if len(temp_dates) != 1:
        print(f"警告: 各投信の間で更新基準日が一致していません。取得日付: {temp_dates}")
        target_date = max(temp_dates)
    else:
        target_date = list(temp_dates)[0]

    print(f"\n判定日: {target_date}")

    # すでにその日付が記録簿に存在しているかチェック
    if target_date in database:
        print("  --> 本日の価格データはすでに記録簿に存在します。ファイル更新をスキップします。")
        # データの追記はしませんが、取得自体は成功したため「本日の確認完了」のステータスを更新します
        try:
            with open(status_file, 'w', encoding='utf-8') as f:
                f.write(today_jst)
            print(f"  --> 【完了】本日の確認が成功したため、ステータスを更新しました（次回以降スキップ）。")
        except Exception as e:
            print(f"警告: ステータスファイルの書き込みに失敗しました: {e}")
        sys.exit(0)

    # 存在していなければ、本日の確定データを追記
    database[target_date] = temp_prices
    
    # 日付順にソート
    sorted_database = dict(sorted(database.items()))

    # JSONファイルに保存
    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(sorted_database, f, indent=2, ensure_ascii=False)

    # 「本日の確認完了」のステータスを更新して保存
    try:
        with open(status_file, 'w', encoding='utf-8') as f:
            f.write(today_jst)
        print(f"  --> 【成功】{target_date} の確定価格データを追記し、ステータスを更新しました。")
    except Exception as e:
        print(f"警告: ステータスファイルの書き込みに失敗しました: {e}")

    sys.exit(0)

if __name__ == '__main__':
    main()
