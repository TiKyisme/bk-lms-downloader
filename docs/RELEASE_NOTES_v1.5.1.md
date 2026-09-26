# BK-LMS Downloader v1.5.1

## Fixed progress reporting

Synchronization no longer reaches 100% while later courses are still running.

For a two-course batch:

- course 1 completion = 50%
- course 2 active = between 50% and less than 100%
- final completion = 100%

AI Study Pack preparation now reports granular real-work progress across source
processing, Coursewave enrichment, optimization, validation, and final archive
work. Completed-course counts represent completed courses only.

## No behavior change to Study Pack retention

The v1.5.0 AI Study Pack size-budget and Coursewave exam policies remain
unchanged.

## Privacy

AI Study Pack preparation remains local and no telemetry or cloud AI upload was
introduced.
