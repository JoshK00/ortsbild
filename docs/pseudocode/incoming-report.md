# Pseudocode: IncomingReport (connector gateway output)

Pipeline order:

```
connector -> IncomingReport (raw) -> privacy agent -> SanitizedReport -> classification agent -> ...
```

Rule: nothing downstream of the privacy agent ever sees an `IncomingReport`. The raw and the sanitized report are separate types (see [privacy-agent.md](privacy-agent.md)), so the type system enforces this.

## IncomingReport (raw, unsanitized)

```
IncomingReport
  id: str                      # assigned by the connector, stable across all agents
  received_at: datetime        # UTC
  source:
    type: "app" | "email"      # TODO: more source types later
    connector: str
    raw_ref: str               # pointer to the raw data, needed to delete it after sanitizing
  location: Location           # REQUIRED, a report without a location is meaningless
    lat, lon, accuracy_m
    origin: "device_gps" | "exif" | "geocoded_from_text"
  text: str | None             # free text, not yet sanitized
  photos: list[Photo]          # may be empty (email without attachments)
    id, mime_type, ref
  user:
    identifier: str            # plain identifier (email, device id), for the privacy agent ONLY
    identifier_type: "email" | "device_id"
```

Same schema for every source. Sources differ only in which optional fields are filled (text, photos), never in structure.

## Connector gateway

The gateway, not the agent, enforces the contract:

- no location -> the report is NOT forwarded, it is rejected at the gateway
- only image attachments pass

**Decision:** The gateway receives raw data (the unsanitized email or app payload) and processes it inside our own backend. For geocoding it sends ONLY the extracted address to the external geocoder: no sender, no user identifier, no other text. The request carries nothing that links the address to a user.

## Open items

- TODO: An email always names a place, but as text ("playground in the city park", "Main St 5"), not as coordinates. The gateway has to extract the place from the text and turn it into lat/lon (or take EXIF of an attached photo). Define what happens when extraction fails or the place is ambiguous (reject, ask the sender back) and what the sender gets back in that case.
- TODO: Decide whether `Location` also keeps the place as text (`address_text`) next to lat/lon, e.g. for the report to the authority.
- TODO: Verify with the real extraction step that the extracted address string really contains only the place (no name or other personal data mixed in).
- TODO: Define limits (max photos, max file size, allowed mime types) in the gateway.
- TODO: Normalize the mime type to lowercase in the gateway before building `Photo`. MIME types are case-insensitive by standard (some mail clients send `Image/JPEG`), but `Photo` only accepts lowercase `image/...` on purpose (see `test_uppercase_mime_type_is_rejected`).
- TODO: The mime type is only a claim of the sender. The gateway must also check that the file really is an image (e.g. try to open it with Pillow) before it passes as `Photo`.
