# Signal Forge working instructions

Read: README.md, ARCHITECTURE.md, docs/decisions/ADR-execution-layer.md.

Preserve deterministic research and risk logic, paper-only execution boundaries, kill switches and operator arming. Read the execution ADR before touching execution. Never use live credentials or market-provider calls in CI. Large docs/research outputs are evidence; load only named results relevant to the question.

Start with the listed entry points and `devkit context` if available (or read .toolkit.json).
Use rg for scoped text searches and ast-grep for code structure. Read matching sections,
not whole trees. Run focused tests after edits; use full gates for broad changes.
`devkit run -- <command>` keeps complete local logs and prints a bounded tail, preserving
exit status. Read full failures when needed. Do not hide a failed check or claim token
savings without measurement. Keep generated outputs, private state, credentials and
.toolkit-runs out of commits. Shared tools: https://github.com/louisbrailey/developer-toolkit.
