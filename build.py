"""Build charts/*.png and README.md from data/. Usage: python3 build.py"""
import json
import random
import re
from math import comb
from pathlib import Path
from urllib.parse import urlparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker

ROOT = Path(__file__).parent
ARMS = ["brave", "linkup"]
LABEL = {"brave": "Claude + Brave", "linkup": "Claude + Linkup"}
SHORT = {"brave": "Brave", "linkup": "Linkup"}
COLOR = {"brave": "#eb6834", "linkup": "#1baf7a"}  # same orange / teal-green pair as the Linkup vs Claude repo
TIE = "#b9b7b0"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
TOPIC = {"law_tax": "Law, tax & regulation", "companies": "Companies & markets", "tech": "Tech & IT",
         "products": "Products & pricing", "local": "Local & everyday", "other": "Other"}
LANG = {"de": "German", "en": "English", "other": "Other languages"}
VERDICTS = ["correct", "partial", "incorrect", "not_found"]
VLABEL = {"correct": "Correct", "partial": "Partial", "incorrect": "Incorrect", "not_found": "Not found"}

# List prices used for every cost figure (USD).
PRICE = {
    "sonnet_input": 2.00, "sonnet_output": 10.00, "sonnet_cache_read": 0.20, "sonnet_cache_write": 2.50,  # per 1M tokens
    "brave_search": 5.00,  # Brave Search API (Search plan, extra snippets included), per 1,000 requests
    "linkup_search": 5.00,  # Linkup fast searchResults, per 1,000 calls
}
VOLS = [1_000_000, 5_000_000, 10_000_000]  # Langdock's expected monthly range


def rows(name):
    with open(ROOT / "data" / name) as f:
        return [json.loads(l) for l in f if l.strip()]


questions = {q["id"]: q for q in rows("questions.jsonl")}
ids = sorted(questions)
N = len(ids)
answers = {a: {r["id"]: r for r in rows(f"answers_{a}.jsonl")} for a in ARMS}
ab = {r["id"]: r for r in rows("grades_ab.jsonl")}
fc = {(g["id"], g["arm"]): g for g in rows("grades_factcheck.jsonl")}
random.seed(0)


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def boot_ci(xs, reps=4000):
    ms = sorted(mean(random.choices(xs, k=len(xs))) for _ in range(reps))
    return ms[int(0.025 * reps)], ms[int(0.975 * reps)]


def sign_p(a, b):
    n, k = a + b, max(a, b)
    return min(1.0, 2 * sum(comb(n, j) for j in range(k, n + 1)) / 2**n) if n else 1.0


def quantile(xs, p):
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))]


def token_cost(u):
    return (u["input_tokens"] * PRICE["sonnet_input"] + u["output_tokens"] * PRICE["sonnet_output"]
            + u["cache_read_tokens"] * PRICE["sonnet_cache_read"] + u["cache_write_tokens"] * PRICE["sonnet_cache_write"]) / 1e6


def domains(text):
    out = set()
    for u in re.findall(r"https?://[^\s)\]>\"'`]+", text):
        try:
            h = urlparse(u).hostname
        except ValueError:
            h = None
        if h:
            out.add(h.removeprefix("www.").lower())
    return out


# ---------- metrics ----------
wins = {"linkup": sum(ab[i]["winner"] == "linkup" for i in ids), "brave": sum(ab[i]["winner"] == "brave" for i in ids)}
ties = N - wins["linkup"] - wins["brave"]
AB = {"linkup": wins["linkup"], "brave": wins["brave"], "tie": ties, "p": sign_p(wins["linkup"], wins["brave"])}


def subset_ab(sel):
    s = [i for i in ids if sel(i)]
    return {"n": len(s), "linkup": sum(ab[i]["winner"] == "linkup" for i in s), "brave": sum(ab[i]["winner"] == "brave" for i in s),
            "tie": sum(ab[i]["winner"] == "tie" for i in s)}


