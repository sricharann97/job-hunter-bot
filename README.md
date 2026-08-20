# job-hunter-bot

Job alert bot for Hyderabad accounting/finance fresher roles.

## What this repo does

- `job_hunter.py` scans LinkedIn and Indeed for Hyderabad accounting jobs, filters for Hyderabad/India-only fresher roles, deduplicates against `seen_jobs.json`, and sends Telegram alerts.
- GitHub Actions runs it every 3 hours (8x/day), commits updated `seen_jobs.json`.
- A daily weekday 9 AM IST Manus schedule applies to matching jobs by cold email (resume attached), drafts WhatsApp messages, lists portal links, and updates the Notion + Google Sheets trackers. A 9 PM IST schedule sends the evening report on Telegram.

## Candidate profile

Aadirala Sri Charan — B.Com fresher (6th-semester results awaited), Osmania University, Hyderabad. Tally ERP 9 with GST, TDS, MS-Office certified. Target roles: Accounts Executive/Assistant, Junior Accountant, Tally Operator, GST/TDS Assistant, Billing Executive, Bookkeeper.

## Workspace (Claude + Manus collaboration)

This repo is the shared memory for the job hunt. Claude refines strategy in `context/` and `drafts/`; Manus executes — scraping, applying, tracking — storing findings in `research/` and outputs in `deliverables/`.

| Folder | Purpose | Owner |
| --- | --- | --- |
| `context/` | Project brief: keywords, location, candidate profile, architecture | Claude / Manus |
| `research/` | Job-board findings and company contacts gathered by Manus | Manus |
| `drafts/` | Working drafts: email templates, interview prep, README copy | Claude / Manus |
| `deliverables/` | Finished outputs: resume versions, reports, tracker exports | Manus |

## Quick start

New idea for what to track? Edit `context/brief.md`. Need real market data? Check `research/`. New resume or report? Place it in `deliverables/`.
