//
//  DraftCard.swift
//  Ortsbild
//

import SwiftUI

/// Draft card with one-click approval (level 1).
struct DraftCard: View {
    let draft: ReportDraft
    let isEnabled: Bool
    let onAction: (DraftAction) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Entwurf", systemImage: "doc.text")
                    .font(.footnote.weight(.semibold))
                Spacer()
                Text("Version \(draft.version)")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Label(draft.authority, systemImage: "building.columns")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 4) {
                Text(draft.subject)
                    .font(.headline)
                Text(draft.body)
                    .font(.body)
            }

            Divider()

            Button {
                onAction(.approve)
            } label: {
                Text("Freigeben")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)

            // Side by side if there is room (e.g. not at large text sizes), otherwise stacked
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) {
                    secondaryButton("Überarbeiten", action: .revise)
                    secondaryButton("Falsche Stelle", action: .wrongAuthority)
                    secondaryButton("Schließen", action: .close)
                }
                VStack(spacing: 8) {
                    secondaryButton("Überarbeiten", action: .revise)
                    secondaryButton("Falsche Stelle", action: .wrongAuthority)
                    secondaryButton("Schließen", action: .close)
                }
            }
        }
        .padding(16)
        .background(
            Color(.secondarySystemBackground),
            in: RoundedRectangle(cornerRadius: 20, style: .continuous)
        )
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.6)
    }

    private func secondaryButton(_ title: LocalizedStringKey, action: DraftAction) -> some View {
        Button {
            onAction(action)
        } label: {
            Text(title)
                .font(.footnote)
                .lineLimit(1)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
    }
}

#Preview {
    DraftCard(
        draft: ReportDraft(
            subject: "Illegale Müllablagerung",
            body: "Am gemeldeten Standort wurde Sperrmüll abgelagert. Wir bitten um Prüfung und Entfernung.",
            authority: "Ordnungsamt Musterstadt",
            version: 1
        ),
        isEnabled: true
    ) { _ in }
    .padding()
}
