# Offline dependencies

This directory stores air-gapped deployment artifacts.

- `bundles/`: Git-friendly split archives and JSON manifests. These files are
  committed to the repository.
- `wheels/linux-x86_64/`: the Docker runtime wheelhouse. Docker installs
  directly from this directory with `pip --no-index`.
- `wheels/windows-x86_64/`: optional restored Windows wheelhouse; ignored by
  the Docker build context.
- `staging/`: temporary download/build output. This directory is ignored.
- `images/`: restored Docker image archives. This directory is ignored.

Pinned integration:

- Claude Agent SDK: `0.2.107`
- Bundled Claude Code CLI: `2.1.186`
- Python: `3.12`
- Docker target: Linux x86_64 (`manylinux_2_17_x86_64`)

The SDK wheel is platform-specific because it contains the Claude Code CLI
binary. Always restore the wheelhouse matching the target operating system.

The preferred deployment path is to keep the Linux wheelhouse beside the
source tree. Split archives remain available as a fallback when a Git hosting
service rejects the bundled Claude SDK wheel because of its file size.
