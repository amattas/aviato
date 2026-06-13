---
slug: /
sidebar_position: 1
sidebar_label: Overview
title: PROJECT
---

import Link from '@docusaurus/Link';

PROJECT is ... (one-paragraph intro — what it is, who it's for, the headline
capabilities).

<div className="pd-cards">
  <Link className="pd-card" to="/guide/getting-started">
    <span className="pd-card-kicker">Guide</span>
    <span className="pd-card-title">Getting started</span>
    <span className="pd-card-desc">Installation and first steps.</span>
  </Link>
  <Link className="pd-card" to="/api/reference">
    <span className="pd-card-kicker">Reference</span>
    <span className="pd-card-title">API reference</span>
    <span className="pd-card-desc">Generated from docstrings at build time.</span>
  </Link>
</div>

## Installation

```bash
pip install PROJECT
```

{/* MDX gotchas baked into this scaffold:
    - never hand-write <p> with multi-line content (MDX nests another <p>
      inside → invalid HTML → React hydration errors); use a div
    - keep card spans single-line
    - generated/plain-markdown pages need `mdx: { format: md }` front matter */}