M = {}
for a in ARMS:
    g = [fc[(i, a)] for i in ids]
    r = [answers[a][i] for i in ids]
    fees = [x["search_fee"] for x in r]
    toks = [token_cost(x["usage"]) for x in r]
    total = [f + t for f, t in zip(fees, toks)]
    scores = [x["total"] for x in g]
    claims = [c for x in g for c in x["claims"]]
    correct = sum(x["verdict"] == "correct" for x in g)
    M[a] = {
        **{v: sum(x["verdict"] == v for x in g) for v in VERDICTS},
        "score": mean(scores), "score_ci": boot_ci(scores),
        "parts": {k: mean([x[k] for x in g]) for k in ["answers_query_points", "accuracy_points", "freshness_points", "calibration_points"]},
        "claims": len(claims), "supported": sum(c["status"] == "supported" for c in claims),
        "contradicted": sum(c["status"] == "contradicted" for c in claims),
        "answers_with_contradiction": sum(any(c["status"] == "contradicted" for c in x["claims"]) for x in g),
        "searches": mean([x["searches"] for x in r]), "zero_search": sum(x["searches"] == 0 for x in r),
        "input_tokens": mean([x["usage"]["input_tokens"] + x["usage"]["cache_write_tokens"] + x["usage"]["cache_read_tokens"] for x in r]),
        "output_tokens": mean([x["usage"]["output_tokens"] for x in r]),
        "search_fees": mean(fees), "token_cost": mean(toks), "total_cost": mean(total),
        "cost_per_correct": sum(total) / correct if correct else float("nan"),
        "latency_median": quantile([x["latency_ms"] for x in r], 0.5) / 1000, "latency_p90": quantile([x["latency_ms"] for x in r], 0.9) / 1000,
        "domains_cited": mean([len(domains(x["answer"])) for x in r]),
        "by_topic": {t: mean([fc[(i, a)]["total"] for i in ids if questions[i]["topic"] == t]) for t in TOPIC},
        "by_lang": {l: mean([fc[(i, a)]["total"] for i in ids if questions[i]["language"] == l]) for l in LANG},
    }
B, L = M["brave"], M["linkup"]
diff = [fc[(i, "linkup")]["total"] - fc[(i, "brave")]["total"] for i in ids]
better, worse = sum(d >= 5 for d in diff), sum(d <= -5 for d in diff)
FC = {"diff_mean": mean(diff), "diff_ci": boot_ci(diff), "linkup_better_by_5": better, "linkup_worse_by_5": worse,
      "within_5": N - better - worse, "p": sign_p(better, worse)}
b_only = sum(fc[(i, "brave")]["verdict"] == "correct" and fc[(i, "linkup")]["verdict"] != "correct" for i in ids)
l_only = sum(fc[(i, "linkup")]["verdict"] == "correct" and fc[(i, "brave")]["verdict"] != "correct" for i in ids)
by_topic_ab = {t: subset_ab(lambda i, t=t: questions[i]["topic"] == t) for t in TOPIC}
by_lang_ab = {l: subset_ab(lambda i, l=l: questions[i]["language"] == l) for l in LANG}
lat = {a: sorted(answers[a][i]["latency_ms"] / 1000 for i in ids) for a in ARMS}
errors = {a: N - M[a]["correct"] for a in ARMS}


def change(new, old):
    """Relative change of Linkup vs Brave (negative = lower)."""
    return (new - old) / old if old else 0.0


# Lower is better for all of these; bars show Linkup's change vs Brave either way.
COMPARE = [
    ("Answers not fully correct (fact-check)", change(errors["linkup"], errors["brave"])),
    ("Answers with a contradicted claim", change(L["answers_with_contradiction"], B["answers_with_contradiction"])),
    ("Cost per query", change(L["total_cost"], B["total_cost"])),
    ("Cost per correct answer", change(L["cost_per_correct"], B["cost_per_correct"])),
    ("Searches per query", change(L["searches"], B["searches"])),
    ("Median latency", change(L["latency_median"], B["latency_median"])),
    ("p90 latency", change(L["latency_p90"], B["latency_p90"])),
]

