#!/usr/bin/env python3
"""로또 6/45 데이터 갱신 (표준 라이브러리만 사용)

  python scripts/update.py                 # 신규 회차만 추가 (출처 2곳 이상 일치 시)
  python scripts/update.py --audit         # 전체 데이터를 출처와 대조해 불일치 보고
  python scripts/update.py --audit --fix   # 불일치 회차를 다수결 값으로 교정
  python scripts/update.py --source seed   # 시드 복원 후 신규 회차 추가 (오프라인 복원 가능)
  python scripts/update.py --rebuild       # 출처 다수결로 1회~최신 전체 재구성
  python scripts/update.py --add 1245 2026-10-10 1,2,3,4,5,6 7   # 수동 추가
종료 코드: 0 정상 / 2 출처 간 불일치(확인 필요, Actions 실패로 표시됨)
"""
import argparse, json, os, shutil, sys, urllib.request
import datetime as dt
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "lotto645.json")
BACKUP = os.path.join(ROOT, "data", "lotto645.backup.json")
SEED = os.path.join(ROOT, "data", "seed", "lotto645_seed.json")
BASE = dt.date(2002, 12, 7)  # 1회 추첨일(토)
RAW = "https://raw.githubusercontent.com/"
SOURCES = {
    "kysmk1987": RAW + "kysmk1987-lgtm/lotto-data/main/history.json",
    "JunKwon91": RAW + "JunKwon91/lotto-data/main/data/lotto-history.json",
    "uriseozz": RAW + "uriseozz/lotto-data/main/lotto.json",
}
OFFICIAL = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={}"


def _n(rnd, date, nums, bonus):
    return int(rnd), date, tuple(sorted(int(x) for x in nums)), int(bonus)


PARSERS = {
    "kysmk1987": lambda j: (_n(d["round"], d["date"], d["numbers"], d["bonus"]) for d in j["draws"]),
    "JunKwon91": lambda j: (_n(d["drawNo"], d["date"], d["numbers"], d["bonusNo"]) for d in j["data"]),
    "uriseozz": lambda j: (_n(r["id"], r["draw_date"], [r[f"n{i}"] for i in range(1, 7)], r["bonus"]) for r in j["rounds"]),
}


def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def sched_date(r):
    return (BASE + dt.timedelta(days=7 * (r - 1))).isoformat()


def expected_latest():
    """KST 기준 가장 최근에 추첨(토 21:00 이후)된 회차."""
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
    back = (now.date().weekday() - 5) % 7
    sat = now.date() - dt.timedelta(days=back)
    if back == 0 and now.hour < 21:
        sat -= dt.timedelta(days=7)
    return 1 + (sat - BASE).days // 7


def validate(draws):
    errs = []
    if [d["round"] for d in draws] != list(range(1, len(draws) + 1)):
        errs.append("회차가 1부터 연속되지 않음")
    for d in draws:
        r, n, b = d["round"], d["numbers"], d["bonus"]
        if len(n) != 6 or len(set(n)) != 6 or n != sorted(n):
            errs.append(f"{r}회: 번호 개수/중복/정렬 오류")
        if any(not 1 <= v <= 45 for v in n + [b]) or b in n:
            errs.append(f"{r}회: 번호 범위/보너스 오류")
        if d["date"] != sched_date(r):
            errs.append(f"{r}회: 추첨일이 주간 일정과 불일치")
    return errs


def load(path):
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    return obj["draws"] if isinstance(obj, dict) else obj


def save(draws, source):
    errs = validate(draws)
    if errs:
        sys.exit("검증 실패, 저장하지 않음:\n" + "\n".join(errs[:20]))
    if os.path.exists(DATA):
        shutil.copyfile(DATA, BACKUP)  # 교체 전 자동 백업
    tmp = DATA + ".tmp"
    kst = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
    obj = {"updatedAt": kst.strftime("%Y-%m-%d %H:%M KST"), "source": source, "draws": draws}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DATA)  # 검증 통과 후에만 교체
    print(f"저장 완료: {len(draws)}회차 (마지막 {draws[-1]['round']}회)")


def load_sources(need=2):
    out = {}
    for name, url in SOURCES.items():
        try:
            out[name] = {r: (d, n, b) for r, d, n, b in PARSERS[name](get_json(url))}
            print(f"  출처 {name}: {len(out[name])}회차 (최신 {max(out[name])}회)")
        except Exception as e:
            print(f"  출처 {name} 실패: {e}")
    if len(out) < need:
        sys.exit(f"응답한 출처가 {need}곳 미만 → 중단 (기존 데이터 유지)")
    return out


