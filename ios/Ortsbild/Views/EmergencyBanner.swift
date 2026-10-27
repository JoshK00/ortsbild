//
//  EmergencyBanner.swift
//  Ortsbild
//

import SwiftUI

/// Emergency notice. No ticket is created.
struct EmergencyBanner: View {
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Das sieht nach einem Notfall aus", systemImage: "exclamationmark.triangle.fill")
                .font(.headline)
                .foregroundStyle(.red)
            Text("Bitte ruf sofort die Polizei (110) oder die Feuerwehr und den Rettungsdienst (112). Dafür legt Ortsbild keine Meldung an.")
                .font(.subheadline)
            HStack(spacing: 8) {
                callButton("110 anrufen", number: "110")
                callButton("112 anrufen", number: "112")
            }
        }
        .padding(16)
        .background(
            Color.red.opacity(0.12),
            in: RoundedRectangle(cornerRadius: 20, style: .continuous)
        )
    }

    private func callButton(_ title: LocalizedStringKey, number: String) -> some View {
        Button {
            if let url = URL(string: "tel:\(number)") {
                openURL(url)
            }
        } label: {
            Text(title)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .tint(.red)
    }
}

#Preview {
    EmergencyBanner()
        .padding()
}
