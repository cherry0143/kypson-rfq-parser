# NOTE

## Approach

`parse_rfq` is deterministic and standard-library only. It normalises Unicode, case, dotted abbreviations and Hinglish variants, then extracts candidate numbers from digits, Indian grouping (`1,50,000`), suffixes (`20k`, `2.5 lac`, `40 hazaar`, `15K`) and word numbers (`do hazaar`, `dedh`, `paune do`), merging compound forms. Candidates are rejected when context marks them as GSM, micron/thickness, capacity, fill weight (`25 kg bag`), dimensions, ply/colour, percentages, prices/rates, addresses/GSTIN/PIN, ordinals, years or areas. The survivors are scored: count units (`pcs`, `bags`, `boxes`) > explicit kg/mt > multiplier/context; default `pcs`; grams and quintals convert to kg. Category uses weighted keyword patterns with conflict rules: BOPP film/roll → `film` but BOPP-laminated woven bag → `bopp_bag`; jumbo/bulk/FIBC → `fibc`; cement/AD Star → `woven_sack`; shrink/stretch → `film`; plain box/carton → `corrugated_box`; mono/pharma carton → `mono_carton`. GSM and micron are extracted separately, including reversed forms, tolerances and `mm`→micron. Location uses a gazetteer of Indian cities/states, countries and world cities, plus a delivery/`to`/`at` fallback.

## Score

`python score.py my_tests.jsonl`: **78/78 all-fields matches (100%)**, 100% on every field, under 0.1 s on a normal laptop CPU. The 78 examples cover all categories, Hinglish, typos, Indian number formats, missing fields, unit conversions and the main traps.

## Three messages the parser gets wrong

1. **`1 lakh 50 bags`** → `100000`; should be `100050`. Compound merging handles adjacent multiplier groups (`1 lakh 50 hazaar`) but leaves a trailing plain number after a multiplier as a lower-scoring candidate.
2. **`1.5L bags`** → `1.5 pcs`; should be `150000 pcs`. `L` is not modelled as lakh because it also means litres; only `k`, `lakh`/`lac` and `crore` are supported.
3. **`bopp bags 10000 pcs to somewheresville`** → `location: null`; should be `Somewheresville`. Unseen places after a plain `to`/`at` are accepted only when capitalised or after a stronger cue such as `delivery to`, which avoids treating ordinary lowercase words as places.

## With 1,000 real labelled examples

Split by message source/template/time to avoid leakage; stratify by category and trap type. Measure exact match, per-field accuracy, a category confusion matrix, and quantity error buckets (fill vs order, capacity, number format, unit). Keep 200–300 examples held out; use the rest for error analysis and rules. Add every confirmed error to regression tests and review low-confidence cases first. Prefer targeted rules while the held-out score improves. Add a small supervised model (char n-grams/linear or gradient-boosted) only if rules plateau, keeping rule outputs as features. The 78 examples here are a regression suite, not a validation set.

## Knowing it works in production

Log raw text, parsed fields, confidence signals and latency. Dashboard daily: category mix, zero-quantity rate, null location/GSM/micron/unit rates, exceptions and latency. Route low-confidence parses to a human review queue and sample-audit normal traffic weekly; feed corrections back into rules and tests. Shadow/canary new parser versions on live traffic against human-labelled samples, and alert on drift in category mix, quantity distribution, nulls or accuracy. Set an error budget and per-field thresholds.

## AI tools

I used an AI coding assistant to draft and iterate the parser, tests and this note. I personally reviewed the code, ran `python score.py my_tests.jsonl` after each change, manually checked all 78 expected outputs, and verified the trap cases (fill weight, capacity, dimensions, GSM/micron, BOPP film vs bag, jumbo/FIBC, cement/AD Star, mono vs plain carton, Indian formats). No paid APIs or API keys are used; there are no third-party dependencies.
