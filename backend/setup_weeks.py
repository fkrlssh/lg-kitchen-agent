"""실적관리 데모 — 부서별로 서로 다른 주차 상태 세팅 (latest-wins 시연).

현재 주차 = 5월 3주차 (A·D·L 도달). B=5월 2주차, G=5월 1주차 → 뒤처짐(미제출).
실행: python -s setup_weeks.py
"""
import glob
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

import openpyxl  # noqa: E402
from openpyxl.utils import column_index_from_string, get_column_letter  # noqa: E402
from src import docstore, master_lg, parsing_lg, registry, store  # noqa: E402

# ver0.1(2026-06-24 '주차추가') 신규 양식 — 시트명 한글, 데이터 1~4월.
ORIG = glob.glob("../docs/lg_samples/excel/*주차추가*ver0.1.xlsx")[0]
# 회차 = 정밀 차수(월중 몇째 주). 최대 주차 W18 = 4월 5차 → '2026-04-5'.
# (infer_period_id 와 같은 numbering: WEEK_MONTH[18]=(4,5))
PERIOD = "2026-04-5"
# 항목(슬러그)별 목표 주차 — 데이터는 4월(W14~18)까지. 현재 주차 = W18(4월 5차).
# 가공비·품질을 앞 주차로 묶어 '뒤처짐(미제출)' latest-wins 시연.
DEMO = {s: 18 for s in registry.EXPECTED_SLUGS}
DEMO["processing_cost"] = 16   # 4월 3차 → 뒤처짐
DEMO["quality"] = 14           # 4월 1차 → 더 뒤처짐
# 전체 종합엔 파생(고정비=하위 4합)도 포함 — 제출 대상 아니나 구성요소가 차서 계산됨
MASTER_KEEP = {**DEMO, registry.DERIVED_SLUG: 99}


def wn(x):
    m = re.search(r"\d+", str(x))
    return int(m.group()) if m else 0


def _drop_future(r, tw, twm):
    """제출 부서 트림 판정 — 목표 주차 이후 실적 / 그 달 이후 월계."""
    if r["구분"] == "주차":
        return wn(r["주차"]) > tw
    if r["구분"] == "월계":
        return int(r["월"]) > twm
    return False


