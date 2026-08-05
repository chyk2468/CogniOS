---
name: create-file-and-insert-content
description: Create file and insert content
version: 1.0.0
category: general
tags: [file management, text editing, tool usage, content manipulation]
status: published
confidence: 0.95
source: learned
owner: yash
created: "2026-08-02T05:17:13Z"
---

## When to Use

The user requested the creation of a text file and subsequently asked the agent to write specific content into it.

## Procedure

1. Use the write_file tool to create the desired file.
2. Identify the exact text that needs to be inserted or modified.
3. Use the edit_document tool with find/replace logic to update the file content.
4. Verify the final content of the file after the operation.

Use the write_file tool to create the initial file, followed by an edit operation to modify the contents.
