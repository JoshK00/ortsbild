# Plan: research of the responsible authority (agent 2)

Status: 2026-11-04, revised the same day. **Built: R1 to R6 and the display part of R7 (see the steps). Open: the actions in the app (confirm, wrong authority, enter by hand), the editable address line, the evaluation set (R8) and the choice of the real provider (R9).** Detail plan for the research part of item 5.4 of [plan.md](plan.md). Effort: S = under an hour, M = a few hours, L = a day or more.
Owner: **You** = needs your decision or your accounts, **Claude** = can be built here, **Team** = needs the team or an expert.

## What changed

The first version of this plan started from a pilot municipality with a hand-filled registry. That does not fit the test group: the students come from many different places and countries, so **no fixed pilot place can serve them**. The research has to work for **any place**. The agent that looks things up on the web is therefore the core, and the registry becomes a memory of what was confirmed, not a hand-filled start.

## Goal (the MVP)

From a classified report, produce **the final message for the user to approve**: a neutral text, the cleaned photo, the address of the place, and **the authority with a way to contact it**. The research finds the authority, the drafting step (the "main" model) puts everything into the message in the chat (this plan covers the research, the drafting is the next part of plan.md 5.4).

The research is allowed to be wrong, but never silently wrong: the user always sees **who** and **where the information comes from** (links), and the approval is the check. If nothing is found, the user gets the draft anyway and adds the recipient by hand.

What is **not** part of this plan: duplicate check, the drafting itself, the approval pause, the real sending (plan.md 5.5 to 5.7).

## The design

```
classified report + place (country, town, street ... from the phone)
      │
      ▼
1. registry: has someone confirmed this place and category before?
      ├── yes ─► ResearchResult from memory, no model call
      │
      └── no ─► 2. research agent: search the web, read pages, answer with sources
                       │
                       ▼
                 ResearchResult (authority, channel, language, sources, confidence)
                       │
                       ▼
                 shown to the user: [confirm]  [wrong authority]  [enter contact by hand]
                       └─ confirmed ─► written to the registry (the memory grows with use)
```

### 1. The place comes from the phone
The app already has the position. The phone turns it into an address with Apple's geocoder (works worldwide): country, state, town or municipality, district, postal code, street, house number. The app sends these as **structured fields** next to the coordinates and shows one line ("Hauptstraße 12, 80331 München, Deutschland") that the user can correct.
- No geocoder on our server, so no third party gets the location from us. The phone talks to Apple, as it does for every maps app.
- The same address goes into the final message, so this also answers "where is the defect" for the authority.
- The fields are **untrusted input** (the user can edit them): limited in length, never put into an instruction, only used as search words.
- TODO: if the geocoder fails (no network), the app asks the user to type the place.

### 2. The registry is a memory, not a start
A table keyed by (country, municipality, category): authority, channel (`email`, `web_form`, `open311`), target, the sources, how many users confirmed it, whether the team verified it, and when. It is used first, so a place that someone confirmed once costs no model call and gives the same answer again. Old entries expire (a contact changes).
An entry written by users counts as *confirmed by users*, an entry the team checked as *verified*. Real sending (later) needs `verified`.

### 3. The research agent
A LangGraph agent behind the same kind of provider interface as the classification. Tools:

| Tool | What it does | Limit |
|---|---|---|
| `registry_lookup` | what the memory knows | local |
| `search_web` | web search, in the language of the place | a provider behind an interface, a few searches per run |
| `fetch_page` | reads one page and returns its text | the safe fetcher below |

- The agent gets **only the place (country, town, district) and the category.** Not the text, not the photo, not the pseudonym, not the coordinates, not the street number.
- **Every claim needs a source** (a URL it read). A name or an address that no page supports is dropped. A made-up email address is worse than none.
- It has no tool that sends, writes or changes anything outside its own result. A page that says "ignore your rules" can only change the answer inside the schema, and the user sees the sources.
- The language of the answer: the official language of the place. The result carries `language`, so the draft can be written in it.

### The safe page fetcher
Search results lead to pages we do not know. The fetcher is code, not a model, and enforces: only `https`, no private or local addresses (also not after a redirect), no more than a few pages and a few seconds per run, a size limit, only text is extracted, `robots.txt` respected, results cached.

### The result

```python
class Place(ContractModel):          # what the phone sends, all optional text fields with length limits
    country_code: str | None
    state: str | None
    municipality: str | None         # town or municipality
    district: str | None
    postal_code: str | None
    street: str | None
    house_number: str | None

class Channel(ContractModel):
    type: Literal["email", "web_form", "open311"]
    target: str                      # address or URL
    verified: bool                   # the team checked it

class ResearchResult(ContractModel): # strict, extra="forbid", frozen
    authority: str | None
    channel: Channel | None
    language: str | None             # of the place, for the draft
    sources: list[str]               # URLs that support the answer, empty only for a registry hit
    confidence: float                # 0 to 1
```

### Where it sits in the chain
A node `research` behind `classify` in `orchestrator/graph.py`. Emergencies and reports without a classification do not reach it. Statuses: `classified` becomes `researched`. If the research fails or finds nothing, the report stays `classified` and the user adds the recipient by hand. "Wrong authority" in the app runs the node again with the earlier answer excluded.

## Privacy

