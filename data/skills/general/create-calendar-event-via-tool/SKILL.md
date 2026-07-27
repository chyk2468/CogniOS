---
name: create-calendar-event-via-tool
description: Create calendar event via tool
version: 1.0.0
category: general
tags: [tool use, calendar management, intent recognition, API call]
status: published
confidence: 1.0
source: learned
owner: yash
created: "2026-07-26T08:53:04Z"
---

## When to Use

The user requested a meeting be added to the calendar using natural language.

## Procedure

1. Identify the intent: scheduling a new event.
2. Extract necessary details from the user request (participants, time).
3. Format the extracted data into the required JSON structure for the manage_calendar tool.
4. Call the appropriate tool with the structured parameters.
5. Confirm successful action execution to the user.

Call the manage_calendar tool with an 'create' action, a descriptive summary, and the calculated start time.
