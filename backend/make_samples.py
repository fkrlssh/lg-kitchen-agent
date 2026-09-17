"""회차별 진짜 샘플 엑셀 생성 — 원본에서 실적을 회차 시점까지만 남기고 미래 비움.

- 실적(leaf raw)만 트림. 목표/계획·작년(25) 실적은 그대로.
- 주차형 시트: cutoff_week 이후 주차 실적 제거. 월형 시트: cutoff_month 이후 월 실적 제거.
- 회차마다 겹치는 과거 주차/월은 동일값 → 정합성 검증 테스트 가능.
실행: python -s make_samples.py
"""
import glob
import re
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from src import parsing_lg  # noqa: E402

ORIG = glob.glob("../docs/lg_samples/excel/*주차추가*ver0.1.xlsx")[0]
OUT_DIR = Path("../sample_uploads")

# 회차 → (cutoff_week=포함 마지막 주차, cutoff_month=확정 마지막 월)
#  ver0.1(주차추가) 데이터는 1~4월. 주차: 1월 W1-5, 2월 W6-9, 3월 W10-14, 4월 W14-18.
#  월값은 그 달 끝나야 확정 → 월형 시트는 완료된 월까지만 (운영 현실 반영)
PERIODS = {
    "2026-02-2차": {"week": 9, "month": 1},
    "2026-03-2차": {"week": 13, "month": 2},
    "2026-04-1차": {"week": 15, "month": 3},
    "2026-04-2차": {"week": 18, "month": 4},
}


def _wnum(s):
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else 0


def main():
    OUT_DIR.mkdir(exist_ok=True)
    # 원본 1회 파싱 → 실적 leaf 셀 좌표 + 위치정보
    df, _ = parsing_lg.parse_workbook(ORIG)
    cur_act = df[(df["연도구분"] == "당해") & (df["종류"] == "실적")].copy()
    cur_act["w"] = cur_act["주차"].map(lambda x: _wnum(x) if x is not None and str(x) != "nan" else None)

    for tag, cut in PERIODS.items():
        wb = openpyxl.load_workbook(ORIG, data_only=False)  # 수식 보존(캐시는 어차피 날아감)
        cleared = 0
        for _, r in cur_act.iterrows():
            # 트림 대상 판단
            drop = False
            if r["구분"] == "주차" and r["w"] is not None:
                drop = r["w"] > cut["week"]
            elif r["구분"] == "월계":
                drop = int(r["월"]) > cut["month"]
            if not drop:
                continue
            # 원본셀 "Area_A!R3" → 셀 비움
            ref = str(r["원본셀"])
            if "!" not in ref:
                continue
            sheet, cell = ref.split("!", 1)
            if sheet in wb.sheetnames:
                wb[sheet][cell] = None
                cleared += 1
        out = OUT_DIR / f"실적데이터_{tag}.xlsx"
        wb.save(out)
        print(f"{tag}: 실적 {cleared}셀 비움 → {out.name}")


if __name__ == "__main__":
    main()
