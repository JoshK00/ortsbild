//
//  MessageBubble.swift
//  Ortsbild
//

import SwiftUI

/// Text bubble. The user's on the right in white, the agent's on the left in frosted glass.
struct MessageBubble: View {
    let sender: MessageSender
    let text: String

    var body: some View {
        HStack {
            if sender == .user { Spacer(minLength: 48) }
            Text(text)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .foregroundStyle(sender == .user ? Theme.ink : Color.white)
                .background {
                    if sender == .user {
                        RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Color.white)
                    } else {
                        Color.clear.glassCard(cornerRadius: 18)
                    }
                }
            if sender == .agent { Spacer(minLength: 48) }
        }
    }
}

/// The user's photo, optionally with a caption.
struct PhotoBubble: View {
    let image: UIImage
    let caption: String?

    var body: some View {
        HStack {
            Spacer(minLength: 48)
            VStack(alignment: .trailing, spacing: 6) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: 240, maxHeight: 280)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .accessibilityLabel("Hochgeladenes Foto")
                if let caption {
                    MessageBubble(sender: .user, text: caption)
                }
            }
        }
    }
}

#Preview {
    VStack(spacing: 12) {
        MessageBubble(sender: .agent, text: "Hallo! Mach ein Foto vom Mangel.")
        MessageBubble(sender: .user, text: "Hier liegt Müll am Spielplatz.")
        PhotoBubble(image: UIImage(systemName: "photo") ?? UIImage(), caption: "Neben der Rutsche")
    }
    .padding()
}
