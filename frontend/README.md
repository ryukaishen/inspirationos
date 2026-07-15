# InspirationOS — frontend

Next.js (App Router, TypeScript, Tailwind + shadcn/ui, TanStack Query).
`/api/*` is proxied to the FastAPI backend via `next.config.ts` so the browser
only ever talks to one origin.

Commands (run from this directory):

```bash
npm run dev              # dev server on :3000 (expects the backend on :8000)
npm run lint             # eslint
npx tsc --noEmit         # type check
npm run test -- --run    # vitest + React Testing Library
```

See the repository root [README](../README.md) and [docs/](../docs/) for the
full picture.
