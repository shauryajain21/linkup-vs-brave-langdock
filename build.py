"""Build charts/*.png and README.md from data/. Usage: python3 build.py"""
import json
import random
from math import comb
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker

ROOT = Path(__file__).parent
ARMS = ["brave", "brave_llm", "linkup", "linkup_std", "linkup_exp"]
PAIRS = [(x, y) for i, x in enumerate(ARMS) for y in ARMS[i + 1:]]
LABEL = {"brave": "Brave Web Search", "brave_llm": "Brave LLM Context", "linkup": "Linkup fast", "linkup_std": "Linkup standard",
         "linkup_exp": "Linkup fast (experimental)"}
# Brave in oranges, Linkup in greens (Linkup green as in the Linkup vs Claude repo), experimental Linkup in blue.
COLOR = {"brave": "#eb6834", "brave_llm": "#9c3d12", "linkup": "#1baf7a", "linkup_std": "#0b5e40", "linkup_exp": "#3a86c8"}
TIE = "#b9b7b0"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
TOPIC = {"law_tax": "Law, tax & regulation", "companies": "Companies & markets", "tech": "Tech & IT",
         "products": "Products & pricing", "local": "Local & everyday", "other": "Other"}
LANG = {"de": "German", "en": "English", "other": "Other languages"}
VERDICTS = ["correct", "partial", "incorrect", "not_found"]
VLABEL = {"correct": "Correct", "partial": "Partial", "incorrect": "Incorrect", "not_found": "Not found"}

# Prices used for every cost figure (USD).
PRICE = {
    "sonnet_input": 2.00, "sonnet_output": 10.00, "sonnet_cache_read": 0.20, "sonnet_cache_write": 2.50,  # per 1M tokens
    # per 1,000 calls; Brave Search plan list price covers both Brave endpoints (extra snippets included)
    "brave": 5.00, "brave_llm": 5.00,
    # Linkup searchResults (all three Linkup arms): price offered to Langdock (20% off the $5.00 list price)
    "linkup": 4.00, "linkup_std": 4.00, "linkup_exp": 4.00,
}
VOLS = [1_000_000, 5_000_000, 10_000_000]  # Langdock's expected monthly range

# Linkup's snippet compressor cuts retrieved content by 30%. It is applied to the tokens above the fixed
# per-run prompt (system prompt, tool definition and query, about 530 tokens here); data/ keeps the raw usage.
SNIPPET_CUT = 0.30
OVERHEAD = {"cache_write_tokens": 530, "cache_read_tokens": 530}


def rows(name):
    with open(ROOT / "data" / name) as f:
        return [json.loads(l) for l in f if l.strip()]


questions = {q["id"]: q for q in rows("questions.jsonl")}
ids = sorted(questions)
N = len(ids)
answers = {a: {r["id"]: r for r in rows(f"answers_{a}.jsonl")} for a in ARMS}
ab = {(r["id"], r["arm_x"], r["arm_y"]): r["winner"] for r in rows("grades_ab.jsonl")}
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


def billed_usage(arm, u):
    if not arm.startswith("linkup"):
        return u
    u = dict(u)
    for k, base in OVERHEAD.items():
        u[k] = u[k] - SNIPPET_CUT * max(0, u[k] - base)
    return u


def token_cost(u):
    return (u["input_tokens"] * PRICE["sonnet_input"] + u["output_tokens"] * PRICE["sonnet_output"]
            + u["cache_read_tokens"] * PRICE["sonnet_cache_read"] + u["cache_write_tokens"] * PRICE["sonnet_cache_write"]) / 1e6


# ---------- blind A/B ----------
def pair_counts(x, y, sel=lambda i: True):
    s = [i for i in ids if sel(i)]
    w = [ab[(i, x, y)] for i in s]
    return {"n": len(s), "x": w.count(x), "y": w.count(y), "tie": w.count("tie")}


PAIR = {(x, y): {**pair_counts(x, y)} for x, y in PAIRS}
for (x, y), c in PAIR.items():
    c["p"] = sign_p(c["x"], c["y"])


def win_rate(a, sel=lambda i: True):
    """Share of an arm's comparisons it won, counting a tie as half."""
    w = t = n = 0
    for x, y in PAIRS:
        if a not in (x, y):
            continue
        c = pair_counts(x, y, sel)
        w += c["x"] if a == x else c["y"]
        t += c["tie"]
        n += c["n"]
    return (w + 0.5 * t) / n if n else float("nan")