def official(r):
    """보조 출처(실패해도 무시)."""
    try:
        j = get_json(OFFICIAL.format(r), 20)
        if j.get("returnValue") == "success":
            return _n(j["drwNo"], j["drwNoDate"], [j[f"drwtNo{i}"] for i in range(1, 7)], j["bnusNo"])[1:]
    except Exception:
        pass
    return None


def consensus(r, srcs):
    """(상태, (번호,보너스), 이견여부). 상태: ok / hold(근거 1곳 이하) / conflict(동률)"""
    votes = Counter()
    for s in srcs.values():
        rec = s.get(r)
        if rec and rec[0] == sched_date(r):  # 추첨일이 일정과 다르면 무효표
            votes[(rec[1], rec[2])] += 1
    if not votes:
        return "hold", None, False
    top = votes.most_common()
    if top[0][1] >= 2 and (len(top) == 1 or top[1][1] < top[0][1]):
        return "ok", top[0][0], len(top) > 1
    if len(top) == 1:
        return "hold", None, False
    return "conflict", None, False


def collect(draws, target, srcs, use_official=True):
    for r in range(len(draws) + 1, target + 1):
        st, val, dissent = consensus(r, srcs)
        if st == "hold" and use_official and "official" not in srcs.get("_off_failed", {}):
            o = official(r)
            if o:
                srcs.setdefault("official", {})[r] = (sched_date(r),) + o
                st, val, dissent = consensus(r, srcs)
            else:
                srcs["_off_failed"] = {"official": 1}
        if st == "conflict":
            _conflict(r)
        if st != "ok":
            print(f"{r}회: 일치하는 출처가 2곳 미만 → 대기 (다음 실행에서 재시도)")
            return
        if dissent:
            print(f"::warning::{r}회: 일부 출처가 다수결과 다름 (다수결 채택)")
        draws.append({"round": r, "date": sched_date(r), "numbers": list(val[0]), "bonus": val[1]})
        print(f"{r}회 추가: {val[0]} + {val[1]}")


def _conflict(r):
    print(f"::error::{r}회 출처 간 값이 달라 확정할 수 없음 → 확인 필요 (기존 데이터는 변경하지 않음)")
    sys.exit(2)


def audit(draws, srcs, fix=False):
    bad = []
    for d in draws:
        st, val, _ = consensus(d["round"], srcs)
        if st == "ok" and (tuple(d["numbers"]), d["bonus"]) != val:
            bad.append((d["round"], d["numbers"], d["bonus"], list(val[0]), val[1]))
            if fix:
                d["numbers"], d["bonus"] = list(val[0]), val[1]
    for r, n, b, n2, b2 in bad:
        print(f"::warning::{r}회 불일치: 저장값 {n}+{b} / 출처 다수결 {n2}+{b2}")
    print(f"대조 결과: 불일치 {len(bad)}건")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--source", choices=["seed"])
    ap.add_argument("--add", nargs=4, metavar=("ROUND", "DATE", "NUMS", "BONUS"))
    a = ap.parse_args()

    if a.add:
        draws = load(DATA)
        n = sorted(int(x) for x in a.add[2].split(","))
        draws.append({"round": int(a.add[0]), "date": a.add[1], "numbers": n, "bonus": int(a.add[3])})
        return save(draws, "manual")
    if a.rebuild:
        srcs, target, draws = load_sources(), expected_latest(), []
        print(f"전체 재구성(다수결): 1~{target}회")
        collect(draws, target, srcs, use_official=False)
        if len(draws) < target - 2:
            sys.exit(f"재구성 실패({len(draws)}/{target}): 기존 데이터는 변경하지 않았습니다. --source seed 를 사용하세요.")
        return save(draws, "rebuild(consensus)")
    if a.source == "seed":
        draws, src = load(SEED), "seed"
        srcs = load_sources(need=0)
        if len(srcs) >= 2:
            collect(draws, expected_latest(), srcs)
            src = "seed+incremental"
        else:
            print("출처 접속 불가 → 시드 그대로 복원합니다.")
        return save(draws, src)

    if not os.path.exists(DATA):
        sys.exit("data/lotto645.json 없음 → --source seed 로 복구하세요.")
    draws = load(DATA)
    if validate(draws):
        sys.exit("기존 데이터 검증 실패 → --source seed 로 복구하세요.")
    srcs = load_sources()
    before = len(draws)
    if a.audit:
        bad = audit(draws, srcs, a.fix)
        return save(draws, "audit-fix") if (a.fix and bad) else None
    collect(draws, expected_latest(), srcs)
    audit(draws[:before], srcs)  # 기존 데이터 이상 여부는 경고로만 알림
    if len(draws) > before:
        save(draws, "incremental")
    else:
        print("신규 회차 없음 (기존 데이터 유지)")


if __name__ == "__main__":
    main()
