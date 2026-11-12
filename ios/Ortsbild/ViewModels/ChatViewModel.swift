//
//  ChatViewModel.swift
//  Ortsbild
//

import SwiftUI

@MainActor
@Observable
final class ChatViewModel {
    private(set) var messages: [ChatMessage]
    var inputText = ""
    var attachedPhoto: UIImage?
    private(set) var isProcessing = false
    /// What is going on right now, shown in the activity bar. Only set while `isProcessing`.
    private(set) var activity = "Ich arbeite daran"
    /// When the current work started.
    private(set) var processingSince = Date()

    private let service: ReportService
    private let ticketID: UUID
    private let store: TicketStore

    init(ticketID: UUID, store: TicketStore, service: ReportService? = nil) {
        self.ticketID = ticketID
        self.store = store
        self.service = service ?? AppServices.reports
        // A ticket that was written before is read back, a new one starts with the greeting
        messages = store.loadMessages(for: ticketID) ?? [
            ChatMessage(
                sender: .agent,
                content: .text("Hallo! Mach ein Foto vom Mangel oder lade eins hoch. Um den Rest kümmere ich mich.")
            )
        ]
    }

    /// The title for the top of the screen.
    var title: String { TicketText.title(from: messages) }

    var canSend: Bool {
        let hasText = !inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return (hasText || attachedPhoto != nil) && !isProcessing
    }

    /// The report that the app asked a question about, if the last message is that question.
    private var openQuestionReportID: String? {
        if case .clarification(let id, _, _)? = messages.last?.content { id } else { nil }
    }

    /// True while a question waits for the answer: then the input field is the answer.
    var isAnswering: Bool { openQuestionReportID != nil }

    func send() {
        guard canSend else { return }
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        let caption = text.isEmpty ? nil : text
        let photo = attachedPhoto

        // The words are the answer to the open question, they do not start a new report. A new photo does.
        if photo == nil, let caption, let reportID = openQuestionReportID {
            append(.user, .text(caption))
            inputText = ""
            run(service.describe(caption, reportID: reportID))
            return
        }

        if let photo {
            append(.user, .photo(photo, caption: caption))
        } else if let caption {
            append(.user, .text(caption))
        }
        inputText = ""
        attachedPhoto = nil

        run(service.respond(photo: photo, text: caption))
    }

    func choose(option: String) {
        // The question that is open names the report the answer belongs to
        var reportID: String?
        if case .clarification(let id, _, _)? = messages.last?.content { reportID = id }
        append(.user, .text(option))
        run(service.answer(option, reportID: reportID))
    }

    func perform(_ action: DraftAction) {
        append(.user, .text(Self.title(for: action)))
        if action == .delete {
            deleteReport()
        } else {
            run(service.perform(action, reportID: lastDraft?.draft.reportID))
        }
    }

    /// The user confirmed that the report is to be deleted. The server deletes it with its photo for good, then the card is marked as
    /// deleted, its photo goes out of the draft, the proof card and the history on the phone, and its buttons stop working. If the
    /// server cannot delete it, nothing changes and the chat says so. The user can try again.
    private func deleteReport() {
        guard let (draftID, draft) = lastDraft, !draft.isDeleted else { return }
        activity = "Die Meldung wird gelöscht"
        processingSince = Date()
        isProcessing = true
        Task {
            switch await service.deleteReport(reportID: draft.reportID) {
            case .deleted:
                messages = messages.map { message in
                    switch message.content {
                    case .draft where message.id == draftID:
                        ChatMessage(id: message.id, sender: message.sender, content: .draft(draft.deleted()), date: message.date)
                    case .sanitized(let result):
                        ChatMessage(id: message.id, sender: message.sender, content: .sanitized(result.withoutPhoto()), date: message.date)
                    default:
                        message
                    }
                }
                append(.agent, .text(Self.reportDeletedText))
            case .failed(let text):
                append(.agent, .text(text))
            }
            isProcessing = false
        }
    }

    static let reportDeletedText = "Die Meldung wurde gelöscht."

    /// Whether the photo of a draft can be taken away now: only the newest draft, only if it has a photo, and not while the app
    /// is working. It works after the release too, so the user can still take a photo out of the dashboard.
    func canRemovePhoto(_ message: ChatMessage) -> Bool {
        guard !isProcessing, case .draft(let draft) = message.content else { return false }
        return draft.photo != nil && lastDraft?.id == message.id
    }

    /// The user took the photo away because a face or a plate can still be seen. The server deletes it, then the photo is taken out
    /// of the draft, out of the proof card and out of the history on the phone. If the server cannot delete it, the photo stays and
    /// the chat says so.
    func removePhoto() {
        guard let (draftID, draft) = lastDraft, draft.photo != nil, !isProcessing else { return }
        activity = "Das Foto wird gelöscht"
        processingSince = Date()
        isProcessing = true
        Task {
            let result = await service.removePhoto(reportID: draft.reportID)
            switch result {
            case .removed(let body):
                messages = messages.map { message in
                    switch message.content {
                    case .draft where message.id == draftID:
                        ChatMessage(id: message.id, sender: message.sender, content: .draft(draft.withoutPhoto(body: body)), date: message.date)
                    case .sanitized(let result):
                        ChatMessage(id: message.id, sender: message.sender, content: .sanitized(result.withoutPhoto()), date: message.date)
                    default:
                        message
                    }
                }
                append(.agent, .text(Self.photoRemovedText))
            case .failed(let text):
                append(.agent, .text(text))
            }
            isProcessing = false
        }
    }

    static let photoRemovedText = "Das Foto ist gelöscht. Die Meldung bleibt ohne Foto bestehen."

    /// The newest draft in the chat: the one the actions are about.
    private var lastDraft: (id: UUID, draft: ReportDraft)? {
        for message in messages.reversed() {
            if case .draft(let draft) = message.content { return (message.id, draft) }
        }
        return nil
    }

    /// Whether the buttons of a message work. A question is open as long as it is the last message. A draft stays open until
    /// it is released (`.dashboardLink` after it) or deleted, also after an error text or a "comes later" text, so the user can try again.
    func isActive(_ message: ChatMessage) -> Bool {
        guard !isProcessing else { return false }
        if case .draft(let draft) = message.content {
            guard !draft.isDeleted, lastDraft?.id == message.id, let position = messages.firstIndex(where: { $0.id == message.id }) else { return false }
            return !messages[(position + 1)...].contains { if case .dashboardLink = $0.content { true } else { false } }
        }
        return message.id == messages.last?.id
    }

    private func append(_ sender: MessageSender, _ content: ChatContent) {
        messages.append(ChatMessage(sender: sender, content: content))
        // TODO: If the app is closed while the server is still working, the answer is not in the chat when it is opened again.
        // Fetch it with GET /v1/reports/{id} once the report id is kept with the message.
        store.save(messages, for: ticketID)
    }

    private func run(_ stream: AsyncStream<ChatContent>) {
        // The bar is there at once, before the first step is known, so there is no silent moment
        activity = "Ich arbeite daran"
        processingSince = Date()
        isProcessing = true
        Task {
            for await content in stream {
                if case .activity(let text) = content {
                    activity = text  // only for the bar, not a chat message
                } else {
                    append(.agent, content)
                }
            }
            isProcessing = false
        }
    }

    private static func title(for action: DraftAction) -> String {
        switch action {
        case .approve: "Freigeben"
        case .revise: "Überarbeiten"
        case .delete: "Löschen"
        }
    }
}
