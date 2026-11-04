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
    // TODO: Show user_addendum (user additions) separately from the factual part

    /// The letter as one text for the share sheet: to whom, the subject and the body.
    var shareText: String {
        var lines: [String] = []
        if let recipient { lines.append("An: \(authority) (\(recipient))") }
        lines.append("Betreff: \(subject)")
        lines.append("")
        lines.append(body)
        return lines.joined(separator: "\n")
    }

    /// What the share sheet gets: the text and, if there is one, the photo.
    var shareItems: [Any] {
        var items: [Any] = [shareText]
        if let photo { items.append(photo) }
        return items
    }
}

/// Actions of the approval pause (see docs/documentation.md: approve, revise, wrong authority, close).
enum DraftAction {
    case approve
    case revise
    case wrongAuthority
    case close
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
