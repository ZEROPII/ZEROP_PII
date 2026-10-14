# 논문 그림 3개
#
#   fig1_risk_trajectory     → (a) 턴별 후보 수 k_val (중앙값과 사분위) / (b) 턴 t까지 위반한 대상의 누적 비율
#   fig2_privacy_utility     → 정보 유지율(가로) 대 위반 대상 비율(세로). 운영 k_req를 바꾼 Defender 곡선과
#                              턴별 방어, 억제만 하는 Defender, 고정 일반화, 방어 없음을 한 평면에 둔다. 무릎점 표시
#   fig3_sensitivity         → (a) 기준 집단 변형 / (b) 추출 누락 비율 / (c) 최대 일반화 단계
#
# 흑백 인쇄에서도 구분되도록 색과 함께 선 모양·표식을 다르게 쓴다.
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

STYLE = {
    "C0": {"color": "#4D4D4D", "linestyle": "--", "marker": "s"},
    "C1S": {"color": "#D55E00", "linestyle": ":", "marker": "^"},
    "C1": {"color": "#0072B2", "linestyle": "-", "marker": "o"},
    "C1-g0": {"color": "#CC79A7", "linestyle": "-.", "marker": "D"},
    "STATIC": {"color": "#009E73", "linestyle": "-", "marker": "v"},
}

TEXT = {
    "ko": {
        "C0": "방어 없음 (C0)", "C1S": "턴별 방어 (C1S)", "C1": "누적 방어 (C1)",
        "C1-g0": "누적 방어, 억제만", "STATIC": "고정 일반화",
        "turn": "대화 턴", "k": "남은 후보 수 k (로그)", "kreq": "평가 기준 k = {k}",
        "share": "위반한 대상의 누적 비율", "retention": "정보 유지율 (%)", "violation": "위반 대상 비율 (%)",
        "fig1a": "(a) 턴별 후보 수 (중앙값, 사분위 범위)", "fig1b": "(b) 위반 도달 누적 비율",
        "fig2a": "(a) 보호–유용성 평면", "fig2b": "(b) 누적 방어의 운영 k_req", "optimum": "최적 운영점", "knee": "무릎점", "protection": "보호: 모든 대상이 보장받은 최소 후보 수 k (로그)",
        "fig3a": "(a) 기준 집단", "fig3b": "(b) 추출 누락 비율", "fig3c": "(c) 최대 일반화 단계",
        "miss": "Defender가 놓친 관찰 비율 (%)", "kop": "Defender 운영 k_req", "gen": "최대 일반화 단계", "unlimited": "제한 없음",
        "suppress_only": "억제만",
    },
    "en": {
        "C0": "No defense (C0)", "C1S": "Per-turn (C1S)", "C1": "Cumulative (C1)",
        "C1-g0": "Cumulative, suppress only", "STATIC": "Static generalization",
        "turn": "Turn", "k": "Remaining candidates k (log)", "kreq": "evaluation k = {k}",
        "share": "Cumulative share violated", "retention": "Information retention (%)",
        "violation": "Targets violated (%)",
        "fig1a": "(a) Candidates per turn (median, IQR)", "fig1b": "(b) Cumulative violation",
        "fig2a": "(a) Privacy–utility plane", "fig2b": "(b) Operating k_req of C1", "optimum": "optimum", "knee": "knee", "protection": "Protection: worst-case minimum k (log)",
        "fig3a": "(a) Reference population", "fig3b": "(b) Extraction misses", "fig3c": "(c) Max generalization",
        "miss": "Observations missed by Defender (%)", "kop": "Defender k_req", "gen": "Max generalization steps", "unlimited": "unlimited",
        "suppress_only": "suppress only",
    },
}

KOREAN_FONTS = ("AppleGothic", "Apple SD Gothic Neo", "Malgun Gothic", "NanumGothic", "Noto Sans CJK KR",
                "Noto Sans KR", "Source Han Sans K", "Noto Sans CJK JP")   # CJK JP 글꼴 파일에도 한글이 들어 있다


def choose_language(requested: str) -> str:
    """ko를 원하면 한글 글꼴을 찾고, 없으면 en으로 바꾼다 (깨진 글자 대신)."""
    if requested == "en":
        _base_style(None)
        return "en"
    names = {font.name for font in font_manager.fontManager.ttflist}
    font = next((name for name in KOREAN_FONTS if name in names), None)
    if font is None:
        if requested == "ko":
            print("주의: 한글 글꼴을 찾지 못해 그림을 영어로 그립니다.")
        _base_style(None)
        return "en"
    _base_style(font)
    return "ko"


def _base_style(font: str | None) -> None:
    plt.rcParams.update({
        "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8, "legend.fontsize": 7,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#DDDDDD", "grid.linewidth": 0.5, "axes.axisbelow": True,
        "savefig.dpi": 300, "savefig.bbox": "tight", "axes.unicode_minus": False,
    })
    if font:
        plt.rcParams["font.family"] = font


