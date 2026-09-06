"""Shared daily financing river on the homepage and its own page."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .data_fetcher import MarketDataError, get_market_data
from .indicators import build_risk_river, risk_level

COLORS = {'上市風險': '#2563eb', '上櫃風險': '#f97316', '全市場融資壓力': '#7c3aed'}
BANDS = [(0,20,'低風險','#22c55e'),(20,40,'偏低風險','#84cc16'),
         (40,60,'中等風險','#facc15'),(60,80,'偏高風險','#f97316'),(80,100,'極高風險','#ef4444')]


def risk_river_figure(river):
    fig = go.Figure()
    for lo, hi, title, color in BANDS:
        fig.add_hrect(y0=lo,y1=hi,fillcolor=color,opacity=.18,line_width=0,
                      layer='below',annotation_text=title,annotation_position='right')
    for name, group in river.groupby('series'):
        unit = '億元' if name == '全市場融資壓力' else '點'
        fig.add_trace(go.Scatter(x=group['date'],y=group['risk'],name=name,
                                mode='lines',connectgaps=False,line=dict(color=COLORS[name],width=2.5),
                                customdata=group[['raw_value']],
                                hovertemplate='%{x|%Y-%m-%d}<br>風險：%{y:.1f}<br>原始值：%{customdata[0]:,.2f} '+unit+'<extra>'+name+'</extra>'))
    fig.update_layout(height=550,hovermode='x unified',yaxis=dict(range=[0,100],title='風險位階'),
                      xaxis_title='實際交易日期（每日）',legend=dict(orientation='h'),margin=dict(l=10,r=65,t=20,b=10))
    return fig


@st.fragment
def render_margin_monitor():
    st.divider()
    st.header('🌊 台股風險河流圖 V3.3｜每日融資監測')
    st.caption('上市風險、上櫃風險、上市＋上櫃全市場融資壓力：三條河均採每日資料。')
    weeks = st.slider('顯示最近幾週（每個交易日一筆）',20,52,30,key='margin_weeks')
    if st.button('載入／更新並補抓缺日',type='primary',key='margin_refresh'):
        progress = st.empty()
        try:
            with st.spinner('核對交易日、更新最近資料並補抓歷史缺日；首次建立可能需要數分鐘…'):
                data = get_market_data(weeks,progress=progress.caption)
            st.session_state['margin_data'] = data
        except (MarketDataError, ValueError, OSError) as exc:
            st.error(f'融資資料更新未完成：{exc}')
            st.caption('已成功取得的資料會保留；再次按更新即可繼續補抓。')
        finally:
            progress.empty()
    data = st.session_state.get('margin_data')
    if data is None:
        st.info('按上方按鈕載入。之後會保存成功資料，只補抓缺日並刷新最近五個交易日。')
        return
    if data['weeks'] != weeks:
        st.info(f"目前顯示上次載入的 {data['weeks']} 週，按更新套用新範圍。")
    for warning in data['warnings']:
        st.warning(warning)
    recent_calendar = data['calendar'][-130:]
    valid_history = int(data['margin']['date'].isin(recent_calendar).sum())
    if valid_history < 130:
        st.warning(f'最近 130 個交易日的全市場融資，目前僅有 {valid_history} 日資料。融資位階採現有資料暫算，歷史補齊後分數可能改變。')
    river = build_risk_river(data['taiex'],data['tpex'],data['margin'])
    river = river[river['date'] >= data['display_cutoff']]
    for col, name in zip(st.columns(3),COLORS):
        group = river[river['series'] == name].sort_values('date')
        valid = group.dropna(subset=['risk'])
        with col:
            if valid.empty:
                st.metric(name,'資料不足')
            else:
                last = valid.iloc[-1]
                st.metric(name,f"{last['risk']:.1f} / 100")
                st.caption(f"{last['date']:%Y-%m-%d}｜{risk_level(last['risk'])}")
                if last['date'] < data['calendar'].max():
                    st.caption('顯示最近有效值，最新交易日尚未齊全。')
    st.plotly_chart(risk_river_figure(river),use_container_width=True)
    st.caption(f"最近更新嘗試：{data['update_time']}（台北時間）。休市日不算缺漏；缺值不補零、不沿用前日數字，圖線會保留斷點。")
    audit = data['audit']
    display = audit[audit['date'] >= data['display_cutoff']]
    st.write(f"顯示範圍資料完整度：{int(display['完整'].sum())} / {len(display)} 個已知交易日")
    with st.expander('缺日清單與每日原始融資數據',expanded=not display['完整'].all()):
        missing = audit[~audit['完整']].copy()
        if missing.empty:
            st.success('已知交易日資料齊全。')
        else:
            st.dataframe(missing,use_container_width=True,hide_index=True)
        raw = data['margin'].copy()
        if not raw.empty:
            raw = raw[raw['date'] >= data['display_cutoff']]
            raw = raw[['date','twse_margin_balance','tpex_margin_balance','margin_balance']].copy()
            raw.columns = ['日期','上市融資（億元）','上櫃融資（億元）','合計融資（億元）']
            raw.iloc[:,1:] = raw.iloc[:,1:] / 100_000
            st.dataframe(raw,use_container_width=True,hide_index=True)
            st.download_button('下載每日融資 CSV',raw.to_csv(index=False).encode('utf-8-sig'),'daily_margin.csv','text/csv')
    with st.expander('每日模型與資料保存方式'):
        st.markdown('上市／上櫃改用 **100 日均線、60 日動能、20 日年化波動率**，對應原 20／12／4 週尺度；每日算法與原週線分數不會完全相同。\n\n融資沿用 **130 日餘額位階、20 日增幅、價跌資增背離**；兩市場同日融資金額齊全才相加。計算前會保留額外歷史，資料不足或必要日期缺失時不顯示該日分數。\n\n成功資料保存於 `data/margin_monitor/history.sqlite3`。本機更新請保留 data；免費雲端重建若清除磁碟，首次需重建歷史。此頁按按鈕才更新，未另設每日排程。\n\n交易日依兩市場官方指數日期核對；若兩邊同時無法取得某段指數，警告會列出失敗月份，不能當作已完整覆蓋。\n\n來源：[證交所](https://www.twse.com.tw/zh/trading/margin/mi-margn.html)、[櫃買中心](https://www.tpex.org.tw/zh-tw/mainboard/trading/margin-trading/transactions.html)。風險位階不等於實際融資維持率。')