# ---------- charts ----------
plt.rcParams.update({"font.family": "sans-serif", "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
                     "savefig.facecolor": SURFACE, "savefig.dpi": 200})
CHARTS = ROOT / "charts"
CHARTS.mkdir(exist_ok=True)
for old in CHARTS.glob("*.png"):
    old.unlink()


def style(ax, grid="x"):
    for s in ["top", "right"] + (["left"] if grid == "x" else []):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis=grid, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def title(ax, t):
    ax.set_title(t, loc="left", color=INK, fontsize=13, fontweight="bold", pad=12)


def ab_bars(ax, groups, names):
    """Stacked horizontal bars: Linkup wins | tie | Brave wins, as % of each group."""
    y = list(range(len(groups)))[::-1]
    for yy, g in zip(y, groups):
        left = 0
        for key, color in [("linkup", COLOR["linkup"]), ("tie", TIE), ("brave", COLOR["brave"])]:
            w = 100 * g[key] / g["n"]
            ax.barh(yy, w, left=left, color=color, height=0.6, edgecolor=SURFACE, linewidth=2)
            if w >= 7:
                ax.text(left + w / 2, yy, f"{g[key]}", ha="center", va="center", color=SURFACE if key != "tie" else INK,
                        fontsize=10, fontweight="bold")
            left += w
    ax.set_yticks(y, names)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    style(ax)


LEGEND_AB = [plt.Rectangle((0, 0), 1, 1, color=COLOR["linkup"]), plt.Rectangle((0, 0), 1, 1, color=TIE),
             plt.Rectangle((0, 0), 1, 1, color=COLOR["brave"])]

# 1. Linkup vs Brave on every headline metric (lower is better; teal = Linkup lower, orange = Linkup higher).
fig, ax = plt.subplots(figsize=(10, 5))
y = list(range(len(COMPARE)))[::-1]
lim = max(abs(v) for _, v in COMPARE) * 100 * 1.35 or 10
for yy, (name, v) in zip(y, COMPARE):
    ax.barh(yy, v * 100, color=COLOR["linkup" if v <= 0 else "brave"], height=0.6, edgecolor=SURFACE, linewidth=2)
    ax.text(v * 100 + (-1 if v <= 0 else 1) * lim * 0.02, yy, f"{v * 100:+.0f}%", va="center", ha="right" if v <= 0 else "left",
            color=INK, fontweight="bold")
ax.set_yticks(y, [c[0] for c in COMPARE])
ax.set_xlim(-lim, lim)
ax.axvline(0, color=INK2, linewidth=1)
ax.set_xlabel("Claude + Linkup vs Claude + Brave (%, lower is better)")
title(ax, f"Linkup vs Brave on {N} Langdock queries")
style(ax)
fig.savefig(CHARTS / "comparison.png", bbox_inches="tight")
plt.close(fig)

# 2. Blind A/B: overall, by language, by topic.
groups = [{"n": N, **{k: AB[k] for k in ["linkup", "brave", "tie"]}}] + [by_lang_ab[l] for l in LANG] + \
         [by_topic_ab[t] for t in TOPIC]
names = [f"All queries (n={N})"] + [f"{LANG[l]} (n={by_lang_ab[l]['n']})" for l in LANG] + \
        [f"{TOPIC[t]} (n={by_topic_ab[t]['n']})" for t in TOPIC]
