# Step 1-2 Reliability Plan

1. Tighten source identity checks in `scripts/step2_run_import.py`: require the run-date token for dated QuickBI/JYCM files and accept an exact backup receipt only when file contents match.
2. Reconcile every order/sub-order key from today's Tmall order backups against `dunhill_bi订单源` before Step 2 can succeed.
3. Propagate uploader, download-process, and download-timeout failures from the shared `data-import` execution path.
4. Version the orchestrator success contract so legacy success state cannot skip validation, and only notify after both Step 1 and Step 2 satisfy the current contract.
5. Add focused regression tests, run both repositories' full test suites, compile checks, diff checks, and a read-only current-data validation. Do not execute the workflow or macOS Steps 3-5.
