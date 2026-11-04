# Plan: research of the responsible authority (agent 2)

Status: 2026-11-04. Detail plan for the research part of item 5.4 of [plan.md](plan.md). Effort: S = under an hour, M = a few hours, L = a day or more.
Owner: **You** = needs your decision or your accounts, **Claude** = can be built here, **Team** = needs the team or an expert.

## Goal

Take a classified report (category, lane) and its location and answer: **which authority is responsible, and how do we reach it?**
The answer is a `ResearchResult` (authority, channel, sources, confidence). It feeds the policy code, the drafting agent and the approval pause.
A wrong authority is the worst failure here: a report that goes to the wrong office is lost, and the user trusts us less. So the system prefers "I do not know" to a guess.

What is **not** part of this plan: duplicate check, drafting, approval, the real sending (plan.md 5.5 to 5.7).

## The design

**Registry first, the agent second.** Most reports in a pilot area have a known answer. A table we filled and checked ourselves answers them without any model and without sending data to anybody. The agent only works where the registry has no entry, and what it finds is a *suggestion* that a person checks before it becomes a registry entry.

```
classified report
      │
      ▼
1. municipality from the coordinates   (offline, no third party gets the location)
      │
      ▼
2. registry lookup (municipality, category)
      ├── hit ─────────────► ResearchResult, verified, confidence 1.0, no model call
      │
      └── miss ─► 3. research agent (tools, sources) ─► ResearchResult, unverified, with sources
                                                      └► suggestion for the registry (a person checks it)
```

### 1. Municipality from the coordinates
Offline: a point-in-polygon check on boundary data with the official municipality key (AGS). No geocoder gets the location of the report (documentation.md, 2026-10-27: nothing may link location and user).
For the MVP the boundaries of the pilot municipalities are enough, checked with a small geometry library in Python. PostGIS comes with the duplicate check (plan.md 5.5) and can take over then.
TODO to settle: the license and the source of the boundary data (the federal agency data or OpenStreetMap, both need an attribution).

### 2. The registry
- Files in the repository, one per municipality (`backend/registry/<ags>.yaml`): the authority, the department, the categories it handles, the channel (`email`, `web_form` or `open311`), the target (address or URL), the source URL where the contact was read, and the date of the last check. Contact data of authorities is public.
- Why files and not only the database: the team can read, review and correct them in a pull request, and the history shows who changed what. A loader puts them into a table.
- An entry is `verified` only when a person has checked the source and the channel.

### 3. The research agent (fallback)
A LangGraph agent with a few tools, behind the same kind of provider interface as the classification:

| Tool | What it does | Limit |
|---|---|---|
| `find_municipality` | name and key of the municipality | local, no network |
| `registry_lookup` | what the registry knows | local |
| `fetch_page` | reads one web page | only the domain of the municipality and a short allowlist, size and time limit, `robots.txt` respected |
| `search_web` | open web search | **not in the MVP** (needs a search provider and its own privacy check) |

- The agent gets **only the municipality (name, key) and the category.** No text, no photo, no pseudonym, no coordinates.
- A web page is untrusted input (prompt injection): the agent has no tool that writes, sends or changes anything, and its answer is checked against a schema.
- **Every claim needs a source.** An authority or a contact that no fetched page supports is dropped. A made-up email address is worse than none.
- The result is stored as a **suggestion** (`authority_suggestions`) for a person to verify and move into the registry. That is how the registry grows.

### The result

```python
class Channel(ContractModel):
    type: Literal["email", "web_form", "open311"]
    target: str          # address or URL
    verified: bool       # a person checked it

class ResearchResult(ContractModel):          # strict, extra="forbid", frozen
    municipality: str    # name, for the app
    authority: str | None
    channel: Channel | None
    sources: list[str]   # URLs that support the answer, empty only for a registry hit
    confidence: float    # 0 to 1
```

### Where it sits in the chain
A node `research` behind `classify` in `orchestrator/graph.py`. Emergencies and reports without a classification do not reach it. Statuses: `classified` becomes `researched`. If the research fails, the report stays `classified` and is researched later. "Wrong authority" in the app runs the node again and the earlier answer is excluded.

