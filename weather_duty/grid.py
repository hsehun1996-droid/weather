"""위경도 <-> 기상청 격자좌표(nx, ny) 변환 (LCC DFS 투영).

기상청이 공개 배포하는 변환 공식(RE/GRID/SLAT1/SLAT2/OLON/OLAT/XO/YO 상수와
LCC 투영 수식)을 그대로 파이썬으로 옮긴 것. 단기예보/초단기실황 API가 쓰는
5km 격자 nx, ny 좌표를 위도/경도로부터 직접 계산할 수 있어, 지역마다 nx/ny를
일일이 하드코딩하지 않아도 된다.

참고: https://gist.github.com/fronteer-kr/14d7f779d52a21ac2f16 (기상청 배포 공식)
"""
import math

RE = 6371.00877  # 지구 반경(km)
GRID = 5.0  # 격자 간격(km)
SLAT1 = 30.0  # 투영 위도1(degree)
SLAT2 = 60.0  # 투영 위도2(degree)
OLON = 126.0  # 기준점 경도(degree)
OLAT = 38.0  # 기준점 위도(degree)
XO = 43  # 기준점 X좌표(GRID)
YO = 136  # 기준점 Y좌표(GRID)

_DEGRAD = math.pi / 180.0

_re = RE / GRID
_slat1 = SLAT1 * _DEGRAD
_slat2 = SLAT2 * _DEGRAD
_olon = OLON * _DEGRAD
_olat = OLAT * _DEGRAD

_sn = math.tan(math.pi * 0.25 + _slat2 * 0.5) / math.tan(math.pi * 0.25 + _slat1 * 0.5)
_sn = math.log(math.cos(_slat1) / math.cos(_slat2)) / math.log(_sn)
_sf = math.tan(math.pi * 0.25 + _slat1 * 0.5)
_sf = math.pow(_sf, _sn) * math.cos(_slat1) / _sn
_ro = math.tan(math.pi * 0.25 + _olat * 0.5)
_ro = _re * _sf / math.pow(_ro, _sn)


def latlon_to_grid(lat, lon):
    """위도(lat)/경도(lon, degree) -> 기상청 격자좌표 (nx, ny)."""
    ra = math.tan(math.pi * 0.25 + (lat * _DEGRAD) * 0.5)
    ra = _re * _sf / math.pow(ra, _sn)
    theta = lon * _DEGRAD - _olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= _sn
    nx = int(math.floor(ra * math.sin(theta) + XO + 0.5))
    ny = int(math.floor(_ro - ra * math.cos(theta) + YO + 0.5))
    return nx, ny
