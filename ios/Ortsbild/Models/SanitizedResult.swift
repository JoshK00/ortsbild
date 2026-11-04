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
    /// `nil` if the classification failed, the report is classified later.
    let classification: ClassificationDTO?
    /// `nil` if no responsible authority was found (or the report is no defect, or an emergency).
    let research: ResearchDTO?

    enum CodingKeys: String, CodingKey {
        case id, status, reason, report, classification, research
        case photoUrls = "photo_urls"
    }
}

/// The responsible authority as the backend found it. A suggestion: the user checks it.
nonisolated struct ResearchDTO: Decodable, Sendable {
    let authority: String
    let channel: ChannelDTO?
    let sources: [String]
    /// 0 to 1, how sure the research is.
    let confidence: Double
    /// `registry` (an earlier answer) or `web` (found just now).
    let origin: String
}

nonisolated struct ChannelDTO: Decodable, Sendable {
    /// `email`, `web_form` or `open311`.
    let type: String
    let target: String

    var kindName: String {
        switch type {
        case "email": "E-Mail"
        case "web_form": "Formular"
        default: "Meldeportal"
        }
    }
}

/// The classification of a report as the backend sends it.
nonisolated struct ClassificationDTO: Decodable, Sendable {
    let category: String
    let lane: String
    let emergency: Bool
    /// 0 to 1, how sure the classification is about the category.
    let confidence: Double

    /// German name of the category for the chat.
    var categoryName: String {
        switch category {
        case "litter": "Müll"
        case "graffiti": "Graffiti"
        case "street_light": "Straßenbeleuchtung"
        case "playground_equipment": "Spielgerät"
        case "pothole": "Schlagloch"
        case "tree": "Baum"
        default: "Sonstiges"
        }
    }

    var laneName: String {
        lane == "hazard" ? "Gefahrenstelle" : "Beeinträchtigung"
    }

    var isUnsure: Bool { confidence < 0.5 }
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
