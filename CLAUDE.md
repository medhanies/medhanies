# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is `medhanies/medhanies`, a GitHub **profile README repository**. Its `README.md` renders on the owner's GitHub profile page (https://github.com/medhanies). There is no application code, build system, package manager, or test suite — changes here are content edits, not software development.

## Repository contents

- `README.md` — the profile page. It is written as HTML embedded in Markdown (centered `<div>`s, `<img>` tags, `###` separators), in the style produced by [profile-readme-generator](https://github.com/maurodesouza/profile-readme-generator). It pulls in external assets: devicon tech-stack icons, shields.io badges, a visitor badge, GitHub readme stats / streak-stats cards, and a Giphy header image.
- `.github/workflows/snake.yml` — a scheduled GitHub Action ("Generate snake animation") that uses `Platane/snk` to render the contribution-graph snake to `snake.svg` and publishes it to the `output` branch via `crazy-max/ghaction-github-pages`. It runs every 12 hours, on manual dispatch, and on pushes to `master` (note: the repo's default branch is `main`, so the push trigger does not fire in practice — the schedule and manual dispatch do the work).

## Conventions

- Preserve the existing HTML-in-Markdown structure of `README.md` when editing it: sections are separated by `###` lines, and content blocks are wrapped in aligned `<div>`s. Edit content in place rather than converting to plain Markdown.
- The snake image in `README.md` is referenced via `raw.githubusercontent.com` (currently pinned to a commit). The generated asset lives on the `output` branch, not on `main` — do not commit `snake.svg` to `main`.
- Stats cards and badges encode the username `medhanies` in their URLs; keep that consistent if URLs are changed.
- There is no lint, build, or test step. Verifying a change means previewing the rendered Markdown/HTML.
