//
//  TicketStore.swift
//  Ortsbild
//

import Foundation
import os
import UIKit

private let logger = Logger(subsystem: "com.Joshua-Kehrer.Ortsbild", category: "tickets")

/// A chat message as it is written to disk. Photos are separate files, the message only names them.
private struct StoredMessage: Codable {
    let id: UUID
    let sender: String
    let date: Date
    let content: StoredContent
}

private enum StoredContent: Codable {
    case text(String)
    case photo(file: String, caption: String?)
    case status(String)
    case question(String, options: [String])
    case draft(subject: String, body: String, authority: String, version: Int)
    case emergency
    case sanitized(text: String?, photoFile: String?, changes: [String])
}

/// Keeps the tickets (one chat per report) on this phone, nothing is sent anywhere.
///
/// Layout: `index.json` lists the tickets, every ticket has a folder with `messages.json` and its photos.
/// The files are protected until the first unlock and are left out of the backup.
/// A ticket is only written once the user has sent something, so an empty chat leaves no trace.
// TODO: The history is not tied to the signed-in user. On a phone that several people use, the next person sees it.
// It is cleared when the account is deleted and by "Verlauf löschen" in the account sheet.
@MainActor
@Observable
final class TicketStore {
    private(set) var tickets: [Ticket] = []
    private let root: URL

    init(root: URL? = nil) {
        var directory = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appending(path: "Tickets")
        self.root = directory
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true  // the photos of the user stay on the phone
        try? directory.setResourceValues(values)
        tickets = readIndex()
    }

    // MARK: Reading

    /// An id for a new chat. Nothing is written until the user has sent something.
    func newTicketID() -> UUID { UUID() }

    func loadMessages(for id: UUID) -> [ChatMessage]? {
        let folder = folder(of: id)
        guard let data = try? Data(contentsOf: folder.appending(path: "messages.json")),
              let stored = try? decoder.decode([StoredMessage].self, from: data)
        else { return nil }
        return stored.map { message(from: $0, in: folder) }
    }

    // MARK: Writing

    /// Writes the chat of a ticket. Does nothing as long as the user has sent nothing.
    func save(_ messages: [ChatMessage], for id: UUID) {
        guard messages.contains(where: { $0.sender == .user }) else { return }
        let folder = folder(of: id)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let stored = messages.compactMap { stored(from: $0, in: folder) }
        guard let data = try? encoder.encode(stored) else { return logger.error("could not encode a ticket") }
        write(data, to: folder.appending(path: "messages.json"))

        let now = messages.last?.date ?? Date()
        let title = TicketText.title(from: messages)
        let preview = TicketText.preview(from: messages)
        if let index = tickets.firstIndex(where: { $0.id == id }) {
            tickets[index].title = title
            tickets[index].preview = preview
            tickets[index].updatedAt = now
        } else {
            tickets.append(Ticket(id: id, title: title, preview: preview, createdAt: messages.first?.date ?? now, updatedAt: now))
        }
        tickets.sort { $0.updatedAt > $1.updatedAt }
        writeIndex()
    }

    func delete(_ id: UUID) {
        try? FileManager.default.removeItem(at: folder(of: id))
        tickets.removeAll { $0.id == id }
        writeIndex()
    }

    /// Removes the whole history of this phone.
    func deleteAll() {
        for ticket in tickets { try? FileManager.default.removeItem(at: folder(of: ticket.id)) }
        tickets = []
        writeIndex()
    }

    // MARK: Files

    private var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }

    private var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    private func folder(of id: UUID) -> URL { root.appending(path: id.uuidString) }

    private func readIndex() -> [Ticket] {
        guard let data = try? Data(contentsOf: root.appending(path: "index.json")),
              let tickets = try? decoder.decode([Ticket].self, from: data)
        else { return [] }
        return tickets.sorted { $0.updatedAt > $1.updatedAt }
    }

    private func writeIndex() {
        guard let data = try? encoder.encode(tickets) else { return logger.error("could not encode the ticket index") }
        write(data, to: root.appending(path: "index.json"))
    }

    private func write(_ data: Data, to url: URL) {
        do {
            try data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        } catch {
            logger.error("could not write a ticket file: \(type(of: error))")
        }
    }

    /// Writes a photo once. The name comes from the message, so it is not written again on every save.
    private func savePhoto(_ image: UIImage, named name: String, in folder: URL) -> String? {
        let url = folder.appending(path: name)
        if !FileManager.default.fileExists(atPath: url.path) {
            guard let data = image.jpegForUpload(maxSide: 1600, quality: 0.8) else { return nil }
            write(data, to: url)
        }
        return name
    }

    private func loadPhoto(_ name: String?, in folder: URL) -> UIImage? {
        guard let name, let data = try? Data(contentsOf: folder.appending(path: name)) else { return nil }
        return UIImage(data: data)
    }

    // MARK: Conversion

    private func stored(from message: ChatMessage, in folder: URL) -> StoredMessage? {
        let content: StoredContent
        switch message.content {
        case .text(let text): content = .text(text)
        case .photo(let image, let caption):
            guard let file = savePhoto(image, named: "\(message.id.uuidString).jpg", in: folder) else { return nil }
            content = .photo(file: file, caption: caption)
        case .status(let text): content = .status(text)
        case .question(let text, let options): content = .question(text, options: options)
        case .draft(let draft): content = .draft(subject: draft.subject, body: draft.body, authority: draft.authority, version: draft.version)
        case .emergency: content = .emergency
        case .sanitized(let result):
            let file = result.photo.flatMap { savePhoto($0, named: "\(message.id.uuidString)-clean.jpg", in: folder) }
            content = .sanitized(text: result.text, photoFile: file, changes: result.changes)
        case .activity: return nil  // never part of the chat
        }
        return StoredMessage(id: message.id, sender: message.sender == .user ? "user" : "agent", date: message.date, content: content)
    }

    private func message(from stored: StoredMessage, in folder: URL) -> ChatMessage {
        let content: ChatContent
        switch stored.content {
        case .text(let text): content = .text(text)
        case .photo(let file, let caption): content = .photo(loadPhoto(file, in: folder) ?? UIImage(systemName: "photo") ?? UIImage(), caption: caption)
        case .status(let text): content = .status(text)
        case .question(let text, let options): content = .question(text, options: options)
        case .draft(let subject, let body, let authority, let version):
            content = .draft(ReportDraft(subject: subject, body: body, authority: authority, version: version))
        case .emergency: content = .emergency
        case .sanitized(let text, let photoFile, let changes):
            content = .sanitized(SanitizedResult(text: text, photo: loadPhoto(photoFile, in: folder), changes: changes))
        }
        return ChatMessage(id: stored.id, sender: stored.sender == "user" ? .user : .agent, content: content, date: stored.date)
    }

    /// A store in a temporary folder, for previews.
    static var preview: TicketStore {
        TicketStore(root: FileManager.default.temporaryDirectory.appending(path: "preview-tickets"))
    }
}
