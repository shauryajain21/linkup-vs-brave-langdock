# Linkup vs Brave on Langdock's search queries

Claude Sonnet 5.5 answered 100 of Langdock's search queries twice: once with Brave's Web Search API as its search tool (**Brave**) and once with Linkup `fast` (**Linkup**). Same model, same prompt, same 10-search cap. Two separate graders scored the answers: a blind A/B comparison, and a fact-check in which a judge verifies each answer's claims with its own web search.

- **Blind A/B:** Linkup's answer was better on 66 queries and Brave's on 32, with 2 ties (sign test p < 0.001).
- **Fact-check:** Linkup scored 82.8 vs Brave's 79.4 out of 100; 30 vs 26 answers fully correct, 20 vs 24 incorrect.
- **Cost per query:** Linkup $0.0662, Brave $0.0682 (3% lower); per correct answer Linkup $0.2207, Brave $0.2622 (16% lower).
- **Median latency:** Linkup 15.8s, Brave 13.2s.

![Win rate, fact-check score, cost and latency for each arm](charts/overview.png)

| Metric | Brave Web Search | Linkup fast (experimental) |
|---|---|---|
| Blind A/B win rate (ties count half) | 33% | 67% |
| Fact-check score (0–100) | 79.4 | 82.8 |
| Fully correct (fact-check) | 26 | 30 |
| Cost per query | $0.0682 | $0.0662 |
| Cost per correct answer | $0.2622 | $0.2207 |
| Median latency | 13.2s | 15.8s |

## Setup

|  | Brave Web Search | Linkup fast (experimental) |
|---|---|---|
| Model | `claude-sonnet-5-5` | `claude-sonnet-5-5` |
| Endpoint | `/res/v1/web/search` | `/v1/search`, `depth=fast`, experimental API key |
| Settings | `count=10`, `extra_snippets=true` | `searchResults`, `maxResults=10` |
| What Claude sees per result | title, URL, date, description, up to 5 extra snippets | title, URL, content |
| Search price (per 1,000) | $5.00 (list) | $4.00 (offered to Langdock; list $5.00) |
| Search cap | 10 per query | 10 per query |

Claude decides what to search for and how often. Each tool description asks for the query style its provider is built for: keyword queries for Brave, natural-language retrieval instructions for Linkup. Neither provider gets a location hint: Brave runs without `country` or `search_lang`, and Linkup has no location setting.

**Queries:** a random sample (fixed seed) of 100 of the 1,000 synthetic search queries Langdock shared on October 16, 2026 as typical of what its product sends to a search API. Each query is sent to Claude as the user's message, with a system prompt for an enterprise assistant used by companies in Germany and across Europe. 58 are in German, 37 in English and 5 in other languages. `gpt-6-luna` tagged each query with a topic.

