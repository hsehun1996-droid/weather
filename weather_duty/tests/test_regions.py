import unittest

from weather_duty import grid, regions


class TestGridConversion(unittest.TestCase):
    def test_known_reference_points(self):
        self.assertEqual(grid.latlon_to_grid(37.5665, 126.9780), (60, 127))
        self.assertEqual(grid.latlon_to_grid(35.1798, 129.0750), (98, 76))
        self.assertEqual(grid.latlon_to_grid(33.4996, 126.5312), (53, 38))


class TestAllRegions(unittest.TestCase):
    def test_loads_250_sigungu(self):
        all_regions = regions.all_regions()
        self.assertGreaterEqual(len(all_regions), 250)
        self.assertIn("서울특별시 종로구", all_regions)
        self.assertIn("경상북도 안동시", all_regions)

    def test_seoul_jongno_matches_known_values(self):
        info = regions.all_regions()["서울특별시 종로구"]
        self.assertEqual(info["mid_ta_regid"], "11B10101")
        self.assertEqual(info["mid_land_regid"], "11B00000")
        self.assertEqual(info["warn_keyword"], "종로구")
        self.assertEqual(info["asos_stn_id"], "108")

    def test_gangwon_yeongdong_vs_yeongseo_split(self):
        all_regions = regions.all_regions()
        gangneung = all_regions["강원특별자치도 강릉시"]
        chuncheon = all_regions["강원특별자치도 춘천시"]
        self.assertEqual(gangneung["mid_land_regid"], "11D20000")
        self.assertEqual(chuncheon["mid_land_regid"], "11D10000")

    def test_every_region_has_valid_grid_and_regids(self):
        for name, info in regions.all_regions().items():
            self.assertIsInstance(info["nx"], int, name)
            self.assertIsInstance(info["ny"], int, name)
            self.assertTrue(info["mid_ta_regid"], name)
            self.assertTrue(info["mid_land_regid"], name)
            self.assertTrue(info["asos_stn_id"], name)


class TestAsosStations(unittest.TestCase):
    def test_nearest_station_for_known_point(self):
        stations = regions._load_asos_stations()
        # 서울시청 인근 좌표는 서울(108) 관측소가 가장 가까워야 한다.
        self.assertEqual(regions._nearest_asos_stn_id(37.5665, 126.9780, stations), "108")

    def test_build_region_info_includes_asos_stn_id(self):
        midterm_points = regions._load_midterm_ta_points()
        info = regions.build_region_info(
            37.5665, 126.9780, "서울특별시", "종로구", midterm_points
        )
        self.assertEqual(info["asos_stn_id"], "108")


if __name__ == "__main__":
    unittest.main()
