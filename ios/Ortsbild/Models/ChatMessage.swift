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
    // TODO: Show user_addendum (user additions) separately from the factual part
}

/// Actions of the approval pause (see handoff: approve, revise, wrong authority, close).
enum DraftAction {
    case approve
    case revise
    case wrongAuthority
    case close
}

/// Content types of a chat message. They mirror the escalation levels from the handoff.
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
}

struct ChatMessage: Identifiable {
    let id = UUID()
    let sender: MessageSender
    let content: ChatContent
    let date = Date()
}