def _save(fig: Any, out: Path, name: str) -> list[Path]:
    paths = []
    for ext in ("png", "pdf"):
        path = out / f"{name}.{ext}"
        fig.savefig(path)
        paths.append(path)
    plt.close(fig)
    return paths


def fig1(trajectories: dict[str, list[dict]], survivals: dict[str, list[dict]], eval_k: int, lang: str,
         out: Path) -> list[Path]:
    t = TEXT[lang]
    fig, (left, right) = plt.subplots(1, 2, figsize=(7.0, 2.7))
    for arm in ("C0", "C1S", "C1"):
        rows, style = trajectories[arm], STYLE[arm]
        turns = [r["turn"] for r in rows]
        left.plot(turns, [r["median"] for r in rows], label=t[arm], linewidth=1.4, markersize=3.5, **style)
        left.fill_between(turns, [r["q1"] for r in rows], [r["q3"] for r in rows], color=style["color"], alpha=0.12,
                          linewidth=0)
        rows = survivals[arm]
        right.step([r["turn"] for r in rows], [100 * r["violated_share"] for r in rows], where="post",
                   label=t[arm], color=style["color"], linestyle=style["linestyle"], linewidth=1.4)
    left.axhline(eval_k, color="#B00020", linewidth=0.9, linestyle=(0, (4, 3)))
    left.text(max(r["turn"] for r in trajectories["C0"]), eval_k * 1.3, t["kreq"].format(k=eval_k), color="#B00020",
              fontsize=7, ha="right")
    left.set_yscale("log")
    left.set_xlabel(t["turn"])
    left.set_ylabel(t["k"])
    left.set_title(t["fig1a"], loc="left")
    right.set_xlabel(t["turn"])
    right.set_ylabel(t["share"] + " (%)")
    right.set_ylim(-3, 103)
    right.set_title(t["fig1b"], loc="left")
    for axis in (left, right):
        axis.set_xticks(range(1, max(r["turn"] for r in trajectories["C0"]) + 1))
    right.legend(frameon=False, loc="upper left")
    return _save(fig, out, "fig1_risk_trajectory")


def fig2(series: dict[str, list[dict]], optimum: dict | None, eval_k: int, lang: str, out: Path) -> list[Path]:
    """
    (a) 보호–유용성 평면: 가로 정보 유지율 %, 세로 위반 대상 비율 %. 오른쪽 아래가 좋은 방향
    (b) 누적 방어의 운영 k_req에 따른 위반 비율과 정보 유지율. 최적 운영점을 세로선으로 표시
    series: 이름 → [{"retention", "violation", "label", "k_req"}, ...] (설정 순서)
    """
    t = TEXT[lang]
    fig, (left, right) = plt.subplots(1, 2, figsize=(7.0, 2.9), gridspec_kw={"width_ratios": [1.15, 1.0]})
    for name in ("C1", "C1-g0", "C1S", "STATIC", "C0"):
        points = series.get(name) or []
        if not points:
            continue
        style = STYLE[name]
        left.plot([p["retention"] for p in points], [p["violation"] for p in points], label=t[name], linewidth=1.2,
                  markersize=4 if name != "C0" else 6, **style)
        if name in ("C1", "STATIC"):
            seen: set[tuple[float, float]] = set()
            for p in points:
                key = (round(p["retention"], 1), round(p["violation"], 1))
                if key in seen or (p["violation"] == 0 and p is not optimum and name == "C1") \
                        or (name == "STATIC" and p["label"] not in ("G1", "G2")):
                    continue
                seen.add(key)
                left.annotate(p["label"], (p["retention"], p["violation"]), textcoords="offset points", xytext=(3, 4),
                              fontsize=6, color=style["color"])
    if optimum:
        left.scatter([optimum["retention"]], [optimum["violation"]], s=90, facecolors="none", edgecolors="#B00020",
                     linewidths=1.2, zorder=5)
        left.annotate(f"{t['optimum']} ({optimum['label']})", (optimum["retention"], optimum["violation"]),
                      textcoords="offset points", xytext=(4, 14), fontsize=7, color="#B00020")
    left.set_xlabel(t["retention"])
    left.set_ylabel(t["violation"] + f" (k<{eval_k})")
    left.set_xlim(-3, 103)
    left.set_ylim(-3, 103)
    left.set_title(t["fig2a"], loc="left")
    left.legend(frameon=False, loc="upper left", fontsize=6)

    c1 = [p for p in series.get("C1") or [] if p.get("k_req")]
    ks = [p["k_req"] for p in c1]
    right.plot(ks, [p["violation"] for p in c1], color="#B00020", marker="o", markersize=3.5, linewidth=1.3,
               label=t["violation"])
    right.plot(ks, [p["retention"] for p in c1], color=STYLE["C1"]["color"], marker="s", markersize=3.5,
               linewidth=1.3, label=t["retention"])
    c1s = [p for p in series.get("C1S") or [] if p.get("k_req")]
    if c1s:
        right.plot([p["k_req"] for p in c1s], [p["violation"] for p in c1s], color="#B00020", linestyle=":",
                   linewidth=1.0, label=t["violation"] + " · " + t["C1S"])
    if optimum:
        right.axvline(optimum["k_req"], color="#B00020", linewidth=0.9, linestyle=(0, (4, 3)))
        right.text(optimum["k_req"] * 1.08, 28, f"{t['optimum']}\nk_req = {optimum['k_req']}", color="#B00020",
                   fontsize=7, va="center")
    right.set_xscale("log")
    right.set_xlabel(t["kop"])
    right.set_ylabel("%")
    right.set_ylim(-3, 103)
    right.set_title(t["fig2b"], loc="left")
    right.legend(frameon=False, loc="upper right", fontsize=6)
    fig.tight_layout(w_pad=1.5)
    return _save(fig, out, "fig2_privacy_utility")


