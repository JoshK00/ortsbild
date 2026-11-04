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
                // TODO: Show these photo tips as an overlay in the camera view too, and warn before the upload if faces are visible (Apple Vision)
                content: .text("Hallo! Mach ein Foto vom Mangel oder lade eins hoch. Um den Rest kümmere ich mich.\n\nTipp für das Foto: Bitte halte Personen und Kennzeichen aus dem Bild heraus und nimm den Mangel aus der Nähe auf.")
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
        run(service.perform(action))
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
        case .wrongAuthority: "Falsche Stelle"
        case .close: "Schließen"
        }
    }
}
