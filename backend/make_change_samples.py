"""변경 추적 데모 — 기존 제출본(v1)에서 몇 셀 바꾼 v2 를 올려 changelog 피드/버전 생성.

실행: python -s make_change_samples.py   (setup_weeks.py 먼저 돌려 v1 들이 있어야 함)
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

import openpyxl  # noqa: E402
from src import changelog, docstore, store  # noqa: E402

# 항목별 바꿀 셀 (시트, 셀, 새 값) — 모두 당해 raw leaf + **대표총계에 닿는 셀**이라
# changelog 에도 잡히고 카드·그래프·표(대표총계 기준)도 같이 바뀜.
#   재료비: G25(대표총계 실적)=SUM(G29,G33) → G29/G33 변경(월계=마감 → 변경 라벨 'N월 마감').
#   투자비: F12=...F10/F11(월계=마감).
#   가공비: 부서가 3월 '주차' 실적을 정정 상향 제출하는 케이스 → 변경 라벨 'N월 M차'
#           (월계 마감만이 아니라 주차 단위 변경도 시뮬에 뜨게). U13=W12(3월3차)·V13=W13(3월4차).
EDITS = {
    "material_cost":   [("재료비", "G29", 280.0), ("재료비", "G33", 30.0)],
    "investment":      [("투자비", "F10", 30.0), ("투자비", "F11", 45.5)],
    "processing_cost": [("가공비", "U13", 20.0), ("가공비", "V13", 16.0)],
    "sales_region1":   [],   # 채워질 수 있으면 아래서 자동 1셀 선택
}


def _latest_doc(area):
    docs = [d for d in docstore.list_docs() if d.get("area") == area]
    docs.sort(key=lambda d: d.get("uploaded_at", ""))
    return docs[-1] if docs else None


def main():
    for area, edits in EDITS.items():
        if not edits:
            continue
        v1 = _latest_doc(area)
        if not v1:
            print(f"{area}: v1 없음 (setup_weeks 먼저) — skip")
            continue
        p = docstore.path_of(v1["id"])
        wb = openpyxl.load_workbook(p)
        applied = []
        for sheet, cell, val in edits:
            if sheet in wb.sheetnames:
                old = wb[sheet][cell].value
                wb[sheet][cell] = val
                applied.append(f"{sheet}!{cell} {old}→{val}")
        bio = io.BytesIO()
        wb.save(bio)
        data = bio.getvalue()
        # v2 파일명
        base = store.submission_filename(area, v1["period_id"])
        prev_n = sum(1 for d in docstore.list_docs()
                     if d.get("area") == area and d.get("period_id") == v1["period_id"])
        fname = base.replace("_제출.xlsx", f"_제출_v{prev_n + 1}.xlsx")
        rec = docstore.save(data, fname, category=docstore.CAT_DEPT,
                            period_id=v1["period_id"], area=area)
        chg = changelog.record_on_upload(area, data, rec)
        print(f"{area}: {fname}")
        for a in applied:
            print(f"    {a}")
        print(f"    → 변경 피드: {chg['summary'] if chg else '(직전 버전 없음)'}")

    print("\n=== 변경 피드(최신) ===")
    for e in changelog.load_feed(10):
        s = e["summary"]
        print(f"  {e['at']} [{e['항목']}] 변경 {s['changed']} / 추가 {s['added']} / 삭제 {s['removed']}")
        for ch in e["changed"][:3]:
            print(f"      {ch['부서경로']} {ch['월']}월 {ch.get('종류')} {ch['old']}→{ch['new']}")


if __name__ == "__main__":
    main()
