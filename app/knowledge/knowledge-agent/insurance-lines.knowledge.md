# Knowledge: Insurance Lines & Products

---
domain: knowledge-agent
relates-to: [policy-terms, claims-process, underwriting]
---

## Entry: Personal Lines Overview

```yaml
id: personal-lines-overview
importance: 0.9
tags: [personal-lines, homeowners, auto, renters, umbrella, life, health]
connects-to: [commercial-lines-overview, specialty-lines-overview, deductible-definition, premium-definition]
```

Personal lines insurance covers individuals and families for their personal property and liability exposures. The major personal lines products are:

| Product | Covers | Common Forms |
|---------|--------|--------------|
| Homeowners | Dwelling, personal property, liability, loss of use | HO-3 (most common), HO-5 (open peril), HO-6 (condo) |
| Auto | Liability, collision, comprehensive, medical payments, UM/UIM | PAP (Personal Auto Policy) |
| Renters | Personal property, liability (not dwelling) | HO-4 |
| Umbrella | Excess liability above underlying auto/home limits | Typically $1M-$5M increments |
| Life | Death benefit to beneficiaries | Term, Whole Life, Universal Life |
| Health | Medical expenses, preventive care | HMO, PPO, HDHP |

Personal lines are typically filed and rated per-state, with each state's Department of Insurance (DOI) approving forms and rates.

---

## Entry: Commercial Lines Overview

```yaml
id: commercial-lines-overview
importance: 0.9
tags: [commercial-lines, general-liability, workers-comp, BOP, property, cyber, E&O]
connects-to: [personal-lines-overview, specialty-lines-overview, underwriting-process, claims-fnol]
```

Commercial lines insurance protects businesses against losses from liability, property damage, business interruption, and employee-related risks.

| Product | Covers | Key Considerations |
|---------|--------|-------------------|
| General Liability (CGL) | Third-party bodily injury, property damage, personal/advertising injury | ISO occurrence vs. claims-made forms |
| Workers' Compensation | Employee work injuries, occupational disease, lost wages | State-mandated, experience modification factor |
| Business Owner's Policy (BOP) | Bundled property + liability for small/mid businesses | Cost-effective, coverage limits apply |
| Commercial Property | Buildings, contents, business income/extra expense | Replacement cost vs. actual cash value |
| Cyber Liability | Data breaches, ransomware, regulatory fines, notification costs | First-party + third-party coverage |
| Professional Liability (E&O) | Errors, omissions, negligent professional services | Claims-made trigger, retroactive dates |

Commercial lines underwriting requires business classification (NAICS/SIC codes), loss history, revenue/payroll data, and operational risk assessment.

---

## Entry: Specialty Lines Overview

```yaml
id: specialty-lines-overview
importance: 0.7
tags: [specialty-lines, flood, earthquake, pet, travel, event, surplus]
connects-to: [personal-lines-overview, commercial-lines-overview, regulatory-compliance]
```

Specialty lines cover risks that standard markets decline or exclude:

- **Flood Insurance**: Primarily through NFIP (National Flood Insurance Program); private flood growing. Standard homeowners explicitly excludes flood.
- **Earthquake**: Separate policy or endorsement. Not covered under standard HO-3. California Earthquake Authority (CEA) is a major provider.
- **Pet Insurance**: Veterinary expenses, accident/illness coverage. Growing market segment.
- **Travel Insurance**: Trip cancellation, medical evacuation, baggage loss. Often underwritten by specialty carriers.
- **Event Insurance**: Liability and cancellation coverage for weddings, concerts, festivals. Short-term policies.
- **Surplus Lines**: Risks placed with non-admitted carriers when standard market capacity is unavailable. Requires surplus lines broker licensing.

---

## Entry: Coverage Triggers and Forms

```yaml
id: coverage-triggers
importance: 0.8
tags: [occurrence, claims-made, coverage-trigger, policy-forms, ISO]
connects-to: [commercial-lines-overview, personal-lines-overview, claims-fnol]
```

Insurance policies are triggered by different mechanisms depending on the form:

**Occurrence Form**: Coverage is triggered when the loss *occurs* during the policy period, regardless of when the claim is reported. Used for most personal lines (HO-3, PAP) and standard CGL policies. Advantage: long-tail coverage. Disadvantage: insurer carries tail risk.

**Claims-Made Form**: Coverage is triggered when the claim is *reported* during the policy period (and after the retroactive date). Used for professional liability (E&O), directors & officers (D&O), employment practices liability (EPLI), and cyber. Requires understanding of:
- **Retroactive date**: No coverage for acts before this date
- **Extended reporting period (ERP/tail)**: Extends time to report after policy expires
- **Prior acts coverage**: Covers acts before policy inception but after retroactive date

**ISO Forms**: The Insurance Services Office (ISO) provides standardized policy forms used by most carriers. Key forms: CG 00 01 (CGL occurrence), CG 00 02 (CGL claims-made), HO 00 03 (homeowners special form).

---

## Entry: Insurance Distribution Channels

```yaml
id: distribution-channels
importance: 0.6
tags: [distribution, agents, brokers, direct, insurtech, MGA]
connects-to: [personal-lines-overview, commercial-lines-overview, underwriting-process]
```

Insurance reaches consumers through multiple distribution channels:

| Channel | Description | Typical Lines |
|---------|-------------|---------------|
| Independent Agents | Represent multiple carriers, own their book of business | Personal + small commercial |
| Captive Agents | Represent a single carrier exclusively (State Farm, Allstate) | Personal lines primarily |
| Brokers | Represent the insured, shop across carriers | Large commercial, specialty |
| Direct/Online | Carrier sells directly to consumer (GEICO, Progressive Direct) | Auto, simple personal lines |
| MGA/MGU | Managing General Agent with delegated underwriting authority | Specialty, E&S lines |
| Insurtech | Technology-driven distribution (Lemonade, Root, Hippo) | Personal lines, niche commercial |

The choice of distribution channel affects commission structures (typically 10-20% for personal, 10-15% for commercial), servicing responsibilities, and claims reporting workflows.
