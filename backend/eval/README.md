# Evaluation set for the classification

`classification_cases.jsonl` has one case per line:

| Field | Meaning |
|---|---|
| `id` | name of the case |
| `text` | the sanitized text (German), may be missing for a photo-only case |
| `photo` | optional, a file name inside `eval/photos/` (not in git, see below) |
| `category`, `lane` | expected values, `null` if the case is only about the emergency flag |
| `emergency` | expected emergency flag |
| `tags` | `emergency`, `injection` (the text tries to give the model orders), `no_alarm` (looks like an emergency word, is none) |

Run it: `make eval-classification` (uses the provider of `CLASSIFICATION_PROVIDER`).

The first 49 cases are text only and were written by us. **Photo cases are still missing**: the team takes photos of the six
categories (5 to 8 each, plus a selfie, a blurred photo, an indoor photo), no people and no license plates, saves them in
`eval/photos/` and adds the lines with `photo`. The folder is ignored by git, real photos do not belong into the repository.
