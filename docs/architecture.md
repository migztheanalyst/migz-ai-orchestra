# Architecture

MIGZ AI ORCHESTRA separates **decision**, **execution**, **verification**, and **release authority** so one agent does not silently own the whole lifecycle.

```text
User / CLI
   ↓
Decision layer (heuristic by default, JEV optional)
   ↓
Maestro / scheduler
   ↓
Backend router
   ├─ Native local model
   ├─ Aider (optional)
   ├─ OpenHands (optional)
   ├─ Hermes advisory (optional)
   └─ DeepSeek local advisory (optional)
   ↓
Change guard
   ↓
Tests / Terra-style independent QA
   ↓
Independent reviewer
   ↓
Evidence → verified commit
```

The public core is local-first. Optional integrations may add capabilities but are not required for core health.
