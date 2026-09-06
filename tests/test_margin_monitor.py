import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from margin_monitor import data_fetcher as f
from margin_monitor.indicators import build_risk_river


class MarginTests(unittest.TestCase):
    def test_rate_limit_stops_network_and_preserves_cache(self):
        class Response:
            status_code=429
            headers={'Retry-After':'240'}
        with patch.object(f.requests,'get',return_value=Response()) as request,patch.object(f,'_BLOCKED_UNTIL',{}),patch.object(f,'_LAST_REQUEST',{}):
            with self.assertRaises(f.RateLimitedError):
                f._get_json('https://official.example/data',{})
            with self.assertRaises(f.RateLimitedError):
                f._get_json('https://official.example/data',{})
            self.assertEqual(request.call_count,1)

    def test_transient_gap_repaired_and_persisted(self):
        days = [dt.date(2026,8,3), dt.date(2026,8,4)]
        calls = {}
        def fetch(day):
            calls[day] = calls.get(day,0)+1
            if day==days[0] and calls[day]==1:
                raise f.MarketDataError('temporary')
            return {'date':pd.Timestamp(day),'margin_balance':100.}
        with tempfile.TemporaryDirectory() as tmp, patch.object(f.time,'sleep'):
            path=Path(tmp)/'history.sqlite3'
            store=f.HistoryStore(path)
            failed,_=f._repair_margin(fetch,days,store,'test')
            self.assertFalse(failed)
            self.assertEqual(calls[days[0]],2)
            reopened=f.HistoryStore(path)
            self.assertEqual(len(reopened.read('test','margin_balance',days[0],days[-1])),2)

    def test_only_gap_and_recent_five_are_requested(self):
        days=list(pd.bdate_range('2026-08-03',periods=15).date)
        calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            store=f.HistoryStore(Path(tmp)/'db')
            store.save('test',[{'date':pd.Timestamp(d),'margin_balance':200.} for d in days if d!=days[1]])
            def fetch(day):
                calls.append(day)
                return {'date':pd.Timestamp(day),'margin_balance':201.}
            f._repair_margin(fetch,days,store,'test')
            self.assertEqual(set(calls),set(days[-5:])|{days[1]})

    def test_failed_refresh_does_not_erase_existing_balance(self):
        day=dt.date(2026,8,3)
        with tempfile.TemporaryDirectory() as tmp, patch.object(f.time,'sleep'):
            store=f.HistoryStore(Path(tmp)/'db')
            store.save('test',[{'date':pd.Timestamp(day),'margin_balance':200.}])
            def fail(day): raise f.MarketDataError('down')
            f._repair_margin(fail,[day],store,'test')
            self.assertEqual(store.read('test','margin_balance',day,day).iloc[0]['margin_balance'],200.)

    def test_twse_wrong_response_date_rejected(self):
        with patch.object(f,'_get_json',return_value={'date':'20260803'}):
            with self.assertRaises(f.MarketDataError): f._fetch_twse_margin_day(dt.date(2026,8,4))

    def test_tpex_json_summary_uses_amount_not_shares(self):
        payload={'date':'20260803','tables':[{'summary':[['','合計(張)','10','20','30','40','50'],['','融資金(仟元)','100','20','10','5','105','','']]}]}
        with patch.object(f,'_get_json',return_value=payload):
            self.assertEqual(f._fetch_tpex_margin_day(dt.date(2026,8,3))['margin_balance'],105)

    def test_tpex_html_fallback_date_checked(self):
        html='<div>資料日期:115/08/03</div><table><tr><td>融資金(仟元)</td><td>100</td><td>20</td><td>10</td><td>5</td><td>105</td></tr></table>'
        with patch.object(f,'_get_json',side_effect=f.MarketDataError('json down')),patch.object(f,'_get_text',return_value=html):
            self.assertEqual(f._fetch_tpex_margin_day(dt.date(2026,8,3))['margin_balance'],105)
            with self.assertRaises(f.MarketDataError): f._fetch_tpex_margin_day(dt.date(2026,8,4))

    def test_daily_river_keeps_gaps_and_calendar_windows(self):
        dates=pd.bdate_range('2025-01-01',periods=190)
        taiex=pd.DataFrame({'date':dates,'taiex':np.arange(190)+20000.})
        tpex=pd.DataFrame({'date':dates,'tpex':np.arange(190)+250.})
        twse=pd.DataFrame({'date':dates,'margin_balance':np.arange(190)*1000+500000.})
        otc=pd.DataFrame({'date':dates,'margin_balance':np.arange(190)*500+200000.}).drop(index=160)
        margin=f._combine_margin_amounts(twse,otc)
        river=build_risk_river(taiex,tpex,margin)
        for name,group in river.groupby('series'):
            self.assertEqual(list(group.date),list(dates))
            self.assertTrue(group.risk.dropna().between(0,100).all())
        line=river[river.series=='全市場融資壓力'].set_index('date')
        self.assertTrue(pd.isna(line.loc[dates[160],'risk']))
        self.assertTrue(pd.isna(line.loc[dates[180],'risk'])) # missing 20-session baseline
        expected=(twse.iloc[-1].margin_balance+otc.iloc[-1].margin_balance)/100000
        self.assertAlmostEqual(line.iloc[-1].raw_value,expected)

    def test_one_market_missing_does_not_create_false_total(self):
        dates=pd.bdate_range('2026-08-03',periods=3)
        a=pd.DataFrame({'date':dates,'margin_balance':[100.,110.,120.]})
        b=pd.DataFrame({'date':dates[:2],'margin_balance':[50.,60.]})
        result=f._combine_margin_amounts(a,b)
        self.assertEqual(result.margin_balance.tolist(),[150.,170.])

    def test_missing_index_on_one_market_is_still_audited(self):
        dates=pd.bdate_range('2026-08-03',periods=4)
        a=[{'date':d,'taiex':20000.} for d in dates]
        b=[{'date':d,'tpex':250.} for d in dates if d!=dates[1]]
        def index_a(month): return a if month.month==8 else []
        def index_b(month): return b if month.month==8 else []
        def margin(day): return {'date':pd.Timestamp(day),'margin_balance':100.}
        with tempfile.TemporaryDirectory() as tmp,patch.object(f,'_fetch_twse_month',side_effect=index_a),patch.object(f,'_fetch_tpex_month',side_effect=index_b),patch.object(f,'_fetch_twse_margin_day',side_effect=margin),patch.object(f,'_fetch_tpex_margin_day',side_effect=margin):
            result=f.get_market_data(8,cache_path=Path(tmp)/'db',today=dt.date(2026,8,7))
            audit=result['audit'].set_index('date')
            self.assertIn(dates[1],audit.index)
            self.assertFalse(audit.loc[dates[1],'上櫃指數'])
            self.assertTrue(audit.loc[dates[1],'上櫃融資'])


if __name__=='__main__': unittest.main()
