# Safe Project Stop Script

## Goal

Provide one repeatable command that stops every development backend and Vite
frontend instance belonging to `world_simulation_2D`, including instances
started manually on non-default ports, without touching unrelated processes.

## Design

`scripts/stop.sh` scans processes owned by the current user. A process is a
candidate only when its resolved working directory is the project root or a
descendant and its command matches one of the project service signatures:
`scripts/dev.sh`, `uvicorn app.main:app`, `npm run dev`, the project Vite
binary, or the project esbuild worker.

The default mode sends `SIGTERM`, waits up to five seconds, and sends `SIGKILL`
only to still-running candidates. `--dry-run` prints candidates without
signalling them. The script reports the selected PIDs and any survivors.

The script intentionally does not identify processes by port and does not use
unbounded `pkill -f`; this covers custom ports while avoiding unrelated
services. It does not use PID files, which would become stale when a process is
started outside `scripts/dev.sh`.

## Verification

- `bash -n scripts/stop.sh`
- `bash scripts/stop.sh --dry-run` lists only project service processes.
- Running the script stops the existing 8000/8002/5173/5174 instances.
- A second run is harmless and reports no matching processes.
- `ss -lntp` confirms those ports are no longer held by project services.

