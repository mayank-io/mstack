# Template: PG Gyaan Market Predictions

This template is for videos from the PG Gyaan YouTube channel, which provides astrology-based gold/silver/stock market predictions in Hindi.

## Channel Matching

Match this template when channel name contains:
- "pg gyaan"
- "pggyaan"
- "pg ज्ञान"

## Whisper Settings

For this Hindi channel, use:
- **model:** medium (or large for better quality)
- **language:** hi (Hindi)

## Frontmatter

```yaml
---
title: "{{title}}"
author:
  - "[[@PG Gyaan]]"
duration: "{{duration}}"
published: {{published_date}}
source: {{url}}
image: {{thumbnail_url}}
created: {{created_date}}
channel: pg gyaan
tags:
  - videos
  - youtube
  - inbox
  - clippings
  - gold
  - silver
  - astrology
  - commodities
  - india
  - market-prediction
categories:
  - "[[Clippings]]"
---
```

## Summary Structure

For market prediction videos, structure themes as:

### Theme 1: Historic Events / Recent Market Analysis
- What happened recently in the market
- Causes attributed (planetary movements, etc.)
- Reference to previous predictions

### Theme 2: Week/Period Prediction (with IST→PST table)

**IMPORTANT:** This is the key differentiator for this template.

Include timezone note:
```markdown
> **Timezone:** IST (UTC+5:30) → PST (UTC-8). IST trading day (9am-11:30pm) = PST previous evening 7:30pm through next morning 10am.
```

Create a two-column table with complete predictions:

```markdown
| IST Prediction | PST Prediction |
|----------------|----------------|
| [[YYYY-MM-DD|Mon D]]: Prediction details | [[YYYY-MM-DD|Mon D]] time → [[YYYY-MM-DD|Mon D]] time: Prediction |
```

**Timezone Conversion Rules:**
- IST 9:00am = PST 7:30pm (previous day)
- IST 11:30pm = PST 10:00am (same day)
- IST 1:25pm = PST 11:55pm (previous day)
- IST 9:00pm = PST 7:30am (same day)
- IST 1:54pm = PST 12:24am (same day)

**Date Linking:**
- ALL dates must be wikilinks to daily notes
- Format: `[[YYYY-MM-DD|Mon D]]` (e.g., `[[2026-02-01|Feb 1]]`)
- Include both IST and PST date links

### Theme 3: Overall Outlook
- Monthly/period summary
- Gold vs Silver outlook comparison
- Physical holders vs traders advice

### Theme 4: Strategy Recommendations
- When to book profits
- When to buy/accumulate
- Risk warnings and disclaimers

## Key Data Points Table

```markdown
## Key Data Points

| Metric | Value | Context |
|--------|-------|---------|
| Historic fall date | [Date] | What happened |
| Bullish window | [Date range] | Trading opportunity |
| Profit booking deadline | [Date] | Last day to exit longs |
| Bearish period | [Date onwards] | When to avoid |
| Key timing | [Time IST → PST] | Planetary change |
```

## Notable Quotes

Include original Hindi quotes with English translation:

```markdown
## Notable Quotes

> "Hindi quote here"
> (English translation)

> "Another Hindi quote"
> (English translation)
```

## Predictions Summary

Numbered list with date-linked predictions:

```markdown
## Predictions Summary

1. **[[YYYY-MM-DD|Mon D]]** — Prediction
2. **[[YYYY-MM-DD|Mon D]]-[[YYYY-MM-DD|Mon D]]** — Prediction for range
3. **After [[YYYY-MM-DD|Mon D]]** — What happens next
```

## Body Structure

```markdown
# Summary: {{title_cleaned}}

**Speaker:** PG Gyaan
**Basis:** Indian astrology / Vedic Jyotish predictions
**Disclaimer:** This is astrology-based prediction, not financial advice

---

## Core Themes

### Theme 1: [Recent Event/Historic Fall]
- What happened
- Planetary cause (Guru/Jupiter, Mangal/Mars movements)
- Previous prediction accuracy

### Theme 2: Week Prediction ([Date Range])

> **Timezone:** IST (UTC+5:30) → PST (UTC-8). IST trading day (9am-11:30pm) = PST previous evening 7:30pm through next morning 10am.

| IST Prediction | PST Prediction |
|----------------|----------------|
| [[YYYY-MM-DD|Date]]: Prediction | [[YYYY-MM-DD|Date]] time → [[YYYY-MM-DD|Date]] time: Prediction |

### Theme 3: [Month] Overall Outlook
- Gold outlook
- Silver outlook
- Physical holders advice

### Theme 4: Strategy Recommendations
- Profit booking deadline
- Re-entry points
- Risk management

## Key Data Points

| Metric | Value | Context |
|--------|-------|---------|

## Notable Quotes

> "Hindi quote"
> (English translation)

## Predictions Summary

1. **Date** — Prediction

---

# About

![{{title}}]({{url}})

# Description

{{description}}

---

# Transcript (Hindi - Whisper {{whisper_model}} Model)

[Full Hindi transcript from Whisper]
```

## Post-Processing Checklist

1. **Date Wikilinks:** Convert ALL date references to `[[YYYY-MM-DD|Display]]` format
2. **Timezone Table:** Ensure IST predictions have corresponding PST predictions
3. **Daily Note Links:** Every date in prediction table should link to daily note
4. **Hindi Preservation:** Keep original Hindi in quotes section
5. **Speaker Link:** Author should be `[[@PG Gyaan]]`
6. **Tags:** Include: gold, silver, astrology, commodities, india, market-prediction

## Example Output

See: `Clippings/Gold Silver Next Week Prediction (Feb 2-6, 2026) - PG Gyaan.md` for reference implementation.
