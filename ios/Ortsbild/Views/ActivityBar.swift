//
//  ActivityBar.swift
//  Ortsbild
//

import SwiftUI

/// Shows that the app is working, what it is doing, and for how long. It is there from the moment the user
/// sends something until the answer is complete, so there is never a silent wait.
struct ActivityBar: View {
    let text: String
    /// When the work started, for the running seconds.
    let since: Date

    /// After this many seconds the bar says that it takes longer than usual.
    private let slowAfterSeconds = 20

    var body: some View {
        TimelineView(.periodic(from: since, by: 1)) { context in
            let seconds = max(0, Int(context.date.timeIntervalSince(since)))
            HStack(spacing: 10) {
                ProgressView()
                VStack(alignment: .leading, spacing: 2) {
                    Text(seconds >= 5 ? "\(text) · \(seconds) s" : text)
                        .font(.subheadline)
                    if seconds >= slowAfterSeconds {
                        Text("Das dauert länger als sonst, ich arbeite noch daran.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .glassCard(cornerRadius: 18)
            .padding(.horizontal, 12)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Ich arbeite: \(text)")
        }
    }
}

#Preview {
    VStack {
        ActivityBar(text: "Daten werden anonymisiert", since: .now)
        ActivityBar(text: "Zuständige Stelle wird gesucht", since: .now.addingTimeInterval(-25))
    }
    .padding()
}
