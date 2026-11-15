# Recorded demonstration guide

The completed [timed English narration and Japanese recording checklist](final/DADS5250_Demo_Recording_Guide_Satoshi_Nakamura_Solo.pdf) accompanies the [six-page technical report](final/DADS5250_Final_Report_Satoshi_Nakamura_Solo.pdf). The actual MP4/MPEG recording remains to be produced.

Target **nine minutes**, within the course's 8–10 minute requirement. Presenter: **Satoshi Nakamura, Solo**.

The main story is a business request becoming a reviewed data change. Show the user's familiar sheet, the BA's discussion and selection work, the frozen delivery handoff, and the Data Engineer's final review. The normal recording does not need a CSV download/upload step.


## Section audio recording

Use the version 2 PDF or Word script linked above. Its nine recording sections use short sentences and bold main verbs. Record your own voice with Sound Recorder and start with `01_intro` so speaking pace can be checked before the remaining clips. Keep the original audio format. [Plain text scripts, pronunciation notes and instructions](final/Audio_Scripts/00_START_HERE_JA.txt) accompany the reading copy. Screen footage and English captions will be aligned to the actual supplied recordings; no final subtitle timestamps are claimed yet. The timeline below is a planning aid. Actual recorded speech determines the edit.

## Prepare before capturing the screen

1. Start `Run_Demo.cmd` and open **0 BA intake**.
2. Decide which source you can honestly demonstrate. **Google Sheets** is a direct private read and requires completed local OAuth setup. **Demo backlog** is an explicitly labeled synthetic local queue. Never describe the latter as a fresh live read.
3. Decide which generation mode you can demonstrate. **Sample walkthrough** uses explicit rules and templates. A claim about AI-generated estimates or proposals requires a successful **OpenAI API** run with real credentials.
4. If using the real private-sheet connection, follow `GOOGLE_SHEETS_SETUP_JA.md` and test **Refresh Google Sheets** before recording. The credentialed connection is not established by a mocked reader test.
5. Keep the Google Sheet's `Request backlog` tab ready. Use synthetic data only. The original `Requests` tab and CSV examples are advanced fallback material, not the main story.
6. Run the relevant tests and evaluation beforehand. Keep actual output and dependency versions for the report; do not substitute planned values or old counts.
7. Keep `.env`, `.secrets`, OAuth JSON and token files closed. Do not display credentials, authorization codes or account-setup details in the recording.

## Suggested sequence

| Time | Show | Explain |
| --- | --- | --- |
| 0:00–0:45 | The business problem | Marketing, EC and other users raise BI or data requests. A BA discusses the need, priority and desired timing before development starts. |
| 0:45–1:30 | The actual request backlog | Show the grouped columns, business requirement, BA notes, impact, priority, desired date and readiness. Explain that new requests can remain unestimated. |
| 1:30–2:45 | Refresh the source and estimate | Choose Google Sheets if OAuth is working, otherwise label Demo backlog clearly. Select **Estimate impact and change volume** and explain the four quadrants plus Needs estimation. |
| 2:45–3:30 | Repository evidence and BA Go | Open a ready revenue-policy request, inspect the estimate and cited dbt files, enter a BA rationale, confirm the review and select **Record BA decision** with Go. |
| 3:30–5:00 | Frozen handoff and delivery preparation | Show the immutable Jira-style request and BA decision ID. Select **Prepare and validate**, then inspect the structured ticket, repository evidence and affected-file plan. |
| 5:00–6:15 | Proposed diff and actual checks | Inspect SQL, test, documentation and BI changes. Show dbt/pytest results and expected versus proposed revenue derived from the synthetic order data. |
| 6:15–7:00 | Data Engineer approval and export | Review the evidence and checks, record the second human decision, and show the approved package becoming available. No production release is executed. |
| 7:00–8:00 | One realistic exception | Show an unready or unestimated request remaining Clarify/Hold, an out-of-scope request requiring scope review, or a changed source invalidating an old review. Explain how it returns to BA discussion. |
| 8:00–9:00 | Results, limitations and reproduction | Separate actual live results from sample results. Show setup instructions, test/evaluation evidence and the repository. State the current delivery boundary and remaining integrations. |

Keep the recording focused on one successful request and one exception. Avoid spending the entire time on diagrams or attempting every example. The current README contains concise workflow and architecture diagrams that can introduce the process before the actual interaction.

## Explain the two-axis estimate accurately

- **Business impact** comes from the business requirement, BA assessment and notes. A missing BA rating is unknown, not an invented middle score.
- **Change volume** is informed by the existing dbt assets and dependencies. For the bounded revenue policy, the app can compare canonical templates and count proposed SQL models, files and added/removed text lines.
- These are provisional scope estimates. A line delta is not a measured developer duration, a final generated patch or a promise of delivery effort.
- A new dashboard, source or extraction request can have low confidence or unknown file/model/line counts. Keep that uncertainty visible rather than inventing an estimate.
- Priority, desired timing and initial effort are secondary planning inputs. The rubric and AI ranking support the BA's discussion; they do not record Go automatically.

## Distinguish the two human gates

**BA Go** confirms that the request is ready and appropriate to start. The app rereads the source before the decision and freezes the reviewed requirement in a local receipt. The receipt is a Jira-style handoff, not a real Jira API call. The app does not write the decision back to the sheet.

**Data Engineer approval** reviews the prepared code, evidence and validation results. Passing tests makes review possible; it does not execute a merge or release. The exported package must match the checked proposal and the recorded decision.

If the requirement changes after Go, update the source and repeat BA intake. Do not imply that an edited field, a blocked request or an old Go authorized a different change. Reviewer names are self-entered local demonstration identities, not production authentication.

## Optional safety segment

If time permits, show one supplied synthetic attack through the advanced CSV fallback or a controlled test result. Explain that a pattern filter is one mitigation, not guaranteed prompt-injection prevention. Keep the normal business intake and two human decisions as the main story.

## Evidence for the report

Save a redacted triage review and BA receipt, a successful delivery review, and one paused/blocked/failed case. Explain which source and generation mode produced each record. Use measured evaluation outputs and dependency versions, not assumed success rates.

The existing labeled delivery evaluation checks its small set of revenue-policy cases and synthetic attacks. It does not by itself measure the quality of the new backlog ranking, the two-axis estimates or the live private Google connection. A successful synthetic workflow is useful engineering evidence but does not establish live AI quality.

Place the business workflow on the report's problem/scope page and the architecture on the following page. Discuss source-grounded estimates, the two separate human decisions, current limitations and reproducibility. Before submission, check the ZIP contains the 8–10 minute recording, 4–6 page report, repository URL and clean source snapshot, while excluding credentials and runtime clutter.
