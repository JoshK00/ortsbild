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

    init(service: ReportService? = nil) {
        self.service = service ?? AppServices.reports
        messages = [
            ChatMessage(
                sender: .agent,
                // TODO: Show these photo tips as an overlay in the camera view too, and warn before the upload if faces are visible (Apple Vision)
                content: .text("Hallo! Mach ein Foto vom Mangel oder lade eins hoch. Um den Rest kümmere ich mich.\n\nTipp für das Foto: Bitte halte Personen und Kennzeichen aus dem Bild heraus und nimm den Mangel aus der Nähe auf.")
            )
        ]
    }

    var canSend: Bool {
        let hasText = !inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return (hasText || attachedPhoto != nil) && !isProcessing
    }

    func send() {
        guard canSend else { return }
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        let caption = text.isEmpty ? nil : text
        let photo = attachedPhoto

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
        append(.user, .text(option))
        run(service.answer(option))
    }

    func perform(_ action: DraftAction) {
        append(.user, .text(Self.title(for: action)))
        run(service.perform(action))
    }

    private func append(_ sender: MessageSender, _ content: ChatContent) {
        messages.append(ChatMessage(sender: sender, content: content))
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
