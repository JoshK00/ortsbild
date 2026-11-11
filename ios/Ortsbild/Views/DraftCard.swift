//
//  DraftCard.swift
//  Ortsbild
//

import SwiftUI

/// Draft card with one-click approval (level 1).
struct DraftCard: View {
    let draft: ReportDraft
    let isEnabled: Bool
    /// Whether the photo can be taken away now (see `ChatViewModel.canRemovePhoto`). It works after the release too.
    var canRemovePhoto = false
    let onAction: (DraftAction) -> Void
    /// The user confirmed that the photo is to be deleted.
    var onRemovePhoto: () -> Void = {}

    @State private var confirmsDeletion = false
    @State private var showsPhotoViewer = false
    @State private var confirmsPhotoRemoval = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Entwurf", systemImage: "doc.text")
                    .font(.footnote.weight(.semibold))
                Spacer()
                Text(draft.isDeleted ? "Gelöscht" : "Version \(draft.version)")
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

            photoSection

            Divider()

            VStack(alignment: .leading, spacing: 12) {
                // The release is also the check of the photo and the user's statement that the content is theirs to share
                if !draft.isDeleted {
                    Text(draft.photo != nil ? PrivacyNotice.releaseWithPhoto : PrivacyNotice.releaseWithoutPhoto)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Button {
                    onAction(.approve)
                } label: {
                    Text("Freigeben")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(PrimaryButtonStyle())

                // Side by side if there is room (e.g. not at large text sizes), otherwise stacked
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) {
                        reviseButton
                        deleteButton
                    }
                    VStack(spacing: 8) {
                        reviseButton
                        deleteButton
                    }
                }
            }
            .disabled(!isEnabled)
            .opacity(isEnabled ? 1 : 0.6)
        }
        .padding(16)
        .glassCard(cornerRadius: 24)
        .confirmationDialog("Meldung löschen?", isPresented: $confirmsDeletion, titleVisibility: .visible) {
            Button("Löschen", role: .destructive) { onAction(.delete) }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Die Meldung und das Foto werden auf dem Server gelöscht. Das kann nicht rückgängig gemacht werden.")
        }
        .fullScreenCover(isPresented: $showsPhotoViewer) {
            if let photo = draft.photo {
                PhotoViewer(image: photo)
            }
        }
    }

    /// The photo is a step of the check: it opens in full screen, and the user can take it away. Without a photo the card says so.
    @ViewBuilder
    private var photoSection: some View {
        if let photo = draft.photo {
            VStack(alignment: .leading, spacing: 8) {
                Button {
                    showsPhotoViewer = true
                } label: {
                    Image(uiImage: photo)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: 260, maxHeight: 220)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .overlay(alignment: .bottomLeading) {
                            Label("Anhang", systemImage: "paperclip")
                                .font(.caption2.weight(.semibold))
                                .padding(6)
                                .background(.thinMaterial, in: Capsule())
                                .padding(6)
                        }
                        .overlay(alignment: .topTrailing) {
                            Image(systemName: "arrow.up.left.and.arrow.down.right")
                                .font(.caption.weight(.semibold))
                                .padding(7)
                                .background(.thinMaterial, in: Circle())
                                .padding(6)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Bereinigtes Foto im Anhang, prüfen")
                .accessibilityHint("Öffnet das Foto im Vollbild")

                Text("Prüfe das Foto. Ist noch ein Gesicht oder ein Kennzeichen erkennbar, entferne es.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Button(role: .destructive) {
                    confirmsPhotoRemoval = true
                } label: {
                    Label("Foto entfernen", systemImage: "trash")
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(GlassButtonStyle())
                .disabled(!canRemovePhoto)
                .confirmationDialog("Foto entfernen?", isPresented: $confirmsPhotoRemoval, titleVisibility: .visible) {
                    Button("Foto entfernen", role: .destructive, action: onRemovePhoto)
                    Button("Abbrechen", role: .cancel) {}
                } message: {
                    Text("Das Foto wird auf dem Server gelöscht. Die Meldung bleibt ohne Foto bestehen.")
                }
            }
        } else {
            Label("Kein Foto", systemImage: "photo.slash")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .accessibilityLabel("Die Meldung hat kein Foto")
        }
    }

    private var reviseButton: some View {
        // TODO: Revise (the user's addition to the letter) is the one function of the three that is not built yet, it says so in the chat.
        Button {
            onAction(.revise)
        } label: {
            Text("Überarbeiten")
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(GlassButtonStyle())
    }

    private var deleteButton: some View {
        Button(role: .destructive) {
            confirmsDeletion = true
        } label: {
            Label("Löschen", systemImage: "trash")
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(GlassButtonStyle())
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
