# DeepTutor Agent Instructions

This file mirrors repository-level constraints for Claude-style agents. The
canonical project instructions live in `AGENTS.md`; when in doubt, follow
`AGENTS.md` and the closest applicable nested instructions.

## Mandatory Upstream Mergeability Constraint

All work in this repository MUST preserve the ability to merge changes from
`upstream/main` back into the current repo at any time. This is a hard
architecture and delivery requirement.

- Keep EduPlus2, enterprise, third-party integration, and product-specific logic
  in extension packages such as `extensions/enterprise/` whenever possible.
- Modify core DeepTutor code only for generic, upstream-neutral seams: auth
  providers, scope propagation, permission providers, Store/ObjectStore
  abstractions, app/router composition hooks, lifecycle hooks, or similar
  reusable interfaces.
- Do not hard-code EduPlus2 or tenant-specific business rules in core runtime
  paths, including orchestrators, session lifecycle, registries, tool/capability
  execution, or persistence primitives.
- Do not use monkey patching, `sitecustomize`, import-order side effects, global
  singleton replacement, or router registration order as production override
  mechanisms.
- Document every required core patch with its generic purpose, affected entry
  points, upstream merge risk, and verification coverage.
- Before declaring integration work complete, perform or explicitly record an
  upstream-compatibility check and verify the relevant smoke path, including
  authentication, HTTP/WS turn execution, session ownership, and audit
  correlation.

If a requested change would make upstream merges fragile, stop and propose a
seam, extension-package implementation, or narrower core patch before coding.
