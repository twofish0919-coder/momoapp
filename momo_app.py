import re
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from curl_cffi import requests

API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HOME_URL = "https://www.momoshop.com.tw/"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}

PRICE_BINS = [0, 500, 1000, 1500, 2000, 3000, float("inf")]
PRICE_LABELS = ["500以下", "501-1000", "1001-1500", "1501-2000", "2001-3000", "3000以上"]


def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


@st.cache_data(show_spinner=False, ttl=600)
def crawl_momo(keyword: str, pages: int, delay: float = 1.0):
    """爬取多頁商品，回傳 (DataFrame, 錯誤訊息列表)。"""
    rows, errors = [], []
    session = requests.Session(impersonate="chrome")  # 模擬 Chrome TLS 指紋
    try:
        session.get(HOME_URL, headers=HEADERS)  # 先取得 cookie
    except Exception as e:
        return pd.DataFrame(), [f"無法連線至 momo：{e}"]

    for page in range(1, pages + 1):
        try:
            resp = session.post(API_URL, headers=HEADERS, json=build_payload(keyword, page))
            if resp.status_code != 200:
                errors.append(f"第 {page} 頁失敗（HTTP {resp.status_code}）：{resp.text[:200]}")
                continue
            goods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
            if not goods:
                errors.append(f"第 {page} 頁沒有資料，已停止。")
                break
            for p in goods:
                rows.append(
                    {
                        "頁數": page,
                        "品名": p.get("goodsName", ""),
                        "價格": p.get("goodsPrice", ""),
                    }
                )
        except Exception as e:
            errors.append(f"第 {page} 頁發生錯誤：{e}")
        time.sleep(delay)

    df = pd.DataFrame(rows)
    if df.empty:
        return df, errors

    # 價格清理：只保留數字
    df["價格"] = df["價格"].astype(str).str.replace(r"[^\d]", "", regex=True)
    df["價格"] = pd.to_numeric(df["價格"], errors="coerce")
    df = df.dropna(subset=["價格"]).reset_index(drop=True)
    df["價格"] = df["價格"].astype(int)
    return df, errors


def extract_brand(name: str) -> str:
    """從品名抓品牌：優先取開頭【】內文字，否則取第一個詞。"""
    name = str(name).strip()
    m = re.match(r"^[【\[]([^】\]]{1,12})[】\]]", name)
    if m:
        return m.group(1).strip()
    first = re.split(r"[\s/／,，]+", name)[0] if name else ""
    return first[:8] if first else "其他"


def add_columns(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    df = df.copy()
    df["價格區間"] = pd.cut(df["價格"], bins=PRICE_BINS, labels=PRICE_LABELS, right=True).astype(str)
    df["品牌"] = df["品名"].apply(extract_brand)
    top_brands = df["品牌"].value_counts().head(top_n).index
    df["品牌"] = df["品牌"].where(df["品牌"].isin(top_brands), "其他")
    return df


# ---------------------------- UI ----------------------------
st.set_page_config(page_title="MOMO 商品價格分析", page_icon="🛒", layout="wide")
st.title("🛒 MOMO 商品價格分析")

with st.sidebar:
    st.header("搜尋條件")
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    top_n = st.slider("旭日圖顯示前幾大品牌", 3, 15, 8)
    run = st.button("開始爬取", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.warning("請輸入產品名稱")
        st.stop()
    with st.spinner(f"正在爬取「{keyword}」共 {pages} 頁..."):
        df, errors = crawl_momo(keyword.strip(), int(pages))
    st.session_state["df"] = df
    st.session_state["errors"] = errors
    st.session_state["keyword"] = keyword.strip()

if "df" not in st.session_state:
    st.info("請在左側輸入產品名稱與頁數，然後按「開始爬取」。")
    st.stop()

df = st.session_state["df"]
kw = st.session_state["keyword"]
for msg in st.session_state.get("errors", []):
    st.warning(msg)

if df.empty:
    st.error("沒有取得任何資料，可能被網站擋下或關鍵字無結果。")
    st.stop()

df = add_columns(df, top_n)
avg_price = df["價格"].mean()

# 統計指標
c1, c2, c3, c4 = st.columns(4)
c1.metric("商品數", f"{len(df):,}")
c2.metric("平均價格", f"${avg_price:,.0f}")
c3.metric("最高價格", f"${df['價格'].max():,}")
c4.metric("最低價格", f"${df['價格'].min():,}")

tab1, tab2, tab3, tab4 = st.tabs(["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖", "📄 資料表"])

with tab1:
    fig = px.line(
        df.reset_index(),
        x="index",
        y="價格",
        hover_data=["品名", "頁數"],
        markers=True,
        title=f"MOMO 電商網站上「{kw}」售價",
        labels={"index": "商品序號", "價格": "價格 (NTD)"},
    )
    fig.add_hline(
        y=avg_price,
        line_dash="dash",
        line_color="red",
        annotation_text=f"平均 {avg_price:,.0f}",
        annotation_position="top left",
    )
    fig.update_layout(height=520)
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    pie_df = (
        df.groupby("價格區間")
        .size()
        .reindex(PRICE_LABELS, fill_value=0)
        .reset_index(name="商品數")
    )
    pie_df = pie_df[pie_df["商品數"] > 0]
    fig = px.pie(
        pie_df,
        names="價格區間",
        values="商品數",
        title=f"「{kw}」價格區間分布",
        hole=0.3,
        category_orders={"價格區間": PRICE_LABELS},
    )
    fig.update_traces(textinfo="percent+label")
    fig.update_layout(height=520)
    st.plotly_chart(fig, use_container_width=True)

with tab3:
    fig = px.sunburst(
        df,
        path=["價格區間", "品牌"],
        title=f"「{kw}」價格區間 → 品牌 分布",
    )
    fig.update_traces(textinfo="label+percent parent")
    fig.update_layout(height=620)
    st.plotly_chart(fig, use_container_width=True)

with tab4:
    st.dataframe(df[["頁數", "品名", "價格", "價格區間", "品牌"]], use_container_width=True)
    fname = f"MOMO_{kw}_{datetime.now():%Y%m%d}.csv"
    st.download_button(
        "下載 CSV",
        data=df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=fname,
        mime="text/csv",
    )