fig, ax = plt.subplots(figsize=(10, 6))
ab_bars(ax, groups, names)
ax.axhline(len(groups) - 1.5, color=GRID, linewidth=1)
ax.axhline(len(groups) - 1 - len(LANG) - 0.5, color=GRID, linewidth=1)
ax.set_xlabel("Share of queries")
title(ax, "Blind A/B: which answer would the user rather get?")
ax.legend(LEGEND_AB, ["Linkup better", "Tie", "Brave better"], loc="lower center", bbox_to_anchor=(0.4, -0.2), ncol=3, frameon=False)
fig.savefig(CHARTS / "ab.png", bbox_inches="tight")
plt.close(fig)

# 3. Fact-check: verdicts per arm (stacked) and average score by topic.
fig, axes = plt.subplots(1, 2, figsize=(16, 4.6), gridspec_kw={"wspace": 0.85, "width_ratios": [1, 1.2]})
ax = axes[0]
VCOLOR = {"correct": "#1f7a5a", "partial": "#a7c4b5", "incorrect": "#c2442b", "not_found": TIE}
for yy, a in zip([1, 0], ARMS):
    left = 0
    for v in VERDICTS:
        w = M[a][v]
        ax.barh(yy, w, left=left, color=VCOLOR[v], height=0.55, edgecolor=SURFACE, linewidth=2)
        if w >= 4:
            ax.text(left + w / 2, yy, str(w), ha="center", va="center", color=SURFACE if v in ("correct", "incorrect") else INK,
                    fontsize=10, fontweight="bold")
        left += w
ax.set_yticks([1, 0], [LABEL[a] for a in ARMS])
ax.set_xlim(0, N)
ax.set_xlabel(f"Answers out of {N}")
title(ax, "Fact-check verdicts")
style(ax)
ax.legend([plt.Rectangle((0, 0), 1, 1, color=VCOLOR[v]) for v in VERDICTS], [VLABEL[v] for v in VERDICTS],
          loc="lower center", bbox_to_anchor=(0.5, -0.42), ncol=4, frameon=False)
ax = axes[1]
topics = list(TOPIC)
h = 0.36
for k, a in enumerate(ARMS):
    ys = [len(topics) - 1 - j + (0.5 - k) * h for j in range(len(topics))]
    vals = [M[a]["by_topic"][t] for t in topics]
    ax.barh(ys, vals, height=h, color=COLOR[a], label=LABEL[a], edgecolor=SURFACE, linewidth=2)
    for yy, v in zip(ys, vals):
        ax.text(v + 0.8, yy, f"{v:.0f}", va="center", fontsize=9, color=INK)
ax.set_yticks(range(len(topics))[::-1], [f"{TOPIC[t]} (n={by_topic_ab[t]['n']})" for t in topics])
ax.set_xlim(0, 108)
ax.set_xlabel("Fact-check score (0–100, average)")
title(ax, "Fact-check score by topic")
style(ax)
ax.legend(loc="lower center", bbox_to_anchor=(0.4, -0.42), ncol=2, frameon=False)
fig.savefig(CHARTS / "factcheck.png", bbox_inches="tight")
plt.close(fig)

# 4. Cost per query (search fees vs model tokens), and at Langdock's volumes.
fig, axes = plt.subplots(1, 2, figsize=(15, 3.6), gridspec_kw={"wspace": 0.3, "width_ratios": [1.3, 1]})
ax = axes[0]
for yy, a in zip([1, 0], ARMS):
    fee, tok = M[a]["search_fees"], M[a]["token_cost"]
    ax.barh(yy, fee, color=COLOR[a], height=0.55, edgecolor=SURFACE, linewidth=2)
    ax.barh(yy, tok, left=fee, color=COLOR[a], alpha=0.45, height=0.55, edgecolor=SURFACE, linewidth=2)
    ax.text(fee + tok, yy, f"  ${fee + tok:.4f}", va="center", color=INK, fontweight="bold")
