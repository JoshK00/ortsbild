# Ortsbild: Projektregeln

## Mark open items in code with TODO

Everything in the code that is open, provisional, mocked or unfinished is marked with a `// TODO:` comment directly at that spot.

- Format: `// TODO: <what is missing or open>`
- Applies to placeholders, mock data, unimplemented features, undecided questions and known limitations.
- Never leave anything open silently. Even small gaps get a TODO.
- Example: `// TODO: Integrate anonymization (Vision), the photo is currently used unchanged`

## Codebase language: English

The entire codebase is written in English, including all comments.

- Applies to identifiers (types, properties, methods), code comments, doc comments (`///`), `// TODO:` comments, commit messages and file names.
- Exception: user-facing UI texts (labels, buttons, chat messages) are German for now and will be localized via a String Catalog later.
