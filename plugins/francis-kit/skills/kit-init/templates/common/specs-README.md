# specs

One directory per feature: `NNN-slug/` with `spec.md`, then `plan.md` and `tasks.md` after approval. `_living/<capability>/spec.md` states what the system does today and is updated when a feature is closed.

Every `spec.md` starts with:

```
# Feature Specification: <name>

**Status**: Draft
**Ticket**: none
**Capability**: <the one capability under _living/ this feature changes>
```

Status moves Draft, Approved, Built, Released, Closed. A feature that will not ship ends as Superseded or Dropped. Only a person sets Approved.
