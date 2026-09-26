# BK-LMS Downloader v1.5.0

## Highlights

- Smoother synchronization progress
- Smaller AI Study Packs
- Smarter Coursewave exam retention

## AI Study Pack improvements

Large packs now receive a compact budget pass only when safe omission of
lecturer-binary copies is needed. Markdown, retrieval chunks, and chapters
remain the primary textual representation, while explicit retention decisions
record any omitted binary representation. Smaller packs remain unchanged.

As one real validation example, GE1013 changed from 275.7 MB to 91.1 MB.
This is an example of the safety budget in action, not a guaranteed compression
ratio for every course.

## Sync progress

Progress advances during the active course and contributes current-course work
to the batch percentage. Processing course 3/3 does not count as complete until
that course finishes. Cancellation preserves the actual achieved progress.

## Coursewave

Historical exam material is retained representatively: at most 2 Midterm exams,
2 Final exams, 4 exams total, and 15 MiB of retained exam binaries.

## Privacy

AI Study Pack preparation remains local. No AI or cloud API is required for
pack preparation, and no telemetry or automatic upload is introduced.