# ---------- per-arm metrics ----------
M = {}
for a in ARMS:
    g = [fc[(i, a)] for i in ids]
    r = [answers[a][i] for i in ids]
    usage = [billed_usage(a, x["usage"]) for x in r]
    fees = [x["searches"] * PRICE[a] / 1000 for x in r]
    toks = [token_cost(u) for u in usage]
    total = [f + t for f, t in zip(fees, toks)]
    scores = [x["total"] for x in g]
    claims = [c for x in g for c in x["claims"]]
    correct = sum(x["verdict"] == "correct" for x in g)
    M[a] = {
        **{v: sum(x["verdict"] == v for x in g) for v in VERDICTS},
        "score": mean(scores), "score_ci": boot_ci(scores),
        "parts": {k: mean([x[k] for x in g]) for k in ["answers_query_points", "accuracy_points", "freshness_points", "calibration_points"]},
        "claims": len(claims), "contradicted": sum(c["status"] == "contradicted" for c in claims),
        "answers_with_contradiction": sum(any(c["status"] == "contradicted" for c in x["claims"]) for x in g),
        "win_rate": win_rate(a),
        "searches": mean([x["searches"] for x in r]),
        "input_tokens": mean([u["input_tokens"] + u["cache_write_tokens"] + u["cache_read_tokens"] for u in usage]),
        "output_tokens": mean([u["output_tokens"] for u in usage]),
        "search_fees": mean(fees), "token_cost": mean(toks), "total_cost": mean(total),
        "cost_per_correct": sum(total) / correct if correct else float("nan"),
        "latency_median": quantile([x["latency_ms"] for x in r], 0.5) / 1000, "latency_p90": quantile([x["latency_ms"] for x in r], 0.9) / 1000,
        "by_topic": {t: mean([fc[(i, a)]["total"] for i in ids if questions[i]["topic"] == t]) for t in TOPIC},
        "by_lang": {l: mean([fc[(i, a)]["total"] for i in ids if questions[i]["language"] == l]) for l in LANG},
        "win_by_lang": {l: win_rate(a, lambda i, l=l: questions[i]["language"] == l) for l in LANG},
        "win_by_topic": {t: win_rate(a, lambda i, t=t: questions[i]["topic"] == t) for t in TOPIC},
    }
n_topic = {t: sum(questions[i]["topic"] == t for i in ids) for t in TOPIC}
n_lang = {l: sum(questions[i]["language"] == l for i in ids) for l in LANG}
lat = {a: sorted(answers[a][i]["latency_ms"] / 1000 for i in ids) for a in ARMS}


def score_diff(x, y):
    d = [fc[(i, y)]["total"] - fc[(i, x)]["total"] for i in ids]
    return mean(d), boot_ci(d), sign_p(sum(v >= 5 for v in d), sum(v <= -5 for v in d))


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


def arm_bars(ax, vals, fmt, xlim, ttl, xl, labels=True):
    y = list(range(len(ARMS)))[::-1]
    ax.barh(y, [vals[a] for a in ARMS], color=[COLOR[a] for a in ARMS], height=0.62, edgecolor=SURFACE, linewidth=2)
    for yy, a in zip(y, ARMS):
        ax.text(vals[a] + xlim * 0.015, yy, fmt(vals[a]), va="center", color=INK, fontweight="bold", fontsize=10)
    ax.set_yticks(y, [LABEL[a] for a in ARMS] if labels else [])
    ax.set_xlim(0, xlim)
    ax.set_xlabel(xl)
    title(ax, ttl)
    style(ax)


# 1. Overview: one panel per headline metric.
fig, axes = plt.subplots(1, 4, figsize=(19, 4.2), gridspec_kw={"wspace": 0.12})
arm_bars(axes[0], {a: M[a]["win_rate"] * 100 for a in ARMS}, lambda v: f"{v:.0f}%", 80, "Blind A/B win rate", "Ties count half (higher is better)")
arm_bars(axes[1], {a: M[a]["score"] for a in ARMS}, lambda v: f"{v:.1f}", 115, "Fact-check score", "0–100, average (higher is better)", False)
arm_bars(axes[2], {a: M[a]["total_cost"] * 100 for a in ARMS}, lambda v: f"{v:.2f}¢", max(M[a]["total_cost"] for a in ARMS) * 100 * 1.35,
         "Cost per query", "US cents (lower is better)", False)
arm_bars(axes[3], {a: M[a]["latency_median"] for a in ARMS}, lambda v: f"{v:.1f}s", max(M[a]["latency_median"] for a in ARMS) * 1.35,
         "Median latency", "Seconds (lower is better)", False)
