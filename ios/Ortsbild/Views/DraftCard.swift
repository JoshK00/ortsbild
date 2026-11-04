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

    @State private var showsShareSheet = false

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

            VStack(alignment: .leading, spacing: 4) {
                Label(draft.authority, systemImage: "building.columns")
                if let recipient = draft.recipient {
                    Label(recipient, systemImage: "envelope")
                        .textSelection(.enabled)
                }
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 4) {
                Text(draft.subject)
                    .font(.headline)
                Text(draft.body)
                    .font(.body)
                    .textSelection(.enabled)
            }

            // A letter in a language the user may not read: say in German what it says
            if let summary = draft.summaryDE, let language = draft.language, language != "de" {
                Label("Auf Deutsch (\(language.uppercased())): \(summary)", systemImage: "character.bubble")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            if let photo = draft.photo {
                Image(uiImage: photo)
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: 200, maxHeight: 160)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay(alignment: .bottomLeading) {
                        Label("Anhang", systemImage: "paperclip")
                            .font(.caption2.weight(.semibold))
                            .padding(6)
                            .background(.thinMaterial, in: Capsule())
                            .padding(6)
                    }
                    .accessibilityLabel("Bereinigtes Foto im Anhang")
            }

            Divider()

            // The user can always take the letter with them, also after the actions below are used up
            Button {
                showsShareSheet = true
            } label: {
                Label("Teilen", systemImage: "square.and.arrow.up")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .accessibilityHint("Schickt den Text und das Foto mit Mail oder einer anderen App")

            VStack(alignment: .leading, spacing: 12) {

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
            .disabled(!isEnabled)
            .opacity(isEnabled ? 1 : 0.6)
        }
        .padding(16)
        .background(
            Color(.secondarySystemBackground),
            in: RoundedRectangle(cornerRadius: 20, style: .continuous)
        )
        .sheet(isPresented: $showsShareSheet) {
            ShareSheet(items: draft.shareItems)
                .presentationDetents([.medium, .large])
        }
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
