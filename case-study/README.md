# Optio.News — Portfolio Case Study

Everything needed to publish the Optio.News case study on a portfolio site, in three formats. Pick whichever matches your portfolio's stack.

## What's in here

| File | What it is |
|---|---|
| `index.html` | **Fully self-contained page** — all styling and images embedded (no external assets except the optional mermaid CDN for the pipeline diagram, which degrades gracefully to text). Dark/light theme aware. |
| `case-study.md` | The same content as **Markdown with YAML frontmatter**, referencing `images/*.jpg` — for MDX / Astro / Hugo / Jekyll / Next.js portfolios. |
| `images/` | The four screenshots as standalone JPEGs (`before.jpg`, `after.jpg`, `login.jpg`, `mobile.jpg`). |
| `metadata.json` | SEO title/description, slug, tags, skills, thumbnail spec, and the four headline metrics as structured data — for portfolio card components. |

## Option 1 — Static HTML drop-in (any host)

Copy the folder into your portfolio and link to it:

```
portfolio/
└── work/
    └── optio-news/        ← this folder, renamed
        ├── index.html
        └── images/        (only needed for the og:image social preview;
                            the page itself embeds its images)
```

Then link to `/work/optio-news/` from your project grid. Done — no build step.

## Option 2 — Markdown / MDX portfolio (Next.js, Astro, Hugo, Jekyll…)

1. Copy `case-study.md` into your content directory (e.g. `content/work/optio-news.md`).
2. Copy `images/` next to it (or into your static/public dir and adjust the four image paths).
3. The YAML frontmatter carries title, role, timeline, stack, metrics, thumbnail, and links — map those to your project-card component. `metadata.json` has the same data as JSON if that's easier to consume.
4. The pipeline diagram is a standard ```mermaid fence — enable your SSG's mermaid plugin, or delete the fence (the paragraph below it describes the flow in prose).

## Option 3 — Just a link

The case study is also published as a hosted page:
https://claude.ai/code/artifact/d697e45b-2514-4823-acd0-7e1fdd82f888
(Private by default — share it from that page's menu before linking to it publicly.)

## Portfolio card snippet

> **Optio.News** — Turning 94 raw RSS feeds into an image-forward news platform that loads instantly.
> Python · Flask · Postgres · Vanilla JS — *60% → 98% image coverage · instant cold loads · 56/56 tests*

## Before publishing

- The "Review the source" button links to `github.com/leifheaney5/optio-news` — confirm the repo is public (or remove the button).
- All metrics were measured against the live system in July 2026; the page labels anything unmeasured. If you add analytics later, the Results section has an obvious slot for adoption numbers.
