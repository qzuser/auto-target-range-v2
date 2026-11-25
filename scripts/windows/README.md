# Windows Launchers

- `start-web.cmd` / `start-web.ps1`: self-check dependencies, reuse or create the
  local environment according to project policy, then start the Web console on
  port 8010.
- `start-console.cmd` / `start-console.ps1`: fast start using the existing
  `.venv`; command-line arguments are passed through to `spiritscout`.

The only root-level double-click entry is `Start-SpiritScout.cmd`, which forwards
to `start-web.cmd`.
