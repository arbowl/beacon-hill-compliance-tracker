# MA Rules - Simple User Guide
*How to Track Massachusetts Legislative Committee Compliance*

## What is this tool?

**MA Rules** is like a digital watchdog that automatically checks if Massachusetts legislative committees are following the rules. Think of it as a robot that visits the state legislature's website every day to see if committees are doing their homework on time.

## What does it check?

Massachusetts law says that committees must follow several rules when handling bills:

1. **Give proper notice**: Hearings must be announced at least **10 days** in advance
2. **Make decisions on time**: After a hearing, they have **60 days** to decide what to do with the bill (they can ask for one 30-day extension, making it 90 days total)
3. **Be transparent**: They must post summaries of what they decided and vote records showing how each member voted

The tool checks if committees are:
1. **Announcing hearings with adequate notice** (at least 10 days in advance)
2. **Making decisions on time** (within 60-90 days)
3. **Posting summaries** of what they decided
4. **Posting vote records** showing how each committee member voted

## What you'll get

After running the tool, you'll get two types of reports:

### 1. Easy-to-Read Web Page (HTML Report)
This looks like a simple table with columns showing:
- **Bill**: The bill number (like H103 or S29)
- **Hearing**: When the committee heard the bill
- **D60**: The 60-day deadline
- **Notice Gap**: How many days notice was given (or "Missing" if not found)
- **Reported?**: Whether the committee made a decision
- **Summary**: Whether they posted a summary
- **Votes**: Whether they posted vote records
- **State**: The overall compliance status
- **Reason**: Why it's compliant or not

**Color coding:**
- 🟢 **Green** = Everything is good (compliant, adequate notice)
- 🟡 **Yellow** = Partially good (unknown, missing notice data)
- 🔴 **Red** = Not following rules (non-compliant, insufficient notice)

### 2. Data File (JSON Report)
This is the same information but in a format that computers can easily read. You probably won't need this unless you're doing advanced analysis.

## How to use it (Super Simple Version)

### Step 1: Get the tool
1. Download the tool files to your computer
2. Look for a file called `app.exe` (this is the program you'll run)

_(Note: The person who distributed the files to you should ideally set `config.yaml` up with the right settings for you. If the software is behaving expectedly, ask them for help.)_

### Step 2: Run the tool
1. Double-click on `app.exe`
2. Wait for it to finish (it might take a long time depending on the number of bills to read)
3. Look in the `out` folder for your results

### Step 3: View your results
1. Open the `out` folder
2. Look for a file ending in `.html` (like `basic_J33.html`)
3. Double-click on it to open in your web browser
4. You'll see a table with all the compliance information

## Understanding the results

### What the columns mean:

**Bill**: The bill number. Click on it to go to the official bill page.

**Hearing**: The date the committee held a hearing on this bill.

**D60**: The 60-day deadline. Committees must decide by this date.

**Eff. Deadline**: The effective deadline (usually the same as D60, unless there was an extension).

**Notice Gap**: How many days advance notice was given for the hearing:
- **Green numbers** (like "15 days") = Adequate notice (10+ days)
- **Red numbers** (like "5 days") = Insufficient notice (less than 10 days) 
- **Yellow "Missing"** = No announcement found

**Reported?**: 
- **Yes** = The committee made a decision and moved the bill forward
- **No** = The committee hasn't decided yet

**Summary**: 
- **Yes** = The committee posted a summary of their decision
- **—** = No summary found

**Votes**: 
- **Yes** = The committee posted how each member voted
- **—** = No vote record found

**State**: The overall compliance status:
- **compliant** = Following all the rules
- **non-compliant** = Breaking the rules
- **unknown** = Partially following rules

**Reason**: Why it got that status:
- **"Reported out"** = Committee made a decision on time
- **"Partial: one of summary/votes missing after deadline"** = Committee decided but didn't post all required documents
- **"Not reported out after deadline"** = Committee didn't decide on time

## Real-world example

Let's say you see this in your results:

| Bill | Hearing    | D60        | Reported? | Summary | Votes | State   | Reason                                               |
|------|------------|------------|-----------|---------|-------|---------|------------------------------------------------------|
| H103 | 2025-04-09 | 2025-06-08 | No        | Yes     | —     | unknown | Partial: one of summary/votes missing after deadline |

This means:
- Bill H103 was heard on April 9, 2025
- The committee had until June 8, 2025 to decide
- The committee hasn't made a decision yet (Reported? = No)
- They posted a summary but no vote record
- Status is "unknown" because they're missing required documents

## What to do with the results

### For citizens:
- Use this information to hold your representatives accountable
- Share concerning results with local news or advocacy groups
- Contact committee members about bills that seem stuck

### For journalists:
- Look for patterns of non-compliance
- Investigate committees that consistently miss deadlines
- Use the data to write stories about legislative transparency

### For advocacy groups:
- Track specific bills you care about
- Identify committees that need pressure
- Use the data in reports and campaigns

## Troubleshooting

**"It's not targeting the right committee/bills"**
- You can change it by opening `config.yaml` in Notepad and editing the "committee_ids" line
- You can limit or expand the number of hearings by opening `config.yaml` in Notepad and editing the "limit_hearings" line

**"I don't see any results"**
- Check that the `out` folder was created
- Look for files ending in `.html` or `.json`
- The tool might still be running - wait a few more minutes

**"The results don't make sense"**
- Remember that some bills might be legitimately complex and need more time
- Check if the committee requested an extension
- Look at the "Reason" column for explanations

## Getting help

If you need help:
1. Check this guide first
2. Look at the technical README for advanced users
3. Contact the person who gave you this tool

## Why this matters

Massachusetts law requires committees to be transparent and timely. When they don't follow the rules:
- Bills get stuck in limbo
- Citizens can't see how their representatives voted
- The democratic process breaks down

This tool helps ensure that committees follow the rules and stay accountable to the people they serve.

---

*This tool was designed to be simple and accessible. You don't need to be a computer expert to use it - just follow these steps and you'll have valuable information about legislative compliance.*
