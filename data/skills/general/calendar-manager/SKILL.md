---
name: calendar-manager
description: Manages calendar events via the manage_calendar tool — list, create, update, delete events with recurrence, reminders, tags, and importance.
version: 2.0.0
category: general
tags: [calendar, schedule, event, planner, reminder, recurring, rrule]
status: published
confidence: 0.95
source: user
owner: yash
created: "2026-07-26T04:56:05Z"
---

## When to Use

Use when the user wants to create, view, update, delete, move, reschedule, duplicate, or search calendar events. Also use for recurring events, reminders/alarms, checking availability, or managing calendars.

Do NOT use for note/todo reminders without a calendar event — use `manage_notes` with `due_date` for standalone reminders.

## Procedure

### Step 1 — Resolve dates first

Before calling the tool, resolve ALL relative dates ("today", "tomorrow", "next Monday", "this weekend") against the **Current date and time** from the system context. Convert them to ISO 8601 strings in the user's local wall time. Example: if today is 2026-07-26 and user says "tomorrow at 3pm", pass `"2026-07-27T15:00:00"`.

### Step 2 — Pick the correct action

The `manage_calendar` tool accepts exactly **5 actions**:

| Action | Purpose | Required fields |
|---|---|---|
| `list_events` | Query events in a date range | `start`, `end` |
| `create_event` | Create a new event | `summary`, `dtstart` |
| `update_event` | Modify an existing event | `uid` + changed fields |
| `delete_event` | Delete an event | `uid` |
| `list_calendars` | List all calendars | *(none)* |

Short aliases `create`, `update`, `delete`, `list` are also accepted.

### Step 3 — Map complex requests to these actions

| User intent | How to handle |
|---|---|
| **Move/reschedule event** | `update_event` with new `dtstart` (and `dtend` if needed) |
| **Duplicate event** | `list_events` to read the original → `create_event` with copied data |
| **Add reminder/alarm** | `create_event` with `reminder_minutes` (e.g. `10` = 10 min before). Do NOT also call `manage_notes` — the calendar tool creates the Notes reminder automatically |
| **Search events** | `list_events` with `start`/`end` covering the search window, then filter results yourself |
| **Today's events** | `list_events` with start=today 00:00, end=today+1 00:00 |
| **This week's events** | `list_events` with start=Monday 00:00, end=next Monday 00:00 |
| **Check availability / conflicts** | `list_events` for the time range, then analyze gaps |
| **Create recurring event** | `create_event` with `rrule` in iCalendar RRULE format |
| **Delete single occurrence** | Not supported via tool — advise user to use calendar UI |
| **Remove recurrence** | `update_event` with `rrule: ""` (empty string) |

### Step 4 — Build the JSON payload

#### create_event
```json
{
  "action": "create_event",
  "summary": "Team standup",
  "dtstart": "2026-07-27T09:00:00",
  "dtend": "2026-07-27T09:30:00",
  "location": "Conference Room A",
  "description": "Weekly sync",
  "all_day": false,
  "calendar": "Work",
  "event_type": "work",
  "importance": "high",
  "reminder_minutes": 15,
  "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR"
}
```

**Field reference:**
- `summary` *(required)* — event title
- `dtstart` *(required)* — start time as ISO 8601 or natural language ("tomorrow at 1pm", "next monday 9am")
- `dtend` — end time; defaults to dtstart + 1 hour (or +1 day if all_day)
- `duration` — alternative to dtend: "1h", "30m", "1hr30m"
- `all_day` — boolean; when true, pass dtstart as YYYY-MM-DD
- `location` — event location
- `description` — event notes/body
- `calendar` — calendar name ("Personal", "Work") or ID; defaults to first calendar
- `event_type` — tag/category: work, personal, health, travel, meal, social, admin, other
- `importance` — low, normal (default), high, critical
- `reminder_minutes` — integer, minutes before event to fire a reminder (creates a Notes reminder automatically)
- `rrule` — iCalendar RRULE string for recurrence. Examples:
  - Weekly on Monday: `FREQ=WEEKLY;BYDAY=MO`
  - Daily for 10 days: `FREQ=DAILY;COUNT=10`
  - Monthly on the 1st: `FREQ=MONTHLY;BYMONTHDAY=1`
  - Every weekday: `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR`
  - **Do NOT use rrule for single occurrences** like "next Wednesday only"

#### list_events
```json
{
  "action": "list_events",
  "start": "2026-07-01T00:00:00",
  "end": "2026-07-31T23:59:59",
  "calendar": "Work"
}
```
- `start` — range start (ISO datetime). Also accepts: start_time, start_date, from, since
- `end` — range end (ISO datetime). Also accepts: end_time, end_date, to, until
- `calendar` — optional filter by calendar name or ID
- If start omitted, defaults to today 00:00. If end omitted, defaults to start + 14 days
- **Do NOT pass a loose `query` string** — resolve the date range yourself

#### update_event
```json
{
  "action": "update_event",
  "uid": "abc123-def456",
  "summary": "Updated title",
  "dtstart": "2026-07-28T10:00:00",
  "importance": "critical"
}
```
- `uid` *(required)* — event UID from list_events results
- All other fields are optional — only pass the ones being changed
- Pass `rrule: ""` to remove recurrence from a repeating event
- For recurring events, updating changes the entire series

#### delete_event
```json
{
  "action": "delete_event",
  "uid": "abc123-def456"
}
```
- `uid` *(required)* — event UID from list_events results

#### list_calendars
```json
{
  "action": "list_calendars"
}
```
Returns calendar names and IDs. **Call this first** before create/update/delete if you need to target a specific calendar.

### Step 5 — Link back to the calendar

After creating an event, use the returned `uid` to create a clickable markdown link:
`[Event Title](#event-<uid>)` — this opens the calendar and highlights the event day.

## Pitfalls

- Never invent missing information. Ask the user for clarification if required fields (summary, date) are missing.
- Do NOT pass unsupported actions like `move_event`, `search_events`, `find_free_slots`, `snooze_reminder` — the tool will return an error. Map them to the 5 supported actions.
- Do NOT create a `manage_notes` reminder AND pass `reminder_minutes` on the same event — that creates duplicate reminders.
- Do NOT pass `rrule` for single-occurrence events. Only use when the user explicitly wants recurrence.
- Do NOT hit `/api/calendar/events` via `app_api` — always use `manage_calendar`.
- Batch creation: you can pass `{"events": [{...}, {...}]}` to create multiple events at once.
- For all-day events, set `all_day: true` and pass dtstart as `YYYY-MM-DD`.
- Dates must be in the user's local time (ISO 8601). The tool handles timezone conversion internally.
