//
//  ChatView.swift
//  Ortsbild
//

import SwiftUI

/// The chat of one report: conversation between user and AI. It is opened from the list of reports.
struct ChatView: View {
    @Environment(AuthViewModel.self) private var auth
    @State private var viewModel: ChatViewModel
    /// Action the user tried before being signed in. It runs once the sign-in succeeds.
    @State private var pendingAction: DraftAction?
    /// The user pressed send before being signed in, the report is sent once the sign-in succeeds.
    @State private var pendingSend = false

    init(ticketID: UUID, store: TicketStore) {
        _viewModel = State(initialValue: ChatViewModel(ticketID: ticketID, store: store))
    }

    // TODO: Move texts into a String Catalog (localization), German only for now

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    ForEach(viewModel.messages) { message in
                        MessageRow(
                            message: message,
                            isActive: message.id == viewModel.messages.last?.id && !viewModel.isProcessing,
                            onOption: viewModel.choose(option:),
                            onAction: handle(_:)
                        )
                        .id(message.id)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: viewModel.messages.count) {
                guard let last = viewModel.messages.last else { return }
                withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
            }
        }
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 8) {
                if viewModel.isProcessing {
                    ActivityBar(text: viewModel.activity, since: viewModel.processingSince)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                ComposerBar(
                    text: $viewModel.inputText,
                    photo: $viewModel.attachedPhoto,
                    canSend: viewModel.canSend,
                    placeholder: viewModel.isAnswering ? "Beschreibe das Problem" : "Nachricht",
                    onSend: handleSend
                )
            }
            .animation(.easeInOut(duration: 0.2), value: viewModel.isProcessing)
        }
        .navigationTitle(viewModel.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    auth.isSheetPresented = true
                } label: {
                    Image(systemName: auth.isSignedIn ? "person.crop.circle.fill" : "person.crop.circle")
                }
                .accessibilityLabel("Konto")
            }
        }
        .onChange(of: auth.isSheetPresented) {
            // The sheet is closed without a sign-in: forget what was waiting for it
            if !auth.isSheetPresented, !auth.isSignedIn {
                pendingAction = nil
                pendingSend = false
            }
        }
        .onChange(of: auth.isSignedIn) {
            guard auth.isSignedIn else { return }
            if let action = pendingAction {
                pendingAction = nil
                viewModel.perform(action)
            }
            if pendingSend {
                pendingSend = false
                viewModel.send()
            }
        }
    }

    /// Sending a report requires an account, the server accepts only signed-in users.
    private func handleSend() {
        if auth.isSignedIn {
            viewModel.send()
        } else {
            pendingSend = true
            auth.isSheetPresented = true
        }
    }

    /// Actions on a draft: approving needs an account, everything else works without one.
    private func handle(_ action: DraftAction) {
        if action == .approve, !auth.isSignedIn {
            pendingAction = action
            auth.isSheetPresented = true
        } else {
            viewModel.perform(action)
        }
    }
}

/// Picks the matching presentation for a message's content.
private struct MessageRow: View {
    let message: ChatMessage
    /// Only the last message can still be interacted with (follow-up question, draft).
    let isActive: Bool
    let onOption: (String) -> Void
    let onAction: (DraftAction) -> Void

    var body: some View {
        switch message.content {
        case .text(let text):
            MessageBubble(sender: message.sender, text: text)
        case .photo(let image, let caption):
            PhotoBubble(image: image, caption: caption)
        case .status(let text):
            StatusRow(text: text)
        case .clarification(_, let text, let options), .question(let text, let options):
            VStack(alignment: .leading, spacing: 8) {
                MessageBubble(sender: .agent, text: text)
                QuickReplyBar(options: options, isEnabled: isActive, onSelect: onOption)
            }
        case .draft(let draft):
            DraftCard(draft: draft, isEnabled: isActive, onAction: onAction)
        case .emergency:
            EmergencyBanner()
        case .sanitized(let result):
            SanitizedCard(result: result)
        case .activity:
            EmptyView()  // never added to the chat, the view model keeps it for the activity bar
        }
    }
}

#Preview {
    NavigationStack {
        ChatView(ticketID: UUID(), store: .preview)
    }
    .environment(AuthViewModel(service: MockAuthService()))
}
