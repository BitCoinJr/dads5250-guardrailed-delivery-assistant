# Recorded demonstration guide

Target: **nine minutes**, within the course's 8–10 minute requirement. Presenter: **Satoshi Nakamura, Solo**.

Use a functioning local app and show the actual interactions. Keep workflow figures brief so the recording gives enough time to CSV import, evidence, changes, validation and a human decision. Prepare the app and dependency environment before starting the screen recording.

## Before recording

1. Start `Run_Demo.cmd` and open the local Streamlit page.
2. Select the mode you will demonstrate. If you use sample mode, explicitly call it a deterministic demonstration and show its label. A claim about live AI generation requires a successful run in OpenAI mode.
3. Keep `inputs/sample_request.csv`, `inputs/ambiguous_request.csv` and `inputs/adversarial_requests.csv` ready. Use only the supplied synthetic data.
4. Keep the workflow and architecture figures from `../Design` available. Hide terminals or files that could reveal credentials, and never open `.env` on screen.
5. Run tests and the evaluation suite before recording. Keep the real output for the report; do not substitute planned or assumed numbers.

## Suggested sequence

| Time | What to show | Explanation |
| --- | --- | --- |
| 0:00–0:45 | Problem and one revenue request | Users already know Google Sheets. The assistant helps turn a request into a consistent, reviewable data change. |
| 0:45–1:30 | Workflow figure | Trace spreadsheet input to an approved patch. Point out the clarification loop, validation loop and future merge/release boundary. |
| 1:30–2:15 | Architecture figure | Explain Structured Output, repository RAG, LangGraph and controls enforced outside the model. |
| 2:15–3:00 | Import `sample_request.csv` | Show the actual upload or selection and the requested canceled-order policy. Confirm the acceptance criteria. |
| 3:00–4:00 | Generate and inspect evidence | Show the structured ticket, cited source paths, affected files and proposed plan. Explain why downstream tests/docs/BI must change together. |
| 4:00–5:15 | Diff and automated validation | Inspect the four proposed files and the validation outcomes. Explain expected revenue versus proposed revenue using the synthetic orders. |
| 5:15–6:00 | Clarification example | Import the ambiguous request. Show the pause and missing information. Add an explicit excluded status and acceptance criteria, then start a new run. |
| 6:00–6:30 | One adversarial request | Show a supplied instruction-override or secret-extraction request being blocked. Explain that this is one tested mitigation, not guaranteed prevention. |
| 6:30–7:30 | Human decision | Return to a validated run, inspect its diff/checks, enter a reviewer name, and approve it. Show the recorded decision and approved export. Explain rejection or revision without releasing anything. |
| 7:30–8:30 | Actual evaluation results and limits | Separate sample-mode measurements from live AI results. Discuss wrong or unclear requests, the small dataset, and the bounded change grammar. |
| 8:30–9:00 | Repository and reproducibility | Show README/setup instructions and the clean repository structure. End with the implemented MVP boundary and remaining stretch goals. |

The order of selecting runs depends on the interface. If the app shows one active run, reload the successful request for the approval portion rather than implying that a blocked or ambiguous request was approved.

## What to explain at the approval gate

- Tests provide evidence for a decision; passing checks does not execute a merge or release.
- The source repository is read-only. Proposed changes are applied only to the isolated run workspace for validation.
- The exported patch corresponds to the checked files and recorded decision. A changed request or requested revision creates a new run.
- Reviewer names are self-entered in this local demo. Production identity and permission controls are future work.

## Evidence for the technical report

Save a redacted successful run and a paused/blocked or failed run. Include the evaluation report's actual metrics and dependency versions. Discuss both the role of the model and the deterministic controls around it. A successful sample run proves the UI/workflow and validation path; it does not by itself prove the quality of the live OpenAI integration.

Use the workflow figure on the report's problem/scope page and the architecture figure on the following architecture page. Keep results separate from planned features. Before submission, check the ZIP includes the 8–10 minute recording, 4–6 page report, repository URL and clean reproducible source.