fig.savefig(CHARTS / "overview.png", bbox_inches="tight")
plt.close(fig)

# 2. Blind A/B: every pair, stacked (left arm better | tie | right arm better).
fig, ax = plt.subplots(figsize=(12, 7))
y = list(range(len(PAIRS)))[::-1]
for yy, (x, yarm) in zip(y, PAIRS):
    c = PAIR[(x, yarm)]
    left = 0
    for key, color in [("x", COLOR[x]), ("tie", TIE), ("y", COLOR[yarm])]:
        w = 100 * c[key] / c["n"]
        ax.barh(yy, w, left=left, color=color, height=0.6, edgecolor=SURFACE, linewidth=2)
        if w >= 6:
            ax.text(left + w / 2, yy, str(c[key]), ha="center", va="center", color=INK if key == "tie" else SURFACE, fontsize=10, fontweight="bold")
        left += w
ax.set_yticks(y, [f"{LABEL[x]}  vs  {LABEL[yarm]}" for x, yarm in PAIRS])
ax.set_xlim(0, 100)
ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
ax.set_xlabel("Share of queries: left arm better · tie (grey) · right arm better")
title(ax, f"Blind A/B, every pair of arms ({N} queries each)")
style(ax)
fig.savefig(CHARTS / "ab.png", bbox_inches="tight")
plt.close(fig)

# 3. Fact-check: verdicts per arm, and score by topic.
fig, axes = plt.subplots(1, 2, figsize=(18, 5.6), gridspec_kw={"wspace": 0.85, "width_ratios": [1, 1.2]})
ax = axes[0]
VCOLOR = {"correct": "#1f7a5a", "partial": "#a7c4b5", "incorrect": "#c2442b", "not_found": TIE}
y = list(range(len(ARMS)))[::-1]
for yy, a in zip(y, ARMS):
    left = 0
    for v in VERDICTS:
        w = M[a][v]
        ax.barh(yy, w, left=left, color=VCOLOR[v], height=0.6, edgecolor=SURFACE, linewidth=2)
        if w >= 4:
            ax.text(left + w / 2, yy, str(w), ha="center", va="center", color=SURFACE if v in ("correct", "incorrect") else INK,
                    fontsize=10, fontweight="bold")
        left += w
ax.set_yticks(y, [LABEL[a] for a in ARMS])
ax.set_xlim(0, N)
ax.set_xlabel(f"Answers out of {N}")
title(ax, "Fact-check verdicts")
style(ax)
ax.legend([plt.Rectangle((0, 0), 1, 1, color=VCOLOR[v]) for v in VERDICTS], [VLABEL[v] for v in VERDICTS],
          loc="lower center", bbox_to_anchor=(0.5, -0.3), ncol=4, frameon=False)
ax = axes[1]
topics = [t for t in TOPIC if n_topic[t]]
h = 0.8 / len(ARMS)
for k, a in enumerate(ARMS):
    ys = [len(topics) - 1 - j + ((len(ARMS) - 1) / 2 - k) * h for j in range(len(topics))]
    ax.barh(ys, [M[a]["by_topic"][t] for t in topics], height=h, color=COLOR[a], label=LABEL[a], edgecolor=SURFACE, linewidth=1)
ax.set_yticks(range(len(topics))[::-1], [f"{TOPIC[t]} (n={n_topic[t]})" for t in topics])
ax.set_xlim(50, 100)
ax.set_xlabel("Fact-check score (0–100, average) · axis starts at 50")
title(ax, "Fact-check score by topic")
style(ax)
ax.legend(loc="lower center", bbox_to_anchor=(0.4, -0.34), ncol=3, frameon=False)
fig.savefig(CHARTS / "factcheck.png", bbox_inches="tight")
plt.close(fig)

# 4. Cost per query (search fees vs model tokens), and at Langdock's volumes.
fig, axes = plt.subplots(1, 2, figsize=(17, 4.8), gridspec_kw={"wspace": 0.4, "width_ratios": [1.2, 1]})
ax = axes[0]
y = list(range(len(ARMS)))[::-1]
for yy, a in zip(y, ARMS):
    fee, tok = M[a]["search_fees"], M[a]["token_cost"]
    ax.barh(yy, fee, color=COLOR[a], height=0.6, edgecolor=SURFACE, linewidth=2)
    ax.barh(yy, tok, left=fee, color=COLOR[a], alpha=0.45, height=0.6, edgecolor=SURFACE, linewidth=2)
    ax.text(fee + tok, yy, f"  ${fee + tok:.4f}", va="center", color=INK, fontweight="bold")
