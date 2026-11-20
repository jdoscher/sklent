# Revisions

Every rendered version of a design keeps its own render set: one per **blob**, because a
commit that didn't change the file has nothing new to render. Each set is labelled with the
commit that made that version of the file (message, author, date, from the forge) and every
git tag whose tree holds it. Tiles show `N rev` when more than one version is kept.

Re-rendering the same version (**Re-render**, `force`) replaces only that version's set, and
only once the new one has finished: a cancelled or failed re-render leaves the old set in
place.

## What's kept

- **Every tagged version** stays.
- Of the untagged ones, the newest `revisions_keep` (default **10**; `0` keeps all) stay on
  disk and older ones are pruned.
- Pruning never touches [Kist](https://kist.pictures) (the optional self-hosted library for images and files
  that Sklent can file sets into) unless `revisions_prune_kist` is on (default **off**), which
  trashes the pruned versions' items (restorable from [Kist](https://kist.pictures)'s trash).

In [Kist](https://kist.pictures), a new version never trashes the previous one's items: each new item is linked
`version_of` the one it follows and stacked with it as the cover, so [Kist](https://kist.pictures)'s versions list and
compare work on the chain and links to older items keep working. See
[Working with Kist](kist.md).

## Compare

A sheet in the drawing sheet, under **Revisions**: two versions as a **slider**, **side by
side**, or **Changes**, the pixels that differ drawn in the sheet's ink over a faded copy of
the newer one (never a hue). It works on any still, or on the same frame of any turntable.
Each version's stills are framed to its own envelope, so when the envelope changed the compare
says part of the difference is framing. Below it are the commits that changed the file in
between, from the forge API.

## Filmstrip

One still per kept version along a hairline timeline, with the commit and date in mono and
any tags. Choosing one compares it with the current version.

## Build-history timelapse

With `revisions_timelapse` on (default off), each render also makes
`<design>-timelapse-1080p.mp4` and `<design>-timelapse.gif`: the part building itself feature
by feature (`timeline.rollback` through the history, one still per step from a fixed iso
camera, then a hold on the finished part). Nothing is drawn on the frames. Every step is a
rebuild, so designs over `revisions_timelapse_max_bodies` (100) bodies or
`revisions_timelapse_max_features` (200) features are skipped, with the reason in the set's
`report.json` (`timelapse.skipped`).

## Settings

| setting | default | |
|---|---|---|
| `revisions_keep` | `10` | Untagged versions kept on disk besides every tagged one; `0` keeps all |
| `revisions_prune_kist` | off | Also trash pruned versions' [Kist](https://kist.pictures) items |
| `revisions_timelapse` | off | Build-history timelapse MP4 and GIF |
| `revisions_timelapse_max_features`, `revisions_timelapse_max_bodies` | `200`, `100` | Skip the timelapse above these |

## API and agents

- `GET /api/designs/{id}/sets` (newest first), `/sets/{set}`, `/sets/{set}/files/{name}`.
- `GET /api/designs/{id}/compare?a=&b=&style=&variant=&frame=` (`a` older, `b` newer; by
  default the current version against the one before), plus `/compare/diff.png`,
  `/compare/frame.png`, `/compare/composite.png` and `/changelog?base=&head=`.
- [MCP](mcp.md) (the protocol AI agents like Claude use to call tools): `list_sets`, `compare_sets` (changed share, bounding box, mask and composite URLs, and
  the commits in between) and `view_compare` (older, newer and changes as one picture).