- **Nothing about the person** goes to the search or the model: only place and category.
- The search queries contain a town and a word like "Ordnungsamt" or "Mängelmelder". The search provider sees which town is searched, not who searches (the request comes from our server).
- The coordinates stay on the phone and in our database. The exact street number is not needed for the research.
- The research stays on the sanitized side of the chain: it never sees a raw report.

## Decisions needed first

| # | Decision | My recommendation |
|---|---|---|
| P1 | Where does the address come from? | From the phone (Apple geocoder), editable by the user. No geocoder on our server. |
| P2 | **Which web search provider?** It needs an account and a key, and a privacy check (EU or not, terms). | Put it behind an interface and build the agent with a scripted stand-in first. The team picks the candidates, I build the adapter and we measure (as with the classification). Some model providers have a built-in search tool, worth checking for Mistral (not verified). |
| P3 | **Which countries and languages for the test?** Where do the students come from? | Start with the countries of the team, the agent works in the language of the place. Say which, so the evaluation set covers them. |
| P4 | Which model runs the agent? It needs tool calling and reading. | The same open decision as for the classification (D1). Build with a scripted stand-in first and swap the model later. |
| P5 | Registry as a memory that grows with confirmations? | Yes. It is what makes the second user of a place cheap and consistent. |
| P6 | In which language is the draft written? | In the language of the authority's place (the agent reports it). The app shows the user a short German summary next to it. |

## Steps

| # | What | Owner | Effort | Done when |
|---|---|---|---|---|
| R0 | Decide P1 to P6 | You, Team | S | written into the decision log |
| R1 | ~~Contract: `Place`, `Channel`, `ResearchResult`, strict models with tests~~ **Done** (`research/models.py`, `Place` in `models/incoming_report.py`) | Claude | S | tests green |
| R2 | ~~App: turn the position into a `Place` with the phone's geocoder, show one editable line, send the fields. Backend: take them in, validate, store~~ **Mostly done**: the app turns the position into a `Place` with MapKit and sends it, the backend validates, stores and returns it. Still open: the editable line for the user | Claude | M | the place arrives and is stored |
| R3 | ~~The safe page fetcher with its limits and tests (private addresses, redirects, size, time)~~ **Done**: `research/fetcher.py` with tests for the attacks. It is used to *check* answers (`research/verify.py`), not as a tool of an agent | Claude | M | the attacks of the tests are refused |
| R4 | ~~Search provider interface and a scripted stand-in, the agent graph with source check~~ **Changed and done**: no own agent loop. One call to Mistral with its built-in web search finds the answer (`research/mistral.py`), then our code checks every answer against the pages it names. A scripted stand-in exists for tests | Claude | L | a scripted run gives a result with sources, an answer without a source is dropped |
| R5 | ~~Registry as a memory: table (migration `006`), lookup first, write on confirmation, expiry~~ **Done**: `authority_registry` (migration `006`), lookup first, an entry found by the agent expires after 30 days. Still open: writing the confirmations from the app | Claude | M | the second report of a place needs no model |
| R6 | ~~Put it into the chain: node `research`, status `researched`, the answer in the endpoint and `GET /v1/reports/{id}`~~ **Done**: node `research` in the orchestrator, status `researched`, the answer in the endpoints | Claude | M | the result comes back with the report |
| R7 | ~~App: show authority, contact and the source links, the actions confirm, wrong authority, enter by hand~~ **Partly done**: the chat shows authority, contact and sources. Still open: confirm, wrong authority and enter by hand | Claude | M | the mock lines are gone |
| R8 | Evaluation set: 15 to 20 real places (the home towns of the team) with the authority a person checked, and a script for the hit rate, answers without a source and time | Team, Claude | M | table with numbers |
| R9 | Real search provider and real model, chosen with the classification decision | You, Team, Claude | M | decision with numbers |

Order: R0 → R1 → R2 and R3 in parallel → R4 → R5 → R6 → R7, R8 → R9.
The chain works end to end with the stand-ins first, the real search and the real model are swapped in at the end.

## Targets (proposals, please confirm in R0)

| Measure | Target on the evaluation set |
|---|---|
| Authority correct (judged by the team member from that place) | at least 70 % at the first try, to be raised later |
| Answers with a source that supports them | 100 % |
| Answers stated as sure that are wrong | 0 (better "not found" than a wrong sure one) |
| Contact that exists (an address with a valid form, a page that loads) | 100 % of the answers |
| Time of one research | under 30 seconds, from memory under 1 second |
| Cost of one research | measured in R9, then set |

## Risks

- **Quality differs a lot by place.** A big city has a clear page, a small village in another country may have none. The honest answer is "not found", and the user then adds the recipient. The target of 70 % is a guess until R8.
- **Responsibility is not always clear.** A road can belong to the city, the district or the state. The key (country, municipality, category) is coarse. A rule per road class comes later if the evaluation shows it.
- **Pages with hidden orders.** The agent cannot act on them and every claim needs a source, but a page can still lead it to a wrong answer. The user sees the sources and approves.
- **The fetcher is an attack surface.** It reads addresses that a search or a page chose. That is why it is plain code with strict limits and its own tests.
- **Cost and speed.** A research with several searches and pages takes seconds and tokens. The memory and the limits per run keep it small. The answer by polling (classification plan C8) becomes necessary.
- **A wrong confirmation poisons the memory.** One user clicking "confirm" is not proof. Real sending needs `verified` by the team, and the count of confirmations tells how much to trust an entry.
