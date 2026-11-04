//
//  Ticket.swift
//  Ortsbild
//

import Foundation

/// One report with its own chat. The list of tickets is the history of the user on this phone.
struct Ticket: Identifiable, Codable, Equatable {
    let id: UUID
    var title: String
    /// The last thing in the chat, shown under the title in the list.
    var preview: String
    let createdAt: Date
    var updatedAt: Date
}

/// Title and preview of a ticket, made from its messages.
enum TicketText {
    static let untitled = "Neue Meldung"

    /// The first thing the user wrote, or "Foto-Meldung" if only a photo was sent.
    static func title(from messages: [ChatMessage]) -> String {
        for message in messages where message.sender == .user {
            switch message.content {
            case .text(let text): return shortened(text)
            case .photo(_, let caption): return caption.map { shortened($0) } ?? "Foto-Meldung"
            default: continue
            }
        }
        return untitled
    }

    /// The last visible message in one line.
    static func preview(from messages: [ChatMessage]) -> String {
        for message in messages.reversed() {
            switch message.content {
            case .text(let text): return shortened(text)
            case .status(let text): return shortened(text)
            case .question(let text, _): return shortened(text)
            case .clarification(_, let text, _): return shortened(text)
            case .draft(let draft): return shortened(draft.subject)
            case .emergency: return "Notfall: bitte 110 oder 112 anrufen"
            case .sanitized: return "Daten anonymisiert"
            case .photo(_, let caption): return caption.map { shortened($0) } ?? "Foto"
            case .activity: continue
            }
        }
        return ""
    }

    private static func shortened(_ text: String) -> String {
        let line = text.split(whereSeparator: \.isNewline).first.map(String.init) ?? text
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        return trimmed.count > 70 ? String(trimmed.prefix(70)) + "…" : trimmed
    }
}
