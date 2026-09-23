# Working in this project

- **TDD, always.** Write the failing test first in `tests/`, run `uv run pytest` to see it fail,
  then write the minimum code, then refactor. Show red → green. Fakes for Canvas, Todoist, Photon
  and OpenAI keep the suite network-free and under a few seconds.
- **Teach as you go.** Faith is learning from this codebase. Each phase gets a `docs/NN-*.md`
  walkthrough explaining why, not just what. Prefer small, readable modules over clever ones.
- **Decisions live in `DECISIONS.md`.** Don't re-ask settled questions; do add new decisions there.
- **Research lives in `RESEARCH.md`.** The design rules at the top of `src/assistant/sync.py`
  (plan then apply, identity by Canvas id, adopt don't clobber, never delete) come from it.
- Run everything with `uv run ...`. Secrets only in `.env` (gitignored). Never commit `data/`.
