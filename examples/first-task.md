# First task example

This example creates a bounded coding task, inspects the queue, and runs it.

```bash
./orchestra create \
  --title "Add health endpoint" \
  --objective "Add GET /health with tests. Keep changes inside the application and test folders." \
  --role coding

./orchestra status
./orchestra run-next
```

Before using a new machine for real work, verify the runtime:

```bash
./orchestra doctor --probe
./orchestra preflight
```

The task should either finish with verified evidence or stop as blocked. Agent self-reports are not accepted as proof of success.
