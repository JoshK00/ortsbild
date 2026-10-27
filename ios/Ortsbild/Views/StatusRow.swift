//
//  StatusRow.swift
//  Ortsbild
//

import SwiftUI

/// Small progress line from the agent.
struct StatusRow: View {
    let text: String

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .accessibilityHidden(true)
            Text(text)
                .font(.footnote)
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.horizontal, 4)
    }
}

#Preview {
    StatusRow(text: "Kategorie erkannt: Müll (92 %)")
        .padding()
}
