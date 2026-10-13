# RecallNest interface direction

The product is a personal reading and review workbench. Its distinctive device is a visible trail from a question to a distilled note and back to the original conversation. Use a small woven-nest wordmark, quiet document surfaces, and a source rail rather than a marketing hero or ornamental dashboard.

## Tokens

| Role | Value |
| --- | --- |
| Canvas | `#f3f7fa` |
| Reading surface | `#ffffff` |
| Navigation surface | `#eaf1f5` |
| Primary text | `#15344a` |
| Secondary text | `#526979` |
| Action | `#146b71` |
| Border | `#d7e3eb` |
| Warning | `#94611b` |

Typography: system Chinese sans-serif (`Segoe UI`, `Microsoft YaHei`, `PingFang SC`, sans-serif); 14px interface text, 16px reading text, 28px page title with deliberate weight and modest tracking. Long note content has a maximum reading width around 68ch and a 1.75 line height. Small metadata must remain legible at 12px.

## Layout

Desktop: a 220px sidebar containing six navigation entries, an unobtrusive header with global search/import/settings, and a main reading workspace. Detail screens add a narrow evidence rail with source/date/quote links. Content is left-aligned.

Mobile: a drawer navigation, full-width reading layout, single-column source sections, and wrapping controls. No fixed minimum width or horizontal viewport overflow.

## User flows

- Overview: real state summary, recent notes, next review and an obvious import action. Empty database presents import and clearly labeled synthetic examples.
- Knowledge: searchable document rows, compact filter controls, open detail with evidence, edit and favorite actions.
- Conversations: title/source/date list; readable messages; branch selector; new chat with context disclosure and model setup guidance.
- Projects: project selection, editable status and goals, linked conversations, knowledge and artifact URLs.
- Review: one question at a time; reveal answer; four named feedback buttons; source link; queue filters and pause/edit controls.
- My memory: readable grouped statements, status filters, confirm/edit/reject/expire actions and source/previous-state history.

Use one vocabulary across buttons, confirmations and errors. Data-derived numbers are actual API results. Busy states disable repeated submissions, failed states keep entered values, and empty states explain the next action.

## Preflight review

The visual device relates to the actual task: tracing how conversations become durable knowledge. Palette and typography support long reading rather than visual spectacle. Avoid unrelated photos, purple gradients, oversized vanity numbers and identical feature-card grids. Keyboard focus, reduced motion, labels, contrast and source readability are required.
