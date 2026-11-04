//
//  SanitizedResult.swift
//  Ortsbild
//

import UIKit

/// What the backend sent for one report (`POST /v1/reports`). Only the fields the app uses.
nonisolated struct ReportResponse: Decodable, Sendable {
    let id: String
    /// `sanitized`, `blocked`, `rejected` or `processing`.
    let status: String
    /// Short code when the photo was rejected, e.g. `too_many_faces`.
    let reason: String?
    let report: SanitizedReportDTO?
    let photoUrls: [String]

    enum CodingKeys: String, CodingKey {
        case id, status, reason, report
        case photoUrls = "photo_urls"
    }
}

nonisolated struct SanitizedReportDTO: Decodable, Sendable {
    let text: String?
    let pseudonym: String
    let redactionLog: RedactionLogDTO

    enum CodingKeys: String, CodingKey {
        case text, pseudonym
        case redactionLog = "redaction_log"
    }
}

nonisolated struct RedactionLogDTO: Decodable, Sendable {
    let entries: [RedactionEntryDTO]
}

nonisolated struct RedactionEntryDTO: Decodable, Sendable {
    let kind: String
    let count: Int
}

/// The proof the user sees in the chat: the report after the privacy layer.
struct SanitizedResult {
    let text: String?
    let photo: UIImage?
    /// One line per kind of removed data, e.g. "2 Gesichter verdeckt". Never the removed content itself.
    let changes: [String]

    init(text: String?, photo: UIImage?, entries: [RedactionEntryDTO]) {
        self.text = text
        self.photo = photo
        self.changes = entries.compactMap(Self.describe)
    }

    nonisolated private static func describe(_ entry: RedactionEntryDTO) -> String? {
        let n = entry.count
        switch entry.kind {
        case "face": return n == 1 ? "1 Gesicht verdeckt" : "\(n) Gesichter verdeckt"
        case "plate": return n == 1 ? "1 Kennzeichen ersetzt" : "\(n) Kennzeichen ersetzt"
        case "name": return n == 1 ? "1 Name ersetzt" : "\(n) Namen ersetzt"
        case "address": return n == 1 ? "1 Adresse ersetzt" : "\(n) Adressen ersetzt"
        case "organization": return n == 1 ? "1 Organisation ersetzt" : "\(n) Organisationen ersetzt"
        case "email": return n == 1 ? "1 E-Mail-Adresse ersetzt" : "\(n) E-Mail-Adressen ersetzt"
        case "phone": return n == 1 ? "1 Telefonnummer ersetzt" : "\(n) Telefonnummern ersetzt"
        case "iban": return n == 1 ? "1 IBAN ersetzt" : "\(n) IBANs ersetzt"
        case "exif": return "Foto-Metadaten (Gerät, Aufnahmeort) entfernt"
        case "user_identifier": return "Deine Kennung durch ein Pseudonym ersetzt"
        default: return nil
        }
    }
}
