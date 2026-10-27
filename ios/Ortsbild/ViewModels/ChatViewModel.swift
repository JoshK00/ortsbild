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

    private let service: ReportService

    init(service: ReportService = MockReportService()) {
        self.service = service
        messages = [
            ChatMessage(
                sender: .agent,
                content: .text("Hallo! Mach ein Foto vom Mangel oder lade eins hoch. Um den Rest kümmere ich mich.")
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
        isProcessing = true
        Task {
            for await content in stream {
                append(.agent, content)
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
