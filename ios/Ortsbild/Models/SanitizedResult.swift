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
    /// The message for the user to approve. `nil` if none was written (no defect, an emergency, or the writing failed).
    let draft: DraftDTO?
    /// Set if the picture could not be assigned and the user is asked. Nothing is researched or drafted until they answer.
    let clarification: ClarificationDTO?
    /// Says whether the same defect was reported before and how many votes it has. `nil` while the report has no category.
    let caseInfo: CaseDTO?
    /// `true` once the user released the report for the dashboard. Missing on an older server, then `isApproved` is false.
    let approved: Bool?

    var isApproved: Bool { approved ?? false }

    enum CodingKeys: String, CodingKey {
        case id, status, reason, report, classification, research, draft, clarification, approved
        case photoUrls = "photo_urls"
        case caseInfo = "case"
    }
}

/// The case of a report: the same category within 40 m counts as the same defect, every released report is one vote.
nonisolated struct CaseDTO: Decodable, Sendable, Equatable {
    /// How many released reports the case has, this one included (it counts once the user releases it).
    let votes: Int
    /// `true` if another released report of the case came first.
    let isDuplicate: Bool
    /// The id the dashboard knows the case by (deep link `#case=<id>`). `nil` from an older server.
    var caseId: String? = nil

    enum CodingKeys: String, CodingKey {
        case votes
        case isDuplicate = "is_duplicate"
        case caseId = "case_id"
    }

    /// The sentence for the chat, or `nil` if there is nothing to say (the first report of a defect).
    var message: String? {
        guard isDuplicate, votes > 1 else { return nil }
        return "Dieses Problem wurde hier schon gemeldet. Mit deiner Freigabe zählt deine Meldung als weitere Stimme (dann \(votes))."
    }
}

/// The open question: why the picture could not be assigned, and what the user can pick.
nonisolated struct ClarificationDTO: Decodable, Sendable {
    /// `unclear` (the model doubts) or `no_defect` (the picture shows none of the defects we know).
    let reason: String
    /// The codes of the categories, see `DefectCategory`.
    let options: [String]
}

/// The draft as the backend wrote it: the text of the model plus the location, written by the server.
nonisolated struct DraftDTO: Decodable, Sendable {
    let subject: String
    let body: String
    let summaryDe: String
    /// Two letters, the language of the authority's place.
    let language: String
    let authority: String?
    let contact: ChannelDTO?
    let version: Int

    enum CodingKeys: String, CodingKey {
        case subject, body, language, authority, contact, version
        case summaryDe = "summary_de"
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
        DefectCategory(rawValue: category)?.title ?? "Sonstiges"
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
        self.init(text: text, photo: photo, changes: entries.compactMap(Self.describe))
    }

    /// From lines that were made before, for a chat that is read back from the phone.
    init(text: String?, photo: UIImage?, changes: [String]) {
        self.text = text
        self.photo = photo
        self.changes = changes
    }

    /// The same result without the photo, after the user took the photo away.
    func withoutPhoto() -> SanitizedResult {
        SanitizedResult(text: text, photo: nil, changes: changes)
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
