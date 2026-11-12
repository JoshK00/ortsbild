//
//  SanitizedCard.swift
//  Ortsbild
//

import SwiftUI

/// The report after the privacy layer: the proof that nothing personal left the app unchecked.
struct SanitizedCard: View {
    let result: SanitizedResult

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 10) {
                Label("Daten anonymisiert", systemImage: "checkmark.shield.fill")
                    .font(.headline)
                    .foregroundStyle(.green)

                if let photo = result.photo {
                    Image(uiImage: photo)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: 240, maxHeight: 280)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .accessibilityLabel("Anonymisiertes Foto")
                }

                if let text = result.text {
                    Text(text)
                }

                if !result.changes.isEmpty {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(result.changes, id: \.self) { change in
                            Label(change, systemImage: "eye.slash")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .padding(14)
            .glassCard(cornerRadius: 22)
            Spacer(minLength: 24)
        }
    }
}

#Preview {
    SanitizedCard(result: SanitizedResult(
        text: "Schlagloch vor dem Haus, <PHONE>",
        photo: nil,
        entries: [RedactionEntryDTO(kind: "face", count: 2), RedactionEntryDTO(kind: "exif", count: 1)]
    ))
    .padding()
}
