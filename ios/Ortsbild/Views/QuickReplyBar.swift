//
//  QuickReplyBar.swift
//  Ortsbild
//

import SwiftUI

/// Tap replies for a follow-up question (level 2).
struct QuickReplyBar: View {
    let options: [String]
    let isEnabled: Bool
    let onSelect: (String) -> Void

    var body: some View {
        HStack(spacing: 8) {
            ForEach(options, id: \.self) { option in
                Button(option) { onSelect(option) }
                    .buttonStyle(.bordered)
                    .buttonBorderShape(.capsule)
                    .disabled(!isEnabled)
            }
            Spacer()
        }
    }
}

#Preview {
    QuickReplyBar(options: ["Ja", "Nein"], isEnabled: true) { _ in }
        .padding()
}
