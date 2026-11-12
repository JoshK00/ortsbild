//
//  ChatMessage.swift
//  Ortsbild
//

import UIKit

enum MessageSender {
    case user
    case agent
}

/// Draft of a report as produced by the drafting agent.
struct ReportDraft {
    let subject: String
    let body: String
    let authority: String
    let version: Int
    /// How to reach the authority, e.g. "E-Mail: tiefbau@muenchen.de". `nil` if none was found.
    var recipient: String? = nil
    /// The language of the letter (two letters). `nil` for the scripted drafts of the mock.
    var language: String? = nil
    /// One sentence in German about what the letter says, for a letter in a language the user may not read.
    var summaryDE: String? = nil
    /// The cleaned photo that goes with the letter.
    var photo: UIImage? = nil
    /// The report on the server that the draft belongs to, needed to release it. `nil` for the scripted drafts of the mock
    /// and for drafts that were written by an older version of the app.
    var reportID: String? = nil
    /// The id the dashboard knows the case by, for the link "Im Dashboard ansehen". `nil` if the server sent none.
    var caseID: String? = nil
    /// The user deleted the report (and with it the photo) on the server. The card stays in the chat, but nothing on it works any more.
    var isDeleted = false
    // TODO: Show user_addendum (user additions) separately from the factual part

    /// The line that our server writes under the letter when a photo is attached (backend/drafting/service.py, `facts_block`).
    static let attachmentLine = "Anhang / Attachment: Foto / photo"

    /// The letter without the line that a photo is attached.
    static func removingAttachmentLine(from body: String) -> String {
        body.split(separator: "\n", omittingEmptySubsequences: false)
            .filter { $0.trimmingCharacters(in: .whitespaces) != attachmentLine }
            .joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// The same draft after the user took the photo away. `body` is the letter of the server, or `nil` to take the line out here.
    func withoutPhoto(body newBody: String?) -> ReportDraft {
        ReportDraft(
            subject: subject, body: newBody ?? Self.removingAttachmentLine(from: body), authority: authority, version: version,
            recipient: recipient, language: language, summaryDE: summaryDE, photo: nil, reportID: reportID, caseID: caseID,
            isDeleted: isDeleted
        )
    }

    /// The same draft after the user deleted the report: no photo, and the card is marked as deleted.
    func deleted() -> ReportDraft {
        var copy = withoutPhoto(body: nil)
        copy.isDeleted = true
        return copy
    }
}

/// The three actions on a draft (decided by the team on 2026-11-11): release it, revise it, delete the report.
enum DraftAction: CaseIterable {
    case approve
    case revise
    case delete
}

/// Content types of a chat message. They mirror the escalation levels from docs/documentation.md.
enum ChatContent {
    case text(String)
    case photo(UIImage, caption: String?)
    /// Progress line from the agent, e.g. "Zuständige Stelle wird recherchiert".
    case status(String)
    /// Level 2: one follow-up question answered by tap.
    case question(String, options: [String])
    /// Level 1: draft with one-click approval.
    case draft(ReportDraft)
    /// Emergency: only a hint to call 110 / 112, no ticket.
    case emergency
    /// The report after the privacy layer: cleaned photo and text, and what was removed.
    case sanitized(SanitizedResult)
    /// What the app is doing right now, for the activity bar. It is not a chat message and is never added to the chat.
    case activity(String)
    /// The picture could not be assigned: a question with the answers as buttons. The report id says which report is asked about.
    case clarification(reportID: String, text: String, options: [String])
    /// The report was released and is now in the dashboard: a button that shows it there. `caseID` is `nil` if the server sent none.
    case dashboardLink(caseID: String?)
}

struct ChatMessage: Identifiable {
    let id: UUID
    let sender: MessageSender
    let content: ChatContent
    let date: Date

    init(id: UUID = UUID(), sender: MessageSender, content: ChatContent, date: Date = Date()) {
        self.id = id
        self.sender = sender
        self.content = content
        self.date = date
    }
}