def main():
    # data + documents 비우기 (Win+Dropbox 잠금 관대하게)
    for d in (store.DATA_DIR, docstore.DOC_DIR):
        if d.exists():
            for p in sorted(d.rglob("*"), reverse=True):
                try:
                    p.unlink() if p.is_file() else p.rmdir()
                except OSError:
                    pass

    df, _ = parsing_lg.parse_workbook(ORIG)
    cur_act = df[(df["연도구분"] == "당해") & (df["종류"] == "실적")]

    # ── 비울 셀 좌표 모으기 ──
    # save_excel 은 매 호출마다 _area_tables/_master_table 을 source 파일 전체로 재계산한다.
    # 따라서 부서별 only_area 업로드를 반복하면 캐시가 '마지막 파일'(다른 부서 시트는 안 잘림)로
    # 덮인다 → 트림 무효. 해결: 모든 부서 시트를 한 파일에 트림해서 save_excel 을 단 한 번 호출.
    clear: set = set()
    for area, tw in DEMO.items():               # 제출 부서: 목표 주차 이후 실적만 비움(트림)
        twm = store.WEEK_MONTH.get(tw, (12, 1))[0]
        for _, r in cur_act[cur_act["항목"] == area].iterrows():
            if _drop_future(r, tw, twm) and "!" in str(r["원본셀"]):
                clear.add(str(r["원본셀"]))
    for area in df["항목"].unique():            # 미제출(운영자·파생 등): 그 Area leaf 전부 비움 → 미수집
        if area in DEMO:
            continue
        for _, r in df[df["항목"] == area].iterrows():
            if "!" in str(r["원본셀"]):
                clear.add(str(r["원본셀"]))

    # ── 마감 실적(월계) lag 시연 = 제거(방향 A) ──
    # 예전엔 '마감은 다음 달에 늦게 도착'을 흉내내려고 일부 항목의 그 달 마감(월계)을 캐시에서 비워
    # /reports 잠정(※) 처리했다. 그런데 보관 문서·CSV엔 마감이 남아 **다운로드 ≠ 보고서**가 됐다.
    # → 인위 마감 삭제를 없애 모든 항목이 파일의 진짜 마감을 그대로 표시(보고서=다운로드=CSV 일치).
    #   (마감 lag '기능' 자체는 코드에 남아있어 진짜로 마감 안 온 실데이터엔 그대로 동작.)
    #   latest-wins(부서별 다른 주차=미제출) 시연은 위 future 트림으로 그대로 유지된다.

    # ── 정합성 경고 시연 ── 물류비는 3월 마감(월계)은 있는데 3월 2차(W11) 주차 실적만 비운다.
    # → 마감 있으니 그 달은 확정·요청 안 함, 대신 '3월 마감 있으나 주차 불완전' 경고(제출오류) 표시.
    #   (재료비는 완전 미수집 시연으로 바뀌어, 정합성 경고는 완전 제출 항목인 물류비로 이동.)
    ANOMALY = {"logistics_cost": [11]}   # 항목 → 비울 주차 ISO번호(그 달 마감은 둠)
    for area, aw in ANOMALY.items():
        for _, r in cur_act[(cur_act["항목"] == area) & (cur_act["구분"] == "주차")].iterrows():
            if "!" in str(r["원본셀"]) and store._wnum(r["주차"]) in aw:
                clear.add(str(r["원본셀"]))

    # (재료비 완전 미수집 시연은 제거 — 재료비는 정상 제출로 복원. 미수집/공란 감지 로직은
    #  aggregate_lg·store 에 그대로 남아 실데이터/다른 항목이 미수집이면 동일하게 동작.)

    # ── 예측치(잠정) 시연 ── 물류비는 현재월(4월) 마감(월계)만 미도착(주차값은 유지).
    #   → 물류비 4월 = 주차값으로 추정(잠정): 그래프 4월 점선/연한, 표·카드 ※. (3월 W11 정합성경고와 별개 달.)
    PROV_MARGIN = {"logistics_cost": 4}        # 항목 → 마감(월계) 비울 달
    for area, mo in PROV_MARGIN.items():
        for _, r in cur_act[(cur_act["항목"] == area) & (cur_act["구분"] == "월계")
                            & (cur_act["월"] == mo)].iterrows():
            if "!" in str(r["원본셀"]):
                clear.add(str(r["원본셀"]))

    # ── 셀 단위 누락(부분 구멍) 시연 ── 받은 주차 안에서 leaf 실적 '한 칸'만 비운다(목표·앞뒤 주차는 둠).
    # ⚠️ raw 값 셀이어야 진짜 빈 칸(area_table 평가값 None). 수식 셀(cur_act 엔 없음)은 못 비움.
    # 품질 '제품1 / 유상수익' 2월 2차(W7) 실적 1칸 → /data '실적 빈 셀' 경고 + /reports 셀 하이라이트.
    HOLE = [("quality", "제품1 / 유상수익", 7)]
    for area, leaf, wk in HOLE:
        h = cur_act[(cur_act["항목"] == area) & (cur_act["부서경로"] == leaf)
                    & (cur_act["구분"] == "주차") & (cur_act["주차"].map(store._wnum) == wk)]
        for _, r in h.iterrows():
            if "!" in str(r["원본셀"]):
                clear.add(str(r["원본셀"]))

    # 병합 트림본 1개 → data CSV + 보고서 캐시 한 번에 (트림본 기준으로 정합)
    wb = openpyxl.load_workbook(ORIG, data_only=False)
    for ref in clear:
        sh, c = ref.split("!", 1)
        if sh in wb.sheetnames:
            wb[sh][c] = None
    merged = Path("_tmp_merged.xlsx")
    wb.save(merged)
    try:
        store.save_excel(str(merged), period_id=PERIOD)
    finally:
        merged.unlink(missing_ok=True)

    # 보고서 캐시 결과 레벨 트림 — 제출 부서만 + 각자 기준 주차 이후 주차 제거.
    # (엑셀 셀 비우기는 영역별 수식 구조 차이로 불완전 → 계산 끝난 표에서 주차번호로 자름)
    store.trim_area_tables(PERIOD, MASTER_KEEP)       # 개별 Area 뷰 (제출 부서 + 고정비 파생 유지)
    store.trim_master_headline(PERIOD, MASTER_KEEP)   # 칩·요약·차트 (master_detail 재집계, H 포함)
    store.trim_master_table(PERIOD, MASTER_KEEP)      # 전체 종합 표 (합계행 재합산, H 포함)
    store.mask_missing_actual(PERIOD)                 # 실적 전무(미수집) 항목 개별표 공란화(소계 0 잔여 제거)


    # 문서관리 보관함 — 부서별 개별 제출본. **적재 데이터(merged)와 동일하게** 비운다:
    #   merged 에 적용한 clear 셀 중 이 항목 시트분을 그대로 null → 다운로드한 파일 == /reports 표시
    #   (미래주차 트림·정합성 경고·셀 누락 모두 일치). 가짜 마감 삭제는 제거됨(방향 A).
    for area, tw in DEMO.items():
        wb2 = openpyxl.load_workbook(ORIG, data_only=False)
        sheet = registry.BY_SLUG[area]["sheet"]
        for ref in clear:
            sh, c = ref.split("!", 1)
            if sh == sheet and sh in wb2.sheetnames:
                wb2[sh][c] = None
        tmp = Path(f"_tmp_{area}.xlsx")
        wb2.save(tmp)
        clean = store.submission_filename(area, PERIOD)
        docstore.save(tmp.read_bytes(), clean, category=docstore.CAT_DEPT, period_id=PERIOD, area=area)
        tmp.unlink(missing_ok=True)
        print(f"{area}: {store.week_label(tw)} → {clean}")

    st = store.latest_status()
    print(f"\n현재 주차: {st['current_label']} | 미제출: {st['missing']}")
    for it in st["items"]:
        if it["source"] == "부서":
            print(f"   {it['항목']}: 최신={it['latest_label']} 제출={it['received']}")

    # 변경 추적 데모 — v1 위에 몇 셀 바꾼 v2 생성(재료비·투자비) → 변경 이력/피드/타임라인 채움.
    # setup_weeks 를 재실행해도(=documents 초기화돼도) 변경 추적 데모가 유지되도록 여기서 함께 생성.
    try:
        import make_change_samples
        print("\n── 변경 추적 데모(v2) ──")
        make_change_samples.main()
    except Exception as e:  # 변경 샘플 실패해도 본 시드는 유지
        print(f"변경 샘플 생성 skip: {e}")

    # 변경 시뮬레이션 캐시 워밍 — 각 변경 항목의 per-doc 결과(headline/전체표/Area, 호출당 ~2.5s)를
    # 미리 계산·저장해 /simulation 첫 조회가 즉시 뜨게 한다. 실사용 배선 = 항목별 실제 문서에서
    # 변경월만 조립(합본 스냅샷 불필요). 캐시=documents/_headlines·_doc_mtables·_doc_atables.
    try:
        from src import changelog
        cands = changelog.simulate_versions(4)              # 후보(+_doc_headline 워밍)
        areas = [c["항목"] for c in cands]
        picks = {a: None for a in areas}                    # picks dict (항목→최신본)
        changelog.compose_master_table(PERIOD, picks)       # _doc_master_table 워밍
        for a in areas:
            changelog.compose_area_table(PERIOD, a, {a: None})  # _doc_area_table 워밍
        print(f"시뮬레이션 캐시 워밍 완료 — 변경 항목 {len(areas)}개")
    except Exception as e:
        print(f"시뮬 캐시 워밍 skip: {e}")


if __name__ == "__main__":
    main()
