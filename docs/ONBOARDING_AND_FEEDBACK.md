# Onboarding and feedback

## First-run onboarding

The desktop tutorial uses a small anchored CustomTkinter card and highlights
real controls instead of duplicating the app interface. It explains Chrome
login, course import, checkbox selection, sync, and local AI Study Pack export.

`AppSettings` stores only `onboarding_completed_version` alongside the existing
last output directory. A missing or corrupt settings profile is treated as a
new profile and may show onboarding. A valid legacy settings file without this
field is migrated as already onboarded, so v1.1.4 users are not interrupted on
update. Completing or skipping persists the same harmless marker. Help can
replay the tutorial without resetting it.

## Feedback

The feedback dialog collects only user-entered type, title, and description,
then shows app version and operating system as read-only context. It never
collects course names, URLs, local paths, logs, credentials, cookies, session
data, or authentication headers automatically.

Selecting **Mở GitHub để gửi** opens a prefilled GitHub issue URL in the
browser. The user reviews and submits the issue on GitHub; the app does not
send a network request, use an API token, or create an issue itself. If the
browser cannot open, the dialog exposes a copyable prepared URL.