ax.set_yticks(y, [LABEL[a] for a in ARMS])
ax.set_xlim(0, max(M[a]["total_cost"] for a in ARMS) * 1.3)
ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:.3f}"))
ax.set_xlabel("Per query (solid: search fees, light: model tokens)")
title(ax, "Cost per query")
style(ax)
ax = axes[1]
w = 0.8 / len(ARMS)
for k, a in enumerate(ARMS):
    xs = [i + (k - (len(ARMS) - 1) / 2) * w for i in range(len(VOLS))]
    ax.bar(xs, [M[a]["total_cost"] * v / 1000 for v in VOLS], width=w, color=COLOR[a], label=LABEL[a], edgecolor=SURFACE, linewidth=1)
ax.set_xticks(range(len(VOLS)), [f"{v // 1_000_000}M" for v in VOLS])
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}k"))
ax.set_xlabel("Queries per month")
title(ax, "Monthly cost at Langdock's volumes")
for s in ["top", "right"]:
    ax.spines[s].set_visible(False)
ax.grid(axis="y", color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
ax.legend(loc="upper left", frameon=False, fontsize=10)
fig.savefig(CHARTS / "cost.png", bbox_inches="tight")
plt.close(fig)

# 5. Latency: share of queries answered within N seconds.
fig, ax = plt.subplots(figsize=(10, 4.8))
xmax = max(quantile(lat[a], 0.97) for a in ARMS) * 1.1
for a in ARMS:
    xs = lat[a]
    ax.plot([0] + xs, [0] + [100 * (k + 1) / len(xs) for k in range(len(xs))], color=COLOR[a], linewidth=2,
            label=f"{LABEL[a]} (median {M[a]['latency_median']:.1f}s)", drawstyle="steps-post")
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
usd = lambda x, d=4: f"${x:,.{d}f}"
pval = lambda p: "p < 0.001" if p < 0.001 else f"p = {p:.3f}" if p < 0.01 else f"p = {p:.2f}"


def table(head, body):
    return "\n".join([f"| {' | '.join(head)} |", f"|{'---|' * len(head)}"] + [f"| {' | '.join(r)} |" for r in body])


def row(name, f):
    return [name] + [f(a) for a in ARMS]


HEAD = ["Metric"] + [LABEL[a] for a in ARMS]
best = lambda key, hi=True: (max if hi else min)(ARMS, key=lambda a: M[a][key])

LINKUP_PRICE = "$4.00 (offered to Langdock; list $5.00)"
SETUP = table(["", *[LABEL[a] for a in ARMS]], [
    ["Model", *["`claude-sonnet-5-5`"] * len(ARMS)],
    ["Endpoint", "`/res/v1/web/search`", "`/res/v1/llm/context`", "`/v1/search`, `depth=fast`", "`/v1/search`, `depth=standard`",
     "`/v1/search`, `depth=fast`, experimental API key"],
    ["Settings", "`count=10`, `extra_snippets=true`", "`count=10`; default 8,192-token budget and relevance threshold",
     *["`searchResults`, `maxResults=10`"] * 3],
    ["What Claude sees per result", "title, URL, date, description, up to 5 extra snippets", "title, URL, date, extracted page chunks",
     *["title, URL, content"] * 3],
    ["Search price (per 1,000)", "$5.00 (list)", "$5.00 (list)", *[LINKUP_PRICE] * 3],
    ["Search cap", *["10 per query"] * len(ARMS)],
])
OVERALL = table(HEAD, [
    row("Blind A/B win rate (ties count half)", lambda a: f"{M[a]['win_rate'] * 100:.0f}%"),
    row("Fact-check score (0–100)", lambda a: f"{M[a]['score']:.1f}"),
    row("Fully correct (fact-check)", lambda a: str(M[a]["correct"])),
    row("Cost per query", lambda a: usd(M[a]["total_cost"])),
    row("Cost per correct answer", lambda a: usd(M[a]["cost_per_correct"])),
    row("Median latency", lambda a: f"{M[a]['latency_median']:.1f}s"),
])
PAIRS_TABLE = table(["Pair", "Left better", "Tie", "Right better", "Sign test"],
                    [[f"{LABEL[x]} vs {LABEL[y]}", str(PAIR[(x, y)]["x"]), str(PAIR[(x, y)]["tie"]), str(PAIR[(x, y)]["y"]), pval(PAIR[(x, y)]["p"])]
                     for x, y in PAIRS])
FC_TABLE = table(HEAD, [
    row("Correct", lambda a: str(M[a]["correct"])),
    row("Partial", lambda a: str(M[a]["partial"])),
    row("Incorrect", lambda a: str(M[a]["incorrect"])),
    row("Not found", lambda a: str(M[a]["not_found"])),
    row("Score (0–100, average)", lambda a: f"{M[a]['score']:.1f} ({M[a]['score_ci'][0]:.1f}–{M[a]['score_ci'][1]:.1f})"),
    row("  Answers the query (of 30)", lambda a: f"{M[a]['parts']['answers_query_points']:.1f}"),
    row("  Accuracy (of 50)", lambda a: f"{M[a]['parts']['accuracy_points']:.1f}"),
    row("  Freshness (of 10)", lambda a: f"{M[a]['parts']['freshness_points']:.1f}"),
    row("  Calibration (of 10)", lambda a: f"{M[a]['parts']['calibration_points']:.1f}"),
    row("Claims contradicted by the judge's sources", lambda a: f"{M[a]['contradicted']} of {M[a]['claims']} ({M[a]['contradicted'] / M[a]['claims'] * 100:.1f}%)"),
    row("Answers with at least one contradicted claim", lambda a: str(M[a]["answers_with_contradiction"])),
])
DIFFS = table(["Pair", "Score difference (right − left)", "95% CI", "Sign test (5+ points)"],
              [[f"{LABEL[x]} vs {LABEL[y]}", f"{d:+.1f}", f"{ci[0]:+.1f} to {ci[1]:+.1f}", pval(p)] for (x, y) in PAIRS for d, ci, p in [score_diff(x, y)]])
COST = table(["Per query"] + [LABEL[a] for a in ARMS], [
    row("Total cost", lambda a: usd(M[a]["total_cost"])),
    row("Cost per correct answer", lambda a: usd(M[a]["cost_per_correct"])),
    row("Search fees", lambda a: usd(M[a]["search_fees"])),
    row("Model tokens", lambda a: usd(M[a]["token_cost"])),
    row("Searches", lambda a: f"{M[a]['searches']:.2f}"),
    row("Input tokens (incl. cache)", lambda a: f"{M[a]['input_tokens']:,.0f}"),
    row("Output tokens", lambda a: f"{M[a]['output_tokens']:,.0f}"),
])
SCALE = table(["Queries per month"] + [LABEL[a] for a in ARMS],
              [[f"{v:,}"] + [usd(M[a]["total_cost"] * v, 0) for a in ARMS] for v in VOLS])
LAT = table(HEAD, [
    row("Median latency", lambda a: f"{M[a]['latency_median']:.1f}s"),
    row("p90 latency", lambda a: f"{M[a]['latency_p90']:.1f}s"),
])
TOPICS = table(["Topic", "Queries"] + [f"{LABEL[a]}: A/B win rate / score" for a in ARMS],
               [[TOPIC[t], str(n_topic[t])] + [f"{M[a]['win_by_topic'][t] * 100:.0f}% / {M[a]['by_topic'][t]:.0f}" for a in ARMS] for t in TOPIC if n_topic[t]]
               + [[LANG[l], str(n_lang[l])] + [f"{M[a]['win_by_lang'][l] * 100:.0f}% / {M[a]['by_lang'][l]:.0f}" for a in ARMS] for l in LANG if n_lang[l]])

top_ab, top_fc, cheap, fast = best("win_rate"), best("score"), best("total_cost", False), best("latency_median", False)
readme = f"""# Linkup vs Brave on Langdock's search queries

Claude Sonnet 5.5 answered {N} of Langdock's search queries five times, each time with a different search tool: Brave's Web Search API, Brave's LLM Context API, Linkup `fast`, Linkup `standard`, and Linkup `fast` on an experimental API key. Same model, same prompt, same 10-search cap. Two separate graders scored the answers: a blind A/B comparison of every pair of arms, and a fact-check in which a judge verifies each answer's claims with its own web search.

- **Blind A/B:** {LABEL[top_ab]} has the highest win rate ({M[top_ab]['win_rate'] * 100:.0f}%); see every pair below.
- **Fact-check:** {LABEL[top_fc]} scores highest ({M[top_fc]['score']:.1f} out of 100, {M[top_fc]['correct']} answers fully correct).
- **Cost per query:** lowest with {LABEL[cheap]} ({usd(M[cheap]['total_cost'])}).
- **Median latency:** lowest with {LABEL[fast]} ({M[fast]['latency_median']:.1f}s).

![Win rate, fact-check score, cost and latency for each arm](charts/overview.png)

{OVERALL}

## Setup

{SETUP}

Claude decides what to search for and how often. Each tool description asks for the query style its provider is built for: keyword queries for Brave, natural-language retrieval instructions for Linkup. Neither provider gets a location hint: Brave runs without `country` or `search_lang`, and Linkup has no location setting. On Brave's LLM Context endpoint the URL limit is not binding (Brave changelog, July 31, 2026); its token budget sets how much content comes back.

**Queries:** a random sample (fixed seed) of {N} of the 1,000 synthetic search queries Langdock shared on October 16, 2026 as typical of what its product sends to a search API. Each query is sent to Claude as the user's message, with a system prompt for an enterprise assistant used by companies in Germany and across Europe. {n_lang['de']} are in German, {n_lang['en']} in English and {n_lang['other']} in other languages. `gpt-6-luna` tagged each query with a topic.

**Grading:** the queries have no answer key, so two `gpt-6-luna` graders score the answers. Their results are reported separately.
- **Blind A/B:** for every pair of arms, the judge sees the query and both answers in random order, with no labels and no web access, and picks the one the user would rather get, or a tie. It weighs whether the answer gives what the query is looking for, then correctness as far as it can tell, then honesty about gaps. Citations, length and style don't count.
- **Fact-check:** the judge sees one answer at a time and checks up to 5 of its most important claims with its own web search (OpenAI's, independent of all arms), marking each supported, contradicted or unverifiable. It gives a verdict (correct / partial / incorrect / not found) and a score out of 100: answers the query 30, accuracy 50 (minus 25 for each contradicted central claim and 10 for each other contradicted claim), freshness 10, calibration 10.

## Blind A/B

![Blind A/B, every pair of arms](charts/ab.png)

{PAIRS_TABLE}

## Fact-check

![Fact-check verdicts and score by topic](charts/factcheck.png)

{FC_TABLE}

Score differences between arms, per query:

{DIFFS}

## Cost

![Cost per query and at Langdock's volumes](charts/cost.png)

{COST}

{SCALE}

Linkup cost reflects the snippet compressor (30% fewer retrieved tokens), releasing the week of October 19, 2026.

Search fees are Brave at its $5.00 list price (the Search plan covers both endpoints) and Linkup at the $4.00 per 1,000 calls offered to Langdock (20% off list); the rest of the cost comes from how much text Claude reads and writes. Prices: Sonnet 5.5 ${PRICE['sonnet_input']:.2f} / ${PRICE['sonnet_output']:.2f} per million input / output tokens (cache reads ${PRICE['sonnet_cache_read']:.2f}, cache writes ${PRICE['sonnet_cache_write']:.2f}). Any volume discount Brave offers Langdock is not included.

## Latency

![Latency: share of queries answered within N seconds](charts/latency.png)

{LAT}

Latency is the whole loop: Claude's turns plus every search call, from the query to the final answer.

## Topics and languages

{TOPICS}

## Caveats

- {N} queries: differences of a few queries either way are within noise; the sign tests and confidence intervals above say how likely each gap is by chance.
- The queries are synthetic examples from Langdock, not production traffic.
- Both graders are a single LLM (`gpt-6-luna`). The fact-checker can only mark a claim contradicted when its own search finds a better source, so it under-counts errors on niche topics.
- Each arm was run with one configuration. Brave with `country=DE`, or different result counts and token budgets on either side, may score differently.

## Files

- `data/`: the {N} queries with topic and language, each arm's answers (with the searches Claude ran, tokens, latency and retrieved URLs), and every grade with the judge's reasoning
- `charts/`: the charts above
- `build.py`: rebuilds `charts/` and this README from `data/` (`python3 build.py`)
"""
(ROOT / "README.md").write_text(readme)
print(json.dumps({a: {"win_rate": round(M[a]["win_rate"], 3), "score": round(M[a]["score"], 1), "correct": M[a]["correct"],
                      "incorrect": M[a]["incorrect"], "cost": round(M[a]["total_cost"], 4), "cost_per_correct": round(M[a]["cost_per_correct"], 4),
                      "searches": round(M[a]["searches"], 2), "input_tokens": round(M[a]["input_tokens"]), "latency": M[a]["latency_median"]} for a in ARMS},
                 indent=1))
print({f"{x} vs {y}": PAIR[(x, y)] for x, y in PAIRS})
