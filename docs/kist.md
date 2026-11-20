# Working with Kist

[Kist](https://kist.pictures) is a self-hosted visual library, and Sklent's sibling: the two
share one design system, and Sklent can file every render set into Kist. Kist is optional.
**Sklent works on its own**: with `SK_KIST_URL` empty, sets stay on Sklent's disk
(`SK_DATA/renders`) and the grid, drawing sheets, revisions, specs, presets, file packs,
project pages, listing packs and MCP all work the same. Only the Kist review board and its
share links need Kist.

## Connecting

In `.env`:

```bash
SK_KIST_URL=http://kist-host:8080     # the Kist that sets are filed into
SK_KIST_TOKEN=                        # a Kist token that may add, tag and file items
SK_KIST_ROOT_FOLDER=SolidCraft        # the top-level folder (default)
```

Restart the container. The **Kist** chip in the top bar shows whether Kist is reachable, and
the drawing sheet gets a **Kist** link to the design's folder.

## What lands in Kist

Each set lands in `SolidCraft/<owner>/<repo>/<design>`, every file as an item tagged:

| tag | value |
|---|---|
| `solidcraft` | every Sklent item |
| `repo:<owner>/<repo>` | the source repo |
| `design:<name>` | the design |
| `style:<shaded\|wireframe>` | the look |
| `format:<variant>` | `1080p`, `reel`, `gif`, `social`, `spec-card`, `views-sheet`, `contact-sheet`, `pack-etsy`, … |
| `palette:<name>` | `cool-grey` or `white` |
| `rev:<commit10>` | the commit that made that version of the file |

Each item's source is the file's URL at the rendered commit. Renders of a pull request, another
branch or a tag file into their own subfolder (`<design>/pr-<n>` or `<design>/@<branch>`),
tagged `ref:pr-<n>` or `ref:<branch>`.

## Versions

A new version never trashes the previous one's items: each new item is linked `version_of`
the item it follows and stacked with it as the cover, so Kist's versions list and compare work
on the chain, and links to older items keep working. Untagged versions that Sklent prunes from
its own disk stay in Kist unless you turn on `revisions_prune_kist`. See [Revisions](revisions.md).

## Review boards and share links

From a design's **Publish** pages, **Kist review** makes a Kist board of a design's set (or one
still per design of a source), real photos first. A **share link** to that board is a public
page on your Kist with Kist's guest proofing. It is off until you turn on
`outputs_review_share_links`, is made only when you click and confirm, expires after 30 days
by default, and can be revoked. Pull-request review comments can point their pictures at that
share link instead of at Sklent's own file URLs. See [Publishing](publishing.md#kist-review-board).

## Agents across both

Sklent's MCP tools return each set's Kist folder and item ids (`get_render_set`). With Kist's
own MCP connected as well, an agent can go on to browse, view and tag the filed sets there.
