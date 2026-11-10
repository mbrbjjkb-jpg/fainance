import os
import sys
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# Yahoo!ファイナンス対応の正しい8桁コード
FUNDS = {
    "hifumi": "9C31108A",       # ひふみ投信
    "saison": "96311073",       # セゾン・グローバルバランスファンド
    "rakuten_vti": "9I312179",   # 楽天・全米株式インデックス・ファンド（楽天・ＶＴＩ）
    "ishares": "4831C139"       # ｉシェアーズ 米国株式（Ｓ＆Ｐ５００）インデックス・ファンド
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_latest_price_from_yahoo(code):
    url = f"https://finance.yahoo.co.jp/quote/{code}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"接続エラー ({url}): {str(e)}")

    html = r.text
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    # ----------------------------------------------------
    # 1. 基準価額（price）の抽出
    # ----------------------------------------------------
    price = None

    # パターンA: Next.jsの初期データスクリプト (__NEXT_DATA__) から直接抽出（最も確実）
    next_data_script = soup.find("script", id="__NEXT_DATA__")
    if next_data_script and next_data_script.string:
        try:
            data = json.loads(next_data_script.string)
            # JSONテキストから "standardPrice": 92651 や "price": 92651 などの数値を正規表現で探索
            m = re.search(r'"(?:standardPrice|price|basePrice)":\s*([0-9]+)', next_data_script.string)
            if m:
                price = int(m.group(1))
        except Exception:
            pass

    # パターンB: HTMLタグ内の「基準価額」直後にある大きな数字を抽出
    if not price:
        # 「基準価額」という文字を含む要素を特定
        for elem in soup.find_all(text=re.compile(r'基準価額')):
            parent = elem.parent
            # 親や周囲の兄弟要素からカンマ区切りの数字（千〜十万単位）を探す
            surrounding_text = parent.find_parent(["div", "section", "li"]).get_text(" ", strip=True)
            m = re.search(r'基準価額[^\d]*?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*円', surrounding_text)
            if m:
                price = int(m.group(1).replace(",", ""))
                break

    # パターンC: テキスト全体から探索（純資産などを拾わないよう「円」の直前で限定）
    if not price:
        m = re.search(r'基準価額\D*?([0-9]{1,3}(?:,[0-9]{3})+)\s*円', page_text)
        if m:
            price = int(m.group(1).replace(",", ""))

    # ----------------------------------------------------
    # 2. 基準日（date）の抽出（設定日ではなく直近の日付を拾う）
    # ----------------------------------------------------
    date_val = None
    current_year = datetime.now().year

    # パターンA: 「基準日」という文字の直後にある日付
    m_date = re.search(r'基準日[^\d]*?(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', page_text)
    if m_date:
        y, m, d = int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
        # 設定日（2008年など）を誤爆しないよう、直近5年以内の年か検証
        if current_year - 5 <= y <= current_year + 1:
            date_val = f"{y:04d}-{m:02d}-{d:02d}"

    # パターンB: ページ上部の「（MM/DD）」または「（YYYY/MM/DD）」形式の日付
    if not date_val:
        # 今年の西暦で探す
        m_curr = re.search(rf'({current_year})[年/-](\d{{1,2}})[月/-](\d{{1,2}})', page_text)
        if m_curr:
            date_val = f"{int(m_curr.group(1)):04d}-{int(m_curr.group(2)):02d}-{int(m_curr.group(3)):02d}"
        else:
            # 年が省略された「（11/02）」などの形式
            m_short = re.search(r'[（\(](\d{1,2})[/月](\d{1,2})[日\)）]', page_text)
            if m_short:
                date_val = f"{current_year:04d}-{int(m_short.group(1)):02d}-{int(m_short.group(2)):02d}"

    if price and date_val:
        return date_val, price

    raise RuntimeError(f"Yahoo!ファイナンス ({url}) からの抽出に失敗しました (price={price}, date={date_val})")

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

    print("--- 各投資信託の最新価格情報の自動取得を開始します（Yahoo!ファイナンス） ---")
    
    temp_prices = {}
    temp_dates = set()

    for key, code in FUNDS.items():
        try:
            date_str, price = get_latest_price_from_yahoo(code)
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