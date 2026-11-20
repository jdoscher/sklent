---
title: Sklent
description: Point it at a CAD repo; get turntables, sheets and listing packs for every design. Self-hosted.
hide:
  - navigation
  - toc
---

<div class="sk-hero" markdown>

# Your CAD repo, as a showcase. { .sk-hero__line }

<p class="sk-hero__sub">Sklent turns the 3D designs in a Git repo into turntable videos, stills,
drawing sheets and marketplace listing packs, on your own server. Point it at a repo on GitHub or
Forgejo (a self-hosted Git forge) and it renders every STEP, STL and 3MF file in it, plus designs
made in <a href="https://github.com/tangency-labs/solidcraft">SolidCraft</a>, an open-source parametric CAD app. AI agents like Claude
can run it too, over MCP, the protocol they use to call tools.</p>

[Install](install.md){ .md-button .md-button--primary } [Connect an agent](mcp.md){ .md-button }

![Sklent's grid in gallery grey: five SolidCraft designs from tangency-labs/solidcraft (a Raspberry Pi case, the SELENE rover, two test blocks and a frame), each with its envelope, body count, revision and bed-fit badge, with sources, class sets and the job log on the left](assets/screenshots/grid-gallery.webp){ .sk-shot }

</div>

<div class="sk-proof" markdown>
<div markdown><span class="sk-k">01 · Input</span><strong>Point it at a repo</strong>
<p>An account, repo, folder, file, branch, tag or pull request on GitHub or Forgejo. Nothing is cloned, and a re-scan renders only the files that changed.</p></div>
<div markdown><span class="sk-k">02 · Output</span><strong>Every output a maker publishes</strong>
<p>Turntable movies, reels, Discord clips, GIFs and stills in shaded and x-ray, plus spec cards, engineering sheets, parts lists, print file packs and marketplace listing packs.</p></div>
<div markdown><span class="sk-k">03 · Runs on</span><strong>Your own server</strong>
<p>One Docker container, GPU or software rendering. Sklent works on its own and keeps every set on its own disk. If you also run <a href="https://kist.pictures">Kist</a>, a self-hosted library for the images and files you collect, it files each set there, tagged and versioned.</p></div>
</div>

<div class="sk-spec" markdown>
<div><b>6 × 2</b><span>core outputs, shaded and x-ray</span></div>
<div><b>1024 px</b><span>quick-check still, made first</span></div>
<div><b>3840×2160</b><span>high-res still</span></div>
<div><b>46</b><span>MCP tools, 24 read-only</span></div>
<div><b>5</b><span>marketplace listing packs</span></div>
</div>

## See it move

![The turntable GIF Sklent made of pi-case.sc: the Raspberry Pi case turns once in cool grey on a light backdrop](assets/outputs/turntable.gif){ .sk-shot .sk-gif }

Every design gets the same orbit, fitted so its bounding box stays in frame at every angle, in
**cool grey** or **white**: never in the design's own colours.

## Outputs

Real outputs of Sklent 0.2.1 from public designs in
[tangency-labs/solidcraft](credits.md). The full list, with every setting and its default, is
in [Outputs and settings](outputs.md).

<div class="sk-gallery" markdown>
<figure markdown>
![The pi-case turntable](assets/outputs/turntable.gif)
<figcaption><b>Turntable</b> · 1080p MP4 and a 640 px GIF, shaded and x-ray</figcaption>
</figure>
<figure markdown>
![A frame of the SELENE rover's vertical reel](assets/outputs/reel-frame.webp)
<figcaption><b>Reel</b> · 1080×1920 for Instagram reels and stories (a frame)</figcaption>
</figure>
<figure markdown>
<div class="sk-missing">Exploded still and animation: needs two or more components, and none of the small example designs has them, so there's no picture here yet.</div>
<figcaption><b>Exploded</b> · <code>views_exploded</code>, off by default</figcaption>
</figure>
<figure markdown>
![The Raspberry Pi case cut through its centre, showing its walls, floor slots and standoffs](assets/outputs/section.webp)
<figcaption><b>Section</b> · a cut through the centre with filled caps</figcaption>
</figure>
<figure markdown>
![SELENE's spec card: an iso view, envelope 1600 × 490 × 296 mm, volume, bodies, components, parameters and a title block](assets/outputs/spec-card.webp)
<figcaption><b>Spec card</b> · 2048×1152, from <code>spec.json</code></figcaption>
</figure>
<figure markdown>
![SELENE's A3 views sheet: top, front, right and iso views in third-angle projection with a title block](assets/outputs/views-sheet.webp)
<figcaption><b>Engineering sheet</b> · A3 views sheet, PNG and PDF</figcaption>
</figure>
<figure markdown>
![SELENE's parts list sheet with quantities and part names under a title block](assets/outputs/bom-sheet.webp)
<figcaption><b>BOM</b> · CSV, JSON and a parts sheet</figcaption>
</figure>
<figure markdown>
![A contact sheet of five designs, each with its hero still, envelope, body count and commit](assets/outputs/contact-sheet.webp)
<figcaption><b>Contact sheet</b> · every design of a source, PNG pages and a PDF</figcaption>
</figure>
</div>

## The drawing sheet

Click a tile and the design opens as a drawing sheet: the file at its true pixel size between
dimension lines, a numbered schedule of every file, and a title block with the source, commit,
revision, palette and envelope. The same window holds revisions, specs and the publish pages.

=== "Dark"
    ![The drawing sheet of pi-case in the dark theme: the high-res still between 3840 px and 2160 px dimension lines, and the spec, publish checklist and title block on the right](assets/screenshots/sheet-dark.webp){ .sk-shot }
=== "Grid, gallery grey"
    ![The grid in gallery grey](assets/screenshots/grid-gallery.webp){ .sk-shot }
=== "Grid, light"
    ![The grid in the light theme](assets/screenshots/grid-light.webp){ .sk-shot }
=== "Grid, dark"
    ![The grid in the dark theme](assets/screenshots/grid-dark.webp){ .sk-shot }

It works on a phone too: the menu opens filters, sources and jobs.

<div class="sk-phones" markdown>
![Sklent on a phone in gallery grey: the design grid in two columns](assets/screenshots/phone-gallery.webp)
![Sklent on a phone in the light theme](assets/screenshots/phone-light.webp)
![Sklent on a phone in the dark theme](assets/screenshots/phone-dark.webp)
</div>

## A sibling of Kist

Sklent shares its [design system](https://kist.pictures/brand/) with [Kist](https://kist.pictures), so the two apps look like one
suite. You don't need [Kist](https://kist.pictures) to use Sklent. If you run it, Sklent files every render set into
a folder there, tagged by repo, design, style, format and commit, with each new version stacked
on the last. Without it, Sklent keeps the sets on its own disk and does everything else the same.
More in [Working with Kist](kist.md).
