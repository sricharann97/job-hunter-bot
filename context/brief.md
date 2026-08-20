# Project Brief — Hyderabad Accounting Job Alerts
















## Candidate profile
















| Field | Value |
| --- | --- |
| Name | Aadirala Sri Charan |
| Education | B.Com, Osmania University (6th-semester results pending); pursuing MBA via OU DDE |
| Location | Hyderabad, Telangana, India |
| Certifications | Complete Course for Accountants (AA/CERT/15081341); Tally ERP 9 with GST (GEENI, Grade A); MS-Office Diploma (Grade A) |
| Skills | Tally ERP 9, GST, TDS, MS Excel, MS Word, MS PowerPoint |
| Languages | English, Telugu, Hindi |
| Email | aadiralasricharan@gmail.com |
















## Target keywords
















Accounts Exe
Enter file contents here
cutive, Accounts Assistant, Junior Accountant, Accountant Trainee, Tally Operator, GST Assistant, GST Executive, TDS Assistant, Tax Assistant, Billing Executive, Data Entry Operator (Accounts), Finance Assistant, Bookkeeper, Back Office Executive (Finance/Accounts), MIS Executive (Entry Level)








## Filters








- **Location:** Hyderabad / Secunderabad / Telangana only. Exclude out-of-India remote roles.
- **Experience:** Fresher / 0–2 years
- **Salary:** Any (include even if not mentioned)
- **Job type:** Full-time, Part-time, Internship with stipend, Contract








## Architecture








1. **Hunter bot(`job-hunter-bot` repo): GitHub Actions cron every 3 hours; Python script fetches LinkedIn (public guest search) and other boards; deduplicates against `job_tracker_state.json`; filters to Hyderabad; sends Telegram alerts (12-job chunks) and commits state to repo
2. **Auto-apply run**: Weekdays 9:00 AM IST; scans for new matches; cold emails via Gmail with resume; WhatsApp drafts when phone numbers are published; portal links collected for manual apply; updates Notion + Google Sheets; Telegram summary
3. **Evening report**: Daily 9:00 PM IST Telegram summary (new matches, application status, next-day priorities)
4. **Trackers**: Notion DB `4b339305-a3d9-47d4-8fe0-a8b89cc9f666` (collection `collection://6bfb694d-4c86-4bde-b09a-56f25b0b1250`); Google Sheet `1msxG0oXEsO_JSZJbC-QicRQBPEhNe0WF5hLMmVuK-sI` (Applications tab)
5. **Alerts delivery**: Telegram bot token/chat stored as GitHub secrets in `job-hunter-bot` (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)


## Rules


- Always mention "B.Com fresher, awaiting 6th-semester results" in applications
- Never apply twice to the same company + role
- Only use contact emails found on company pages or job postings — never fabricated
- WhatsApp applications require the user's phone (QR scan on WhatsApp Web)
