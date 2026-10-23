# Knowledge: Claims Process & Workflow

---
domain: knowledge-agent
relates-to: [policy-terms, insurance-lines, underwriting]
---

## Entry: FNOL - First Notice of Loss

```yaml
id: claims-fnol
importance: 0.9
tags: [FNOL, claims, first-notice, reporting, intake, loss-report]
connects-to: [claims-investigation, claims-settlement, deductible-definition, coverage-triggers]
```

**First Notice of Loss (FNOL)** is the initial report of a claim from the insured (or a third party) to the insurance carrier. FNOL sets the entire claims process in motion.

**FNOL intake captures:**
- Policyholder identification and policy number
- Date, time, and location of loss
- Description of what happened (narrative)
- Parties involved (for liability claims)
- Extent of damage or injury (initial estimate)
- Police/fire report numbers if applicable
- Witness information

**FNOL channels:**
- Phone (24/7 claims center)
- Online portal / mobile app
- Agent-reported (agent calls on behalf of insured)
- Third-party administrators (TPA) for self-insured programs

**Time sensitivity**: Most policies require "prompt" notice (not a specific deadline). However, late reporting can prejudice coverage if the insurer's ability to investigate is impaired. Claims-made policies have strict reporting deadlines.

**Coverage verification**: Upon FNOL, the claims handler immediately verifies: Is there an active policy? Does the loss fall within the policy period? Is the peril covered? Does an exclusion apply? Is the deductible met?

---

## Entry: Claims Investigation

```yaml
id: claims-investigation
importance: 0.85
tags: [investigation, adjuster, evidence, fraud, SIU, field-inspection]
connects-to: [claims-fnol, claims-settlement, subrogation-definition, claims-reserves]
```

After FNOL, the claims investigation determines the cause, extent, and validity of the loss.

**Investigation types:**

| Method | When Used | Conducted By |
|--------|-----------|--------------|
| Desk adjustment | Small, clear-cut claims (<$5K) | Inside adjuster |
| Field inspection | Moderate to large losses, complexity | Field adjuster or independent adjuster |
| SIU referral | Fraud indicators, suspicious circumstances | Special Investigations Unit |
| Engineering/expert | Structural damage, cause & origin (fire) | Forensic engineers, fire investigators |
| IME/peer review | Injury disputes, medical necessity | Independent Medical Examination physician |

**Red flags triggering SIU referral:**
- Claim filed shortly after policy inception or increase
- Prior claim history (frequent filer)
- Insured financial stress (recent bankruptcy, foreclosure)
- Inconsistent statements or uncooperative behavior
- Loss exceeds coverage amount (overinsurance)
- Staged accident indicators (pattern of soft-tissue-only claims)

**Documentation standards**: All investigation findings must be documented in the claim file with dates, source attribution, and relevance to coverage determination.

---

## Entry: Claims Reserves

```yaml
id: claims-reserves
importance: 0.8
tags: [reserves, IBNR, case-reserve, actuarial, financial, loss-reserve]
connects-to: [claims-investigation, claims-settlement, claims-fnol, experience-modification]
```

**Claims reserves** are the estimated future cost of claims that have been reported but not yet paid (case reserves) plus claims that have occurred but not yet been reported (IBNR).

**Reserve types:**
- **Case reserve**: Set by the claims adjuster for each known open claim based on expected ultimate cost
- **IBNR (Incurred But Not Reported)**: Actuarial estimate of claims that have occurred but haven't been reported yet
- **Bulk reserve**: Additional reserve above case reserves to account for development (claims getting more expensive over time)
- **ALAE/ULAE**: Allocated and unallocated loss adjustment expenses (investigation, legal, adjuster costs)

**Reserve adequacy** impacts carrier financials:
- Under-reserving → Future surprise deterioration, regulatory action
- Over-reserving → Depresses current profitability, potential tax implications
- Regulatory scrutiny: State DOIs examine reserve adequacy annually

