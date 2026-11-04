//
//  AccountSheet.swift
//  Ortsbild
//

import AuthenticationServices
import SwiftUI

/// Sheet over the chat: sign in with Apple, or account management once signed in.
struct AccountSheet: View {
    @Environment(AuthViewModel.self) private var auth
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.dismiss) private var dismiss
    @State private var confirmsDeletion = false

    // TODO: Move texts into a String Catalog (localization), German only for now

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                if auth.isSignedIn {
                    signedInContent
                } else {
                    signedOutContent
                }

                if let message = auth.errorMessage {
                    Text(message)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                }
            }
            .padding(24)
            .frame(maxHeight: .infinity, alignment: .top)
            .navigationTitle("Konto")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Fertig") { dismiss() }
                }
            }
            .overlay { if auth.isWorking { ProgressView() } }
            .disabled(auth.isWorking)
        }
        .presentationDetents([.medium, .large])
    }

    private var signedOutContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "person.crop.circle")
                .font(.system(size: 56))
                .foregroundStyle(.secondary)
            Text("Melde dich an, um Meldungen abzusenden.")
                .font(.headline)
                .multilineTextAlignment(.center)
            Text("Deine Apple-ID wird nicht an Behörden weitergegeben. Meldungen laufen unter einer zufälligen Kennung und werden nur bei Missbrauch dir zugeordnet.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            SignInWithAppleButton(.signIn) { request in
                auth.prepare(request)
            } onCompletion: { result in
                auth.handle(result)
            }
            .signInWithAppleButtonStyle(colorScheme == .dark ? .white : .black)
            .frame(height: 50)
        }
    }

    private var signedInContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 56))
                .foregroundStyle(.green)
            Text("Angemeldet")
                .font(.headline)
            if let reporter = auth.reporter {
                // Shortened pseudonymous ID, useful when contacting support.
                Text("Kennung: \(reporter.id.prefix(8))")
                    .font(.footnote.monospaced())
                    .foregroundStyle(.secondary)
            }
            // TODO: Show the user's own reports once `GET /v1/reports` (the list) exists

            Button("Abmelden") {
                auth.signOut()
            }
            .buttonStyle(.bordered)

            Button("Account löschen", role: .destructive) {
                confirmsDeletion = true
            }
            .confirmationDialog(
                "Account wirklich löschen?",
                isPresented: $confirmsDeletion,
                titleVisibility: .visible
            ) {
                Button("Account löschen", role: .destructive) {
                    auth.deleteAccount()
                }
            } message: {
                Text("Dein Konto und die zugehörigen Daten werden entfernt.")
            }
        }
    }
}

#Preview("Abgemeldet") {
    AccountSheet()
        .environment(AuthViewModel(service: MockAuthService()))
}
