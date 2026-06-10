# VideoCraft Desktop (Electron renderer)

This is where the **composition core** lives: the OTIO-style multi-track IR, the
shared video component library, and the GPU compositor (WebGPU/WebCodecs +
libass-wasm). Per [`docs/design/composition-otio-foundation.md`](../docs/design/composition-otio-foundation.md),
composition is a TypeScript / renderer concern — the Python side keeps only
project / material / analysis / AI and drops out of the render path.

## Current scope (2026-05-29)

Bootstrapped with the **pure-logic IR layer** only — no React, no Electron main
process, no WebGPU yet. That keeps the foundation substrate-independent and
fully unit-testable (foundation doc §10 step 1).

- `src/composition/` — OTIO IR types, clip-kind catalog, placement/duration
  derivation, TimeMap, and the invariant unit tests that pin the contract.

The Electron shell, component library, and compositor land in later steps.

## Commands

```sh
pnpm install
pnpm test          # run the invariant suite once
pnpm test:watch    # watch mode
pnpm typecheck     # tsc --noEmit
```
