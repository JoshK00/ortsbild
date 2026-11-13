//
//  PrivacyNotice.swift
//  Ortsbild
//

import Foundation

/// The texts of the first and the third safety layer for photos.
///
/// 1. Before the photo is taken: the user decides what to photograph. 2. The server covers faces (not text, it is the
/// privacy layer). 3. Before the release: the user checks the photo and is responsible for the content.
/// All texts are here so they are written once, read once by a lawyer and tested.
// TODO: Let the data protection sign-off read these texts and the terms of use, this is not legal advice.
enum PrivacyNotice {
    static let sheetTitle = "Bevor du fotografierst"

    /// The three points of the sheet that opens the first time. Each one is a rule and a short reason. The sheet does not say that
    /// faces are covered by the server, on purpose: people would rely on it.
    static let sheetPoints: [(symbol: String, title: String, text: String)] = [
        ("scope", "Nur den Mangel", "Geh nah heran, damit nichts anderes im Bild ist."),
        ("person.slash", "Keine Personen", "Warte, bis niemand im Bild ist, auch nicht im Hintergrund."),
        ("doc.text.magnifyingglass", "Keine Kennzeichen oder Dokumente", "Auch keine Bildschirme oder Briefe, die man lesen kann."),
    ]

    static let sheetButton = "Verstanden"

    /// Under the button "Freigeben" when there is a photo.
    static let releaseWithPhoto = "Mit „Freigeben“ bestätigst du, dass auf dem Foto niemand erkennbar ist und du die Meldung so teilen darfst. Du bist für den Inhalt deiner Meldung verantwortlich."

    /// Under the button "Freigeben" when there is no photo.
    static let releaseWithoutPhoto = "Mit „Freigeben“ wird deine Meldung im Dashboard sichtbar. Du bist für den Inhalt deiner Meldung verantwortlich."
}

/// Remembers that the user has seen the sheet, so it opens only the first time the user presses the camera or the library button.
struct PhotoNoticeGate {
    static let key = "photoNoticeSeen.v1"
    var defaults: UserDefaults = .standard

    var shouldShow: Bool { !defaults.bool(forKey: Self.key) }

    func markSeen() { defaults.set(true, forKey: Self.key) }
}
