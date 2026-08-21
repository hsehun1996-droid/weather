import datetime
import unittest
from unittest.mock import patch, MagicMock

import requests

from weather_duty import kma_client


def _mock_response(items):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
            "body": {"dataType": "JSON", "items": {"item": items}},
        }
    }
    return resp


class TestUltraSrtNcst(unittest.TestCase):
    @patch("weather_duty.kma_client._SESSION.get")
    def test_parses_temp_and_rain(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {"category": "T1H", "obsrValue": "27.3"},
                {"category": "RN1", "obsrValue": "0"},
            ]
        )
        result = kma_client.get_current_conditions(
            "dummy-key", 60, 127, now=datetime.datetime(2026, 8, 19, 15, 0)
        )
        self.assertEqual(result["temp"], "27.3")
        self.assertEqual(result["rain_1h"], "0")


class TestVilageFcst(unittest.TestCase):
    @patch("weather_duty.kma_client._SESSION.get")
    def test_groups_by_date(self, mock_get):
        items = [
            {"fcstDate": "20260819", "fcstTime": "1500", "category": "TMX", "fcstValue": "34"},
            {"fcstDate": "20260819", "fcstTime": "0600", "category": "TMN", "fcstValue": "26"},
            {"fcstDate": "20260819", "fcstTime": "1500", "category": "POP", "fcstValue": "30"},
            {"fcstDate": "20260819", "fcstTime": "0900", "category": "PCP", "fcstValue": "1.0mm"},
            {"fcstDate": "20260819", "fcstTime": "1200", "category": "PCP", "fcstValue": "1mm 미만"},
            {"fcstDate": "20260819", "fcstTime": "1500", "category": "PCP", "fcstValue": "강수없음"},
            {"fcstDate": "20260819", "fcstTime": "1500", "category": "SKY", "fcstValue": "1"},
            {"fcstDate": "20260819", "fcstTime": "1500", "category": "PTY", "fcstValue": "0"},
            {"fcstDate": "20260819", "fcstTime": "1500", "category": "TMP", "fcstValue": "31"},
            {"fcstDate": "20260819", "fcstTime": "1500", "category": "REH", "fcstValue": "70"},
            {"fcstDate": "20260820", "fcstTime": "1500", "category": "TMX", "fcstValue": "33"},
            {"fcstDate": "20260820", "fcstTime": "0600", "category": "TMN", "fcstValue": "25"},
            {"fcstDate": "20260820", "fcstTime": "1500", "category": "PCP", "fcstValue": "30.0mm 이상"},
        ]
        mock_get.return_value = _mock_response(items)
        result = kma_client.get_short_term_forecast(
            "dummy-key", 60, 127, now=datetime.datetime(2026, 8, 19, 15, 20)
        )
        self.assertEqual(len(result), 2)
        day1 = result[0]
        self.assertEqual(day1["date"], "20260819")
        self.assertEqual(day1["tmin"], "26")
        self.assertEqual(day1["tmax"], "34")
        self.assertEqual(day1["pop"], 30)
        self.assertEqual(day1["condition"], "맑음")
        # 00~24시 누적: 1.0mm + 1mm(미만 표기값 그대로) = 2mm
        self.assertEqual(day1["pcp"], "2mm")
        hourly_by_time = {h["time"]: h for h in day1["hourly"]}
        self.assertEqual(hourly_by_time["0900"]["pcp"], "1.0mm")
        self.assertEqual(hourly_by_time["1200"]["pcp"], "1mm 미만")
        self.assertEqual(hourly_by_time["1500"]["pcp"], "강수없음")
        self.assertEqual(hourly_by_time["1500"]["temp"], "31")
        # 8월(여름)이라 열지수 공식이 쓰였는지 - 습도 없는 시간대는 None, 있는 시간대는 값이 나와야 함
        self.assertIsNone(hourly_by_time["0900"]["feels_like"])
        expected = kma_client.feels_like_c("31", "70", None, 8)
        self.assertAlmostEqual(hourly_by_time["1500"]["feels_like"], expected)
        self.assertEqual(day1["feels_like_max"], round(expected, 1))

        day2 = result[1]
        self.assertEqual(day2["pcp"], "30mm+")


