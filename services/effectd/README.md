# effectd

Effect delivery daemon. Picks up pending trigger firings and action executions
and delivers them via pluggable executors (notify/Gotify, webhook). Applies the
trust ladder (approval → auto → dry-run) and the legacy nag policy for
zero-config notifications.

## Full documentation

- [Actions and trust ladder](../../docs/concepts/actions-and-trust.md)
- [Configuration reference](../../docs/reference/configuration.md)
- [Entry points reference](../../docs/reference/entry-points.md)
