# UTM Naming Conventions

The rulebook for tagging every link we share, so traffic and signups group
cleanly in Umami and in the `attribution` field on user documents.

**Why this file exists:** UTM values are free text — whatever you type into a
link is stored verbatim, and analytics treats `Telegram`, `telegram`, and `tg`
as three different sources. Inconsistent tags split one channel across many
rows, and **you cannot fix a tag after the link is shared**. So: decide the
format here, follow it every time, and log every new source in the registry at
the bottom **before** posting the link.

---

## The rules

1. **Lowercase only.** `tg`, never `TG` or `Tg`.
2. **Underscores as separators.** No spaces, no dashes. `tg_jeeneetards`.
3. **ASCII letters, numbers, underscore only.** Nothing else.
4. **Never rename a source once it's live.** If a value is wrong, pick a new one
   and add it — don't reuse or "correct" an old one (the old links can't change).
5. **Register it first.** Every new `utm_source` goes in the table below before
   the link goes out.

---

## The three parameters

| Param | Required? | What it holds | Example |
|---|---|---|---|
| `utm_source` | **yes** | the specific placement, as `<channel>_<detail>` | `tg_jeeneetards` |
| `utm_medium` | recommended | the channel *type*, for grouping | `community` |
| `utm_campaign` | optional | a time-bound push only | `launch_aug2026` |

`utm_source` is the workhorse — it identifies exactly where the link lived.
`utm_medium` lets you answer "how's all my community traffic vs social?" without
string-parsing. `utm_campaign` is only for dated drives; skip it for evergreen links.

### `utm_source` — channel prefixes (the vocabulary)

| Prefix | Channel | Examples |
|---|---|---|
| `tg_` | Telegram group/channel | `tg_jeeneetards`, `tg_allen_physics` |
| `wa_` | WhatsApp group | `wa_class12`, `wa_dropperbatch` |
| `reddit_` | Subreddit | `reddit_jeeneetards`, `reddit_jee` |
| `ig_` | Instagram placement | `ig_bio`, `ig_story`, `ig_post` |
| `yt_` | YouTube | `yt_desc`, `yt_pinned` |
| `x_` | Twitter / X | `x_bio`, `x_post` |
| `quora` | Quora | `quora` (or `quora_<space>`) |

### `utm_medium` — the fixed grouping set (pick one)

- `community` — group chats & forums: Telegram, WhatsApp, Reddit, FB groups
- `social` — feeds & profiles: Instagram, X, YouTube
- `referral` — answers & mentions: Quora

---

## How to build a link

```
https://www.makemymock.com/?utm_source=<source>&utm_medium=<medium>
```

Concrete examples:

| Where you're posting | Link |
|---|---|
| "JEE NEETards" Telegram, pinned msg | `https://www.makemymock.com/?utm_source=tg_jeeneetards&utm_medium=community` |
| r/JEENEETards post | `https://www.makemymock.com/?utm_source=reddit_jeeneetards&utm_medium=community` |
| Instagram bio link | `https://www.makemymock.com/?utm_source=ig_bio&utm_medium=social` |
| Instagram story swipe-up | `https://www.makemymock.com/?utm_source=ig_story&utm_medium=social` |
| Quora answer | `https://www.makemymock.com/?utm_source=quora&utm_medium=referral` |

---

## Source registry

Add a row here **before** you use a new `utm_source`. Keep it the single source
of truth for what's live.

| `utm_source` | Channel | Where exactly | First used |
|---|---|---|---|
| `tg_jeeneetards` | Telegram | JEE NEETards group, pinned message | — |
| `reddit_jeeneetards` | Reddit | r/JEENEETards | — |
| `ig_bio` | Instagram | profile bio link | — |
| `ig_story` | Instagram | story | — |
| `quora` | Quora | answers | — |

---

## How this gets measured

- **Umami** → *traffic*: how many people each `utm_source` sent to the site
  (visits, bounce, pages), regardless of whether they signed up.
- **`attribution.utm_source` on the user doc** → *conversions*: how many of those
  visitors actually created an account, captured first-touch at signup.
- **Traffic ÷ conversions per source** = your conversion rate per channel — the
  number that tells you where to spend effort.