ax.set_yticks([1, 0], [LABEL[a] for a in ARMS])
ax.set_xlim(0, max(B["total_cost"], L["total_cost"]) * 1.3)
ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"${x:.3f}"))
ax.set_xlabel("Per query, list prices (solid: search fees, light: model tokens)")
title(ax, "Cost per query")
style(ax)
ax = axes[1]
x = range(len(VOLS))
w = 0.38
for k, a in enumerate(ARMS):
    vals = [M[a]["total_cost"] * v / 1000 for v in VOLS]
    xs = [i + (k - 0.5) * w for i in x]
    ax.bar(xs, vals, width=w, color=COLOR[a], label=LABEL[a], edgecolor=SURFACE, linewidth=2)
    for xx, v in zip(xs, vals):
        ax.text(xx, v * 1.02, f"${v:,.0f}k", ha="center", va="bottom", fontsize=9, color=INK)
ax.set_xticks(list(x), [f"{v // 1_000_000}M" for v in VOLS])
ax.set_ylim(0, max(B["total_cost"], L["total_cost"]) * VOLS[-1] / 1000 * 1.18)
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"${y:,.0f}k"))
ax.set_xlabel("Queries per month")
title(ax, "Monthly cost at Langdock's volumes")
for s in ["top", "right"]:
    ax.spines[s].set_visible(False)