def fig3(population_rows: Sequence[dict], miss_rows: Sequence[dict], miss_reference: float,
         generalization_rows: Sequence[dict], lang: str, out: Path) -> list[Path]:
    t = TEXT[lang]
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(7.0, 2.5), gridspec_kw={"width_ratios": [1.5, 1.1, 1.0]})
    # (a) 기준 집단: 갈래별 위반 비율
    names = [r["population"] for r in population_rows if r["arm"] == "C0"]
    width = 0.26
    for offset, arm in zip((-width, 0, width), ("C0", "C1S", "C1")):
        values = [next(r["violation_pct"] for r in population_rows if r["arm"] == arm and r["population"] == n)
                  for n in names]
        a.bar([i + offset for i in range(len(names))], values, width, label=t[arm], color=STYLE[arm]["color"],
              alpha=0.85, hatch={"C0": "", "C1S": "//", "C1": ""}[arm], edgecolor="white", linewidth=0.3)
        for i, value in enumerate(values):
            if value == 0:
                a.text(i + offset, 1.5, "0", ha="center", va="bottom", fontsize=6, color=STYLE[arm]["color"])
    a.set_xticks(range(len(names)))
    a.set_xticklabels([n.replace("-", "\n") for n in names], fontsize=6)
    a.set_ylabel(t["violation"])
    a.set_ylim(0, 105)
    a.set_title(t["fig3a"], loc="left")
    a.legend(frameon=False, fontsize=6, loc="upper right")
    # (b) 추출 누락
    xs = [100 * r["miss_rate"] for r in miss_rows]
    b.plot(xs, [r["violation_pct"] for r in miss_rows], **STYLE["C1"], linewidth=1.3, markersize=3.5, label=t["C1"])
    b.fill_between(xs, [r["low_pct"] for r in miss_rows], [r["high_pct"] for r in miss_rows],
                   color=STYLE["C1"]["color"], alpha=0.15, linewidth=0)
    b.axhline(miss_reference, color=STYLE["C0"]["color"], linestyle="--", linewidth=1, label=t["C0"])
    b.set_xlabel(t["miss"])
    b.set_ylabel(t["violation"])
    b.set_ylim(0, 105)
    b.set_title(t["fig3b"], loc="left")
    b.legend(frameon=False, fontsize=6, loc="upper left")
    # (c) 최대 일반화 단계: 운영 k_req에 따른 정보 유지율
    levels = list(dict.fromkeys(r["max_generalization"] for r in generalization_rows))
    shades = {None: STYLE["C1"], 0: STYLE["C1-g0"]}
    for number, g in enumerate(levels):
        rows = [r for r in generalization_rows if r["max_generalization"] == g]
        style = shades.get(g, {"color": STYLE["C1"]["color"], "linestyle": (0, (2, 1 + number)), "marker": "o"})
        label = t["unlimited"] if g is None else (t["suppress_only"] if g == 0 else f"≤ {g}")
        c.plot([r["k_req"] for r in rows], [r["retention_pct"] for r in rows], label=label, linewidth=1.2,
               markersize=3.5, alpha=1.0 if g in (None, 0) else 0.55, **style)
    c.set_xscale("log")
    c.set_xlabel(t["kop"])
    c.set_ylabel(t["retention"])
    c.set_ylim(0, 105)
    c.set_title(t["fig3c"], loc="left")
    c.legend(frameon=False, fontsize=6, loc="upper right", title=t["gen"], title_fontsize=6)
    fig.tight_layout(w_pad=1.2)
    return _save(fig, out, "fig3_sensitivity")
