# Third-party notices

## Mostly Basic Python Problems (MBPP)

- Upstream: https://github.com/google-research/google-research/tree/master/mbpp
- Copyright: Google Research and dataset contributors.
- License: Apache License 2.0, inherited from the upstream repository.
- Bundled file: `data/mbpp/sanitized-mbpp.json`.
- Use in EDUCODER 10: optional teacher-facing reference bank. Standard solutions
  are not shown to learners by the application.

## Design references (not copied into this project)

The EDUCODER 10 implementation is original code. Its architecture was informed
by public project documentation from:

- `dglabsxyz/adaptive-genai-learning-tutor`: diagnostic → path → exercise →
  deterministic grade → progress cycle.
- `mohddarwix/SmartCode` (MIT): sandbox-first grading, progressive hints and
  adaptive recommendations.
- `AyushGit2k5/ai-programming-tutor`: progressive educational hints. The
  inspected repository did not include a clear license file, so no source code
  was copied.

