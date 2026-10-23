# Knowledge: Policy Terms & Definitions

---
domain: knowledge-agent
relates-to: [insurance-lines, claims-process]
---

## Entry: Deductible

```yaml
id: deductible-definition
importance: 0.95
tags: [deductible, premium, out-of-pocket, cost-sharing, policy-terms]
connects-to: [premium-definition, coinsurance-definition, coverage-triggers, claims-fnol]
```

A **deductible** is the amount the policyholder pays out-of-pocket before insurance coverage begins. It is a form of cost-sharing that reduces moral hazard and keeps premiums lower.

**Types of deductibles:**
- **Per-occurrence deductible**: Applies each time a covered loss occurs (e.g., $1,000 per auto collision)
- **Annual/aggregate deductible**: Accumulates across multiple claims within the policy year (common in health insurance)
- **Percentage deductible**: A percentage of the insured value (common for hurricane/earthquake: 2-5% of dwelling value)
- **Split deductible**: Different deductibles for different perils on the same policy (e.g., $1,000 for wind, $500 for all other perils)

**Relationship to premium**: Higher deductible = lower premium (policyholder assumes more risk). A $1,000 deductible typically saves 15-25% on premium compared to a $250 deductible, depending on the line and territory.

**Deductible vs. elimination period**: In disability/long-term care, the equivalent concept is the "elimination period" (waiting days before benefits begin).

---

## Entry: Premium

```yaml
id: premium-definition
importance: 0.95
tags: [premium, rate, pricing, factors, underwriting]
connects-to: [deductible-definition, underwriting-process, coinsurance-definition, experience-modification]
```

The **premium** is the price paid for insurance coverage, typically expressed as an annual amount paid monthly, quarterly, semi-annually, or annually.

**Premium components:**
- **Pure premium (loss cost)**: Expected claims cost per exposure unit
- **Expense loading**: Carrier operating expenses (acquisition, servicing, overhead)
- **Profit and contingency**: Target return on capital + uncertainty buffer
- **Taxes and fees**: State premium taxes (typically 1.5-4%), regulatory fees

**Rating factors (personal auto example):**

| Factor | Impact | Why |
|--------|--------|-----|
| Driving record | High | Claims frequency prediction |
| Age/experience | High | Statistical loss correlation |
| Territory/ZIP | High | Local loss frequency/severity |
| Vehicle type | Medium | Repair cost, theft rate |
| Credit score | Medium | Correlates with loss frequency (where permitted) |
| Coverage limits | Medium | Exposure amount |
| Deductible chosen | Medium | Cost-sharing level |
| Annual mileage | Low-Medium | Exposure frequency |

**Premium audit**: For commercial policies (especially workers' comp and general liability), premiums are based on estimated payroll/revenue at inception. A premium audit at policy end adjusts the premium based on actual figures.

---

## Entry: Coinsurance

```yaml
id: coinsurance-definition
importance: 0.85
tags: [coinsurance, valuation, penalty, cost-sharing, commercial-property]
connects-to: [deductible-definition, premium-definition, commercial-lines-overview]
```

**Coinsurance** has two distinct meanings in insurance:

**1. Property coinsurance (commercial)**: A clause requiring the insured to carry coverage equal to a specified percentage (typically 80%, 90%, or 100%) of the property's value. If underinsured, a penalty reduces claim payments proportionally.

Formula: `Payment = (Coverage Carried / Coverage Required) × Loss - Deductible`

Example: Building worth $1M, 80% coinsurance, insured for $600K. Required: $800K.
- $100K loss: Payment = (600K/800K) × 100K = $75K (25% penalty for underinsurance)

**2. Health insurance coinsurance**: The percentage of costs shared between insurer and insured after the deductible. Example: 80/20 coinsurance means the insurer pays 80%, patient pays 20% until out-of-pocket maximum is reached.

---

## Entry: Subrogation

```yaml
id: subrogation-definition
importance: 0.8
tags: [subrogation, recovery, third-party, claims, liability]
connects-to: [claims-fnol, claims-settlement, deductible-definition]
```

**Subrogation** is the insurer's right to recover claim payments from the responsible third party after paying the insured's loss.

**Process flow:**
1. Insured suffers a loss caused by a third party
2. Insured's carrier pays the claim under the policy
3. Carrier "steps into the shoes" of the insured (subrogation right)
4. Carrier pursues recovery from the at-fault party or their insurer
5. If successful, the insured's deductible is reimbursed (proportionally or fully)

**Key principles:**
- Insurer cannot subrogate against its own insured
- Anti-subrogation clauses can waive recovery rights (common in commercial leases)
- Subrogation preserves the indemnity principle (insured shouldn't profit from a loss)
- Recovery is typically net of collection expenses

**Example**: Driver A (insured by Carrier X) is rear-ended by Driver B (insured by Carrier Y). Carrier X pays Driver A's repair ($5,000) and pursues Carrier Y for reimbursement through inter-company arbitration.

---

## Entry: Endorsement

```yaml
id: endorsement-definition
importance: 0.8
tags: [endorsement, rider, amendment, policy-modification, coverage-extension]
connects-to: [personal-lines-overview, commercial-lines-overview, coverage-triggers, premium-definition]
```

An **endorsement** (also called a rider or amendment) modifies the terms, conditions, or coverage of an insurance policy. Endorsements can add coverage, remove coverage, or change policy conditions.

**Common endorsement types:**

| Type | Purpose | Example |
|------|---------|---------|
| Coverage extension | Add perils or property not in base policy | Scheduled jewelry endorsement on HO-3 |
| Coverage restriction | Exclude specific perils or situations | Mold exclusion, animal liability exclusion |
| Limit modification | Increase or decrease sublimits | Increased water backup limit ($25K → $50K) |
| Condition change | Modify policy conditions | Additional insured endorsement (CG 20 10) |
| Mandatory | Required by state regulation | Uninsured motorist coverage in mandatory states |

**Additional insured endorsements** are critical in commercial insurance: they extend liability coverage to third parties (landlords, general contractors, certificate holders) who require evidence of coverage via Certificate of Insurance (COI).

---

## Entry: Experience Modification Factor

```yaml
id: experience-modification
importance: 0.7
tags: [experience-mod, workers-comp, rating, loss-history, NCCI]
connects-to: [premium-definition, commercial-lines-overview, underwriting-process, claims-fnol]
```

The **Experience Modification Factor (EMR/E-Mod)** adjusts workers' compensation premiums based on an employer's actual loss experience compared to the industry average.

- **E-Mod = 1.00**: Average loss experience for the classification
- **E-Mod < 1.00**: Better than average (premium discount)
- **E-Mod > 1.00**: Worse than average (premium surcharge)

**Calculation basis:**
- Uses 3-year loss history (excluding current + most recent year)
- Splits losses into "primary" (first $5K-$18K per claim, weighted heavily) and "excess" (remainder, weighted less)
- Frequency matters more than severity: five $10K claims hurt more than one $50K claim
- Administered by NCCI (most states), or state-specific bureaus (CA, NY, PA, etc.)

**Impact example**: A contractor with $100K base workers' comp premium:
- E-Mod 0.80 → Pays $80K (20% savings from good safety record)
- E-Mod 1.35 → Pays $135K (35% surcharge from poor loss history)

E-Mod is a key competitive factor: it affects bid eligibility (many GCs require E-Mod ≤ 1.00) and directly impacts profitability.
