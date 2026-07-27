---
name: schedule-event-using-calendar-tool
description: Schedule event using calendar tool
version: 1.0.0
category: general
tags: [calendar, scheduling, tool use, date handling]
status: published
confidence: 1.0
source: learned
owner: yash
created: "2026-07-26T04:24:58Z"
---

## When to Use

The user requested to add a meeting to their calendar, requiring the assistant to extract the time and create a structured tool call.

## Procedure

1. Identify the core intent: scheduling an event.
2. Prompt the user for missing details (e.g., time).
3. Extract the specified time information from the user's response.
4. Format the extracted data into the required tool action structure.
5. Execute the appropriate tool call to modify the calendar.

Identify the required information (event summary and start time) from the user and translate it directly into the appropriate function call format.