**Grading:** the queries have no answer key, so two `gpt-6-luna` graders score the answers. Their results are reported separately.
- **Blind A/B:** the judge sees the query and both answers in random order, with no labels and no web access, and picks the one the user would rather get, or a tie. It weighs whether the answer gives what the query is looking for, then correctness as far as it can tell, then honesty about gaps. Citations, length and style don't count.
- **Fact-check:** the judge sees one answer at a time and checks up to 5 of its most important claims with its own web search (OpenAI's, independent of both arms), marking each supported, contradicted or unverifiable. It gives a verdict (correct / partial / incorrect / not found) and a score out of 100: answers the query 30, accuracy 50 (minus 25 for each contradicted central claim and 10 for each other contradicted claim), freshness 10, calibration 10.

## Blind A/B

![Blind A/B](charts/ab.png)

| Pair | Left better | Tie | Right better | Sign test |
|---|---|---|---|---|
| Brave Web Search vs Linkup fast (experimental) | 32 | 2 | 66 | p < 0.001 |

## Fact-check

![Fact-check verdicts and score by topic](charts/factcheck.png)

| Metric | Brave Web Search | Linkup fast (experimental) |
|---|---|---|
| Correct | 26 | 30 |
| Partial | 49 | 50 |
| Incorrect | 24 | 20 |
| Not found | 1 | 0 |
| Score (0–100, average) | 79.4 (75.8–82.8) | 82.8 (79.7–85.8) |
|   Answers the query (of 30) | 25.0 | 25.9 |
|   Accuracy (of 50) | 37.9 | 40.1 |
|   Freshness (of 10) | 8.9 | 8.7 |
|   Calibration (of 10) | 7.7 | 8.1 |
| Claims contradicted by the judge's sources | 81 of 460 (17.6%) | 69 of 471 (14.6%) |
| Answers with at least one contradicted claim | 61 | 58 |

Score differences between arms, per query:

| Pair | Score difference (right − left) | 95% CI | Sign test (5+ points) |
|---|---|---|---|
| Brave Web Search vs Linkup fast (experimental) | +3.4 | -0.3 to +7.2 | p = 0.22 |

## Cost

![Cost per query and at Langdock's volumes](charts/cost.png)

| Per query | Brave Web Search | Linkup fast (experimental) |
|---|---|---|
| Total cost | $0.0682 | $0.0662 |
| Cost per correct answer | $0.2622 | $0.2207 |
| Search fees | $0.0112 | $0.0078 |
| Model tokens | $0.0570 | $0.0585 |
| Searches | 2.23 | 1.94 |
| Input tokens (incl. cache) | 18,488 | 18,646 |
| Output tokens | 1,784 | 1,857 |

| Queries per month | Brave Web Search | Linkup fast (experimental) |
|---|---|---|
| 1,000,000 | $68,183 | $66,214 |
| 5,000,000 | $340,916 | $331,070 |
| 10,000,000 | $681,833 | $662,141 |

Linkup cost reflects the snippet compressor (30% fewer retrieved tokens), releasing the week of October 19, 2026.

Search fees are Brave at its $5.00 list price and Linkup at the $4.00 per 1,000 calls offered to Langdock (20% off list); the rest of the cost comes from how much text Claude reads and writes. Prices: Sonnet 5.5 $2.00 / $10.00 per million input / output tokens (cache reads $0.20, cache writes $2.50). Any volume discount Brave offers Langdock is not included.

## Latency

![Latency: share of queries answered within N seconds](charts/latency.png)

| Metric | Brave Web Search | Linkup fast (experimental) |
|---|---|---|
| Median latency | 13.2s | 15.8s |
| p90 latency | 18.9s | 22.7s |

Latency is the whole loop: Claude's turns plus every search call, from the query to the final answer.

## Topics and languages

| Topic | Queries | Brave Web Search: A/B win rate / score | Linkup fast (experimental): A/B win rate / score |
|---|---|---|---|
| Law, tax & regulation | 36 | 17% / 81 | 83% / 83 |
| Companies & markets | 22 | 59% / 75 | 41% / 78 |
| Tech & IT | 15 | 27% / 87 | 73% / 89 |
| Products & pricing | 12 | 25% / 75 | 75% / 80 |
| Local & everyday | 10 | 60% / 74 | 40% / 85 |
| Other | 5 | 20% / 87 | 80% / 89 |
| German | 58 | 30% / 78 | 70% / 81 |
| English | 37 | 39% / 81 | 61% / 85 |
| Other languages | 5 | 20% / 83 | 80% / 83 |

## Caveats

- 100 queries: differences of a few queries either way are within noise; the sign tests and confidence intervals above say how likely each gap is by chance.
- The queries are synthetic examples from Langdock, not production traffic.
- Both graders are a single LLM (`gpt-6-luna`). The fact-checker can only mark a claim contradicted when its own search finds a better source, so it under-counts errors on niche topics.
- Each arm was run with one configuration. Brave with `country=DE`, or different result counts and token budgets on either side, may score differently.

## Files

- `data/`: the 100 queries with topic and language, each arm's answers (with the searches Claude ran, tokens, latency and retrieved URLs), and every grade with the judge's reasoning
- `charts/`: the charts above
- `build.py`: rebuilds `charts/` and this README from `data/` (`python3 build.py`)
