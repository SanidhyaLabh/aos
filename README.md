# Origin // ASO Sentinel

**Manipulation-cost-aware oracle protection and bounded-loss borrowing for a Multipli-style
(MakerDAO-fork) RWA lending market.**

Hackathon prototype for the Multipli Hackathon (GraVITas '26, VIT Vellore). Problem statement: Web3 oracle
reliability, accuracy and resilience.

> **What this is:** a tested prototype that runs **Multipli's own verified mainnet contracts** (Vat, Spotter,
> OSM, PriceFeedAdapter, GemJoin5) on a local chain, side by side **with and without** our protection layer.
> It includes a dashboard, a one-command on-chain demo, and a public Sepolia deployment of the v1 core.
>
> **What this is not:** it is not integrated with, deployed to, or endorsed by Multipli. It is not audited
> and not production-ready. It does **not** guarantee protection against manipulation or guarantee that
> bad debt is prevented: it **bounds** how much new debt can be created while data or market conditions
> look wrong. The liquidity depth and source weights are **assumptions set by governance**, not measured
> data.

## Contents

1. [Project overview](#1-project-overview)
2. [Problem statement](#2-problem-statement)
3. [Threat model](#3-threat-model)
4. [Why an oracle quorum alone is insufficient](#4-why-an-oracle-quorum-alone-is-insufficient)
5. [Architecture diagram](#5-architecture-diagram)
6. [Smart contract architecture](#6-smart-contract-architecture)
7. [Risk Engine](#7-risk-engine)
8. [Manipulation-cost model](#8-manipulation-cost-model)
9. [Sentinel state machine — five states, five different actions](#9-sentinel-state-machine--five-states-five-different-actions)
10. [Borrowing growth cap](#10-borrowing-growth-cap)
11. [Baseline versus protected](#11-baseline-versus-protected)
12. [Validation: false positives and false negatives](#12-validation-false-positives-and-false-negatives)
13. [Historical validation](#13-historical-validation)
14. [Known detection boundaries](#14-known-detection-boundaries)
15. [Installation](#15-installation)
16. [Local development (dashboard)](#16-local-development-dashboard)
17. [Tests](#17-tests)
18. [Demo](#18-demo)
19. [Deployment](#19-deployment)
20. [Contract addresses (verified)](#20-contract-addresses-verified)
21. [Transaction evidence](#21-transaction-evidence)
22. [Security assumptions](#22-security-assumptions)
23. [Known limitations](#23-known-limitations)
24. [Future improvements](#24-future-improvements)
25. [Judge presentation flow](#25-judge-presentation-flow)

**Status at a glance**

| | What |
|---|---|
| **Implemented** | `ASOVerifier`, `ASOSentinel` (v1); `ASORiskEngine`, `WeightedMedian`, `CostModel`, `OriginSentinel` (Origin); deploy scripts; CLI demos; dashboard |
| **Tested** | 183 Foundry tests (unit, fuzz, invariant) incl. 21 state/action-policy tests; 40 mutants all killed; validation suite of 38 + 19 holdout labelled cases with measured TP/FN/TN/FP ([docs/VALIDATION.md](docs/VALIDATION.md)); on-chain demos with 22/22 (v1) and 152/152 (Origin) expected outcomes; 9 dashboard unit tests |
| **Simulated** | price sources (anvil or team keys), the Chainlink-style feed, the collateral token, time (anvil time travel), the keeper, market depth (a governance input), and attacker behaviour in scenarios |
| **Planned (not done)** | Multipli integration (`vat.rely`), real independent sources, measured liquidity, keeper incentives, vault-integrity checks, timelock/multisig ownership, an external audit, an Origin Sepolia deployment |

---

## 1. Project overview

Multipli's rwaUSD market lends against a single price path (`feed → adapter → OSM → Spotter → Vat`). Origin
adds an independent, permissionless guard. It **never changes a collateral price**, so it cannot cause
liquidations. It controls exactly one thing: the collateral debt ceiling `line`.

- **v1 core** (`ASOVerifier` + `ASOSentinel`): signed N-of-M attestations with freshness, replay and
  disagreement checks. Borrowing closes when the data is stale, disputed or overvalued, and repayments keep
  working.
- **Origin layer** (`ASORiskEngine` + `OriginSentinel`): honest sources can still faithfully report a
  *manipulated market*. The Origin layer therefore also looks at TWAP deviation, velocity, source divergence
  and an explicit manipulation-cost estimate. It moves through FRESH / WATCH / DISPUTED / PROTECTIVE /
  RECOVERING, and caps debt growth per epoch so that residual exposure is **bounded**.

The v1 contracts are unchanged from the Sepolia deployment. Origin is added as new contracts next to them.

## 2. Problem statement

The following is verified in Multipli's deployed code (vendored byte-identical in [`src/multipli`](src/multipli);
see [docs/PROVENANCE.md](docs/PROVENANCE.md)):

- **The adapter detects staleness.** `PriceFeedAdapter.peek()` returns `(0, false)` when the feed is older than
  `maxDelay` (24h on mainnet).
- **The OSM discards that signal.** `OSM.poke()` does nothing when the adapter returns `false`, while
  `OSM.peek()` keeps returning its cached price with `has = true`.
- **The Vat keeps lending at that price.** It has no notion of freshness.
- **Invalidating the price is worse.** If the OSM reported "no price", the Spotter would set `spot = 0` and
  every vault would become liquidatable.
- **A fresh price can still be a manipulated price.** If the underlying market is pumped, every honest
  source reports the pumped value, the quorum is satisfied, and the Vat lends against it.

Mainnet configuration (read at block 26,009,365): `mat` 140%, OSM `hop` 3600s, adapter `maxDelay` 86,400s, ilk
`line` 1,000,000 rwaUSD, `dust` 100 rwaUSD. The demo uses the same values.

**Historical reference (Mango Markets, October 2022).** According to the
[SEC](https://www.sec.gov/newsroom/press-releases/2023-13) and
[CFTC](https://www.cftc.gov/PressRoom/PressReleases/8647-23) complaints, a trader allegedly pushed up the
price of MNGO on the exchanges that fed Mango's oracle (over 13-fold within about 30 minutes), then borrowed and
withdrew roughly $110–116 million against the inflated collateral value. These are regulators' allegations; a
federal judge later
[overturned the criminal convictions](https://www.trmlabs.com/resources/blog/breaking-federal-judge-overturns-all-criminal-convictions-in-mango-markets-case-against-avraham-eisenberg).
We cite the case only because it illustrates the mechanism: *an accurate oracle of a manipulated market*. We do
not claim Origin would have prevented it. Mango was a different system, and our cost model is a rough proxy.

## 3. Threat model

| Actor / failure | Can do | Origin response |
|---|---|---|
| Feed stops updating | OSM keeps an old price, Vat keeps lending | adapter `has=false` → PROTECTIVE; Vat price above effective price → PROTECTIVE |
| Minority of sources lie or break | submit outlier prices | no quorum, or DISPUTED (> 1% disagreement) → borrowing closed |
| Attacker without source keys | forge, replay, duplicate or reorder signatures | reverts (`InvalidSignature`, `NonceNotIncreasing`, `SignersNotStrictlyAscending`, …) |
| Market manipulator | moves the real market, so all honest sources agree on a bad price | TWAP deviation, velocity and the cost gate → WATCH or PROTECTIVE; epoch cap bounds what is left |
| Patient manipulator | holds the price longer than the TWAP window | **not fully detectable**; exposure bounded by WATCH headroom and the epoch cap (scenario B) |
| Keeper absent | nobody calls `poke()` | exposure bounded by the `line` set at the last poke |
| Admin | changes sources and parameters within bounds | out of scope; production needs a timelock/multisig |

Out of scope: a compromised majority of source keys, Multipli governance, L1 consensus, and liquidation
mechanics (Dog/Clipper are not deployed).

## 4. Why an oracle quorum alone is insufficient

A 3-of-5 quorum answers *"do independent sources agree on what the market says?"* It does not answer
*"is the market itself being manipulated?"* or *"is it worth manipulating?"* In scenario A, all five sources
honestly sign a +60% pumped price and the verifier returns `OK`. The baseline lends 285,000 rwaUSD that are
backed by 250,000 USD at the fair price. Origin looks at **how the price got there** (TWAP deviation and
velocity) and at **how cheap it would be to push it there** (the cost gate), and it limits **how much can be
borrowed at once** (the epoch cap).

## 5. Architecture diagram

```mermaid
flowchart LR
    subgraph OFF["Off-chain (demo: anvil test keys)"]
        SRC["5 price sources<br/>EIP-712 signatures"]
        FEEDER["Feeder<br/>(stops = stale)"]
        KEEP["Relayer / keeper (anyone)"]
    end
    subgraph MOCKS["Mocks"]
        AGG["MockAggregator"]
    end
    subgraph MULTIPLI["Multipli verified mainnet code (unmodified)"]
        ADP["PriceFeedAdapter"] --> OSM["OSM (1h delay)"]
        OSM --> SPB["Spotter"] --> VATB["Vat BASELINE"]
        OSM --> SPP["Spotter"] --> VATP["Vat PROTECTED"]
    end
    subgraph OURS["Ours"]
        VER["ASOVerifier<br/>quorum · freshness · replay · disagreement"]
        RISK["ASORiskEngine<br/>TWAP · velocity · weighted median · cost gate"]
        SEN["OriginSentinel<br/>state machine · epoch cap"]
    end
    FEEDER --> AGG --> ADP
    SRC --> KEEP
    KEEP -- submitRound --> VER
    KEEP -- "sync / recordSources" --> RISK
    KEEP -- poke --> SEN
    VER --> RISK --> SEN
    VER --> SEN
    ADP -. "peek(): valid?" .-> SEN
    VATP -. "spot" .-> SEN
    SEN == "file(ilk,'line',x): its ONLY write" ==> VATP
