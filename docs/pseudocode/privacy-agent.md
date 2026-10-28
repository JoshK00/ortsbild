# Pseudocode: privacy layer

Takes an `IncomingReport` (see [incoming-report.md](incoming-report.md)) and returns a `SanitizedReport`. Mostly deterministic code in our own backend, no external model call.

## 1. Steps

Steps only run when their input exists: the photo steps (a, c) only for reports with photos,
the text step (b) only for reports with text. After every step a router in the graph picks the
next step that applies, so no detector runs on a report without photos or without text.

```
a. strip_metadata
     for each photo: remove EXIF (GPS, device, timestamps)
     the location already comes from the gateway, so EXIF is simply dropped
     HEIC/HEIF (iPhone default) is converted to JPEG, so later steps see one format

b. sanitize_text   (if text)
     find: emails, phone numbers, IBAN, license plates      -> patterns + checksums
     find: person names, addresses, organizations           -> small local NER model
     replace every hit with a placeholder: <PERSON>, <ADDRESS>, <PLATE> ...
     TODO: Decide which addresses belong to the report (defect location) and
           which are private. Pure detection cannot tell. Needs the
           model-assisted step, working on already sanitized text only.

c. sanitize_photos (for each photo)
     find faces          -> small local detector (CPU)
     find license plates -> small local detector (CPU)
     blur / black out every box
     if a detector fails or is below the confidence threshold -> see 2. Fail closed

d. pseudonymize_user
     look up user.identifier in the pseudonym table
     if found:     use the existing pseudonym
     else:         create a new random pseudonym, store the mapping
     the mapping table is separate and only readable by this agent
     TODO: A pseudonym is still personal data in the GDPR sense. Needs sign-off
           (docs/documentation.md, section 6).
     TODO: Open question: may the authority contact the reporter? If yes, define
           when and how the identifier is released.

e. assemble
     build SanitizedReport, write RedactionLog, delete the raw data via raw_ref
     TODO: Define the deletion deadline and whether backups may hold raw data.
```

The location is NOT changed by the privacy layer. It is the location of the defect and
the authority needs it exactly. The reporter is protected by the pseudonym.

- TODO: For the data protection sign-off: many exact locations of the same pseudonym could add up to a movement profile. Check whether that needs a rule.

## 2. Fail closed

If any step fails or is unsure (detector down, confidence too low, unreadable file):

- do NOT pass the report on
- set status `blocked_privacy` and hand it to an operator
- the blocked report keeps its raw data only until the operator decides

Default is blocking. Passing on a reduced report (for example without photos) is a possible alternative.

- TODO: Make this configurable per deployment (block vs. reduced report).

## 3. Output: SanitizedReport (what the next agents see)

```
SanitizedReport
  id: str                      # same id as the IncomingReport
  received_at: datetime
  source_type: "app" | "email"
  location: Location           # unchanged, it is the location of the defect
  text: str | None             # placeholders instead of personal data
  photos: list[Photo]          # blurred
  pseudonym: str               # replaces user, no plain identifier anywhere
  redaction_log: RedactionLog

RedactionLog
  entries: list of { step, kind, count, confidence }
  # records WHAT was removed and how often, never the removed content itself
  # kinds: face, plate, name, address, organization, email, phone, iban, exif, user_identifier
```

## 4. Handover to classification (agent 1)

The classification agent takes a `SanitizedReport` and returns the existing `Classification` model (category, lane, emergency, confidence).

- TODO: Agree on one name across the project (the handoff says `Classification`, the first sketch said `RequestType`).