class TestDailyPcpSum(unittest.TestCase):
    def test_all_no_rain_is_no_rain(self):
        self.assertEqual(kma_client._sum_daily_pcp(["강수없음", "강수없음"]), "강수없음")

    def test_empty_is_no_rain(self):
        self.assertEqual(kma_client._sum_daily_pcp([]), "강수없음")

    def test_sums_exact_values(self):
        self.assertEqual(kma_client._sum_daily_pcp(["1.0mm", "4.0mm", "강수없음"]), "5mm")


class TestMidTermForecast(unittest.TestCase):
    @patch("weather_duty.kma_client._SESSION.get")
    def test_combines_ta_and_land(self, mock_get):
        ta_item = {"taMin3": "24", "taMax3": "33", "taMin8": "23", "taMax8": "31"}
        land_item = {
            "wf3Am": "맑음",
            "wf3Pm": "구름많음",
            "rnSt3Am": "10",
            "rnSt3Pm": "20",
            "wf8": "흐림",
            "rnSt8": "40",
        }

        def side_effect(url, timeout):
            if "getMidTa" in url:
                return _mock_response([ta_item])
            return _mock_response([land_item])

        mock_get.side_effect = side_effect
        result = kma_client.get_mid_term_forecast(
            "dummy-key", "11B10101", "11B10101", now=datetime.datetime(2026, 8, 19, 19, 0)
        )
        day3 = next(d for d in result if d["date"] == "20260822")
        self.assertEqual(day3["tmin"], "24")
        self.assertEqual(day3["tmax"], "33")
        self.assertEqual(day3["condition"], "오전 맑음 / 오후 구름많음")
        self.assertEqual(day3["pop"], "20")

        day8 = next(d for d in result if d["date"] == "20260827")
        self.assertEqual(day8["condition"], "흐림")
        self.assertEqual(day8["pop"], "40")


class TestWarningMatch(unittest.TestCase):
    def test_match_by_keyword(self):
        warnings = [
            {"text": "폭염경보 서울, 경기 지역 발효"},
            {"text": "호우주의보 전남 지역"},
        ]
        matched = kma_client.match_region_warning(warnings, "서울")
        self.assertEqual(matched, ["폭염경보 서울, 경기 지역 발효"])

        matched_none = kma_client.match_region_warning(warnings, "제주")
        self.assertEqual(matched_none, [])


class TestErrorHandling(unittest.TestCase):
    @patch("weather_duty.kma_client._SESSION.get")
    def test_error_result_code_raises(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "response": {
                "header": {"resultCode": "30", "resultMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"},
                "body": {},
            }
        }
        mock_get.return_value = resp
        with self.assertRaises(kma_client.KmaApiError):
            kma_client.get_current_conditions("bad-key", 60, 127)


class TestServiceKeyRedaction(unittest.TestCase):
    @patch("weather_duty.kma_client._SESSION.get")
    def test_connection_error_does_not_leak_service_key(self, mock_get):
        secret_key = "TOP-SECRET-KEY-12345"
        mock_get.side_effect = requests.exceptions.ConnectionError(
            f"Failed to reach https://apis.data.go.kr/x?serviceKey={secret_key}&y=1"
        )
        with self.assertRaises(kma_client.KmaApiError) as ctx:
            kma_client.get_current_conditions(secret_key, 60, 127)
        self.assertNotIn(secret_key, str(ctx.exception))
        self.assertIn("***", str(ctx.exception))


class TestFeelsLike(unittest.TestCase):
    def test_summer_uses_heat_index_and_needs_humidity(self):
        self.assertIsNone(kma_client.feels_like_c(30, None, 3, 8))
        value = kma_client.feels_like_c(30, 70, None, 8)
        self.assertIsInstance(value, float)
        # 무더운 날 고습도에서는 체감온도가 실제 기온보다 높게 나와야 한다
        self.assertGreater(value, 30)

    def test_winter_uses_wind_chill_and_needs_wind_speed(self):
        self.assertIsNone(kma_client.feels_like_c(0, 60, None, 1))
        value = kma_client.feels_like_c(0, 60, 5, 1)
        self.assertIsInstance(value, float)
        # 바람이 불면 겨울 체감온도는 실제 기온보다 낮게 나와야 한다
        self.assertLess(value, 0)

    def test_missing_temperature_returns_none(self):
        self.assertIsNone(kma_client.feels_like_c(None, 70, 3, 8))


if __name__ == "__main__":
    unittest.main()
