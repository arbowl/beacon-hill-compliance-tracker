# **Plain-English Description of the Compliance Logic for the 194th Session**

This compliance system evaluates a bill’s committee process using four independent rules:

1. **Advance Notice** (for Senate and Joint committees only)
2. **Deadline / Reported-Out Requirement**
3. **Vote Posting**
4. **Summary Posting**

Each rule evaluates one requirement and returns its own result.
The system then aggregates them into a final compliance state.

---

# 1. **Advance Notice Requirement**

**Who it applies to:**

* Senate committees
* Joint committees
* Not applied to House committees

**What it checks:**
Whether the hearing was announced far enough in advance.

* Senate committees require **5 days’ notice**
* Joint committees require **10 days’ notice**
* House committees require **0 days** and therefore this rule is skipped
* Hearings announced before **June 26, 2025** are automatically exempt (requirement = 0 days)

**Outcomes:**

* **Insufficient notice -> Automatic Non-Compliance**
  Notice failures are *deal-breakers*. No other rules are considered.

* **Missing announcement or hearing date -> Special Handling**
  The system checks for other evidence:

  * If *nothing else* shows the bill moved, the result is **Unknown**
  * If other evidence exists, the bill becomes **Non-Compliant** (missing notice)

* **Sufficient notice or exemption -> Contributes descriptive text to the final reason**
  (e.g., “adequate notice (7 days)”)

---

# 2. **Deadline / Reported-Out Requirement**

This rule determines whether the committee acted on the bill by its deadline.

### **Deadlines**

* **House bills:**

  * 60 days after the hearing
  * Up to 90 days if extended
* **Senate bills:**

  * The session’s Wednesday deadline
  * Up to 30 days extension

### **Key behaviors**

* If the bill was **formally reported out on time**, the requirement is satisfied.

* If the bill is **not marked as reported out**, but **votes are posted**, the system assumes action occurred and marks this requirement as satisfied.
  This covers cases where committees fail to enter a reported-out event but votes confirm that action happened.

* If evidence is missing but *today is still before the deadline*, the result is **Unknown** and the system returns **UNKNOWN** overall, with a reason like:
  “Before deadline, adequate notice (7 days)”

* If the deadline has passed and there is **no reported-out date and no votes**, the requirement fails and contributes:
  **“not reported out by deadline YYYY-MM-DD”**

This is one of the three **core requirements**.

---

# 3. **Summary Requirement**

A bill must have a summary posted.

* If present -> the requirement is satisfied.
* If missing -> contributes “no summaries posted” to the final reason.

This is a **core requirement**.

---

# 4. **Vote Requirement**

Committee votes must be posted.

* If present -> the requirement is satisfied.
* If missing -> contributes “no votes posted” to the final reason.

This is a **core requirement**.

---

# 5. **Aggregation Logic (Final Output)**

After all rules run (except when a notice failure short-circuits):

### **A. If there is no hearing date**

The system cannot evaluate deadlines:
-> **UNKNOWN** with reason:
“No hearing scheduled – cannot evaluate deadline compliance”

### **B. If a deal-breaker occurred**

* Currently only notice failures qualify
  -> **NON-COMPLIANT**, using the notice rule’s reason

### **C. If still before the deadline**

* Determined by the Deadline rule
  -> **UNKNOWN**, with reason built from

  * “Before deadline”
  * * any notice description

### **D. Otherwise, count core requirements**

Core requirements are:

1. Reported-out / deadline requirement
2. Votes posted
3. Summaries posted

* **If all three are satisfied -> COMPLIANT**
  Reason:
  “All requirements met: reported out, votes posted, summaries posted”

* **If one or more are missing -> NON-COMPLIANT**
  Reason begins with:
  “Factors: …” listing the missing items, e.g.:

  * “no votes posted”
  * “no summaries posted”
  * “not reported out by deadline 2025-12-03”

  Followed by any notice description (if applicable).

---

# 6. **Special Clarifications**

### **Missing Notice vs. Insufficient Notice**

* **Insufficient notice** (not enough days):
  -> Immediate **NON-COMPLIANT** (deal breaker)

* **Missing notice data** (no announcement or hearing date):
  -> Special handling, may be **UNKNOWN** or **NON-COMPLIANT** depending on other evidence

### **Votes can substitute for missing “reported out”**

This is *not* forgiveness of lateness.
It is only a fallback when **metadata is missing** but **action is evident**.

### **Only core requirements affect COMPLIANT vs NON-COMPLIANT**

Notice only affects the **reason**, unless it fails or is missing and triggers special handling.