**Loss development**: Claims rarely settle at initial reserve. Development factors (from actuarial triangles) project ultimate cost. Long-tail lines (workers' comp, medical malpractice) develop over 5-10+ years.

---

## Entry: Claims Settlement

```yaml
id: claims-settlement
importance: 0.85
tags: [settlement, payment, ACV, replacement-cost, negotiation, release]
connects-to: [claims-investigation, claims-fnol, deductible-definition, subrogation-definition, coinsurance-definition]
```

**Claims settlement** is the final resolution of a claim through payment, denial, or negotiation.

**Valuation methods:**

| Method | Definition | Common Use |
|--------|-----------|------------|
| Actual Cash Value (ACV) | Replacement cost minus depreciation | Auto total loss, older property |
| Replacement Cost Value (RCV) | Cost to replace with like kind/quality, no depreciation | Homeowners (most HO-3 policies) |
| Agreed Value | Pre-agreed amount at policy inception | Fine art, classic cars, scheduled items |
| Functional Replacement | Cost to replace with functionally equivalent (not identical) | Older commercial buildings |

**Settlement process:**
1. Coverage confirmed and liability determined
2. Damages documented and valued
3. Deductible applied
4. Coinsurance calculated (if applicable)
5. Settlement offer presented to insured/claimant
6. Negotiation (if disputed)
7. Release/settlement agreement signed
8. Payment issued

**Payment timing regulations**: Most states mandate timely payment (typically 30 days after proof of loss is submitted and accepted). Unfair Claims Settlement Practices Acts penalize unreasonable delays.

**Denied claims**: If coverage is denied, the carrier must issue a written denial letter citing the specific policy language and exclusion. Insured has the right to appeal, invoke appraisal clause, or pursue litigation.

---

## Entry: Underwriting Process

```yaml
id: underwriting-process
importance: 0.85
tags: [underwriting, risk-assessment, selection, pricing, binding, declination]
connects-to: [premium-definition, experience-modification, commercial-lines-overview, personal-lines-overview, distribution-channels]
```

**Underwriting** is the process of evaluating, selecting, and pricing risks to ensure an adequate and profitable book of business.

**Underwriting workflow:**
1. **Submission received** — Application with exposure data from agent/broker
2. **Risk assessment** — Evaluate hazards (physical, moral, morale), loss history, financial condition
3. **Classification** — Assign risk class/code (ISO, NAICS/SIC, territory)
4. **Pricing** — Apply rates, credits/debits, schedule rating, experience mod
5. **Decision** — Accept, decline, or counter-offer with conditions/exclusions
6. **Binding** — Issue binder (temporary evidence of coverage pending policy issuance)
7. **Policy issuance** — Full policy documents with declarations, forms, endorsements

**Underwriting guidelines** (appetite): Each carrier defines which risks it will write, at what limits, in which territories, and under what conditions. Risks outside appetite are declined or referred to surplus lines.

**Key underwriting tools:**
- Credit-based insurance scores (where permitted by state)
- Loss runs from prior carriers (5-year history)
- Inspections (physical site review)
- MVR (Motor Vehicle Reports) for auto
- CLUE reports (Comprehensive Loss Underwriting Exchange)
- Financial statements (commercial risks)

---

## Entry: Regulatory Compliance

```yaml
id: regulatory-compliance
importance: 0.7
tags: [regulation, DOI, compliance, market-conduct, filing, NAIC]
connects-to: [underwriting-process, claims-settlement, personal-lines-overview, commercial-lines-overview, specialty-lines-overview]
```

Insurance is regulated primarily at the **state level** in the United States (McCarran-Ferguson Act, 1945). Each state's Department of Insurance (DOI) oversees carriers operating in its jurisdiction.

**Regulatory areas:**

| Area | What DOI Regulates | Consequences of Non-Compliance |
|------|-------------------|-------------------------------|
| Rate filings | Premium rates must be filed and often approved before use | Fines, required refunds, license action |
| Form filings | Policy forms must be filed (and often approved) | Withdrawal of form from market |
| Market conduct | Fair underwriting, claims handling, advertising | Consent orders, fines, license suspension |
| Solvency | Capital adequacy, reserve adequacy, reinsurance | Receivership, rehabilitation, liquidation |
| Producer licensing | Agents/brokers must be licensed per state per line | Fines, license revocation, E&O exposure |
| Consumer complaints | Must respond to DOI inquiries within deadlines | Penalties, increased scrutiny |

**NAIC (National Association of Insurance Commissioners)**: Develops model laws, accredits state regulators, maintains databases (SERFF for filings, UCAA for company licensing). Not a federal regulator — states adopt NAIC models voluntarily.

**Key regulations impacting claims**: Unfair Claims Settlement Practices Act (model), prompt payment statutes, bad faith standards (first-party and third-party), appraisal clauses.