### Policy
An unverified channel is **never used for real sending**. The policy code (plan.md 5.4) reads `verified` and `confidence` to choose the approval level. In the prototype the sending is simulated anyway (plan.md 5.7).

## Decisions needed first

| # | Decision | My recommendation |
|---|---|---|
| P1 | **Pilot municipality (one or two).** Where do the test users report? The research needs real contacts for it. | One municipality where the team lives or studies, a second one later to prove that it is not hard-coded. **Please name it.** |
| P2 | Municipality from the coordinates: offline boundaries or a geocoder (Nominatim)? | Offline boundaries of the pilot area. A geocoder would send the exact location to a third party. |
| P3 | Registry: files in the repository or only the database? | Files in the repository, loaded into a table. Reviewable and versioned. |
| P4 | Open web search in the MVP? | No. Registry plus fetching the pages of the municipality only. Open search later, with its own privacy check. |
| P5 | Which model runs the agent? | The same open decision as for the classification (D1). Build with a scripted stand-in first and swap the model in later, as before. |
| P6 | Who fills the registry for the pilot? | The team, by hand, from the websites of the municipality: authority, department and contact per category. The agent can prepare drafts of these entries, a person checks them. |

## Steps

| # | What | Owner | Effort | Done when |
|---|---|---|---|---|
| R0 | Decide P1 to P6 | You, Team | S | written into the decision log |
| R1 | Collect the registry data for the pilot municipality: per category the authority, the department, the channel, the source URL | Team, Claude | M | a reviewed file with source URLs |
| R2 | Contract: `Channel`, `ResearchResult`, the registry entry, strict models with tests | Claude | S | tests green |
| R3 | Boundary data of the pilot area and the offline municipality lookup | Claude | M | a coordinate gives the municipality, outside the area gives "unknown" |
| R4 | Registry loader and lookup (files into a table, migration `006`), a hit needs no model | Claude | M | a report in the pilot area gets a verified result |
| R5 | Put it into the chain: node `research`, status `researched`, the answer in the endpoint and in `GET /v1/reports/{id}` | Claude | M | the result comes back with the report, a failure leaves the report `classified` |
| R6 | App: show the authority and the channel instead of the scripted "Zuständig: Ordnungsamt Musterstadt" | Claude | S | the mock lines are gone |
| R7 | Research agent for the registry misses: tools, scripted stand-in, source check, suggestions table | Claude | L | a miss gives a result with sources or "unknown" |
| R8 | Evaluation set: 20 to 30 cases (municipality, category, the authority a person checked) and a script for the hit rate, wrong answers and answers without a source | Claude, Team | M | table with numbers |
| R9 | Real model for the agent, chosen with the classification provider decision | You, Team, Claude | M | decision with numbers |

Order: R0 → R1 and R2 and R3 in parallel → R4 → R5 → R6 → R7 and R8 → R9.
The first useful result needs **no model**: R1 to R6 give a working "responsible authority" from the registry alone.

## Targets (proposals, please confirm in R0)

| Measure | Target |
|---|---|
| Registry hits in the pilot area that are correct | 100 % (the data is checked by a person, a miss here is a data error) |
| Agent answers with a source that supports them | 100 % |
| Agent: wrong authority stated as sure (confidence high) | 0 on the evaluation set |
| Agent: no answer where it cannot find one | allowed, better than a guess |
| Time for a registry hit | under 1 second |

## Risks

- **Wrong or outdated contacts.** The registry has a check date and a source for every entry, and old entries are flagged. A real sending needs `verified`.
- **Responsibility is not always clear.** A road can belong to the city, the district or the state, a playground to the city or a private owner. The registry key is (municipality, category) today. If that is too coarse, a rule per road class or an owner field comes later. This is exactly why a wrong-authority action exists in the app.
- **Pages with hidden orders.** The agent cannot act on them (it only reads and answers in a schema) and every claim needs a source.
- **Scraping rules.** Only the pages of the municipality, `robots.txt` respected, few requests, cached. Check the terms of use before any broader fetching.
- **The pilot is one place.** It proves the idea, not that it works for every municipality. That is the reason for a second municipality.
