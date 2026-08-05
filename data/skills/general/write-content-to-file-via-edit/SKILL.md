---
name: write-content-to-file-via-edit
description: Write content to file via edit
version: 1.0.0
category: general
tags: [file_management, text_editing, tool_usage, write_file]
status: published
confidence: 1.0
source: learned
owner: yash
created: "2026-08-02T05:16:20Z"
---

## When to Use

The user needed to create a file and then write specific content into it.

## Procedure

1. Use the write_file tool to create the target file.
2. Use the edit_document tool with FIND to locate existing text (or a placeholder).
3. Use the REPLACE command to substitute the existing text or insert the new content.
4. Specify the exact text that needs to be inserted/modified.
5. Use END to conclude the document editing operation.

Create the file first, then use the edit tool with FIND and REPLACE operations to insert the desired text.
