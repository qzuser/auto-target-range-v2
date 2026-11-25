# Linux And macOS Compatibility Scripts

These scripts preserve the upstream Linux/macOS source workflow. They are not
part of the Windows desktop release path.

- `install.sh`: create or reuse `.venv`, install core dependencies, and create
  missing configuration files.
- `launch.sh`: foreground start, stop, restart, and lightweight offline mode.
- `build-traffic-proxy.sh`: build the Go traffic proxy.
- `install_awdp_toolchains.sh`: prepare the Fedora 44 AWDP toolchain.
- `run_ollama_light.sh`: lightweight local-model entry used by `launch.sh`.
