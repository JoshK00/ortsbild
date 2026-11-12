//
//  PhotoNoticeSheet.swift
//  Ortsbild
//

import SwiftUI

/// The rules for the photo, shown once before the first photo. Short on purpose: three points, one sentence of reason.
struct PhotoNoticeSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(PrivacyNotice.sheetTitle)
                .font(.title2.bold())
                .accessibilityAddTraits(.isHeader)

            ForEach(PrivacyNotice.sheetPoints, id: \.title) { point in
                HStack(alignment: .top, spacing: 14) {
                    Image(systemName: point.symbol)
                        .font(.title3)
                        .frame(width: 32)
                        .foregroundStyle(.tint)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(point.title).font(.headline)
                        Text(point.text).font(.subheadline).foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                }
            }

            Spacer(minLength: 0)

            Button {
                PhotoNoticeGate().markSeen()
                dismiss()
            } label: {
                Text(PrivacyNotice.sheetButton)
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
        .padding(24)
        .presentationDetents([.medium, .large])
        .interactiveDismissDisabled()
    }
}

#Preview {
    PhotoNoticeSheet()
}