ax.grid(axis="y", color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
ax.legend(loc="upper left", frameon=False)
fig.savefig(CHARTS / "cost.png", bbox_inches="tight")
plt.close(fig)

# 5. Latency: share of queries answered within N seconds.
fig, ax = plt.subplots(figsize=(10, 4.8))
xmax = max(quantile(lat[a], 0.97) for a in ARMS) * 1.1
for a in ARMS:
    xs = lat[a]
    ax.plot([0] + xs, [0] + [100 * (k + 1) / len(xs) for k in range(len(xs))], color=COLOR[a], linewidth=2, label=LABEL[a], drawstyle="steps-post")
    med = M[a]["latency_median"]
    other = M["linkup" if a == "brave" else "brave"]["latency_median"]
    ax.plot([med], [50], "o", color=COLOR[a], markersize=8, markeredgecolor=SURFACE, markeredgewidth=2, zorder=3)
    right = med >= other
    ax.annotate(f"{SHORT[a]}: median {med:.1f}s", (med, 50), xytext=(10, -4) if right else (-10, -4),
                textcoords="offset points", color=INK, fontsize=10, ha="left" if right else "right")
ax.set_xlim(0, xmax)
ax.set_ylim(0, 102)
ax.set_xlabel("Seconds to answer (Claude's full search-and-answer loop)")
ax.set_ylabel("Queries answered (%)")
title(ax, "Latency: share of queries answered within N seconds")
ax.legend(loc="lower right", frameon=False)
style(ax, grid="y")
fig.savefig(CHARTS / "latency.png", bbox_inches="tight")
plt.close(fig)

# ---------- README ----------
pct = lambda x: f"{x * 100:.0f}%"
usd = lambda x, d=4: f"${x:,.{d}f}"
rel = lambda new, old: f"{abs(change(new, old)) * 100:.0f}% {'lower' if new <= old else 'higher'}"
pval = lambda p: "p < 0.001" if p < 0.001 else f"p = {p:.3f}" if p < 0.01 else f"p = {p:.2f}"


def table(head, body):
    return "\n".join([f"| {' | '.join(head)} |", f"|{'---|' * len(head)}"] + [f"| {' | '.join(r)} |" for r in body])


def lead(a, b):
    return "Linkup" if a > b else "Brave" if b > a else "Even"


AB_TABLE = table(["Queries", "n", "Linkup better", "Tie", "Brave better"],
                 [["All", str(N), f"**{AB['linkup']}**", str(AB['tie']), f"**{AB['brave']}**"]]
                 + [[LANG[l], str(g["n"]), str(g["linkup"]), str(g["tie"]), str(g["brave"])] for l, g in by_lang_ab.items() if g["n"]]
                 + [[TOPIC[t], str(g["n"]), str(g["linkup"]), str(g["tie"]), str(g["brave"])] for t, g in by_topic_ab.items() if g["n"]])
FC_TABLE = table(["Metric", "Brave", "Linkup", "Linkup vs Brave"], [
    ["Correct (fact-check verdict)", f"{B['correct']}", f"{L['correct']}", f"{L['correct'] - B['correct']:+d}"],
    ["Partial", f"{B['partial']}", f"{L['partial']}", f"{L['partial'] - B['partial']:+d}"],
    ["Incorrect", f"{B['incorrect']}", f"{L['incorrect']}", f"{L['incorrect'] - B['incorrect']:+d}"],
    ["Not found", f"{B['not_found']}", f"{L['not_found']}", f"{L['not_found'] - B['not_found']:+d}"],
    ["Score (0–100, average)", f"{B['score']:.1f}", f"{L['score']:.1f}", f"{FC['diff_mean']:+.1f} (95% CI {FC['diff_ci'][0]:+.1f} to {FC['diff_ci'][1]:+.1f})"],
    ["  Answers the query (of 30)", f"{B['parts']['answers_query_points']:.1f}", f"{L['parts']['answers_query_points']:.1f}", f"{L['parts']['answers_query_points'] - B['parts']['answers_query_points']:+.1f}"],
    ["  Accuracy (of 50)", f"{B['parts']['accuracy_points']:.1f}", f"{L['parts']['accuracy_points']:.1f}", f"{L['parts']['accuracy_points'] - B['parts']['accuracy_points']:+.1f}"],
    ["  Freshness (of 10)", f"{B['parts']['freshness_points']:.1f}", f"{L['parts']['freshness_points']:.1f}", f"{L['parts']['freshness_points'] - B['parts']['freshness_points']:+.1f}"],
    ["  Calibration (of 10)", f"{B['parts']['calibration_points']:.1f}", f"{L['parts']['calibration_points']:.1f}", f"{L['parts']['calibration_points'] - B['parts']['calibration_points']:+.1f}"],
    ["Claims checked", str(B["claims"]), str(L["claims"]), ""],
    ["Claims contradicted by the judge's sources", f"{B['contradicted']} ({B['contradicted'] / B['claims'] * 100:.1f}%)",
     f"{L['contradicted']} ({L['contradicted'] / L['claims'] * 100:.1f}%)", ""],
    ["Answers with at least one contradicted claim", str(B["answers_with_contradiction"]), str(L["answers_with_contradiction"]),
     f"{L['answers_with_contradiction'] - B['answers_with_contradiction']:+d}"],
    ["Queries only this arm got fully correct", str(b_only), str(l_only), f"sign test {pval(sign_p(b_only, l_only))}"],
    ["Queries where this arm scored 5+ points higher", str(FC["linkup_worse_by_5"]), str(FC["linkup_better_by_5"]), f"sign test {pval(FC['p'])}"],
])
COST = table(["Per query", "Brave", "Linkup", "Linkup vs Brave"], [
    ["Total cost", usd(B["total_cost"]), usd(L["total_cost"]), rel(L["total_cost"], B["total_cost"])],
    ["Cost per correct answer", usd(B["cost_per_correct"]), usd(L["cost_per_correct"]), rel(L["cost_per_correct"], B["cost_per_correct"])],
    ["Search fees", usd(B["search_fees"]), usd(L["search_fees"]), rel(L["search_fees"], B["search_fees"])],
    ["Model tokens", usd(B["token_cost"]), usd(L["token_cost"]), rel(L["token_cost"], B["token_cost"])],
    ["Searches", f"{B['searches']:.2f}", f"{L['searches']:.2f}", rel(L["searches"], B["searches"])],
    ["Input tokens (incl. cache)", f"{B['input_tokens']:,.0f}", f"{L['input_tokens']:,.0f}", rel(L["input_tokens"], B["input_tokens"])],
    ["Output tokens", f"{B['output_tokens']:,.0f}", f"{L['output_tokens']:,.0f}", rel(L["output_tokens"], B["output_tokens"])],
])
SCALE = table(["Queries per month", "Brave", "Linkup", "Difference"],
              [[f"{v:,}", usd(B["total_cost"] * v, 0), usd(L["total_cost"] * v, 0),
                f"{'Linkup' if L['total_cost'] < B['total_cost'] else 'Brave'} {usd(abs(B['total_cost'] - L['total_cost']) * v, 0)} cheaper"] for v in VOLS])
LAT = table(["Metric", "Brave", "Linkup", "Linkup vs Brave"], [
    ["Median latency", f"{B['latency_median']:.1f}s", f"{L['latency_median']:.1f}s", rel(L["latency_median"], B["latency_median"])],
    ["p90 latency", f"{B['latency_p90']:.1f}s", f"{L['latency_p90']:.1f}s", rel(L["latency_p90"], B["latency_p90"])],
])
TOPICS = table(["Topic", "Queries", "A/B: Linkup / tie / Brave", "Brave fact-check score", "Linkup fact-check score"],
               [[TOPIC[t], str(by_topic_ab[t]["n"]), f"{by_topic_ab[t]['linkup']} / {by_topic_ab[t]['tie']} / {by_topic_ab[t]['brave']}",
                 f"{B['by_topic'][t]:.1f}", f"{L['by_topic'][t]:.1f}"] for t in TOPIC if by_topic_ab[t]["n"]]
               + [[LANG[l], str(by_lang_ab[l]["n"]), f"{by_lang_ab[l]['linkup']} / {by_lang_ab[l]['tie']} / {by_lang_ab[l]['brave']}",
                   f"{B['by_lang'][l]:.1f}", f"{L['by_lang'][l]:.1f}"] for l in LANG if by_lang_ab[l]["n"]])

ab_lead = lead(AB["linkup"], AB["brave"])
readme = f"""# Linkup vs Brave on Langdock's search queries

Claude Sonnet 5.5 answered {N} of Langdock's search queries twice: once with the Brave Web Search API as its search tool (**Brave**) and once with Linkup (**Linkup**). Same model, same prompt, same 10-search cap. Two separate graders scored the answers: a blind A/B comparison, and a fact-check in which a judge verifies each answer's claims with its own web search.

- **Blind A/B:** Linkup's answer was better on {AB['linkup']} queries and Brave's on {AB['brave']}, with {AB['tie']} ties (sign test {pval(AB['p'])}).
- **Fact-check:** {L['correct']} of Linkup's answers were fully correct vs {B['correct']} of Brave's; average score {L['score']:.1f} vs {B['score']:.1f} out of 100.
- **Cost per query:** Linkup {usd(L['total_cost'])}, Brave {usd(B['total_cost'])} ({rel(L['total_cost'], B['total_cost'])}).
- **Median latency:** Linkup {L['latency_median']:.1f}s, Brave {B['latency_median']:.1f}s ({rel(L['latency_median'], B['latency_median'])}).

![Linkup vs Brave on every headline metric](charts/comparison.png)

## Setup

| | Brave | Linkup |
|---|---|---|
| Model | `claude-sonnet-5-5` | `claude-sonnet-5-5` |
| Search | Brave Web Search API `/res/v1/web/search`: 10 results, `extra_snippets=true` (title, URL, date, description and up to 5 extra excerpts per result) | Linkup `/v1/search`: `fast` depth, `searchResults`, 10 results |
| Search cap | 10 per query | 10 per query |
| Search price | ${PRICE['brave_search']:.2f} per 1,000 requests | ${PRICE['linkup_search']:.2f} per 1,000 calls |

Claude decides what to search for and how often. Each tool description asks for the query style its provider is built for: keyword queries for Brave, natural-language retrieval instructions for Linkup. Brave runs with its default settings (no `country` or `search_lang`), and Linkup has no location setting, so neither arm gets a location hint.

**Queries:** a random sample (fixed seed) of {N} of the 1,000 synthetic search queries Langdock shared on October 16, 2026 as typical of what its product sends to a search API. Each query is sent to Claude as the user's message, with a system prompt for an enterprise assistant used by companies in Germany and across Europe. {by_lang_ab['de']['n']} are in German, {by_lang_ab['en']['n']} in English and {by_lang_ab['other']['n']} in other languages. `gpt-6-luna` tagged each query with a topic.

**Grading:** the queries have no answer key, so two `gpt-6-luna` graders score the answers. Their results are reported separately.
- **Blind A/B:** the judge sees the query and both answers in random order, with no labels and no web access, and picks the one the user would rather get, or a tie. It weighs whether the answer gives what the query is looking for, then correctness as far as it can tell, then honesty about gaps. Citations, length and style don't count.
- **Fact-check:** the judge sees one answer at a time and checks up to 5 of its most important claims with its own web search (OpenAI's, independent of both arms), marking each supported, contradicted or unverifiable. It gives a verdict (correct / partial / incorrect / not found) and a score out of 100: answers the query 30, accuracy 50 (minus 25 for each contradicted central claim and 10 for each other contradicted claim), freshness 10, calibration 10.

## Blind A/B

![Blind A/B by language and topic](charts/ab.png)

{AB_TABLE}

## Fact-check

![Fact-check verdicts and score by topic](charts/factcheck.png)

{FC_TABLE}

## Cost

![Cost per query and at Langdock's volumes](charts/cost.png)

{COST}

{SCALE}

Both search APIs cost $5 per 1,000 calls at list price, so the cost gap comes from how many searches Claude makes and how much text it reads and writes. List prices: Sonnet 5.5 ${PRICE['sonnet_input']:.2f} / ${PRICE['sonnet_output']:.2f} per million input / output tokens (cache reads ${PRICE['sonnet_cache_read']:.2f}, cache writes ${PRICE['sonnet_cache_write']:.2f}); Brave Search plan ${PRICE['brave_search']:.2f} per 1,000 requests (extra snippets included); Linkup `fast` ${PRICE['linkup_search']:.2f} per 1,000 calls. Volume discounts on either side are not included.

## Latency

![Latency: share of queries answered within N seconds](charts/latency.png)

{LAT}

Latency is the whole loop: Claude's turns plus every search call, from the query to the final answer.

## Topics and languages

{TOPICS}

## Caveats

- {N} queries: differences of a few queries either way are within noise; the sign tests above say how likely each split is by chance.
- The queries are synthetic examples from Langdock, not production traffic.
- Both graders are a single LLM (`gpt-6-luna`). The fact-checker can only mark a claim contradicted when its own search finds a better source, so it under-counts errors on niche topics.
- Brave and Linkup were each run with one configuration. Brave with a `country=DE` setting, or Linkup at `standard` depth, may score differently.

## Files

- `data/`: the {N} queries with topic and language, both arms' answers (with the searches Claude ran, tokens, latency and retrieved URLs), and every grade with the judge's reasoning
- `charts/`: the charts above
- `build.py`: rebuilds `charts/` and this README from `data/` (`python3 build.py`)
"""
(ROOT / "README.md").write_text(readme)
print(json.dumps({"n": N, "ab": AB, "fc_correct": {a: M[a]["correct"] for a in ARMS}, "fc_score": {a: round(M[a]["score"], 1) for a in ARMS},
                  "fc_diff_ci": FC["diff_ci"], "contradicted": {a: M[a]["contradicted"] for a in ARMS},
                  "cost": {a: round(M[a]["total_cost"], 4) for a in ARMS}, "searches": {a: round(M[a]["searches"], 2) for a in ARMS},
                  "latency_median": {a: M[a]["latency_median"] for a in ARMS}}, indent=1))
